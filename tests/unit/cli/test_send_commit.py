"""``send_commit``: the CLI sends a commit and reads the state of a request that waits."""

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from huron.applications.cli.client import ApiClient
from huron.applications.cli.deadline import Deadline
from huron.applications.cli.errors import CliError, ExitCode
from huron.applications.cli.sync import COMMIT_POLL, COMMIT_WAIT, send_commit
from tests.support.clock import MonotonicClock

STATUS = "/api/v1/commit-requests/r1"
#: The timeout of each request, unless the deadline of a wait limits it.
TIMEOUT = 30.0


def outcome(state: str, refusal: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"request_id": "r1", "state": state, "version": 4, "refusal": refusal}


def answer(state: str, status: int = 200) -> httpx.Response:
    headers = {"Location": STATUS} if status == 202 else {}
    return httpx.Response(status, json=outcome(state), headers=headers)


def send(
    *answers: httpx.Response,
    clock: MonotonicClock | None = None,
    during: Callable[[httpx.Request], None] = lambda _: None,
) -> tuple[dict[str, Any], list[float], list[httpx.Request]]:
    """Send a commit to fixed answers; the result, the sleeps and the requests."""
    clock = clock or MonotonicClock()
    queue, sent = list(answers), []

    def handle(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        during(request)
        return queue.pop(0)

    http = httpx.Client(transport=httpx.MockTransport(handle), timeout=TIMEOUT)
    api = ApiClient(http, "http://huron.test", sleep=clock.sleep)
    result = send_commit(
        api, "c1", {"request_id": "r1"}, lambda seconds: Deadline(seconds, clock, clock.sleep)
    )
    return result, clock.slept, sent


def test_a_commit_that_succeeds_at_once_needs_no_wait() -> None:
    result, slept, sent = send(answer("succeeded"))
    assert (result["state"], slept) == ("succeeded", [])
    assert [request.url.path for request in sent] == ["/api/v1/collections/c1/commits"]


@pytest.mark.parametrize("state", ["accepted", "blocked"])
def test_an_accepted_or_blocked_commit_is_read_until_it_succeeds(state: str) -> None:
    result, slept, sent = send(answer(state, 202), answer(state), answer("succeeded"))
    assert result["state"] == "succeeded"
    assert slept == [COMMIT_POLL, COMMIT_POLL]
    assert [request.url.path for request in sent[1:]] == [STATUS, STATUS]


def test_a_request_that_the_service_rejected_raises_its_refusal() -> None:
    refusal = {
        "code": "COLLECTION_BUSY",
        "detail": "the collection has a pending commit",
        "context": {},
    }
    rejected = httpx.Response(200, json=outcome("rejected", refusal))
    with pytest.raises(CliError) as raised:
        send(answer("accepted", 202), rejected)
    assert (raised.value.code, raised.value.exit_code) == ("COLLECTION_BUSY", ExitCode.CONFLICT)
    assert raised.value.message == "the collection has a pending commit"


def test_a_request_that_stays_blocked_names_the_operator() -> None:
    polls = int(COMMIT_WAIT / COMMIT_POLL)
    with pytest.raises(CliError) as raised:
        send(answer("blocked", 202), *[answer("blocked")] * polls)
    assert raised.value.message == "the service accepted the commit, but a step of it is blocked"
    assert raised.value.hint == "a platform administrator must resolve the commit request"
    assert (raised.value.code, raised.value.exit_code) == ("PUBLICATION_BLOCKED", ExitCode.CONFLICT)


def test_an_abandoned_request_says_so() -> None:
    with pytest.raises(CliError) as raised:
        send(answer("accepted", 202), answer("abandoned"))
    assert raised.value.message == "a platform administrator abandoned the commit"
    assert (raised.value.hint, raised.value.exit_code) == (
        "run `huron push` again",
        ExitCode.CONFLICT,
    )


def test_a_request_that_stays_accepted_ends_the_wait_at_the_deadline() -> None:
    polls = int(COMMIT_WAIT / COMMIT_POLL)
    clock = MonotonicClock()
    start = clock.now
    with pytest.raises(CliError) as raised:
        send(answer("accepted", 202), *[answer("accepted")] * polls, clock=clock)
    assert raised.value.message == (
        "the service accepted the commit, but did not finish it in 600 seconds"
    )
    assert raised.value.hint == "to see the result later, run `huron get files`"
    assert clock.now - start == COMMIT_WAIT
    assert clock.slept == [COMMIT_POLL] * polls


def test_the_wait_counts_the_time_of_its_requests() -> None:
    clock = MonotonicClock()
    reads: list[httpx.Request] = []
    durations = [570.0, 17.0]

    def take_time(request: httpx.Request) -> None:
        if request.url.path == STATUS:
            reads.append(request)
            clock.advance(durations.pop(0))

    with pytest.raises(CliError, match="did not finish it in 600 seconds"):
        send(answer("accepted", 202), *[answer("accepted")] * 2, clock=clock, during=take_time)
    assert clock.slept == [COMMIT_POLL, COMMIT_POLL, 3.0]
    timeouts = [request.extensions["timeout"]["read"] for request in reads]
    assert timeouts == [TIMEOUT, 20.0]
