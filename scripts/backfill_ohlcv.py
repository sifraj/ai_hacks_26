"""
One-off historical OHLCV backfill — not part of the live tick loop.

The live market_ingestor only fetches the latest candle each tick (Phase 2),
so a fresh TimescaleDB has no history to backtest against. This script pulls
N days of 1h candles per asset from Coinbase via ccxt and inserts them, so
backtest_runner.run() has something to replay.

Usage:
    python scripts/backfill_ohlcv.py --days 90
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ccxt.async_support as ccxt

from src.data.timescale_client import timescale_client
from src.ingestors.market_ingestor import ASSETS, _to_ccxt_symbol


async def backfill_asset(exchange: ccxt.coinbase, asset: str, days: int) -> int:
    symbol = _to_ccxt_symbol(asset)
    since = exchange.parse8601((datetime.now(timezone.utc) - timedelta(days=days)).isoformat())
    inserted = 0

    while True:
        candles = await exchange.fetch_ohlcv(symbol, timeframe="1h", since=since, limit=300)
        if not candles:
            break

        for ts_ms, open_, high, low, close, volume in candles:
            time = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
            await timescale_client.insert_ohlcv(
                asset=asset, interval="1h", time=time,
                open=open_, high=high, low=low, close=close, volume=volume,
            )
            inserted += 1

        last_ts = candles[-1][0]
        next_since = last_ts + 1
        if next_since <= since:
            break
        since = next_since

        if len(candles) < 300:
            break

    return inserted


async def main(days: int) -> None:
    await timescale_client.connect()
    exchange = ccxt.coinbase()
    try:
        for asset in ASSETS:
            count = await backfill_asset(exchange, asset, days)
            print(f"{asset}: inserted {count} candles")
    finally:
        await exchange.close()
        await timescale_client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90, help="how many days of history to backfill")
    args = parser.parse_args()
    asyncio.run(main(args.days))
