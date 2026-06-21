import pytest

from src.agents.risk_manager import RiskManager
from src.schemas.portfolio import Position, PortfolioState
from src.schemas.trades import ProposedTrade


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


def _trade(**overrides) -> ProposedTrade:
    defaults = dict(
        tick_id="t1",
        asset="BTC-USD",
        side="BUY",
        order_type="MARKET",
        size_usd=2000.0,
        stop_loss_pct=0.02,
        trade_rationale="momentum signal",
        confidence_composite=0.6,
    )
    defaults.update(overrides)
    return ProposedTrade(**defaults)


@pytest.fixture
def manager():
    return RiskManager()


class TestRiskOrderAndRejection:
    def test_kill_switch_rejects_first(self, manager):
        state = _state(kill_switch=True, drawdown_from_session_high_pct=0.10)
        decision = manager._evaluate_single(_trade(), state)
        assert decision.status == "REJECTED"
        assert decision.rules_violated == ["RISK_006"]
        assert decision.rules_checked == ["RISK_006"]

    def test_drawdown_breach_rejects(self, manager):
        state = _state(drawdown_from_session_high_pct=0.06)
        decision = manager._evaluate_single(_trade(), state)
        assert decision.status == "REJECTED"
        assert decision.rules_violated == ["RISK_001"]
        assert decision.rules_checked == ["RISK_006", "RISK_001"]

    def test_daily_loss_breach_rejects(self, manager):
        state = _state(daily_pnl_pct=-0.05)
        decision = manager._evaluate_single(_trade(), state)
        assert decision.status == "REJECTED"
        assert decision.rules_violated == ["RISK_002"]

    def test_long_exposure_breach_rejects(self, manager):
        existing = Position(
            asset="ETH-USD", size_usd=75_000.0, entry_price=3000.0, current_price=3000.0,
            unrealized_pnl_usd=0.0, unrealized_pnl_pct=0.0, stop_loss_price=2940.0,
        )
        state = _state(positions=[existing])
        decision = manager._evaluate_single(_trade(asset="BTC-USD", size_usd=10_000.0), state)
        assert decision.status == "REJECTED"
        assert decision.rules_violated == ["RISK_005"]

    def test_sell_side_not_blocked_by_long_exposure(self, manager):
        existing = Position(
            asset="BTC-USD", size_usd=75_000.0, entry_price=60_000.0, current_price=60_000.0,
            unrealized_pnl_usd=0.0, unrealized_pnl_pct=0.0, stop_loss_price=58_800.0,
        )
        state = _state(positions=[existing])
        decision = manager._evaluate_single(
            _trade(asset="BTC-USD", side="SELL", size_usd=10_000.0), state
        )
        assert decision.status != "REJECTED" or decision.rules_violated != ["RISK_005"]

    def test_asset_allocation_cap_resizes_not_rejects(self, manager):
        state = _state(total_value_usd=100_000.0)
        # 20% cap = $20,000; proposing $25,000 with full confidence should resize down.
        decision = manager._evaluate_single(
            _trade(asset="BTC-USD", size_usd=25_000.0, confidence_composite=1.0), state
        )
        assert decision.status == "RESIZED"
        assert decision.approved_size_usd <= 20_000.0
        assert decision.rules_violated == ["RISK_004"]

    def test_asset_at_cap_already_rejects(self, manager):
        existing = Position(
            asset="BTC-USD", size_usd=20_000.0, entry_price=60_000.0, current_price=60_000.0,
            unrealized_pnl_usd=0.0, unrealized_pnl_pct=0.0, stop_loss_price=58_800.0,
        )
        state = _state(total_value_usd=100_000.0, positions=[existing])
        decision = manager._evaluate_single(_trade(asset="BTC-USD", size_usd=5_000.0), state)
        assert decision.status == "REJECTED"
        assert decision.rules_violated == ["RISK_004"]

    def test_single_position_loss_breach_rejects(self, manager):
        existing = Position(
            asset="BTC-USD", size_usd=10_000.0, entry_price=60_000.0, current_price=57_000.0,
            unrealized_pnl_usd=-3000.0, unrealized_pnl_pct=-0.05, stop_loss_price=58_800.0,
        )
        state = _state(total_value_usd=100_000.0, positions=[existing])
        decision = manager._evaluate_single(_trade(asset="BTC-USD", size_usd=1_000.0), state)
        assert decision.status == "REJECTED"
        assert decision.rules_violated == ["RISK_003"]

    def test_clean_trade_is_approved(self, manager):
        state = _state(total_value_usd=100_000.0)
        decision = manager._evaluate_single(
            _trade(asset="BTC-USD", size_usd=2000.0, confidence_composite=0.6), state
        )
        assert decision.status == "APPROVED"
        assert decision.approved_size_usd == 2000.0
        assert decision.rules_checked == ["RISK_006", "RISK_001", "RISK_002", "RISK_005", "RISK_004", "RISK_003"]


class TestEvaluate:
    @pytest.mark.asyncio
    async def test_evaluate_returns_one_decision_per_trade(self, manager):
        state = _state()
        trades = [_trade(asset="BTC-USD"), _trade(asset="ETH-USD")]
        decisions = await manager.evaluate(trades, state)
        assert len(decisions) == 2
        assert {d.proposal_id for d in decisions} == {t.proposal_id for t in trades}
