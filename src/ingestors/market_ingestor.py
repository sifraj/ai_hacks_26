from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import ccxt.async_support as ccxt
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log
import logging

from src.data.redis_client import redis_client
from src.data.timescale_client import timescale_client
from src.harness.audit_logger import get_logger

logger = get_logger("market_ingestor")

# SPEC.md §4.1 asset universe (normalized "-USD" naming)
ASSETS = [
    "BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD",
    "ADA-USD", "AVAX-USD", "DOT-USD", "POL-USD", "LINK-USD",
]
INTERVALS = ["5m", "1h", "1d"]


def _to_ccxt_symbol(asset: str) -> str:
    base = asset.split("-")[0]
    return f"{base}/USD"


def _to_asset(ccxt_symbol: str) -> str:
    base = ccxt_symbol.split("/")[0]
    return f"{base}-USD"


class MarketIngestor:
    def __init__(self) -> None:
        self._exchange = ccxt.coinbase()

    async def close(self) -> None:
        await self._exchange.close()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _fetch_ohlcv(self, symbol: str, timeframe: str) -> list:
        return await self._exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=1)

    async def _ingest_asset_interval(self, asset: str, interval: str) -> None:
        symbol = _to_ccxt_symbol(asset)
        try:
            candles = await self._fetch_ohlcv(symbol, interval)
            if not candles:
                return
            ts_ms, open_, high, low, close, volume = candles[-1]
            time = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)

            await timescale_client.insert_ohlcv(
                asset=asset, interval=interval, time=time,
                open=open_, high=high, low=low, close=close, volume=volume,
            )

            if interval == "5m":
                await redis_client.client.set(f"price:latest:{asset}", str(close))

            logger.info(
                "market_ingest_success",
                event_type="market_ingest_success",
                payload={"asset": asset, "interval": interval, "close": close},
            )
        except Exception as e:
            logger.error(
                "market_ingest_failed",
                event_type="market_ingest_failed",
                payload={"asset": asset, "interval": interval, "error": str(e)},
            )

    async def run(self) -> None:
        tasks = [
            self._ingest_asset_interval(asset, interval)
            for asset in ASSETS
            for interval in INTERVALS
        ]
        await asyncio.gather(*tasks)

    async def subscribe_ticker(self, asset: str) -> None:
        symbol = _to_ccxt_symbol(asset)
        while True:
            try:
                ticker = await self._exchange.watch_ticker(symbol)
                await redis_client.client.set(f"price:live:{asset}", str(ticker["last"]))
                logger.info(
                    "ticker_update",
                    event_type="ticker_update",
                    payload={"asset": asset, "last": ticker["last"]},
                )
            except Exception as e:
                logger.error(
                    "ticker_subscribe_failed",
                    event_type="ticker_subscribe_failed",
                    payload={"asset": asset, "error": str(e)},
                )
                await asyncio.sleep(5)


market_ingestor = MarketIngestor()
