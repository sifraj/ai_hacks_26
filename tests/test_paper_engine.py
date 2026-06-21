from datetime import datetime, timedelta, timezone

import pytest

import src.paper_trading.paper_engine as paper_engine_module
from src.paper_trading.paper_engine import PaperTradingEngine, INITIAL_CASH_USD, TAKER_FEE_PCT
from src.paper_trading.slippage_model import calculate_slippage
from src.schemas.trades import ClearedTrade


class FakeRedisClient:
    def __init__(self) -> None:
        self._state: dict | None = None

    async def get_portfolio_state(self) -> dict | None:
        return self._state

    async def set_portfolio_state(self, state: dict) -> None:
        self._state = state


class FakeTimescaleClient:
    def __init__(self, prices: dict[str, float], volume: float = 5_000_000.0) -> None:
        self.prices = prices
        self.volume = volume

    async def get_latest_price(self, asset: str) -> float | None:
        return self.prices.get(asset)

    async def get_ohlcv(self, asset: str, start: datetime, end: datetime, interval: str) -> list[dict]:
        return [{"volume": self.volume}]


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    monkeypatch.setattr("random.uniform", lambda a, b: 0.0)


@pytest.fixture
def fake_redis():
    return FakeRedisClient()


@pytest.fixture
def fake_timescale():
    return FakeTimescaleClient(prices={"BTC-USD": 65_000.0, "ETH-USD": 3_500.0})


@pytest.fixture
def engine(monkeypatch, fake_redis, fake_timescale):
    monkeypatch.setattr(paper_engine_module, "redis_client", fake_redis)
    monkeypatch.setattr(paper_engine_module, "timescale_client", fake_timescale)
    return PaperTradingEngine()


@pytest.mark.asyncio
async def test_initial_state_when_redis_empty(engine):
    state = await engine.get_portfolio_state()
    assert state.cash_usd == INITIAL_CASH_USD
    assert state.total_value_usd == INITIAL_CASH_USD
    assert state.positions == []
    assert state.kill_switch is False


@pytest.mark.asyncio
async def test_execute_paper_order_rejects_non_positive_size_explicitly(engine):
    # ClearedTrade.final_size_usd is schema-validated >0, but the engine itself
    # must not rely on a bare `assert` for this safety check (those vanish under
    # `python -O`) — construct a valid trade then mutate past validation to
    # confirm the engine's own explicit, non-strippable guard still fires.
    cleared = ClearedTrade(
        proposal_id="p1", asset="BTC-USD", side="BUY", order_type="MARKET",
        final_size_usd=1000.0, stop_loss_pct=0.02,
    )
    cleared.final_size_usd = -1000.0

    with pytest.raises(ValueError, match="final_size_usd must be positive"):
        await engine.execute_paper_order(cleared)


@pytest.mark.asyncio
async def test_execute_buy_creates_new_position(engine, fake_timescale):
    cleared = ClearedTrade(
        proposal_id="p1", asset="BTC-USD", side="BUY", order_type="MARKET",
        final_size_usd=2000.0, stop_loss_pct=0.02,
    )
    fill = await engine.execute_paper_order(cleared)

    expected_slippage = calculate_slippage(2000.0, fake_timescale.volume)
    expected_fill_price = 65_000.0 * (1 + expected_slippage)
    expected_fee = 2000.0 * TAKER_FEE_PCT

    assert fill.fill_price == pytest.approx(expected_fill_price)
    assert fill.fee_usd == pytest.approx(expected_fee)
    assert fill.side == "BUY"

    state = await engine.get_portfolio_state()
    assert len(state.positions) == 1
    position = state.positions[0]
    assert position.asset == "BTC-USD"
    assert position.size_usd == pytest.approx(2000.0)
    assert position.entry_price == pytest.approx(expected_fill_price)
    assert state.cash_usd == pytest.approx(INITIAL_CASH_USD - 2000.0 - expected_fee)


@pytest.mark.asyncio
async def test_second_buy_averages_entry_price(engine):
    cleared1 = ClearedTrade(
        proposal_id="p1", asset="BTC-USD", side="BUY", order_type="MARKET",
        final_size_usd=2000.0, stop_loss_pct=0.02,
    )
    fill1 = await engine.execute_paper_order(cleared1)

    cleared2 = ClearedTrade(
        proposal_id="p2", asset="BTC-USD", side="BUY", order_type="MARKET",
        final_size_usd=1000.0, stop_loss_pct=0.02,
    )
    fill2 = await engine.execute_paper_order(cleared2)

    state = await engine.get_portfolio_state()
    assert len(state.positions) == 1
    position = state.positions[0]

    qty1 = 2000.0 / fill1.fill_price
    qty2 = 1000.0 / fill2.fill_price
    expected_qty = qty1 + qty2
    # Quantity-weighted average cost = total dollars in / total units.
    expected_entry = 3000.0 / expected_qty
    assert position.quantity == pytest.approx(expected_qty)
    assert position.entry_price == pytest.approx(expected_entry)
    # size_usd is now marked to market at the latest fill price.
    assert position.size_usd == pytest.approx(expected_qty * fill2.fill_price)


@pytest.mark.asyncio
async def test_sell_reduces_position_and_increases_cash(engine):
    buy = ClearedTrade(
        proposal_id="p1", asset="BTC-USD", side="BUY", order_type="MARKET",
        final_size_usd=2000.0, stop_loss_pct=0.02,
    )
    buy_fill = await engine.execute_paper_order(buy)
    qty_bought = 2000.0 / buy_fill.fill_price
    state_after_buy = await engine.get_portfolio_state()
    cash_after_buy = state_after_buy.cash_usd

    sell = ClearedTrade(
        proposal_id="p2", asset="BTC-USD", side="SELL", order_type="MARKET",
        final_size_usd=500.0, stop_loss_pct=0.02,
    )
    sell_fill = await engine.execute_paper_order(sell)
    qty_sold = 500.0 / sell_fill.fill_price

    state = await engine.get_portfolio_state()
    assert len(state.positions) == 1
    remaining_qty = qty_bought - qty_sold
    assert state.positions[0].quantity == pytest.approx(remaining_qty)
    assert state.positions[0].size_usd == pytest.approx(remaining_qty * sell_fill.fill_price)
    # Proceeds from selling $500 of notional at the fill price == $500 (minus fee).
    assert state.cash_usd == pytest.approx(cash_after_buy + 500.0 - sell_fill.fee_usd)


@pytest.mark.asyncio
async def test_sell_realizes_pnl_into_cash(engine, fake_timescale):
    # The bug this guards against: selling a winner used to settle at cost basis,
    # destroying the realized gain. A doubled position must return its full value.
    buy = ClearedTrade(
        proposal_id="p1", asset="BTC-USD", side="BUY", order_type="MARKET",
        final_size_usd=10_000.0, stop_loss_pct=0.10,
    )
    buy_fill = await engine.execute_paper_order(buy)

    # Price doubles.
    doubled = buy_fill.fill_price * 2.0
    fake_timescale.prices["BTC-USD"] = doubled
    await engine.update_positions_with_prices({"BTC-USD": doubled})

    state_before_sell = await engine.get_portfolio_state()
    total_before = state_before_sell.total_value_usd

    # Sell the entire position at the doubled price.
    sell = ClearedTrade(
        proposal_id="p2", asset="BTC-USD", side="SELL", order_type="MARKET",
        final_size_usd=state_before_sell.positions[0].size_usd, stop_loss_pct=1.0,
    )
    sell_fill = await engine.execute_paper_order(sell)

    state = await engine.get_portfolio_state()
    assert state.positions == []
    # Realized P&L should be ~the full appreciation (qty * (sell_price - entry_price)).
    qty = 10_000.0 / buy_fill.fill_price
    expected_realized = qty * (sell_fill.fill_price - buy_fill.fill_price)
    assert state.realized_pnl_usd == pytest.approx(expected_realized, rel=1e-6)
    assert state.realized_pnl_usd > 9_000.0  # a doubled $10k position => ~+$10k
    # Total value should be preserved across the sale (only fees + sell-side
    # slippage lost), NOT collapse back toward cost basis (~$100k).
    assert state.total_value_usd == pytest.approx(total_before, rel=2e-3)
    assert state.total_value_usd > 109_000.0


@pytest.mark.asyncio
async def test_naked_sell_with_no_position_is_rejected(engine):
    sell = ClearedTrade(
        proposal_id="p1", asset="BTC-USD", side="SELL", order_type="MARKET",
        final_size_usd=1000.0, stop_loss_pct=1.0,
    )
    with pytest.raises(ValueError, match="no open position"):
        await engine.execute_paper_order(sell)

    state = await engine.get_portfolio_state()
    # Cash must be untouched — a naked sell must not fabricate money.
    assert state.cash_usd == pytest.approx(INITIAL_CASH_USD)


@pytest.mark.asyncio
async def test_sell_full_size_closes_position(engine):
    buy = ClearedTrade(
        proposal_id="p1", asset="BTC-USD", side="BUY", order_type="MARKET",
        final_size_usd=2000.0, stop_loss_pct=0.02,
    )
    await engine.execute_paper_order(buy)

    sell = ClearedTrade(
        proposal_id="p2", asset="BTC-USD", side="SELL", order_type="MARKET",
        final_size_usd=2000.0, stop_loss_pct=0.02,
    )
    await engine.execute_paper_order(sell)

    state = await engine.get_portfolio_state()
    assert state.positions == []


@pytest.mark.asyncio
async def test_update_positions_with_prices_recomputes_unrealized_pnl(engine):
    buy = ClearedTrade(
        proposal_id="p1", asset="BTC-USD", side="BUY", order_type="MARKET",
        final_size_usd=2000.0, stop_loss_pct=0.02,
    )
    await engine.execute_paper_order(buy)
    state_before = await engine.get_portfolio_state()
    entry_price = state_before.positions[0].entry_price

    new_price = entry_price * 1.10  # +10%
    state = await engine.update_positions_with_prices({"BTC-USD": new_price})

    position = state.positions[0]
    assert position.current_price == pytest.approx(new_price)
    assert position.unrealized_pnl_pct == pytest.approx(0.10)
    assert position.unrealized_pnl_usd == pytest.approx(2000.0 * 0.10)


@pytest.mark.asyncio
async def test_close_all_positions_empties_portfolio(engine):
    for asset, size in (("BTC-USD", 2000.0), ("ETH-USD", 1000.0)):
        cleared = ClearedTrade(
            proposal_id=f"p-{asset}", asset=asset, side="BUY", order_type="MARKET",
            final_size_usd=size, stop_loss_pct=0.02,
        )
        await engine.execute_paper_order(cleared)

    state_before = await engine.get_portfolio_state()
    assert len(state_before.positions) == 2

    fills = await engine.close_all_positions()
    assert len(fills) == 2

    state_after = await engine.get_portfolio_state()
    assert state_after.positions == []


@pytest.mark.asyncio
async def test_drawdown_reflected_after_losses(engine):
    buy = ClearedTrade(
        proposal_id="p1", asset="BTC-USD", side="BUY", order_type="MARKET",
        final_size_usd=20_000.0, stop_loss_pct=0.02,
    )
    await engine.execute_paper_order(buy)
    state_before = await engine.get_portfolio_state()
    entry_price = state_before.positions[0].entry_price
    session_high = state_before.session_high_usd

    crashed_price = entry_price * 0.5  # -50%
    state = await engine.update_positions_with_prices({"BTC-USD": crashed_price})

    assert state.total_value_usd < session_high
    assert state.drawdown_from_session_high_pct > 0.0
