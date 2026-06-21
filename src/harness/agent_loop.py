from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.agents.cio_agent import cio_agent
from src.agents.compliance_agent import compliance_agent
from src.agents.execution_agent import execution_agent
from src.agents.portfolio_manager import portfolio_manager
from src.agents.risk_manager import risk_manager
from src.agents.analysts.momentum_analyst import momentum_analyst
from src.agents.analysts.onchain_analyst import onchain_analyst
from src.agents.analysts.sentiment_analyst import sentiment_analyst
from src.agents import state_manager
from src.config import settings
from src.harness.audit_logger import get_logger, log_tick_summary
from src.harness.websocket_broadcaster import broadcast_tick_update
from src.ingestors.market_ingestor import market_ingestor
from src.ingestors.onchain_ingestor import onchain_ingestor
from src.ingestors.sentiment_ingestor import sentiment_ingestor
from src.schemas.signals import Signal, SignalBatch

logger = get_logger("agent_loop")

TICK_LATENCY_WARNING_SECONDS = 60.0


def _flatten(signal_lists: list[list[Signal] | list[dict]]) -> list[Signal]:
    flat: list[Signal] = []
    for signals in signal_lists:
        for s in signals:
            flat.append(s if isinstance(s, Signal) else Signal.model_validate(s))
    return flat


RISK_TO_TRADE_STATUS = {"APPROVED": "APPROVED", "RESIZED": "APPROVED", "REJECTED": "REJECTED"}


async def _safe_broadcast(message: dict) -> None:
    try:
        from src.api.main import broadcast

        await broadcast(message)
    except Exception as e:
        logger.warning(
            "broadcast_failed",
            event_type="broadcast_failed",
            payload={"error": str(e), "original_event_type": message.get("event_type")},
        )


async def run_tick(tick_id: str) -> None:
    start = time.monotonic()

    portfolio_state = await state_manager.get_state()
    if portfolio_state.kill_switch:
        logger.warning(
            "tick_skipped",
            event_type="tick_skipped",
            tick_id=tick_id,
            payload={"reason": "kill_switch_active"},
        )
        return

    try:
        # Phase 1: Parallel ingestion
        await asyncio.gather(
            market_ingestor.run(),
            sentiment_ingestor.run(),
            onchain_ingestor.run(),
        )

        # Phase 2: Parallel analysis
        signals = await asyncio.gather(
            momentum_analyst.run(tick_id),
            sentiment_analyst.run(tick_id),
            onchain_analyst.run(tick_id),
        )
        signal_batch = SignalBatch(
            tick_id=tick_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            signals=_flatten(signals),
        )
        for s in signal_batch.signals:
            await _safe_broadcast({"event_type": "signal_generated", "payload": s.model_dump()})

        # Phase 3: Sequential decision chain
        regime = await cio_agent.run(signal_batch)
        await _safe_broadcast({"event_type": "regime_update", "payload": regime.model_dump()})

        portfolio_state = await state_manager.get_state()
        proposed = await portfolio_manager.run(signal_batch, regime, portfolio_state)
        for trade in proposed:
            await _safe_broadcast(
                {
                    "event_type": "trade_proposed",
                    "payload": {
                        "proposal_id": trade.proposal_id,
                        "tick_id": trade.tick_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "asset": trade.asset,
                        "side": trade.side,
                        "size_usd": trade.size_usd,
                        "status": "PROPOSED",
                        "trade_rationale": trade.trade_rationale,
                        "signal_ids": trade.signal_ids,
                    },
                }
            )

        approved = await risk_manager.run(proposed, portfolio_state)
        for decision in approved:
            await _safe_broadcast(
                {
                    "event_type": "trade_approved"
                    if decision.status != "REJECTED"
                    else "trade_rejected",
                    "payload": {
                        "proposal_id": decision.proposal_id,
                        "status": RISK_TO_TRADE_STATUS[decision.status],
                        "risk_decision": decision.model_dump(),
                    },
                }
            )

        cleared = await compliance_agent.run(approved, proposed)
        cleared_id_to_proposal_id: dict[str, str] = {}
        for cleared_trade in cleared:
            cleared_id_to_proposal_id[cleared_trade.cleared_id] = cleared_trade.proposal_id
            await _safe_broadcast(
                {
                    "event_type": "trade_cleared",
                    "payload": {
                        "proposal_id": cleared_trade.proposal_id,
                        "cleared_trade": cleared_trade.model_dump(),
                    },
                }
            )

        fills = await execution_agent.run(cleared, proposed)
        for fill in fills:
            proposal_id = cleared_id_to_proposal_id.get(fill.cleared_id)
            if proposal_id is not None:
                await _safe_broadcast(
                    {
                        "event_type": "trade_filled",
                        "payload": {
                            "proposal_id": proposal_id,
                            "status": "FILLED",
                            "fill": fill.model_dump(),
                        },
                    }
                )

        # Phase 4: State update
        updated_state = await state_manager.process_fills(fills)
        await log_tick_summary(tick_id, signal_batch, regime, proposed, approved, cleared, fills)
        await broadcast_tick_update(tick_id, updated_state)

        logger.info(
            "tick_complete",
            event_type="tick_complete",
            tick_id=tick_id,
            payload={"fill_count": len(fills)},
        )
    except Exception as e:
        logger.error(
            "tick_failed",
            event_type="tick_failed",
            tick_id=tick_id,
            payload={"error": str(e)},
        )
    finally:
        latency_seconds = time.monotonic() - start
        if latency_seconds > TICK_LATENCY_WARNING_SECONDS:
            logger.warning(
                "tick_latency_exceeded",
                event_type="tick_latency_exceeded",
                tick_id=tick_id,
                payload={"latency_seconds": latency_seconds},
            )
        else:
            logger.info(
                "tick_latency",
                event_type="tick_latency",
                tick_id=tick_id,
                payload={"latency_seconds": latency_seconds},
            )


async def _scheduled_run_tick() -> None:
    tick_id = str(uuid.uuid4())
    await run_tick(tick_id)


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _scheduled_run_tick,
        "interval",
        seconds=settings.tick_interval_seconds,
        id="agent_tick",
        max_instances=1,
        coalesce=True,
    )
    return scheduler
