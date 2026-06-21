import json

import pytest

from src.agents.portfolio_manager import PortfolioManager, MAX_PROPOSED_TRADES
from src.schemas.portfolio import PortfolioState
from src.schemas.regime import MarketRegime
from src.schemas.signals import SignalBatch


def _signal_batch() -> SignalBatch:
    return SignalBatch(tick_id="t1", timestamp="2026-06-20T00:00:00Z", signals=[])


def _regime() -> MarketRegime:
    return MarketRegime(
        tick_id="t1", timestamp="2026-06-20T00:00:00Z", regime="RISK_ON", posture="AGGRESSIVE",
        posture_multiplier=1.0, regime_rationale="x", signal_ids_cited=["a", "b", "c"],
    )


def _state() -> PortfolioState:
    return PortfolioState(
        timestamp="2026-06-20T00:00:00Z", total_value_usd=100_000.0, cash_usd=100_000.0,
        positions=[], session_high_usd=100_000.0, daily_pnl_usd=0.0, daily_pnl_pct=0.0,
        drawdown_from_session_high_pct=0.0, kill_switch=False,
    )


@pytest.fixture
def manager():
    return PortfolioManager()


@pytest.mark.asyncio
async def test_valid_response_parsed_into_trades(manager, monkeypatch):
    valid_json = json.dumps([
        {
            "asset": "BTC-USD", "side": "BUY", "order_type": "MARKET", "size_usd": 2000.0,
            "stop_loss_pct": 0.02, "trade_rationale": "momentum + sentiment agree",
            "signal_ids": ["s1", "s2"], "confidence_composite": 0.7,
        }
    ])

    async def fake_call_llm(messages, system_prompt, max_tokens=2000):
        return valid_json

    monkeypatch.setattr(manager, "_call_llm", fake_call_llm)

    trades = await manager.run(_signal_batch(), _regime(), _state())
    assert len(trades) == 1
    assert trades[0].asset == "BTC-USD"
    assert trades[0].tick_id == "t1"


@pytest.mark.asyncio
async def test_llm_failure_returns_empty_list(manager, monkeypatch):
    async def fake_call_llm(messages, system_prompt, max_tokens=2000):
        raise RuntimeError("API down")

    monkeypatch.setattr(manager, "_call_llm", fake_call_llm)

    trades = await manager.run(_signal_batch(), _regime(), _state())
    assert trades == []


@pytest.mark.asyncio
async def test_invalid_json_returns_empty_list(manager, monkeypatch):
    async def fake_call_llm(messages, system_prompt, max_tokens=2000):
        return "not json"

    monkeypatch.setattr(manager, "_call_llm", fake_call_llm)

    trades = await manager.run(_signal_batch(), _regime(), _state())
    assert trades == []


@pytest.mark.asyncio
async def test_invalid_trade_items_are_skipped_others_kept(manager, monkeypatch):
    valid_json = json.dumps([
        {"asset": "BTC-USD", "side": "BUY", "order_type": "MARKET", "size_usd": 2000.0,
         "stop_loss_pct": 0.02, "trade_rationale": "x", "confidence_composite": 1.5},  # invalid: >1.0
        {"asset": "ETH-USD", "side": "BUY", "order_type": "MARKET", "size_usd": 1000.0,
         "stop_loss_pct": 0.02, "trade_rationale": "x", "confidence_composite": 0.5},
    ])

    async def fake_call_llm(messages, system_prompt, max_tokens=2000):
        return valid_json

    monkeypatch.setattr(manager, "_call_llm", fake_call_llm)

    trades = await manager.run(_signal_batch(), _regime(), _state())
    assert len(trades) == 1
    assert trades[0].asset == "ETH-USD"


@pytest.mark.asyncio
async def test_capped_at_max_proposed_trades(manager, monkeypatch):
    real_assets = [
        "BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD",
        "ADA-USD", "AVAX-USD", "DOT-USD",
    ]
    items = [
        {"asset": asset, "side": "BUY", "order_type": "MARKET", "size_usd": 1000.0,
         "stop_loss_pct": 0.02, "trade_rationale": "x", "confidence_composite": 0.5}
        for asset in real_assets
    ]
    valid_json = json.dumps(items)

    async def fake_call_llm(messages, system_prompt, max_tokens=2000):
        return valid_json

    monkeypatch.setattr(manager, "_call_llm", fake_call_llm)

    trades = await manager.run(_signal_batch(), _regime(), _state())
    assert len(trades) == MAX_PROPOSED_TRADES


def _signal_batch_with_signals() -> SignalBatch:
    from src.schemas.signals import Signal

    signal = Signal(
        timestamp="2026-06-20T00:00:00Z", source_agent="momentum_analyst", asset="BTC-USD",
        direction="LONG", confidence_score=0.6, horizon_hours=4,
    )
    return SignalBatch(tick_id="t1", timestamp="2026-06-20T00:00:00Z", signals=[signal])


@pytest.mark.asyncio
async def test_unknown_asset_is_rejected(manager, monkeypatch):
    valid_json = json.dumps([
        {"asset": "DOGE-USD", "side": "BUY", "order_type": "MARKET", "size_usd": 1000.0,
         "stop_loss_pct": 0.02, "trade_rationale": "x", "confidence_composite": 0.5},
    ])

    async def fake_call_llm(messages, system_prompt, max_tokens=2000):
        return valid_json

    monkeypatch.setattr(manager, "_call_llm", fake_call_llm)

    trades = await manager.run(_signal_batch(), _regime(), _state())
    assert trades == []


@pytest.mark.asyncio
async def test_hallucinated_signal_ids_are_sanitized_not_rejected(manager, monkeypatch):
    batch = _signal_batch_with_signals()
    real_id = batch.signals[0].signal_id
    valid_json = json.dumps([
        {"asset": "BTC-USD", "side": "BUY", "order_type": "MARKET", "size_usd": 1000.0,
         "stop_loss_pct": 0.02, "trade_rationale": "x", "confidence_composite": 0.5,
         "signal_ids": [real_id, "hallucinated-id-123"]},
    ])

    async def fake_call_llm(messages, system_prompt, max_tokens=2000):
        return valid_json

    monkeypatch.setattr(manager, "_call_llm", fake_call_llm)

    trades = await manager.run(batch, _regime(), _state())
    assert len(trades) == 1
    assert trades[0].signal_ids == [real_id]


@pytest.mark.asyncio
async def test_negative_size_rejected_by_schema(manager, monkeypatch):
    valid_json = json.dumps([
        {"asset": "BTC-USD", "side": "BUY", "order_type": "MARKET", "size_usd": -500.0,
         "stop_loss_pct": 0.02, "trade_rationale": "x", "confidence_composite": 0.5},
    ])

    async def fake_call_llm(messages, system_prompt, max_tokens=2000):
        return valid_json

    monkeypatch.setattr(manager, "_call_llm", fake_call_llm)

    trades = await manager.run(_signal_batch(), _regime(), _state())
    assert trades == []
