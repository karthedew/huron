"""Shared pytest configuration: no service configuration from the shell, a fixed umask, logging
restored after each test, the test database, the event loop's clock, its error reports and modes
restored."""

import asyncio
import logging
import os
import stat
from collections.abc import Callable, Iterator
from pathlib import Path

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
def fixed_umask() -> Iterator[None]:
    """Umask ``022`` for each test, as the API sets at start (``SERVICE_UMASK``); restored after."""
    previous = os.umask(0o022)
    yield
    os.umask(previous)


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


@pytest.fixture
def temporary_mode() -> Iterator[Callable[[Path, int], None]]:
    """``chmod`` for real entries; each gets its mode back at teardown, so cleanup can remove it."""
    changed: list[tuple[Path, int]] = []

    def change(path: Path, mode: int) -> None:
        changed.append((path, stat.S_IMODE(os.lstat(path).st_mode)))
        os.chmod(path, mode)

    yield change
    for path, mode in reversed(changed):
        os.chmod(path, mode)
