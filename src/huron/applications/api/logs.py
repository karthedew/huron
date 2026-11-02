"""The service's log output: one stdout handler and one line format for stdlib and structlog.

Huron's own events go through structlog, one ``area.event`` name per line with key=value fields
(``bootstrap.organization_created``, ``api.unexpected_error``, ``broker.exchange``); a record a
module writes through the standard library's ``logging`` under ``huron`` is rendered the same way.
:func:`configure_logging` routes both into a single handler on the ``huron`` logger, rendered
by structlog's :class:`~structlog.stdlib.ProcessorFormatter`, and filters both at the configured
level. Other libraries' loggers are left alone; uvicorn keeps its own access and error logging.
"""

from __future__ import annotations

import logging
import sys

import structlog
from structlog.typing import Processor

__all__ = ["HANDLER_NAME", "LOGGER_NAME", "configure_logging"]

#: The logger every Huron module logs under, stdlib and structlog alike.
LOGGER_NAME = "huron"

#: The name of the handler :func:`configure_logging` installs, so a second call replaces it.
HANDLER_NAME = "huron.stdout"


def configure_logging(level: str) -> None:
    """Send Huron's log records at ``level`` and above to stdout, in one format.

    ``level`` is a standard level name (``DEBUG``, ``INFO``, ``WARNING``, ``ERROR`` or
    ``CRITICAL``, any case). Calling it again replaces the handler it installed and the level,
    so it never adds a second handler.
    """
    numeric = logging.getLevelNamesMapping()[level.upper()]
    shared = _shared_processors()
    handler = logging.StreamHandler(sys.stdout)
    handler.set_name(HANDLER_NAME)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.dev.ConsoleRenderer(
                    colors=False, exception_formatter=structlog.dev.plain_traceback
                ),
            ],
        )
    )
    logger = logging.getLogger(LOGGER_NAME)
    for existing in [h for h in logger.handlers if h.get_name() == HANDLER_NAME]:
        logger.removeHandler(existing)
        existing.close()
    logger.addHandler(handler)
    logger.setLevel(numeric)
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            *shared,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )


def _shared_processors() -> list[Processor]:
    """The fields every line carries, whether it began in stdlib logging or in structlog."""
    return [
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
    ]
