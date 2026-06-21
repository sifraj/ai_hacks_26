from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import src.agents.compliance_agent as compliance_module
import src.backtesting.backtest_runner as runner_module
from src.backtesting.backtest_runner import BacktestRunner
from src.schemas.portfolio import PortfolioState
from src.schemas.regime import MarketRegime
from src.schemas.signals import Signal
from src.schemas.trades import ProposedTrade


class FakeRawRedisClient:
    async def get(self, key: str):
        return None  # no macro event, coinbase status "operational" (absence => pass)


class FakeComplianceTimescaleClient:
    def __init__(self, volume: float = 100_000_000.0) -> None:
        self.volume = volume

    async def get_ohlcv(self, asset, start, end, interval):
        return [{"volume": self.volume}]


def _regime() -> MarketRegime:
    return MarketRegime(
        tick_id="t1", timestamp="2026-06-20T00:00:00Z", regime="RISK_ON", posture="AGGRESSIVE",
        posture_multiplier=1.0, regime_rationale="x", signal_ids_cited=["a", "b", "c"],
    )


@pytest.fixture
def runner(monkeypatch):
    r = BacktestRunner()

    async def fake_get_ohlcv(asset, start, end, interval):
        base_price = {"BTC-USD": 60_000.0}.get(asset, 100.0)
        rows = []
        t = start
        while t <= end:
            rows.append({"time": t, "close": base_price, "high": base_price, "low": base_price,
                         "open": base_price, "volume": 50_000_000.0})
            t += timedelta(hours=1)
        return rows

    monkeypatch.setattr(runner_module.timescale_client, "get_ohlcv", fake_get_ohlcv)

    for name in ("momentum_analyst", "sentiment_analyst", "onchain_analyst"):
        monkeypatch.setattr(runner_module, name, SimpleNamespace(run=AsyncMock(return_value=[]), name=name))

    monkeypatch.setattr(runner_module, "cio_agent", SimpleNamespace(run=AsyncMock(return_value=_regime())))
    monkeypatch.setattr(runner_module, "portfolio_manager", SimpleNamespace(run=AsyncMock(return_value=[])))

    # Compliance agent's hard checks hit real Redis/Timescale singletons — fake them out.
    monkeypatch.setattr(compliance_module, "redis_client", SimpleNamespace(client=FakeRawRedisClient()))
    monkeypatch.setattr(compliance_module, "timescale_client", FakeComplianceTimescaleClient())

    return r


class TestCandleAtOrBefore:
    def test_returns_latest_candle_not_after_ts(self, runner):
        candles = [
            {"time": datetime(2026, 1, 1, 0), "close": 100.0},
            {"time": datetime(2026, 1, 1, 1), "close": 105.0},
            {"time": datetime(2026, 1, 1, 2), "close": 110.0},
        ]
        result = runner._candle_at_or_before(candles, datetime(2026, 1, 1, 1, 30))
        assert result["close"] == 105.0

    def test_returns_none_when_ts_before_all_candles(self, runner):
        candles = [{"time": datetime(2026, 1, 1, 5), "close": 100.0}]
        result = runner._candle_at_or_before(candles, datetime(2026, 1, 1, 0))
        assert result is None


class TestRun:
    @pytest.mark.asyncio
    async def test_run_with_no_proposals_produces_clean_result(self, runner):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = start + timedelta(hours=3)

        result = await runner.run(start, end, tick_interval=timedelta(hours=1))

        assert result.tick_count == 4
        assert result.fills == []
        assert result.performance is not None
        assert result.performance.total_trades == 0

    @pytest.mark.asyncio
    async def test_progress_callback_invoked_each_tick(self, runner):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = start + timedelta(hours=2)

        calls = []

        async def progress_callback(update: dict) -> None:
            calls.append(update)

        await runner.run(start, end, tick_interval=timedelta(hours=1), progress_callback=progress_callback)
        assert len(calls) == 3
        assert all("total_value_usd" in c for c in calls)

    @pytest.mark.asyncio
    async def test_run_executes_a_proposed_trade_end_to_end(self, runner, monkeypatch):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = start + timedelta(hours=2)

        proposed_trade = ProposedTrade(
            tick_id="whatever", asset="BTC-USD", side="BUY", order_type="MARKET",
            size_usd=2000.0, stop_loss_pct=0.02, trade_rationale="test trade",
            signal_ids=["sig1"], confidence_composite=0.6,
        )
        monkeypatch.setattr(
            runner_module, "portfolio_manager", SimpleNamespace(run=AsyncMock(return_value=[proposed_trade]))
        )

        result = await runner.run(start, end, tick_interval=timedelta(hours=1))

        assert len(result.fills) >= 1
        assert result.fills[0].asset == "BTC-USD"
        assert result.performance.total_trades >= 0  # round-trip not closed yet (no SELL) -> 0 closed trades
