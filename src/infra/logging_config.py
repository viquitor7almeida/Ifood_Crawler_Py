from __future__ import annotations

import logging
import os
import sys

try:
    import structlog
    HAS_STRUCTLOG = True
except ImportError:
    HAS_STRUCTLOG = False


_TIMESTAMP_FMT = "%Y-%m-%d %H:%M:%S"


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


def configure_logging():
    level_name = _env("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    fmt = "%(asctime)s [%(levelname)s] %(name)s - %(message)s"

    if HAS_STRUCTLOG:
        structlog.configure(
            processors=[
                structlog.stdlib.filter_by_level,
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.stdlib.PositionalArgumentsFormatter(),
                structlog.processors.TimeStamper(fmt=_TIMESTAMP_FMT, utc=True),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.dev.ConsoleRenderer()
                if sys.stderr.isatty()
                else structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )
        logging.basicConfig(level=level, format=fmt, stream=sys.stdout)
    else:
        logging.basicConfig(level=level, format=fmt, stream=sys.stdout)
