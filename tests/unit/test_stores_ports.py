"""Shared paging and retry values reject mutation."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest

from huron.core.foundation.paging import Window
from huron.core.foundation.retry import IdempotencyClaim, Replay

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
