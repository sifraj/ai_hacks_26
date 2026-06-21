import pytest

from src.agents.cio_agent import CIOAgent
from src.schemas.signals import Signal, SignalBatch


def _signal_batch(n=3) -> SignalBatch:
    signals = [
        Signal(
            timestamp="2026-06-20T00:00:00Z",
            source_agent="momentum_analyst",
            asset="BTC-USD",
            direction="LONG",
            confidence_score=0.6,
            horizon_hours=4,
        )
        for _ in range(n)
    ]
    return SignalBatch(tick_id="t1", timestamp="2026-06-20T00:00:00Z", signals=signals)


@pytest.fixture
def agent():
    return CIOAgent()


@pytest.mark.asyncio
async def test_valid_llm_response_parsed_into_regime(agent, monkeypatch):
    batch = _signal_batch()
    valid_json = (
        '{"tick_id": "t1", "timestamp": "2026-06-20T00:00:00Z", "regime": "RISK_ON", '
        '"posture": "AGGRESSIVE", "posture_multiplier": 1.0, '
        '"regime_rationale": "strong momentum across BTC, ETH, SOL", '
        '"signal_ids_cited": ["a", "b", "c"]}'
    )

    async def fake_call_llm(messages, system_prompt, max_tokens=1000, **_kw):
        return valid_json

    monkeypatch.setattr(agent, "_call_llm", fake_call_llm)

    regime = await agent.run(batch)
    assert regime.regime == "RISK_ON"
    assert regime.posture == "AGGRESSIVE"


@pytest.mark.asyncio
async def test_invalid_json_falls_back_to_ranging_defensive(agent, monkeypatch):
    batch = _signal_batch()

    async def fake_call_llm(messages, system_prompt, max_tokens=1000, **_kw):
        return "not valid json at all"

    monkeypatch.setattr(agent, "_call_llm", fake_call_llm)

    regime = await agent.run(batch)
    assert regime.regime == "RANGING"
    assert regime.posture == "DEFENSIVE"
    assert regime.posture_multiplier == 0.3


@pytest.mark.asyncio
async def test_llm_call_failure_falls_back(agent, monkeypatch):
    batch = _signal_batch()

    async def fake_call_llm(messages, system_prompt, max_tokens=1000, **_kw):
        raise RuntimeError("API down")

    monkeypatch.setattr(agent, "_call_llm", fake_call_llm)

    regime = await agent.run(batch)
    assert regime.regime == "RANGING"
    assert regime.posture == "DEFENSIVE"


@pytest.mark.asyncio
async def test_fallback_pads_citations_when_fewer_than_three_signals(agent, monkeypatch):
    batch = _signal_batch(n=1)

    async def fake_call_llm(messages, system_prompt, max_tokens=1000, **_kw):
        raise RuntimeError("API down")

    monkeypatch.setattr(agent, "_call_llm", fake_call_llm)

    regime = await agent.run(batch)
    assert len(regime.signal_ids_cited) >= 3


@pytest.mark.asyncio
async def test_schema_invalid_response_falls_back(agent, monkeypatch):
    batch = _signal_batch()
    # posture_multiplier 0.5 is not an allowed enum value -> validation failure.
    invalid_json = (
        '{"tick_id": "t1", "timestamp": "2026-06-20T00:00:00Z", "regime": "RISK_ON", '
        '"posture": "AGGRESSIVE", "posture_multiplier": 0.5, '
        '"regime_rationale": "x", "signal_ids_cited": ["a", "b", "c"]}'
    )

    async def fake_call_llm(messages, system_prompt, max_tokens=1000, **_kw):
        return invalid_json

    monkeypatch.setattr(agent, "_call_llm", fake_call_llm)

    regime = await agent.run(batch)
    assert regime.regime == "RANGING"


@pytest.mark.asyncio
async def test_markdown_fenced_response_is_parsed_not_fallback(agent, monkeypatch):
    batch = _signal_batch()
    fenced_json = (
        '```json\n'
        '{"tick_id": "t1", "timestamp": "2026-06-20T00:00:00Z", "regime": "RISK_ON", '
        '"posture": "AGGRESSIVE", "posture_multiplier": 1.0, '
        '"regime_rationale": "strong momentum", "signal_ids_cited": ["a", "b", "c"]}\n'
        '```'
    )

    async def fake_call_llm(messages, system_prompt, max_tokens=1000, **_kw):
        return fenced_json

    monkeypatch.setattr(agent, "_call_llm", fake_call_llm)

    regime = await agent.run(batch)
    assert regime.regime == "RISK_ON"
    assert regime.regime_rationale == "strong momentum"


@pytest.mark.asyncio
async def test_aliased_field_names_are_recovered_not_fallback(agent, monkeypatch):
    batch = _signal_batch()
    real_id = batch.signals[0].signal_id
    aliased_json = (
        '{"tick_id": "t1", "timestamp": "2026-06-20T00:00:00Z", "regime": "RANGING", '
        '"posture": "NEUTRAL", "posture_scalar": 0.6, '
        f'"regime_rationale": "mixed signals", "key_signals_cited": ["{real_id}"]}}'
    )

    async def fake_call_llm(messages, system_prompt, max_tokens=1000, **_kw):
        return aliased_json

    monkeypatch.setattr(agent, "_call_llm", fake_call_llm)

    regime = await agent.run(batch)
    # Recovered Claude's real judgment, not the hardcoded fallback.
    assert regime.regime == "RANGING"
    assert regime.posture == "NEUTRAL"
    assert regime.posture_multiplier == 0.6
    assert regime.regime_rationale == "mixed signals"
    assert real_id in regime.signal_ids_cited
    assert len(regime.signal_ids_cited) >= 3


@pytest.mark.asyncio
async def test_recovery_pads_with_real_signal_ids_when_few_cited(agent, monkeypatch):
    batch = _signal_batch(n=5)
    aliased_json = (
        '{"tick_id": "t1", "timestamp": "2026-06-20T00:00:00Z", "regime": "RANGING", '
        '"posture": "NEUTRAL", "posture_multiplier": 0.6, '
        '"regime_rationale": "thin data", "signal_ids_cited": []}'
    )

    async def fake_call_llm(messages, system_prompt, max_tokens=1000, **_kw):
        return aliased_json

    monkeypatch.setattr(agent, "_call_llm", fake_call_llm)

    regime = await agent.run(batch)
    assert regime.regime_rationale == "thin data"  # real judgment preserved
    assert len(regime.signal_ids_cited) >= 3
    real_ids = {s.signal_id for s in batch.signals}
    assert all(sid in real_ids for sid in regime.signal_ids_cited)
