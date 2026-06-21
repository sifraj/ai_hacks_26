import pytest

from src.harness.tool_registry import ToolRegistry, ToolAccessDeniedError


@pytest.fixture
def registry():
    return ToolRegistry()


@pytest.mark.asyncio
async def test_register_and_get(registry):
    async def my_tool(**kwargs):
        return "result"

    registry.register("my_tool", my_tool)
    assert registry.get("my_tool") is my_tool


def test_get_unregistered_tool_raises_keyerror(registry):
    with pytest.raises(KeyError):
        registry.get("nonexistent")


@pytest.mark.asyncio
async def test_call_allowed_tool_succeeds(registry):
    async def my_tool(value: int) -> int:
        return value * 2

    registry.register("my_tool", my_tool)
    result = await registry.call("my_tool", allowed_tools=["my_tool"], agent_name="tester", value=5)
    assert result == 10


@pytest.mark.asyncio
async def test_call_disallowed_tool_raises(registry):
    async def my_tool(**kwargs):
        return "result"

    registry.register("my_tool", my_tool)
    with pytest.raises(ToolAccessDeniedError):
        await registry.call("my_tool", allowed_tools=["other_tool"], agent_name="tester")


@pytest.mark.asyncio
async def test_call_with_no_allowed_tools_restriction_succeeds(registry):
    async def my_tool(**kwargs):
        return "unrestricted"

    registry.register("my_tool", my_tool)
    result = await registry.call("my_tool", agent_name="tester")
    assert result == "unrestricted"


@pytest.mark.asyncio
async def test_call_sync_tool_function_works(registry):
    def sync_tool(value: int) -> int:
        return value + 1

    registry.register("sync_tool", sync_tool)
    result = await registry.call("sync_tool", allowed_tools=["sync_tool"], value=41)
    assert result == 42
