from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from src.agents.base_agent import BaseAgent
from src.agents.llm_json import strip_json_fences
from src.data.redis_client import redis_client
from src.ingestors.onchain_ingestor import ONCHAIN_TTL_SECONDS
from src.schemas.signals import Signal

SYSTEM_PROMPT = """You are a Crypto On-Chain Analyst for an automated trading fund.

ROLE: Interpret on-chain metrics (exchange flows, whale activity, network activity,
funding rates, open interest) to produce directional signals.

INPUTS: Normalized on-chain metrics from the last 24 hours.

OUTPUTS: Signal[] JSON only.

KEY METRICS TO INTERPRET:
- Exchange inflows (bearish pressure) vs outflows (supply reduction, bullish)
- Whale wallet accumulation or distribution
- Network transaction volume and active addresses
- Funding rates (positive = longs paying = overheated, potentially bearish)
- Open interest changes (rising OI + rising price = healthy trend)

SIGNAL RULES:
- On-chain signals are slower-moving. horizon_hours should generally be 24–168.
- High confidence (>0.75) requires multiple corroborating on-chain metrics.
- Funding rate signals are short-term exceptions (horizon 4–24h).
- Never produce a signal based on a single metric alone.

Your output is Signal[] JSON only."""

ONCHAIN_RAW_KEY_PREFIX = "onchain:raw"
FRESHNESS_LIMIT_SECONDS = 45 * 60


class OnChainAnalyst(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="onchain_analyst", allowed_tools=["read_normalized_data", "write_signal"])

    async def _fetch_fresh_onchain_data(self) -> dict[str, dict]:
        raw_by_asset: dict[str, dict] = {}
        async for key in redis_client.client.scan_iter(match=f"{ONCHAIN_RAW_KEY_PREFIX}:*"):
            asset = key.split(":")[-1]
            ttl_remaining = await redis_client.client.ttl(key)
            if ttl_remaining is None or ttl_remaining < 0:
                continue

            age_seconds = ONCHAIN_TTL_SECONDS - ttl_remaining
            if age_seconds > FRESHNESS_LIMIT_SECONDS:
                self.logger.info(
                    "onchain_data_stale_skipped",
                    event_type="onchain_data_stale_skipped",
                    payload={"asset": asset, "age_seconds": age_seconds},
                )
                continue

            raw = await redis_client.client.get(key)
            if raw:
                raw_by_asset[asset] = json.loads(raw)
        return raw_by_asset

    def _build_user_message(self, asset: str, data: dict) -> str:
        return (
            f"Asset: {asset}\n"
            f"Funding rate: {data.get('funding_rate')}\n"
            f"Open interest (USD): {data.get('open_interest_usd')}\n"
            f"24h liquidations (USD): {data.get('liquidations_24h_usd')}\n\n"
            "Return a JSON array of Signal objects for this asset if you have genuine "
            "conviction (otherwise return an empty array []). Each Signal needs: asset, "
            "direction (LONG|SHORT|NEUTRAL), confidence_score (0.0-1.0), horizon_hours, "
            "supporting_factors (string[]), contradicting_factors (string[]). JSON only."
        )

    def _parse_signals(self, raw_text: str, asset: str) -> list[Signal]:
        data = json.loads(strip_json_fences(raw_text))
        if not isinstance(data, list):
            raise ValueError("expected a JSON array of Signal objects")

        signals: list[Signal] = []
        now = datetime.now(timezone.utc).isoformat()
        for item in data:
            if not isinstance(item, dict):
                continue
            item = dict(item)
            item["timestamp"] = now
            item["source_agent"] = "onchain_analyst"
            item.pop("signal_id", None)

            try:
                signal = Signal.model_validate(item)
            except Exception as e:
                self.logger.error(
                    "onchain_signal_rejected",
                    event_type="onchain_signal_rejected",
                    payload={"asset": asset, "error": str(e), "raw_item": item},
                )
                continue

            if signal.asset != asset:
                self.logger.error(
                    "onchain_signal_unknown_asset",
                    event_type="onchain_signal_unknown_asset",
                    payload={"expected_asset": asset, "got_asset": signal.asset},
                )
                continue

            signals.append(signal)
        return signals

    async def _analyze_asset(self, asset: str, data: dict) -> list[Signal]:
        user_message = self._build_user_message(asset, data)

        raw_response = await self._call_llm(
            messages=[{"role": "user", "content": user_message}],
            system_prompt=SYSTEM_PROMPT,
            max_tokens=1000,
        )

        try:
            return self._parse_signals(raw_response, asset)
        except (json.JSONDecodeError, ValueError) as e:
            self.logger.warning(
                "onchain_json_parse_failed",
                event_type="onchain_json_parse_failed",
                payload={"asset": asset, "error": str(e)},
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
                    max_tokens=1000,
                )
                return self._parse_signals(corrected, asset)
            except Exception as retry_error:
                self.logger.error(
                    "onchain_json_parse_failed_after_retry",
                    event_type="onchain_json_parse_failed_after_retry",
                    payload={"asset": asset, "error": str(retry_error)},
                )
                return []

    async def _run_impl(self, context: dict[str, Any]) -> dict[str, Any]:
        raw_by_asset = await self._fetch_fresh_onchain_data()
        if not raw_by_asset:
            return {"signals": []}

        all_signals: list[Signal] = []
        for asset, data in raw_by_asset.items():
            try:
                signals = await self._analyze_asset(asset, data)
                all_signals.extend(signals)
            except Exception as e:
                self.logger.error(
                    "onchain_analysis_failed",
                    event_type="onchain_analysis_failed",
                    payload={"asset": asset, "error": str(e)},
                )

        return {"signals": all_signals}

    async def run(self, tick_id: str) -> list[Signal]:
        result = await super().run({"tick_id": tick_id})
        return result["signals"]


onchain_analyst = OnChainAnalyst()
