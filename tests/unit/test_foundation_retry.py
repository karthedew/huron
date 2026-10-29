"""Request fingerprints and the receipt kinds that idempotency records may hold.

Idempotency records keep these digests across restarts and deployments, so
the encoding itself is the contract: the operation and its fields, joined
by NUL and hashed as UTF-8, rendered as lower-case hexadecimal SHA-256.
"""

from __future__ import annotations

import hashlib
import re
from typing import get_args, get_type_hints
from uuid import UUID

import pytest

from huron.core.foundation.retry import Replay, request_sha256

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("operation", "parts", "encoded"),
    [
        pytest.param(
            "organization",
            ("astro", "Astro", ""),
            b"organization\x00astro\x00Astro\x00",
            id="trailing-empty-field",
        ),
        pytest.param(
            "raw-web", ("dataset", "café"), b"raw-web\x00dataset\x00caf\xc3\xa9", id="utf-8"
        ),
        pytest.param("revision", (), b"revision", id="operation-only"),
    ],
)
def test_a_fingerprint_hashes_the_nul_joined_utf8_operation_and_fields(
    operation: str, parts: tuple[str, ...], encoded: bytes
) -> None:
    """The digest is the lower-case hex SHA-256 of the operation and fields joined by NUL."""
    digest = request_sha256(operation, *parts)

    assert digest == hashlib.sha256(encoded).hexdigest()
    assert re.fullmatch("[0-9a-f]{64}", digest)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        pytest.param(("dataset", "ab", "c"), ("dataset", "a", "bc"), id="field-boundary"),
        pytest.param(("dataset", "a", "b"), ("dataset", "b", "a"), id="field-order"),
        pytest.param(("dataset", "a"), ("dataset", "a", ""), id="added-empty-field"),
        pytest.param(("dataset",), ("dataset", ""), id="no-field-or-one-empty-field"),
        pytest.param(("project", "a"), ("dataset", "a"), id="operation"),
    ],
)
def test_requests_that_differ_in_fields_or_operation_have_different_fingerprints(
    first: tuple[str, ...], second: tuple[str, ...]
) -> None:
    """A moved field boundary, a reordering, an added empty field or another operation all count."""
    assert request_sha256(first[0], *first[1:]) != request_sha256(second[0], *second[1:])


def test_replay_kinds_cover_the_lake_admin_creating_calls() -> None:
    """Catalog, schema and key creation receipts join the legacy hierarchy kinds, and only those."""
    # The receipt id type is imported for type checking only.
    kinds = set(get_args(get_type_hints(Replay, localns={"UUID": UUID})["kind"]))
    assert kinds == {
        "organization",
        "project",
        "dataset",
        "catalog",
        "metadata_schema",
        "signing_key",
    }
