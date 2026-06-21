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
    # Remove handlers from any prior configuration so we don't double-log on reconfigure.
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
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
        # IMPORTANT: caching off. Module-level loggers are bound at import time —
        # before this runs in the FastAPI lifespan — and with caching on, those
        # pre-bound loggers freeze the default (stdout-only) config and never reach
        # the file/handlers configured here. Re-resolving per call fixes that.
        cache_logger_on_first_use=False,
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


class _LazyAuditLogger:
    """Resolves a fresh structlog logger on every call so log events always route
    through the *currently configured* pipeline. Module-level loggers are created at
    import time — before configure_audit_logger() runs in the FastAPI lifespan — and
    a structlog logger bound that early permanently freezes the default (stdout-only)
    config and never reaches the file handlers. Re-resolving per call avoids that."""

    def __init__(self, agent_name: str | None = None) -> None:
        self._agent_name = agent_name

    def _resolve(self):
        logger = structlog.get_logger()
        if self._agent_name:
            logger = logger.bind(agent_name=self._agent_name)
        return logger

    def bind(self, **kwargs):
        agent_name = kwargs.pop("agent_name", self._agent_name)
        new = _LazyAuditLogger(agent_name)
        if kwargs:
            new._extra = {**getattr(self, "_extra", {}), **kwargs}
        return new

    def _log(self, level: str, *args, **kwargs):
        extra = getattr(self, "_extra", None)
        if extra:
            kwargs = {**extra, **kwargs}
        return getattr(self._resolve(), level)(*args, **kwargs)

    def info(self, *args, **kwargs):
        return self._log("info", *args, **kwargs)

    def warning(self, *args, **kwargs):
        return self._log("warning", *args, **kwargs)

    def error(self, *args, **kwargs):
        return self._log("error", *args, **kwargs)

    def debug(self, *args, **kwargs):
        return self._log("debug", *args, **kwargs)


def get_logger(agent_name: str | None = None) -> _LazyAuditLogger:
    return _LazyAuditLogger(agent_name)


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
audit_logger = _LazyAuditLogger()
