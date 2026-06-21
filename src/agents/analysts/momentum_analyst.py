from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import pandas_ta as ta

from src.agents.base_agent import BaseAgent
from src.data.timescale_client import timescale_client
from src.schemas.signals import Signal

ASSETS = [
    "BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD",
    "ADA-USD", "AVAX-USD", "DOT-USD", "POL-USD", "LINK-USD",
]

MIN_CANDLES_REQUIRED = 30  # enough lookback for RSI(14)/MACD(12,26,9)/BB(20)
MAX_CONFIDENCE = 0.85


class MomentumAnalyst(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="momentum_analyst", allowed_tools=["read_normalized_data", "write_signal"])

    async def _run_impl(self, context: dict[str, Any]) -> dict[str, Any]:
        as_of = context.get("as_of") or datetime.now(timezone.utc)
        signals: list[Signal] = []
        for asset in ASSETS:
            signal = await self._analyze_asset(asset, as_of)
            if signal is not None:
                signals.append(signal)
        return {"signals": signals}

    async def _fetch_candles(self, asset: str, as_of: datetime) -> pd.DataFrame | None:
        end = as_of
        start = end - timedelta(hours=24 * 7)  # 7 days of 1h candles
        rows = await timescale_client.get_ohlcv(asset, start, end, "1h")
        if len(rows) < MIN_CANDLES_REQUIRED:
            return None
        return pd.DataFrame(rows)

    def _compute_indicators(self, df: pd.DataFrame) -> dict[str, float] | None:
        close = df["close"]
        volume = df["volume"]

        rsi = ta.rsi(close, length=14)
        macd = ta.macd(close, fast=12, slow=26, signal=9)
        bbands = ta.bbands(close, length=20, std=2)

        if rsi is None or macd is None or bbands is None:
            return None
        if rsi.isna().iloc[-1] or macd.iloc[-1].isna().any() or bbands.iloc[-1].isna().any():
            return None

        latest_close = float(close.iloc[-1])
        latest_rsi = float(rsi.iloc[-1])
        latest_macd = float(macd["MACD_12_26_9"].iloc[-1])
        latest_macd_prev = float(macd["MACD_12_26_9"].iloc[-2])
        latest_signal = float(macd["MACDs_12_26_9"].iloc[-1])
        latest_signal_prev = float(macd["MACDs_12_26_9"].iloc[-2])
        bb_lower = float(bbands["BBL_20_2.0_2.0"].iloc[-1])
        bb_upper = float(bbands["BBU_20_2.0_2.0"].iloc[-1])

        avg_volume_20 = float(volume.iloc[-20:].mean())
        latest_volume = float(volume.iloc[-1])
        volume_ratio = latest_volume / avg_volume_20 if avg_volume_20 > 0 else 0.0

        price_24h_ago = float(close.iloc[-24]) if len(close) >= 24 else float(close.iloc[0])
        price_change_24h_pct = (
            (latest_close - price_24h_ago) / price_24h_ago if price_24h_ago > 0 else 0.0
        )

        return {
            "close": latest_close,
            "rsi": latest_rsi,
            "macd": latest_macd,
            "macd_prev": latest_macd_prev,
            "macd_signal": latest_signal,
            "macd_signal_prev": latest_signal_prev,
            "bb_lower": bb_lower,
            "bb_upper": bb_upper,
            "volume_ratio": volume_ratio,
            "price_change_24h_pct": price_change_24h_pct,
        }

    def _generate_signal(self, asset: str, metrics: dict[str, float], as_of: datetime) -> Signal | None:
        direction: str | None = None
        confidence = 0.0
        supporting: list[str] = []
        contradicting: list[str] = []

        rsi = metrics["rsi"]
        close = metrics["close"]
        bb_lower = metrics["bb_lower"]
        bb_upper = metrics["bb_upper"]

        # RSI + Bollinger Band extremes
        if rsi < 30 and close <= bb_lower:
            direction = "LONG"
            confidence = ((30 - rsi) / 30) * 0.8
            supporting.append(f"RSI oversold at {rsi:.1f}, price at lower Bollinger Band")
        elif rsi > 70 and close >= bb_upper:
            direction = "SHORT"
            confidence = ((rsi - 70) / 30) * 0.8
            supporting.append(f"RSI overbought at {rsi:.1f}, price at upper Bollinger Band")

        # MACD crossover (signal line cross)
        macd_crossed_up = (
            metrics["macd_prev"] <= metrics["macd_signal_prev"] and metrics["macd"] > metrics["macd_signal"]
        )
        macd_crossed_down = (
            metrics["macd_prev"] >= metrics["macd_signal_prev"] and metrics["macd"] < metrics["macd_signal"]
        )

        if direction is None and macd_crossed_up:
            direction = "LONG"
            confidence = 0.5
            supporting.append("MACD bullish crossover")
        elif direction is None and macd_crossed_down:
            direction = "SHORT"
            confidence = 0.5
            supporting.append("MACD bearish crossover")
        elif direction == "LONG" and macd_crossed_down:
            contradicting.append("MACD bearish crossover contradicts LONG signal")
        elif direction == "SHORT" and macd_crossed_up:
            contradicting.append("MACD bullish crossover contradicts SHORT signal")

        if direction is None:
            return None

        # Volume confirmation
        price_up = metrics["price_change_24h_pct"] > 0
        if metrics["volume_ratio"] > 2.0 and price_up:
            confidence += 0.1
            supporting.append(f"Volume {metrics['volume_ratio']:.1f}x 20-period average with rising price")

        confidence = min(confidence, MAX_CONFIDENCE)

        return Signal(
            timestamp=as_of.isoformat(),
            source_agent="momentum_analyst",
            asset=asset,
            direction=direction,
            confidence_score=round(confidence, 4),
            horizon_hours=4,
            supporting_factors=supporting,
            contradicting_factors=contradicting,
            raw_metrics={
                "rsi": rsi,
                "macd": metrics["macd"],
                "macd_signal": metrics["macd_signal"],
                "volume_ratio": metrics["volume_ratio"],
                "price_change_24h_pct": metrics["price_change_24h_pct"],
            },
        )

    async def _analyze_asset(self, asset: str, as_of: datetime) -> Signal | None:
        df = await self._fetch_candles(asset, as_of)
        if df is None:
            self.logger.info(
                "momentum_insufficient_data",
                event_type="momentum_insufficient_data",
                payload={"asset": asset},
            )
            return None

        metrics = self._compute_indicators(df)
        if metrics is None:
            self.logger.info(
                "momentum_indicators_unavailable",
                event_type="momentum_indicators_unavailable",
                payload={"asset": asset},
            )
            return None

        try:
            signal = self._generate_signal(asset, metrics, as_of)
        except Exception as e:
            self.logger.error(
                "momentum_signal_generation_failed",
                event_type="momentum_signal_generation_failed",
                payload={"asset": asset, "error": str(e)},
            )
            return None

        if signal is None:
            return None

        try:
            Signal.model_validate(signal.model_dump())
        except Exception as e:
            self.logger.error(
                "momentum_signal_validation_failed",
                event_type="momentum_signal_validation_failed",
                payload={"asset": asset, "error": str(e)},
            )
            return None

        return signal

    async def run(self, tick_id: str, as_of: datetime | None = None) -> list[Signal]:
        result = await super().run({"tick_id": tick_id, "as_of": as_of})
        return result["signals"]


momentum_analyst = MomentumAnalyst()
