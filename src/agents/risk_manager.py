from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.agents.base_agent import BaseAgent
from src.data.redis_client import redis_client
from src.schemas.portfolio import PortfolioState, Position
from src.schemas.trades import ProposedTrade, RiskDecision

BASE_RISK_PCT = 0.05
ASSET_ALLOCATION_CAP_PCT = 0.20
MIN_TRADE_SIZE_USD = 500.0

DRAWDOWN_LIMIT_PCT = 0.05  # RISK_001
DAILY_LOSS_LIMIT_PCT = 0.03  # RISK_002
LONG_EXPOSURE_LIMIT_PCT = 0.80  # RISK_005
SINGLE_POSITION_LOSS_LIMIT_PCT = 0.02  # RISK_003

# Dated sticky halt flag set by the state manager on a RISK_002 breach. Its value is
# the ISO date it was set on, so it auto-expires at the next UTC day rollover.
TRADING_HALTED_KEY = "risk:trading_halted"


class RiskManager(BaseAgent):
    def __init__(self) -> None:
        super().__init__(
            name="risk_manager",
            allowed_tools=["read_proposed_trades", "read_portfolio_state", "write_approved_trades"],
        )

    async def _run_impl(self, context: dict[str, Any]) -> dict[str, Any]:
        return {"decisions": []}

    async def _is_trading_halted(self) -> bool:
        """True if a RISK_002 daily-loss halt is in effect for the current UTC day."""
        try:
            value = await redis_client.client.get(TRADING_HALTED_KEY)
        except Exception:
            return False
        return value == datetime.now(timezone.utc).date().isoformat()

    def _existing_position(self, asset: str, state: PortfolioState) -> Position | None:
        return next((p for p in state.positions if p.asset == asset), None)

    def _position_sizing_cap(
        self,
        trade: ProposedTrade,
        state: PortfolioState,
        existing_position: Position | None,
        posture_multiplier: float = 1.0,
    ) -> float:
        """Max allowed size for this trade under SPEC §6's sizing formula AND the
        RISK_004 per-asset allocation cap (existing exposure + this trade <= 20%)."""
        if state.total_value_usd <= 0:
            return 0.0

        base_size = state.total_value_usd * BASE_RISK_PCT
        formula_sized = base_size * posture_multiplier * trade.confidence_composite
        formula_sized = min(formula_sized, state.total_value_usd * ASSET_ALLOCATION_CAP_PCT)
        formula_sized = max(formula_sized, MIN_TRADE_SIZE_USD)

        existing_size = existing_position.size_usd if existing_position else 0.0
        remaining_asset_room = (state.total_value_usd * ASSET_ALLOCATION_CAP_PCT) - existing_size
        remaining_asset_room = max(remaining_asset_room, 0.0)

        return min(formula_sized, remaining_asset_room)

    def _evaluate_single(
        self, trade: ProposedTrade, state: PortfolioState, trading_halted: bool = False
    ) -> RiskDecision:
        rules_checked: list[str] = []

        # RISK_006: kill switch active -> reject ALL trades
        rules_checked.append("RISK_006")
        if state.kill_switch:
            return RiskDecision(
                proposal_id=trade.proposal_id,
                status="REJECTED",
                risk_rationale="Kill switch is active — all trades rejected",
                rules_checked=rules_checked,
                rules_violated=["RISK_006"],
            )

        # RISK_001: drawdown from session high > 5% -> halt all trading
        rules_checked.append("RISK_001")
        if state.drawdown_from_session_high_pct > DRAWDOWN_LIMIT_PCT:
            return RiskDecision(
                proposal_id=trade.proposal_id,
                status="REJECTED",
                risk_rationale=(
                    f"Session drawdown {state.drawdown_from_session_high_pct:.1%} "
                    f"exceeds {DRAWDOWN_LIMIT_PCT:.0%} limit"
                ),
                rules_checked=rules_checked,
                rules_violated=["RISK_001"],
            )

        # RISK_002: daily loss > 3% -> no new positions for remainder of session.
        # Reject if currently breaching OR if a sticky halt was tripped earlier today
        # (the halt persists even if daily P&L recovers). SELLs to close are allowed.
        rules_checked.append("RISK_002")
        if state.daily_pnl_pct < -DAILY_LOSS_LIMIT_PCT:
            return RiskDecision(
                proposal_id=trade.proposal_id,
                status="REJECTED",
                risk_rationale=f"Daily loss {state.daily_pnl_pct:.1%} exceeds {DAILY_LOSS_LIMIT_PCT:.0%} limit",
                rules_checked=rules_checked,
                rules_violated=["RISK_002"],
            )
        if trading_halted and trade.side == "BUY":
            return RiskDecision(
                proposal_id=trade.proposal_id,
                status="REJECTED",
                risk_rationale="Daily-loss trading halt is active for the session — no new positions",
                rules_checked=rules_checked,
                rules_violated=["RISK_002"],
            )

        existing_position = self._existing_position(trade.asset, state)

        # RISK_005: total long exposure > 80% portfolio -> reject additional longs
        rules_checked.append("RISK_005")
        if trade.side == "BUY" and state.total_value_usd > 0:
            current_long_exposure = sum(p.size_usd for p in state.positions if p.size_usd > 0)
            projected_exposure_pct = (current_long_exposure + trade.size_usd) / state.total_value_usd
            if projected_exposure_pct > LONG_EXPOSURE_LIMIT_PCT:
                return RiskDecision(
                    proposal_id=trade.proposal_id,
                    status="REJECTED",
                    risk_rationale=(
                        f"Projected long exposure {projected_exposure_pct:.1%} exceeds "
                        f"{LONG_EXPOSURE_LIMIT_PCT:.0%} limit"
                    ),
                    rules_checked=rules_checked,
                    rules_violated=["RISK_005"],
                )

        # RISK_004: single-asset allocation cap (combined with SPEC §6 position sizing formula)
        rules_checked.append("RISK_004")
        approved_size_usd = trade.size_usd
        resized = False
        if trade.side == "BUY":
            size_cap = self._position_sizing_cap(trade, state, existing_position)
            if size_cap <= 0:
                return RiskDecision(
                    proposal_id=trade.proposal_id,
                    status="REJECTED",
                    risk_rationale=f"Asset {trade.asset} is already at or beyond the 20% allocation cap",
                    rules_checked=rules_checked,
                    rules_violated=["RISK_004"],
                )
            if size_cap < approved_size_usd:
                approved_size_usd = size_cap
                resized = True

        # RISK_003: single position loss > 2% of portfolio -> block adding to a losing position
        rules_checked.append("RISK_003")
        if (
            trade.side == "BUY"
            and existing_position is not None
            and existing_position.unrealized_pnl_usd < 0
            and state.total_value_usd > 0
            and (-existing_position.unrealized_pnl_usd / state.total_value_usd) > SINGLE_POSITION_LOSS_LIMIT_PCT
        ):
            return RiskDecision(
                proposal_id=trade.proposal_id,
                status="REJECTED",
                risk_rationale=f"Existing {trade.asset} position loss exceeds {SINGLE_POSITION_LOSS_LIMIT_PCT:.0%} of portfolio",
                rules_checked=rules_checked,
                rules_violated=["RISK_003"],
            )

        if resized:
            return RiskDecision(
                proposal_id=trade.proposal_id,
                status="RESIZED",
                approved_size_usd=approved_size_usd,
                risk_rationale=f"Resized to ${approved_size_usd:.2f} to respect the 20% per-asset allocation cap",
                rules_checked=rules_checked,
                rules_violated=["RISK_004"],
            )

        return RiskDecision(
            proposal_id=trade.proposal_id,
            status="APPROVED",
            approved_size_usd=approved_size_usd,
            risk_rationale="Passed all hard risk rules",
            rules_checked=rules_checked,
        )

    async def evaluate(
        self, proposed: list[ProposedTrade], state: PortfolioState
    ) -> list[RiskDecision]:
        trading_halted = await self._is_trading_halted()
        decisions: list[RiskDecision] = []
        for trade in proposed:
            decision = self._evaluate_single(trade, state, trading_halted)
            self.logger.info(
                "risk_decision",
                event_type="risk_decision",
                payload=decision.model_dump(),
            )
            decisions.append(decision)
        return decisions

    async def run(
        self,
        proposed: list[ProposedTrade],
        portfolio_state: PortfolioState,
    ) -> list[RiskDecision]:
        await super().run({"proposed_count": len(proposed)})
        return await self.evaluate(proposed, portfolio_state)


risk_manager = RiskManager()
