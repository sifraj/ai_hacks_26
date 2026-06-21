from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from src.agents.base_agent import BaseAgent
from src.config import settings
from src.data.redis_client import redis_client
from src.data.timescale_client import timescale_client
from src.schemas.trades import ClearedTrade, ProposedTrade, RiskDecision

MIN_24H_VOLUME_USD = 50_000_000.0  # RULE_003
MAX_ORDER_PCT_OF_VOLUME = 0.01  # RULE_006
MACRO_EVENT_BUFFER_MINUTES = 10  # RULE_001

MACRO_EVENT_KEY = "compliance:next_macro_event_ts"
COINBASE_STATUS_KEY = "compliance:coinbase_status"


class ComplianceAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(
            name="compliance_agent",
            allowed_tools=["read_approved_trades", "read_rule_book", "write_cleared_trades"],
        )

    async def _run_impl(self, context: dict[str, Any]) -> dict[str, Any]:
        return {"cleared": []}

    # RULE_001: no trading within 10 minutes of a scheduled macro event
    async def _check_rule_001_macro_event(self) -> bool:
        raw = await redis_client.client.get(MACRO_EVENT_KEY)
        if not raw:
            return True
        try:
            event_time = datetime.fromisoformat(raw)
        except ValueError:
            return True
        now = datetime.now(timezone.utc)
        return abs((event_time - now).total_seconds()) > MACRO_EVENT_BUFFER_MINUTES * 60

    # RULE_002: no trading if Coinbase API returns degraded status
    async def _check_rule_002_coinbase_status(self) -> bool:
        status = await redis_client.client.get(COINBASE_STATUS_KEY)
        return not status or status == "operational"

    async def _get_24h_volume(self, asset: str) -> float:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=1)
        rows = await timescale_client.get_ohlcv(asset, start, end, "1d")
        return float(rows[-1]["volume"]) if rows else 0.0

    # RULE_003: asset must have >$50M 24h volume on Coinbase to be tradeable
    def _check_rule_003_min_volume(self, volume_24h: float) -> bool:
        return volume_24h > MIN_24H_VOLUME_USD

    # RULE_004: no duplicate orders for same asset within same tick
    def _check_rule_004_duplicate(self, asset: str, assets_seen_this_tick: set[str]) -> bool:
        return asset not in assets_seen_this_tick

    # RULE_005: paper trading mode must be confirmed active before any order submission
    def _check_rule_005_paper_trading(self) -> bool:
        return settings.paper_trading is True

    # RULE_006: order size must not exceed 1% of asset's 24h volume
    def _check_rule_006_max_order_size(self, size_usd: float, volume_24h: float) -> bool:
        if volume_24h <= 0:
            return False
        return size_usd <= volume_24h * MAX_ORDER_PCT_OF_VOLUME

    async def _check_trade(
        self,
        trade: ProposedTrade,
        approved_size_usd: float,
        assets_seen_this_tick: set[str],
    ) -> tuple[ClearedTrade | None, list[str], str | None]:
        checks_passed: list[str] = []

        if not self._check_rule_005_paper_trading():
            return None, checks_passed, "RULE_005"
        checks_passed.append("RULE_005")

        if not await self._check_rule_001_macro_event():
            return None, checks_passed, "RULE_001"
        checks_passed.append("RULE_001")

        if not await self._check_rule_002_coinbase_status():
            return None, checks_passed, "RULE_002"
        checks_passed.append("RULE_002")

        if not self._check_rule_004_duplicate(trade.asset, assets_seen_this_tick):
            return None, checks_passed, "RULE_004"
        checks_passed.append("RULE_004")

        volume_24h = await self._get_24h_volume(trade.asset)
        if not self._check_rule_003_min_volume(volume_24h):
            return None, checks_passed, "RULE_003"
        checks_passed.append("RULE_003")

        if not self._check_rule_006_max_order_size(approved_size_usd, volume_24h):
            return None, checks_passed, "RULE_006"
        checks_passed.append("RULE_006")

        cleared = ClearedTrade(
            proposal_id=trade.proposal_id,
            asset=trade.asset,
            side=trade.side,
            order_type=trade.order_type,
            final_size_usd=approved_size_usd,
            limit_price=trade.limit_price,
            stop_loss_pct=trade.stop_loss_pct,
            compliance_checks_passed=checks_passed,
        )
        return cleared, checks_passed, None

    async def check_all(
        self, approved: list[RiskDecision], proposed: list[ProposedTrade]
    ) -> list[ClearedTrade]:
        proposed_by_id = {p.proposal_id: p for p in proposed}
        cleared_trades: list[ClearedTrade] = []
        assets_seen_this_tick: set[str] = set()

        for decision in approved:
            if decision.status not in ("APPROVED", "RESIZED"):
                continue

            trade = proposed_by_id.get(decision.proposal_id)
            if trade is None:
                self.logger.error(
                    "compliance_missing_proposal",
                    event_type="compliance_missing_proposal",
                    payload={"proposal_id": decision.proposal_id},
                )
                continue

            approved_size_usd = (
                decision.approved_size_usd if decision.approved_size_usd is not None else trade.size_usd
            )

            cleared, checks_passed, failed_rule = await self._check_trade(
                trade, approved_size_usd, assets_seen_this_tick
            )
            assets_seen_this_tick.add(trade.asset)

            if cleared is None:
                self.logger.warning(
                    "compliance_rejected",
                    event_type="compliance_rejected",
                    payload={
                        "proposal_id": trade.proposal_id,
                        "asset": trade.asset,
                        "failed_rule": failed_rule,
                        "checks_passed": checks_passed,
                    },
                )
                continue

            cleared_trades.append(cleared)
            self.logger.info(
                "compliance_cleared",
                event_type="compliance_cleared",
                payload=cleared.model_dump(),
            )

        return cleared_trades

    async def run(
        self, approved: list[RiskDecision], proposed: list[ProposedTrade] | None = None
    ) -> list[ClearedTrade]:
        proposed = proposed or []
        await super().run({"approved_count": len(approved)})
        return await self.check_all(approved, proposed)


compliance_agent = ComplianceAgent()
