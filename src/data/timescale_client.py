from __future__ import annotations

from datetime import datetime
from pathlib import Path

import asyncpg

from src.config import settings


class TimescaleClient:
    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn or settings.database_url
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(self._dsn, min_size=2, max_size=10)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def run_migrations(self) -> None:
        migrations_dir = Path(__file__).parent / "migrations"
        assert self._pool is not None, "call connect() first"
        async with self._pool.acquire() as conn:
            for sql_file in sorted(migrations_dir.glob("*.sql")):
                await conn.execute(sql_file.read_text())

    async def insert_ohlcv(
        self,
        asset: str,
        interval: str,
        time: datetime,
        open: float,
        high: float,
        low: float,
        close: float,
        volume: float,
    ) -> None:
        assert self._pool is not None, "call connect() first"
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO ohlcv (time, asset, interval, open, high, low, close, volume)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (asset, interval, time) DO UPDATE SET
                    open = EXCLUDED.open,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    close = EXCLUDED.close,
                    volume = EXCLUDED.volume
                """,
                time, asset, interval, open, high, low, close, volume,
            )

    async def get_ohlcv(
        self,
        asset: str,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> list[dict]:
        assert self._pool is not None, "call connect() first"
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT time, asset, interval, open, high, low, close, volume
                FROM ohlcv
                WHERE asset = $1 AND interval = $2 AND time >= $3 AND time <= $4
                ORDER BY time ASC
                """,
                asset, interval, start, end,
            )
            return [dict(row) for row in rows]

    async def get_latest_price(self, asset: str) -> float | None:
        assert self._pool is not None, "call connect() first"
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT close FROM ohlcv
                WHERE asset = $1
                ORDER BY time DESC
                LIMIT 1
                """,
                asset,
            )
            return row["close"] if row else None


timescale_client = TimescaleClient()
