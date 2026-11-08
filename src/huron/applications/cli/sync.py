"""Working copies: checkout, staging, pull and push of one collection."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

from huron.applications.cli.client import ApiClient
from huron.applications.cli.errors import CliError, ExitCode, UsageError
from huron.applications.cli.mount import Mount
from huron.applications.cli.services import Services
from huron.applications.cli.state import Stage, StagedAdd, WorkingCopy
from huron.applications.cli.uploads import Uploader, UploadService
from huron.schema.naming import RelPathError, check_rel_path, rel_path_key

__all__ = [
    "PushResult",
    "RmAction",
    "checkout",
    "current",
    "pull",
    "push",
    "recorded_files",
    "stage_paths",
    "unstage_or_remove",
    "write_sidecar",
]


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


def checkout(services: Services, collection: dict[str, Any]) -> WorkingCopy:
    """Record a working copy of ``collection`` and make it current; its stage is kept."""
    copy = WorkingCopy(
        collection_id=str(collection["id"]),
        identifier=str(collection["identifier"]),
        version=int(collection["version"]),
        path=collection.get("path"),
    )
    services.state.write_copy(copy)
    services.save_config(replace(services.config, current_collection=copy.collection_id))
    return copy


def current(services: Services) -> WorkingCopy:
    """The checked-out working copy."""
    collection_id = services.config.current_collection
    copy = None if collection_id is None else services.state.read_copy(collection_id)
    if copy is None:
        raise UsageError(
            "there is no current collection",
            hint="run `huron checkout <identifier>`, or run `huron checkout` to choose one",
        )
    return copy


def recorded_files(api: ApiClient, collection_id: str) -> dict[str, dict[str, Any]]:
    """Recorded files by case-folded path."""
    return {
        rel_path_key(item["rel_path"]): item
        for item in api.pages(f"/api/v1/collections/{collection_id}/files")
    }


def stage_paths(
    services: Services, copy: WorkingCopy, paths: list[Path], rename: str | None, recursive: bool
) -> list[StagedAdd]:
    """Stage local files (and, with ``recursive``, directories) for the next push."""
    if rename is not None and len(paths) != 1:
        raise UsageError("`--as` needs exactly one file")
    staged: list[StagedAdd] = []
    for path in paths:
        staged.extend(_collect(path, rename, recursive))
    stage = services.state.read_stage(copy.collection_id)
    keys = {rel_path_key(add.rel_path) for add in staged}
    stage.adds = [add for add in stage.adds if rel_path_key(add.rel_path) not in keys] + staged
    stage.removes = [path for path in stage.removes if rel_path_key(path) not in keys]
    services.state.write_stage(copy.collection_id, stage)
    return staged


def unstage_or_remove(
    services: Services, copy: WorkingCopy, rel_paths: list[str]
) -> list[tuple[RmAction, str]]:
    """Drop a staged add or removal, or stage the removal of a recorded file, for each path.

    Returns what was done to each path, in order; a path already staged for removal is unstaged,
    so ``huron rm`` undoes itself. Nothing is written when a path is neither recorded nor staged.
    """
    stage = services.state.read_stage(copy.collection_id)
    recorded = recorded_files(services.api(), copy.collection_id)
    done = [item for rel_path in rel_paths for item in _rm_one(stage, recorded, rel_path)]
    services.state.write_stage(copy.collection_id, stage)
    return done


def pull(services: Services, copy: WorkingCopy) -> tuple[WorkingCopy, list[str]]:
    """Catch the working copy up with the service; drops staged removes no longer recorded."""
    api = services.api()
    collection = api.get(f"/api/v1/collections/{copy.collection_id}")
    stage = services.state.read_stage(copy.collection_id)
    recorded = recorded_files(api, copy.collection_id)
    dropped = [path for path in stage.removes if rel_path_key(path) not in recorded]
    stage.removes = [path for path in stage.removes if rel_path_key(path) in recorded]
    services.state.write_stage(copy.collection_id, stage)
    return checkout(services, collection), dropped


def push(services: Services, copy: WorkingCopy, message: str | None) -> PushResult:
    """Upload the staged files through tusd and commit them with the version they were based on.

    The service checks the commit with a dry run first, so a push it would refuse (no right to
    write files, a stale base version, a removed file that is not recorded) fails before any byte
    is uploaded. The stage records each upload, so a push that stops continues on the next push.
    """
    with services.state.locked(copy.collection_id):
        stage = services.state.read_stage(copy.collection_id)
        api = services.api()
        collection = api.get(f"/api/v1/collections/{copy.collection_id}")
        if int(collection["version"]) != copy.version:
            raise CliError(
                f"{copy.identifier} is at version {collection['version']},"
                f" but your working copy is at version {copy.version}",
                ExitCode.CONFLICT,
                hint="run `huron pull`",
                code="BASE_VERSION_CONFLICT",
            )
        if collection.get("path") is None:
            raise CliError(
                f"{copy.identifier} is a draft",
                ExitCode.CONFLICT,
                hint="run `huron activate collection`",
            )
        uploader = _uploader(services, api) if stage.adds else None
        _preflight(services, api, copy, stage, message)
        if uploader is not None:
            _upload_files(services, copy, stage, uploader)
        result = _commit(services, api, copy, stage, message)
        services.state.write_stage(copy.collection_id, Stage())
        services.state.write_copy(replace(copy, version=int(result["version"])))
        return PushResult(copy.version, int(result["version"]), len(stage.adds), len(stage.removes))


def write_sidecar(services: Services, mount: Mount, collection: dict[str, Any]) -> None:
    """Write the service's ``metadata.json`` rendering into the collection directory."""
    target = mount.path(str(collection["path"])) / "metadata.json"
    body = services.api().request("GET", f"/api/v1/collections/{collection['id']}/metadata.json")
    mount.storage.write_bytes(target, body.content)


def _rm_one(
    stage: Stage, recorded: dict[str, dict[str, Any]], rel_path: str
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
    stage: Stage, recorded: dict[str, dict[str, Any]], rel_path: str
) -> tuple[RmAction, str]:
    """Stage the removal of the recorded file at ``rel_path``, spelled as it was recorded."""
    found = recorded.get(rel_path_key(rel_path))
    if found is None:
        raise UsageError(f"{rel_path} is neither recorded nor staged")
    stage.removes.append(found["rel_path"])
    return RmAction.STAGED_REMOVE, found["rel_path"]


def _collect(path: Path, rename: str | None, recursive: bool) -> list[StagedAdd]:
    if path.is_symlink():
        raise UsageError(f"{path} is a symbolic link. Stage the file that it points to")
    if path.is_dir():
        if not recursive:
            raise UsageError(f"{path} is a directory", hint="use `--recursive`")
        found: list[StagedAdd] = []
        for root, _, names in os.walk(path):
            for name in sorted(names):
                file = Path(root) / name
                if not file.is_symlink():
                    found.append(_staged(file, file.relative_to(path).as_posix()))
        return found
    if not path.is_file():
        raise UsageError(f"{path} does not exist")
    return [_staged(path, rename or path.name)]


def _staged(path: Path, rel_path: str) -> StagedAdd:
    try:
        check_rel_path(rel_path)
    except RelPathError as error:
        raise UsageError(
            f"{rel_path!r} is not a valid path in a collection ({error.rule})"
        ) from error
    return StagedAdd(rel_path, str(path.resolve()), path.stat().st_size)


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


def _upload_files(services: Services, copy: WorkingCopy, stage: Stage, uploader: Uploader) -> None:
    def save() -> None:
        services.state.write_stage(copy.collection_id, stage)

    for add in stage.adds:
        uploader.upload(copy.collection_id, add, save)
        save()


def _preflight(
    services: Services, api: ApiClient, copy: WorkingCopy, stage: Stage, message: str | None
) -> None:
    api.post(
        f"/api/v1/collections/{copy.collection_id}/commits",
        params={"dry_run": "true"},
        json=_commit_body(services, copy, stage, message),
    )


def _commit(
    services: Services, api: ApiClient, copy: WorkingCopy, stage: Stage, message: str | None
) -> dict[str, Any]:
    body = _commit_body(services, copy, stage, message)
    try:
        result: dict[str, Any] = api.post(
            f"/api/v1/collections/{copy.collection_id}/commits", json=body
        )
    except CliError as error:
        if error.code is not None:
            raise
        result = _recover(api, copy, stage, error)
    return result


def _commit_body(
    services: Services, copy: WorkingCopy, stage: Stage, message: str | None
) -> dict[str, Any]:
    """The commit body.

    Each add's ``sha256`` is the ``Huron-Sha256`` receipt of its upload. An add not yet uploaded
    has none, which a dry run accepts.
    """
    adds: list[dict[str, Any]] = []
    for add in stage.adds:
        entry: dict[str, Any] = {"rel_path": add.rel_path, "size": add.size}
        if add.sha256 is not None:
            entry["sha256"] = add.sha256
        adds.append(entry)
    body: dict[str, Any] = {
        "base_version": copy.version,
        "adds": adds,
        "removes": list(stage.removes),
        "host": services.hostname,
    }
    if message:
        body["message"] = message
    return body


def _recover(api: ApiClient, copy: WorkingCopy, stage: Stage, error: CliError) -> dict[str, Any]:
    collection = api.get(f"/api/v1/collections/{copy.collection_id}")
    if int(collection["version"]) <= copy.version:
        raise error
    recorded = recorded_files(api, copy.collection_id)
    for add in stage.adds:
        found = recorded.get(rel_path_key(add.rel_path))
        if found is None or found["sha256"] != add.sha256:
            raise error
    return {"version": collection["version"], "file_count": collection["file_count"]}
