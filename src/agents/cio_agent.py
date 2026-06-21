from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.agents.base_agent import BaseAgent
from src.schemas.regime import MarketRegime
from src.schemas.signals import SignalBatch

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


class CIOAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="cio_agent", allowed_tools=["read_signals", "read_market_data", "write_regime"])

    async def _run_impl(self, context: dict[str, Any]) -> dict[str, Any]:
        return {"regime": None}

    async def run(self, signal_batch: SignalBatch) -> MarketRegime:
        await super().run({"tick_id": signal_batch.tick_id})

        user_message = signal_batch.model_dump_json()

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
            regime = MarketRegime.model_validate_json(raw_response.strip())
        except Exception as e:
            self.logger.warning(
                "cio_regime_parse_failed",
                event_type="cio_regime_parse_failed",
                payload={"error": str(e), "raw_response": raw_response},
            )
            return _fallback_regime(signal_batch)

        return regime


cio_agent = CIOAgent()
