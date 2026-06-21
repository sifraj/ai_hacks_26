import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import src.ingestors.onchain_ingestor as onchain_module
from src.ingestors.onchain_ingestor import OnChainIngestor


class FakeRawRedisClient:
    def __init__(self) -> None:
        self.stored: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.stored[key] = value


@pytest.fixture
def ingestor(monkeypatch):
    fake_redis = SimpleNamespace(client=FakeRawRedisClient())
    monkeypatch.setattr(onchain_module, "redis_client", fake_redis)
    return OnChainIngestor(), fake_redis


@pytest.mark.asyncio
async def test_liquidation_failure_does_not_discard_successful_metrics(ingestor, monkeypatch):
    ingestor_obj, fake_redis = ingestor

    async def fake_fetch(url, params):
        if "liquidation" in url:
            raise RuntimeError("500 Internal Server Error")
        return {"data": [{"value": 0.01}]}

    monkeypatch.setattr(ingestor_obj, "_fetch", fake_fetch)

    await ingestor_obj._ingest_asset("BTC-USD")

    stored = fake_redis.client.stored.get("onchain:raw:BTC-USD")
    assert stored is not None
    payload = json.loads(stored)
    assert payload["funding_rate"] == 0.01
    assert payload["open_interest_usd"] == 0.01
    assert payload["liquidations_24h_usd"] is None


@pytest.mark.asyncio
async def test_all_metrics_failing_skips_storage(ingestor, monkeypatch):
    ingestor_obj, fake_redis = ingestor

    async def fake_fetch(url, params):
        raise RuntimeError("down")

    monkeypatch.setattr(ingestor_obj, "_fetch", fake_fetch)

    await ingestor_obj._ingest_asset("BTC-USD")

    assert "onchain:raw:BTC-USD" not in fake_redis.client.stored


@pytest.mark.asyncio
async def test_all_metrics_succeeding_stores_full_payload(ingestor, monkeypatch):
    ingestor_obj, fake_redis = ingestor

    async def fake_fetch(url, params):
        return {"data": [{"value": 5.0}]}

    monkeypatch.setattr(ingestor_obj, "_fetch", fake_fetch)

    await ingestor_obj._ingest_asset("ETH-USD")

    stored = fake_redis.client.stored.get("onchain:raw:ETH-USD")
    payload = json.loads(stored)
    assert payload["funding_rate"] == 5.0
    assert payload["open_interest_usd"] == 5.0
    assert payload["liquidations_24h_usd"] == 5.0
