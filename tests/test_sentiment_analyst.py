import fnmatch
import json

import pytest

import src.agents.analysts.sentiment_analyst as sentiment_module
from src.agents.analysts.sentiment_analyst import SentimentAnalyst, MAX_LLM_CALLS_PER_TICK


class FakeRawRedisClient:
    def __init__(self, data: dict[str, str] | None = None) -> None:
        self._data = data or {}

    async def scan_iter(self, match: str):
        for key in list(self._data.keys()):
            if fnmatch.fnmatch(key, match):
                yield key

    async def get(self, key: str):
        return self._data.get(key)


@pytest.fixture
def analyst():
    return SentimentAnalyst()


class TestChunkAssets:
    def test_no_assets_returns_no_batches(self, analyst):
        assert analyst._chunk_assets({}) == []

    def test_few_assets_one_call_per_asset(self, analyst):
        # Under the cap, no batching needed — one call per asset for accuracy.
        raw = {f"ASSET{i}-USD": {"headlines": []} for i in range(3)}
        batches = analyst._chunk_assets(raw)
        assert len(batches) == 3
        all_assets = set()
        for b in batches:
            all_assets.update(b.keys())
        assert all_assets == set(raw.keys())

    def test_many_assets_capped_at_max_batches(self, analyst):
        raw = {f"ASSET{i}-USD": {"headlines": []} for i in range(25)}
        batches = analyst._chunk_assets(raw)
        assert len(batches) <= MAX_LLM_CALLS_PER_TICK
        all_assets = set()
        for b in batches:
            all_assets.update(b.keys())
        assert all_assets == set(raw.keys())


class TestParseSignals:
    def test_valid_json_parses_into_signals(self, analyst):
        raw = json.dumps([
            {
                "asset": "BTC-USD",
                "direction": "LONG",
                "confidence_score": 0.6,
                "horizon_hours": 12,
                "supporting_factors": ["positive regulatory news"],
                "contradicting_factors": [],
            }
        ])
        signals = analyst._parse_signals(raw, {"BTC-USD"})
        assert len(signals) == 1
        assert signals[0].asset == "BTC-USD"
        assert signals[0].source_agent == "sentiment_analyst"

    def test_non_list_json_raises_value_error(self, analyst):
        with pytest.raises(ValueError):
            analyst._parse_signals(json.dumps({"asset": "BTC-USD"}), {"BTC-USD"})

    def test_invalid_json_raises_json_decode_error(self, analyst):
        with pytest.raises(json.JSONDecodeError):
            analyst._parse_signals("not json", {"BTC-USD"})

    def test_unknown_asset_is_rejected(self, analyst):
        raw = json.dumps([
            {
                "asset": "DOGE-USD",
                "direction": "LONG",
                "confidence_score": 0.5,
                "horizon_hours": 12,
            }
        ])
        signals = analyst._parse_signals(raw, {"BTC-USD"})
        assert signals == []

    def test_schema_invalid_item_is_rejected_but_others_kept(self, analyst):
        raw = json.dumps([
            {"asset": "BTC-USD", "direction": "LONG", "confidence_score": 1.5, "horizon_hours": 12},
            {"asset": "BTC-USD", "direction": "LONG", "confidence_score": 0.5, "horizon_hours": 12},
        ])
        signals = analyst._parse_signals(raw, {"BTC-USD"})
        assert len(signals) == 1


class TestAnalyzeBatch:
    @pytest.mark.asyncio
    async def test_succeeds_on_first_try(self, analyst, monkeypatch):
        valid_json = json.dumps([
            {"asset": "BTC-USD", "direction": "LONG", "confidence_score": 0.5, "horizon_hours": 12}
        ])

        async def fake_call_llm(messages, system_prompt, max_tokens=1000):
            return valid_json

        monkeypatch.setattr(analyst, "_call_llm", fake_call_llm)

        signals = await analyst._analyze_batch({"BTC-USD": {"headlines": ["news"]}})
        assert len(signals) == 1

    @pytest.mark.asyncio
    async def test_retries_once_then_succeeds(self, analyst, monkeypatch):
        calls = {"n": 0}
        valid_json = json.dumps([
            {"asset": "BTC-USD", "direction": "LONG", "confidence_score": 0.5, "horizon_hours": 12}
        ])

        async def fake_call_llm(messages, system_prompt, max_tokens=1000):
            calls["n"] += 1
            if calls["n"] == 1:
                return "not valid json"
            return valid_json

        monkeypatch.setattr(analyst, "_call_llm", fake_call_llm)

        signals = await analyst._analyze_batch({"BTC-USD": {"headlines": ["news"]}})
        assert calls["n"] == 2
        assert len(signals) == 1

    @pytest.mark.asyncio
    async def test_gives_up_after_retry_failure(self, analyst, monkeypatch):
        async def fake_call_llm(messages, system_prompt, max_tokens=1000):
            return "still not valid json"

        monkeypatch.setattr(analyst, "_call_llm", fake_call_llm)

        signals = await analyst._analyze_batch({"BTC-USD": {"headlines": ["news"]}})
        assert signals == []


class TestFetchRawSentiment:
    @pytest.mark.asyncio
    async def test_fetches_all_matching_keys(self, analyst, monkeypatch):
        fake_raw = FakeRawRedisClient(
            data={
                "sentiment:raw:BTC-USD": json.dumps({"headlines": ["h1"]}),
                "sentiment:raw:ETH-USD": json.dumps({"headlines": ["h2"]}),
                "onchain:raw:BTC-USD": json.dumps({"funding_rate": 0.01}),
            }
        )
        from types import SimpleNamespace

        monkeypatch.setattr(sentiment_module, "redis_client", SimpleNamespace(client=fake_raw))

        result = await analyst._fetch_raw_sentiment()
        assert set(result.keys()) == {"BTC-USD", "ETH-USD"}


class TestRunImpl:
    @pytest.mark.asyncio
    async def test_no_data_returns_empty_signals(self, analyst, monkeypatch):
        async def fake_fetch():
            return {}

        monkeypatch.setattr(analyst, "_fetch_raw_sentiment", fake_fetch)
        result = await analyst._run_impl({})
        assert result == {"signals": []}
