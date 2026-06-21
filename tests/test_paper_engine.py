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
    expected_entry = (
        (fill1.fill_price * 2000.0) + (fill2.fill_price * 1000.0)
    ) / 3000.0
    assert position.size_usd == pytest.approx(3000.0)
    assert position.entry_price == pytest.approx(expected_entry)


@pytest.mark.asyncio
async def test_sell_reduces_position_and_increases_cash(engine):
    buy = ClearedTrade(
        proposal_id="p1", asset="BTC-USD", side="BUY", order_type="MARKET",
        final_size_usd=2000.0, stop_loss_pct=0.02,
    )
    await engine.execute_paper_order(buy)
    state_after_buy = await engine.get_portfolio_state()
    cash_after_buy = state_after_buy.cash_usd

    sell = ClearedTrade(
        proposal_id="p2", asset="BTC-USD", side="SELL", order_type="MARKET",
        final_size_usd=500.0, stop_loss_pct=0.02,
    )
    sell_fill = await engine.execute_paper_order(sell)

    state = await engine.get_portfolio_state()
    assert len(state.positions) == 1
    assert state.positions[0].size_usd == pytest.approx(1500.0)
    assert state.cash_usd == pytest.approx(cash_after_buy + 500.0 - sell_fill.fee_usd)


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
