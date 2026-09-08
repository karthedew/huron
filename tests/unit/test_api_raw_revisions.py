"""Raw submissions publish complete, independent copies of their declared files."""

from __future__ import annotations

import hashlib
import io
import os
import stat
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

import pytest

from tests.ingest_client import IngestClient, manifest_file

if TYPE_CHECKING:
    from collections.abc import Iterable

    from fastapi.testclient import TestClient

    from huron.applications.api.runtime import ApiStores

pytestmark = pytest.mark.unit

_FILE_COUNT = 12
_CHANGED_INDEX = 6


def _payload_files(count: int) -> list[tuple[str, bytes]]:
    """Build ``count`` payload files with distinct, deterministic 32-byte content.

    Args:
        count: How many files to build.

    Returns:
        Each file's manifest path paired with its content, in file order.
    """
    return [
        (f"payload/f/{i:04d}.bin", hashlib.sha256(f"dedup-{i}".encode()).digest())
        for i in range(count)
    ]


def _with_changed_file(files: list[tuple[str, bytes]], index: int) -> list[tuple[str, bytes]]:
    """Replace one file's bytes with different deterministic content, leaving its path unchanged.

    Args:
        files: The manifest to derive a new one from.
        index: The position of the file whose bytes change.

    Returns:
        A new file list, identical to ``files`` except at ``index``.
    """
    changed_path = files[index][0]
    changed_data = hashlib.sha256(f"changed-{changed_path}".encode()).digest()
    return [
        (changed_path, changed_data) if position == index else pair
        for position, pair in enumerate(files)
    ]


def _create_and_commit_second_revision(
    client: TestClient, dataset_id: str, files: list[tuple[str, bytes]]
) -> tuple[dict[str, object], dict[str, object], int]:
    """Create, upload, verify and commit a second revision on an existing dataset.

    Args:
        client: The TestClient the session is driven through.
        dataset_id: The dataset already holding the parent revision.
        files: Each file's manifest path paired with its complete bytes.

    Returns:
        The create response's upload plan, the committed revision's view,
        and how many PUT requests the upload issued.
    """
    ingest = IngestClient(client)
    sources = dict(files)
    session = ingest.create(dataset_id, [manifest_file(path, data) for path, data in files])
    assert session.status_code == 201, session.text
    plan = session.json()
    ingest.upload(plan, lambda path: io.BytesIO(sources[path]))
    verified = ingest.verify(plan["id"])
    assert verified.status_code == 200, verified.text
    verified_body = verified.json()
    committed = ingest.commit(
        verified_body["id"],
        verified_body["etag"],
        {"title": "Revision 2", "creators": [ingest.subject]},
    )
    assert committed.status_code == 201, committed.text
    return plan, committed.json(), ingest.put_count


def _directories_under(root: Path) -> list[Path]:
    """List every directory below ``root``, excluding ``root`` itself.

    Args:
        root: The directory to walk.

    Returns:
        Every subdirectory found anywhere beneath ``root``.
    """
    return [Path(parent) / name for parent, names, _ in os.walk(root) for name in names]


def _make_writable_and_remove(root: Path, paths: Iterable[str]) -> None:
    """Make every directory below ``root`` writable, then unlink each payload file's own name.

    The bytes a removed name pointed at are untouched: a hard-linked child
    still holds its own name for the same inode.

    Args:
        root: The revision directory whose payload names are being removed.
        paths: Each file's manifest path, relative to ``root``.
    """
    for parent, _, _ in os.walk(root):
        os.chmod(parent, 0o755)
    for path in paths:
        (root / path).unlink()


def test_every_file_is_uploaded_and_stored_independently(
    client: TestClient, stores: ApiStores
) -> None:
    """A second revision uploads and owns every file, including unchanged bytes."""
    ingest = IngestClient(client)
    _, dataset_id = ingest.developer_dataset()
    first_files = _payload_files(_FILE_COUNT)
    first_view = ingest.upload_revision(dataset_id, first_files)
    second_files = _with_changed_file(first_files, _CHANGED_INDEX)
    changed_path = second_files[_CHANGED_INDEX][0]

    plan, second_view, put_count = _create_and_commit_second_revision(
        client, dataset_id, second_files
    )

    files_by_path = {item["path"]: item for item in plan["files"]}
    unchanged = [item for path, item in files_by_path.items() if path != changed_path]
    assert len(unchanged) == _FILE_COUNT - 1
    assert all(item["action"] == "upload" and item["part_count"] == 1 for item in unchanged)
    assert files_by_path[changed_path]["action"] == "upload"
    assert put_count == _FILE_COUNT

    parent_path = Path(stores.hierarchy._revisions[UUID(first_view["id"])].revision_path)
    child_path = Path(stores.hierarchy._revisions[UUID(second_view["id"])].revision_path)
    assert stat.S_IMODE(parent_path.stat().st_mode) == 0o555
    assert stat.S_IMODE(child_path.stat().st_mode) == 0o555
    for directory in _directories_under(child_path):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o555

    for path, data in second_files:
        target = child_path / path
        assert stat.S_IMODE(target.stat().st_mode) == 0o444
        if path == changed_path:
            assert target.stat().st_nlink == 1
            assert target.read_bytes() == data
        else:
            assert target.stat().st_nlink == 1
            assert not os.path.samefile(parent_path / path, target)
            assert target.read_bytes() == data


def test_a_revision_survives_removal_of_previous_revision_files(
    client: TestClient, stores: ApiStores
) -> None:
    """The child revision still reads back complete once the parent's own payload names are gone."""
    ingest = IngestClient(client)
    _, dataset_id = ingest.developer_dataset()
    first_files = _payload_files(_FILE_COUNT)
    first_view = ingest.upload_revision(dataset_id, first_files)
    second_files = _with_changed_file(first_files, _CHANGED_INDEX)
    changed_path = second_files[_CHANGED_INDEX][0]
    _, second_view, _ = _create_and_commit_second_revision(client, dataset_id, second_files)

    parent_path = Path(stores.hierarchy._revisions[UUID(first_view["id"])].revision_path)
    child_path = Path(stores.hierarchy._revisions[UUID(second_view["id"])].revision_path)
    _make_writable_and_remove(parent_path, (path for path, _ in first_files))

    for path, data in second_files:
        response = ingest.download(second_view["id"], path)
        assert response.status_code == 200, response.text
        assert response.content == data
        target = child_path / path
        assert stat.S_IMODE(target.stat().st_mode) == 0o444
        if path != changed_path:
            assert target.stat().st_nlink == 1
    for directory in _directories_under(child_path):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o555


def test_identical_submissions_create_distinct_revisions(client: TestClient) -> None:
    """A distinct upload of identical content creates another immutable revision."""
    ingest = IngestClient(client)
    _, dataset_id = ingest.developer_dataset()
    files = [("payload/result.txt", b"same scientific evidence")]
    first = ingest.upload_revision(dataset_id, files)
    second = ingest.upload_revision(dataset_id, files)
    assert first["id"] != second["id"]
    assert second["number"] == first["number"] + 1
    assert first["manifest_sha256"] == second["manifest_sha256"]


def test_omitted_files_do_not_carry_forward(client: TestClient) -> None:
    """The new revision contains only its own submission, without parent inheritance."""
    ingest = IngestClient(client)
    _, dataset_id = ingest.developer_dataset()
    first = ingest.upload_revision(dataset_id, [("payload/a.txt", b"a"), ("payload/b.txt", b"b")])
    second = ingest.upload_revision(dataset_id, [("payload/a.txt", b"a")])
    assert ingest.download(first["id"], "payload/b.txt").status_code == 200
    assert ingest.download(second["id"], "payload/b.txt").status_code == 404
