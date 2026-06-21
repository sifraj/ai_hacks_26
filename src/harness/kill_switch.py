from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from src.data.redis_client import redis_client
from src.harness.audit_logger import get_logger

logger = get_logger("kill_switch")

KILL_SWITCH_FILE = Path("./KILL_SWITCH")
CHECK_INTERVAL_SECONDS = 10


class KillSwitchMonitor:
    def __init__(self) -> None:
        self._api_triggered = False
        self._activated = False

    def trigger_via_api(self) -> None:
        self._api_triggered = True

    async def _is_activated(self) -> tuple[bool, str | None]:
        if KILL_SWITCH_FILE.exists():
            return True, "file"

        state = await redis_client.get_portfolio_state()
        if state is not None and state.get("kill_switch") is True:
            return True, "redis_state"

        if self._api_triggered:
            return True, "api"

        return False, None

    async def _activate(self, trigger_source: str) -> None:
        from src.paper_trading.paper_engine import paper_engine

        self._activated = True

        state = await redis_client.get_portfolio_state()
        if state is not None:
            state["kill_switch"] = True
            await redis_client.set_portfolio_state(state)

        fills = await paper_engine.close_all_positions()

        logger.error(
            "KILL_SWITCH_ACTIVATED",
            event_type="KILL_SWITCH_ACTIVATED",
            payload={
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "trigger_source": trigger_source,
                "positions_closed": len(fills),
            },
        )

    async def run(self) -> None:
        while True:
            if self._activated:
                await asyncio.sleep(CHECK_INTERVAL_SECONDS)
                continue

            activated, source = await self._is_activated()
            if activated and source is not None:
                await self._activate(source)

            await asyncio.sleep(CHECK_INTERVAL_SECONDS)


kill_switch_monitor = KillSwitchMonitor()
