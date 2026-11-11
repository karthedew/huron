"""``send_commit``: the CLI sends a commit and reads the state of a request that waits."""

from typing import Any

import httpx
import pytest

from huron.applications.cli.client import ApiClient
from huron.applications.cli.errors import CliError, ExitCode
from huron.applications.cli.sync import COMMIT_POLL, COMMIT_WAIT, send_commit

STATUS = "/api/v1/commit-requests/r1"


def outcome(state: str, refusal: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"request_id": "r1", "state": state, "version": 4, "refusal": refusal}


def accepted() -> httpx.Response:
    return httpx.Response(202, json=outcome("accepted"), headers={"Location": STATUS})


def send(*answers: httpx.Response) -> tuple[dict[str, Any], list[float], list[str]]:
    queue, slept, paths = list(answers), [], []

    def handle(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return queue.pop(0)

    api = ApiClient(httpx.Client(transport=httpx.MockTransport(handle)), "http://huron.test")
    result = send_commit(api, "c1", {"request_id": "r1"}, slept.append)
    return result, slept, paths


def test_a_commit_that_succeeds_at_once_needs_no_wait() -> None:
    result, slept, paths = send(httpx.Response(200, json=outcome("succeeded")))
    assert (result["state"], slept, paths) == ("succeeded", [], ["/api/v1/collections/c1/commits"])


def test_an_accepted_commit_is_read_until_it_succeeds() -> None:
    result, slept, paths = send(
        accepted(),
        httpx.Response(200, json=outcome("accepted")),
        httpx.Response(200, json=outcome("succeeded")),
    )
    assert result["state"] == "succeeded"
    assert slept == [COMMIT_POLL, COMMIT_POLL]
    assert paths[1:] == [STATUS, STATUS]


def test_a_request_that_the_service_rejected_raises_its_refusal() -> None:
    refusal = {
        "code": "COLLECTION_BUSY",
        "detail": "the collection has a pending commit",
        "context": {},
    }
    with pytest.raises(CliError) as raised:
        send(accepted(), httpx.Response(200, json=outcome("rejected", refusal)))
    assert (raised.value.code, raised.value.exit_code) == ("COLLECTION_BUSY", ExitCode.CONFLICT)
    assert raised.value.message == "the collection has a pending commit"


def test_a_blocked_request_names_the_operator() -> None:
    with pytest.raises(CliError) as raised:
        send(httpx.Response(202, json=outcome("blocked"), headers={"Location": STATUS}))
    assert raised.value.message == "the service accepted the commit, but a step of it is blocked"
    assert raised.value.hint == "a platform administrator must resolve the commit request"
    assert (raised.value.code, raised.value.exit_code) == ("PUBLICATION_BLOCKED", ExitCode.CONFLICT)


def test_an_abandoned_request_says_so() -> None:
    with pytest.raises(CliError) as raised:
        send(accepted(), httpx.Response(200, json=outcome("abandoned")))
    assert raised.value.message == "a platform administrator abandoned the commit"
    assert (raised.value.hint, raised.value.exit_code) == (
        "run `huron push` again",
        ExitCode.CONFLICT,
    )


def test_a_request_that_stays_accepted_ends_the_wait_after_the_limit() -> None:
    polls = int(COMMIT_WAIT / COMMIT_POLL)
    answers = [httpx.Response(200, json=outcome("accepted")) for _ in range(polls)]
    with pytest.raises(CliError) as raised:
        send(accepted(), *answers)
    assert raised.value.message == (
        "the service accepted the commit, but did not finish it in 600 seconds"
    )
    assert raised.value.hint == "to see the result later, run `huron get files`"
