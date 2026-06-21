from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Awaitable, Callable

from src.backtesting.backtest_runner import BacktestResult, BacktestRunner
from src.backtesting.performance_metrics import PerformanceReport, compute_performance_report
from src.schemas.trades import Fill

DEFAULT_TRAIN_MONTHS = 6
DEFAULT_TEST_MONTHS = 2
DEFAULT_STEP_MONTHS = 1

ProgressCallback = Callable[[dict], Awaitable[None]]


def _add_months(dt: datetime, months: int) -> datetime:
    total_month_index = dt.month - 1 + months
    year = dt.year + total_month_index // 12
    month = total_month_index % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


@dataclass
class WalkForwardWindow:
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    test_result: BacktestResult


@dataclass
class WalkForwardResult:
    windows: list[WalkForwardWindow] = field(default_factory=list)
    aggregated_performance: PerformanceReport | None = None


class WalkForwardValidator:
    """Implements SPEC §8.3 anti-overfitting rules: parameters are never fit on the
    test window — each window's backtest only ever runs over its test_start/test_end
    range, and only out-of-sample (test) results are aggregated into the final report."""

    def __init__(self, runner: BacktestRunner | None = None) -> None:
        self.runner = runner or BacktestRunner()

    def generate_windows(
        self,
        start_date: datetime,
        end_date: datetime,
        train_months: int = DEFAULT_TRAIN_MONTHS,
        test_months: int = DEFAULT_TEST_MONTHS,
        step_months: int = DEFAULT_STEP_MONTHS,
    ) -> list[tuple[datetime, datetime, datetime, datetime]]:
        windows: list[tuple[datetime, datetime, datetime, datetime]] = []
        train_start = start_date
        while True:
            train_end = _add_months(train_start, train_months)
            test_start = train_end
            test_end = _add_months(test_start, test_months)
            if test_end > end_date:
                break
            windows.append((train_start, train_end, test_start, test_end))
            train_start = _add_months(train_start, step_months)
        return windows

    async def run(
        self,
        start_date: datetime,
        end_date: datetime,
        train_months: int = DEFAULT_TRAIN_MONTHS,
        test_months: int = DEFAULT_TEST_MONTHS,
        step_months: int = DEFAULT_STEP_MONTHS,
        progress_callback: ProgressCallback | None = None,
    ) -> WalkForwardResult:
        window_specs = self.generate_windows(start_date, end_date, train_months, test_months, step_months)
        if not window_specs:
            raise ValueError(
                "date range too short for the requested train/test window sizes — "
                f"need at least {train_months + test_months} months"
            )

        windows: list[WalkForwardWindow] = []
        all_fills: list[Fill] = []
        all_fill_signal_ids: dict[str, list[str]] = {}
        all_signal_source_agents: dict[str, str] = {}
        combined_equity_curve: list[tuple[datetime, float]] = []

        for i, (train_start, train_end, test_start, test_end) in enumerate(window_specs):
            # Out-of-sample only: backtest is run strictly on [test_start, test_end).
            test_result = await self.runner.run(test_start, test_end)

            windows.append(
                WalkForwardWindow(
                    train_start=train_start.isoformat(),
                    train_end=train_end.isoformat(),
                    test_start=test_start.isoformat(),
                    test_end=test_end.isoformat(),
                    test_result=test_result,
                )
            )

            all_fills.extend(test_result.fills)
            all_fill_signal_ids.update(test_result.fill_signal_ids)
            all_signal_source_agents.update(test_result.signal_source_agents)
            combined_equity_curve.extend(
                (datetime.fromisoformat(ts), value) for ts, value in test_result.equity_curve
            )

            if progress_callback is not None:
                await progress_callback(
                    {
                        "window_index": i,
                        "window_count": len(window_specs),
                        "test_start": test_start.isoformat(),
                        "test_end": test_end.isoformat(),
                        "tick_count": test_result.tick_count,
                    }
                )

        aggregated_performance = compute_performance_report(
            fills=all_fills,
            fill_signal_ids=all_fill_signal_ids,
            signal_source_agents=all_signal_source_agents,
            equity_curve=combined_equity_curve,
            initial_cash_usd=100_000.0,
        )

        return WalkForwardResult(windows=windows, aggregated_performance=aggregated_performance)


walk_forward_validator = WalkForwardValidator()
