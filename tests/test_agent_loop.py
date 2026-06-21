from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import src.harness.agent_loop as agent_loop_module
from src.harness.agent_loop import run_tick
from src.schemas.portfolio import PortfolioState
from src.schemas.regime import MarketRegime


def _state(kill_switch: bool = False) -> PortfolioState:
    return PortfolioState(
        timestamp="2026-06-20T00:00:00Z",
        total_value_usd=100_000.0,
        cash_usd=100_000.0,
        positions=[],
        session_high_usd=100_000.0,
        daily_pnl_usd=0.0,
        daily_pnl_pct=0.0,
        drawdown_from_session_high_pct=0.0,
        kill_switch=kill_switch,
    )


def _regime() -> MarketRegime:
    return MarketRegime(
        tick_id="t1",
        timestamp="2026-06-20T00:00:00Z",
        regime="RANGING",
        posture="DEFENSIVE",
        posture_multiplier=0.3,
        regime_rationale="test",
        signal_ids_cited=["a", "b", "c"],
    )


@pytest.fixture
def mock_pipeline(monkeypatch):
    fakes = SimpleNamespace(
        market_ingestor=SimpleNamespace(run=AsyncMock()),
        sentiment_ingestor=SimpleNamespace(run=AsyncMock()),
        onchain_ingestor=SimpleNamespace(run=AsyncMock()),
        momentum_analyst=SimpleNamespace(run=AsyncMock(return_value=[])),
        sentiment_analyst=SimpleNamespace(run=AsyncMock(return_value=[])),
        onchain_analyst=SimpleNamespace(run=AsyncMock(return_value=[])),
        cio_agent=SimpleNamespace(run=AsyncMock(return_value=_regime())),
        portfolio_manager=SimpleNamespace(run=AsyncMock(return_value=[])),
        risk_manager=SimpleNamespace(run=AsyncMock(return_value=[])),
        compliance_agent=SimpleNamespace(run=AsyncMock(return_value=[])),
        execution_agent=SimpleNamespace(run=AsyncMock(return_value=[])),
        log_tick_summary=AsyncMock(),
        broadcast_tick_update=AsyncMock(),
    )

    for attr_name in vars(fakes):
        monkeypatch.setattr(agent_loop_module, attr_name, getattr(fakes, attr_name))

    state_manager_mock = SimpleNamespace(
        get_state=AsyncMock(return_value=_state(kill_switch=False)),
        process_fills=AsyncMock(return_value=_state(kill_switch=False)),
    )
    monkeypatch.setattr(agent_loop_module, "state_manager", state_manager_mock)

    return fakes, state_manager_mock


@pytest.mark.asyncio
async def test_run_tick_skips_when_kill_switch_active(mock_pipeline, monkeypatch):
    fakes, state_manager_mock = mock_pipeline
    state_manager_mock.get_state = AsyncMock(return_value=_state(kill_switch=True))
    monkeypatch.setattr(agent_loop_module, "state_manager", state_manager_mock)

    await run_tick("tick-1")

    fakes.market_ingestor.run.assert_not_called()
    fakes.cio_agent.run.assert_not_called()


@pytest.mark.asyncio
async def test_run_tick_happy_path_runs_all_phases(mock_pipeline):
    fakes, state_manager_mock = mock_pipeline

    await run_tick("tick-2")

    fakes.market_ingestor.run.assert_awaited_once()
    fakes.sentiment_ingestor.run.assert_awaited_once()
    fakes.onchain_ingestor.run.assert_awaited_once()
    fakes.momentum_analyst.run.assert_awaited_once_with("tick-2")
    fakes.cio_agent.run.assert_awaited_once()
    fakes.portfolio_manager.run.assert_awaited_once()
    fakes.risk_manager.run.assert_awaited_once()
    fakes.compliance_agent.run.assert_awaited_once()
    fakes.execution_agent.run.assert_awaited_once()
    state_manager_mock.process_fills.assert_awaited_once()
    fakes.log_tick_summary.assert_awaited_once()
    fakes.broadcast_tick_update.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_tick_catches_exception_without_raising(mock_pipeline):
    fakes, _ = mock_pipeline
    fakes.market_ingestor.run = AsyncMock(side_effect=RuntimeError("ingestor exploded"))

    # Should not raise.
    await run_tick("tick-3")

    fakes.cio_agent.run.assert_not_called()


@pytest.mark.asyncio
async def test_run_tick_logs_latency_warning_when_slow(mock_pipeline, monkeypatch):
    fakes, _ = mock_pipeline

    events = []

    class FakeLogger:
        def info(self, msg, **kwargs):
            events.append((msg, kwargs))

        def warning(self, msg, **kwargs):
            events.append((msg, kwargs))

        def error(self, msg, **kwargs):
            events.append((msg, kwargs))

    monkeypatch.setattr(agent_loop_module, "logger", FakeLogger())

    call_count = {"n": 0}
    real_monotonic = agent_loop_module.time.monotonic

    def fake_monotonic():
        call_count["n"] += 1
        return 0.0 if call_count["n"] == 1 else 100.0

    monkeypatch.setattr(agent_loop_module.time, "monotonic", fake_monotonic)

    await run_tick("tick-4")

    assert any(e[0] == "tick_latency_exceeded" for e in events)


@pytest.mark.asyncio
async def test_run_tick_skipped_logs_warning(mock_pipeline, monkeypatch):
    fakes, state_manager_mock = mock_pipeline
    state_manager_mock.get_state = AsyncMock(return_value=_state(kill_switch=True))
    monkeypatch.setattr(agent_loop_module, "state_manager", state_manager_mock)

    events = []

    class FakeLogger:
        def info(self, msg, **kwargs):
            events.append((msg, kwargs))

        def warning(self, msg, **kwargs):
            events.append((msg, kwargs))

        def error(self, msg, **kwargs):
            events.append((msg, kwargs))

    monkeypatch.setattr(agent_loop_module, "logger", FakeLogger())

    await run_tick("tick-5")

    assert any(e[0] == "tick_skipped" for e in events)
