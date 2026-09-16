"""The frozen values declared in ``stores/ports.py`` and the package's public surface.

``HierarchyWriter`` and ``HierarchyStore`` are bare ``Protocol`` bodies with
no behavior of their own to exercise here; their contracts are pinned by the
stores that implement them.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest

from huron.core.foundation.retry import IdempotencyClaim, Replay
from huron.core.raw.types import LedgerEntry
from huron.core.catalog.types import Window
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
