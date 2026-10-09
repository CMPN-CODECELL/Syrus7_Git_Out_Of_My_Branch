"""
Order builder and validator: turns an LLM draft into an exact, validated 021 payload, or a
question / refusal. Deterministic: no LLM involvement after the draft's fields are extracted.

The same class re-checks a proposal right before it is sent (pre_send_check): limits, kill
switch, instrument freshness, price drift and the source quantity behind "sell half".
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from app.config.settings import Settings, get_settings
from domains.broker.domain.errors import BrokerError
from domains.broker.infrastructure.instruments import expiry_to_date, today_ist
from domains.copilot.application.read_tools import ReadToolbox, ToolError, safe_symbol
from domains.copilot.domain.parsing import ParseError, parse_price_paise, resolve_expiry, round_to_tick
from domains.copilot.domain.portfolio_math import rupees
from domains.historical.application.candle_service import market_is_open
from shared.contracts.instruments import EXCHANGE_TO_REQUEST, Instrument
from shared.contracts.orders import OrderChangeDraft, OrderDraft, OrderPayload, OrderProposal, ProposalDisplay

logger = logging.getLogger(__name__)

DRIFT_LIMIT = 0.005  # 0.5%
OPEN_ORDER_STATUSES = {"Received", "Placed", "Pending", "AcceptedForAMO"}


class DraftProblem(Exception):
    status = "refused"

    def __init__(self, message: str, options: Optional[list[str]] = None):
        super().__init__(message)
        self.message = message
        self.options = options or []


class NeedsClarification(DraftProblem):
    status = "needs_clarification"


class OrderRefused(DraftProblem):
    status = "refused"


@dataclass
class BuiltOrder:
    kind: str
    payload: OrderPayload
    display: ProposalDisplay
    reference_ltp: Optional[int]
    source_check: Optional[dict[str, Any]]
    target_order_id: Optional[str]
    draft: dict[str, Any]


@dataclass
class PreSendResult:
    ok: bool
    reason: Optional[str] = None
    requote: bool = False
    notices: list[str] = field(default_factory=list)


@dataclass
class _Source:
    kind: str          # HOLDING | POSITION
    product: str
    qty: int           # absolute quantity available to close
    token: int
    exchange: str


class OrderBuilder:
    def __init__(
        self,
        toolbox: ReadToolbox,
        *,
        settings: Callable[[], Settings] = get_settings,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        market_open: Callable[[datetime], bool] = market_is_open,
    ):
        self.t = toolbox
        self.s = toolbox.s
        self._settings = settings
        self._now = now
        self._market_open = market_open

    # ── shared helpers ───────────────────────────────────────────
    def _guard_kill_switch(self) -> None:
        if self._settings().TradingKillSwitch:
            raise OrderRefused("Order sending is paused on this server (kill switch is on). Nothing can be placed right now.")

    async def _quote(self, inst: Instrument) -> tuple[Optional[int], bool, Optional[datetime], Optional[int]]:
        key = (inst.ws_code, inst.token)
        quotes = await self.t.live_quotes([key], mode="ltpc")
        ltp, stale, _ = quotes[key]
        quote = self.s.cache.get(*key)
        return ltp, stale, (quote.updated_at if quote else None), (quote.prev_close if quote else None)

    async def _portfolio(self) -> tuple[list[dict], list[dict]]:
        try:
            positions = await self.s.broker.get_positions()
            holdings = await self.s.broker.get_holdings()
        except BrokerError as exc:
            raise OrderRefused(f"Could not read your portfolio from 021 ({exc.user_message()}), so the order can't be checked.") from exc
        return positions, holdings

    def _price(self, text: Optional[str], what: str, tick: int, side: str, notices: list[str]) -> int:
        try:
            paise = parse_price_paise(text)
        except ParseError as exc:
            raise NeedsClarification(f"{exc} Please give the {what} again.") from exc
        rounded = round_to_tick(paise, tick, side)
        if rounded != paise:
            notices.append(f"{what.capitalize()} {rupees(paise)} rounded to {rupees(rounded)} (tick size {rupees(tick)}, "
                           f"rounded {'down' if side == 'BUY' else 'up'} in your favour).")
        return rounded

    @staticmethod
    def _check_circuits(inst: Instrument, price: int, what: str) -> None:
        if price and inst.upper_circuit > 0 and not (inst.lower_circuit <= price <= inst.upper_circuit):
            raise OrderRefused(f"{what.capitalize()} {rupees(price)} is outside today's allowed range for {safe_symbol(inst.symbol)} "
                               f"({rupees(inst.lower_circuit)} to {rupees(inst.upper_circuit)}).")

    @staticmethod
    def _check_sl(side: str, ltp: Optional[int], trigger: int, price: int) -> None:
        if ltp is None:
            raise OrderRefused("No live 021 price, so the stop-loss trigger can't be validated. Try again in a moment.")
        if side == "BUY" and not (trigger > ltp and price >= trigger):
            raise OrderRefused(f"A buy stop-loss needs trigger above the current price ({rupees(ltp)}) and limit price at or above "
                               f"the trigger. You gave trigger {rupees(trigger)}, price {rupees(price)}.")
        if side == "SELL" and not (trigger < ltp and price <= trigger):
            raise OrderRefused(f"A sell stop-loss needs trigger below the current price ({rupees(ltp)}) and limit price at or below "
                               f"the trigger. You gave trigger {rupees(trigger)}, price {rupees(price)}.")

    def _check_limits(self, inst: Instrument, request_exchange: str, product: str, qty: int, value: int) -> None:
        cfg = self._settings()
        if request_exchange not in cfg.get_allowed_exchanges():
            raise OrderRefused(f"Orders on {request_exchange} are not enabled on this server.")
        if product not in cfg.get_allowed_products():
            raise OrderRefused(f"{product} orders are not enabled on this server.")
        if qty > cfg.MaxOrderQty:
            raise OrderRefused(f"Quantity {qty} exceeds this server's safety limit of {cfg.MaxOrderQty} per order.")
        if value > cfg.MaxOrderValuePaise:
            raise OrderRefused(f"Order value {rupees(value)} exceeds this server's safety limit of {rupees(cfg.MaxOrderValuePaise)} per order.")

    # ── instrument resolution ────────────────────────────────────
    def _resolve_equity(self, draft: OrderDraft) -> Instrument:
        store = self.s.instruments
        if draft.exchange_hint == "BSE":
            inst = store.equity(draft.symbol_query, prefer="BSEEQ")
            if inst is None or inst.exchange != "BSEEQ":
                raise OrderRefused(f"{safe_symbol(draft.symbol_query)} is not listed on BSE in today's instrument list.")
            return inst
        try:
            inst = self.t.resolve_instrument(draft.symbol_query)
        except ToolError as exc:
            msg = str(exc)
            raise (NeedsClarification(msg) if "ambiguous" in msg else OrderRefused(msg)) from exc
        if inst.is_index:
            raise OrderRefused(f"{safe_symbol(inst.symbol)} is an index; indices can't be traded directly. "
                               f"I can draft a {safe_symbol(inst.symbol)} future or option instead: tell me the strike, CE/PE and expiry.")
        return inst

    def _resolve_derivative(self, draft: OrderDraft, notices: list[str]) -> Instrument:
        store = self.s.instruments
        underlying = draft.symbol_query.strip().upper()
        contracts = store.options(underlying) if draft.instrument_kind == "OPTION" else store.futures(underlying)
        if not contracts:
            kind = "options" if draft.instrument_kind == "OPTION" else "futures"
            raise OrderRefused(f"No {kind} are listed for {safe_symbol(underlying)} in today's instrument list.")
        today = today_ist(self._now())
        by_date: dict = {}
        for c in contracts:
            d = expiry_to_date(c.expiry, today=today)
            if d is not None:
                by_date.setdefault(d, []).append(c)
        try:
            expiry_date = resolve_expiry(draft.expiry, sorted(by_date), today)
        except ParseError as exc:
            raise NeedsClarification(str(exc)) from exc
        candidates = by_date[expiry_date]
        notices.append(f"Expiry {expiry_date.isoformat()}" + (" (nearest on or after today)." if not draft.expiry else "."))
        if draft.instrument_kind == "FUTURE":
            return candidates[0]
        if draft.option_type is None:
            raise NeedsClarification("Call (CE) or put (PE)?", ["CE", "PE"])
        if not draft.strike:
            strikes = sorted({c.strike_price for c in candidates})
            raise NeedsClarification("Which strike?", [rupees(s) for s in strikes[:5]])
        try:
            strike = parse_price_paise(draft.strike)
        except ParseError as exc:
            raise NeedsClarification(f"{exc} Which strike?") from exc
        want = "CALL" if draft.option_type == "CE" else "PUT"
        match = [c for c in candidates if c.strike_price == strike and c.option_type == want]
        if not match:
            nearby = sorted({c.strike_price for c in candidates if c.option_type == want}, key=lambda s: abs(s - strike))[:5]
            raise NeedsClarification(f"No {safe_symbol(underlying)} {rupees(strike)} {draft.option_type} for {expiry_date.isoformat()}. "
                                     f"Nearest strikes:", [rupees(s) for s in sorted(nearby)])
        return match[0]

    # ── quantity ─────────────────────────────────────────────────
    def _sources(self, inst: Instrument, side: str, positions: list[dict], holdings: list[dict]) -> list[_Source]:
        sources: list[_Source] = []
        if side == "SELL" and not inst.is_derivative:
            for h in holdings:
                h_inst = self.t.holding_instrument(h)
                if h_inst is None or h_inst.symbol != inst.symbol:
                    continue
                available = int(h.get("freeQty", 0) or 0) + int(h.get("btstQty", 0) or 0) - int(h.get("sellQty", 0) or 0)
                if available > 0:
                    sources.append(_Source("HOLDING", "CNC", available, inst.token, inst.exchange))
        for p in positions:
            if str(p.get("exchange")) != inst.exchange or int(p.get("token", 0) or 0) != inst.token:
                continue
            net = int(p.get("netQuantity", 0) or 0)
            if (side == "SELL" and net > 0) or (side == "BUY" and net < 0):
                sources.append(_Source("POSITION", str(p.get("product")), abs(net), inst.token, inst.exchange))
        return sources

    def _pick_source(self, draft: OrderDraft, sources: list[_Source], inst: Instrument, side: str) -> _Source:
        name = safe_symbol(inst.symbol)
        if draft.source:
            sources = [s for s in sources if s.kind == draft.source]
        if draft.product:
            sources = [s for s in sources if s.product == draft.product]
        if not sources:
            what = "holding or long position" if side == "SELL" else "short position"
            raise OrderRefused(f"You have no {name} {what} to {'sell' if side == 'SELL' else 'buy back'}.")
        if len(sources) > 1:
            options = [f"{s.kind.lower()} of {s.qty} ({s.product})" for s in sources]
            raise NeedsClarification(f"You have more than one {name} position. Which one: " + " or ".join(options) + "?", options)
        return sources[0]

    # ── PLACE ────────────────────────────────────────────────────
    async def build_place(self, draft: OrderDraft) -> BuiltOrder:
        self._guard_kill_switch()
        if len(self.s.instruments) == 0:
            raise OrderRefused("The instrument list is not loaded yet, so orders can't be prepared.")
        notices: list[str] = []
        inst = self._resolve_equity(draft) if draft.instrument_kind == "EQUITY" else self._resolve_derivative(draft, notices)
        request_exchange = inst.request_exchange
        if request_exchange is None:
            raise OrderRefused(f"{safe_symbol(inst.symbol)} is not tradable.")
        side = draft.action
        lot = inst.board_lot_quantity if inst.is_derivative else 1
        name = safe_symbol(inst.symbol)

        ltp, stale, ltp_time, prev_close = await self._quote(inst)
        now = self._now()
        amo = not self._market_open(now)
        positions, holdings = await self._portfolio()
        sources = self._sources(inst, side, positions, holdings)

        # Quantity
        source_check: Optional[dict[str, Any]] = None
        closing_product: Optional[str] = None
        lots: Optional[int] = None
        if draft.quantity_mode in ("HALF", "ALL"):
            src = self._pick_source(draft, sources, inst, side)
            closing_product = src.product
            if draft.quantity_mode == "ALL":
                qty = src.qty
            else:
                qty = (src.qty // 2) // lot * lot
                notices.append(f"Half of your {src.qty} {name} ({src.kind.lower()}) = {qty}"
                               + (" (rounded down)." if src.qty % (2 * lot) else "."))
            if qty <= 0:
                raise OrderRefused(f"Half of {src.qty} {name} rounds down to 0, so there is nothing to {side.lower()}.")
            source_check = {"kind": src.kind, "token": src.token, "exchange": src.exchange, "product": src.product,
                            "side": side, "qty": src.qty}
        elif draft.quantity is None:
            unit = "lots" if inst.is_derivative else "shares"
            raise NeedsClarification(f"How many {unit} of {name}?")
        elif draft.quantity_mode == "LOTS":
            lots = draft.quantity
            qty = draft.quantity * lot
            if inst.is_derivative:
                notices.append(f"{lots} lot(s) x {lot} = {qty} units.")
        else:
            qty = draft.quantity
            if inst.is_derivative and qty % lot:
                raise OrderRefused(f"F&O quantity must be a multiple of the lot size {lot}; {qty} is not. "
                                   f"Did you mean {qty} lot(s) = {qty * lot} units?")
        if inst.is_derivative:
            lots = qty // lot
            if inst.freeze_quantity and qty > inst.freeze_quantity:
                raise OrderRefused(f"{qty} units exceeds the exchange freeze limit of {inst.freeze_quantity} per order for {name}. "
                                   f"Split it into smaller orders (each at most {inst.freeze_quantity // lot * lot} units).")

        # Product
        product = draft.product or closing_product
        if product is None:
            if draft.short:
                product = "INTRADAY"
            else:
                closing = [s for s in sources if s.kind == "POSITION" and s.qty >= qty]
                product = closing[0].product if closing and not any(s.kind == "HOLDING" for s in sources) else (
                    "NRML" if inst.is_derivative else "CNC")
        if product == "CNC" and inst.is_derivative:
            raise OrderRefused("CNC is delivery for cash shares only; F&O uses NRML (carry forward) or INTRADAY.")
        if product == "NRML" and not inst.is_derivative:
            raise OrderRefused("NRML is for F&O only; cash shares use CNC (delivery) or INTRADAY.")

        # Selling: never sell what you don't have unless the trader explicitly asked to short
        if side == "SELL" and draft.quantity_mode not in ("HALF", "ALL"):
            closable = sum(s.qty for s in sources if s.product == product)
            if product == "CNC":
                if closable < qty:
                    raise OrderRefused(f"You can sell at most {closable} {name} from delivery holdings; you asked for {qty}. "
                                       f"To short-sell intraday, say 'short' explicitly.")
                source_check = {"kind": "AVAILABLE", "token": inst.token, "exchange": inst.exchange, "product": product,
                                "side": side, "qty": closable, "needed": qty}
            elif closable < qty and not draft.short:
                raise OrderRefused(f"This would open a short position of {qty - closable} {name}. "
                                   f"If you mean to short, say 'short' explicitly.")
        if draft.short and side == "SELL":
            notices.append("Short sale: INTRADAY positions are squared off automatically before market close.")

        # Price
        order_type = draft.order_type
        if order_type == "MARKET" and draft.limit_price:
            order_type = "LIMIT"
        price, trigger = 0, None
        if order_type in ("LIMIT", "SL"):
            if not draft.limit_price:
                raise NeedsClarification(f"At what limit price{' (the SL order also needs one)' if order_type == 'SL' else ''}?")
            price = self._price(draft.limit_price, "limit price", inst.ticksize, side, notices)
            self._check_circuits(inst, price, "limit price")
        if order_type == "SL":
            if not draft.trigger_price:
                raise NeedsClarification("At what trigger price?")
            trigger = self._price(draft.trigger_price, "trigger price", inst.ticksize, side, notices)
            self._check_circuits(inst, trigger, "trigger price")
            self._check_sl(side, ltp, trigger, price)

        reference = price or ltp or (prev_close if amo else None)
        if reference is None:
            raise OrderRefused(f"021 has no live price for {name} right now, so a market order can't be sized safely. "
                               f"Try again in a moment or give a limit price.")
        if ltp is not None and stale:
            notices.append("The 021 price may be stale; it will be re-checked when you approve.")
        if amo:
            notices.append("Market is closed: this is an after-market order (AMO), queued for the next market open.")
        value = reference * qty
        self._check_limits(inst, request_exchange, product, qty, value)

        payload = OrderPayload(
            exchange=request_exchange, token=inst.token, qty=qty if side == "BUY" else -qty, price=price,
            book="SL" if order_type == "SL" else "RL", product=product, validity=draft.validity, trigger=trigger,
            amo=True if amo else None,
        )
        display = ProposalDisplay(
            symbol=name, exchange=request_exchange, side=side, quantity=qty, lots=lots,
            lot_size=lot if inst.is_derivative else None, order_type=order_type, product=product, validity=draft.validity,
            limit_price_paise=price or None, trigger_price_paise=trigger, amo=amo, action="PLACE",
            reference_ltp_paise=ltp if ltp is not None else prev_close, reference_ltp_as_of=ltp_time,
            estimated_value_paise=value, notices=notices,
        )
        return BuiltOrder("PLACE", payload, display, ltp if not amo else None, source_check, None, draft.model_dump())

    # ── MODIFY / CANCEL ──────────────────────────────────────────
    async def _find_open_order(self, draft: OrderChangeDraft, verb: str, verb_past: str) -> tuple[dict, Instrument]:
        try:
            orders = await self.s.broker.get_orders()
        except BrokerError as exc:
            raise OrderRefused(f"Could not read your orders from 021 ({exc.user_message()}).") from exc

        def inst_of(o: dict) -> Optional[Instrument]:
            return self.s.instruments.get(str(o.get("exchange")), int(o.get("token", 0) or 0))

        if draft.order_id:
            matches = [o for o in orders if str(o.get("orderId")) == draft.order_id]
        else:
            query = draft.symbol_query.strip().upper()
            try:
                wanted = self.t.resolve_instrument(query).symbol
            except ToolError:
                wanted = query
            matches = [o for o in orders if (i := inst_of(o)) is not None and i.symbol == wanted]
            if draft.side:
                matches = [o for o in matches if (int(o.get("qtyRemaining", 0) or 0) > 0) == (draft.side == "BUY")]
            if draft.stop_loss_only:
                matches = [o for o in matches if o.get("book") == "SL"]
        open_ = [o for o in matches if o.get("status") in OPEN_ORDER_STATUSES]
        if not open_:
            if matches:
                last = matches[0]
                raise OrderRefused(f"Only pending orders can be {verb_past}. Order #{last.get('orderId')} is {last.get('status')} "
                                   f"(filled {last.get('qtyTraded', 0)}).")
            raise OrderRefused(f"I couldn't find an open order for {safe_symbol(draft.symbol_query)} to {verb}.")
        if len(open_) > 1:
            options = [self._describe(o, inst_of(o)) for o in open_]
            raise NeedsClarification(f"You have {len(open_)} open orders that match. Which one?", options)
        order = open_[0]
        inst = inst_of(order)
        if inst is None:
            raise OrderRefused(f"Order #{order.get('orderId')} is for an instrument missing from today's instrument list.")
        return order, inst

    @staticmethod
    def _describe(o: dict, inst: Optional[Instrument]) -> str:
        rem = int(o.get("qtyRemaining", 0) or 0)
        side = "BUY" if rem > 0 else "SELL"
        price = int(o.get("price", 0) or 0)
        trig = int(o.get("triggerPrice", 0) or 0)
        what = f"{rupees(price)}" if price else "market"
        if o.get("book") == "SL":
            what += f", trigger {rupees(trig)}"
        return f"#{o.get('orderId')} {side} {abs(rem)} {safe_symbol(inst.symbol) if inst else ''} at {what} ({o.get('status')})"

    def _current_payload(self, order: dict) -> OrderPayload:
        rem = int(order.get("qtyRemaining", 0) or 0)
        book = "SL" if order.get("book") == "SL" else "RL"
        return OrderPayload(
            exchange=EXCHANGE_TO_REQUEST[str(order.get("exchange"))], token=int(order["token"]), qty=rem,
            price=int(order.get("price", 0) or 0), book=book, product=str(order.get("product")),
            validity=str(order.get("validity") or "Day"),
            trigger=int(order.get("triggerPrice", 0) or 0) or None if book == "SL" else None,
            amo=True if order.get("amo") else None,
        )

    async def build_modify(self, draft: OrderChangeDraft) -> BuiltOrder:
        self._guard_kill_switch()
        order, inst = await self._find_open_order(draft, "modify", "modified")
        if int(order.get("qtyTraded", 0) or 0) > 0:
            raise OrderRefused(f"Order #{order.get('orderId')} is partially filled ({order.get('qtyTraded')} done). "
                               f"Cancel the rest and place a new order instead.")
        current = self._current_payload(order)
        side = "BUY" if current.qty > 0 else "SELL"
        notices: list[str] = []
        price, trigger, qty = current.price, current.trigger, abs(current.qty)
        if draft.new_limit_price:
            price = self._price(draft.new_limit_price, "limit price", inst.ticksize, side, notices)
            self._check_circuits(inst, price, "limit price")
            notices.append(f"Limit price {rupees(current.price) if current.price else 'market'} -> {rupees(price)}.")
        if draft.new_trigger_price:
            if current.book != "SL":
                raise OrderRefused(f"Order #{order.get('orderId')} is not a stop-loss order, so it has no trigger to move.")
            trigger = self._price(draft.new_trigger_price, "trigger price", inst.ticksize, side, notices)
            self._check_circuits(inst, trigger, "trigger price")
            notices.append(f"Trigger {rupees(current.trigger)} -> {rupees(trigger)}.")
            if current.price and not draft.new_limit_price:
                # Keep a stop-loss limit valid relative to its new trigger.
                if (side == "SELL" and current.price > trigger) or (side == "BUY" and current.price < trigger):
                    price = trigger
                    notices.append(f"Limit price moved to {rupees(price)} so it stays valid for the new trigger.")
        if draft.new_quantity:
            lot = inst.board_lot_quantity if inst.is_derivative else 1
            if draft.new_quantity % lot:
                raise OrderRefused(f"Quantity must be a multiple of the lot size {lot}.")
            notices.append(f"Quantity {qty} -> {draft.new_quantity}.")
            qty = draft.new_quantity
        if (price, trigger, qty) == (current.price, current.trigger, abs(current.qty)):
            raise NeedsClarification("What should change: the limit price, the trigger price, or the quantity?")
        ltp, stale, ltp_time, _ = await self._quote(inst)
        if current.book == "SL":
            self._check_sl(side, ltp, trigger, price)
        reference = price or ltp
        self._check_limits(inst, current.exchange, current.product, qty, (reference or 0) * qty)
        payload = current.model_copy(update={"price": price, "trigger": trigger, "qty": qty if side == "BUY" else -qty})
        payload = OrderPayload.model_validate(payload.model_dump())
        order_id = str(order.get("orderId"))
        display = ProposalDisplay(
            symbol=safe_symbol(inst.symbol), exchange=current.exchange, side=side, quantity=qty,
            order_type="SL" if current.book == "SL" else ("LIMIT" if price else "MARKET"), product=current.product,
            validity=current.validity, limit_price_paise=price or None, trigger_price_paise=trigger,
            amo=bool(current.amo), action="MODIFY", target_order_id=order_id, reference_ltp_paise=ltp,
            reference_ltp_as_of=ltp_time, estimated_value_paise=(reference or 0) * qty or None, notices=notices,
        )
        check = {"kind": "ORDER_OPEN", "order_id": order_id}
        return BuiltOrder("MODIFY", payload, display, ltp, check, order_id, draft.model_dump())

    async def build_cancel(self, draft: OrderChangeDraft) -> BuiltOrder:
        order, inst = await self._find_open_order(draft, "cancel", "cancelled")
        current = self._current_payload(order)
        side = "BUY" if current.qty > 0 else "SELL"
        order_id = str(order.get("orderId"))
        filled = int(order.get("qtyTraded", 0) or 0)
        notices = [f"Cancels order #{order_id}" + (f"; {filled} already filled stay filled." if filled else ".")]
        display = ProposalDisplay(
            symbol=safe_symbol(inst.symbol), exchange=current.exchange, side=side, quantity=abs(current.qty),
            order_type="SL" if current.book == "SL" else ("LIMIT" if current.price else "MARKET"), product=current.product,
            validity=current.validity, limit_price_paise=current.price or None, trigger_price_paise=current.trigger,
            amo=bool(current.amo), action="CANCEL", target_order_id=order_id, notices=notices,
        )
        return BuiltOrder("CANCEL", current, display, None, {"kind": "ORDER_OPEN", "order_id": order_id}, order_id, draft.model_dump())

    # ── approval-time re-check ───────────────────────────────────
    async def pre_send_check(self, proposal: OrderProposal) -> PreSendResult:
        cfg = self._settings()
        if cfg.TradingKillSwitch:
            return PreSendResult(False, "Order sending is paused on this server (kill switch is on).")
        if not self.s.instruments.is_fresh(self._now()):
            return PreSendResult(False, "The instrument list is out of date; orders are blocked until today's list is loaded.")
        payload = proposal.payload
        inst = next((i for ex, req in EXCHANGE_TO_REQUEST.items() if req == payload.exchange
                     for i in [self.s.instruments.get(ex, payload.token)] if i is not None), None)
        if inst is None:
            return PreSendResult(False, "The instrument is no longer in today's instrument list.")
        if proposal.kind != "CANCEL":
            if payload.exchange not in cfg.get_allowed_exchanges() or payload.product not in cfg.get_allowed_products():
                return PreSendResult(False, "This exchange/product is no longer enabled on this server.")
            if abs(payload.qty) > cfg.MaxOrderQty:
                return PreSendResult(False, f"Quantity exceeds the safety limit of {cfg.MaxOrderQty}.")

        # Price drift since the card was shown
        if proposal.kind in ("PLACE", "MODIFY") and proposal.reference_ltp and not payload.amo:
            ltp, stale, _, _ = await self._quote(inst)
            if ltp is None or stale:
                return PreSendResult(False, "No fresh 021 price right now, so the price can't be re-confirmed. Try again in a moment.")
            drift = abs(ltp - proposal.reference_ltp) / proposal.reference_ltp
            if drift > DRIFT_LIMIT:
                return PreSendResult(False, f"The price moved {drift * 100:.2f}% (from {rupees(proposal.reference_ltp)} to {rupees(ltp)}) "
                                            f"since the card was shown.", requote=True)
            reference = payload.price or ltp
            if reference * abs(payload.qty) > cfg.MaxOrderValuePaise:
                return PreSendResult(False, f"Order value now exceeds the safety limit of {rupees(cfg.MaxOrderValuePaise)}.")

        # The quantity the order was based on must still be there
        check = proposal.source_check or {}
        kind = check.get("kind")
        try:
            if kind in ("HOLDING", "POSITION", "AVAILABLE"):
                positions, holdings = await self._portfolio()
                sources = [s for s in self._sources(inst, check["side"], positions, holdings)
                           if (kind == "AVAILABLE" and s.product == check["product"]) or s.kind == kind and s.product == check["product"]]
                current = sum(s.qty for s in sources)
                if kind == "AVAILABLE" and current < check["needed"]:
                    return PreSendResult(False, f"You now have {current} available to sell, less than the {check['needed']} on the card.")
                if kind in ("HOLDING", "POSITION") and current != check["qty"]:
                    return PreSendResult(False, f"Your {kind.lower()} changed from {check['qty']} to {current} since the card was "
                                                f"shown, so the quantity is no longer right. Ask again for a fresh card.")
            elif kind == "ORDER_OPEN":
                order = await self.s.broker.get_order(check["order_id"])
                if order is None:
                    return PreSendResult(False, f"Order #{check['order_id']} no longer exists.")
                if order.get("status") not in OPEN_ORDER_STATUSES:
                    return PreSendResult(False, f"Order #{check['order_id']} is now {order.get('status')} "
                                                f"(filled {order.get('qtyTraded', 0)}); only pending orders can be changed.")
        except (BrokerError, OrderRefused) as exc:
            return PreSendResult(False, f"Could not re-check your account before sending: {exc.message}")
        return PreSendResult(True)
