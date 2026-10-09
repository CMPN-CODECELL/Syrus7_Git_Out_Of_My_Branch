"""
L1 read tools. Every number here comes from 021 (portfolio, prices, option chain) or from
Kraken's technicals engine on stored daily candles. The LLM only phrases the result.

Every result carries: an as-of time, the definition/basis used, stale flags, and any symbols
that were skipped and why. Failures are reported, never papered over with guesses.
"""
import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from domains.broker.domain.errors import BrokerError
from domains.broker.infrastructure.instruments import IST, InstrumentStore, expiry_to_date, today_ist
from domains.copilot.domain import portfolio_math as pm
from domains.historical.application.candle_service import CandleService, market_is_open
from domains.analytics.domain.services.technical_indicators_engine import TechnicalIndicatorsEngine
from domains.marketdata.domain.price_cache import PriceCache
from domains.marketdata.domain.symbol_map import analysis_key, yfinance_ticker
from shared.contracts.instruments import EXCHANGE_TO_WS_CODE, Instrument

logger = logging.getLogger(__name__)

QUOTE_WAIT_SECONDS = 2.5
CHAIN_WAIT_SECONDS = 3.0
DIVERGENCE_WARN_PCT = 1.0
SCREEN_MAX_LIVE_FETCHES = 8
_SAFE_TEXT = re.compile(r"[^A-Za-z0-9&\-. ]")


def safe_symbol(value: Any) -> str:
    """Third-party symbol text is data: restrict charset and length before it reaches the LLM."""
    return _SAFE_TEXT.sub("", str(value or ""))[:24]


def _now_ist() -> str:
    return datetime.now(timezone.utc).astimezone(IST).isoformat(timespec="seconds")


@dataclass
class MarketServices:
    broker: Any            # TradeRestClient (get_positions/get_holdings/get_trades)
    instruments: InstrumentStore
    socket: Any            # MarketSocketClient (ensure/wait_fresh)
    cache: PriceCache
    candles: CandleService


class ToolError(Exception):
    """A tool could not answer; the message is safe to show and to give the LLM."""


class ReadToolbox:
    def __init__(self, services: MarketServices):
        self.s = services

    # ── helpers ──────────────────────────────────────────────────
    def _resolve(self, text: str) -> Instrument:
        query = text.strip().upper()
        store = self.s.instruments
        if len(store) == 0:
            raise ToolError("The instrument list is not loaded yet, so symbols cannot be resolved.")
        inst = store.equity(query) or store.index(query)
        if inst is not None:
            return inst
        candidates = store.search(query)
        if not candidates:
            raise ToolError(f"No NSE/BSE instrument matches '{safe_symbol(query)}'.")
        if len({c.symbol for c in candidates}) == 1:
            return candidates[0]
        names = sorted({safe_symbol(c.symbol) for c in candidates})
        raise ToolError(f"'{safe_symbol(query)}' is ambiguous. Did you mean one of: {', '.join(names)}?")

    def _symbol_for(self, exchange: str, token: int) -> str:
        inst = self.s.instruments.get(exchange, token)
        return safe_symbol(inst.symbol) if inst else f"token {token}"

    async def _quotes(self, keys: list[tuple[int, int]], *, mode: str = "ltp", wait: float = QUOTE_WAIT_SECONDS) -> dict:
        """Live quotes for (ws_code, token) keys: {key: (ltp|None, stale, as_of|None)}."""
        out: dict = {}
        if not keys:
            return out
        try:
            accepted = await self.s.socket.ensure(keys, mode)
            if accepted:
                await self.s.socket.wait_fresh(accepted, timeout=wait)
        except Exception as exc:
            logger.warning("quote subscription failed: %s", exc)
        for key in keys:
            quote = self.s.cache.get(*key)
            stale = self.s.cache.is_stale(quote)
            out[key] = (
                quote.ltp if quote else None,
                stale,
                quote.updated_at.astimezone(IST).isoformat(timespec="seconds") if quote else None,
            )
        return out

    async def _portfolio(self, *, need_trades: bool = False) -> tuple[list[dict], list[dict], list[dict]]:
        try:
            if need_trades:
                positions, holdings, trades = await asyncio.gather(
                    self.s.broker.get_positions(), self.s.broker.get_holdings(), self.s.broker.get_trades()
                )
            else:
                positions, holdings = await asyncio.gather(self.s.broker.get_positions(), self.s.broker.get_holdings())
                trades = []
        except BrokerError as exc:
            raise ToolError(f"Could not fetch your portfolio from 021: {exc.user_message()}") from exc
        return positions, holdings, trades

    def _holding_instrument(self, holding: dict) -> Optional[Instrument]:
        isin = str(holding.get("isin") or "")
        return (self.s.instruments.equity_by_isin(isin) if isin else None) or self.s.instruments.equity(str(holding.get("symbol", "")))

    def _base(self, **extra) -> dict:
        return {"as_of": _now_ist(), "market_open": market_is_open(datetime.now(timezone.utc)), "price_source": "021", **extra}

    # ── tools ────────────────────────────────────────────────────
    async def get_pnl(self) -> dict:
        positions, holdings, trades = await self._portfolio(need_trades=True)
        realized = pm.realized_by_key(trades)

        pos_keys = {}
        for p in positions:
            code = EXCHANGE_TO_WS_CODE.get(str(p.get("exchange")))
            if code is not None:
                pos_keys[id(p)] = (code, int(p.get("token", 0) or 0))
        hold_insts = {id(h): self._holding_instrument(h) for h in holdings}
        keys = list(set(pos_keys.values()) | {(i.ws_code, i.token) for i in hold_insts.values() if i})
        quotes = await self._quotes(keys, mode="ltpc")

        pos_rows, stale_symbols = [], []
        total_unrealized = total_realized = 0
        unpriced = 0
        for p in positions:
            key = pos_keys.get(id(p))
            ltp, stale, _ = quotes.get(key, (None, True, None)) if key else (None, True, None)
            symbol = self._symbol_for(str(p.get("exchange")), int(p.get("token", 0) or 0))
            row = pm.position_pnl(p, ltp, realized.get((int(p.get("token", 0) or 0), str(p.get("product", ""))), 0), symbol, stale)
            if row.net_qty and row.unrealized is None:
                unpriced += 1
            if stale and row.net_qty:
                stale_symbols.append(symbol)
            total_unrealized += row.unrealized or 0
            total_realized += row.realized_today
            pos_rows.append({
                "symbol": symbol, "product": row.product, "net_qty": row.net_qty,
                "avg_price": pm.rupees(row.avg_price), "ltp": pm.rupees(row.ltp),
                "unrealized": pm.rupees(row.unrealized), "realized_today": pm.rupees(row.realized_today),
                "unrealized_paise": row.unrealized, "realized_today_paise": row.realized_today,
                "price_stale": row.price_stale,
            })

        hold_rows = []
        total_hold_pnl = total_day = 0
        for h in holdings:
            inst = hold_insts.get(id(h))
            ltp, stale, _ = quotes.get((inst.ws_code, inst.token), (None, True, None)) if inst else (None, True, None)
            row = pm.holding_pnl(h, ltp, stale)
            if stale:
                stale_symbols.append(safe_symbol(row.symbol))
            total_hold_pnl += row.pnl or 0
            total_day += row.day_change or 0
            hold_rows.append({
                "symbol": safe_symbol(row.symbol), "qty": row.qty, "avg_price": pm.rupees(row.avg_price),
                "ltp": pm.rupees(row.ltp), "pnl": pm.rupees(row.pnl), "day_change": pm.rupees(row.day_change),
                "pnl_paise": row.pnl, "day_change_paise": row.day_change, "price_stale": row.price_stale,
            })

        warnings = []
        if stale_symbols:
            warnings.append(f"Live 021 prices are stale or missing for: {', '.join(sorted(set(stale_symbols)))}. Totals may be off.")
        if unpriced:
            warnings.append(f"{unpriced} open position(s) have no live price and are excluded from unrealized P&L.")
        if any(int(p.get("carryForwardQuantity", 0) or 0) for p in positions):
            warnings.append("Some positions were carried forward; realized P&L covers only round trips made today.")

        return self._base(
            definition=pm.PNL_DEFINITION,
            positions=pos_rows,
            positions_total={"unrealized": pm.rupees(total_unrealized), "realized_today": pm.rupees(total_realized),
                             "total": pm.rupees(total_unrealized + total_realized)},
            holdings=hold_rows,
            holdings_total={"pnl": pm.rupees(total_hold_pnl), "day_change": pm.rupees(total_day)},
            empty=not positions and not holdings,
            warnings=warnings,
        )

    async def filter_positions(self, threshold_pct: float, direction: str = "down", scope: str = "both") -> dict:
        positions, holdings, _ = await self._portfolio()
        rows: list[dict] = []
        candidates: list[tuple[str, str, int, int, tuple[int, int] | None]] = []  # kind, symbol, qty, avg, key
        if scope in ("positions", "both"):
            for p in positions:
                qty = int(p.get("netQuantity", 0) or 0)
                if qty == 0:
                    continue
                code = EXCHANGE_TO_WS_CODE.get(str(p.get("exchange")))
                key = (code, int(p.get("token", 0) or 0)) if code is not None else None
                candidates.append(("position", self._symbol_for(str(p.get("exchange")), int(p.get("token", 0) or 0)), qty, int(p.get("netPrice", 0) or 0), key))
        if scope in ("holdings", "both"):
            for h in holdings:
                inst = self._holding_instrument(h)
                candidates.append(("holding", safe_symbol(h.get("symbol")), pm.holding_qty(h), int(h.get("price", 0) or 0), (inst.ws_code, inst.token) if inst else None))

        quotes = await self._quotes([c[4] for c in candidates if c[4]], mode="ltpc")
        unpriced = []
        for kind, symbol, qty, avg, key in candidates:
            ltp, stale, _ = quotes.get(key, (None, True, None)) if key else (None, True, None)
            move = pm.move_pct(avg, ltp, qty)
            if move is None:
                unpriced.append(symbol)
                continue
            hit = move <= -threshold_pct if direction == "down" else move >= threshold_pct
            if hit:
                rows.append({"kind": kind, "symbol": symbol, "qty": qty, "avg_price": pm.rupees(avg),
                             "ltp": pm.rupees(ltp), "move_pct": move, "price_stale": stale})
        rows.sort(key=lambda r: r["move_pct"])
        return self._base(
            basis=pm.MOVE_DEFINITION,
            threshold_pct=threshold_pct,
            direction=direction,
            scope=scope,
            matches=rows,
            result="none" if not rows else f"{len(rows)} match(es)",
            not_checked_no_price=sorted(set(unpriced)),
            checked=len(candidates) - len(unpriced),
        )

    async def get_average_price(self, symbol: str) -> dict:
        inst = self._resolve(symbol)
        positions, holdings, _ = await self._portfolio()
        holding_rows = []
        for h in holdings:
            h_inst = self._holding_instrument(h)
            if (h_inst and h_inst.symbol == inst.symbol) or str(h.get("symbol", "")).upper() == inst.symbol:
                holding_rows.append({"qty": pm.holding_qty(h), "avg_price": pm.rupees(int(h.get("price", 0) or 0)),
                                     "avg_price_paise": int(h.get("price", 0) or 0)})
        intraday_rows = []
        for p in positions:
            p_inst = self.s.instruments.get(str(p.get("exchange")), int(p.get("token", 0) or 0))
            if p_inst is None or (p_inst.symbol != inst.symbol or p_inst.is_derivative):
                continue
            intraday_rows.append({
                "product": p.get("product"), "net_qty": int(p.get("netQuantity", 0) or 0),
                "net_avg_price": pm.rupees(int(p.get("netPrice", 0) or 0)),
                "avg_buy_today": pm.rupees(int(p.get("buyPrice", 0) or 0)) if p.get("buyPrice") else None,
                "avg_sell_today": pm.rupees(int(p.get("sellPrice", 0) or 0)) if p.get("sellPrice") else None,
            })
        name = safe_symbol(inst.symbol)
        held = any(r["qty"] for r in holding_rows) or any(r["net_qty"] for r in intraday_rows)
        if held:
            note = "Holding average is your delivery cost; today's positions show today's intraday averages separately."
        elif intraday_rows:
            note = f"You do not currently hold {name}; you traded it today and the position is closed."
        else:
            note = f"You do not hold {name} and have no position in it today."
        return self._base(
            symbol=name,
            held=held,
            holding_average=holding_rows,
            today_positions=intraday_rows,
            note=note,
        )

    async def get_quote(self, symbol: str) -> dict:
        inst = self._resolve(symbol)
        key = (inst.ws_code, inst.token)
        quotes = await self._quotes([key], mode="ltpc")
        ltp, stale, as_of = quotes[key]
        quote = self.s.cache.get(*key)
        return self._base(
            symbol=safe_symbol(inst.symbol), exchange=inst.exchange, ltp=pm.rupees(ltp), ltp_paise=ltp,
            prev_close=pm.rupees(quote.prev_close) if quote else None, quote_time=as_of, stale=stale,
            note=None if ltp is not None else "021 has not sent a price for this instrument (socket down or no data).",
        )

    async def option_chain_near_atm(self, underlying: str = "NIFTY", strikes_each_side: int = 5) -> dict:
        store = self.s.instruments
        query = underlying.strip().upper()
        base = store.index(query) or store.equity(query)
        if base is None:
            base = self._resolve(query)
        today = today_ist()
        expiry = store.nearest_expiry(base.symbol, today=today)
        if expiry is None:
            raise ToolError(f"No listed options found for {safe_symbol(base.symbol)} on or after {today.isoformat()}.")
        options = [o for o in store.options(base.symbol) if o.expiry == expiry]

        spot_key = (base.ws_code, base.token)
        spot_quotes = await self._quotes([spot_key])
        spot, spot_stale, spot_time = spot_quotes[spot_key]
        if spot is None:
            raise ToolError(f"021 has not sent a price for {safe_symbol(base.symbol)}, so the at-the-money strike cannot be picked.")

        strikes = sorted({o.strike_price for o in options})
        atm = min(strikes, key=lambda s: abs(s - spot))
        idx = strikes.index(atm)
        window = strikes[max(0, idx - strikes_each_side): idx + strikes_each_side + 1]
        legs = {(o.strike_price, o.option_type): o for o in options if o.strike_price in window}
        keys = [(o.ws_code, o.token) for o in legs.values()]
        chain_quotes = await self._quotes(keys, mode="oc", wait=CHAIN_WAIT_SECONDS)

        rows, missing = [], 0
        for strike in window:
            row: dict = {"strike": pm.rupees(strike), "strike_paise": strike, "atm": strike == atm}
            for side, label in (("CALL", "ce"), ("PUT", "pe")):
                leg = legs.get((strike, side))
                if leg is None:
                    row[label] = None
                    continue
                quote = self.s.cache.get(leg.ws_code, leg.token)
                ltp, stale, _ = chain_quotes.get((leg.ws_code, leg.token), (None, True, None))
                if ltp is None:
                    missing += 1
                row[label] = {
                    "ltp": pm.rupees(ltp), "oi": quote.oi if quote else None,
                    "iv_pct": quote.iv if quote else None,
                    "delta": (quote.greeks or {}).get("delta") if quote else None,
                    "stale": stale,
                }
            rows.append(row)
        expiry_date = expiry_to_date(expiry, today=today)
        return self._base(
            underlying=safe_symbol(base.symbol),
            expiry=expiry_date.isoformat() if expiry_date else str(expiry),
            expiry_rule="nearest expiry on or after today",
            spot=pm.rupees(spot), spot_time=spot_time, spot_stale=spot_stale,
            atm_strike=pm.rupees(atm), lot_size=options[0].board_lot_quantity if options else None,
            rows=rows,
            legs_without_data=missing,
            source="021 option-chain (oc) mode",
        )

    async def _technicals_for(self, inst: Instrument, *, allow_live: bool = True) -> dict:
        ticker = yfinance_ticker(inst)
        series = await self.s.candles.get_daily(analysis_key(inst), ticker, allow_live=allow_live)
        closes = series.closes
        out: dict = {
            "symbol": safe_symbol(inst.symbol),
            "history_source": series.source,
            "bars": series.bar_count,
            "data_as_of": series.as_of.isoformat() if series.as_of else None,
            "history_stale": series.stale,
            "excluded_todays_partial_bar": series.excluded_partial_bar,
        }
        if series.error and not closes:
            out["error"] = series.error
            return out
        rsi = TechnicalIndicatorsEngine.calculate_rsi(closes, 14)
        out["rsi14"] = rsi
        out["rsi14_zone"] = None if rsi is None else ("oversold (<30)" if rsi < 30 else "overbought (>70)" if rsi > 70 else "neutral (30-70)")
        if rsi is None:
            out["rsi14_note"] = f"not enough data for RSI(14): need 15 daily closes, have {len(closes)}"
        last = closes[-1] if closes else None
        out["last_close"] = round(last, 2) if last is not None else None
        for period in (50, 200):
            if len(closes) >= period:
                sma = sum(closes[-period:]) / period
                out[f"sma{period}"] = round(sma, 2)
                out[f"close_vs_sma{period}"] = "above" if last >= sma else "below"
            else:
                out[f"sma{period}"] = None
                out[f"sma{period}_note"] = f"needs {period} daily closes, have {len(closes)}"
        macd = TechnicalIndicatorsEngine.calculate_macd(closes)
        if macd["macd"] is not None:
            out["macd"] = macd
            out["macd_state"] = "MACD line above signal line" if macd["histogram"] > 0 else "MACD line below signal line" if macd["histogram"] < 0 else "MACD line equal to signal line"
        else:
            out["macd"] = None
            out["macd_note"] = f"needs 35 daily closes, have {len(closes)}"
        out["_latest_analysis_price"] = series.latest_price
        return out

    async def get_technicals(self, symbol: str) -> dict:
        inst = self._resolve(symbol)
        data = await self._technicals_for(inst)
        yf_price = data.pop("_latest_analysis_price", None)
        divergence = None
        quotes = await self._quotes([(inst.ws_code, inst.token)])
        ltp, stale, _ = quotes[(inst.ws_code, inst.token)]
        if ltp is not None and yf_price:
            pct = round(abs(ltp / 100.0 - yf_price) / yf_price * 100.0, 2)
            divergence = {"021_ltp": pm.rupees(ltp), "analysis_price": round(yf_price, 2), "diff_pct": pct,
                          "warning": pct > DIVERGENCE_WARN_PCT}
        return self._base(
            **data,
            price_source_check=divergence or "021 price unavailable; analysis vs 021 divergence not checked",
            definitions={
                "rsi14": "RSI(14), Wilder smoothing, daily closes; oversold < 30, overbought > 70",
                "sma": "simple average of daily closes",
                "macd": "EMA12 - EMA26 of daily closes; signal = EMA9 of MACD",
                "history": "yfinance/NSE adjusted daily closes; may be delayed and can differ from 021 sandbox prices",
            },
            disclaimer="Indicator values only; not a recommendation to buy or sell.",
        )

    async def screen_portfolio(self, indicator: str = "RSI14", op: str = "below", value: float = 30.0) -> dict:
        positions, holdings, _ = await self._portfolio()
        universe: dict[tuple[str, int], tuple[Instrument, str]] = {}
        skipped: list[dict] = []
        for h in holdings:
            inst = self._holding_instrument(h)
            if inst is None:
                skipped.append({"symbol": safe_symbol(h.get("symbol")), "reason": "not found in 021 instrument list"})
                continue
            universe[(inst.exchange, inst.token)] = (inst, "holding")
        for p in positions:
            if int(p.get("netQuantity", 0) or 0) == 0:
                continue
            inst = self.s.instruments.get(str(p.get("exchange")), int(p.get("token", 0) or 0))
            if inst is None:
                skipped.append({"symbol": f"token {p.get('token')}", "reason": "not found in 021 instrument list"})
                continue
            note = "position"
            if inst.is_derivative:
                underlying = self.s.instruments.get(inst.underlying_exchange, inst.underlying_token) or self.s.instruments.index(inst.symbol) or self.s.instruments.equity(inst.symbol)
                if underlying is None:
                    skipped.append({"symbol": safe_symbol(inst.symbol), "reason": "F&O position whose underlying could not be resolved"})
                    continue
                inst, note = underlying, "F&O position (computed on underlying)"
            universe.setdefault((inst.exchange, inst.token), (inst, note))

        unresolved = len(skipped)
        semaphore = asyncio.Semaphore(4)
        live_budget = [SCREEN_MAX_LIVE_FETCHES]

        async def run(inst: Instrument, note: str) -> tuple[Instrument, str, dict]:
            async with semaphore:
                allow_live = live_budget[0] > 0
                data = await self._technicals_for(inst, allow_live=allow_live)
                if data.get("history_source") == "yfinance":
                    live_budget[0] -= 1
                return inst, note, data

        results = await asyncio.gather(*(run(i, n) for i, n in universe.values()))
        matches, others = [], []
        for inst, note, data in results:
            rsi = data.get("rsi14")
            if rsi is None:
                skipped.append({"symbol": safe_symbol(inst.symbol),
                                "reason": data.get("rsi14_note") or data.get("error") or "no RSI available",
                                "bars": data.get("bars")})
                continue
            row = {"symbol": safe_symbol(inst.symbol), "kind": note, "rsi14": rsi, "data_as_of": data.get("data_as_of"),
                   "history_stale": data.get("history_stale")}
            (matches if (rsi < value if op == "below" else rsi > value) else others).append(row)
        matches.sort(key=lambda r: r["rsi14"])
        return self._base(
            definition=f"RSI(14) on closed daily bars {op} {value:g} (Wilder smoothing; oversold < 30, overbought > 70)",
            universe_size=len(universe) + unresolved,
            matches=matches,
            result="none" if not matches else f"{len(matches)} match(es)",
            not_matching=others,
            skipped=skipped,
            history_source_note="Daily history from yfinance/NSE (may be delayed vs 021).",
            disclaimer="Indicator screen only; not a recommendation to buy or sell.",
        )
