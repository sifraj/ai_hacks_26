from types import SimpleNamespace

import pytest

import src.agents.compliance_agent as compliance_module
from src.agents.compliance_agent import ComplianceAgent
from src.schemas.trades import ProposedTrade, RiskDecision


class FakeRawRedisClient:
    def __init__(self, kv: dict[str, str] | None = None) -> None:
        self._kv = kv or {}

    async def get(self, key: str):
        return self._kv.get(key)


class FakeTimescaleClient:
    def __init__(self, volume: float = 100_000_000.0) -> None:
        self.volume = volume

    async def get_ohlcv(self, asset, start, end, interval):
        return [{"volume": self.volume}]


def _trade(**overrides) -> ProposedTrade:
    defaults = dict(
        proposal_id="p1",
        tick_id="t1",
        asset="BTC-USD",
        side="BUY",
        order_type="MARKET",
        size_usd=2000.0,
        stop_loss_pct=0.02,
        trade_rationale="test",
        signal_ids=["s1", "s2"],
        confidence_composite=0.6,
    )
    defaults.update(overrides)
    return ProposedTrade(**defaults)


def _decision(**overrides) -> RiskDecision:
    defaults = dict(
        proposal_id="p1", status="APPROVED", approved_size_usd=2000.0,
        risk_rationale="ok", rules_checked=["RISK_006"],
    )
    defaults.update(overrides)
    return RiskDecision(**defaults)


@pytest.fixture
def agent(monkeypatch):
    monkeypatch.setattr(compliance_module, "redis_client", SimpleNamespace(client=FakeRawRedisClient()))
    monkeypatch.setattr(compliance_module, "timescale_client", FakeTimescaleClient())
    return ComplianceAgent()


@pytest.fixture
def low_volume_agent(monkeypatch):
    monkeypatch.setattr(compliance_module, "redis_client", SimpleNamespace(client=FakeRawRedisClient()))
    monkeypatch.setattr(compliance_module, "timescale_client", FakeTimescaleClient(volume=10_000_000.0))
    return ComplianceAgent()


class TestCheckAll:
    @pytest.mark.asyncio
    async def test_clean_trade_clears_all_rules(self, agent):
        trade = _trade()
        decision = _decision()
        cleared = await agent.check_all([decision], [trade])
        assert len(cleared) == 1
        assert cleared[0].asset == "BTC-USD"
        assert set(cleared[0].compliance_checks_passed) == {
            "RULE_001", "RULE_002", "RULE_003", "RULE_004", "RULE_005", "RULE_006",
        }

    @pytest.mark.asyncio
    async def test_rejected_decision_is_skipped(self, agent):
        trade = _trade()
        decision = _decision(status="REJECTED", approved_size_usd=None, rules_violated=["RISK_006"])
        cleared = await agent.check_all([decision], [trade])
        assert cleared == []

    @pytest.mark.asyncio
    async def test_resized_decision_uses_approved_size(self, agent):
        trade = _trade(size_usd=5000.0)
        decision = _decision(status="RESIZED", approved_size_usd=1500.0, rules_violated=["RISK_004"])
        cleared = await agent.check_all([decision], [trade])
        assert len(cleared) == 1
        assert cleared[0].final_size_usd == 1500.0

    @pytest.mark.asyncio
    async def test_missing_proposal_is_skipped(self, agent):
        decision = _decision(proposal_id="ghost")
        cleared = await agent.check_all([decision], [])
        assert cleared == []

    @pytest.mark.asyncio
    async def test_duplicate_asset_in_same_tick_only_first_clears(self, agent):
        trade1 = _trade(proposal_id="p1", asset="BTC-USD")
        trade2 = _trade(proposal_id="p2", asset="BTC-USD")
        decision1 = _decision(proposal_id="p1")
        decision2 = _decision(proposal_id="p2")
        cleared = await agent.check_all([decision1, decision2], [trade1, trade2])
        assert len(cleared) == 1
        assert cleared[0].proposal_id == "p1"

    @pytest.mark.asyncio
    async def test_low_volume_asset_rejected_by_rule_003(self, low_volume_agent):
        trade = _trade(size_usd=50_000.0)
        decision = _decision(approved_size_usd=50_000.0)
        cleared = await low_volume_agent.check_all([decision], [trade])
        assert cleared == []

    @pytest.mark.asyncio
    async def test_order_size_exceeding_volume_pct_rejected_by_rule_006(self, agent):
        # volume=100M, 1% cap = $1M; propose $2M order.
        trade = _trade(size_usd=2_000_000.0)
        decision = _decision(approved_size_usd=2_000_000.0)
        cleared = await agent.check_all([decision], [trade])
        assert cleared == []

    @pytest.mark.asyncio
    async def test_paper_trading_disabled_rejects_everything(self, agent, monkeypatch):
        monkeypatch.setattr(compliance_module.settings, "paper_trading", False)
        trade = _trade()
        decision = _decision()
        cleared = await agent.check_all([decision], [trade])
        assert cleared == []

    @pytest.mark.asyncio
    async def test_macro_event_within_buffer_rejects(self, monkeypatch):
        from datetime import datetime, timedelta, timezone

        near_event = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        monkeypatch.setattr(
            compliance_module,
            "redis_client",
            SimpleNamespace(client=FakeRawRedisClient(kv={"compliance:next_macro_event_ts": near_event})),
        )
        monkeypatch.setattr(compliance_module, "timescale_client", FakeTimescaleClient())
        agent = ComplianceAgent()

        trade = _trade()
        decision = _decision()
        cleared = await agent.check_all([decision], [trade])
        assert cleared == []

    @pytest.mark.asyncio
    async def test_coinbase_degraded_status_rejects(self, monkeypatch):
        monkeypatch.setattr(
            compliance_module,
            "redis_client",
            SimpleNamespace(client=FakeRawRedisClient(kv={"compliance:coinbase_status": "degraded"})),
        )
        monkeypatch.setattr(compliance_module, "timescale_client", FakeTimescaleClient())
        agent = ComplianceAgent()

        trade = _trade()
        decision = _decision()
        cleared = await agent.check_all([decision], [trade])
        assert cleared == []
