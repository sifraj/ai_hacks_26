import os
import sys
import logging
from datetime import date
from pathlib import Path

import structlog
from structlog.types import EventDict


def _add_required_fields(logger, method_name: str, event_dict: EventDict) -> EventDict:
    event_dict.setdefault("tick_id", None)
    event_dict.setdefault("agent_name", None)
    event_dict.setdefault("event_type", event_dict.get("event", "unknown"))
    event_dict.setdefault("payload", {})
    return event_dict


def configure_audit_logger(log_dir: str = "./logs", log_level: str = "INFO") -> None:
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_file = Path(log_dir) / f"audit_{date.today().isoformat()}.jsonl"

    # JSON renderer for file output
    json_renderer = structlog.processors.JSONRenderer()

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_required_fields,
    ]

    # File handler (JSON lines)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(message)s"))

    # Stdout handler (pretty)
    stdout_handler = logging.StreamHandler(sys.stdout)

    root_logger = logging.getLogger()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(stdout_handler)
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )

    # Pretty formatter for stdout, JSON for file
    stdout_handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processors=[structlog.dev.ConsoleRenderer()],
            foreign_pre_chain=shared_processors,
        )
    )
    file_handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processors=[json_renderer],
            foreign_pre_chain=shared_processors,
        )
    )


def get_logger(agent_name: str | None = None):
    logger = structlog.get_logger()
    if agent_name:
        logger = logger.bind(agent_name=agent_name)
    return logger


async def log_tick_summary(
    tick_id: str,
    signal_batch,
    regime,
    proposed,
    approved,
    cleared,
    fills,
) -> None:
    logger = get_logger()
    logger.info(
        "tick_summary",
        event_type="tick_summary",
        tick_id=tick_id,
        payload={
            "signal_count": len(signal_batch.signals) if signal_batch else 0,
            "regime": regime.regime if regime else None,
            "posture": regime.posture if regime else None,
            "proposed_count": len(proposed) if proposed else 0,
            "approved_count": len(approved) if approved else 0,
            "cleared_count": len(cleared) if cleared else 0,
            "fill_count": len(fills) if fills else 0,
        },
    )


# Module-level logger for convenience
audit_logger = structlog.get_logger()
