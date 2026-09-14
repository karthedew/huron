"""NFS-backed RawstoreService orchestration, Python 3.11+ (standard library).

Implement Catalog with PostgreSQL before multi-worker deployment. The service
assumes exclusive service-account ownership of its directories: path checks are
not a security boundary against other processes modifying the NFS tree directly.
Raw revisions are full snapshots. Upload resume/part scheduling, authorization,
quotas, cleanup, mount verification and crash-recovery scheduling belong outside
this example. Only catalog-published revisions are visible to readers.
"""
from __future__ import annotations

import asyncio
import errno
import hashlib
import json
import os
import stat
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import AbstractAsyncContextManager
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Protocol, TypeVar
from uuid import UUID, uuid4

T = TypeVar("T")
BUFFER_SIZE = 4 * 1024 * 1024  # Internal write/hash buffer; not an HTTP part size.
State = Literal["OPEN", "SEALED", "COMMITTED", "CONFLICT"]


class IntegrityError(ValueError):
    """An upload does not match its expected manifest."""


class RevisionConflict(RuntimeError):
    """The dataset's current revision changed after this upload began."""


def relative_path(value: str) -> PurePosixPath:
    """Accept canonical relative POSIX paths, including nested payload paths."""
    path = PurePosixPath(value)
    if (not value or path.is_absolute() or str(path) != value
            or any(p in (".", "..") for p in value.split("/"))
            or "\\" in value or "\x00" in value):
        raise ValueError(f"Unsafe relative path: {value!r}")
    return path


@dataclass(frozen=True)
class FileSpec:
    path: str
    size_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        relative_path(self.path)
        if self.size_bytes < 0:
            raise ValueError("size_bytes must be nonnegative")
        if len(self.sha256) != 64 or any(c not in "0123456789abcdef" for c in self.sha256):
            raise ValueError("sha256 must be a lowercase, 64-character hexadecimal digest")


@dataclass(frozen=True)
class DatasetRef:
    dataset_id: UUID
    # Resolved by the catalog after RBAC; never accept this field from a browser.
    # Include org/project/dataset/release segments here for the real layout.
    relative_root: str


@dataclass(frozen=True)
class Ingest:
    ingest_id: UUID
    dataset: DatasetRef
    revision_id: UUID
    revision_number: int
    expected_current_revision: UUID | None
    files: tuple[FileSpec, ...]
    state: State = "OPEN"


@dataclass(frozen=True)
class Revision:
    revision_id: UUID
    revision_number: int
    relative_path: str
    manifest_sha256: str


class Catalog(Protocol):
    """Application-specific PostgreSQL adapter; not a third-party library.

    Persist IDs, manifests, receipts, state and idempotency keys. Methods below
    must enforce their contracts across all processes, not just this instance.
    """

    async def get_dataset(self, dataset_id: UUID) -> DatasetRef | None: ...

    async def begin_ingest(
        self, dataset_id: UUID, files: tuple[FileSpec, ...], idempotency_key: str
    ) -> Ingest:
        """Atomically reserve a unique ID/ordinal and capture the current head.

        Reusing a scoped idempotency key returns the same session; reject reuse
        with different arguments. An explicit unknown dataset ID must fail.
        """
        ...

    def upload_access(self, ingest_id: UUID) -> AbstractAsyncContextManager[Ingest]:
        """Claim one OPEN session for writing; exclude finalizers and other uploads.

        Use a persisted claim/active-writer protocol, not a long DB transaction.
        Do not authorize replacement writers solely because a lease expired.
        """
        ...

    async def file_received(self, ingest_id: UUID, spec: FileSpec) -> None:
        """Idempotently record a verified file while upload_access is held."""
        ...

    def finalize_access(self, ingest_id: UUID) -> AbstractAsyncContextManager[Ingest]:
        """Exclude writers/finalizers; seal only when every file receipt exists.

        A SEALED session may be retried after exclusive ownership is established.
        A COMMITTED session may be returned for idempotent completion. Keep the
        session SEALED on filesystem failure. This is not a long DB transaction.
        """
        ...

    async def publish(self, ingest: Ingest, revision: Revision) -> None:
        """One short transaction: publish revision, CAS head, mark ingest COMMITTED.

        Compare the current head with expected_current_revision; on mismatch,
        raise RevisionConflict without publishing. Recognize an already committed
        ingest before checking its old expected head. Persist conflict/recovery
        state as appropriate. No NFS operations occur inside this transaction.
        """
        ...


async def finish_awaitable(operation: Coroutine[Any, Any, T]) -> T:
    """Drain an owned task before propagating cancellation of its caller."""
    task = asyncio.create_task(operation)
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except BaseException:
            break
    if cancelled:
        if not task.cancelled():
            task.exception()  # Observe a possible error before propagating cancellation.
        raise asyncio.CancelledError
    return task.result()


async def finish_thread(function: Callable[..., T], *args: object) -> T:
    """Drain a running filesystem call before propagating caller cancellation.

    Cancelling an asyncio waiter cannot kill a running OS thread. Delaying the
    cancellation keeps callers' semaphore/claim scopes alive until the operation
    has really finished. An unresponsive NFS mount can therefore delay shutdown.
    """
    return await finish_awaitable(asyncio.to_thread(function, *args))


def fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def ensure_directory(path: Path) -> None:
    """Create one directory, syncing its parent if newly created."""
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        if not stat.S_ISDIR(path.lstat().st_mode):
            raise IntegrityError(f"Not a real directory: {path}")
    else:
        fsync_directory(path.parent)


def ensure_tree(base: Path, relative: PurePosixPath) -> Path:
    current = base
    for part in relative.parts:
        current = current / part
        ensure_directory(current)
    return current


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(BUFFER_SIZE):
            digest.update(block)
    return digest.hexdigest()


def manifest_bytes(ingest: Ingest) -> bytes:
    # Deterministic JSON for these fields; not an implementation of RFC 8785/JCS.
    value = {
        "schema_version": 1,
        "ingest_id": str(ingest.ingest_id),
        "dataset_id": str(ingest.dataset.dataset_id),
        "revision_id": str(ingest.revision_id),
        "revision_number": ingest.revision_number,
        "parent_revision_id": (
            str(ingest.expected_current_revision) if ingest.expected_current_revision else None
        ),
        "files": [asdict(f) for f in sorted(ingest.files, key=lambda f: f.path)],
    }
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def atomic_document(path: Path, contents: bytes) -> None:
    """Idempotently install a small sidecar under exclusive session ownership."""
    if path.exists():
        if not stat.S_ISREG(path.lstat().st_mode) or path.read_bytes() != contents:
            raise IntegrityError(f"Existing sidecar differs: {path}")
        return
    temporary = path.parent / f".document-{uuid4()}.tmp"
    try:
        with temporary.open("xb") as output:
            output.write(contents)
            output.flush()
            os.fsync(output.fileno())
        os.rename(temporary, path)
        fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


class Filesystem:
    """Synchronous filesystem operations. Call through RawstoreService._io()."""

    def __init__(self, root: Path) -> None:
        if not root.is_absolute():
            raise ValueError("Configure an absolute storage root")
        self.root = root

    def dataset_root(self, dataset: DatasetRef) -> Path:
        return self.root.joinpath(*relative_path(dataset.relative_root).parts)

    def staging_root(self, ingest: Ingest) -> Path:
        return self.root / ".staging" / str(ingest.ingest_id)

    def revision_root(self, ingest: Ingest) -> Path:
        if ingest.revision_number < 1:
            raise ValueError("Revision numbers start at 1")
        return self.dataset_root(ingest.dataset) / "revisions" / (
            f"{ingest.revision_number:06d}--{ingest.revision_id}"
        )

    def initialize(self, dataset: DatasetRef) -> Path:
        # Do not create a missing storage root: it may indicate a missing mount.
        if not stat.S_ISDIR(self.root.lstat().st_mode):
            raise IntegrityError("Configured storage root is not a real directory")
        ensure_directory(self.root / ".staging")
        directory = ensure_tree(self.root, relative_path(dataset.relative_root))
        ensure_directory(directory / "revisions")
        return directory

    def stage(self, ingest: Ingest) -> Path:
        directory = self.staging_root(ingest)
        ensure_directory(directory)
        ensure_directory(directory / "payload")
        ensure_directory(directory / ".incoming")
        atomic_document(directory / "manifest.json", manifest_bytes(ingest))
        return directory

    def validate(self, directory: Path, ingest: Ingest, full: bool) -> None:
        if (directory / "manifest.json").read_bytes() != manifest_bytes(ingest):
            raise IntegrityError("Manifest differs from catalog reservation")
        payload = directory / "payload"
        if not stat.S_ISDIR(payload.lstat().st_mode):
            raise IntegrityError("Missing or invalid payload directory")
        expected = {f.path: f for f in ingest.files}
        seen: set[str] = set()
        def walk_error(error: OSError) -> None:
            raise error

        for base, directories, filenames in os.walk(
            payload, followlinks=False, onerror=walk_error
        ):
            for name in directories:
                if not stat.S_ISDIR((Path(base) / name).lstat().st_mode):
                    raise IntegrityError("Symlinks are not allowed in payloads")
            for name in filenames:
                path = Path(base) / name
                rel = path.relative_to(payload).as_posix()
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise IntegrityError(f"Not an independent regular file: {rel}")
                spec = expected.get(rel)
                if spec is None or info.st_size != spec.size_bytes:
                    raise IntegrityError(f"Unexpected file or incorrect size: {rel}")
                if full and sha256_file(path) != spec.sha256:
                    raise IntegrityError(f"SHA-256 mismatch: {rel}")
                seen.add(rel)
        if seen != set(expected):
            raise IntegrityError(f"Missing files: {sorted(set(expected) - seen)}")

    def locate(self, ingest: Ingest) -> tuple[Path, bool]:
        """Recover the successful-rename/before-publication window."""
        staged, final = self.staging_root(ingest), self.revision_root(ingest)
        if final.exists():
            if staged.exists():
                raise IntegrityError("Both staging and final paths exist; reconcile explicitly")
            return final, True
        return staged, False

    def finalize(self, ingest: Ingest) -> Path:
        staged, final = self.staging_root(ingest), self.revision_root(ingest)
        # Catalog ownership + unique revision IDs prevent races for this path.
        if final.exists():
            raise FileExistsError(final)
        if staged.stat().st_dev != final.parent.stat().st_dev:
            raise OSError(errno.EXDEV, "Staging and revisions must share a filesystem")
        incoming = staged / ".incoming"
        if incoming.exists():
            # Refuse to publish orphaned partial transfers. A recovery task can
            # reconcile them; this service never silently commits them.
            incoming.rmdir()  # Fails if not empty.
            fsync_directory(staged)
        # Never fall back to copy-and-delete in this commit operation.
        os.rename(staged, final)
        fsync_directory(final.parent)
        fsync_directory(staged.parent)
        return final

    def mark_ready(self, directory: Path, ingest: Ingest) -> None:
        # The marker means storage validation succeeded, NOT catalog publication.
        contents = (hashlib.sha256(manifest_bytes(ingest)).hexdigest() + "\n").encode()
        atomic_document(directory / "COMMITTED", contents)
        # Repeat directory syncs during recovery from a partially acknowledged rename.
        fsync_directory(directory)
        fsync_directory(directory.parent)
        fsync_directory(self.root / ".staging")


class StreamingFile:
    """One blocking writer; every method is run through the service I/O gate."""

    def __init__(self, filesystem: Filesystem, ingest: Ingest, spec: FileSpec) -> None:
        stage = filesystem.staging_root(ingest)
        self.stage, self.spec = stage, spec
        self.temporary = stage / ".incoming" / str(uuid4())
        self.final = stage / "payload" / spec.path
        self.output = None
        self.count = 0
        self.digest = hashlib.sha256()

    def start(self) -> None:
        parent = PurePosixPath(self.spec.path).parent
        if str(parent) != ".":
            ensure_tree(self.stage / "payload", parent)
        self.output = self.temporary.open("xb")

    def write(self, block: bytes | memoryview) -> None:
        if self.output is None:
            raise RuntimeError("Writer is not open")
        if self.count + len(block) > self.spec.size_bytes:
            raise IntegrityError("Upload exceeded expected size")
        written = self.output.write(block)
        if written != len(block):
            raise OSError("Short file write")
        self.count += written
        self.digest.update(block)

    def finish(self) -> None:
        if self.output is None:
            raise RuntimeError("Writer is not open")
        if self.count != self.spec.size_bytes or self.digest.hexdigest() != self.spec.sha256:
            raise IntegrityError("Upload size or SHA-256 does not match its declaration")
        self.output.flush()
        os.fsync(self.output.fileno())
        self.output.close()
        self.output = None
        if self.final.exists():  # A whole-file retry may find a previously received file.
            info = self.final.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or info.st_size != self.spec.size_bytes
                    or sha256_file(self.final) != self.spec.sha256):
                raise IntegrityError("Existing payload differs; refusing to overwrite")
            self.temporary.unlink()
        else:
            os.rename(self.temporary, self.final)
        fsync_directory(self.final.parent)
        fsync_directory(self.temporary.parent)

    def close(self) -> None:
        try:
            if self.output is not None:
                self.output.close()
                self.output = None
        finally:
            self.temporary.unlink(missing_ok=True)


class RawstoreService:
    """One shared instance per event loop/process, not one instance per request."""

    def __init__(
        self, root: Path, catalog: Catalog, *, max_io: int = 8,
        max_uploads: int = 4, max_validations: int = 2, max_ingests: int = 4
    ) -> None:
        if min(max_io, max_uploads, max_validations, max_ingests) < 1:
            raise ValueError("All concurrency limits must be positive")
        self.catalog = catalog
        self.fs = Filesystem(root)
        self._io_slots = asyncio.BoundedSemaphore(max_io)
        self._upload_slots = asyncio.BoundedSemaphore(max_uploads)
        self._validation_slots = asyncio.BoundedSemaphore(max_validations)
        self._ingest_slots = asyncio.BoundedSemaphore(max_ingests)

    async def _io(self, function: Callable[..., T], *args: object) -> T:
        async with self._io_slots:
            return await finish_thread(function, *args)

    async def check(self, dataset_id: UUID | None) -> Literal["NEW_DATASET", "NEW_REVISION"]:
        """Planning only; not a reservation or concurrency guarantee."""
        if dataset_id is None:
            return "NEW_DATASET"
        if await self.catalog.get_dataset(dataset_id) is None:
            raise LookupError(f"Unknown dataset: {dataset_id}")
        return "NEW_REVISION"

    async def initialize(self, dataset_id: UUID) -> Path:
        """Initialize storage for a dataset already created/authorized in the catalog."""
        dataset = await self.catalog.get_dataset(dataset_id)
        if dataset is None:
            raise LookupError(f"Unknown dataset: {dataset_id}")
        return await self._io(self.fs.initialize, dataset)

    async def stage(
        self, dataset_id: UUID, files: tuple[FileSpec, ...], *, idempotency_key: str
    ) -> Ingest:
        """Reserve an upload and create its private workspace; transfer no bytes."""
        if not files or not idempotency_key:
            raise ValueError("Provide a nonempty manifest and idempotency key")
        names = {f.path for f in files}
        if len(names) != len(files):
            raise ValueError("Duplicate payload paths")
        for name in names:
            if any(str(p) in names for p in PurePosixPath(name).parents if str(p) != "."):
                raise ValueError("One file path is a parent of another file path")
        await self.initialize(dataset_id)
        ingest = await self.catalog.begin_ingest(dataset_id, files, idempotency_key)
        if ingest.state == "OPEN":
            # Serialize retries of stage() with uploads/finalization of this session.
            async with self.catalog.upload_access(ingest.ingest_id) as current:
                await self._io(self.fs.stage, current)
        return ingest

    async def write_file(
        self, ingest_id: UUID, filename: str, chunks: AsyncIterator[bytes]
    ) -> None:
        """Receive one full file; independent sessions can transfer in parallel.

        The producer must itself yield bounded blocks. This method slices them
        for disk I/O but cannot undo memory already allocated by the producer.
        This is NOT a resumable-offset/part implementation.
        """
        relative_path(filename)
        async with self._upload_slots:
            async with self.catalog.upload_access(ingest_id) as ingest:
                spec = next((f for f in ingest.files if f.path == filename), None)
                if spec is None:
                    raise IntegrityError("File is not in the reserved manifest")
                writer = StreamingFile(self.fs, ingest, spec)
                try:
                    await self._io(writer.start)
                    async for chunk in chunks:
                        if not isinstance(chunk, bytes):
                            raise TypeError("The stream must yield bytes")
                        block = memoryview(chunk)
                        for offset in range(0, len(block), BUFFER_SIZE):
                            await self._io(writer.write, block[offset:offset + BUFFER_SIZE])
                    await self._io(writer.finish)
                    await self.catalog.file_received(ingest_id, spec)
                finally:
                    # A started write is drained before close, including cancellation.
                    await finish_awaitable(self._io(writer.close))

    async def validate(self, ingest: Ingest, *, final: bool, full: bool = True) -> None:
        """Validate under a session claim or against immutable committed data."""
        directory = self.fs.revision_root(ingest) if final else self.fs.staging_root(ingest)
        async with self._validation_slots:
            await self._io(self.fs.validate, directory, ingest, full)

    async def ingest(self, ingest_id: UUID) -> Revision:
        """Seal, verify, rename, verify again, mark storage-ready, publish."""
        async with self._ingest_slots:
            async with self.catalog.finalize_access(ingest_id) as ingest:
                directory = self.fs.revision_root(ingest)
                revision = Revision(
                    ingest.revision_id,
                    ingest.revision_number,
                    directory.relative_to(self.fs.root).as_posix(),
                    hashlib.sha256(manifest_bytes(ingest)).hexdigest(),
                )
                if ingest.state == "COMMITTED":
                    return revision
                _, already_moved = await self._io(self.fs.locate, ingest)
                # On recovery, fully validate the candidate at its final path.
                await self.validate(ingest, final=already_moved, full=True)
                if not already_moved:
                    directory = await self._io(self.fs.finalize, ingest)
                    # A rename does not copy the file contents. Recheck inventory,
                    # manifest and sizes, without an unconditional second full scan.
                    await self.validate(ingest, final=True, full=False)
                await self._io(self.fs.mark_ready, directory, ingest)
                # Must atomically recheck the expected head and publish in PostgreSQL.
                await self.catalog.publish(ingest, revision)
                return revision

