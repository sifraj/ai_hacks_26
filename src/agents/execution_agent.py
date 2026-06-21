from __future__ import annotations

import json
from typing import Any

from src.agents.base_agent import BaseAgent
from src.config import settings
from src.data.redis_client import redis_client
from src.paper_trading.paper_engine import paper_engine
from src.schemas.trades import ClearedTrade, Fill, ProposedTrade

FILLS_QUEUE_KEY = "fills:queue"


class ExecutionAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(
            name="execution_agent",
            allowed_tools=["read_cleared_trades", "place_paper_order", "cancel_order", "write_fill"],
        )

    async def _run_impl(self, context: dict[str, Any]) -> dict[str, Any]:
        return {"fills": []}

    async def _execute_one(
        self, cleared_trade: ClearedTrade, signal_ids: list[str]
    ) -> Fill:
        assert settings.paper_trading is True, "PAPER_TRADING must be true — refusing to place a live order"

        fill = await paper_engine.execute_paper_order(cleared_trade)

        await redis_client.client.lpush(FILLS_QUEUE_KEY, fill.model_dump_json())

        self.logger.info(
            "fill_executed",
            event_type="fill_executed",
            payload={
                "fill_id": fill.fill_id,
                "cleared_id": fill.cleared_id,
                "proposal_id": cleared_trade.proposal_id,
                "signal_ids": signal_ids,
                "asset": fill.asset,
                "side": fill.side,
                "filled_size_usd": fill.filled_size_usd,
                "fill_price": fill.fill_price,
                "fee_usd": fill.fee_usd,
            },
        )
        return fill

    async def run(
        self,
        cleared: list[ClearedTrade],
        proposed: list[ProposedTrade] | None = None,
    ) -> list[Fill]:
        await super().run({"cleared_count": len(cleared)})

        proposed_by_id = {p.proposal_id: p for p in (proposed or [])}
        fills: list[Fill] = []

        for cleared_trade in cleared:
            trade = proposed_by_id.get(cleared_trade.proposal_id)
            signal_ids = trade.signal_ids if trade else []

            try:
                fill = await self._execute_one(cleared_trade, signal_ids)
                fills.append(fill)
            except Exception as e:
                self.logger.error(
                    "fill_execution_failed",
                    event_type="fill_execution_failed",
                    payload={"cleared_id": cleared_trade.cleared_id, "error": str(e)},
                )

        return fills


execution_agent = ExecutionAgent()
