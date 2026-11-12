"""Working copies: checkout, staging, pull and push of one collection.

A push saves its commit request, the request ID and the exact body, before it sends it. While
that pending commit exists, ``add``, ``rm``, ``pull`` and ``checkout`` refuse, and the next push
first reads the saved outcome of the request on the service. The CLI never infers the outcome
of a commit from the version of the collection.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

from huron.applications.cli.client import ApiClient
from huron.applications.cli.deadline import Deadline, poll
from huron.applications.cli.errors import ApiError, CliError, ExitCode, UsageError
from huron.applications.cli.localstate import PendingCommit, StagedAdd, WorkingState
from huron.applications.cli.services import Services
from huron.applications.cli.sources import SkippedEntry, collect_sources
from huron.applications.cli.uploads import Uploader, UploadService
from huron.core.lake.publications.models import MAX_ENTRIES
from huron.schema.naming import rel_path_key

__all__ = [
    "COMMIT_POLL",
    "COMMIT_WAIT",
    "PushResult",
    "RmAction",
    "checkout",
    "current",
    "pull",
    "push",
    "recorded_files",
    "refuse_pending",
    "send_commit",
    "stage_paths",
    "unstage_or_remove",
]


#: The seconds between two reads of a commit request that the service did not finish yet.
COMMIT_POLL = 5.0
#: The most seconds the CLI waits for a commit request that is accepted or blocked.
COMMIT_WAIT = 600.0

#: The states of a commit request that can still end in success.
_UNFINISHED = frozenset({"accepted", "blocked"})
#: The states of a commit request that ended without a change.
_REFUSED = frozenset({"rejected", "abandoned"})


@dataclass(frozen=True, slots=True)
class PushResult:
    """What a push changed."""

    before: int
    after: int
    adds: int
    removes: int


class RmAction(StrEnum):
    """What ``huron rm`` did to one path; the value reads before the path."""

    UNSTAGED_ADD = "unstaged"
    UNSTAGED_REMOVE = "unstaged removal of"
    STAGED_REMOVE = "staged removal of"


def checkout(services: Services, collection: dict[str, Any]) -> WorkingState:
    """Record a working copy of ``collection`` and make it current; its stage is kept.

    Refuses while the working copy of ``collection`` or the current working copy has a
    pending commit.
    """
    collection_id = str(collection["id"])
    with services.state.locked():
        refuse_pending(services, collection_id)
        working = services.state.check_out(
            collection_id,
            str(collection["identifier"]),
            int(collection["version"]),
            collection.get("path"),
        )
        services.save_config(replace(services.config, current_collection=working.collection_id))
    return working


def refuse_pending(services: Services, collection_id: str | None = None) -> None:
    """Refuse while the working copy of ``collection_id`` or the current working copy has a
    pending commit, as :func:`checkout` does.

    A command that changes the service and then calls :func:`checkout` calls this first, so
    that it refuses before the change.
    """
    for chosen in (collection_id, services.config.current_collection):
        _refuse_pending(None if chosen is None else services.state.working(chosen))


def current(services: Services) -> WorkingState:
    """The checked-out working copy."""
    collection_id = services.config.current_collection
    working = None if collection_id is None else services.state.working(collection_id)
    if working is None:
        raise UsageError(
            "there is no current collection",
            hint="run `huron checkout <identifier>`, or run `huron checkout` to choose one",
        )
    return working


def send_commit(
    api: ApiClient,
    collection_id: str,
    body: dict[str, Any],
    deadline: Callable[[float], Deadline],
) -> dict[str, Any]:
    """Send the commit ``body``, and wait for the request while it is accepted or blocked.

    The wait reads the state of the request every :data:`COMMIT_POLL` seconds until a deadline
    :data:`COMMIT_WAIT` seconds away, which ``deadline`` gives. Returns the request when it
    succeeded. A request that the service refused raises the refusal, and a blocked, abandoned
    or still accepted request raises an error that says so.
    """
    response = api.request("POST", f"/api/v1/collections/{collection_id}/commits", json=body)
    outcome = _waited(api, response.json(), deadline)
    if outcome["state"] != "succeeded":
        raise _unfinished(outcome, saved=False)
    return outcome


def recorded_files(api: ApiClient, collection_id: str) -> dict[str, dict[str, Any]]:
    """Recorded files by case-folded path."""
    return {
        rel_path_key(item["rel_path"]): item
        for item in api.pages(f"/api/v1/collections/{collection_id}/files")
    }


def stage_paths(
    services: Services,
    working: WorkingState,
    paths: list[Path],
    rename: str | None,
    recursive: bool,
) -> tuple[list[StagedAdd], list[SkippedEntry]]:
    """Stage local files (and, with ``recursive``, directories) for the next push.

    Each add records the size, the modification time and the sha256 of its file, read before
    the state lock is taken. An add replaces a staged add of the same path and unstages its
    removal. Refuses while the working copy has a pending commit. Returns the adds and the
    entries of the directories that the walk skipped; see
    :func:`~huron.applications.cli.sources.collect_sources`.
    """
    _refuse_pending(working)
    staged, skipped = collect_sources(paths, rename, recursive)
    keys = {rel_path_key(add.rel_path) for add in staged}
    with _changing(services, working.collection_id) as stage:
        stage.adds = [add for add in stage.adds if rel_path_key(add.rel_path) not in keys] + staged
        stage.removes = [path for path in stage.removes if rel_path_key(path) not in keys]
    return staged, skipped


def unstage_or_remove(
    services: Services, working: WorkingState, rel_paths: list[str]
) -> list[tuple[RmAction, str]]:
    """Drop a staged add or removal, or stage the removal of a recorded file, for each path.

    Returns what was done to each path, in order; a path already staged for removal is unstaged,
    so ``huron rm`` undoes itself. Nothing is written when a path is neither recorded nor staged.
    Refuses while the working copy has a pending commit.
    """
    recorded = recorded_files(services.api(), working.collection_id)
    with _changing(services, working.collection_id) as stage:
        return [item for rel_path in rel_paths for item in _rm_one(stage, recorded, rel_path)]


def pull(services: Services, working: WorkingState) -> tuple[WorkingState, list[str]]:
    """Catch the working copy up with the service; drops staged removes no longer recorded.

    Refuses while the working copy has a pending commit.
    """
    api = services.api()
    collection = api.get(f"/api/v1/collections/{working.collection_id}")
    recorded = recorded_files(api, working.collection_id)
    with services.state.locked():
        with _changing(services, working.collection_id) as stage:
            dropped = [path for path in stage.removes if rel_path_key(path) not in recorded]
            stage.removes = [path for path in stage.removes if rel_path_key(path) in recorded]
        return checkout(services, collection), dropped


def push(services: Services, working: WorkingState, message: str | None) -> PushResult:
    """Upload the staged files through tusd and commit them with the version they were based on.

    The push holds the push lock of the working copy from start to end. A pending commit of an
    earlier push comes first: the push reads its saved outcome, or sends the same request ID
    and body again when the service does not know the request, and does nothing else.

    Otherwise the push refuses a stage of more than 10,000 entries. The service checks the
    commit with a dry run, so a push it would refuse fails before any byte is uploaded. Before
    it sends a file, the push checks the size and the modification time that ``huron add``
    recorded. The stage records each upload attempt, so a push that stops continues on the next
    push. The push then saves the commit, with a new request ID and the sealed uploads of the
    adds that are still staged, before it sends it.

    The pushed changes leave the stage only when the request succeeded, and the stage gets the
    new base version in the same write. A rejected or abandoned request keeps the stage. A
    request that is still accepted or blocked at the deadline keeps the pending commit.
    """
    with services.state.push_lock(working.collection_id):
        stage = current(services)
        api = services.api()
        pending = stage.pending_commit
        outcome = None if pending is None else _saved_outcome(api, pending)
        if pending is None:
            _upload(services, api, stage, message)
            pending = _save_pending(services, stage.collection_id, message)
        if outcome is None:
            outcome = _send(services, api, stage.collection_id, pending)
        outcome = _waited(api, outcome, services.deadline)
        return _settle(services, stage.collection_id, pending, outcome)


@contextmanager
def _changing(services: Services, collection_id: str) -> Generator[WorkingState]:
    """The working copy under the state lock, written when the block ends.

    Refuses when the working copy has a pending commit, and then writes nothing.
    """
    with services.state.changing(collection_id) as working:
        _refuse_pending(working)
        yield working


def _refuse_pending(working: WorkingState | None) -> None:
    if working is not None and working.pending_commit is not None:
        raise CliError(
            f"the CLI did not get the result of the last commit of {working.identifier}",
            ExitCode.CONFLICT,
            hint="run `huron push` to get the result. Then run the command again",
        )


def _upload(services: Services, api: ApiClient, stage: WorkingState, message: str | None) -> None:
    """Check the stage and the collection, ask the service for a dry run, and upload the adds."""
    entries = len(stage.adds) + len(stage.removes)
    if entries > MAX_ENTRIES:
        raise CliError(
            f"the stage holds {entries:,} changes. A push can send at most {MAX_ENTRIES:,} changes",
            ExitCode.VALIDATION,
            hint=(
                "push the changes in parts. To unstage a path, run `huron rm <path>`."
                " Stage the path again after the push"
            ),
        )
    collection = api.get(f"/api/v1/collections/{stage.collection_id}")
    if int(collection["version"]) != stage.base_version:
        raise CliError(
            f"{stage.identifier} is at version {collection['version']},"
            f" but your working copy is at version {stage.base_version}",
            ExitCode.CONFLICT,
            hint="run `huron pull`",
            code="BASE_VERSION_CONFLICT",
        )
    if collection.get("path") is None:
        raise CliError(
            f"{stage.identifier} is a draft",
            ExitCode.CONFLICT,
            hint="run `huron activate collection`",
        )
    uploader = _uploader(services, api) if stage.adds else None
    api.post(
        f"/api/v1/collections/{stage.collection_id}/commits",
        params={"dry_run": "true"},
        json=_body(services, stage, message, sealed_only=False),
    )
    if uploader is not None:
        _upload_files(services, stage, uploader)


def _save_pending(services: Services, collection_id: str, message: str | None) -> PendingCommit:
    """Save the commit of the sealed adds and the removes that are still staged, before it is
    sent.
    """
    with services.state.changing(collection_id) as stage:
        body = {"request_id": str(uuid.uuid4()), **_body(services, stage, message)}
        stage.pending_commit = PendingCommit(body["request_id"], body)
        return stage.pending_commit


def _saved_outcome(api: ApiClient, pending: PendingCommit) -> dict[str, Any] | None:
    """The saved state of the pending commit; ``None`` when the service does not know it."""
    try:
        outcome: dict[str, Any] = api.get(f"/api/v1/commit-requests/{pending.request_id}")
    except ApiError as error:
        if error.code == "COMMIT_REQUEST_NOT_FOUND":
            return None
        raise
    return outcome


def _send(
    services: Services, api: ApiClient, collection_id: str, pending: PendingCommit
) -> dict[str, Any]:
    """Send the saved body of the pending commit; the state of the request in the answer.

    A refusal (an HTTP status from 400 to 499) is final for the request, so the pending commit
    is cleared and the stage stays. After any other failure the pending commit stays, and the
    next push reads the outcome.
    """
    path = f"/api/v1/collections/{collection_id}/commits"
    try:
        response = api.request("POST", path, json=pending.body)
    except ApiError as error:
        status = (error.problem or {}).get("status")
        if isinstance(status, int) and 400 <= status < 500:
            _clear_pending(services, collection_id)
        raise
    outcome: dict[str, Any] = response.json()
    return outcome


def _waited(
    api: ApiClient, outcome: dict[str, Any], deadline: Callable[[float], Deadline]
) -> dict[str, Any]:
    """The state of the request once it is not accepted or blocked, or at the deadline."""
    if outcome["state"] not in _UNFINISHED:
        return outcome
    limit = deadline(COMMIT_WAIT)
    path = f"/api/v1/commit-requests/{outcome['request_id']}"
    return poll(
        outcome,
        lambda: api.get(path, deadline=limit),
        lambda state: state["state"] in _UNFINISHED,
        limit,
        COMMIT_POLL,
    )


def _settle(
    services: Services, collection_id: str, pending: PendingCommit, outcome: dict[str, Any]
) -> PushResult:
    """Apply the final state of the pending commit to the stage, or raise why it did not
    succeed.
    """
    body = pending.body
    if outcome["state"] == "succeeded":
        version = int(outcome["version"])
        _apply(services, collection_id, body, version)
        return PushResult(body["base_version"], version, len(body["adds"]), len(body["removes"]))
    if outcome["state"] in _REFUSED:
        _clear_pending(services, collection_id)
    raise _unfinished(outcome, saved=True)


def _apply(services: Services, collection_id: str, body: dict[str, Any], version: int) -> None:
    """In one write: remove the committed changes from the stage, set the base to ``version``
    and clear the pending commit. Changes staged before the commit was saved but not in it stay
    staged.
    """
    uploads = {add["upload_id"] for add in body["adds"]}
    removes = set(body["removes"])
    with services.state.changing(collection_id) as stage:
        stage.adds = [add for add in stage.adds if add.upload_id not in uploads]
        stage.removes = [path for path in stage.removes if path not in removes]
        stage.base_version = version
        stage.pending_commit = None


def _clear_pending(services: Services, collection_id: str) -> None:
    with services.state.changing(collection_id) as stage:
        stage.pending_commit = None


def _rm_one(
    stage: WorkingState, recorded: dict[str, dict[str, Any]], rel_path: str
) -> list[tuple[RmAction, str]]:
    """Apply ``huron rm`` to one path of ``stage`` in place; what it did.

    An add and a removal of one path are never staged together (staging an add drops the
    removal), so at most one kind is unstaged.
    """
    key = rel_path_key(rel_path)
    adds, stage.adds = _split(stage.adds, lambda add: rel_path_key(add.rel_path) == key)
    removes, stage.removes = _split(stage.removes, lambda path: rel_path_key(path) == key)
    if not adds and not removes:
        return [_stage_removal(stage, recorded, rel_path)]
    unstaged = [(RmAction.UNSTAGED_ADD, add.rel_path) for add in adds]
    return unstaged + [(RmAction.UNSTAGED_REMOVE, path) for path in removes]


def _split[T](items: list[T], matches: Callable[[T], bool]) -> tuple[list[T], list[T]]:
    """``items`` that match, and the rest, each in order."""
    return [item for item in items if matches(item)], [item for item in items if not matches(item)]


def _stage_removal(
    stage: WorkingState, recorded: dict[str, dict[str, Any]], rel_path: str
) -> tuple[RmAction, str]:
    """Stage the removal of the recorded file at ``rel_path``, spelled as it was recorded."""
    found = recorded.get(rel_path_key(rel_path))
    if found is None:
        raise UsageError(f"{rel_path} is neither recorded nor staged")
    stage.removes.append(found["rel_path"])
    return RmAction.STAGED_REMOVE, found["rel_path"]


def _uploader(services: Services, api: ApiClient) -> Uploader:
    """The tus client for the service's upload endpoint; refuses when there is none."""
    service = UploadService.from_health(api.get("/healthz", auth=False))
    return Uploader(
        services.http,
        api,
        services.session().token,
        service,
        deadline=services.deadline,
        report=lambda line: services.err.print(line, markup=False),
    )


def _upload_files(services: Services, stage: WorkingState, uploader: Uploader) -> None:
    for add in stage.adds:

        def save(sent: StagedAdd = add) -> None:
            _save_attempt(services, stage.collection_id, sent)

        uploader.upload(stage.collection_id, add, save)


def _save_attempt(services: Services, collection_id: str, sent: StagedAdd) -> None:
    """Record the upload of ``sent`` in the stage entry of the same file, if it is still staged."""
    with services.state.changing(collection_id) as stage:
        for add in stage.adds:
            if add.same_file(sent):
                add.attempt_id, add.upload_id = sent.attempt_id, sent.upload_id
                add.attempt_state = sent.attempt_state


def _body(
    services: Services, stage: WorkingState, message: str | None, *, sealed_only: bool = True
) -> dict[str, Any]:
    """The commit body of ``stage`` without its request ID.

    Each add has the size and the sha256 that ``huron add`` recorded, and the ID of its upload
    once the service sealed it. With ``sealed_only`` the body has only the adds of sealed
    uploads. Without it, the body is for a dry run, which accepts an add without an upload.
    """
    adds: list[dict[str, Any]] = []
    for add in stage.adds:
        entry: dict[str, Any] = {"rel_path": add.rel_path, "size": add.size, "sha256": add.sha256}
        sealed = add.attempt_state == "ready" and add.upload_id is not None
        if sealed:
            entry["upload_id"] = add.upload_id
        if sealed or not sealed_only:
            adds.append(entry)
    body: dict[str, Any] = {
        "base_version": stage.base_version,
        "adds": adds,
        "removes": list(stage.removes),
        "host": services.hostname,
    }
    if message:
        body["message"] = message
    return body


def _unfinished(outcome: dict[str, Any], *, saved: bool) -> CliError:
    """The error for a commit request that did not succeed.

    ``saved`` when the request stays the pending commit of the working copy. The hint for a
    request that is still accepted or blocked then tells the user to run ``huron push``.
    """
    refusal = outcome.get("refusal")
    if outcome["state"] == "rejected" and refusal is not None:
        return ApiError.from_problem(0, refusal)
    if outcome["state"] == "blocked":
        resolve = "a platform administrator must resolve the commit request"
        return CliError(
            "the service accepted the commit, but a step of it is blocked",
            ExitCode.CONFLICT,
            hint=f"{resolve}. To get the result, run `huron push`" if saved else resolve,
            code="PUBLICATION_BLOCKED",
        )
    if outcome["state"] == "abandoned":
        return CliError(
            "a platform administrator abandoned the commit",
            ExitCode.CONFLICT,
            hint="run `huron push` again",
        )
    return CliError(
        f"the service accepted the commit, but did not finish it in {int(COMMIT_WAIT)} seconds",
        ExitCode.FAILED,
        hint=(
            "to get the result, run `huron push`"
            if saved
            else "to see the result later, run `huron get files`"
        ),
    )
