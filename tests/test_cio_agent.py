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

    async def fake_call_llm(messages, system_prompt, max_tokens=1000):
        return valid_json

    monkeypatch.setattr(agent, "_call_llm", fake_call_llm)

    regime = await agent.run(batch)
    assert regime.regime == "RISK_ON"
    assert regime.posture == "AGGRESSIVE"


@pytest.mark.asyncio
async def test_invalid_json_falls_back_to_ranging_defensive(agent, monkeypatch):
    batch = _signal_batch()

    async def fake_call_llm(messages, system_prompt, max_tokens=1000):
        return "not valid json at all"

    monkeypatch.setattr(agent, "_call_llm", fake_call_llm)

    regime = await agent.run(batch)
    assert regime.regime == "RANGING"
    assert regime.posture == "DEFENSIVE"
    assert regime.posture_multiplier == 0.3


@pytest.mark.asyncio
async def test_llm_call_failure_falls_back(agent, monkeypatch):
    batch = _signal_batch()

    async def fake_call_llm(messages, system_prompt, max_tokens=1000):
        raise RuntimeError("API down")

    monkeypatch.setattr(agent, "_call_llm", fake_call_llm)

    regime = await agent.run(batch)
    assert regime.regime == "RANGING"
    assert regime.posture == "DEFENSIVE"


@pytest.mark.asyncio
async def test_fallback_pads_citations_when_fewer_than_three_signals(agent, monkeypatch):
    batch = _signal_batch(n=1)

    async def fake_call_llm(messages, system_prompt, max_tokens=1000):
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

    async def fake_call_llm(messages, system_prompt, max_tokens=1000):
        return invalid_json

    monkeypatch.setattr(agent, "_call_llm", fake_call_llm)

    regime = await agent.run(batch)
    assert regime.regime == "RANGING"
