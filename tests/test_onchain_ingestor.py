import json
import time
from types import SimpleNamespace

import pytest

import src.ingestors.onchain_ingestor as onchain_module
from src.ingestors.onchain_ingestor import OnChainIngestor, _to_okx_inst_family, _to_okx_inst_id


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


def _funding_response(rate: float) -> dict:
    return {"code": "0", "data": [{"fundingRate": str(rate)}], "msg": ""}


def _open_interest_response(oi_usd: float) -> dict:
    return {"code": "0", "data": [{"oiUsd": str(oi_usd)}], "msg": ""}


def _liquidation_response(entries: list[tuple[float, float, float]]) -> dict:
    """entries: list of (sz, bkPx, ts_ms)"""
    details = [{"sz": str(sz), "bkPx": str(px), "ts": str(int(ts))} for sz, px, ts in entries]
    return {
        "code": "0",
        "data": [{"instId": "BTC-USDT-SWAP", "instFamily": "BTC-USDT", "details": details}],
        "msg": "",
    }


def test_symbol_mapping():
    assert _to_okx_inst_id("BTC-USD") == "BTC-USDT-SWAP"
    assert _to_okx_inst_family("BTC-USD") == "BTC-USDT"


class TestFetchFundingRate:
    @pytest.mark.asyncio
    async def test_parses_funding_rate(self, ingestor, monkeypatch):
        ingestor_obj, _ = ingestor

        async def fake_fetch(url, params):
            return _funding_response(-0.0001)

        monkeypatch.setattr(ingestor_obj, "_fetch", fake_fetch)
        result = await ingestor_obj._fetch_funding_rate("BTC-USD")
        assert result == -0.0001

    @pytest.mark.asyncio
    async def test_returns_none_on_failure(self, ingestor, monkeypatch):
        ingestor_obj, _ = ingestor

        async def fake_fetch(url, params):
            raise RuntimeError("502 Bad Gateway")

        monkeypatch.setattr(ingestor_obj, "_fetch", fake_fetch)
        result = await ingestor_obj._fetch_funding_rate("BTC-USD")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_empty_data(self, ingestor, monkeypatch):
        ingestor_obj, _ = ingestor

        async def fake_fetch(url, params):
            return {"code": "0", "data": [], "msg": ""}

        monkeypatch.setattr(ingestor_obj, "_fetch", fake_fetch)
        result = await ingestor_obj._fetch_funding_rate("BTC-USD")
        assert result is None


class TestFetchOpenInterest:
    @pytest.mark.asyncio
    async def test_parses_open_interest_usd(self, ingestor, monkeypatch):
        ingestor_obj, _ = ingestor

        async def fake_fetch(url, params):
            return _open_interest_response(1_946_391_688.22)

        monkeypatch.setattr(ingestor_obj, "_fetch", fake_fetch)
        result = await ingestor_obj._fetch_open_interest("BTC-USD")
        assert result == pytest.approx(1_946_391_688.22)


class TestFetchLiquidations:
    @pytest.mark.asyncio
    async def test_sums_recent_liquidations(self, ingestor, monkeypatch):
        ingestor_obj, _ = ingestor
        now_ms = time.time() * 1000

        async def fake_fetch(url, params):
            return _liquidation_response([
                (1.0, 65000.0, now_ms - 1000),  # within 24h
                (2.0, 64000.0, now_ms - 2000),  # within 24h
            ])

        monkeypatch.setattr(ingestor_obj, "_fetch", fake_fetch)
        result = await ingestor_obj._fetch_liquidations_24h("BTC-USD")
        assert result == pytest.approx(65000.0 + 2 * 64000.0)

    @pytest.mark.asyncio
    async def test_excludes_entries_older_than_24h(self, ingestor, monkeypatch):
        ingestor_obj, _ = ingestor
        now_ms = time.time() * 1000
        day_ms = 24 * 60 * 60 * 1000

        async def fake_fetch(url, params):
            return _liquidation_response([
                (1.0, 65000.0, now_ms - 1000),       # within 24h
                (10.0, 65000.0, now_ms - day_ms * 2),  # 48h ago — excluded
            ])

        monkeypatch.setattr(ingestor_obj, "_fetch", fake_fetch)
        result = await ingestor_obj._fetch_liquidations_24h("BTC-USD")
        assert result == pytest.approx(65000.0)

    @pytest.mark.asyncio
    async def test_handles_dollar_ref_deduped_groups(self, ingestor, monkeypatch):
        # OKX's response sometimes includes JSON-reference duplicate groups
        # (no "details" key) alongside the one real group — must not crash.
        ingestor_obj, _ = ingestor
        now_ms = time.time() * 1000

        async def fake_fetch(url, params):
            return {
                "code": "0",
                "data": [
                    {"instId": "BTC-USDT-SWAP", "details": [
                        {"sz": "1.0", "bkPx": "65000.0", "ts": str(int(now_ms - 1000))},
                    ]},
                    {"$ref": "$.data[0]"},
                ],
                "msg": "",
            }

        monkeypatch.setattr(ingestor_obj, "_fetch", fake_fetch)
        result = await ingestor_obj._fetch_liquidations_24h("BTC-USD")
        assert result == pytest.approx(65000.0)

    @pytest.mark.asyncio
    async def test_returns_none_on_failure(self, ingestor, monkeypatch):
        ingestor_obj, _ = ingestor

        async def fake_fetch(url, params):
            raise RuntimeError("down")

        monkeypatch.setattr(ingestor_obj, "_fetch", fake_fetch)
        result = await ingestor_obj._fetch_liquidations_24h("BTC-USD")
        assert result is None


class TestIngestAsset:
    @pytest.mark.asyncio
    async def test_partial_failure_does_not_discard_successful_metrics(self, ingestor, monkeypatch):
        ingestor_obj, fake_redis = ingestor

        async def fake_fetch_funding(asset):
            return 0.0001

        async def fake_fetch_oi(asset):
            return 500_000_000.0

        async def fake_fetch_liq(asset):
            raise RuntimeError("liquidation endpoint down")

        monkeypatch.setattr(ingestor_obj, "_fetch_funding_rate", fake_fetch_funding)
        monkeypatch.setattr(ingestor_obj, "_fetch_open_interest", fake_fetch_oi)
        # _fetch_liquidations_24h itself already catches exceptions internally and
        # returns None — simulate that contract directly.
        monkeypatch.setattr(ingestor_obj, "_fetch_liquidations_24h", AsyncMockReturningNone())

        await ingestor_obj._ingest_asset("BTC-USD")

        stored = fake_redis.client.stored.get("onchain:raw:BTC-USD")
        assert stored is not None
        payload = json.loads(stored)
        assert payload["funding_rate"] == 0.0001
        assert payload["open_interest_usd"] == 500_000_000.0
        assert payload["liquidations_24h_usd"] is None

    @pytest.mark.asyncio
    async def test_all_metrics_failing_skips_storage(self, ingestor, monkeypatch):
        ingestor_obj, fake_redis = ingestor

        monkeypatch.setattr(ingestor_obj, "_fetch_funding_rate", AsyncMockReturningNone())
        monkeypatch.setattr(ingestor_obj, "_fetch_open_interest", AsyncMockReturningNone())
        monkeypatch.setattr(ingestor_obj, "_fetch_liquidations_24h", AsyncMockReturningNone())

        await ingestor_obj._ingest_asset("BTC-USD")

        assert "onchain:raw:BTC-USD" not in fake_redis.client.stored


class AsyncMockReturningNone:
    async def __call__(self, *args, **kwargs):
        return None
