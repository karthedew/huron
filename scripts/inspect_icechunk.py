"""Read bounded Icechunk/Zarr metadata from an independently validated local repository.

The fixed helper accepts JSON on stdin and emits one sanitized JSON document. It opens a
read-only pinned session, never reads array chunks, and never modifies repository state.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import math
import os
import re
import sys
from datetime import UTC
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import icechunk
import zarr

REFERENCE_LIMIT = 100
HISTORY_LIMIT = 100
SCHEMA_LIMIT = 200
ATTRIBUTE_LIMIT = 1000
STRING_LIMIT = 8192
FILESYSTEM_LIMIT = 100_000
METADATA_BYTE_LIMIT = 750_000
SECRET_KEY = re.compile(
    r"password|secret|token|credential|private.?key|access.?key|api.?key|signature|authorization|^sig$",
    re.I,
)


class InspectionError(Exception):
    """An inspection failed without exposing storage or runtime exception details."""


def validate_repository(path: str, roots: list[str]) -> Path:
    """Reject paths outside approved roots and any repository symlink before SDK access.

    Args:
        path: Absolute repository path approved by the server.
        roots: Absolute deployment-owned storage roots.

    Returns:
        Validated canonical repository path.

    Raises:
        InspectionError: The location is missing, unsafe, or contains excessive entries.
    """
    requested = Path(path)
    if not requested.is_absolute():
        raise InspectionError("unsafe-location")
    try:
        resolved = requested.resolve(strict=True)
        approved = [Path(root).resolve(strict=True) for root in roots if Path(root).exists()]
    except (OSError, RuntimeError) as error:
        raise InspectionError("unsafe-location") from error
    if requested != resolved or not resolved.is_dir():
        raise InspectionError("unsafe-location")
    matched = next((root for root in approved if resolved.is_relative_to(root)), None)
    if matched is None:
        raise InspectionError("unsafe-location")
    current = matched
    for part in resolved.relative_to(matched).parts:
        current /= part
        if current.is_symlink():
            raise InspectionError("unsafe-location")
    count = 0
    pending = [resolved]
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                count += 1
                if count > FILESYSTEM_LIMIT or entry.is_symlink():
                    raise InspectionError("unsafe-location")
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
    if requested.resolve(strict=True) != resolved:
        raise InspectionError("unsafe-location")
    return resolved


class MetadataProjection:
    """Bound and redact untrusted repository attributes before returning them to the browser."""

    def __init__(self):
        """Initialize visible projection-limit and redaction evidence."""
        self.truncated = False
        self.redacted = False
        self.remaining_bytes = METADATA_BYTE_LIMIT

    def _string(self, value: str) -> str:
        limit = min(STRING_LIMIT, max(0, self.remaining_bytes // 6))
        if len(value) > limit:
            self.truncated = True
            value = value[:limit] + "[truncated]"
        self.remaining_bytes -= len(json.dumps(value, ensure_ascii=True))
        return value

    def value(self, value: object, depth: int = 0) -> object:
        """Project a JSON metadata value while bounding nested collections and strings.

        Args:
            value: SDK metadata or scientific attribute value.
            depth: Current nesting depth.

        Returns:
            A bounded browser-safe JSON value.
        """
        if depth > 12 or self.remaining_bytes <= 0:
            self.truncated = True
            return "[metadata depth limit]"
        if isinstance(value, dict):
            result = {}
            for index, (key, entry) in enumerate(value.items()):
                if index >= ATTRIBUTE_LIMIT:
                    self.truncated = True
                    break
                name = str(key)
                sensitive = SECRET_KEY.search(name)
                name = self._string(name)
                if self.remaining_bytes <= 0:
                    self.truncated = True
                    break
                if sensitive:
                    self.redacted = True
                    result[name] = "[redacted]"
                else:
                    result[name[:STRING_LIMIT]] = self.value(entry, depth + 1)
            return result
        if isinstance(value, (list, tuple)):
            if len(value) > ATTRIBUTE_LIMIT:
                self.truncated = True
            return [self.value(entry, depth + 1) for entry in value[:ATTRIBUTE_LIMIT]]
        if isinstance(value, str):
            if re.match(r"^(?:https?|s3|gs|file)://", value):
                try:
                    url = urlsplit(value)
                    query = []
                    for key, entry in parse_qsl(url.query, keep_blank_values=True):
                        if SECRET_KEY.search(key):
                            self.redacted = True
                            entry = "[redacted]"
                        query.append((key, entry))
                    host = url.netloc.rsplit("@", 1)[-1]
                    if host != url.netloc:
                        self.redacted = True
                    fragment = url.fragment
                    if SECRET_KEY.search(fragment):
                        self.redacted = True
                        fragment = "[redacted]"
                    return self._string(
                        urlunsplit((url.scheme, host, url.path, urlencode(query), fragment))
                    )
                except ValueError:
                    self.redacted = True
                    return "[invalid URL]"
            return self._string(value)
        if value is None or isinstance(value, (bool, int)):
            return value
        if isinstance(value, float):
            if math.isfinite(value):
                return value
            return "NaN" if math.isnan(value) else "Infinity" if value > 0 else "-Infinity"
        return self.value(str(value), depth + 1)


def _snapshot(snapshot, projection: MetadataProjection) -> dict:
    return {
        "id": snapshot.id,
        "parentId": snapshot.parent_id,
        "writtenAt": snapshot.written_at.astimezone(UTC).isoformat(),
        "message": projection.value(snapshot.message),
        "metadata": projection.value(snapshot.metadata),
    }


async def _schema(store: icechunk.IcechunkStore, projection: MetadataProjection) -> tuple:
    try:
        root = await zarr.api.asynchronous.open_group(store=store, mode="r")
    except zarr.errors.GroupNotFoundError:
        return [], [], {}, False, "This snapshot contains no Zarr group metadata."
    arrays = []
    groups = []
    pending = [root]
    truncated = False
    while pending:
        group = pending.pop(0)
        if len(groups) + len(arrays) >= SCHEMA_LIMIT:
            truncated = True
            break
        groups.append({"path": group.path or "/", "attributes": projection.value(group.attrs)})
        iterator = group.members(max_depth=0)
        try:
            async for _, child in iterator:
                if len(groups) + len(arrays) + len(pending) >= SCHEMA_LIMIT:
                    truncated = True
                    break
                if isinstance(child, zarr.AsyncGroup):
                    pending.append(child)
                    continue
                attrs = child.attrs
                dimensions = getattr(child.metadata, "dimension_names", None) or attrs.get(
                    "_ARRAY_DIMENSIONS"
                )
                if not isinstance(dimensions, (list, tuple)) or len(dimensions) != len(child.shape):
                    dimensions = [None] * len(child.shape)
                arrays.append(
                    {
                        "path": child.path,
                        "dtype": str(child.dtype),
                        "shape": list(child.shape),
                        "chunks": list(child.chunks),
                        "dimensions": [
                            str(value) if value is not None else None for value in dimensions
                        ],
                        "attributes": projection.value(attrs),
                    }
                )
        finally:
            await iterator.aclose()
    return (
        sorted(groups, key=lambda value: value["path"]),
        sorted(arrays, key=lambda value: value["path"]),
        root.attrs,
        truncated,
        None,
    )


def inspect_repository(
    path: str, roots: list[str], branch: str = "", snapshot_id: str = ""
) -> dict:
    """Inspect actual branch references, pinned snapshots and group/array metadata.

    Args:
        path: Absolute local repository location.
        roots: Approved deployment-owned repository roots.
        branch: Selected real branch, or the default main/first branch.
        snapshot_id: Optional existing immutable snapshot selection.

    Returns:
        Browser-safe repository schema, history and recorded import provenance.

    Raises:
        InspectionError: A location or selected reference is invalid or unavailable.
    """
    location = validate_repository(path, roots)
    storage = icechunk.local_filesystem_storage(str(location))
    if not icechunk.Repository.exists(storage):
        raise InspectionError("not-initialized")
    repo = icechunk.Repository.open(storage)
    projection = MetadataProjection()
    branch_names = sorted(repo.list_branches())
    tag_names = sorted(repo.list_tags())
    if branch and branch not in branch_names:
        raise InspectionError("reference-not-found")
    selected = branch or (
        "main" if "main" in branch_names else branch_names[0] if branch_names else None
    )
    visible_branches = branch_names[:REFERENCE_LIMIT]
    if selected and selected not in visible_branches:
        visible_branches[-1] = selected
        visible_branches.sort()
    branches = [{"name": name, "snapshotId": repo.lookup_branch(name)} for name in visible_branches]
    tags = [
        {"name": name, "snapshotId": repo.lookup_tag(name)} for name in tag_names[:REFERENCE_LIMIT]
    ]
    if snapshot_id and not re.fullmatch(r"[A-Z0-9]{20}", snapshot_id):
        raise InspectionError("reference-not-found")
    if not snapshot_id:
        if selected is None:
            raise InspectionError("reference-not-found")
        snapshot_id = next(entry["snapshotId"] for entry in branches if entry["name"] == selected)
    try:
        history = list(itertools.islice(repo.ancestry(snapshot_id=snapshot_id), HISTORY_LIMIT + 1))
        session = repo.readonly_session(snapshot_id=snapshot_id)
    except Exception as error:
        raise InspectionError("reference-not-found") from error
    references_truncated = len(branch_names) > REFERENCE_LIMIT or len(tag_names) > REFERENCE_LIMIT
    groups, arrays, root_attrs, schema_truncated, message = asyncio.run(
        _schema(session.store, projection)
    )
    receipt = root_attrs.get("import_receipt")
    source = {
        key: value
        for key, value in root_attrs.items()
        if key.startswith("source_") or key in {"doi", "acknowledgement", "conversion"}
    }
    visible_history = [_snapshot(entry, projection) for entry in history[:HISTORY_LIMIT]]
    return {
        "state": "available",
        "message": message,
        "storage": "FILE",
        "selectedBranch": selected,
        "branches": branches,
        "tags": tags,
        "snapshot": visible_history[0] if visible_history else None,
        "groups": groups,
        "arrays": arrays,
        "history": visible_history,
        "historyNextSnapshotId": history[HISTORY_LIMIT].id
        if len(history) > HISTORY_LIMIT
        else None,
        "provenance": {
            "importReceipt": projection.value(receipt) if isinstance(receipt, dict) else None,
            "source": projection.value(source),
        },
        "lineage": {
            "state": "unavailable",
            "message": (
                "Icechunk snapshot ancestry and recorded source provenance are available. "
                "Scientific derivation lineage is not implemented."
            ),
        },
        "truncated": references_truncated
        or schema_truncated
        or len(history) > HISTORY_LIMIT
        or projection.truncated,
        "redacted": projection.redacted,
        "limits": {"references": REFERENCE_LIMIT, "history": HISTORY_LIMIT, "schema": SCHEMA_LIMIT},
    }


def _request() -> dict:
    payload = sys.stdin.buffer.read(64 * 1024 + 1)
    if len(payload) > 64 * 1024:
        raise InspectionError("invalid-input")
    request = json.loads(payload)
    if not isinstance(request, dict):
        raise InspectionError("invalid-input")
    return request


def main() -> None:
    """Run one fixed metadata inspection without disclosing runtime exceptions."""
    try:
        request = _request()
        result = inspect_repository(
            request["path"],
            request["roots"],
            request.get("branch", ""),
            request.get("snapshot", ""),
        )
    except InspectionError as error:
        result = {"error": str(error)}
    except Exception:
        result = {"error": "metadata-unavailable"}
    print(json.dumps(result, allow_nan=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
