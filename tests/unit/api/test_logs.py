"""The service's log output: structlog events and stdlib records on stdout, at one level."""

import logging
import re

import pytest
import structlog

from huron.applications.api.app import create_app
from huron.applications.api.logs import HANDLER_NAME, LOGGER_NAME, configure_logging
from tests.support.api import settings

DECLARED = [{"name": "helio", "groups": {"org_admin": ["helio-org-admins"]}}]

#: A rendered line: an ISO UTC timestamp, the padded level, the event, the logger name, the fields.
LINE = re.compile(
    r"^\d{4}-\d\d-\d\dT[\d:.]+Z \[(?P<level>\w+)\s*\] (?P<event>.+?)\s+\[(?P<logger>[\w.]+)\]"
    r"(?: (?P<fields>.*))?$",
    re.MULTILINE,
)


def lines(out: str) -> list[re.Match[str]]:
    """The rendered lines of ``out``; every line must have the shared format."""
    matches = [LINE.match(line) for line in out.splitlines()]
    assert all(matches), out
    return [match for match in matches if match]


def our_handlers() -> list[logging.Handler]:
    """The handlers ``configure_logging`` installed on the ``huron`` logger."""
    return [h for h in logging.getLogger(LOGGER_NAME).handlers if h.get_name() == HANDLER_NAME]


async def startup(level: str) -> None:
    """Start and stop a service that declares ``helio``, logging at ``level``."""
    app = create_app(settings(organizations=DECLARED, log_level=level))
    async with app.router.lifespan_context(app):
        pass


async def test_startup_report_reaches_stdout_at_info(capsys: pytest.CaptureFixture[str]) -> None:
    await startup("info")
    found = lines(capsys.readouterr().out)
    assert [(m["level"], m["event"], m["logger"], m["fields"]) for m in found] == [
        ("info", "bootstrap.organization_created", "huron.api.bootstrap", "name=helio"),
        ("info", "bootstrap.organization_regranted", "huron.api.bootstrap", "name=helio"),
    ]


async def test_a_warning_level_suppresses_the_info_report(
    capsys: pytest.CaptureFixture[str],
) -> None:
    await startup("WARNING")
    assert capsys.readouterr().out == ""


def test_stdlib_and_structlog_lines_share_one_format(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    logging.getLogger("huron.api").info("a plain %s", "record")
    structlog.get_logger("huron.core.security.broker.exchange").info(
        "broker.exchange", subject="alice", group_count=2
    )
    found = lines(capsys.readouterr().out)
    assert [(m["level"], m["event"], m["logger"], m["fields"]) for m in found] == [
        ("info", "a plain record", "huron.api", None),
        (
            "info",
            "broker.exchange",
            "huron.core.security.broker.exchange",
            "group_count=2 subject=alice",
        ),
    ]


@pytest.mark.parametrize(
    ("level", "shown"),
    [
        ("DEBUG", ["debug", "info", "warning", "error"]),
        ("info", ["info", "warning", "error"]),
        ("WARNING", ["warning", "error"]),
        ("critical", []),
    ],
)
def test_both_front_ends_honour_the_level(
    capsys: pytest.CaptureFixture[str], level: str, shown: list[str]
) -> None:
    configure_logging(level)
    stdlib = logging.getLogger("huron.api")
    bound = structlog.get_logger("huron.applications.api.problems")
    for name in ("debug", "info", "warning", "error"):
        getattr(stdlib, name)("stdlib %s", name)
        getattr(bound, name)(f"structlog {name}")
    found = [(m["level"], m["event"]) for m in lines(capsys.readouterr().out)]
    expected = [(name, f"{side} {name}") for name in shown for side in ("stdlib", "structlog")]
    assert found == expected


def test_configuring_twice_keeps_one_handler_at_the_last_level(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO")
    configure_logging("WARNING")
    assert len(our_handlers()) == 1
    assert logging.getLogger(LOGGER_NAME).level == logging.WARNING
    logging.getLogger("huron.api").warning("once")
    assert [m["event"] for m in lines(capsys.readouterr().out)] == ["once"]


def test_other_libraries_loggers_are_left_alone(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("DEBUG")
    logging.getLogger("httpx").info("a request")
    assert capsys.readouterr().out == ""


def test_exceptions_render_their_traceback(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    try:
        raise ValueError("bad")
    except ValueError:
        logging.getLogger("huron.api").exception("failed")
    out = capsys.readouterr().out
    assert LINE.match(out)
    assert "ValueError: bad" in out


def test_records_still_reach_the_root_logger(caplog: pytest.LogCaptureFixture) -> None:
    configure_logging("INFO")
    structlog.get_logger("huron.api.bootstrap").info("bootstrap.organization_created", name="helio")
    found = [(r.name, r.msg["event"], r.msg["name"]) for r in caplog.records]
    assert found == [("huron.api.bootstrap", "bootstrap.organization_created", "helio")]
