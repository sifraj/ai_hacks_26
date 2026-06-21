from __future__ import annotations

import json
import time
from dataclasses import dataclass

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from src.data.redis_client import redis_client
from src.harness.audit_logger import get_logger

logger = get_logger("onchain_ingestor")

# OKX's public market-data API — free, unauthenticated, no plan/paywall.
# CoinGlass's v2 API (the original source here) turned out to be fully gated
# behind a paid plan even for funding rate/open interest (see commit history);
# liquidation orders aren't available there at all on a free tier either.
OKX_BASE_URL = "https://www.okx.com/api/v5"
OKX_FUNDING_URL = f"{OKX_BASE_URL}/public/funding-rate"
OKX_OPEN_INTEREST_URL = f"{OKX_BASE_URL}/public/open-interest"
OKX_LIQUIDATIONS_URL = f"{OKX_BASE_URL}/public/liquidation-orders"

ONCHAIN_TTL_SECONDS = 30 * 60
LIQUIDATION_LOOKBACK_SECONDS = 24 * 60 * 60

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


def _to_okx_inst_id(asset: str) -> str:
    base = asset.split("-")[0]
    return f"{base}-USDT-SWAP"


def _to_okx_inst_family(asset: str) -> str:
    base = asset.split("-")[0]
    return f"{base}-USDT"


class OnChainIngestor:
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _fetch(self, url: str, params: dict) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != "0":
                raise RuntimeError(f"OKX API error: {data.get('msg')}")
            return data

    async def _fetch_funding_rate(self, asset: str) -> float | None:
        try:
            data = await self._fetch(OKX_FUNDING_URL, {"instId": _to_okx_inst_id(asset)})
            entries = data.get("data") or []
            return float(entries[0]["fundingRate"]) if entries else None
        except Exception as e:
            logger.warning(
                "onchain_metric_failed",
                event_type="onchain_metric_failed",
                payload={"asset": asset, "metric": "funding_rate", "error": str(e)},
            )
            return None

    async def _fetch_open_interest(self, asset: str) -> float | None:
        try:
            data = await self._fetch(OKX_OPEN_INTEREST_URL, {"instId": _to_okx_inst_id(asset)})
            entries = data.get("data") or []
            return float(entries[0]["oiUsd"]) if entries else None
        except Exception as e:
            logger.warning(
                "onchain_metric_failed",
                event_type="onchain_metric_failed",
                payload={"asset": asset, "metric": "open_interest_usd", "error": str(e)},
            )
            return None

    async def _fetch_liquidations_24h(self, asset: str) -> float | None:
        try:
            data = await self._fetch(
                OKX_LIQUIDATIONS_URL,
                {"instType": "SWAP", "instFamily": _to_okx_inst_family(asset), "state": "filled"},
            )
            groups = data.get("data") or []
            if not groups:
                return None

            # OKX dedupes identical repeated objects in the response as JSON
            # references — only entries with a real "details" list carry data.
            details = [d for g in groups if isinstance(g, dict) for d in g.get("details", [])]
            if not details:
                return None

            cutoff_ms = (time.time() - LIQUIDATION_LOOKBACK_SECONDS) * 1000
            total_usd = sum(
                float(d["sz"]) * float(d["bkPx"])
                for d in details
                if int(d.get("ts", 0)) >= cutoff_ms
            )
            return total_usd
        except Exception as e:
            logger.warning(
                "onchain_metric_failed",
                event_type="onchain_metric_failed",
                payload={"asset": asset, "metric": "liquidations_24h_usd", "error": str(e)},
            )
            return None

    async def _ingest_asset(self, asset: str) -> None:
        funding_rate = await self._fetch_funding_rate(asset)
        open_interest_usd = await self._fetch_open_interest(asset)
        liquidations_24h_usd = await self._fetch_liquidations_24h(asset)

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
            # Explicit fetch time so the analyst's freshness gate doesn't have to
            # infer age from the Redis TTL (fragile if the TTL constant changes).
            "fetched_at": time.time(),
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


onchain_ingestor = OnChainIngestor()
