"""Runtime catalog contracts remain independent of structurally conforming adapters."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import pytest

from huron.core.foundation.clock import Clock
from huron.core.raw.ports import RawStore
from huron.core.metastore import SystemClock
from huron.core.rawstore import PosixRawStore

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def test_raw_storage_conforms_without_inheriting_the_catalog_protocol(tmp_path: Path) -> None:
    """The catalog-facing interface performs independent completion and validated publication."""
    store: RawStore = PosixRawStore(tmp_path)
    assert RawStore not in type(store).__mro__
    store.initialize()
    session = store.root / ".staging/session"
    store.create_staging(session)
    data = b"catalog contract"
    digest = hashlib.sha256(data).hexdigest()
    assert store.write_part(session, "input", [data], offset=0, length=len(data)) == digest
    assert store.finish_file(
        session, "input", "payload/file", expected_size=len(data), expected_sha256=digest
    ) == (len(data), digest)
    store.discard_file(session, "input")
    envelope = session / "envelope"
    documents = {"COMMITTED": b"marker"}
    store.write_document(envelope, "COMMITTED", documents["COMMITTED"])
    store.seal(envelope)
    final = store.root / "organization/revision"
    store.commit_envelope(envelope, final)
    store.verify_envelope(final, [("payload/file", len(data), digest)], documents, sealed=True)
    assert store.read_document(final / "payload/file") == data
    assert store.stat_document(final / "payload/file").st_nlink == 1


def test_clock_conforms_without_inheriting_the_catalog_protocol() -> None:
    """The real clock supplies aware UTC instants through the catalog contract."""
    clock: Clock = SystemClock()
    assert Clock not in type(clock).__mro__
    assert clock.now().utcoffset().total_seconds() == 0
