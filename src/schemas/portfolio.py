from __future__ import annotations

from pydantic import BaseModel, Field


class Position(BaseModel):
    asset: str
    quantity: float = Field(gt=0.0)  # base-asset units held — source of truth for valuation
    size_usd: float  # current market value = quantity * current_price
    entry_price: float = Field(gt=0.0)  # average cost per unit
    current_price: float = Field(gt=0.0)
    unrealized_pnl_usd: float
    unrealized_pnl_pct: float
    stop_loss_price: float


class PortfolioState(BaseModel):
    timestamp: str
    total_value_usd: float
    cash_usd: float
    positions: list[Position] = Field(default_factory=list)
    session_high_usd: float
    daily_pnl_usd: float
    daily_pnl_pct: float
    drawdown_from_session_high_pct: float
    kill_switch: bool = False
    # Cumulative realized P&L from closed/reduced positions (gains/losses booked to cash).
    realized_pnl_usd: float = 0.0
    # Baseline for *daily* P&L — reset to the day's opening total value each UTC day.
    daily_baseline_usd: float = 100_000.0
    daily_baseline_date: str = ""
