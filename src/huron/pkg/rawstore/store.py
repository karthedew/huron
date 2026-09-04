"""POSIX implementation of raw evidence-tier mechanisms.

:class:`PosixRawStore` is the concrete store behind the catalog's
``RawStore`` port and behind the control-plane documents the hierarchy
repository keeps on disk. It manages one data root on one filesystem with
the same discipline throughout: a file is created exclusively and fsynced
before it is trusted, a revision is built in a private staging envelope
and published by rename, and a published revision is sealed read-only.
The private helpers guard the two things a caller could get wrong - a
client-supplied path escaping the payload directory, and a short ``write``
silently truncating a payload.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from .commit import assert_same_filesystem, commit_envelope, fsync_dir

if TYPE_CHECKING:
    from uuid import UUID


class PosixRawStore:
    """The raw layer on one POSIX filesystem, rooted at ``root``.

    In-flight ingests are built under ``root/.staging/{ingest}`` and
    published under ``root/organization/...`` by a single rename, which is
    why :meth:`initialize` insists both live on the same filesystem.
    :meth:`write_once`, :meth:`write_part` and the hard-link fallback create
    their file exclusively (``O_EXCL``), so a name is written at most once;
    :meth:`atomic_replace` is the one primitive that replaces a file, and it
    does so through a rename so a reader sees the old bytes or the new,
    never a mix. Every primitive fsyncs what it wrote, and then the
    directory naming it, before returning, so a write that returned is a
    durable one. The class structurally satisfies
    :class:`huron.pkg.catalog.ports.RawStore`.
    """

    def __init__(self, root: str | Path, *, hardlink_fallback_copy: bool = True):
        """Bind the store to a data root without touching the filesystem.

        Args:
            root: The data root; ``.staging`` and ``organization`` live
                directly beneath it. Nothing is created until
                :meth:`initialize`.
            hardlink_fallback_copy: Whether :meth:`hardlink_from_parent`
                copies the file when a hard link cannot be made, instead of
                raising the ``OSError`` from the failed link.
        """
        self.root = Path(root)
        self.hardlink_fallback_copy = hardlink_fallback_copy

    @property
    def staging_root(self) -> Path:
        """Return ``root/.staging``, where in-flight ingest envelopes are built.

        Returns:
            The staging directory; it may not exist yet.
        """
        return self.root / ".staging"

    def initialize(self) -> None:
        """Create the store's directory skeleton and prove it can commit.

        Creates ``.staging`` and ``organization`` under the root if missing,
        then checks that they share a filesystem. A
        :class:`~huron.pkg.rawstore.commit.CrossDeviceCommitError` from that
        check means no envelope could ever be published by rename, and it
        surfaces here, at startup, rather than at the first commit.
        """
        self.staging_root.mkdir(parents=True, exist_ok=True)
        (self.root / "organization").mkdir(parents=True, exist_ok=True)
        assert_same_filesystem(self.staging_root, self.root / "organization")

    def create_staging(self, ingest_id: UUID) -> Path:
        """Create the private staging envelope for one ingest.

        The envelope is ``.staging/{ingest hex}`` with an empty ``payload``
        directory inside, both mode ``0o700`` so only the owning user can
        read an envelope before it is published. The directory must not
        already exist: creating it is the ingest's claim on that name, and
        a second call for the same ingest fails at the ``mkdir`` rather
        than reusing a possibly half-built envelope.

        Args:
            ingest_id: The ingest the envelope belongs to; its hex form
                names the directory.

        Returns:
            The envelope's path; uploads go under its ``payload`` child.
        """
        self.staging_root.mkdir(parents=True, exist_ok=True)
        staging = self.staging_root / ingest_id.hex
        staging.mkdir(mode=0o700)
        (staging / "payload").mkdir(mode=0o700)
        return staging

    def hardlink_from_parent(
        self,
        parent_payload: PurePosixPath,
        staging_payload: PurePosixPath,
        rel_path: str,
    ) -> None:
        """Carry one unchanged file from the parent revision into the staging payload.

        The file is hard-linked rather than copied, so an incremental
        revision costs one directory entry per inherited file and the bytes
        stay shared with the parent. When the link cannot be made and
        ``hardlink_fallback_copy`` is set, the bytes are copied into a newly
        created file and fsynced instead. ``rel_path`` is validated as a
        safe payload-relative path first, so an unsafe one fails with the
        ``ValueError`` of that check before anything is touched.

        Args:
            parent_payload: The parent revision's ``payload`` directory.
            staging_payload: The staging envelope's ``payload`` directory.
            rel_path: The file's path relative to the payload directory (a
                leading ``payload/`` is tolerated); intermediate directories
                are created as needed.

        Raises:
            OSError: If the hard link cannot be created and copying is
                disabled.
        """
        relative = _safe_relative(rel_path)
        source = Path(parent_payload) / relative
        target = Path(staging_payload) / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(source, target)
        except OSError:
            if not self.hardlink_fallback_copy:
                raise
            _copy_exclusive(source, target)

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

    def seal(self, revision_dir: PurePosixPath) -> None:
        """Make a published revision read-only, files and directories alike.

        Every regular file becomes ``0o444`` and every directory, from the
        deepest up to ``revision_dir`` itself, ``0o555``: the revision can
        still be read and traversed, but ordinary permissions no longer let
        anything in it be created, renamed or rewritten. Sealing changes
        permission bits only; the content was made durable at commit.

        Args:
            revision_dir: The published revision directory.

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
        root.chmod(0o555)

    def write_once(self, path: PurePosixPath | Path, payload: bytes, *, mode: int = 0o444) -> None:
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
        :meth:`write_once` as a read-only file, so retagging fails at the
        exclusive create instead of silently moving the tag.

        Args:
            tag_file: The tag's path under the dataset's ``releases``
                directory.
            payload: The release document's bytes.
        """
        self.write_once(tag_file, payload, mode=0o444)

    def write_generation(self, entity_dir: PurePosixPath, generation: int, payload: bytes) -> Path:
        """Record one generation of an entity document and point ``CURRENT.json`` at it.

        The document lands at ``{entity_dir}/generations/{NNNNNN}.json``
        through :meth:`atomic_replace`, not :meth:`write_once`: immutability
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

    def write_part(
        self, staging: PurePosixPath, rel_path: str, chunks: list[bytes]
    ) -> tuple[int, str]:
        """Write one upload atomically while hashing the exact bytes in flight.

        The file is created exclusively (``O_EXCL``, mode ``0o600``) under
        the staging directory at the validated relative path, so an upload
        lands at most once and stays private until the revision is sealed.
        Every chunk is written in full and folded into a SHA-256 as it goes,
        and the file is fsynced before returning, so the digest and size
        describe exactly the bytes that reached stable storage - which is
        what lets the manifest be checked against them. An unsafe
        ``rel_path`` fails with the ``ValueError`` of that check before the
        file is created.

        Args:
            staging: The directory the upload is written beneath - the
                envelope's ``payload`` directory, since a leading
                ``payload/`` in ``rel_path`` is stripped rather than kept.
            rel_path: The upload's path relative to the payload directory
                (a leading ``payload/`` is tolerated).
            chunks: The upload's bytes, in order; an empty list writes an
                empty file.

        Returns:
            The number of bytes written and the hex SHA-256 of those bytes.
        """
        target = Path(staging) / _safe_relative(rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        digest = hashlib.sha256()
        size = 0
        try:
            for chunk in chunks:
                _write_all(descriptor, chunk)
                digest.update(chunk)
                size += len(chunk)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return size, digest.hexdigest()


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


def _copy_exclusive(source: Path, target: Path) -> None:
    """Copy ``source`` into a newly created ``target``, refusing an existing file.

    The fallback for filesystems where a hard link cannot be made: the
    target is created exclusively with mode ``0o600``, the bytes are
    streamed across, and the file is flushed and fsynced before it is
    closed, so the copy is as durable as a link would have been.

    Args:
        source: The existing file to read.
        target: The path to create; it must not exist.
    """
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with (
            source.open("rb") as source_file,
            os.fdopen(descriptor, "wb", closefd=False) as target_file,
        ):
            shutil.copyfileobj(source_file, target_file)
            target_file.flush()
            os.fsync(descriptor)
    finally:
        os.close(descriptor)


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
