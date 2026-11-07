"""Shared pytest configuration: no service configuration from the shell, logging restored after
each test, the test database, the event loop's clock and its error reports."""

import asyncio
import logging
from collections.abc import Iterator

import pytest
import structlog

from tests.support.clock import LoopClock
from tests.support.postgres import migrated_database, server_url

#: Variables of the service configuration a developer's shell may export (dev.env sets one); the
#: in-process services of the tests must never pick them up.
SERVICE_CONFIGURATION = ("HURON_CONFIG_FILE", "HURON_ORGANIZATIONS")


@pytest.fixture(autouse=True)
def isolated_service_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """No configuration file or organization list from the shell; a test sets its own."""
    for name in SERVICE_CONFIGURATION:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def restored_logging() -> Iterator[None]:
    """The ``huron`` logger and structlog's configuration as they were before the test.

    A service's startup configures both (``configure_logging``); no test leaves that behind.
    """
    logger = logging.getLogger("huron")
    handlers, level, propagate = list(logger.handlers), logger.level, logger.propagate
    configuration = structlog.get_config()
    yield
    for handler in [h for h in logger.handlers if h not in handlers]:
        logger.removeHandler(handler)
        handler.close()
    logger.handlers[:] = handlers
    logger.setLevel(level)
    logger.propagate = propagate
    structlog.configure(**configuration)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """A database migrated to head, created once per session."""
    with server_url() as server, migrated_database(server) as url:
        yield url


@pytest.fixture
async def loop_clock(monkeypatch: pytest.MonkeyPatch) -> LoopClock:
    """The clock of the test's event loop, stopped until the test advances it."""
    loop = asyncio.get_running_loop()
    stopped = LoopClock(loop.time())
    monkeypatch.setattr(loop, "time", stopped.time)
    return stopped


@pytest.fixture
async def loop_errors() -> list[dict[str, object]]:
    """The reports that reach the exception handler of the test's event loop.

    A future whose exception nobody retrieved reports when it is collected.
    """
    reported: list[dict[str, object]] = []
    asyncio.get_running_loop().set_exception_handler(lambda _, context: reported.append(context))
    return reported
