from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import src.harness.agent_loop as agent_loop_module
from src.harness.agent_loop import _safe_broadcast, run_tick
from src.schemas.portfolio import PortfolioState
from src.schemas.regime import MarketRegime
from src.schemas.signals import Signal
from src.schemas.trades import ClearedTrade, Fill, ProposedTrade, RiskDecision


def _state(kill_switch: bool = False) -> PortfolioState:
    return PortfolioState(
        timestamp="2026-06-20T00:00:00Z", total_value_usd=100_000.0, cash_usd=100_000.0,
        positions=[], session_high_usd=100_000.0, daily_pnl_usd=0.0, daily_pnl_pct=0.0,
        drawdown_from_session_high_pct=0.0, kill_switch=kill_switch,
    )


def _regime() -> MarketRegime:
    return MarketRegime(
        tick_id="t1", timestamp="2026-06-20T00:00:00Z", regime="RISK_ON", posture="AGGRESSIVE",
        posture_multiplier=1.0, regime_rationale="test", signal_ids_cited=["a", "b", "c"],
    )


def _signal() -> Signal:
    return Signal(
        timestamp="2026-06-20T00:00:00Z", source_agent="momentum_analyst", asset="BTC-USD",
        direction="LONG", confidence_score=0.6, horizon_hours=4,
    )


def _proposed() -> ProposedTrade:
    return ProposedTrade(
        proposal_id="p1", tick_id="tick-x", asset="BTC-USD", side="BUY", order_type="MARKET",
        size_usd=2000.0, stop_loss_pct=0.02, trade_rationale="test", signal_ids=["s1"],
        confidence_composite=0.6,
    )


def _decision(status="APPROVED") -> RiskDecision:
    kwargs = dict(proposal_id="p1", status=status, risk_rationale="ok", rules_checked=["RISK_006"])
    if status != "REJECTED":
        kwargs["approved_size_usd"] = 2000.0
    if status in ("REJECTED", "RESIZED"):
        kwargs["rules_violated"] = ["RISK_006"]
    return RiskDecision(**kwargs)


def _cleared() -> ClearedTrade:
    return ClearedTrade(
        cleared_id="c1", proposal_id="p1", asset="BTC-USD", side="BUY", order_type="MARKET",
        final_size_usd=2000.0, stop_loss_pct=0.02, compliance_checks_passed=["RULE_001"],
    )


def _fill() -> Fill:
    return Fill(
        cleared_id="c1", asset="BTC-USD", side="BUY", filled_size_usd=2000.0,
        fill_price=65000.0, fee_usd=12.0, timestamp="2026-06-20T00:00:00Z",
    )


@pytest.fixture
def mock_pipeline(monkeypatch):
    fakes = SimpleNamespace(
        market_ingestor=SimpleNamespace(run=AsyncMock()),
        sentiment_ingestor=SimpleNamespace(run=AsyncMock()),
        onchain_ingestor=SimpleNamespace(run=AsyncMock()),
        momentum_analyst=SimpleNamespace(run=AsyncMock(return_value=[_signal()])),
        sentiment_analyst=SimpleNamespace(run=AsyncMock(return_value=[])),
        onchain_analyst=SimpleNamespace(run=AsyncMock(return_value=[])),
        cio_agent=SimpleNamespace(run=AsyncMock(return_value=_regime())),
        portfolio_manager=SimpleNamespace(run=AsyncMock(return_value=[_proposed()])),
        risk_manager=SimpleNamespace(run=AsyncMock(return_value=[_decision()])),
        compliance_agent=SimpleNamespace(run=AsyncMock(return_value=[_cleared()])),
        execution_agent=SimpleNamespace(run=AsyncMock(return_value=[_fill()])),
        log_tick_summary=AsyncMock(),
        broadcast_tick_update=AsyncMock(),
        paper_engine=SimpleNamespace(mark_to_market=AsyncMock()),
        redis_client=SimpleNamespace(publish_signal=AsyncMock()),
    )
    for attr_name in vars(fakes):
        monkeypatch.setattr(agent_loop_module, attr_name, getattr(fakes, attr_name))

    state_manager_mock = SimpleNamespace(
        get_state=AsyncMock(return_value=_state(kill_switch=False)),
        process_fills=AsyncMock(return_value=_state(kill_switch=False)),
    )
    monkeypatch.setattr(agent_loop_module, "state_manager", state_manager_mock)

    broadcasts: list[dict] = []

    async def fake_broadcast(message: dict) -> None:
        broadcasts.append(message)

    monkeypatch.setattr("src.api.main.broadcast", fake_broadcast)

    return fakes, broadcasts


@pytest.mark.asyncio
async def test_signal_generated_broadcast(mock_pipeline):
    _, broadcasts = mock_pipeline
    await run_tick("tick-x")
    signal_events = [b for b in broadcasts if b["event_type"] == "signal_generated"]
    assert len(signal_events) == 1
    assert signal_events[0]["payload"]["asset"] == "BTC-USD"


@pytest.mark.asyncio
async def test_regime_update_broadcast(mock_pipeline):
    _, broadcasts = mock_pipeline
    await run_tick("tick-x")
    regime_events = [b for b in broadcasts if b["event_type"] == "regime_update"]
    assert len(regime_events) == 1
    assert regime_events[0]["payload"]["regime"] == "RISK_ON"


@pytest.mark.asyncio
async def test_trade_proposed_broadcast(mock_pipeline):
    _, broadcasts = mock_pipeline
    await run_tick("tick-x")
    proposed_events = [b for b in broadcasts if b["event_type"] == "trade_proposed"]
    assert len(proposed_events) == 1
    assert proposed_events[0]["payload"]["status"] == "PROPOSED"
    assert proposed_events[0]["payload"]["proposal_id"] == "p1"


@pytest.mark.asyncio
async def test_trade_approved_broadcast(mock_pipeline):
    _, broadcasts = mock_pipeline
    await run_tick("tick-x")
    approved_events = [b for b in broadcasts if b["event_type"] == "trade_approved"]
    assert len(approved_events) == 1
    assert approved_events[0]["payload"]["status"] == "APPROVED"


@pytest.mark.asyncio
async def test_trade_rejected_event_type_when_decision_rejected(mock_pipeline, monkeypatch):
    fakes, broadcasts = mock_pipeline
    fakes.risk_manager.run = AsyncMock(return_value=[_decision(status="REJECTED")])
    fakes.compliance_agent.run = AsyncMock(return_value=[])
    fakes.execution_agent.run = AsyncMock(return_value=[])

    await run_tick("tick-x")
    rejected_events = [b for b in broadcasts if b["event_type"] == "trade_rejected"]
    assert len(rejected_events) == 1
    assert rejected_events[0]["payload"]["status"] == "REJECTED"


@pytest.mark.asyncio
async def test_resized_decision_maps_to_approved_status(mock_pipeline):
    fakes, broadcasts = mock_pipeline
    fakes.risk_manager.run = AsyncMock(return_value=[_decision(status="RESIZED")])

    await run_tick("tick-x")
    events = [b for b in broadcasts if b["event_type"] == "trade_approved"]
    assert len(events) == 1
    assert events[0]["payload"]["status"] == "APPROVED"
    assert events[0]["payload"]["risk_decision"]["status"] == "RESIZED"


@pytest.mark.asyncio
async def test_trade_cleared_broadcast(mock_pipeline):
    _, broadcasts = mock_pipeline
    await run_tick("tick-x")
    cleared_events = [b for b in broadcasts if b["event_type"] == "trade_cleared"]
    assert len(cleared_events) == 1
    assert cleared_events[0]["payload"]["proposal_id"] == "p1"


@pytest.mark.asyncio
async def test_trade_filled_broadcast_resolves_proposal_id(mock_pipeline):
    _, broadcasts = mock_pipeline
    await run_tick("tick-x")
    filled_events = [b for b in broadcasts if b["event_type"] == "trade_filled"]
    assert len(filled_events) == 1
    assert filled_events[0]["payload"]["proposal_id"] == "p1"
    assert filled_events[0]["payload"]["status"] == "FILLED"
    assert filled_events[0]["payload"]["fill"]["cleared_id"] == "c1"


@pytest.mark.asyncio
async def test_fill_with_unknown_cleared_id_is_not_broadcast(mock_pipeline):
    fakes, broadcasts = mock_pipeline
    orphan_fill = Fill(
        cleared_id="unknown-cleared-id", asset="ETH-USD", side="BUY", filled_size_usd=500.0,
        fill_price=3000.0, fee_usd=3.0, timestamp="2026-06-20T00:00:00Z",
    )
    fakes.execution_agent.run = AsyncMock(return_value=[orphan_fill])

    await run_tick("tick-x")
    filled_events = [b for b in broadcasts if b["event_type"] == "trade_filled"]
    assert filled_events == []


@pytest.mark.asyncio
async def test_safe_broadcast_swallows_errors():
    async def failing_broadcast(message):
        raise RuntimeError("websocket gone")

    import src.api.main as main_module
    original = main_module.broadcast
    main_module.broadcast = failing_broadcast
    try:
        await _safe_broadcast({"event_type": "x"})  # should not raise
    finally:
        main_module.broadcast = original


@pytest.mark.asyncio
async def test_marks_to_market_during_tick(mock_pipeline):
    fakes, _ = mock_pipeline
    await run_tick("tick-x")
    # Live loop must mark positions to market (C2 regression): once before the
    # decision chain and once before the post-fill risk checks.
    assert fakes.paper_engine.mark_to_market.await_count == 2


@pytest.mark.asyncio
async def test_signals_persisted_to_redis(mock_pipeline):
    fakes, _ = mock_pipeline
    await run_tick("tick-x")
    # The single momentum signal in the fixture should be persisted for history.
    fakes.redis_client.publish_signal.assert_awaited()
