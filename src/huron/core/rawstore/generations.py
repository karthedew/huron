"""Durable generation documents and current-generation pointers for the hierarchy."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path, PurePosixPath

from .materialize import fsync_dir, write_all


class PosixGenerationStore:
    """Write hierarchy generations and atomically advance their current pointers."""

    def __init__(self, root: Path) -> None:
        """Bind the generation store without touching the filesystem.

        Args:
            root: Data root containing the organization hierarchy.
        """
        self._root = root

    @property
    def root(self) -> Path:
        """Return the data root containing the organization hierarchy.

        Returns:
            The configured data root.
        """
        return self._root

    def initialize(self) -> None:
        """Create the organization directory and its missing parents."""
        (self.root / "organization").mkdir(parents=True, exist_ok=True)

    def _atomic_replace(self, path: Path, payload: bytes, *, mode: int) -> None:
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
            write_all(descriptor, payload)
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            os.replace(temp_path, target)
            fsync_dir(target.parent)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            temp_path.unlink(missing_ok=True)

    def write_generation(self, entity_dir: PurePosixPath, generation: int, payload: bytes) -> Path:
        """Record one generation of an entity document and point ``CURRENT.json`` at it.

        The document lands at ``{entity_dir}/generations/{NNNNNN}.json``
        through :meth:`_atomic_replace`: immutability of an *acknowledged*
        generation is guaranteed above this layer, by the hierarchy store
        advancing an entity's generation only through a committed,
        version-guarded update, never by refusing to overwrite a file. A
        generation file already on disk at the number being written can
        therefore only be a crashed attempt that never reached that
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
        self._atomic_replace(generation_path, payload, mode=0o444)
        pointer = (
            f'{{"generation":{generation},"path":"generations/{generation:06d}.json"}}'
        ).encode()
        self._atomic_replace(entity_path / "CURRENT.json", pointer, mode=0o444)
        return generation_path
