"""Transactional staging of the lake's append-only audit rows."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.lake.audit import AuditObject

if TYPE_CHECKING:
    from collections.abc import Sequence

    from huron.core.lake.audit import AuditEntry
    from huron.core.metastore.lake.memory import LakeBuffer, LakeTables


class InMemoryAudit:
    """The audit writer half of an open in-memory transaction."""

    buffer: LakeBuffer
    _tables: LakeTables

    async def append_audit(self, entries: Sequence[AuditEntry]) -> None:
        """Validate and stage a complete batch in its supplied order.

        Args:
            entries: Non-empty facts to commit with the transaction's changes.

        Raises:
            ValueError: If the batch is empty.
            IntegrityViolation: If a row violates a persisted constraint.
        """
        from huron.core.metastore.lake.memory import IntegrityViolation

        self.buffer.check_open()
        if not entries:
            raise ValueError("An audit batch must not be empty")
        for entry in entries:
            constraints = {
                "audit_log_vocabulary": (entry.event.ACTION, entry.event.OBJECT)
                in self._tables.audit_actions,
                "audit_log_collection_has_catalog": entry.event.OBJECT != AuditObject.COLLECTION
                or entry.catalog_id is not None,
                "audit_log_actor_check": 1 <= len(entry.actor) <= 160,
                "audit_log_object_id_check": 1 <= len(entry.object_id) <= 255,
                "audit_log_reason_check": entry.reason is None or 1 <= len(entry.reason) <= 1000,
            }
            for constraint, valid in constraints.items():
                if not valid:
                    raise IntegrityViolation(constraint)
        self.buffer.audit_entries.extend(entries)
