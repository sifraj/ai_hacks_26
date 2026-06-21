import json

import pytest

import src.agents.state_manager as state_manager_module
from src.agents.state_manager import (
    _pull_pending_fills,
    _check_hard_risk_rules,
    process_fills,
    FILLS_QUEUE_KEY,
    TRADING_HALTED_KEY,
)
from src.schemas.portfolio import PortfolioState
from src.schemas.trades import Fill


def _state(**overrides) -> PortfolioState:
    defaults = dict(
        timestamp="2026-06-20T00:00:00Z",
        total_value_usd=100_000.0,
        cash_usd=100_000.0,
        positions=[],
        session_high_usd=100_000.0,
        daily_pnl_usd=0.0,
        daily_pnl_pct=0.0,
        drawdown_from_session_high_pct=0.0,
        kill_switch=False,
    )
    defaults.update(overrides)
    return PortfolioState(**defaults)


class FakeRawClient:
    def __init__(self) -> None:
        self.queue: list[str] = []
        self.kv: dict[str, str] = {}

    async def rpop(self, key: str) -> str | None:
        if key == FILLS_QUEUE_KEY and self.queue:
            return self.queue.pop(0)
        return None

    async def set(self, key: str, value: str) -> None:
        self.kv[key] = value


class FakeRedisClient:
    def __init__(self, state: dict | None = None) -> None:
        self._state = state
        self.client = FakeRawClient()

    async def get_portfolio_state(self):
        return self._state

    async def set_portfolio_state(self, state: dict) -> None:
        self._state = state


class FakePaperEngine:
    def __init__(self, state: PortfolioState) -> None:
        self._state = state

    async def get_portfolio_state(self) -> PortfolioState:
        return self._state


class FakeKillSwitchMonitor:
    def __init__(self) -> None:
        self.activated_with: str | None = None

    async def _activate(self, source: str) -> None:
        self.activated_with = source


@pytest.fixture
def fake_redis(monkeypatch):
    fake = FakeRedisClient()
    monkeypatch.setattr(state_manager_module, "redis_client", fake)
    return fake


@pytest.fixture
def fake_kill_switch(monkeypatch):
    fake = FakeKillSwitchMonitor()
    monkeypatch.setattr(state_manager_module, "kill_switch_monitor", fake)
    return fake


def fake_paper_engine(monkeypatch, state):
    fake = FakePaperEngine(state)
    monkeypatch.setattr(state_manager_module, "paper_engine", fake)
    return fake


@pytest.mark.asyncio
async def test_pull_pending_fills_drains_queue(fake_redis):
    fill = Fill(
        cleared_id="c1", asset="BTC-USD", side="BUY",
        filled_size_usd=2000.0, fill_price=65000.0, fee_usd=12.0,
        timestamp="2026-06-20T00:00:00Z",
    )
    fake_redis.client.queue.append(fill.model_dump_json())

    fills = await _pull_pending_fills()
    assert len(fills) == 1
    assert fills[0].asset == "BTC-USD"
    assert fake_redis.client.queue == []


@pytest.mark.asyncio
async def test_check_hard_risk_rules_breaches_drawdown_triggers_kill_switch(
    fake_redis, fake_kill_switch, monkeypatch
):
    breached_state = _state(drawdown_from_session_high_pct=0.06, kill_switch=False)
    refreshed_state = _state(drawdown_from_session_high_pct=0.06, kill_switch=True)
    fake_paper_engine(monkeypatch, refreshed_state)

    result = await _check_hard_risk_rules(breached_state)

    assert fake_kill_switch.activated_with == "RISK_001_drawdown"
    assert result.kill_switch is True


@pytest.mark.asyncio
async def test_check_hard_risk_rules_breaches_daily_loss_sets_halted_flag(
    fake_redis, fake_kill_switch, monkeypatch
):
    state = _state(daily_pnl_pct=-0.05)
    fake_paper_engine(monkeypatch, state)

    await _check_hard_risk_rules(state)

    assert fake_redis.client.kv[TRADING_HALTED_KEY] == "true"
    assert fake_kill_switch.activated_with is None


@pytest.mark.asyncio
async def test_check_hard_risk_rules_no_breach_is_noop(fake_redis, fake_kill_switch, monkeypatch):
    state = _state(drawdown_from_session_high_pct=0.01, daily_pnl_pct=0.01)
    fake_paper_engine(monkeypatch, state)

    result = await _check_hard_risk_rules(state)

    assert fake_kill_switch.activated_with is None
    assert TRADING_HALTED_KEY not in fake_redis.client.kv
    assert result.kill_switch is False


@pytest.mark.asyncio
async def test_process_fills_broadcasts_state(fake_redis, fake_kill_switch, monkeypatch):
    state = _state()
    fake_paper_engine(monkeypatch, state)

    broadcast_calls = []

    async def fake_broadcast(message: dict) -> None:
        broadcast_calls.append(message)

    monkeypatch.setattr("src.api.main.broadcast", fake_broadcast)

    result = await process_fills()

    assert len(broadcast_calls) == 1
    assert broadcast_calls[0]["event_type"] == "portfolio_state_update"
    assert result.total_value_usd == 100_000.0
