from __future__ import annotations

from pydantic import BaseModel, Field


class Position(BaseModel):
    asset: str
    size_usd: float
    entry_price: float
    current_price: float
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
