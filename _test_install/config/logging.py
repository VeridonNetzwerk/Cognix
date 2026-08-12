"""Structured logging configuration.

Levels (configure via ``LOG_LEVEL`` in ``.env``):

* ``DEBUG``   - extremely verbose, prints every event including library noise.
* ``INFO``    - normal operational logging (default in production).
* ``WARNING`` - only abnormal but non-fatal events.
* ``ERROR``   - only failures.
* ``CRITICAL``- only catastrophic events.

The full console output of the current process is also tee'd to
``logs/latest.log``. The file is truncated on every start so it always
contains the most recent session in full.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import structlog

from config.settings import get_settings


def configure_logging() -> None:
    settings = get_settings()
    level_name = (settings.log_level or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    Path("logs").mkdir(parents=True, exist_ok=True)
    log_path = Path("logs") / "latest.log"

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.log_json:
        renderer = structlog.processors.JSONRenderer()
    else:
        # ConsoleRenderer with colours pollutes the log file with ANSI codes.
        renderer = structlog.dev.ConsoleRenderer(colors=False)

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    file_handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    file_handler.setLevel(level)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(logging.Formatter("%(message)s"))
    stream_handler.setLevel(level)

    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(stream_handler)
    root.addHandler(file_handler)
    root.setLevel(level)

    if level > logging.DEBUG:
        for noisy in ("uvicorn.access", "discord.gateway", "discord.client"):
            logging.getLogger(noisy).setLevel(max(level, logging.INFO))


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
