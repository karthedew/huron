"""Working copies: checkout, staging, pull and push of one collection."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

import httpx

from huron.applications.cli.client import ApiClient
from huron.applications.cli.errors import ApiError, CliError, ExitCode, UsageError
from huron.applications.cli.localstate import StagedAdd, WorkingState
from huron.applications.cli.services import Services
from huron.applications.cli.sources import SkippedEntry, collect_sources
from huron.applications.cli.uploads import Uploader, UploadService
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
    "send_commit",
    "stage_paths",
    "unstage_or_remove",
]


#: The seconds between two reads of a commit request that the service did not finish yet.
COMMIT_POLL = 5.0
#: The most seconds the CLI waits for a commit request that the service accepted.
COMMIT_WAIT = 600.0


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
    """Record a working copy of ``collection`` and make it current; its stage is kept."""
    with services.state.locked():
        working = services.state.check_out(
            str(collection["id"]),
            str(collection["identifier"]),
            int(collection["version"]),
            collection.get("path"),
        )
        services.save_config(replace(services.config, current_collection=working.collection_id))
    return working


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
    api: ApiClient, collection_id: str, body: dict[str, Any], sleep: Callable[[float], None]
) -> dict[str, Any]:
    """Send the commit ``body``, and wait for the request when the service answers 202.

    The wait reads the state of the request every :data:`COMMIT_POLL` seconds, for at most
    :data:`COMMIT_WAIT` seconds. Returns the request when it succeeded. A request that the
    service refused raises the refusal, and a blocked, abandoned or still accepted request
    raises an error that says so.
    """
    response = api.request("POST", f"/api/v1/collections/{collection_id}/commits", json=body)
    return _settled(api, response, sleep)


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
    removal. Returns the adds and the entries of the directories that the walk skipped; see
    :func:`~huron.applications.cli.sources.collect_sources`.
    """
    staged, skipped = collect_sources(paths, rename, recursive)
    keys = {rel_path_key(add.rel_path) for add in staged}
    with services.state.changing(working.collection_id) as stage:
        stage.adds = [add for add in stage.adds if rel_path_key(add.rel_path) not in keys] + staged
        stage.removes = [path for path in stage.removes if rel_path_key(path) not in keys]
    return staged, skipped


def unstage_or_remove(
    services: Services, working: WorkingState, rel_paths: list[str]
) -> list[tuple[RmAction, str]]:
    """Drop a staged add or removal, or stage the removal of a recorded file, for each path.

    Returns what was done to each path, in order; a path already staged for removal is unstaged,
    so ``huron rm`` undoes itself. Nothing is written when a path is neither recorded nor staged.
    """
    recorded = recorded_files(services.api(), working.collection_id)
    with services.state.changing(working.collection_id) as stage:
        return [item for rel_path in rel_paths for item in _rm_one(stage, recorded, rel_path)]


def pull(services: Services, working: WorkingState) -> tuple[WorkingState, list[str]]:
    """Catch the working copy up with the service; drops staged removes no longer recorded."""
    api = services.api()
    collection = api.get(f"/api/v1/collections/{working.collection_id}")
    recorded = recorded_files(api, working.collection_id)
    with services.state.locked():
        with services.state.changing(working.collection_id) as stage:
            dropped = [path for path in stage.removes if rel_path_key(path) not in recorded]
            stage.removes = [path for path in stage.removes if rel_path_key(path) in recorded]
        return checkout(services, collection), dropped


def push(services: Services, working: WorkingState, message: str | None) -> PushResult:
    """Upload the staged files through tusd and commit them with the version they were based on.

    The push holds the push lock of the working copy from start to end. The service checks the
    commit with a dry run first, so a push it would refuse (no right to write files, a pending
    commit, a stale base version, a removed file that is not recorded) fails before any byte is
    uploaded. Before it sends a file, the push checks that the size and the modification time
    are those that ``huron add`` recorded, and a change stops the push. The stage records each
    upload attempt, so a push that stops continues on the next push. The commit names each
    upload by its ID and the recorded sha256, under a new request ID. A file staged while the
    push runs stays staged for the next push.
    """
    with services.state.push_lock(working.collection_id):
        stage = current(services)
        api = services.api()
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
        _preflight(services, api, stage, message)
        if uploader is not None:
            _upload_files(services, stage, uploader)
        result = _commit(services, api, stage, message)
        _finish(services, stage, int(result["version"]))
        return PushResult(
            stage.base_version, int(result["version"]), len(stage.adds), len(stage.removes)
        )


def _finish(services: Services, pushed: WorkingState, version: int) -> None:
    """Remove the pushed changes from the stage and move its base to ``version``.

    Changes staged while the push ran stay staged.
    """
    with services.state.changing(pushed.collection_id) as stage:
        stage.adds = [
            add for add in stage.adds if not any(add.same_file(sent) for sent in pushed.adds)
        ]
        stage.removes = [path for path in stage.removes if path not in pushed.removes]
        stage.base_version = version


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
        sleep=services.sleep,
        report=lambda line: services.err.print(line, markup=False),
    )


def _upload_files(services: Services, stage: WorkingState, uploader: Uploader) -> None:
    for add in stage.adds:

        def save(sent: StagedAdd = add) -> None:
            _save_attempt(services, stage.collection_id, sent)

        uploader.upload(stage.collection_id, add, save)
        save()


def _save_attempt(services: Services, collection_id: str, sent: StagedAdd) -> None:
    """Record the upload of ``sent`` in the stage entry of the same file, if it is still staged."""
    with services.state.changing(collection_id) as stage:
        for add in stage.adds:
            if add.same_file(sent):
                add.attempt_id, add.upload_id = sent.attempt_id, sent.upload_id
                add.attempt_state = sent.attempt_state


def _preflight(
    services: Services, api: ApiClient, stage: WorkingState, message: str | None
) -> None:
    api.post(
        f"/api/v1/collections/{stage.collection_id}/commits",
        params={"dry_run": "true"},
        json=_commit_body(services, stage, message),
    )


def _commit(
    services: Services, api: ApiClient, stage: WorkingState, message: str | None
) -> dict[str, Any]:
    body = _commit_body(services, stage, message)
    body["request_id"] = str(uuid.uuid4())
    path = f"/api/v1/collections/{stage.collection_id}/commits"
    try:
        response = api.request("POST", path, json=body)
    except CliError as error:
        if error.code is not None:
            raise
        return _recover(api, stage, error)
    return _settled(api, response, services.sleep)


def _commit_body(services: Services, stage: WorkingState, message: str | None) -> dict[str, Any]:
    """The commit body without its request ID.

    Each add has the size and the sha256 that ``huron add`` recorded, and the ID of its upload
    once the service sealed it. A dry run accepts an add without an upload.
    """
    adds: list[dict[str, Any]] = []
    for add in stage.adds:
        entry: dict[str, Any] = {"rel_path": add.rel_path, "size": add.size, "sha256": add.sha256}
        if add.attempt_state == "ready" and add.upload_id is not None:
            entry["upload_id"] = add.upload_id
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


def _settled(
    api: ApiClient, response: httpx.Response, sleep: Callable[[float], None]
) -> dict[str, Any]:
    """The succeeded request of the commit answer ``response``; see :func:`send_commit`."""
    outcome: dict[str, Any] = response.json()
    location = response.headers.get("Location")
    waited = 0.0
    while response.status_code == 202 and outcome["state"] == "accepted" and waited < COMMIT_WAIT:
        sleep(COMMIT_POLL)
        waited += COMMIT_POLL
        outcome = api.get(str(location))
    if outcome["state"] != "succeeded":
        raise _unfinished(outcome)
    return outcome


def _unfinished(outcome: dict[str, Any]) -> CliError:
    """The error for a commit request that did not succeed."""
    refusal = outcome.get("refusal")
    if outcome["state"] == "rejected" and refusal is not None:
        return ApiError.from_problem(0, refusal)
    if outcome["state"] == "blocked":
        return CliError(
            "the service accepted the commit, but a step of it is blocked",
            ExitCode.CONFLICT,
            hint="a platform administrator must resolve the commit request",
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
        hint="to see the result later, run `huron get files`",
    )


def _recover(api: ApiClient, stage: WorkingState, error: CliError) -> dict[str, Any]:
    collection = api.get(f"/api/v1/collections/{stage.collection_id}")
    if int(collection["version"]) <= stage.base_version:
        raise error
    recorded = recorded_files(api, stage.collection_id)
    for add in stage.adds:
        found = recorded.get(rel_path_key(add.rel_path))
        if found is None or found["sha256"] != add.sha256:
            raise error
    return {"version": collection["version"], "file_count": collection["file_count"]}
