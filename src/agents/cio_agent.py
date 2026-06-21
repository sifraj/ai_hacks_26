from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from src.agents.base_agent import BaseAgent
from src.agents.llm_json import strip_json_fences
from src.schemas.regime import MarketRegime
from src.schemas.signals import SignalBatch

# Field names Claude has been observed substituting for our schema's real ones.
_FIELD_ALIASES = {
    "posture_scalar": "posture_multiplier",
    "posture_mult": "posture_multiplier",
    "signal_ids_used": "signal_ids_cited",
    "key_signals_cited": "signal_ids_cited",
    "cited_signal_ids": "signal_ids_cited",
}

SYSTEM_PROMPT = """You are the Chief Investment Officer of an automated crypto trading fund.

ROLE: Assess current market regime and set strategic posture for the portfolio.

INPUTS: You receive a batch of signals from research analysts covering momentum,
sentiment, and on-chain data across BTC, ETH, and top altcoins.

OUTPUTS: You produce a MarketRegime object (schema provided). Your output must be
valid JSON matching the schema exactly. No additional text.

REGIME CLASSIFICATIONS:
- RISK_ON: Trending upward, positive sentiment, healthy on-chain activity
- RISK_OFF: Downtrending, negative sentiment, capital outflows
- HIGH_VOLATILITY: Large moves in either direction, uncertainty dominant
- RANGING: Low volatility, no clear trend, consolidation

POSTURE OPTIONS: AGGRESSIVE (1.0x base sizing), NEUTRAL (0.6x), DEFENSIVE (0.3x), FLAT (0x - no new positions)

RULES:
- In HIGH_VOLATILITY regimes, posture never exceeds NEUTRAL
- In RISK_OFF regimes, posture defaults to DEFENSIVE unless strong contradicting evidence
- You must cite at least 3 signal inputs in your regime_rationale
- When signals conflict, err conservative

Your output is MarketRegime JSON only. No preamble, no markdown."""

# The system prompt above is the exact SPEC §3.1 text and must not be edited.
# Claude reliably invents its own field names (e.g. "posture_scalar") when only
# told "schema provided" without ever actually seeing it — so the concrete
# schema is appended to the per-tick user message instead, where it's safe to
# adjust. Raw JSON output (no markdown fences) is enforced by strip_json_fences()
# as a second line of defense regardless.
SCHEMA_INSTRUCTIONS = """
Respond with ONLY a single raw JSON object — no markdown code fences, no preamble —
matching exactly this shape and these exact field names:

{
  "tick_id": "<echo the tick_id from the input>",
  "timestamp": "<ISO 8601 timestamp>",
  "regime": "RISK_ON" | "RISK_OFF" | "HIGH_VOLATILITY" | "RANGING",
  "posture": "AGGRESSIVE" | "NEUTRAL" | "DEFENSIVE" | "FLAT",
  "posture_multiplier": 1.0 | 0.6 | 0.3 | 0.0,
  "regime_rationale": "<string, must cite at least 3 signal_ids from the input>",
  "signal_ids_cited": ["<signal_id>", "<signal_id>", "<signal_id>", ...]
}

Do not add, rename, or omit any field. posture_multiplier must match posture exactly:
AGGRESSIVE=1.0, NEUTRAL=0.6, DEFENSIVE=0.3, FLAT=0.0. signal_ids_cited must contain
at least 3 entries copied verbatim from the input signals' signal_id fields."""


def _fallback_regime(signal_batch: SignalBatch) -> MarketRegime:
    cited = [s.signal_id for s in signal_batch.signals[:3]]
    while len(cited) < 3:
        cited.append(f"no_signal_{len(cited)}")

    return MarketRegime(
        tick_id=signal_batch.tick_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        regime="RANGING",
        posture="DEFENSIVE",
        posture_multiplier=0.3,
        regime_rationale="Fallback default — LLM regime assessment failed or returned invalid output",
        signal_ids_cited=cited,
    )


def _recover_regime(raw_response: str, signal_batch: SignalBatch) -> MarketRegime:
    """Best-effort recovery of Claude's actual judgment before giving up entirely.
    Normalizes known field-name aliases and pads citations using real signal_ids
    from this tick's batch when Claude legitimately had fewer than 3 to cite."""
    data = json.loads(strip_json_fences(raw_response))
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")

    for alias, canonical in _FIELD_ALIASES.items():
        if alias in data and canonical not in data:
            data[canonical] = data.pop(alias)

    data.setdefault("tick_id", signal_batch.tick_id)
    data.setdefault("timestamp", datetime.now(timezone.utc).isoformat())

    real_signal_ids = [s.signal_id for s in signal_batch.signals]
    cited = [sid for sid in data.get("signal_ids_cited", []) if isinstance(sid, str)]
    # Keep only citations that reference real signals from this tick.
    cited = [sid for sid in cited if sid in real_signal_ids] or list(real_signal_ids[:3])
    for sid in real_signal_ids:
        if len(cited) >= 3:
            break
        if sid not in cited:
            cited.append(sid)
    while len(cited) < 3:
        cited.append(f"insufficient_signal_data_{len(cited)}")
    data["signal_ids_cited"] = cited

    return MarketRegime.model_validate(data)


class CIOAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="cio_agent", allowed_tools=["read_signals", "read_market_data", "write_regime"])

    async def _run_impl(self, context: dict[str, Any]) -> dict[str, Any]:
        return {"regime": None}

    async def run(self, signal_batch: SignalBatch) -> MarketRegime:
        await super().run({"tick_id": signal_batch.tick_id})

        user_message = signal_batch.model_dump_json() + "\n" + SCHEMA_INSTRUCTIONS

        try:
            raw_response = await self._call_llm(
                messages=[{"role": "user", "content": user_message}],
                system_prompt=SYSTEM_PROMPT,
                max_tokens=1000,
            )
        except Exception as e:
            self.logger.error(
                "cio_llm_call_failed",
                event_type="cio_llm_call_failed",
                payload={"error": str(e)},
            )
            return _fallback_regime(signal_batch)

        try:
            return MarketRegime.model_validate_json(strip_json_fences(raw_response))
        except Exception as first_error:
            try:
                regime = _recover_regime(raw_response, signal_batch)
                self.logger.info(
                    "cio_regime_recovered",
                    event_type="cio_regime_recovered",
                    payload={"original_error": str(first_error)},
                )
                return regime
            except Exception as e:
                self.logger.warning(
                    "cio_regime_parse_failed",
                    event_type="cio_regime_parse_failed",
                    payload={"error": str(e), "raw_response": raw_response},
                )
                return _fallback_regime(signal_batch)


cio_agent = CIOAgent()
