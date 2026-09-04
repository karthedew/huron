"""``PosixRawStore.write_generation``'s replace-not-refuse behavior, and its neighbors' contracts.

A generation file is replaced when one already exists at that number,
because acknowledged immutability comes from the hierarchy store advancing
a version only through a committed update, never from the filesystem
refusing to overwrite. ``write_tag_once`` keeps the opposite behavior - a
tag is a citation that must never be repointed - so this module also pins
that its ``O_EXCL`` refusal survived the change untouched.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from huron.pkg.rawstore import PosixRawStore

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def test_writing_the_same_generation_twice_replaces_its_document(tmp_path: Path) -> None:
    """A second write at an already-used generation number replaces the document without raising."""
    store = PosixRawStore(tmp_path)
    entity_dir = tmp_path / "organization" / "astro"

    store.write_generation(entity_dir, 1, b"first")
    store.write_generation(entity_dir, 1, b"second")

    assert (entity_dir / "generations" / "000001.json").read_bytes() == b"second"


def test_current_json_names_the_generation_last_written_at_that_number(tmp_path: Path) -> None:
    """After two writes to the same generation number, ``CURRENT.json`` still names it."""
    store = PosixRawStore(tmp_path)
    entity_dir = tmp_path / "organization" / "astro"

    store.write_generation(entity_dir, 1, b"first")
    store.write_generation(entity_dir, 1, b"second")

    pointer = json.loads((entity_dir / "CURRENT.json").read_bytes())
    assert pointer == {"generation": 1, "path": "generations/000001.json"}


def test_a_later_generation_leaves_the_earlier_one_untouched_and_repoints_current(
    tmp_path: Path,
) -> None:
    """Writing generation 2 does not disturb generation 1's document and moves ``CURRENT.json``."""
    store = PosixRawStore(tmp_path)
    entity_dir = tmp_path / "organization" / "astro"
    store.write_generation(entity_dir, 1, b"second")

    store.write_generation(entity_dir, 2, b"third")

    assert (entity_dir / "generations" / "000001.json").read_bytes() == b"second"
    assert (entity_dir / "generations" / "000002.json").read_bytes() == b"third"
    pointer = json.loads((entity_dir / "CURRENT.json").read_bytes())
    assert pointer == {"generation": 2, "path": "generations/000002.json"}


def test_write_generation_rejects_a_generation_number_outside_the_valid_range(
    tmp_path: Path,
) -> None:
    """A generation number outside ``1..999_999`` raises ``ValueError`` before any write."""
    store = PosixRawStore(tmp_path)
    entity_dir = tmp_path / "organization" / "astro"

    with pytest.raises(ValueError, match="generation out of range"):
        store.write_generation(entity_dir, 0, b"payload")

    assert not (entity_dir / "generations").exists()


def test_write_tag_once_still_refuses_a_second_write_to_the_same_tag(tmp_path: Path) -> None:
    """A second ``write_tag_once`` for the same tag file still raises ``FileExistsError``."""
    store = PosixRawStore(tmp_path)
    tag_file = tmp_path / "organization" / "astro" / "releases" / "v1.json"

    store.write_tag_once(tag_file, b"first")

    with pytest.raises(FileExistsError):
        store.write_tag_once(tag_file, b"second")

    assert tag_file.read_bytes() == b"first"
