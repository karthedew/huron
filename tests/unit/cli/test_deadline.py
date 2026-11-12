"""The deadline of a wait: the time that remains limits each sleep and each request timeout."""

import httpx
import pytest

from huron.applications.cli.client import ApiClient
from huron.applications.cli.deadline import Deadline, DeadlinePassed, poll
from huron.applications.cli.errors import CliError
from tests.support.cli import Cli
from tests.support.clock import MonotonicClock


@pytest.fixture
def clock() -> MonotonicClock:
    return MonotonicClock()


def deadline(clock: MonotonicClock, seconds: float = 10.0) -> Deadline:
    return Deadline(seconds, clock, clock.sleep)


def test_the_time_that_remains_falls_with_the_clock_and_stops_at_zero(
    clock: MonotonicClock,
) -> None:
    limit = deadline(clock)
    assert limit.remaining() == 10.0
    clock.advance(4.0)
    assert limit.remaining() == 6.0
    clock.advance(7.0)
    assert limit.remaining() == 0.0


def test_a_pause_sleeps_its_time_while_more_time_remains(clock: MonotonicClock) -> None:
    limit = deadline(clock)
    assert limit.pause(3.0) is True
    assert (clock.slept, limit.remaining()) == ([3.0], 7.0)


def test_a_pause_sleeps_only_the_time_that_remains(clock: MonotonicClock) -> None:
    limit = deadline(clock)
    clock.advance(8.0)
    assert limit.pause(5.0) is False
    assert clock.slept == [2.0]


def test_a_pause_after_the_deadline_does_not_sleep(clock: MonotonicClock) -> None:
    limit = deadline(clock, 0.0)
    assert limit.pause(5.0) is False
    assert clock.slept == []


def test_a_timeout_is_limited_part_by_part(clock: MonotonicClock) -> None:
    limit = deadline(clock)
    clock.advance(4.0)
    limited = limit.limit(httpx.Timeout(30.0, connect=2.0, pool=None))
    assert (limited.connect, limited.read, limited.write, limited.pool) == (2.0, 6.0, 6.0, 6.0)


def test_poll_returns_a_first_value_that_does_not_wait_without_a_read(
    clock: MonotonicClock,
) -> None:
    def read() -> str:
        raise AssertionError("poll must not read")

    value = poll("done", read, lambda v: v == "wait", deadline(clock), 5.0)
    assert (value, clock.slept) == ("done", [])


def test_poll_reads_after_each_interval_until_the_value_does_not_wait(
    clock: MonotonicClock,
) -> None:
    values = iter(["wait", "done"])
    value = poll("wait", lambda: next(values), lambda v: v == "wait", deadline(clock), 3.0)
    assert (value, clock.slept) == ("done", [3.0, 3.0])


def test_poll_stops_at_the_deadline_with_the_last_value(clock: MonotonicClock) -> None:
    reads: list[float] = []

    def read() -> str:
        reads.append(clock.now)
        return "wait"

    value = poll("wait", read, lambda v: v == "wait", deadline(clock), 4.0)
    assert value == "wait"
    assert clock.slept == [4.0, 4.0, 2.0]
    assert reads == [104.0, 108.0]


def test_poll_ends_with_the_last_value_when_a_read_passes_the_deadline(
    clock: MonotonicClock,
) -> None:
    answers: list[str | DeadlinePassed] = ["still", DeadlinePassed()]

    def read() -> str:
        answer = answers.pop(0)
        if isinstance(answer, DeadlinePassed):
            raise answer
        return answer

    value = poll("wait", read, lambda v: v != "done", deadline(clock), 3.0)
    assert (value, answers, clock.slept) == ("still", [], [3.0, 3.0])


def client(
    clock: MonotonicClock,
    fails: int,
    error: type[httpx.TransportError] = httpx.ConnectError,
    *,
    slow: bool = False,
) -> tuple[ApiClient, list[httpx.Request]]:
    """An API client whose first ``fails`` requests fail with ``error``; by default they lose
    their connection. A request that times out takes the whole read timeout of the request,
    and so does each failing request when ``slow``.
    """
    sent: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if len(sent) <= fails:
            if slow or issubclass(error, httpx.TimeoutException):
                clock.advance(request.extensions["timeout"]["read"])
            raise error("down", request=request)
        return httpx.Response(200, json={"ok": True})

    http = httpx.Client(transport=httpx.MockTransport(handle), timeout=30.0)
    return ApiClient(http, "http://huron.test", sleep=clock.sleep), sent


def test_a_read_with_a_deadline_limits_its_timeout(clock: MonotonicClock) -> None:
    api, sent = client(clock, 0)
    assert api.get("/x", deadline=deadline(clock, 12.0)) == {"ok": True}
    assert sent[0].extensions["timeout"]["read"] == 12.0


def test_a_read_with_a_deadline_sleeps_before_a_retry_only_the_time_that_remains(
    clock: MonotonicClock,
) -> None:
    api, sent = client(clock, 2)
    limit = deadline(clock, 1.0)
    with pytest.raises(CliError, match="unreachable"):
        api.get("/x", deadline=limit)
    assert clock.slept == [0.5, 0.5]
    assert len(sent) == 2


def test_a_read_with_a_deadline_retries_while_time_remains(clock: MonotonicClock) -> None:
    api, sent = client(clock, 2)
    assert api.get("/x", deadline=deadline(clock)) == {"ok": True}
    assert clock.slept == [0.5, 1.0]
    timeouts = [request.extensions["timeout"]["read"] for request in sent]
    assert timeouts == [10.0, 9.5, 8.5]


@pytest.mark.parametrize(
    ("error", "raised", "message"),
    [
        (httpx.ReadTimeout, DeadlinePassed, None),
        (httpx.ReadError, CliError, r"^the Huron API at http://huron\.test is unreachable: down$"),
    ],
    ids=["a timeout", "a lost connection"],
)
def test_a_read_that_fails_when_no_time_remains_raises_deadline_passed_only_for_a_timeout(
    clock: MonotonicClock,
    error: type[httpx.TransportError],
    raised: type[Exception],
    message: str | None,
) -> None:
    api, sent = client(clock, 1, error, slow=True)
    with pytest.raises(raised, match=message):
        api.get("/x", deadline=deadline(clock, 12.0))
    assert (len(sent), clock.slept) == (1, [])


def test_a_read_that_times_out_while_time_remains_is_sent_again(clock: MonotonicClock) -> None:
    api, sent = client(clock, 1, httpx.ReadTimeout)
    assert api.get("/x", deadline=deadline(clock, 40.0)) == {"ok": True}
    timeouts = [request.extensions["timeout"]["read"] for request in sent]
    assert (timeouts, clock.slept) == ([30.0, 9.5], [0.5])


def test_a_read_without_a_deadline_that_times_out_reports_the_api_unreachable(
    clock: MonotonicClock,
) -> None:
    api, sent = client(clock, 3, httpx.ReadTimeout)
    with pytest.raises(CliError, match="unreachable"):
        api.get("/x")
    assert len(sent) == 3


def test_the_services_give_deadlines_on_their_monotonic_clock_and_sleep(cli: Cli) -> None:
    services, _, _ = cli.services()
    limit = services.deadline(7.0)
    assert limit.pause(5.0) is True
    assert (cli.slept, limit.remaining()) == ([5.0], 2.0)
