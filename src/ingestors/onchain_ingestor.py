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

    async def _fetch_metric(self, url: str, symbol: str, metric_name: str, asset: str) -> float | None:
        try:
            data = await self._fetch(url, {"symbol": symbol})
            return _extract_first_numeric(data)
        except Exception as e:
            logger.warning(
                "onchain_metric_failed",
                event_type="onchain_metric_failed",
                payload={"asset": asset, "metric": metric_name, "error": str(e)},
            )
            return None

    async def _ingest_asset(self, asset: str) -> None:
        symbol = _to_coinglass_symbol(asset)

        funding_rate = await self._fetch_metric(COINGLASS_FUNDING_URL, symbol, "funding_rate", asset)
        open_interest_usd = await self._fetch_metric(COINGLASS_OI_URL, symbol, "open_interest_usd", asset)
        liquidations_24h_usd = await self._fetch_metric(
            COINGLASS_LIQUIDATION_URL, symbol, "liquidations_24h_usd", asset
        )

        if funding_rate is None and open_interest_usd is None and liquidations_24h_usd is None:
            logger.error(
                "onchain_ingest_failed",
                event_type="onchain_ingest_failed",
                payload={"asset": asset, "error": "all metrics failed"},
            )
            return

        raw = OnChainRawData(
            asset=asset,
            funding_rate=funding_rate,
            open_interest_usd=open_interest_usd,
            liquidations_24h_usd=liquidations_24h_usd,
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
