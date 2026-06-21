from __future__ import annotations

import json
from typing import Any

import redis.asyncio as redis

from src.config import settings

PORTFOLIO_STATE_KEY = "portfolio:state"
SIGNALS_KEY_PREFIX = "signals:latest"
AGENT_STATUS_KEY_PREFIX = "agent:status"


class RedisClient:
    def __init__(self, url: str | None = None) -> None:
        self._url = url or settings.redis_url
        self._client: redis.Redis | None = None

    async def connect(self) -> None:
        if self._client is None:
            self._client = redis.from_url(self._url, decode_responses=True)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    @property
    def client(self) -> redis.Redis:
        assert self._client is not None, "call connect() first"
        return self._client

    async def set_portfolio_state(self, state: dict[str, Any]) -> None:
        await self.client.set(PORTFOLIO_STATE_KEY, json.dumps(state))

    async def get_portfolio_state(self) -> dict[str, Any] | None:
        raw = await self.client.get(PORTFOLIO_STATE_KEY)
        return json.loads(raw) if raw else None

    async def publish_signal(self, asset: str, signal: dict[str, Any]) -> None:
        key = f"{SIGNALS_KEY_PREFIX}:{asset}"
        await self.client.lpush(key, json.dumps(signal))
        await self.client.ltrim(key, 0, 49)

    async def get_latest_signals(self, asset: str | None = None) -> list[dict[str, Any]]:
        if asset is not None:
            raw_list = await self.client.lrange(f"{SIGNALS_KEY_PREFIX}:{asset}", 0, -1)
            return [json.loads(r) for r in raw_list]

        signals: list[dict[str, Any]] = []
        async for key in self.client.scan_iter(match=f"{SIGNALS_KEY_PREFIX}:*"):
            raw_list = await self.client.lrange(key, 0, -1)
            signals.extend(json.loads(r) for r in raw_list)
        return signals

    async def set_agent_status(self, agent_name: str, status: dict[str, Any]) -> None:
        await self.client.set(f"{AGENT_STATUS_KEY_PREFIX}:{agent_name}", json.dumps(status))

    async def get_all_agent_statuses(self) -> dict[str, dict[str, Any]]:
        statuses: dict[str, dict[str, Any]] = {}
        async for key in self.client.scan_iter(match=f"{AGENT_STATUS_KEY_PREFIX}:*"):
            agent_name = key.split(":")[-1]
            raw = await self.client.get(key)
            if raw:
                statuses[agent_name] = json.loads(raw)
        return statuses


redis_client = RedisClient()
