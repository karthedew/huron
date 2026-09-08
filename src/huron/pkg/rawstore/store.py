"""POSIX implementation of raw evidence-tier mechanisms.

:class:`PosixRawStore` is the concrete store behind the catalog's
``RawStore`` port and behind the control-plane documents the hierarchy
repository keeps on disk. It manages one data root on one filesystem with
the same discipline throughout: a revision is built in a private staging
envelope and published by rename, and a published revision is sealed
read-only. The private helpers guard the two things a caller could get
wrong - a client-supplied path escaping the payload directory, and a short
``write`` silently truncating a payload.
"""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from huron.schema.storage import PartLengthMismatchError

from .commit import assert_same_filesystem, commit_envelope, fsync_dir
from .inspection import verify_envelope
from .materialize import candidate, descendant, directory, file_chunks, install, observe

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

#: Document names a caller may never write at the envelope root: the empty
#: string and the two directory pseudo-entries are unsafe path components,
#: and ``payload`` is reserved for the upload tree itself.
_RESERVED_DOCUMENT_NAMES = frozenset({"", ".", "..", "payload"})


class PosixRawStore:
    """The raw layer on one POSIX filesystem, rooted at ``root``.

    In-flight ingests are built under ``root/.staging/{ingest}`` and
    published under ``root/organization/...`` by a single rename, which is
    why :meth:`initialize` insists both live on the same filesystem.
    :meth:`write_part` writes into a fixed byte range of a payload file
    that may already exist, so a resent part overwrites only its own
    bytes; it is the ingest ledger, not the filesystem, that vouches a
    part is durable. :meth:`atomic_replace` is the one primitive that
    replaces a file wholesale, and it does so through a rename so a reader
    sees the old bytes or the new, never a mix. Every primitive fsyncs
    what it wrote, and then the directory naming it, before returning, so
    a write that returned is a durable one. The class structurally
    satisfies :class:`huron.pkg.catalog.ports.RawStore`.
    """

    def __init__(self, root: str | Path):
        """Bind the store to a data root without touching the filesystem.

        Args:
            root: The data root; ``.staging`` and ``organization`` live
                directly beneath it. Nothing is created until
                :meth:`initialize`.
        """
        self.root = Path(root)

    def initialize(self) -> None:
        """Create the store's directory skeleton and prove it can commit.

        Creates ``.staging`` and ``organization`` under the root if missing,
        then checks that they share a filesystem. A
        :class:`~huron.pkg.rawstore.commit.CrossDeviceCommitError` from that
        check means no envelope could ever be published by rename, and it
        surfaces here, at startup, rather than at the first commit.
        """
        staging_root = self.root / ".staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        (self.root / "organization").mkdir(parents=True, exist_ok=True)
        assert_same_filesystem(staging_root, self.root / "organization")

    def create_staging(self, staging: PurePosixPath) -> None:
        """Claim a fresh, private envelope for one ingest session.

        ``staging`` must name a direct child of ``root/.staging``; the
        envelope and its ``payload`` child are created at mode ``0o700``,
        and all three directory entries - ``.staging``, the envelope and
        ``payload`` - are fsynced before returning. The envelope must not
        already exist: creating it is the ingest's claim on that name, and
        a second call for the same name fails at the ``mkdir`` rather than
        reusing a possibly half-built envelope.

        Args:
            staging: The envelope's path, from
                :func:`huron.pkg.catalog.paths.staging_dir`.

        Raises:
            ValueError: If ``staging``'s parent is not ``root/.staging``.
        """
        staging_root = self.root / ".staging"
        if PurePosixPath(staging).parent != PurePosixPath(staging_root):
            raise ValueError(f"staging envelope must live directly under {staging_root}: {staging}")
        envelope = Path(staging)
        staging_root.mkdir(parents=True, exist_ok=True)
        envelope.mkdir(mode=0o700)
        for child in ("upload", "completion", "envelope", "envelope/payload"):
            (envelope / child).mkdir(mode=0o700)
            fsync_dir(envelope / child)
        fsync_dir(envelope / "envelope")
        fsync_dir(envelope)
        fsync_dir(staging_root)

    def write_part(
        self,
        staging_payload: PurePosixPath,
        rel_path: str,
        chunks: Iterable[bytes],
        *,
        offset: int,
        length: int,
    ) -> str:
        """Stream one range of a payload file into place, hashing as it goes.

        The target is opened for writing without truncating and without
        requiring it to be new (``O_WRONLY | O_CREAT``, mode ``0o600``),
        because parts of one file arrive independently and a resend must
        overwrite only its own range. Exactly ``length`` bytes are pulled
        from ``chunks``, in order, written at ``[offset, offset + length)``
        with positional writes, and folded into a SHA-256 as they land;
        nothing outside that range is touched. An unsafe ``rel_path``
        raises ``ValueError`` before anything opens, and a stream that
        ends short or runs long raises ``PartLengthMismatchError`` before any
        success is reported. Before returning, the file and every
        directory from its parent up to ``staging_payload`` are fsynced,
        so a part the caller goes on to record is durable together with
        the names that reach it.

        Args:
            staging_payload: The envelope's ``payload`` directory.
            rel_path: The file's path relative to ``staging_payload`` (a
                leading ``payload/`` component is tolerated).
            chunks: The range's bytes, consumed once, in order.
            offset: The first byte position the range writes to.
            length: The exact number of bytes the range must contain.

        Returns:
            The hex SHA-256 of the bytes written.

        Raises:
            ValueError: If the upload input is not an independently owned regular file.
        """
        relative = _safe_relative(rel_path)
        with directory(Path(staging_payload)) as session, descendant(session, ("upload",)) as root:
            with descendant(root, relative.parts[:-1], create=True) as parent:
                descriptor = os.open(
                    relative.name,
                    os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                    0o600,
                    dir_fd=parent,
                )
                try:
                    info = os.fstat(descriptor)
                    if (
                        not stat.S_ISREG(info.st_mode)
                        or info.st_nlink != 1
                        or info.st_uid != os.geteuid()
                    ):
                        raise ValueError("upload input is not an independent regular file")
                    digest = _stream_part(descriptor, chunks, offset=offset, length=length)
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                os.fsync(parent)
            os.fsync(root)
        return digest

    def finish_file(
        self,
        staging: PurePosixPath,
        file_id: str,
        rel_path: str,
        *,
        expected_size: int,
        expected_sha256: str,
    ) -> tuple[int, str]:
        """Materialize verified bytes into an independent, closed payload inode.

        Args:
            staging: Existing session root.
            file_id: Upload input name.
            rel_path: Manifest path of the installed payload.
            expected_size: Declared complete byte count.
            expected_sha256: Declared content digest.

        Returns:
            Observed size and digest. A mismatch installs nothing.

        Raises:
            ValueError: If the input name is unsafe or an installed file conflicts.
        """
        if _safe_relative(file_id).parts != (file_id,):
            raise ValueError("upload input must be a single file name")
        relative = _safe_relative(rel_path)
        expected = expected_size, expected_sha256
        with (
            directory(Path(staging)) as root,
            descendant(root, ("upload",)) as upload,
            descendant(root, ("completion",)) as completion,
            descendant(root, ("envelope", "payload")) as payload,
            descendant(payload, relative.parts[:-1], create=True) as parent,
        ):
            try:
                existing = observe(parent, relative.name)
            except FileNotFoundError:
                pass
            else:
                if existing != expected:
                    raise ValueError("installed payload conflicts with declared content")
                os.fsync(parent)
                return existing
            with candidate(completion, file_chunks(upload, file_id)) as name:
                observed = observe(completion, name)
                if observed == expected:
                    install(completion, name, parent, relative.name, expected)
                return observed

    def discard_file(self, staging_payload: PurePosixPath, rel_path: str) -> None:
        """Remove a payload file the ledger no longer vouches for.

        A missing file is success: nothing is raised and nothing is
        fsynced, since there is no removal to make durable.

        Args:
            staging_payload: The envelope's ``payload`` directory.
            rel_path: The file's path relative to ``staging_payload`` (a
                leading ``payload/`` is tolerated).
        """
        relative = _safe_relative(rel_path)
        with (
            directory(Path(staging_payload)) as session,
            descendant(session, ("upload",)) as upload,
            descendant(upload, relative.parts[:-1]) as parent,
        ):
            try:
                os.unlink(relative.name, dir_fd=parent)
            except FileNotFoundError:
                return
            os.fsync(parent)

    def stat_document(self, path: PurePosixPath) -> os.stat_result:
        """Inspect a stored file without reading its contents.

        Args:
            path: The stored file's location.

        Returns:
            Its current filesystem metadata.
        """
        return os.stat(path)

    def read_document(self, path: PurePosixPath) -> bytes:
        """Return a stored document's bytes exactly as written.

        A path storage does not hold raises ``FileNotFoundError``.

        Args:
            path: The document's path.

        Returns:
            The document's content.
        """
        return Path(path).read_bytes()

    def write_document(self, staging: PurePosixPath, name: str, payload: bytes) -> None:
        """Durably place a control document at the envelope root.

        ``name`` must be a single path component and none of the reserved
        names; the document is written read-only through
        :meth:`atomic_replace`, so a second call with the same name
        replaces its bytes wholesale, never leaving a mix of an earlier
        attempt's content and the new one.

        Args:
            staging: The envelope's root directory.
            name: The document's file name.
            payload: The document's complete content.

        Raises:
            ValueError: If ``name`` is not a single, non-reserved
                component.
        """
        if "/" in name or name in _RESERVED_DOCUMENT_NAMES:
            raise ValueError(f"invalid document name: {name!r}")
        envelope = Path(staging)
        with (
            directory(envelope.parent) as root,
            descendant(root, ("completion",)) as completion,
            descendant(root, (envelope.name,)) as target,
            candidate(completion, (payload,)) as name_candidate,
        ):
            install(
                completion,
                name_candidate,
                target,
                name,
                (len(payload), hashlib.sha256(payload).hexdigest()),
            )

    def atomic_replace(
        self, path: PurePosixPath | Path, payload: bytes, *, mode: int = 0o444
    ) -> None:
        """Replace a file's content in one step, so a reader sees old bytes or new, never a mix.

        The payload is written to a temporary file beside the target
        (``.{name}.XXXXXX``), given ``mode``, fsynced and closed, and only
        then moved over the target with ``os.replace``; the directory is
        fsynced afterwards so the swap is durable. If anything fails before
        the swap, the temporary file is removed and the target is left as
        it was. This is the one primitive in the store that overwrites, and
        it exists for pointers such as ``CURRENT.json`` whose whole point
        is to move.

        Args:
            path: The file to replace; it need not exist yet, and parent
                directories are created as needed.
            payload: The complete new content.
            mode: Permission bits for the replacement file.
        """
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        temp_path = Path(temp_name)
        try:
            os.fchmod(descriptor, mode)
            _write_all(descriptor, payload)
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            os.replace(temp_path, target)
            fsync_dir(target.parent)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            temp_path.unlink(missing_ok=True)

    def seal(self, revision_dir: PurePosixPath) -> None:
        """Make everything below a directory read-only, the directory itself untouched.

        Every regular file becomes ``0o444`` and every directory below
        ``revision_dir``, from the deepest up, ``0o555``; ``revision_dir``
        keeps its own mode, so it can still be renamed by whatever
        publishes it next. Sealing changes permission bits only; the
        content was made durable at commit.

        Args:
            revision_dir: The directory whose contents are sealed.

        Raises:
            FileNotFoundError: If ``revision_dir`` is not a directory.
        """
        root = Path(revision_dir)
        if not root.is_dir():
            raise FileNotFoundError(root)
        for path in root.rglob("*"):
            if path.is_file():
                path.chmod(0o444)
        for path in sorted(
            (item for item in root.rglob("*") if item.is_dir()),
            key=lambda item: len(item.parts),
            reverse=True,
        ):
            path.chmod(0o555)

    def verify_envelope(
        self,
        envelope: PurePosixPath,
        files: Sequence[tuple[str, int, str]],
        documents: Mapping[str, bytes],
    ) -> None:
        """Check exact inventory and frozen evidence before publication or replay.

        Args:
            envelope: Existing staged or final envelope.
            files: Manifest paths, sizes and digests.
            documents: Frozen control document bytes.
        """
        verify_envelope(Path(envelope), files, documents)

    def commit_envelope(self, staging: PurePosixPath, final: PurePosixPath) -> None:
        """Publish a finished staging envelope at its final revision path.

        Delegates to :func:`huron.pkg.rawstore.commit.commit_envelope`, which
        holds the guarantees and the failure cases: the envelope is fsynced,
        revealed by one rename, never overwrites an existing revision, and
        a commit that already completed may be retried harmlessly.

        Args:
            staging: The envelope from :meth:`create_staging`, with its
                ``COMMITTED`` marker written.
            final: The revision directory to publish it as.
        """
        commit_envelope(Path(staging), Path(final))

    def _write_once(self, path: PurePosixPath | Path, payload: bytes, *, mode: int = 0o444) -> None:
        """Create a file that must not already exist, write ``payload``, and make it durable.

        The file is opened with ``O_EXCL``, so a name is written at most
        once and a second writer fails with the ``FileExistsError`` of that
        open rather than replacing what is there. The whole payload is
        written, the file fsynced, and then its directory fsynced so the
        new name survives a crash; parent directories are created as
        needed.

        Args:
            path: The file to create.
            payload: The complete content.
            mode: Permission bits for the new file; read-only for everyone
                by default, because the raw layer's records are written
                once and never edited.
        """
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        try:
            _write_all(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        fsync_dir(target.parent)

    def write_tag_once(self, tag_file: PurePosixPath, payload: bytes) -> None:
        """Publish one release tag file, refusing to overwrite an existing tag.

        A tag names one revision for good: it goes through
        :meth:`_write_once` as a read-only file, so retagging fails at the
        exclusive create instead of silently moving the tag.

        Args:
            tag_file: The tag's path under the dataset's ``releases``
                directory.
            payload: The release document's bytes.
        """
        self._write_once(tag_file, payload, mode=0o444)

    def write_generation(self, entity_dir: PurePosixPath, generation: int, payload: bytes) -> Path:
        """Record one generation of an entity document and point ``CURRENT.json`` at it.

        The document lands at ``{entity_dir}/generations/{NNNNNN}.json``
        through :meth:`atomic_replace`, not :meth:`_write_once`: immutability
        of an *acknowledged* generation is guaranteed above this layer, by
        the hierarchy store advancing an entity's generation only through a
        committed, version-guarded update, never by refusing to overwrite a
        file. A generation file already on disk at the number being written
        can therefore only be a crashed attempt that never reached that
        commit - a committed generation N would have made the store hand
        out N+1 next - so replacing it loses nothing a caller was ever told
        succeeded. ``{entity_dir}/CURRENT.json`` is then replaced atomically
        with a small pointer,
        ``{"generation": N, "path": "generations/NNNNNN.json"}``. The two
        steps are ordered, not joint: the generation file is durable before
        the pointer moves, so a crash between them leaves ``CURRENT.json``
        naming the previous generation with the new file already on disk.

        Args:
            entity_dir: The organization, project or dataset directory.
            generation: The document's generation number, ``1`` to
                ``999_999``, zero-padded to six digits in the file name.
            payload: The canonical bytes of the document.

        Returns:
            The path of the generation file that was written.

        Raises:
            ValueError: If ``generation`` is outside ``1..999_999``.
        """
        if not 1 <= generation <= 999_999:
            raise ValueError(f"generation out of range: {generation}")
        entity_path = Path(entity_dir)
        generation_path = entity_path / "generations" / f"{generation:06d}.json"
        self.atomic_replace(generation_path, payload, mode=0o444)
        pointer = (
            f'{{"generation":{generation},"path":"generations/{generation:06d}.json"}}'
        ).encode()
        self.atomic_replace(entity_path / "CURRENT.json", pointer, mode=0o444)
        return generation_path


def _safe_relative(value: str) -> Path:
    """Turn a client-supplied path into a safe path relative to the payload directory.

    Refuses anything that could reach outside the payload: an absolute
    path, an empty one, or any ``.``, ``..`` or empty component. A leading
    ``payload`` component is stripped so callers may name a file either
    relative to the payload directory or relative to the envelope, but
    something must remain after it - ``payload`` alone names no file.

    Args:
        value: The path as the client supplied it, in POSIX form.

    Returns:
        The validated path, relative to the payload directory.

    Raises:
        ValueError: If the path is absolute, empty, contains an unsafe
            component, or is nothing but ``payload``.
    """
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError(f"unsafe relative path: {value!r}")
    parts = path.parts[1:] if path.parts[0] == "payload" else path.parts
    if not parts:
        raise ValueError("a payload file path is required")
    return Path(*parts)


def _stream_part(descriptor: int, chunks: Iterable[bytes], *, offset: int, length: int) -> str:
    """Write a stream of chunks into a file range at ``offset``, hashing and length-checking it.

    Each chunk is fully written before the next is pulled from ``chunks``,
    so the producer only supplies the next chunk once the previous one is
    on disk; nothing is buffered here beyond one chunk.

    Args:
        descriptor: An open, writable file descriptor.
        chunks: The range's bytes, consumed once, in order.
        offset: The first byte position the range writes to.
        length: The exact number of bytes the range must contain.

    Returns:
        The hex SHA-256 of the bytes written.

    Raises:
        PartLengthMismatchError: If more or fewer than ``length`` bytes arrive.
    """
    digest = hashlib.sha256()
    written = 0
    for chunk in chunks:
        if written + len(chunk) > length:
            raise PartLengthMismatchError(f"part exceeded its planned length of {length} bytes")
        _pwrite_all(descriptor, chunk, offset + written)
        digest.update(chunk)
        written += len(chunk)
    if written != length:
        raise PartLengthMismatchError(f"part delivered {written} bytes, expected {length}")
    return digest.hexdigest()


def _write_all(descriptor: int, payload: bytes) -> None:
    """Write the whole payload to ``descriptor``, retrying across short writes.

    ``os.write`` may accept fewer bytes than it was given; this loops until
    every byte has been accepted, so no caller can mistake a partial write
    for a complete one.

    Args:
        descriptor: An open, writable file descriptor.
        payload: The bytes to write in full.
    """
    remaining = memoryview(payload)
    while remaining:
        written = os.write(descriptor, remaining)
        remaining = remaining[written:]


def _pwrite_all(descriptor: int, payload: bytes, offset: int) -> None:
    """Write the whole payload to ``descriptor`` at ``offset``, retrying across short writes.

    The positional twin of :func:`_write_all`: ``os.pwrite`` may accept
    fewer bytes than it was given, so this loops, advancing the offset by
    what was actually written, until every byte has landed.

    Args:
        descriptor: An open, writable file descriptor.
        payload: The bytes to write in full.
        offset: The absolute file position to start writing at.
    """
    remaining = memoryview(payload)
    position = offset
    while remaining:
        written = os.pwrite(descriptor, remaining, position)
        remaining = remaining[written:]
        position += written
