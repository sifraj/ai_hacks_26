from __future__ import annotations

import inspect
import json
from typing import Any, Awaitable, Callable

from src.data.redis_client import redis_client
from src.harness.audit_logger import get_logger

logger = get_logger("tool_registry")


class ToolAccessDeniedError(Exception):
    pass


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Callable[..., Any]] = {}

    def register(self, name: str, fn: Callable[..., Any]) -> None:
        self._tools[name] = fn

    def get(self, name: str) -> Callable[..., Any]:
        if name not in self._tools:
            raise KeyError(f"tool '{name}' is not registered")
        return self._tools[name]

    async def call(
        self,
        name: str,
        allowed_tools: list[str] | None = None,
        agent_name: str | None = None,
        **kwargs: Any,
    ) -> Any:
        if allowed_tools is not None and name not in allowed_tools:
            raise ToolAccessDeniedError(
                f"agent '{agent_name}' is not allowed to use tool '{name}'"
            )

        fn = self.get(name)
        logger.info(
            "tool_invoked",
            event_type="tool_invoked",
            agent_name=agent_name,
            payload={"tool_name": name, "kwargs_keys": list(kwargs.keys())},
        )
        result = fn(**kwargs)
        if inspect.isawaitable(result):
            result = await result
        return result


tool_registry = ToolRegistry()


# --- Generic Redis-backed blackboard helpers (used by tools without dedicated stores) ---

async def _redis_write_json(key: str, value: Any) -> None:
    payload = value if isinstance(value, str) else json.dumps(value)
    await redis_client.client.set(key, payload)


async def _redis_read_json(key: str) -> Any | None:
    raw = await redis_client.client.get(key)
    return json.loads(raw) if raw else None


# --- Ingestor tools (SPEC §2.4: Ingestors) ---

async def fetch_market_data(**_: Any) -> None:
    from src.ingestors.market_ingestor import market_ingestor
    await market_ingestor.run()


async def fetch_news(**_: Any) -> None:
    from src.ingestors.sentiment_ingestor import sentiment_ingestor
    await sentiment_ingestor.run()


async def fetch_onchain(**_: Any) -> None:
    from src.ingestors.onchain_ingestor import onchain_ingestor
    await onchain_ingestor.run()


# --- Analyst tools ---

async def read_normalized_data(asset: str, source: str) -> Any | None:
    return await _redis_read_json(f"{source}:raw:{asset}")


async def write_signal(asset: str, signal: dict) -> None:
    await redis_client.publish_signal(asset, signal)


# --- CIO tools ---

async def read_signals(asset: str | None = None) -> list[dict]:
    return await redis_client.get_latest_signals(asset)


async def read_market_data(asset: str) -> float | None:
    from src.data.timescale_client import timescale_client
    return await timescale_client.get_latest_price(asset)


async def write_regime(regime: dict) -> None:
    await _redis_write_json("regime:latest", regime)


# --- Portfolio Manager tools ---

async def read_regime() -> Any | None:
    return await _redis_read_json("regime:latest")


async def read_portfolio_state() -> Any | None:
    return await redis_client.get_portfolio_state()


async def write_proposed_trades(trades: list[dict]) -> None:
    await _redis_write_json("trades:proposed:latest", trades)


# --- Risk Manager tools ---

async def read_proposed_trades() -> Any | None:
    return await _redis_read_json("trades:proposed:latest")


async def write_approved_trades(decisions: list[dict]) -> None:
    await _redis_write_json("trades:approved:latest", decisions)


# --- Compliance tools ---

async def read_approved_trades() -> Any | None:
    return await _redis_read_json("trades:approved:latest")


async def read_rule_book() -> dict:
    return {"rules": ["RULE_001", "RULE_002", "RULE_003", "RULE_004", "RULE_005", "RULE_006"]}


async def write_cleared_trades(trades: list[dict]) -> None:
    await _redis_write_json("trades:cleared:latest", trades)


# --- Execution tools ---

async def read_cleared_trades() -> Any | None:
    return await _redis_read_json("trades:cleared:latest")


async def place_paper_order(cleared_trade: dict) -> dict:
    from src.paper_trading.paper_engine import paper_engine
    from src.schemas.trades import ClearedTrade

    fill = await paper_engine.execute_paper_order(ClearedTrade.model_validate(cleared_trade))
    return fill.model_dump()


async def cancel_order(order_id: str) -> None:
    # No live exchange order book in paper mode — no-op placeholder.
    logger.info("cancel_order_noop", event_type="cancel_order_noop", payload={"order_id": order_id})


async def write_fill(fill: dict) -> None:
    await redis_client.client.lpush("fills:queue", json.dumps(fill))


# --- State Manager tools ---

async def read_fills() -> str | None:
    return await redis_client.client.rpop("fills:queue")


async def write_portfolio_state(state: dict) -> None:
    await redis_client.set_portfolio_state(state)


_TOOL_FUNCTIONS: dict[str, Callable[..., Awaitable[Any]]] = {
    "fetch_market_data": fetch_market_data,
    "fetch_news": fetch_news,
    "fetch_onchain": fetch_onchain,
    "read_normalized_data": read_normalized_data,
    "write_signal": write_signal,
    "read_signals": read_signals,
    "read_market_data": read_market_data,
    "write_regime": write_regime,
    "read_regime": read_regime,
    "read_portfolio_state": read_portfolio_state,
    "write_proposed_trades": write_proposed_trades,
    "read_proposed_trades": read_proposed_trades,
    "write_approved_trades": write_approved_trades,
    "read_approved_trades": read_approved_trades,
    "read_rule_book": read_rule_book,
    "write_cleared_trades": write_cleared_trades,
    "read_cleared_trades": read_cleared_trades,
    "place_paper_order": place_paper_order,
    "cancel_order": cancel_order,
    "write_fill": write_fill,
    "read_fills": read_fills,
    "write_portfolio_state": write_portfolio_state,
}

for _name, _fn in _TOOL_FUNCTIONS.items():
    tool_registry.register(_name, _fn)
