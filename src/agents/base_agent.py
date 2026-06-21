from __future__ import annotations

import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from anthropic import AsyncAnthropic

from src.config import settings
from src.harness.audit_logger import get_logger
from src.harness.tool_registry import tool_registry

LLM_MODEL = "claude-sonnet-4-6"
SLOW_LATENCY_MS = 5000.0


class LLMBudgetExceeded(Exception):
    """Raised when a tick has consumed its configured LLM-call budget."""


class _LLMBudget:
    """Per-tick global LLM-call budget (cost control). Reset at the start of each
    tick by the agent loop; every _call_llm consumes one unit. Agents already treat
    an LLM failure as a graceful fallback, so exceeding the budget degrades cleanly."""

    def __init__(self) -> None:
        self.count = 0

    def reset(self) -> None:
        self.count = 0

    def check_and_increment(self) -> None:
        if self.count >= settings.max_llm_calls_per_tick:
            raise LLMBudgetExceeded(
                f"per-tick LLM call budget ({settings.max_llm_calls_per_tick}) exhausted"
            )
        self.count += 1


llm_budget = _LLMBudget()


class BaseAgent(ABC):
    def __init__(self, name: str, allowed_tools: list[str], logger=None) -> None:
        self.name = name
        self.allowed_tools = allowed_tools
        self.logger = logger or get_logger(name)
        self._anthropic = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._error_count = 0
        self._last_error: str | None = None

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        start = time.monotonic()
        self.logger.info(
            "agent_run_start",
            event_type="agent_run_start",
            agent_name=self.name,
            payload={"context_keys": list(context.keys())},
        )
        status = "ok"
        try:
            result = await self._run_impl(context)
        except Exception as e:
            status = "error"
            self._error_count += 1
            self._last_error = str(e)
            raise
        finally:
            latency_ms = (time.monotonic() - start) * 1000
            if status == "ok" and latency_ms > SLOW_LATENCY_MS:
                status = "slow"
            timestamp = datetime.now(timezone.utc).isoformat()
            self.logger.info(
                "agent_run_end",
                event_type="agent_run_end",
                agent_name=self.name,
                payload={"latency_ms": latency_ms, "status": status},
            )
            await self._broadcast_status(status, latency_ms, timestamp)
        return result

    async def _broadcast_status(self, status: str, latency_ms: float, timestamp: str) -> None:
        try:
            from src.api.main import broadcast

            await broadcast(
                {
                    "event_type": "agent_status",
                    "timestamp": timestamp,
                    "payload": {
                        "agent_name": self.name,
                        "status": status,
                        "last_run_timestamp": timestamp,
                        "last_latency_ms": latency_ms,
                        "error_count": self._error_count,
                        "last_error": self._last_error,
                    },
                }
            )
        except Exception:
            pass  # a broadcast failure must never break agent execution

    @abstractmethod
    async def _run_impl(self, context: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    async def _call_llm(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
        max_tokens: int = 1000,
        critical: bool = False,
    ) -> str:
        # The per-tick budget caps variable analyst spend. The decision chain
        # (CIO, PM) passes critical=True so a budget exhausted by the analysts can't
        # starve the agents that actually set posture and propose trades.
        if not critical:
            llm_budget.check_and_increment()
        start = time.monotonic()
        try:
            response = await self._anthropic.messages.create(
                model=LLM_MODEL,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=messages,
            )
            latency_ms = (time.monotonic() - start) * 1000
            self.logger.info(
                "llm_call_success",
                event_type="llm_call_success",
                agent_name=self.name,
                payload={
                    "prompt_tokens": response.usage.input_tokens,
                    "completion_tokens": response.usage.output_tokens,
                    "latency_ms": latency_ms,
                },
            )
            return response.content[0].text
        except Exception as e:
            latency_ms = (time.monotonic() - start) * 1000
            self.logger.error(
                "llm_call_failed",
                event_type="llm_call_failed",
                agent_name=self.name,
                payload={"error": str(e), "latency_ms": latency_ms},
            )
            raise

    async def _use_tool(self, tool_name: str, **kwargs: Any) -> Any:
        return await tool_registry.call(
            tool_name, allowed_tools=self.allowed_tools, agent_name=self.name, **kwargs
        )
