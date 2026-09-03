"""``IngestSession`` refuses to advance once its lease or its state is spent.

Past the lease's expiry, an in-progress session refuses both to transition
and to renew by heartbeat. A heartbeat is refused once more by a session that
has already reached a terminal state, even with time left on the lease.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from huron.pkg.catalog.errors import IngestSessionExpired
from huron.pkg.catalog.ingest import IngestLease, IngestSession, IngestState

pytestmark = pytest.mark.unit


def _lease(*, expires_at: datetime) -> IngestLease:
    """Build an ``IngestLease`` with arbitrary ids and the given expiry."""
    return IngestLease(
        ingest_id=uuid4(),
        dataset_id=uuid4(),
        revision_id=uuid4(),
        revision_number=1,
        expires_at=expires_at,
    )


def test_transition_refuses_once_the_lease_has_expired() -> None:
    """Past its lease, an uploading session refuses to transition, even to a legal next state."""
    now = datetime.now(UTC)
    session = IngestSession(
        lease=_lease(expires_at=now - timedelta(seconds=1)),
        state=IngestState.UPLOADING,
        manifest_sha256="a" * 64,
    )
    with pytest.raises(IngestSessionExpired, match="has expired"):
        session.transition(IngestState.VERIFYING, now=now)


def test_heartbeat_refuses_once_the_lease_has_expired() -> None:
    """Past its lease, an uploading session refuses a heartbeat renewal too."""
    now = datetime.now(UTC)
    session = IngestSession(
        lease=_lease(expires_at=now - timedelta(seconds=1)),
        state=IngestState.UPLOADING,
        manifest_sha256="a" * 64,
    )
    with pytest.raises(IngestSessionExpired, match="not renewable"):
        session.heartbeat(now=now)


def test_heartbeat_refuses_once_the_session_reached_a_terminal_state() -> None:
    """A committed session refuses a heartbeat renewal even though its lease has not expired."""
    now = datetime.now(UTC)
    session = IngestSession(
        lease=_lease(expires_at=now + timedelta(hours=1)),
        state=IngestState.COMMITTED,
        manifest_sha256="a" * 64,
    )
    with pytest.raises(IngestSessionExpired, match="not renewable"):
        session.heartbeat(now=now)
