"""Canonical JSON, identifiers, clocks and hashing."""

import hashlib
import io
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import rfc8785

from huron.pkg.canonical import NotCanonicalizable, canonical_bytes, document_sha256
from huron.pkg.clock import FrozenClock, SystemClock
from huron.pkg.hashing import EMPTY_SHA256, sha256_copy, sha256_file
from huron.pkg.identifiers import new_id, parse_id


def test_canonical_bytes_ignore_key_order() -> None:
    assert canonical_bytes({"b": 1, "a": [1, 2]}) == canonical_bytes({"a": [1, 2], "b": 1})
    assert canonical_bytes({"b": 1, "a": 2}) == b'{"a":2,"b":1}'
    assert document_sha256({"a": 1}) == hashlib.sha256(b'{"a":1}').hexdigest()


def test_canonical_bytes_write_integers_of_any_size_with_their_digits() -> None:
    assert canonical_bytes({"fill": -(10**31)}) == b'{"fill":-10000000000000000000000000000000}'
    assert (
        canonical_bytes([2**53, -(2**53), 2**64])
        == b"[9007199254740992,-9007199254740992,18446744073709551616]"
    )
    assert document_sha256({"n": 2**63}) == hashlib.sha256(b'{"n":9223372036854775808}').hexdigest()


DOCUMENTS_RFC_8785_ACCEPTS = [
    {},
    [],
    {"\u20ac": 1, "\r": 2, "\U0001f600": 3, "a": [True, False, None]},
    {"n": [2**53 - 1, -(2**53) + 1, 0, -0.0, 1e21, 1e-7, 0.1, -1e31, 1.5]},
    {"s": 'quote " backslash \\ tab \t control \u0001 \u00e9'},
    ("tuple", 1),
]


@pytest.mark.parametrize("document", DOCUMENTS_RFC_8785_ACCEPTS)
def test_canonical_bytes_match_rfc_8785_inside_its_integer_domain(document: object) -> None:
    assert canonical_bytes(document) == rfc8785.dumps(document)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ({"x": float("nan")}, "nan is not a JSON number"),
        ([float("inf")], "inf is not a JSON number"),
        ({1: "a"}, "object keys must be strings"),
        ({"\ud800": 1}, "an object key holds a lone surrogate"),
        (["\udfff"], "a string holds a lone surrogate"),
        ({"when": datetime(2026, 1, 1)}, "datetime is not a JSON value"),
        ({"n": 10**5000}, "an integer has too many digits"),
    ],
)
def test_canonical_bytes_refuse_what_json_cannot_hold(document: object, message: str) -> None:
    with pytest.raises(NotCanonicalizable, match=message):
        canonical_bytes(document)


def test_new_ids_are_version_seven_and_ordered() -> None:
    first, second = new_id(), new_id()
    assert first.version == 7
    assert first < second or first.time <= second.time
    assert parse_id(str(first)) == first
    with pytest.raises(ValueError):
        parse_id("not-a-uuid")
    assert isinstance(first, uuid.UUID)


def test_frozen_clock_moves_only_when_advanced() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    clock = FrozenClock(start)
    assert clock.now() == start
    clock.advance(timedelta(minutes=5))
    assert clock.now() == start + timedelta(minutes=5)
    with pytest.raises(ValueError):
        FrozenClock(datetime(2026, 1, 1))


def test_system_clock_is_aware() -> None:
    assert SystemClock().now().tzinfo is UTC


def test_sha256_copy_of_empty_stream() -> None:
    target = io.BytesIO()
    assert sha256_copy(io.BytesIO(b""), target) == (0, EMPTY_SHA256)
    assert target.getvalue() == b""


def test_sha256_copy_streams_in_chunks(tmp_path: Path) -> None:
    data = b"abc" * 1000
    target = io.BytesIO()
    expected = hashlib.sha256(data).hexdigest()
    assert sha256_copy(io.BytesIO(data), target, chunk=7) == (3000, expected)
    assert target.getvalue() == data
    path = tmp_path / "f"
    path.write_bytes(data)
    assert sha256_file(path, chunk=11) == (3000, expected)
