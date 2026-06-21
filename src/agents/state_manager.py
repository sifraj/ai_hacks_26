from __future__ import annotations

import json
from datetime import datetime, timezone

from src.data.redis_client import redis_client
from src.harness.audit_logger import get_logger
from src.harness.kill_switch import kill_switch_monitor
from src.paper_trading.paper_engine import paper_engine
from src.schemas.portfolio import PortfolioState
from src.schemas.trades import Fill

logger = get_logger("state_manager")

FILLS_QUEUE_KEY = "fills:queue"
TRADING_HALTED_KEY = "risk:trading_halted"

DRAWDOWN_LIMIT_PCT = 0.05  # RISK_001
DAILY_LOSS_LIMIT_PCT = 0.03  # RISK_002


async def _pull_pending_fills() -> list[Fill]:
    fills: list[Fill] = []
    while True:
        raw = await redis_client.client.rpop(FILLS_QUEUE_KEY)
        if raw is None:
            break
        fills.append(Fill.model_validate(json.loads(raw)))
    return fills


async def _check_hard_risk_rules(state: PortfolioState) -> PortfolioState:
    # RISK_001: drawdown from session high > 5% -> kill switch + close all positions
    if state.drawdown_from_session_high_pct > DRAWDOWN_LIMIT_PCT:
        logger.error(
            "RISK_001_BREACHED",
            event_type="RISK_001_BREACHED",
            payload={"drawdown_pct": state.drawdown_from_session_high_pct},
        )
        state.kill_switch = True
        await redis_client.set_portfolio_state(state.model_dump())
        await kill_switch_monitor._activate("RISK_001_drawdown")
        state = await paper_engine.get_portfolio_state()

    # RISK_002: daily loss > 3% -> halt new positions for remainder of session.
    # Store today's date so the halt is sticky for the day yet auto-clears tomorrow;
    # risk_manager reads this flag to reject new BUYs even if daily P&L recovers.
    if state.daily_pnl_pct < -DAILY_LOSS_LIMIT_PCT:
        logger.error(
            "RISK_002_BREACHED",
            event_type="RISK_002_BREACHED",
            payload={"daily_pnl_pct": state.daily_pnl_pct},
        )
        today = datetime.now(timezone.utc).date().isoformat()
        await redis_client.client.set(TRADING_HALTED_KEY, today)

    return state


async def get_state() -> PortfolioState:
    return await paper_engine.get_portfolio_state()


async def process_fills(fills: list[Fill] | None = None) -> PortfolioState:
    if fills is None:
        fills = await _pull_pending_fills()
    for fill in fills:
        logger.info(
            "fill_processed",
            event_type="fill_processed",
            payload=fill.model_dump(),
        )

    state = await paper_engine.get_portfolio_state()
    state = await _check_hard_risk_rules(state)

    await redis_client.set_portfolio_state(state.model_dump())

    from src.api.main import broadcast

    await broadcast({"event_type": "portfolio_state_update", "payload": state.model_dump()})

    logger.info(
        "state_manager_tick_complete",
        event_type="state_manager_tick_complete",
        payload={"fills_processed": len(fills), "total_value_usd": state.total_value_usd},
    )
    return state
