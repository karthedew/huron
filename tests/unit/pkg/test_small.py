"""Canonical JSON, identifiers, clocks and hashing."""

import hashlib
import io
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from huron.pkg.canonical import canonical_bytes, document_sha256
from huron.pkg.clock import FrozenClock, SystemClock
from huron.pkg.hashing import EMPTY_SHA256, sha256_copy, sha256_file
from huron.pkg.identifiers import new_id, parse_id


def test_canonical_bytes_ignore_key_order() -> None:
    assert canonical_bytes({"b": 1, "a": [1, 2]}) == canonical_bytes({"a": [1, 2], "b": 1})
    assert canonical_bytes({"b": 1, "a": 2}) == b'{"a":2,"b":1}'
    assert document_sha256({"a": 1}) == hashlib.sha256(b'{"a":1}').hexdigest()


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
