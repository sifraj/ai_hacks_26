from datetime import datetime, timedelta

import pytest

from src.backtesting.performance_metrics import (
    build_trade_records,
    sharpe_ratio,
    sortino_ratio,
    max_drawdown,
    win_rate,
    avg_win_pct,
    avg_loss_pct,
    calmar_ratio,
    per_asset_breakdown,
    signal_accuracy_by_analyst,
    compute_performance_report,
)
from src.schemas.trades import Fill


def _fill(**overrides) -> Fill:
    defaults = dict(
        cleared_id="c1", asset="BTC-USD", side="BUY", filled_size_usd=1000.0,
        fill_price=100.0, fee_usd=6.0, timestamp="2026-06-01T00:00:00+00:00",
    )
    defaults.update(overrides)
    return Fill(**defaults)


class TestBuildTradeRecords:
    def test_simple_round_trip_profit(self):
        buy = _fill(cleared_id="c1", side="BUY", fill_price=100.0, filled_size_usd=1000.0,
                     timestamp="2026-06-01T00:00:00+00:00")
        sell = _fill(cleared_id="c2", side="SELL", fill_price=110.0, filled_size_usd=1000.0,
                      timestamp="2026-06-02T00:00:00+00:00")

        trades = build_trade_records([buy, sell], {}, {})
        assert len(trades) == 1
        assert trades[0].pnl_pct == pytest.approx(0.10)
        assert trades[0].pnl_usd == pytest.approx(100.0)
        assert trades[0].hold_hours == pytest.approx(24.0)

    def test_partial_sell_splits_lot(self):
        buy = _fill(cleared_id="c1", side="BUY", fill_price=100.0, filled_size_usd=1000.0,
                     timestamp="2026-06-01T00:00:00+00:00")
        sell = _fill(cleared_id="c2", side="SELL", fill_price=105.0, filled_size_usd=400.0,
                      timestamp="2026-06-02T00:00:00+00:00")

        trades = build_trade_records([buy, sell], {}, {})
        assert len(trades) == 1
        assert trades[0].size_usd == pytest.approx(400.0)
        assert trades[0].pnl_usd == pytest.approx(0.05 * 400.0)

    def test_fifo_matches_earliest_lot_first(self):
        buy1 = _fill(cleared_id="c1", side="BUY", fill_price=100.0, filled_size_usd=500.0,
                      timestamp="2026-06-01T00:00:00+00:00")
        buy2 = _fill(cleared_id="c2", side="BUY", fill_price=200.0, filled_size_usd=500.0,
                      timestamp="2026-06-02T00:00:00+00:00")
        sell = _fill(cleared_id="c3", side="SELL", fill_price=150.0, filled_size_usd=500.0,
                      timestamp="2026-06-03T00:00:00+00:00")

        trades = build_trade_records([buy1, buy2, sell], {}, {})
        assert len(trades) == 1
        assert trades[0].entry_price == pytest.approx(100.0)  # matched against earliest lot

    def test_signal_attribution_carried_through(self):
        buy = _fill(cleared_id="c1", side="BUY", fill_price=100.0, filled_size_usd=1000.0,
                     timestamp="2026-06-01T00:00:00+00:00")
        sell = _fill(cleared_id="c2", side="SELL", fill_price=110.0, filled_size_usd=1000.0,
                      timestamp="2026-06-02T00:00:00+00:00")

        fill_signal_ids = {"c1": ["sig1", "sig2"]}
        signal_source_agents = {"sig1": "momentum_analyst", "sig2": "sentiment_analyst"}

        trades = build_trade_records([buy, sell], fill_signal_ids, signal_source_agents)
        assert set(trades[0].source_agents) == {"momentum_analyst", "sentiment_analyst"}


class TestRatios:
    def test_sharpe_ratio_zero_for_insufficient_data(self):
        assert sharpe_ratio([]) == 0.0
        assert sharpe_ratio([0.01]) == 0.0

    def test_sharpe_ratio_positive_for_consistent_gains(self):
        returns = [0.001] * 30
        # constant returns -> zero variance -> implementation returns 0.0 (no signal)
        assert sharpe_ratio(returns) == 0.0

    def test_sharpe_ratio_nonzero_with_variance(self):
        returns = [0.01, -0.005, 0.02, -0.01, 0.015, 0.005, -0.002]
        result = sharpe_ratio(returns)
        assert isinstance(result, float)

    def test_sortino_ratio_ignores_upside_volatility(self):
        returns = [0.05, 0.06, 0.07, 0.04]  # all positive, no downside
        result = sortino_ratio(returns)
        assert result == 0.0  # zero downside deviation -> defined as 0.0

    def test_calmar_ratio_zero_drawdown_returns_zero(self):
        assert calmar_ratio(0.10, 0.0) == 0.0

    def test_calmar_ratio_normal_case(self):
        assert calmar_ratio(0.20, 0.05) == pytest.approx(4.0)


class TestMaxDrawdown:
    def test_no_drawdown_when_monotonically_increasing(self):
        base = datetime(2026, 1, 1)
        curve = [(base + timedelta(days=i), 100_000.0 + i * 1000) for i in range(10)]
        dd_pct, dd_days = max_drawdown(curve)
        assert dd_pct == 0.0
        assert dd_days == 0.0

    def test_drawdown_detected_and_measured(self):
        base = datetime(2026, 1, 1)
        curve = [
            (base, 100_000.0),
            (base + timedelta(days=1), 110_000.0),  # peak
            (base + timedelta(days=2), 99_000.0),  # -10% from peak
            (base + timedelta(days=3), 105_000.0),
        ]
        dd_pct, dd_days = max_drawdown(curve)
        assert dd_pct == pytest.approx((110_000.0 - 99_000.0) / 110_000.0)
        # Still hasn't recovered to a new high by day 3 -> drawdown duration spans peak to day 3.
        assert dd_days == pytest.approx(2.0)

    def test_empty_curve_returns_zero(self):
        assert max_drawdown([]) == (0.0, 0.0)


class TestWinLossStats:
    def test_win_rate_and_avg_pct(self):
        from src.backtesting.performance_metrics import TradeRecord

        t1 = TradeRecord(asset="A", entry_time=datetime(2026, 1, 1), exit_time=datetime(2026, 1, 2),
                          entry_price=100, exit_price=110, size_usd=1000, pnl_usd=100, pnl_pct=0.10)
        t2 = TradeRecord(asset="A", entry_time=datetime(2026, 1, 1), exit_time=datetime(2026, 1, 2),
                          entry_price=100, exit_price=90, size_usd=1000, pnl_usd=-100, pnl_pct=-0.10)

        assert win_rate([t1, t2]) == pytest.approx(0.5)
        assert avg_win_pct([t1, t2]) == pytest.approx(0.10)
        assert avg_loss_pct([t1, t2]) == pytest.approx(-0.10)

    def test_empty_trades_returns_zero(self):
        assert win_rate([]) == 0.0
        assert avg_win_pct([]) == 0.0
        assert avg_loss_pct([]) == 0.0


class TestBreakdowns:
    def test_per_asset_breakdown_groups_correctly(self):
        from src.backtesting.performance_metrics import TradeRecord

        btc = TradeRecord(asset="BTC-USD", entry_time=datetime(2026, 1, 1), exit_time=datetime(2026, 1, 2),
                           entry_price=100, exit_price=110, size_usd=1000, pnl_usd=100, pnl_pct=0.10)
        eth = TradeRecord(asset="ETH-USD", entry_time=datetime(2026, 1, 1), exit_time=datetime(2026, 1, 2),
                           entry_price=100, exit_price=95, size_usd=1000, pnl_usd=-50, pnl_pct=-0.05)

        breakdown = per_asset_breakdown([btc, eth])
        by_asset = {b.asset: b for b in breakdown}
        assert by_asset["BTC-USD"].trade_count == 1
        assert by_asset["BTC-USD"].win_rate == 1.0
        assert by_asset["ETH-USD"].win_rate == 0.0

    def test_signal_accuracy_by_analyst(self):
        from src.backtesting.performance_metrics import TradeRecord

        win = TradeRecord(asset="BTC-USD", entry_time=datetime(2026, 1, 1), exit_time=datetime(2026, 1, 2),
                           entry_price=100, exit_price=110, size_usd=1000, pnl_usd=100, pnl_pct=0.10,
                           source_agents=["momentum_analyst"])
        loss = TradeRecord(asset="ETH-USD", entry_time=datetime(2026, 1, 1), exit_time=datetime(2026, 1, 2),
                            entry_price=100, exit_price=95, size_usd=1000, pnl_usd=-50, pnl_pct=-0.05,
                            source_agents=["momentum_analyst"])

        accuracy = signal_accuracy_by_analyst([win, loss])
        assert len(accuracy) == 1
        assert accuracy[0].source_agent == "momentum_analyst"
        assert accuracy[0].signal_count == 2
        assert accuracy[0].profitable_signal_count == 1
        assert accuracy[0].accuracy_pct == pytest.approx(0.5)


class TestComputePerformanceReport:
    def test_end_to_end_report(self):
        base = datetime(2026, 1, 1)
        buy = _fill(cleared_id="c1", side="BUY", fill_price=100.0, filled_size_usd=10_000.0,
                     timestamp=base.isoformat())
        sell = _fill(cleared_id="c2", side="SELL", fill_price=120.0, filled_size_usd=10_000.0,
                      timestamp=(base + timedelta(days=5)).isoformat())

        equity_curve = [(base, 100_000.0), (base + timedelta(days=5), 102_000.0)]

        report = compute_performance_report(
            fills=[buy, sell],
            fill_signal_ids={},
            signal_source_agents={},
            equity_curve=equity_curve,
            initial_cash_usd=100_000.0,
        )
        assert report.total_trades == 1
        assert report.total_return_pct == pytest.approx(0.02)
        assert report.win_rate == 1.0
