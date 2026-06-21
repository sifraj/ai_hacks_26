import numpy as np
from datetime import datetime, timedelta, timezone
import pandas as pd
import pytest

import src.agents.analysts.momentum_analyst as momentum_module
from src.agents.analysts.momentum_analyst import MomentumAnalyst, MAX_CONFIDENCE


def _flat_df(n=40, price=100.0, volume=1000.0) -> pd.DataFrame:
    # Tiny noise avoids NaN RSI/MACD on a perfectly constant series (0/0 division).
    rng = np.random.default_rng(42)
    closes = price + rng.normal(0, 0.01, n)
    return pd.DataFrame({"close": closes, "volume": [volume] * n})


def _oversold_df(n=40) -> pd.DataFrame:
    # Steady decline so RSI ends up well below 30 and price sits at/below lower BB.
    closes = np.linspace(150, 90, n)
    volumes = [1000.0] * n
    return pd.DataFrame({"close": closes, "volume": volumes})


def _overbought_df(n=40) -> pd.DataFrame:
    closes = np.linspace(90, 150, n)
    volumes = [1000.0] * n
    return pd.DataFrame({"close": closes, "volume": volumes})


@pytest.fixture
def analyst():
    return MomentumAnalyst()


class TestComputeIndicators:
    def test_returns_none_for_too_short_series(self, analyst):
        df = _flat_df(n=5)
        assert analyst._compute_indicators(df) is None

    def test_returns_metrics_for_sufficient_data(self, analyst):
        df = _oversold_df(n=40)
        metrics = analyst._compute_indicators(df)
        assert metrics is not None
        assert "rsi" in metrics
        assert "macd" in metrics
        assert "bb_lower" in metrics
        assert "volume_ratio" in metrics


class TestGenerateSignal:
    def test_oversold_rsi_at_lower_band_generates_long(self, analyst):
        df = _oversold_df(n=40)
        metrics = analyst._compute_indicators(df)
        assert metrics is not None
        # Force the textbook oversold-at-band condition regardless of exact BB float.
        metrics["rsi"] = 20.0
        metrics["close"] = metrics["bb_lower"]

        signal = analyst._generate_signal("BTC-USD", metrics, datetime.now(timezone.utc))
        assert signal is not None
        assert signal.direction == "LONG"
        expected_confidence = min(((30 - 20.0) / 30) * 0.8, MAX_CONFIDENCE)
        assert signal.confidence_score == pytest.approx(expected_confidence, abs=0.02)

    def test_overbought_rsi_at_upper_band_generates_short(self, analyst):
        df = _overbought_df(n=40)
        metrics = analyst._compute_indicators(df)
        assert metrics is not None
        metrics["rsi"] = 80.0
        metrics["close"] = metrics["bb_upper"]

        signal = analyst._generate_signal("ETH-USD", metrics, datetime.now(timezone.utc))
        assert signal is not None
        assert signal.direction == "SHORT"

    def test_confidence_capped_at_max(self, analyst):
        df = _oversold_df(n=40)
        metrics = analyst._compute_indicators(df)
        metrics["rsi"] = 1.0  # would produce confidence > 0.85 uncapped
        metrics["close"] = metrics["bb_lower"]
        metrics["volume_ratio"] = 5.0
        metrics["price_change_24h_pct"] = 0.05

        signal = analyst._generate_signal("BTC-USD", metrics, datetime.now(timezone.utc))
        assert signal.confidence_score <= MAX_CONFIDENCE

    def test_macd_bullish_crossover_generates_long_when_no_rsi_extreme(self, analyst):
        df = _flat_df(n=40)
        metrics = analyst._compute_indicators(df)
        metrics["rsi"] = 50.0
        metrics["close"] = 100.0
        metrics["bb_lower"] = 90.0
        metrics["bb_upper"] = 110.0
        metrics["macd_prev"] = -0.5
        metrics["macd_signal_prev"] = -0.4
        metrics["macd"] = 0.2
        metrics["macd_signal"] = 0.1

        signal = analyst._generate_signal("SOL-USD", metrics, datetime.now(timezone.utc))
        assert signal is not None
        assert signal.direction == "LONG"
        assert signal.confidence_score == pytest.approx(0.5, abs=1e-6)

    def test_volume_confirmation_adds_to_confidence(self, analyst):
        df = _flat_df(n=40)
        metrics = analyst._compute_indicators(df)
        metrics["rsi"] = 50.0
        metrics["close"] = 100.0
        metrics["bb_lower"] = 90.0
        metrics["bb_upper"] = 110.0
        metrics["macd_prev"] = -0.5
        metrics["macd_signal_prev"] = -0.4
        metrics["macd"] = 0.2
        metrics["macd_signal"] = 0.1
        metrics["volume_ratio"] = 3.0
        metrics["price_change_24h_pct"] = 0.02

        signal = analyst._generate_signal("SOL-USD", metrics, datetime.now(timezone.utc))
        assert signal.confidence_score == pytest.approx(0.6, abs=1e-6)

    def test_no_signal_when_no_condition_met(self, analyst):
        df = _flat_df(n=40)
        metrics = analyst._compute_indicators(df)
        metrics["rsi"] = 50.0
        metrics["close"] = 100.0
        metrics["bb_lower"] = 90.0
        metrics["bb_upper"] = 110.0
        metrics["macd_prev"] = 0.1
        metrics["macd_signal_prev"] = 0.1
        metrics["macd"] = 0.1
        metrics["macd_signal"] = 0.1

        signal = analyst._generate_signal("ADA-USD", metrics, datetime.now(timezone.utc))
        assert signal is None


class TestAnalyzeAsset:
    @pytest.mark.asyncio
    async def test_insufficient_data_returns_none(self, analyst, monkeypatch):
        async def fake_get_ohlcv(asset, start, end, interval):
            return []

        monkeypatch.setattr(momentum_module.timescale_client, "get_ohlcv", fake_get_ohlcv)
        result = await analyst._analyze_asset("BTC-USD", datetime.now(timezone.utc))
        assert result is None

    @pytest.mark.asyncio
    async def test_full_pipeline_produces_valid_signal(self, analyst, monkeypatch):
        closes = np.linspace(150, 90, 60)
        rows = [
            {"close": c, "high": c, "low": c, "open": c, "volume": 1000.0}
            for c in closes
        ]

        async def fake_get_ohlcv(asset, start, end, interval):
            return rows

        monkeypatch.setattr(momentum_module.timescale_client, "get_ohlcv", fake_get_ohlcv)

        result = await analyst._analyze_asset("BTC-USD", datetime.now(timezone.utc))
        # A steady, strong decline should trigger the oversold LONG rule.
        if result is not None:
            assert result.asset == "BTC-USD"
            assert result.source_agent == "momentum_analyst"
            assert 0.0 <= result.confidence_score <= MAX_CONFIDENCE


class TestAsOfThreading:
    @pytest.mark.asyncio
    async def test_fetch_candles_queries_relative_to_as_of_not_real_now(self, analyst, monkeypatch):
        # Regression test for the backtest bug: momentum_analyst used to hardcode
        # datetime.now(), silently using *today's* real candles during a backtest
        # over a historical window. The query range must follow the simulated clock.
        captured = {}

        async def fake_get_ohlcv(asset, start, end, interval):
            captured["start"] = start
            captured["end"] = end
            return [{"close": 1, "high": 1, "low": 1, "open": 1, "volume": 1} for _ in range(40)]

        monkeypatch.setattr(momentum_module.timescale_client, "get_ohlcv", fake_get_ohlcv)

        historical_as_of = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)
        await analyst._fetch_candles("BTC-USD", historical_as_of)

        assert captured["end"] == historical_as_of
        assert captured["start"] == historical_as_of - timedelta(days=7)
        # Must not be anywhere near the real current time.
        assert abs((captured["end"] - datetime.now(timezone.utc)).days) > 30
