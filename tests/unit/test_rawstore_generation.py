"""``PosixGenerationStore.write_generation``'s replace-not-refuse behavior.

A generation file is replaced when one already exists at that number,
because acknowledged immutability comes from the hierarchy store advancing
a version only through a committed update, never from the filesystem
refusing to overwrite.
"""

from __future__ import annotations

import errno
import json
import os
from typing import TYPE_CHECKING

import pytest

from huron.core.rawstore import PosixGenerationStore
from tests.unit.support import crash_on, fsync_log

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def test_writing_the_same_generation_twice_replaces_its_document(tmp_path: Path) -> None:
    """A second write at an already-used generation number replaces the document without raising."""
    store = PosixGenerationStore(tmp_path)
    entity_dir = tmp_path / "organization" / "astro"

    store.write_generation(entity_dir, 1, b"first")
    store.write_generation(entity_dir, 1, b"second")

    assert (entity_dir / "generations" / "000001.json").read_bytes() == b"second"


def test_current_json_names_the_generation_last_written_at_that_number(tmp_path: Path) -> None:
    """After two writes to the same generation number, ``CURRENT.json`` still names it."""
    store = PosixGenerationStore(tmp_path)
    entity_dir = tmp_path / "organization" / "astro"

    store.write_generation(entity_dir, 1, b"first")
    store.write_generation(entity_dir, 1, b"second")

    pointer = json.loads((entity_dir / "CURRENT.json").read_bytes())
    assert pointer == {"generation": 1, "path": "generations/000001.json"}


def test_a_later_generation_leaves_the_earlier_one_untouched_and_repoints_current(
    tmp_path: Path,
) -> None:
    """Writing generation 2 does not disturb generation 1's document and moves ``CURRENT.json``."""
    store = PosixGenerationStore(tmp_path)
    entity_dir = tmp_path / "organization" / "astro"
    store.write_generation(entity_dir, 1, b"second")

    store.write_generation(entity_dir, 2, b"third")

    assert (entity_dir / "generations" / "000001.json").read_bytes() == b"second"
    assert (entity_dir / "generations" / "000002.json").read_bytes() == b"third"
    pointer = json.loads((entity_dir / "CURRENT.json").read_bytes())
    assert pointer == {"generation": 2, "path": "generations/000002.json"}


@pytest.mark.parametrize("generation", [-1, 0, 1_000_000])
def test_write_generation_rejects_a_generation_number_outside_the_valid_range(
    tmp_path: Path,
    generation: int,
) -> None:
    """A generation number outside ``1..999_999`` raises ``ValueError`` before any write."""
    store = PosixGenerationStore(tmp_path)
    entity_dir = tmp_path / "organization" / "astro"

    with pytest.raises(ValueError, match="generation out of range"):
        store.write_generation(entity_dir, generation, b"payload")

    assert not (entity_dir / "generations").exists()


def test_initialize_creates_only_the_organization_directory_idempotently(tmp_path: Path) -> None:
    """Initialization creates missing parents and only the organization directory under its root."""
    root = tmp_path / "missing" / "data"
    store = PosixGenerationStore(root)
    assert store.root == root
    assert not root.exists()
    store.initialize()
    store.initialize()
    assert list(root.iterdir()) == [root / "organization"]
    assert (root / "organization").is_dir()


def test_generation_is_durable_before_the_pointer_moves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed pointer rename leaves the old pointer and a fully flushed new generation."""
    store = PosixGenerationStore(tmp_path)
    entity = tmp_path / "organization" / "astro"
    store.write_generation(entity, 1, b"first")
    log = fsync_log(monkeypatch)
    original_replace = os.replace

    def replace(source: Path, target: Path) -> None:
        if target.name == "CURRENT.json":
            assert (entity / "generations/000002.json").read_bytes() == b"second"
            assert entity / "generations" in log
            assert any(path.parent == entity / "generations" for path in log)
            raise OSError(errno.EIO, "pointer rename failed")
        original_replace(source, target)

    monkeypatch.setattr(os, "replace", replace)
    with pytest.raises(OSError, match="pointer rename failed"):
        store.write_generation(entity, 2, b"second")
    assert json.loads((entity / "CURRENT.json").read_bytes())["generation"] == 1
    assert not list(entity.glob(".CURRENT.json.*"))


def test_failed_generation_flush_preserves_old_bytes_and_cleans_temporary_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed file flush retains the previous generation bytes and removes its temporary file."""
    store = PosixGenerationStore(tmp_path)
    store.write_generation(tmp_path, 1, b"first")
    crash_on(monkeypatch, "fsync")
    with pytest.raises(OSError):
        store.write_generation(tmp_path, 1, b"second")
    assert (tmp_path / "generations/000001.json").read_bytes() == b"first"
    assert not list((tmp_path / "generations").glob(".000001.json.*"))


def test_document_writes_complete_short_writes_and_refuse_zero_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Generation replacement writes every byte and retains its old value when writing stalls."""
    store = PosixGenerationStore(tmp_path)
    original = os.write
    with monkeypatch.context() as patch:
        patch.setattr(os, "write", lambda descriptor, data: original(descriptor, data[:2]))
        store.write_generation(tmp_path, 1, b"original")
    target = tmp_path / "generations/000001.json"
    assert target.read_bytes() == b"original"
    with monkeypatch.context() as patch:
        patch.setattr(os, "write", lambda *_args: 0)
        with pytest.raises(OSError) as raised:
            store.write_generation(tmp_path, 1, b"replacement")
    assert raised.value.errno == errno.EIO
    assert target.read_bytes() == b"original"
    assert not list(target.parent.glob(".000001.json.*"))
