import pytest
from pydantic import ValidationError

from src.schemas.signals import Signal, SignalBatch
from src.schemas.regime import MarketRegime
from src.schemas.trades import ProposedTrade, RiskDecision, ClearedTrade, Fill
from src.schemas.portfolio import Position, PortfolioState


def _signal(**overrides) -> Signal:
    defaults = dict(
        timestamp="2026-06-20T00:00:00Z",
        source_agent="momentum_analyst",
        asset="BTC-USD",
        direction="LONG",
        confidence_score=0.7,
        horizon_hours=4,
    )
    defaults.update(overrides)
    return Signal(**defaults)


class TestSignal:
    def test_valid_signal_generates_uuid(self):
        s = _signal()
        assert s.signal_id
        assert s.asset == "BTC-USD"

    def test_confidence_score_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            _signal(confidence_score=1.5)

    def test_invalid_direction_rejected(self):
        with pytest.raises(ValidationError):
            _signal(direction="UP")

    def test_invalid_source_agent_rejected(self):
        with pytest.raises(ValidationError):
            _signal(source_agent="random_agent")

    def test_signal_batch(self):
        batch = SignalBatch(tick_id="t1", timestamp="2026-06-20T00:00:00Z", signals=[_signal(), _signal()])
        assert len(batch.signals) == 2


class TestMarketRegime:
    def _regime(self, **overrides):
        defaults = dict(
            tick_id="t1",
            timestamp="2026-06-20T00:00:00Z",
            regime="RISK_ON",
            posture="AGGRESSIVE",
            posture_multiplier=1.0,
            regime_rationale="strong momentum",
            signal_ids_cited=["a", "b", "c"],
        )
        defaults.update(overrides)
        return MarketRegime(**defaults)

    def test_valid_regime(self):
        regime = self._regime()
        assert regime.posture_multiplier == 1.0

    @pytest.mark.parametrize("multiplier", [1.0, 0.6, 0.3, 0.0])
    def test_allowed_posture_multipliers(self, multiplier):
        regime = self._regime(posture_multiplier=multiplier)
        assert regime.posture_multiplier == multiplier

    def test_disallowed_posture_multiplier_rejected(self):
        with pytest.raises(ValidationError):
            self._regime(posture_multiplier=0.5)

    def test_fewer_than_three_citations_rejected(self):
        with pytest.raises(ValidationError):
            self._regime(signal_ids_cited=["a", "b"])

    def test_exactly_three_citations_accepted(self):
        regime = self._regime(signal_ids_cited=["a", "b", "c"])
        assert len(regime.signal_ids_cited) == 3


class TestProposedTrade:
    def _trade(self, **overrides):
        defaults = dict(
            tick_id="t1",
            asset="BTC-USD",
            side="BUY",
            order_type="MARKET",
            size_usd=1000.0,
            stop_loss_pct=0.02,
            trade_rationale="momentum breakout",
            confidence_composite=0.6,
        )
        defaults.update(overrides)
        return ProposedTrade(**defaults)

    def test_market_order_without_limit_price_ok(self):
        trade = self._trade()
        assert trade.limit_price is None

    def test_limit_order_requires_limit_price(self):
        with pytest.raises(ValidationError):
            self._trade(order_type="LIMIT")

    def test_limit_order_with_price_ok(self):
        trade = self._trade(order_type="LIMIT", limit_price=64000.0)
        assert trade.limit_price == 64000.0

    def test_confidence_composite_bounds(self):
        with pytest.raises(ValidationError):
            self._trade(confidence_composite=1.1)


class TestRiskDecision:
    def test_approved_requires_size(self):
        with pytest.raises(ValidationError):
            RiskDecision(
                proposal_id="p1", status="APPROVED",
                risk_rationale="ok", rules_checked=["RISK_001"],
            )

    def test_approved_with_size_ok(self):
        decision = RiskDecision(
            proposal_id="p1", status="APPROVED", approved_size_usd=500.0,
            risk_rationale="ok", rules_checked=["RISK_001"],
        )
        assert decision.approved_size_usd == 500.0

    def test_rejected_requires_rules_violated(self):
        with pytest.raises(ValidationError):
            RiskDecision(
                proposal_id="p1", status="REJECTED",
                risk_rationale="kill switch active", rules_checked=["RISK_006"],
            )

    def test_rejected_with_rules_violated_ok(self):
        decision = RiskDecision(
            proposal_id="p1", status="REJECTED",
            risk_rationale="kill switch active", rules_checked=["RISK_006"],
            rules_violated=["RISK_006"],
        )
        assert decision.rules_violated == ["RISK_006"]


class TestClearedTradeAndFill:
    def test_cleared_trade_defaults(self):
        trade = ClearedTrade(
            proposal_id="p1", asset="ETH-USD", side="BUY", order_type="MARKET",
            final_size_usd=2000.0, stop_loss_pct=0.02,
        )
        assert trade.cleared_id

    def test_fill_defaults_paper_trade_true(self):
        fill = Fill(
            cleared_id="c1", asset="ETH-USD", side="BUY",
            filled_size_usd=2000.0, fill_price=3500.0, fee_usd=12.0,
            timestamp="2026-06-20T00:00:00Z",
        )
        assert fill.paper_trade is True


class TestPortfolioState:
    def test_position_and_state(self):
        position = Position(
            asset="BTC-USD", size_usd=2000.0, entry_price=65000.0, current_price=66000.0,
            unrealized_pnl_usd=30.0, unrealized_pnl_pct=0.015, stop_loss_price=63700.0,
        )
        state = PortfolioState(
            timestamp="2026-06-20T00:00:00Z", total_value_usd=102000.0, cash_usd=100000.0,
            positions=[position], session_high_usd=102000.0, daily_pnl_usd=2000.0,
            daily_pnl_pct=0.02, drawdown_from_session_high_pct=0.0, kill_switch=False,
        )
        assert state.positions[0].asset == "BTC-USD"
        assert state.kill_switch is False
