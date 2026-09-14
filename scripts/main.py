"""Upload ~/documents/Books into a new Raw dataset through the running Huron API.

Run with HURON_API_KEY set in the environment:
    uv run python scripts/main.py --project-id <project-uuid> --creator "Karl"

Reuse the printed --upload-id with the same files and arguments to resume a run.
Each new upload ID creates a new books-<upload-id> dataset in the chosen project.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, Field

from huron.pkg.catalog import ManifestEntry, validate_manifest
from huron.pkg.catalog.errors import DomainError
from huron.pkg.catalog.metadata import MetadataSubmission

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import BinaryIO


class UploadFile(BaseModel):
    """The fields needed from an API file-upload plan."""

    file_id: UUID
    path: str
    size: int = Field(ge=0)
    part_count: int = Field(ge=1)
    state: str
    completed_parts: list[int]


class UploadSession(BaseModel):
    """The fields needed to resume and commit an API upload session."""

    id: UUID
    dataset_id: UUID
    state: str
    etag: int
    manifest_sha256: str
    part_bytes: int = Field(gt=0)
    files: list[UploadFile]


def directory_files(directory: Path) -> Iterator[Path]:
    """Walk regular files recursively, refusing links and unreadable directories.

    Args:
        directory: Source directory to enumerate.

    Yields:
        Each regular file, in stable path order.

    Raises:
        ValueError: If a symbolic link or special file is encountered.
    """
    for path in sorted(directory.iterdir()):
        if path.is_symlink():
            raise ValueError(f"Symbolic links are not supported: {path}")
        if path.is_dir():
            yield from directory_files(path)
        elif path.is_file():
            yield path
        else:
            raise ValueError(f"Not a regular file: {path}")


def part_chunks(handle: BinaryIO, length: int) -> Iterator[bytes]:
    """Stream exactly one upload part with at most 1 MiB buffered at a time.

    Args:
        handle: Source file positioned at the part's starting offset.
        length: Number of bytes the server expects for this part.

    Yields:
        Bounded chunks totalling the declared part length.

    Raises:
        ValueError: If the file has become shorter since it was hashed.
    """
    remaining = length
    while remaining:
        chunk = handle.read(min(1024 * 1024, remaining))
        if not chunk:
            raise ValueError("Source file became shorter during upload")
        remaining -= len(chunk)
        yield chunk


def upload_files(client: httpx.Client, session: UploadSession, sources: dict[str, Path]) -> None:
    """Transfer missing parts and complete files using the server's upload plan.

    Args:
        client: Authenticated HTTP client connected to Huron.
        session: Current upload plan and acknowledged progress.
        sources: Local files keyed by their declared manifest paths.
    """
    for file in session.files:
        if file.state == "COMPLETE":
            continue
        print(f"Uploading {file.path} ({file.size:,} bytes)", flush=True)
        target = f"/api/v1/transfer/uploads/{file.file_id}"
        with sources[file.path].open("rb") as handle:
            for part in range(1, file.part_count + 1):
                if part in file.completed_parts:
                    continue
                offset = (part - 1) * session.part_bytes
                length = min(session.part_bytes, file.size - offset)
                handle.seek(offset)
                client.put(
                    f"{target}/parts/{part}",
                    content=part_chunks(handle, length),
                    headers={
                        "Content-Length": str(length),
                        "Content-Type": "application/octet-stream",
                    },
                ).raise_for_status()
        if file.part_count > 1:
            client.post(f"{target}/complete").raise_for_status()


def upload_books(
    client: httpx.Client, source: Path, project_id: UUID, creator: str, upload_id: UUID
) -> httpx.Response:
    """Create or resume a Books dataset and return only after its revision commits.

    Args:
        client: Authenticated HTTP client connected to Huron.
        source: Directory containing the complete submission.
        project_id: Existing project that will own the new dataset.
        creator: Descriptive revision creator, not an authentication identity.
        upload_id: Stable retry identity; a new value creates a new dataset.

    Returns:
        Successful commit response containing the revision receipt.

    Raises:
        ValueError: If the source is not a directory, the creator is empty, or the session
            cannot be resumed. Local manifest validation and HTTP errors also propagate.
    """
    source = source.expanduser()
    if not source.is_dir():
        raise ValueError(f"Source directory does not exist: {source}")
    if not creator.strip():
        raise ValueError("A non-empty revision creator is required")
    metadata = MetadataSubmission(title="Books", creators=[creator], description="Book collection")
    print(f"Upload ID: {upload_id} (reuse --upload-id {upload_id} to resume)", flush=True)
    sources = {
        f"payload/{path.relative_to(source).as_posix()}": path for path in directory_files(source)
    }
    entries = []
    for name, path in sources.items():
        print(f"Hashing {name}", flush=True)
        with path.open("rb") as handle:
            size = os.fstat(handle.fileno()).st_size
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        entries.append(ManifestEntry(path=name, size=size, sha256=digest))
    manifest = validate_manifest(entries)
    print(f"Submitting {len(entries)} files ({manifest.total_bytes:,} bytes)", flush=True)
    opened = client.post(
        f"/api/v1/projects/{project_id}/ingest-sessions",
        headers={"Idempotency-Key": f"books/{upload_id}"},
        json={
            "dataset": {
                "slug": f"books-{upload_id.hex}",
                "title": "Books",
                "description": "Book collection",
                "profile_name": "books",
                "profile_version": "1.0",
            },
            "files": [
                {"path": file.path, "size": file.size, "sha256": file.sha256}
                for file in manifest.files
            ],
        },
    ).raise_for_status()
    session = UploadSession.model_validate(opened.json())
    print(f"Dataset: {session.dataset_id}\nSession: {session.id}", flush=True)
    endpoint = f"/api/v1/ingest-sessions/{session.id}"
    if session.state == "UPLOADING":
        upload_files(client, session, sources)
        verified = client.post(f"{endpoint}/verify").raise_for_status()
        session = UploadSession.model_validate(verified.json())
    if session.state not in {"VERIFYING", "COMMITTING", "COMMITTED"}:
        raise ValueError(f"Cannot resume session in state {session.state}; use a new --upload-id")
    return client.post(
        f"{endpoint}/commit",
        headers={"Idempotency-Key": f"books/{upload_id}/commit", "If-Match": f'"{session.etag}"'},
        json={
            "manifest_sha256": session.manifest_sha256,
            "metadata": metadata.model_dump(exclude_none=True),
        },
    ).raise_for_status()


def main() -> None:
    """Read connection settings and upload the Books directory as one committed revision.

    Raises:
        SystemExit: If local validation, transfer, or commit fails.
    """
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--project-id", type=UUID, required=True, help="Existing parent project UUID"
    )
    parser.add_argument("--source", type=Path, default=Path("~/documents/Books"))
    parser.add_argument("--api-url", default=os.getenv("HURON_API_URL", "http://localhost:8080"))
    parser.add_argument("--creator", default=getpass.getuser(), help="Revision metadata creator")
    parser.add_argument("--upload-id", type=UUID, default=uuid4(), help="Reuse this UUID to resume")
    parser.add_argument(
        "--dev-subject", help="Explicit subject for a server using dev-headers auth"
    )
    args = parser.parse_args()
    token = os.getenv("HURON_API_KEY")
    if args.dev_subject and token:
        parser.error("Choose HURON_API_KEY or --dev-subject, not both")
    if not token and not args.dev_subject:
        parser.error("Set HURON_API_KEY, or supply --dev-subject for a development server")
    headers = (
        {"Authorization": f"Bearer {token}"} if token else {"X-Huron-Subject": args.dev_subject}
    )
    try:
        with httpx.Client(base_url=args.api_url, headers=headers, timeout=600.0) as client:
            response = upload_books(
                client, args.source, args.project_id, args.creator, args.upload_id
            )
        print(f"Committed revision:\n{response.text}")
    except httpx.HTTPStatusError as error:
        print(
            f"Upload failed: HTTP {error.response.status_code}\n{error.response.text}",
            file=sys.stderr,
        )
        raise SystemExit(1) from error
    except (httpx.RequestError, OSError, ValueError, DomainError) as error:
        print(f"Upload failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
