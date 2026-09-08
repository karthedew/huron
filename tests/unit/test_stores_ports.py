"""The frozen values declared in ``stores/ports.py`` and the package's public surface.

``HierarchyWriter`` and ``HierarchyStore`` are bare ``Protocol`` bodies with
no behavior of their own to exercise here; their contracts are pinned by the
stores that implement them.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest

import huron.pkg.metastore as stores_package
from huron.pkg.catalog.persistence import IdempotencyClaim, LedgerEntry, Replay, Window
from tests.unit.support import ingest_file

pytestmark = pytest.mark.unit


def test_window_idempotency_claim_and_replay_reject_attribute_assignment() -> None:
    """``Window``, ``IdempotencyClaim`` and ``Replay`` are frozen dataclasses."""
    window = Window(items=[1, 2], has_more=True)
    claim = IdempotencyClaim(principal="user:alice", key="retry-1", request_sha256="a" * 64)
    replay = Replay(kind="organization", resource_id=uuid4())

    with pytest.raises(FrozenInstanceError):
        window.items = []

    with pytest.raises(FrozenInstanceError):
        claim.key = "retry-2"

    with pytest.raises(FrozenInstanceError):
        replay.kind = "project"


def test_ledger_entry_pairs_a_file_with_the_session_it_belongs_to() -> None:
    """``LedgerEntry`` holds one ingest file beside the id of its owning session."""
    session_id = uuid4()
    file = ingest_file()
    entry = LedgerEntry(ingest_id=session_id, file=file)
    assert entry.ingest_id == session_id
    assert entry.file is file


def test_stores_package_exports_the_hierarchy_port_and_its_values() -> None:
    """The package's public surface names every hierarchy-port symbol a consumer imports."""
    assert {
        "AuditEvent",
        "IdempotencyClaim",
        "LedgerEntry",
        "Replay",
        "SystemClock",
        "Visibility",
        "Window",
    } <= set(stores_package.__all__)
