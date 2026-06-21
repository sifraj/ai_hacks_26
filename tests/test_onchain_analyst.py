import fnmatch
import json
from types import SimpleNamespace

import pytest

import src.agents.analysts.onchain_analyst as onchain_module
from src.agents.analysts.onchain_analyst import OnChainAnalyst


class FakeRawRedisClient:
    def __init__(self, data: dict[str, str] | None = None, ttls: dict[str, int] | None = None) -> None:
        self._data = data or {}
        self._ttls = ttls or {}

    async def scan_iter(self, match: str):
        for key in list(self._data.keys()):
            if fnmatch.fnmatch(key, match):
                yield key

    async def get(self, key: str):
        return self._data.get(key)

    async def ttl(self, key: str):
        return self._ttls.get(key, -2)


@pytest.fixture
def analyst():
    return OnChainAnalyst()


class TestFetchFreshOnchainData:
    @pytest.mark.asyncio
    async def test_fresh_data_is_included(self, analyst, monkeypatch):
        monkeypatch.setattr(onchain_module, "ONCHAIN_TTL_SECONDS", 3600)  # 60 min
        fake_raw = FakeRawRedisClient(
            data={"onchain:raw:BTC-USD": json.dumps({"funding_rate": 0.01})},
            ttls={"onchain:raw:BTC-USD": 3000},  # age = 600s = 10min, fresh
        )
        monkeypatch.setattr(onchain_module, "redis_client", SimpleNamespace(client=fake_raw))

        result = await analyst._fetch_fresh_onchain_data()
        assert "BTC-USD" in result

    @pytest.mark.asyncio
    async def test_stale_data_is_excluded(self, analyst, monkeypatch):
        monkeypatch.setattr(onchain_module, "ONCHAIN_TTL_SECONDS", 3600)  # 60 min
        fake_raw = FakeRawRedisClient(
            data={"onchain:raw:BTC-USD": json.dumps({"funding_rate": 0.01})},
            ttls={"onchain:raw:BTC-USD": 600},  # age = 3000s = 50min > 45min limit
        )
        monkeypatch.setattr(onchain_module, "redis_client", SimpleNamespace(client=fake_raw))

        result = await analyst._fetch_fresh_onchain_data()
        assert result == {}

    @pytest.mark.asyncio
    async def test_missing_key_excluded(self, analyst, monkeypatch):
        fake_raw = FakeRawRedisClient(data={}, ttls={})
        monkeypatch.setattr(onchain_module, "redis_client", SimpleNamespace(client=fake_raw))

        result = await analyst._fetch_fresh_onchain_data()
        assert result == {}


class TestParseSignals:
    def test_valid_json_parses(self, analyst):
        raw = json.dumps([
            {
                "asset": "BTC-USD",
                "direction": "SHORT",
                "confidence_score": 0.7,
                "horizon_hours": 48,
                "supporting_factors": ["rising funding rate"],
            }
        ])
        signals = analyst._parse_signals(raw, "BTC-USD")
        assert len(signals) == 1
        assert signals[0].source_agent == "onchain_analyst"

    def test_mismatched_asset_rejected(self, analyst):
        raw = json.dumps([
            {"asset": "ETH-USD", "direction": "LONG", "confidence_score": 0.5, "horizon_hours": 48}
        ])
        signals = analyst._parse_signals(raw, "BTC-USD")
        assert signals == []

    def test_empty_array_is_valid(self, analyst):
        signals = analyst._parse_signals("[]", "BTC-USD")
        assert signals == []

    def test_invalid_json_raises(self, analyst):
        with pytest.raises(json.JSONDecodeError):
            analyst._parse_signals("nope", "BTC-USD")


class TestAnalyzeAsset:
    @pytest.mark.asyncio
    async def test_retries_once_then_succeeds(self, analyst, monkeypatch):
        calls = {"n": 0}
        valid_json = json.dumps([
            {"asset": "BTC-USD", "direction": "SHORT", "confidence_score": 0.6, "horizon_hours": 24}
        ])

        async def fake_call_llm(messages, system_prompt, max_tokens=1000):
            calls["n"] += 1
            return "garbage" if calls["n"] == 1 else valid_json

        monkeypatch.setattr(analyst, "_call_llm", fake_call_llm)

        signals = await analyst._analyze_asset("BTC-USD", {"funding_rate": 0.02})
        assert calls["n"] == 2
        assert len(signals) == 1

    @pytest.mark.asyncio
    async def test_gives_up_after_retry_failure(self, analyst, monkeypatch):
        async def fake_call_llm(messages, system_prompt, max_tokens=1000):
            return "still garbage"

        monkeypatch.setattr(analyst, "_call_llm", fake_call_llm)

        signals = await analyst._analyze_asset("BTC-USD", {"funding_rate": 0.02})
        assert signals == []


class TestRunImpl:
    @pytest.mark.asyncio
    async def test_no_fresh_data_returns_empty(self, analyst, monkeypatch):
        async def fake_fetch():
            return {}

        monkeypatch.setattr(analyst, "_fetch_fresh_onchain_data", fake_fetch)
        result = await analyst._run_impl({})
        assert result == {"signals": []}
