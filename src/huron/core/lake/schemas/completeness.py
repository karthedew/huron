"""Re-validate a catalog's collections after its schema assignment changes."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from huron.core.lake.audit import Action, AuditWriter, ObjectType
from huron.core.lake.collections.models import State
from huron.pkg.canonical import document_sha256
from huron.schema.composition import SchemaIncompatible
from huron.schema.validator import Validator

if TYPE_CHECKING:
    from huron.core.lake.catalogs.models import Catalog
    from huron.core.lake.collections.models import Collection
    from huron.core.lake.schemas.registry import SchemaResolver
    from huron.core.lake.transaction import Transaction
    from huron.core.security.rbac import Actor
    from huron.pkg.clock import Clock

__all__ = ["Completeness", "RecomputeResult"]


@dataclass(frozen=True, slots=True)
class RecomputeResult:
    """How many collections ended each state, and how many changed."""

    active: int
    incomplete: int
    changed: int

    def as_dict(self) -> dict[str, int]:
        """Render for the API."""
        return {"active": self.active, "incomplete": self.incomplete, "changed": self.changed}


class Completeness:
    """Moves settled collections between ``active`` and ``incomplete``."""

    def __init__(self, resolver: SchemaResolver, clock: Clock) -> None:
        self._resolver = resolver
        self._clock = clock

    async def recompute(self, tx: Transaction, actor: Actor, catalog: Catalog) -> RecomputeResult:
        """Validate every settled collection of ``catalog`` against its current schema.

        Each row is re-read under its row lock, so a commit or metadata change that lands while
        the catalog is being recomputed is never overwritten.
        """
        settled = await tx.collections.list_in_catalog(catalog.id, {State.ACTIVE, State.INCOMPLETE})
        validators: dict[str, Validator] = {}
        counts = {State.ACTIVE: 0, State.INCOMPLETE: 0}
        changed = 0
        for listed in settled:
            collection = await tx.collections.lock(listed.id)
            if collection is None or not collection.settled:
                continue
            target = await self._target_state(tx, catalog, collection, validators)
            counts[target] += 1
            if target is not collection.state:
                changed += 1
                await self._move(tx, actor, collection, target)
        return RecomputeResult(counts[State.ACTIVE], counts[State.INCOMPLETE], changed)

    async def _target_state(
        self,
        tx: Transaction,
        catalog: Catalog,
        collection: Collection,
        validators: dict[str, Validator],
    ) -> State:
        try:
            document = await self._resolver.for_collection(
                tx.schemas, catalog.schema_id, collection.schema_override
            )
        except SchemaIncompatible:
            return State.INCOMPLETE
        key = document_sha256(document)
        validator = validators.get(key)
        if validator is None:
            validator = validators[key] = Validator(document)
        return State.ACTIVE if not validator.validate(collection.metadata) else State.INCOMPLETE

    async def _move(
        self, tx: Transaction, actor: Actor, collection: Collection, target: State
    ) -> None:
        now = self._clock.now()
        moved = replace(collection, state=target, version=collection.version + 1, updated_at=now)
        await tx.collections.update(moved)
        action = (
            Action.COLLECTION_MARK_ACTIVE
            if target is State.ACTIVE
            else Action.COLLECTION_MARK_INCOMPLETE
        )
        detail: dict[str, Any] = {"version": moved.version}
        await AuditWriter(tx.audit, self._clock).record(
            actor,
            action,
            ObjectType.COLLECTION,
            collection.id,
            catalog_id=collection.catalog_id,
            detail=detail,
        )
