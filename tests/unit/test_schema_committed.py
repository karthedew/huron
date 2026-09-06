"""The ``COMMITTED`` marker's schema: every field a revision record carries but its location.

A marker with a missing or malformed field cannot be trusted to reconstruct
the row it describes, so the schema is as strict as the value object built
from it: no unlisted member, every digest and identifier well formed, and
an instant that is actually RFC 3339.
"""

from __future__ import annotations

from typing import Any

import pytest
from jsonschema import ValidationError

from huron.schema import validate, validator

pytestmark = pytest.mark.unit

SCHEMA = "committed-v1.json"
DIGEST = "a" * 64
REVISION_ID = "4c29d3e9-88dd-4aac-a703-859ad82b180b"
DATASET_ID = "5c29d3e9-88dd-4aac-a703-859ad82b180c"


def _committed(**overrides: Any) -> dict[str, Any]:
    """Build a valid ``COMMITTED`` document, with any overrides merged in."""
    document: dict[str, Any] = {
        "schema": "urn:huron:committed:1",
        "revision_id": REVISION_ID,
        "dataset_id": DATASET_ID,
        "revision_number": 1,
        "manifest_sha256": DIGEST,
        "metadata_sha256": DIGEST,
        "file_count": 3,
        "total_bytes": 1024,
        "committed_by": "user:karl",
        "committed_at": "2026-08-30T19:02:41Z",
    }
    return document | overrides


def test_the_schema_itself_is_valid() -> None:
    """The committed schema itself is a valid JSON Schema document."""
    validator(SCHEMA)


def test_a_well_formed_marker_validates() -> None:
    """A marker with every required member, well formed, validates."""
    validate(SCHEMA, _committed())


@pytest.mark.parametrize(
    "member",
    [
        "schema",
        "revision_id",
        "dataset_id",
        "revision_number",
        "manifest_sha256",
        "metadata_sha256",
        "file_count",
        "total_bytes",
        "committed_by",
        "committed_at",
    ],
)
def test_every_required_member_is_required(member: str) -> None:
    """Removing any one required member fails validation."""
    document = _committed()
    del document[member]
    with pytest.raises(ValidationError):
        validate(SCHEMA, document)


def test_unknown_members_are_refused() -> None:
    """A marker carrying a member the schema does not list fails validation."""
    with pytest.raises(ValidationError):
        validate(SCHEMA, _committed(extra="not part of the contract"))


@pytest.mark.parametrize(
    ("member", "value"),
    [
        ("revision_id", "not-a-uuid"),
        ("dataset_id", "not-a-uuid"),
        ("manifest_sha256", DIGEST.upper()),
        ("metadata_sha256", DIGEST.upper()),
        ("manifest_sha256", "too-short"),
    ],
)
def test_digests_and_ids_must_be_well_formed(member: str, value: str) -> None:
    """A malformed digest or identifier fails validation."""
    with pytest.raises(ValidationError):
        validate(SCHEMA, _committed(**{member: value}))


def test_a_malformed_instant_is_refused() -> None:
    """A ``committed_at`` that is not an RFC 3339 instant fails validation."""
    with pytest.raises(ValidationError):
        validate(SCHEMA, _committed(committed_at="yesterday"))
