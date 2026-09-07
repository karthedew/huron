"""``INDEX.json``'s schema: a dataset's committed revisions, each named by its directory.

The index is a derived navigation aid, not a source of truth, but a reader
still has to trust that each entry's digests and identifiers are well
formed and that ``directory`` actually names a revision directory, so a
stale or hand-edited index is caught before anything walks it.
"""

from __future__ import annotations

from typing import Any

import pytest
from jsonschema import ValidationError

from huron.schema import validate, validator

pytestmark = pytest.mark.unit

SCHEMA = "revision-index-v1.json"
DIGEST = "a" * 64
REVISION_ID = "4c29d3e9-88dd-4aac-a703-859ad82b180b"
DATASET_ID = "5c29d3e9-88dd-4aac-a703-859ad82b180c"
DIRECTORY = "000001--0192f1a000007000800000000000ab00"


def _entry(**overrides: Any) -> dict[str, Any]:
    """Build a valid revision-index entry, with any overrides merged in."""
    entry: dict[str, Any] = {
        "number": 1,
        "revision_id": REVISION_ID,
        "directory": DIRECTORY,
        "manifest_sha256": DIGEST,
        "metadata_sha256": DIGEST,
        "file_count": 3,
        "total_bytes": 1024,
        "committed_at": "2026-08-30T19:02:41Z",
    }
    return entry | overrides


def _index(**overrides: Any) -> dict[str, Any]:
    """Build a valid revision index document, with any overrides merged in."""
    document: dict[str, Any] = {
        "schema": "urn:huron:revision-index:1",
        "dataset_id": DATASET_ID,
        "revisions": [_entry()],
    }
    return document | overrides


def test_the_schema_itself_is_valid() -> None:
    """The revision-index schema itself is a valid JSON Schema document."""
    validator(SCHEMA)


def test_a_well_formed_index_validates() -> None:
    """An index with every required member, well formed, validates."""
    validate(SCHEMA, _index())


def test_an_empty_index_validates() -> None:
    """A dataset with no committed revisions is a valid, empty index."""
    validate(SCHEMA, _index(revisions=[]))


@pytest.mark.parametrize("member", ["schema", "dataset_id", "revisions"])
def test_every_required_member_is_required(member: str) -> None:
    """Removing any one top-level required member fails validation."""
    document = _index()
    del document[member]
    with pytest.raises(ValidationError):
        validate(SCHEMA, document)


@pytest.mark.parametrize(
    "member",
    [
        "number",
        "revision_id",
        "directory",
        "manifest_sha256",
        "metadata_sha256",
        "file_count",
        "total_bytes",
        "committed_at",
    ],
)
def test_every_entry_member_is_required(member: str) -> None:
    """Removing any one required member of an entry fails validation."""
    entry = _entry()
    del entry[member]
    with pytest.raises(ValidationError):
        validate(SCHEMA, _index(revisions=[entry]))


def test_unknown_members_are_refused() -> None:
    """An index or an entry carrying an unlisted member fails validation."""
    with pytest.raises(ValidationError):
        validate(SCHEMA, _index(extra="not part of the contract"))
    with pytest.raises(ValidationError):
        validate(SCHEMA, _index(revisions=[_entry(extra="not part of the contract")]))


@pytest.mark.parametrize(
    ("member", "value"),
    [
        ("revision_id", "not-a-uuid"),
        ("manifest_sha256", DIGEST.upper()),
        ("metadata_sha256", DIGEST.upper()),
        ("manifest_sha256", "too-short"),
    ],
)
def test_digests_and_ids_must_be_well_formed(member: str, value: str) -> None:
    """A malformed digest or identifier in an entry fails validation."""
    with pytest.raises(ValidationError):
        validate(SCHEMA, _index(revisions=[_entry(**{member: value})]))


@pytest.mark.parametrize(
    "directory",
    ["not-a-directory", "1--0192f1a000007000800000000000ab", "000001--too-short"],
)
def test_the_directory_name_must_be_a_revision_directory(directory: str) -> None:
    """A ``directory`` that is not ``{NNNNNN}--{32 hex characters}`` fails validation."""
    with pytest.raises(ValidationError):
        validate(SCHEMA, _index(revisions=[_entry(directory=directory)]))
