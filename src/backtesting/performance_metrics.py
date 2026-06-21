from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

from src.schemas.trades import Fill

TRADING_DAYS_PER_YEAR = 365.0


@dataclass
class TradeRecord:
    asset: str
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    size_usd: float
    pnl_usd: float
    pnl_pct: float
    signal_ids: list[str] = field(default_factory=list)
    source_agents: list[str] = field(default_factory=list)

    @property
    def hold_hours(self) -> float:
        return (self.exit_time - self.entry_time).total_seconds() / 3600.0


@dataclass
class AssetBreakdown:
    asset: str
    trade_count: int
    total_pnl_usd: float
    win_rate: float
    avg_pnl_pct: float


@dataclass
class AnalystAccuracy:
    source_agent: str
    signal_count: int
    profitable_signal_count: int
    accuracy_pct: float


@dataclass
class PerformanceReport:
    total_return_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown_pct: float
    max_drawdown_duration_days: float
    win_rate: float
    avg_win_pct: float
    avg_loss_pct: float
    calmar_ratio: float
    total_trades: int
    avg_hold_hours: float
    per_asset: list[AssetBreakdown] = field(default_factory=list)
    signal_accuracy_by_analyst: list[AnalystAccuracy] = field(default_factory=list)


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def build_trade_records(
    fills: list[Fill],
    fill_signal_ids: dict[str, list[str]],  # keyed by Fill.cleared_id
    signal_source_agents: dict[str, str],
) -> list[TradeRecord]:
    """FIFO-matches BUY/SELL fills per asset into closed round-trip trades."""
    open_lots: dict[str, list[dict]] = {}
    records: list[TradeRecord] = []

    sorted_fills = sorted(fills, key=lambda f: _parse_ts(f.timestamp))

    for fill in sorted_fills:
        lots = open_lots.setdefault(fill.asset, [])
        signal_ids = fill_signal_ids.get(fill.cleared_id, [])
        source_agents = sorted({signal_source_agents[sid] for sid in signal_ids if sid in signal_source_agents})

        if fill.side == "BUY":
            lots.append(
                {
                    "entry_time": _parse_ts(fill.timestamp),
                    "entry_price": fill.fill_price,
                    "remaining_usd": fill.filled_size_usd,
                    "signal_ids": signal_ids,
                    "source_agents": source_agents,
                }
            )
        else:  # SELL — close against earliest open lot(s)
            remaining_to_close = fill.filled_size_usd
            while remaining_to_close > 0 and lots:
                lot = lots[0]
                matched = min(remaining_to_close, lot["remaining_usd"])

                pnl_pct = (fill.fill_price - lot["entry_price"]) / lot["entry_price"] if lot["entry_price"] > 0 else 0.0
                pnl_usd = pnl_pct * matched

                records.append(
                    TradeRecord(
                        asset=fill.asset,
                        entry_time=lot["entry_time"],
                        exit_time=_parse_ts(fill.timestamp),
                        entry_price=lot["entry_price"],
                        exit_price=fill.fill_price,
                        size_usd=matched,
                        pnl_usd=pnl_usd,
                        pnl_pct=pnl_pct,
                        signal_ids=lot["signal_ids"],
                        source_agents=lot["source_agents"],
                    )
                )

                lot["remaining_usd"] -= matched
                remaining_to_close -= matched
                if lot["remaining_usd"] <= 0:
                    lots.pop(0)

    return records


def _daily_returns(equity_curve: list[tuple[datetime, float]]) -> list[float]:
    if len(equity_curve) < 2:
        return []

    by_day: dict[str, float] = {}
    for ts, value in equity_curve:
        by_day[ts.date().isoformat()] = value  # last value per day wins

    values = [by_day[day] for day in sorted(by_day.keys())]
    returns = []
    for i in range(1, len(values)):
        prev = values[i - 1]
        if prev > 0:
            returns.append((values[i] - prev) / prev)
    return returns


def sharpe_ratio(returns: list[float], risk_free_rate: float = 0.0) -> float:
    if len(returns) < 2:
        return 0.0
    excess = [r - risk_free_rate / TRADING_DAYS_PER_YEAR for r in returns]
    mean = sum(excess) / len(excess)
    variance = sum((r - mean) ** 2 for r in excess) / (len(excess) - 1)
    std = math.sqrt(variance)
    if std == 0:
        return 0.0
    return (mean / std) * math.sqrt(TRADING_DAYS_PER_YEAR)


def sortino_ratio(returns: list[float], risk_free_rate: float = 0.0) -> float:
    if len(returns) < 2:
        return 0.0
    target = risk_free_rate / TRADING_DAYS_PER_YEAR
    excess = [r - target for r in returns]
    mean = sum(excess) / len(excess)
    downside = [min(r, 0.0) ** 2 for r in excess]
    downside_deviation = math.sqrt(sum(downside) / len(downside))
    if downside_deviation == 0:
        return 0.0
    return (mean / downside_deviation) * math.sqrt(TRADING_DAYS_PER_YEAR)


def max_drawdown(equity_curve: list[tuple[datetime, float]]) -> tuple[float, float]:
    """Returns (max_drawdown_pct, max_drawdown_duration_days)."""
    if not equity_curve:
        return 0.0, 0.0

    sorted_curve = sorted(equity_curve, key=lambda x: x[0])
    peak_value = sorted_curve[0][1]
    peak_time = sorted_curve[0][0]
    max_dd_pct = 0.0
    max_dd_duration_days = 0.0

    for ts, value in sorted_curve:
        if value >= peak_value:
            peak_value = value
            peak_time = ts
        else:
            dd_pct = (peak_value - value) / peak_value if peak_value > 0 else 0.0
            duration_days = (ts - peak_time).total_seconds() / 86400.0
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct
            if duration_days > max_dd_duration_days:
                max_dd_duration_days = duration_days

    return max_dd_pct, max_dd_duration_days


def win_rate(trades: list[TradeRecord]) -> float:
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.pnl_usd > 0)
    return wins / len(trades)


def avg_win_pct(trades: list[TradeRecord]) -> float:
    wins = [t.pnl_pct for t in trades if t.pnl_usd > 0]
    return sum(wins) / len(wins) if wins else 0.0


def avg_loss_pct(trades: list[TradeRecord]) -> float:
    losses = [t.pnl_pct for t in trades if t.pnl_usd < 0]
    return sum(losses) / len(losses) if losses else 0.0


def calmar_ratio(total_return_pct: float, max_drawdown_pct: float) -> float:
    if max_drawdown_pct == 0:
        return 0.0
    return total_return_pct / max_drawdown_pct


def per_asset_breakdown(trades: list[TradeRecord]) -> list[AssetBreakdown]:
    by_asset: dict[str, list[TradeRecord]] = {}
    for t in trades:
        by_asset.setdefault(t.asset, []).append(t)

    breakdown = []
    for asset, asset_trades in by_asset.items():
        breakdown.append(
            AssetBreakdown(
                asset=asset,
                trade_count=len(asset_trades),
                total_pnl_usd=sum(t.pnl_usd for t in asset_trades),
                win_rate=win_rate(asset_trades),
                avg_pnl_pct=sum(t.pnl_pct for t in asset_trades) / len(asset_trades),
            )
        )
    return breakdown


def signal_accuracy_by_analyst(trades: list[TradeRecord]) -> list[AnalystAccuracy]:
    counts: dict[str, int] = {}
    profitable: dict[str, int] = {}

    for trade in trades:
        is_profitable = trade.pnl_usd > 0
        for agent in trade.source_agents:
            counts[agent] = counts.get(agent, 0) + 1
            if is_profitable:
                profitable[agent] = profitable.get(agent, 0) + 1

    accuracy = []
    for agent, count in counts.items():
        profitable_count = profitable.get(agent, 0)
        accuracy.append(
            AnalystAccuracy(
                source_agent=agent,
                signal_count=count,
                profitable_signal_count=profitable_count,
                accuracy_pct=profitable_count / count if count > 0 else 0.0,
            )
        )
    return accuracy


def compute_performance_report(
    fills: list[Fill],
    fill_signal_ids: dict[str, list[str]],  # keyed by Fill.cleared_id
    signal_source_agents: dict[str, str],
    equity_curve: list[tuple[datetime, float]],
    initial_cash_usd: float,
) -> PerformanceReport:
    trades = build_trade_records(fills, fill_signal_ids, signal_source_agents)

    final_value = equity_curve[-1][1] if equity_curve else initial_cash_usd
    total_return_pct = (
        (final_value - initial_cash_usd) / initial_cash_usd if initial_cash_usd > 0 else 0.0
    )

    daily_returns = _daily_returns(equity_curve)
    max_dd_pct, max_dd_duration_days = max_drawdown(equity_curve)

    avg_hold_hours = sum(t.hold_hours for t in trades) / len(trades) if trades else 0.0

    return PerformanceReport(
        total_return_pct=total_return_pct,
        sharpe_ratio=sharpe_ratio(daily_returns),
        sortino_ratio=sortino_ratio(daily_returns),
        max_drawdown_pct=max_dd_pct,
        max_drawdown_duration_days=max_dd_duration_days,
        win_rate=win_rate(trades),
        avg_win_pct=avg_win_pct(trades),
        avg_loss_pct=avg_loss_pct(trades),
        calmar_ratio=calmar_ratio(total_return_pct, max_dd_pct),
        total_trades=len(trades),
        avg_hold_hours=avg_hold_hours,
        per_asset=per_asset_breakdown(trades),
        signal_accuracy_by_analyst=signal_accuracy_by_analyst(trades),
    )
