"""
Unit tests for Paper Trading Mode.

Verifies that when PAPER_TRADING=true:
1. KrakenRuntime boots in paper trading mode without network access or live broker keys.
2. Market socket and price cache are connected and healthy with realistic mock quotes.
3. L1 questions (P&L, position filters, average prices, option chains) execute cleanly.
4. L2 order placement (drafting order cards and approving them) executes immediately against
   the simulated paper broker, filling market orders and creating trade journal entries.
"""
import asyncio
from datetime import date
from typing import Optional

import pytest

from app.config.settings import get_settings
from app.runtime import KrakenRuntime
from shared.contracts.orders import OrderDraft


class FakeLLM:
    def new_conversation(self, *args, **kwargs):
        raise AssertionError("LLM not invoked directly in paper broker test")


@pytest.fixture
def paper_runtime(tmp_path):
    settings = get_settings().model_copy(update={
        "PaperTrading": True,
        "InstrumentsCachePath": "data/instruments.csv.gz",
        "TradeApiRatePerSecond": 1000.0,
    })
    runtime = KrakenRuntime(settings, llm=FakeLLM())
    return runtime


@pytest.mark.asyncio
async def test_paper_runtime_startup_and_status(paper_runtime):
    await paper_runtime.start()
    try:
        status = paper_runtime.status()
        assert status["paper_trading"] is True
        assert status["broker_configured"] is True
        assert status["instruments_loaded"] > 1000
        assert status["instruments_fresh"] is True
        assert status["market_socket_connected"] is True
        assert status["market_feed_healthy"] is True
        assert status["orders_enabled"] is True
    finally:
        await paper_runtime.stop()


@pytest.mark.asyncio
async def test_paper_trading_l1_read_tools(paper_runtime):
    await paper_runtime.start()
    try:
        toolbox = paper_runtime.toolbox

        # 1. get_pnl
        pnl = await toolbox.get_pnl()
        assert "positions" in pnl
        assert "holdings" in pnl
        assert len(pnl["holdings"]) >= 5
        assert pnl["price_source"] == "021"

        # 2. filter_positions
        filt = await toolbox.filter_positions(threshold_pct=0.0, direction="down")
        assert "matches" in filt
        assert filt["price_source"] == "021"

        # 3. get_average_price
        avg_infy = await toolbox.get_average_price("INFY")
        assert avg_infy["held"] is True
        assert len(avg_infy["holding_average"]) > 0

        # 4. option_chain_near_atm
        chain = await toolbox.option_chain_near_atm("NIFTY", strikes_each_side=3)
        assert chain["underlying"] == "NIFTY"
        assert len(chain["rows"]) > 0
        atm_row = next((r for r in chain["rows"] if r["atm"]), None)
        assert atm_row is not None
        assert atm_row["ce"] is not None
        assert atm_row["pe"] is not None

    finally:
        await paper_runtime.stop()


@pytest.mark.asyncio
async def test_paper_trading_l2_order_draft_and_approve(paper_runtime):
    await paper_runtime.start()
    try:
        user_id = "test-paper-user"
        builder = paper_runtime.execution._check.__self__  # OrderBuilder

        # 1. Draft a Market Buy for Reliance
        draft = OrderDraft(
            action="BUY",
            symbol_query="RELIANCE",
            quantity=5,
            order_type="MARKET",
            product="CNC",
        )
        built = await builder.build_place(draft)
        assert built.display.symbol == "RELIANCE"
        assert built.display.quantity == 5

        # 2. Store proposal
        proposal = await paper_runtime.proposals.create(user_id, built)
        assert proposal.state == "PROPOSED"

        # 3. Approve proposal
        outcome = await paper_runtime.execution.approve(proposal.id, user_id, proposal.payload_hash)
        assert outcome.status == "sent"
        assert outcome.http_status == 200
        assert outcome.journal is not None
        assert outcome.journal.state == "ACKED"
        assert outcome.journal.order_id is not None

        # 4. Verify the paper broker recorded the order and fill
        orders = await paper_runtime.broker.get_orders()
        assert len(orders) >= 1
        placed = next(o for o in orders if str(o["orderId"]) == outcome.journal.order_id)
        assert placed["status"] == "Executed"
        assert placed["qtyTraded"] == 5

        # 5. Verify trades list contains the simulated fill
        trades = await paper_runtime.broker.get_trades()
        assert any(t["orderId"] == int(outcome.journal.order_id) for t in trades)

    finally:
        await paper_runtime.stop()
