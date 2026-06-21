from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import settings
from src.data.redis_client import redis_client
from src.harness.audit_logger import get_logger

logger = get_logger("sentiment_ingestor")

NEWSAPI_URL = "https://newsapi.org/v2/everything"
SENTIMENT_TTL_SECONDS = 15 * 60
LAST_FETCH_KEY = "sentiment:last_fetch_ts"
MIN_FETCH_INTERVAL_SECONDS = 14 * 60

# Keyword -> asset mapping (SPEC.md §4.2)
ASSET_KEYWORDS: dict[str, list[str]] = {
    "BTC-USD": ["bitcoin", "btc"],
    "ETH-USD": ["ethereum", "eth"],
    "SOL-USD": ["solana", "sol"],
    "BNB-USD": ["binance coin", "bnb"],
    "XRP-USD": ["ripple", "xrp"],
    "ADA-USD": ["cardano", "ada"],
    "AVAX-USD": ["avalanche", "avax"],
    "DOT-USD": ["polkadot", "dot"],
    "MATIC-USD": ["polygon", "matic"],
    "LINK-USD": ["chainlink", "link"],
}


@dataclass
class SentimentRawData:
    asset: str
    headlines: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    published_at: list[str] = field(default_factory=list)


def _map_article_to_assets(title: str, description: str) -> list[str]:
    text = f"{title or ''} {description or ''}".lower()
    matched = []
    for asset, keywords in ASSET_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            matched.append(asset)
    return matched


class SentimentIngestor:
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _fetch_news(self) -> dict:
        params = {
            "q": "bitcoin OR ethereum OR crypto",
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 20,
            "apiKey": settings.newsapi_key,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(NEWSAPI_URL, params=params)
            resp.raise_for_status()
            return resp.json()

    async def _should_skip_rate_limit(self) -> bool:
        last_fetch = await redis_client.client.get(LAST_FETCH_KEY)
        if last_fetch is None:
            return False
        elapsed = time.time() - float(last_fetch)
        return elapsed < MIN_FETCH_INTERVAL_SECONDS

    async def run(self) -> None:
        if await self._should_skip_rate_limit():
            logger.info(
                "sentiment_ingest_skipped",
                event_type="sentiment_ingest_skipped",
                payload={"reason": "rate_limit_guard"},
            )
            return

        try:
            data = await self._fetch_news()
            await redis_client.client.set(LAST_FETCH_KEY, str(time.time()))

            per_asset: dict[str, SentimentRawData] = {
                asset: SentimentRawData(asset=asset) for asset in ASSET_KEYWORDS
            }

            for article in data.get("articles", []):
                title = article.get("title") or ""
                description = article.get("description") or ""
                matched_assets = _map_article_to_assets(title, description)
                for asset in matched_assets:
                    entry = per_asset[asset]
                    entry.headlines.append(f"{title} {description}".strip())
                    entry.sources.append((article.get("source") or {}).get("name", "unknown"))
                    entry.published_at.append(article.get("publishedAt", ""))

            for asset, raw in per_asset.items():
                if not raw.headlines:
                    continue
                payload = {
                    "asset": raw.asset,
                    "headlines": raw.headlines,
                    "sources": raw.sources,
                    "published_at": raw.published_at,
                }
                await redis_client.client.set(
                    f"sentiment:raw:{asset}",
                    json.dumps(payload),
                    ex=SENTIMENT_TTL_SECONDS,
                )

            logger.info(
                "sentiment_ingest_success",
                event_type="sentiment_ingest_success",
                payload={"articles_fetched": len(data.get("articles", []))},
            )
        except Exception as e:
            logger.error(
                "sentiment_ingest_failed",
                event_type="sentiment_ingest_failed",
                payload={"error": str(e)},
            )


sentiment_ingestor = SentimentIngestor()
