"""The lake audit log's constraints and its in-memory transaction half."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from huron.core.lake.audit import AUDIT_REASON_MAX, AuditObject

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence

    from huron.core.lake.audit import AuditAction, AuditEntry
    from huron.core.metastore.lake.memory import LakeBuffer

_ACTOR_MAX: Final = 160
_OBJECT_ID_MAX: Final = 255


def audit_log_violation(
    entry: AuditEntry, vocabulary: Collection[tuple[AuditAction, AuditObject]]
) -> str | None:
    """Name the first `lake.audit_log` constraint that the entry's row would violate.

    Args:
        entry: The entry about to be staged.
        vocabulary: The seeded `(action, object_type)` pairs the row must reference.

    Returns:
        The PostgreSQL constraint name, or None when the row is acceptable.
    """
    holds = {
        "audit_log_vocabulary": (entry.event.ACTION, entry.event.OBJECT) in vocabulary,
        "audit_log_collection_has_catalog": entry.event.OBJECT is not AuditObject.COLLECTION
        or entry.catalog_id is not None,
        "audit_log_actor_check": 1 <= len(entry.actor) <= _ACTOR_MAX,
        "audit_log_object_id_check": 1 <= len(entry.object_id) <= _OBJECT_ID_MAX,
        "audit_log_reason_check": entry.reason is None
        or 1 <= len(entry.reason) <= AUDIT_REASON_MAX,
    }
    return next((constraint for constraint, held in holds.items() if not held), None)


class InMemoryAudit:
    """The audit writer half of an open in-memory transaction."""

    buffer: LakeBuffer

    async def append_audit(self, entries: Sequence[AuditEntry]) -> None:
        """Stage entries in call order, to be numbered when the transaction commits.

        Args:
            entries: Facts about changes made in the same transaction.

        Raises:
            ValueError: If no entry is given.
        """
        if not entries:
            raise ValueError("An audited change must append at least one entry")
        self.buffer.audit_log.append(entries)
