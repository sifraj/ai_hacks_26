from __future__ import annotations

import json
from dataclasses import dataclass

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import settings
from src.data.redis_client import redis_client
from src.harness.audit_logger import get_logger

logger = get_logger("onchain_ingestor")

COINGLASS_FUNDING_URL = "https://open-api.coinglass.com/public/v2/funding"
COINGLASS_OI_URL = "https://open-api.coinglass.com/public/v2/open_interest"
COINGLASS_LIQUIDATION_URL = "https://open-api.coinglass.com/public/v2/liquidation"

ONCHAIN_TTL_SECONDS = 30 * 60

ASSETS = [
    "BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD",
    "ADA-USD", "AVAX-USD", "DOT-USD", "POL-USD", "LINK-USD",
]


@dataclass
class OnChainRawData:
    asset: str
    funding_rate: float | None = None
    open_interest_usd: float | None = None
    liquidations_24h_usd: float | None = None


def _to_coinglass_symbol(asset: str) -> str:
    return asset.split("-")[0]


class OnChainIngestor:
    def __init__(self) -> None:
        self._headers = {"coinglassSecret": settings.coinglass_api_key}

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _fetch(self, url: str, params: dict) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params, headers=self._headers)
            resp.raise_for_status()
            return resp.json()

    async def _ingest_asset(self, asset: str) -> None:
        symbol = _to_coinglass_symbol(asset)
        try:
            funding_data = await self._fetch(COINGLASS_FUNDING_URL, {"symbol": symbol})
            oi_data = await self._fetch(COINGLASS_OI_URL, {"symbol": symbol})
            liq_data = await self._fetch(COINGLASS_LIQUIDATION_URL, {"symbol": symbol})

            raw = OnChainRawData(
                asset=asset,
                funding_rate=_extract_first_numeric(funding_data),
                open_interest_usd=_extract_first_numeric(oi_data),
                liquidations_24h_usd=_extract_first_numeric(liq_data),
            )

            payload = {
                "asset": raw.asset,
                "funding_rate": raw.funding_rate,
                "open_interest_usd": raw.open_interest_usd,
                "liquidations_24h_usd": raw.liquidations_24h_usd,
            }
            await redis_client.client.set(
                f"onchain:raw:{asset}",
                json.dumps(payload),
                ex=ONCHAIN_TTL_SECONDS,
            )

            logger.info(
                "onchain_ingest_success",
                event_type="onchain_ingest_success",
                payload={"asset": asset},
            )
        except Exception as e:
            logger.error(
                "onchain_ingest_failed",
                event_type="onchain_ingest_failed",
                payload={"asset": asset, "error": str(e)},
            )

    async def run(self) -> None:
        for asset in ASSETS:
            await self._ingest_asset(asset)


def _extract_first_numeric(data: dict) -> float | None:
    payload = data.get("data")
    if isinstance(payload, list) and payload:
        first = payload[0]
        for value in first.values():
            if isinstance(value, (int, float)):
                return float(value)
    return None


onchain_ingestor = OnChainIngestor()
