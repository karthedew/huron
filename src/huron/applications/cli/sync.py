"""Working copies: checkout, staging, pull and push of one collection."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from huron.applications.cli.client import ApiClient
from huron.applications.cli.errors import CliError, ExitCode, UsageError
from huron.applications.cli.mount import Mount
from huron.applications.cli.services import Services
from huron.applications.cli.state import Stage, StagedAdd, WorkingCopy
from huron.core.storage import FileStamp, StorageError
from huron.schema.naming import RelPathError, check_rel_path, rel_path_key

__all__ = [
    "PushResult",
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
        raise UsageError("no collection is checked out", hint="run: huron checkout <identifier>")
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
        raise UsageError("--as takes exactly one file")
    staged: list[StagedAdd] = []
    for path in paths:
        staged.extend(_collect(path, rename, recursive))
    stage = services.state.read_stage(copy.collection_id)
    keys = {rel_path_key(add.rel_path) for add in staged}
    stage.adds = [add for add in stage.adds if rel_path_key(add.rel_path) not in keys] + staged
    stage.removes = [path for path in stage.removes if rel_path_key(path) not in keys]
    services.state.write_stage(copy.collection_id, stage)
    return staged


def unstage_or_remove(services: Services, copy: WorkingCopy, rel_paths: list[str]) -> list[str]:
    """Drop staged adds, or stage removals of recorded files; returns what was staged to remove."""
    stage = services.state.read_stage(copy.collection_id)
    recorded = recorded_files(services.api(), copy.collection_id)
    removed: list[str] = []
    for rel_path in rel_paths:
        key = rel_path_key(rel_path)
        before = len(stage.adds)
        stage.adds = [add for add in stage.adds if rel_path_key(add.rel_path) != key]
        if len(stage.adds) != before:
            continue
        if key not in recorded:
            raise UsageError(f"{rel_path} is neither recorded nor staged")
        if recorded[key]["rel_path"] not in stage.removes:
            stage.removes.append(recorded[key]["rel_path"])
            removed.append(recorded[key]["rel_path"])
    services.state.write_stage(copy.collection_id, stage)
    return removed


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
    """Copy staged files onto the share and commit them with the version they were based on."""
    with services.state.locked(copy.collection_id):
        stage = services.state.read_stage(copy.collection_id)
        api = services.api()
        collection = api.get(f"/api/v1/collections/{copy.collection_id}")
        if int(collection["version"]) != copy.version:
            raise CliError(
                f"{copy.identifier} is at version {collection['version']}, your copy at"
                f" {copy.version}",
                ExitCode.CONFLICT,
                hint="run: huron pull",
                code="BASE_VERSION_CONFLICT",
            )
        if collection.get("path") is None:
            raise CliError(
                f"{copy.identifier} is a draft",
                ExitCode.CONFLICT,
                hint="run: huron collection activate",
            )
        mount = Mount(services)
        storage = mount.require()
        directory = mount.path(str(collection["path"]))
        _copy_files(services, copy, stage, storage, directory)
        result = _commit(services, api, copy, stage, message)
        for rel_path in stage.removes:
            try:
                storage.remove_file(directory.joinpath(*rel_path.split("/")))
            except StorageError as error:
                services.err.print(f"warning: {error.message}", markup=False)
        services.state.write_stage(copy.collection_id, Stage())
        services.state.write_copy(replace(copy, version=int(result["version"])))
        return PushResult(copy.version, int(result["version"]), len(stage.adds), len(stage.removes))


def write_sidecar(services: Services, mount: Mount, collection: dict[str, Any]) -> None:
    """Write the service's ``metadata.json`` rendering into the collection directory."""
    storage = mount.require()
    body = services.api().request("GET", f"/api/v1/collections/{collection['id']}/metadata.json")
    target = mount.path(str(collection["path"])) / "metadata.json"
    storage.write_bytes(target, body.content)


def _collect(path: Path, rename: str | None, recursive: bool) -> list[StagedAdd]:
    if path.is_symlink():
        raise UsageError(f"{path} is a symbolic link; stage the file it points to")
    if path.is_dir():
        if not recursive:
            raise UsageError(f"{path} is a directory", hint="use --recursive")
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
        raise UsageError(f"{rel_path!r} cannot be stored ({error.rule})") from error
    return StagedAdd(rel_path, str(path.resolve()), path.stat().st_size)


def _copy_files(
    services: Services, copy: WorkingCopy, stage: Stage, storage: Any, directory: Path
) -> None:
    for add in stage.adds:
        expected = None if add.sha256 is None else FileStamp(add.size, add.sha256)
        try:
            stamp = storage.copy_in(Path(add.source), directory, add.rel_path, expected)
        except StorageError as error:
            raise CliError(error.message, ExitCode.STORAGE, code=error.code) from error
        add.size, add.sha256 = stamp.size, stamp.sha256
        services.state.write_stage(copy.collection_id, stage)
        services.err.print(f"copied {add.rel_path} ({stamp.size} bytes)", markup=False)


def _commit(
    services: Services, api: ApiClient, copy: WorkingCopy, stage: Stage, message: str | None
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "base_version": copy.version,
        "adds": [{"rel_path": a.rel_path, "size": a.size, "sha256": a.sha256} for a in stage.adds],
        "removes": list(stage.removes),
        "host": services.hostname,
    }
    if message:
        body["message"] = message
    try:
        result: dict[str, Any] = api.post(
            f"/api/v1/collections/{copy.collection_id}/commits", json=body
        )
    except CliError as error:
        if error.code is not None:
            raise
        result = _recover(api, copy, stage, error)
    return result


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
