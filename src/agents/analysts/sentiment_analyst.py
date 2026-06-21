from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from src.agents.base_agent import BaseAgent
from src.data.redis_client import redis_client
from src.schemas.signals import Signal

SYSTEM_PROMPT = """You are a Crypto Sentiment Analyst for an automated trading fund.

ROLE: Analyze news headlines and social media data to produce directional signals
for specific crypto assets.

INPUTS: Raw text from news feeds and social data for the past 4 hours.

OUTPUTS: An array of Signal objects (schema provided). JSON only, no other text.

SIGNAL RULES:
- Only produce signals where you have genuine conviction. Omit uncertain assets.
- confidence_score: 0.0 (no conviction) to 1.0 (extremely high conviction).
  Be conservative — most signals should be 0.4–0.7. Above 0.8 only for clear,
  corroborated evidence.
- horizon_hours: How long you expect this signal to be relevant (1–72)
- Always populate contradicting_factors honestly. Never suppress bearish evidence
  for an asset you're bullish on.
- Distinguish between noise and signal. Celebrity tweets are noise.
  Regulatory announcements are signal.

You are a researcher, not a trader. You do not size positions. You flag information.
Your output is Signal[] JSON only."""

MAX_LLM_CALLS_PER_TICK = 10
SENTIMENT_RAW_KEY_PREFIX = "sentiment:raw"


class SentimentAnalyst(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="sentiment_analyst", allowed_tools=["read_normalized_data", "write_signal"])

    async def _fetch_raw_sentiment(self) -> dict[str, dict]:
        raw_by_asset: dict[str, dict] = {}
        async for key in redis_client.client.scan_iter(match=f"{SENTIMENT_RAW_KEY_PREFIX}:*"):
            asset = key.split(":")[-1]
            raw = await redis_client.client.get(key)
            if raw:
                raw_by_asset[asset] = json.loads(raw)
        return raw_by_asset

    def _chunk_assets(self, raw_by_asset: dict[str, dict]) -> list[dict[str, dict]]:
        assets = list(raw_by_asset.items())
        if not assets:
            return []
        num_batches = min(MAX_LLM_CALLS_PER_TICK, len(assets))
        batch_size = -(-len(assets) // num_batches)  # ceil division
        return [dict(assets[i : i + batch_size]) for i in range(0, len(assets), batch_size)]

    def _build_user_message(self, batch: dict[str, dict]) -> str:
        lines: list[str] = []
        for asset, data in batch.items():
            lines.append(f"Asset: {asset}")
            for headline in data.get("headlines", []):
                lines.append(f"- {headline}")
            lines.append("")
        lines.append(
            "Return a JSON array of Signal objects for the assets above where you have "
            "genuine conviction. Each Signal needs: asset, direction (LONG|SHORT|NEUTRAL), "
            "confidence_score (0.0-1.0), horizon_hours (1-72), supporting_factors (string[]), "
            "contradicting_factors (string[]). Omit assets with no conviction. JSON only."
        )
        return "\n".join(lines)

    def _parse_signals(self, raw_text: str, valid_assets: set[str]) -> list[Signal]:
        data = json.loads(raw_text)
        if not isinstance(data, list):
            raise ValueError("expected a JSON array of Signal objects")

        signals: list[Signal] = []
        now = datetime.now(timezone.utc).isoformat()
        for item in data:
            if not isinstance(item, dict):
                continue
            item = dict(item)
            item["timestamp"] = now
            item["source_agent"] = "sentiment_analyst"
            item.pop("signal_id", None)

            try:
                signal = Signal.model_validate(item)
            except Exception as e:
                self.logger.error(
                    "sentiment_signal_rejected",
                    event_type="sentiment_signal_rejected",
                    payload={"error": str(e), "raw_item": item},
                )
                continue

            if signal.asset not in valid_assets:
                self.logger.error(
                    "sentiment_signal_unknown_asset",
                    event_type="sentiment_signal_unknown_asset",
                    payload={"asset": signal.asset},
                )
                continue

            signals.append(signal)
        return signals

    async def _analyze_batch(self, batch: dict[str, dict]) -> list[Signal]:
        user_message = self._build_user_message(batch)
        valid_assets = set(batch.keys())

        raw_response = await self._call_llm(
            messages=[{"role": "user", "content": user_message}],
            system_prompt=SYSTEM_PROMPT,
            max_tokens=1500,
        )

        try:
            return self._parse_signals(raw_response, valid_assets)
        except (json.JSONDecodeError, ValueError) as e:
            self.logger.warning(
                "sentiment_json_parse_failed",
                event_type="sentiment_json_parse_failed",
                payload={"error": str(e)},
            )
            correction_message = (
                f"Your last response failed validation: {e}\n"
                f"Return ONLY valid JSON matching the schema. No other text.\n"
                f"Your response was: {raw_response}"
            )
            try:
                corrected = await self._call_llm(
                    messages=[
                        {"role": "user", "content": user_message},
                        {"role": "assistant", "content": raw_response},
                        {"role": "user", "content": correction_message},
                    ],
                    system_prompt=SYSTEM_PROMPT,
                    max_tokens=1500,
                )
                return self._parse_signals(corrected, valid_assets)
            except Exception as retry_error:
                self.logger.error(
                    "sentiment_json_parse_failed_after_retry",
                    event_type="sentiment_json_parse_failed_after_retry",
                    payload={"error": str(retry_error)},
                )
                return []

    async def _run_impl(self, context: dict[str, Any]) -> dict[str, Any]:
        raw_by_asset = await self._fetch_raw_sentiment()
        if not raw_by_asset:
            return {"signals": []}

        all_signals: list[Signal] = []
        for batch in self._chunk_assets(raw_by_asset):
            try:
                signals = await self._analyze_batch(batch)
                all_signals.extend(signals)
            except Exception as e:
                self.logger.error(
                    "sentiment_batch_failed",
                    event_type="sentiment_batch_failed",
                    payload={"assets": list(batch.keys()), "error": str(e)},
                )

        return {"signals": all_signals}

    async def run(self, tick_id: str) -> list[Signal]:
        result = await super().run({"tick_id": tick_id})
        return result["signals"]


sentiment_analyst = SentimentAnalyst()
