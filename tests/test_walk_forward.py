from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from src.backtesting.backtest_runner import BacktestResult
from src.backtesting.walk_forward import WalkForwardValidator, _add_months


class TestAddMonths:
    def test_simple_add(self):
        assert _add_months(datetime(2026, 1, 15), 1) == datetime(2026, 2, 15)

    def test_wraps_year(self):
        assert _add_months(datetime(2026, 12, 1), 2) == datetime(2027, 2, 1)

    def test_clamps_day_for_shorter_month(self):
        # Jan 31 + 1 month -> Feb has no 31st, clamp to Feb 28 (2026 not a leap year).
        assert _add_months(datetime(2026, 1, 31), 1) == datetime(2026, 2, 28)


class TestGenerateWindows:
    def test_default_window_spacing(self):
        validator = WalkForwardValidator()
        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 1, 1, tzinfo=timezone.utc)
        windows = validator.generate_windows(start, end)
        assert len(windows) >= 1
        train_start, train_end, test_start, test_end = windows[0]
        assert train_start == start
        assert test_start == train_end
        assert test_end <= end

    def test_too_short_range_returns_no_windows(self):
        validator = WalkForwardValidator()
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 2, 1, tzinfo=timezone.utc)  # only 1 month, need 8
        windows = validator.generate_windows(start, end)
        assert windows == []

    def test_windows_step_forward_by_step_months(self):
        validator = WalkForwardValidator()
        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 6, 1, tzinfo=timezone.utc)
        windows = validator.generate_windows(start, end, train_months=6, test_months=2, step_months=1)
        assert len(windows) >= 2
        assert windows[1][0] == _add_months(windows[0][0], 1)


def _fake_backtest_result(start: datetime, end: datetime) -> BacktestResult:
    return BacktestResult(
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        tick_count=10,
        fills=[],
        equity_curve=[(start.isoformat(), 100_000.0), (end.isoformat(), 105_000.0)],
        performance=None,
        fill_signal_ids={},
        signal_source_agents={},
    )


class TestRun:
    @pytest.mark.asyncio
    async def test_raises_when_range_too_short(self):
        validator = WalkForwardValidator()
        with pytest.raises(ValueError):
            await validator.run(
                datetime(2026, 1, 1, tzinfo=timezone.utc),
                datetime(2026, 2, 1, tzinfo=timezone.utc),
            )

    @pytest.mark.asyncio
    async def test_run_aggregates_across_windows(self):
        fake_runner = AsyncMock()
        fake_runner.run = AsyncMock(side_effect=lambda start, end, **kw: _fake_backtest_result(start, end))

        validator = WalkForwardValidator(runner=fake_runner)
        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 6, 1, tzinfo=timezone.utc)

        result = await validator.run(start, end, train_months=6, test_months=2, step_months=1)

        assert len(result.windows) >= 2
        assert result.aggregated_performance is not None
        # Only out-of-sample (test) windows should have been run.
        for call in fake_runner.run.call_args_list:
            call_start, call_end = call.args[0], call.args[1]
            assert call_start < call_end

    @pytest.mark.asyncio
    async def test_progress_callback_invoked_per_window(self):
        fake_runner = AsyncMock()
        fake_runner.run = AsyncMock(side_effect=lambda start, end, **kw: _fake_backtest_result(start, end))

        validator = WalkForwardValidator(runner=fake_runner)
        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 6, 1, tzinfo=timezone.utc)

        calls = []

        async def progress_callback(update: dict) -> None:
            calls.append(update)

        result = await validator.run(start, end, progress_callback=progress_callback)
        assert len(calls) == len(result.windows)
