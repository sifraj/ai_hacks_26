from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.agents.base_agent import BaseAgent
import src.harness.tool_registry as tool_registry_module
from src.harness.tool_registry import ToolAccessDeniedError


class EchoAgent(BaseAgent):
    def __init__(self, allowed_tools=None):
        super().__init__(name="echo_agent", allowed_tools=allowed_tools or [])

    async def _run_impl(self, context):
        return {"echo": context}


@pytest.fixture
def agent():
    return EchoAgent(allowed_tools=["read_signals"])


@pytest.mark.asyncio
async def test_run_calls_run_impl_and_returns_result(agent):
    result = await agent.run({"foo": "bar"})
    assert result == {"echo": {"foo": "bar"}}


@pytest.mark.asyncio
async def test_run_logs_start_and_end(agent, monkeypatch):
    events = []

    class FakeLogger:
        def info(self, msg, **kwargs):
            events.append((msg, kwargs))

        def error(self, msg, **kwargs):
            events.append((msg, kwargs))

    agent.logger = FakeLogger()
    await agent.run({"foo": "bar"})

    event_names = [e[0] for e in events]
    assert "agent_run_start" in event_names
    assert "agent_run_end" in event_names
    end_event = next(e for e in events if e[0] == "agent_run_end")
    assert "latency_ms" in end_event[1]["payload"]


@pytest.mark.asyncio
async def test_use_tool_allowed_succeeds(agent, monkeypatch):
    called = {}

    async def fake_read_signals(**kwargs):
        called.update(kwargs)
        return ["signal1"]

    monkeypatch.setattr(tool_registry_module.tool_registry, "_tools", {"read_signals": fake_read_signals})

    result = await agent._use_tool("read_signals", asset="BTC-USD")
    assert result == ["signal1"]
    assert called == {"asset": "BTC-USD"}


@pytest.mark.asyncio
async def test_use_tool_disallowed_raises(agent, monkeypatch):
    async def fake_write_signal(**kwargs):
        return None

    monkeypatch.setattr(tool_registry_module.tool_registry, "_tools", {"write_signal": fake_write_signal})

    with pytest.raises(ToolAccessDeniedError):
        await agent._use_tool("write_signal", asset="BTC-USD", signal={})


@pytest.mark.asyncio
async def test_call_llm_returns_text_and_logs(agent):
    fake_response = SimpleNamespace(
        content=[SimpleNamespace(text="hello world")],
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )
    agent._anthropic.messages.create = AsyncMock(return_value=fake_response)

    events = []

    class FakeLogger:
        def info(self, msg, **kwargs):
            events.append((msg, kwargs))

        def error(self, msg, **kwargs):
            events.append((msg, kwargs))

    agent.logger = FakeLogger()

    result = await agent._call_llm(messages=[{"role": "user", "content": "hi"}], system_prompt="sys")

    assert result == "hello world"
    success_event = next(e for e in events if e[0] == "llm_call_success")
    assert success_event[1]["payload"]["prompt_tokens"] == 10
    assert success_event[1]["payload"]["completion_tokens"] == 5


@pytest.mark.asyncio
async def test_call_llm_logs_and_reraises_on_failure(agent):
    agent._anthropic.messages.create = AsyncMock(side_effect=RuntimeError("boom"))

    events = []

    class FakeLogger:
        def info(self, msg, **kwargs):
            events.append((msg, kwargs))

        def error(self, msg, **kwargs):
            events.append((msg, kwargs))

    agent.logger = FakeLogger()

    with pytest.raises(RuntimeError):
        await agent._call_llm(messages=[{"role": "user", "content": "hi"}], system_prompt="sys")

    assert any(e[0] == "llm_call_failed" for e in events)
