from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


async def broadcast_tick_update(tick_id: str, state: Any) -> None:
    from src.api.main import broadcast

    payload = state.model_dump() if hasattr(state, "model_dump") else state
    await broadcast(
        {
            "event_type": "tick_update",
            "tick_id": tick_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
    )
