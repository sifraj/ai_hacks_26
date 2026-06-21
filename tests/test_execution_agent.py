from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import src.agents.execution_agent as execution_module
from src.agents.execution_agent import ExecutionAgent
from src.schemas.trades import ClearedTrade, Fill, ProposedTrade


class FakeRawRedisClient:
    def __init__(self) -> None:
        self.pushed: list[str] = []

    async def lpush(self, key: str, value: str) -> None:
        self.pushed.append(value)


def _cleared(**overrides) -> ClearedTrade:
    defaults = dict(
        proposal_id="p1", asset="BTC-USD", side="BUY", order_type="MARKET",
        final_size_usd=2000.0, stop_loss_pct=0.02, compliance_checks_passed=["RULE_001"],
    )
    defaults.update(overrides)
    return ClearedTrade(**defaults)


def _proposed(**overrides) -> ProposedTrade:
    defaults = dict(
        proposal_id="p1", tick_id="t1", asset="BTC-USD", side="BUY", order_type="MARKET",
        size_usd=2000.0, stop_loss_pct=0.02, trade_rationale="x",
        signal_ids=["s1", "s2"], confidence_composite=0.6,
    )
    defaults.update(overrides)
    return ProposedTrade(**defaults)


def _fill(**overrides) -> Fill:
    defaults = dict(
        cleared_id="c1", asset="BTC-USD", side="BUY", filled_size_usd=2000.0,
        fill_price=65000.0, fee_usd=12.0, timestamp="2026-06-20T00:00:00Z",
    )
    defaults.update(overrides)
    return Fill(**defaults)


@pytest.fixture
def agent(monkeypatch):
    fake_redis = SimpleNamespace(client=FakeRawRedisClient())
    monkeypatch.setattr(execution_module, "redis_client", fake_redis)
    return ExecutionAgent(), fake_redis


@pytest.mark.asyncio
async def test_executes_and_pushes_fill_to_queue(agent, monkeypatch):
    execution_agent, fake_redis = agent
    fake_fill = _fill()
    monkeypatch.setattr(
        execution_module.paper_engine, "execute_paper_order", AsyncMock(return_value=fake_fill)
    )

    fills = await execution_agent.run([_cleared()], [_proposed()])

    assert len(fills) == 1
    assert fills[0] == fake_fill
    assert len(fake_redis.client.pushed) == 1


@pytest.mark.asyncio
async def test_paper_trading_disabled_raises_and_is_caught(agent, monkeypatch):
    execution_agent, fake_redis = agent
    monkeypatch.setattr(execution_module.settings, "paper_trading", False)
    monkeypatch.setattr(
        execution_module.paper_engine, "execute_paper_order", AsyncMock(return_value=_fill())
    )

    fills = await execution_agent.run([_cleared()], [_proposed()])

    assert fills == []
    assert fake_redis.client.pushed == []


@pytest.mark.asyncio
async def test_one_failure_does_not_block_other_fills(agent, monkeypatch):
    execution_agent, fake_redis = agent

    async def fake_execute(trade):
        if trade.asset == "BTC-USD":
            raise RuntimeError("execution failed")
        return _fill(asset=trade.asset, cleared_id=trade.cleared_id)

    monkeypatch.setattr(execution_module.paper_engine, "execute_paper_order", fake_execute)

    cleared = [
        _cleared(proposal_id="p1", asset="BTC-USD"),
        _cleared(proposal_id="p2", asset="ETH-USD"),
    ]
    proposed = [_proposed(proposal_id="p1", asset="BTC-USD"), _proposed(proposal_id="p2", asset="ETH-USD")]

    fills = await execution_agent.run(cleared, proposed)
    assert len(fills) == 1
    assert fills[0].asset == "ETH-USD"


@pytest.mark.asyncio
async def test_works_without_proposed_trades_arg(agent, monkeypatch):
    execution_agent, fake_redis = agent
    monkeypatch.setattr(
        execution_module.paper_engine, "execute_paper_order", AsyncMock(return_value=_fill())
    )

    fills = await execution_agent.run([_cleared()])
    assert len(fills) == 1
