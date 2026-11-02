"""Write audit entries inside the transaction that makes the change."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from huron.core.lake.audit.models import Action, AuditEntry, ObjectType

if TYPE_CHECKING:
    import uuid

    from huron.core.lake.audit.ports import AuditStore
    from huron.core.security.rbac import Actor
    from huron.pkg.clock import Clock

__all__ = ["AuditWriter"]


class AuditWriter:
    """Builds entries with the clock and the actor and appends them."""

    def __init__(self, store: AuditStore, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    async def record(
        self,
        actor: Actor | str,
        action: Action,
        object_type: ObjectType,
        object_id: uuid.UUID | None,
        *,
        catalog_id: uuid.UUID | None = None,
        organization_id: uuid.UUID | None = None,
        detail: dict[str, Any] | None = None,
    ) -> AuditEntry:
        """Append one entry and return it."""
        subject = actor if isinstance(actor, str) else actor.subject
        entry = AuditEntry(
            at=self._clock.now(),
            actor=subject,
            action=action,
            object_type=object_type,
            object_id=object_id,
            catalog_id=catalog_id,
            organization_id=organization_id,
            detail=dict(detail or {}),
        )
        return await self._store.write(entry)
