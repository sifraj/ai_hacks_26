import pytest

import src.harness.kill_switch as kill_switch_module
from src.harness.kill_switch import KillSwitchMonitor


class FakeRedisClient:
    def __init__(self, state: dict | None = None) -> None:
        self._state = state

    async def get_portfolio_state(self):
        return self._state

    async def set_portfolio_state(self, state: dict) -> None:
        self._state = state


class FakePaperEngine:
    def __init__(self) -> None:
        self.close_all_positions_called = False

    async def close_all_positions(self):
        self.close_all_positions_called = True
        return []


@pytest.fixture
def fake_redis(monkeypatch):
    fake = FakeRedisClient(state={"cash_usd": 100_000.0, "kill_switch": False})
    monkeypatch.setattr(kill_switch_module, "redis_client", fake)
    return fake


@pytest.fixture
def fake_paper_engine(monkeypatch):
    fake = FakePaperEngine()
    monkeypatch.setattr("src.paper_trading.paper_engine.paper_engine", fake)
    return fake


@pytest.mark.asyncio
async def test_no_trigger_when_nothing_set(fake_redis, tmp_path, monkeypatch):
    monkeypatch.setattr(kill_switch_module, "KILL_SWITCH_FILE", tmp_path / "KILL_SWITCH")
    monitor = KillSwitchMonitor()
    activated, source = await monitor._is_activated()
    assert activated is False
    assert source is None


@pytest.mark.asyncio
async def test_file_trigger_detected(fake_redis, tmp_path, monkeypatch):
    kill_file = tmp_path / "KILL_SWITCH"
    kill_file.write_text("stop")
    monkeypatch.setattr(kill_switch_module, "KILL_SWITCH_FILE", kill_file)

    monitor = KillSwitchMonitor()
    activated, source = await monitor._is_activated()
    assert activated is True
    assert source == "file"


@pytest.mark.asyncio
async def test_redis_trigger_detected(tmp_path, monkeypatch):
    fake = FakeRedisClient(state={"cash_usd": 100_000.0, "kill_switch": True})
    monkeypatch.setattr(kill_switch_module, "redis_client", fake)
    monkeypatch.setattr(kill_switch_module, "KILL_SWITCH_FILE", tmp_path / "KILL_SWITCH")

    monitor = KillSwitchMonitor()
    activated, source = await monitor._is_activated()
    assert activated is True
    assert source == "redis_state"


@pytest.mark.asyncio
async def test_api_trigger_detected(fake_redis, tmp_path, monkeypatch):
    monkeypatch.setattr(kill_switch_module, "KILL_SWITCH_FILE", tmp_path / "KILL_SWITCH")

    monitor = KillSwitchMonitor()
    monitor.trigger_via_api()
    activated, source = await monitor._is_activated()
    assert activated is True
    assert source == "api"


@pytest.mark.asyncio
async def test_activate_sets_redis_flag_and_closes_positions(fake_redis, fake_paper_engine):
    monitor = KillSwitchMonitor()
    await monitor._activate("test_source")

    assert monitor._activated is True
    assert fake_paper_engine.close_all_positions_called is True
    state = await kill_switch_module.redis_client.get_portfolio_state()
    assert state["kill_switch"] is True
