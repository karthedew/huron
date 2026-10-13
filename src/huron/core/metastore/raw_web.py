"""PostgreSQL external catalog mappings and Raw registration acknowledgements."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal
from uuid import UUID

from huron.core.catalog.external import ExternalDataset, target_key
from huron.core.foundation.errors import ResourceNotFound
from huron.core.security.raw_delegation import DelegationTarget

if TYPE_CHECKING:
    from collections.abc import Mapping

    import asyncpg


def _mapping(row: Mapping[str, object] | None) -> ExternalDataset:
    """Decode a persisted mapping through its validated public value.

    Args:
        row: PostgreSQL mapping row, or an absent required mapping.

    Returns:
        Its immutable target and backend identity.

    Raises:
        ResourceNotFound: If the required mapping does not exist.
    """
    if row is None:
        raise ResourceNotFound("no such Raw dataset")
    target = DelegationTarget.model_validate(
        {key: row[key] for key in ("endpoint", "realm", "catalog", "namespace", "name")}
    )
    return ExternalDataset(target, UUID(str(row["dataset_id"])))


class PostgresRawWebStore:
    """One adapter satisfies Catalog mapping and Raw publication persistence ports."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        """Use the application-owned pool.

        Args:
            pool: An open PostgreSQL connection pool.
        """
        self._pool = pool

    async def provisioned_identity(
        self,
        kind: Literal["organization", "project", "dataset"],
        slug: str,
        parent_id: UUID | None,
    ) -> UUID | None:
        """Read trusted deterministic hierarchy identities for interrupted provisioning.

        Args:
            kind: Internal hierarchy level.
            slug: Canonical target-derived internal slug.
            parent_id: Exact parent, absent for an organization.

        Returns:
            The existing identity or None.
        """
        queries = {
            "organization": "SELECT id FROM organizations WHERE slug=$1 AND $2::uuid IS NULL",
            "project": "SELECT id FROM projects WHERE slug=$1 AND organization_id=$2",
            "dataset": "SELECT id FROM datasets WHERE slug=$1 AND project_id=$2",
        }
        value = await self._pool.fetchval(queries[kind], slug, parent_id)
        return UUID(str(value)) if value is not None else None

    async def by_target(self, target: DelegationTarget) -> ExternalDataset | None:
        """Read the exact upstream mapping.

        Args:
            target: Complete upstream identity.

        Returns:
            The mapping or None.

        Raises:
            ResourceNotFound: If the persisted complete identity differs from the target.
        """
        row = await self._pool.fetchrow(
            "SELECT * FROM raw_external_datasets WHERE target_key=$1", target_key(target)
        )
        mapping = _mapping(row) if row is not None else None
        if mapping is not None and mapping.target != target:
            raise ResourceNotFound("no such Raw dataset")
        return mapping

    async def by_dataset(self, dataset_id: UUID) -> ExternalDataset:
        """Resolve an opaque backend dataset.

        Args:
            dataset_id: Backend identity.

        Returns:
            Its immutable mapping.

        """
        row = await self._pool.fetchrow(
            "SELECT * FROM raw_external_datasets WHERE dataset_id=$1", dataset_id
        )
        return _mapping(row)

    async def remember(self, mapping: ExternalDataset) -> ExternalDataset:
        """Insert one immutable mapping, preserving an identical concurrent insertion.

        Args:
            mapping: Verified target and created backend identity.

        Returns:
            The persisted mapping.

        Raises:
            RuntimeError: If the same upstream target resolved to different identities.
        """
        target = mapping.target
        await self._pool.execute(
            """INSERT INTO raw_external_datasets
               (target_key, endpoint, realm, catalog, namespace, name, dataset_id)
               VALUES ($1,$2,$3,$4,$5,$6,$7) ON CONFLICT (target_key) DO NOTHING""",
            target_key(target),
            target.endpoint,
            target.realm,
            target.catalog,
            list(target.namespace),
            target.name,
            mapping.dataset_id,
        )
        stored = await self.by_target(target)
        if stored != mapping:
            raise RuntimeError("external target mapping conflicts with its created identity")
        return stored

    async def registered(self, revision_id: UUID) -> bool:
        """Read a durable registration acknowledgement.

        Args:
            revision_id: Committed revision identity.

        Returns:
            Whether registration has been acknowledged.
        """
        return bool(
            await self._pool.fetchval(
                "SELECT EXISTS(SELECT 1 FROM raw_catalog_publications WHERE revision_id=$1)",
                revision_id,
            )
        )

    async def acknowledge(self, revision_id: UUID) -> None:
        """Record acknowledgement exactly once.

        Args:
            revision_id: Committed revision identity checked by the workflow.
        """
        await self._pool.execute(
            "INSERT INTO raw_catalog_publications (revision_id) VALUES ($1) ON CONFLICT DO NOTHING",
            revision_id,
        )

    async def revision_ids(
        self, dataset_id: UUID, *, before: int | None, limit: int
    ) -> tuple[UUID, ...]:
        """Page committed revisions in descending revision-number order.

        Args:
            dataset_id: Authorized dataset identity.
            before: Exclusive revision-number cursor.
            limit: Maximum returned rows.

        Returns:
            Immutable revision identifiers.
        """
        rows = await self._pool.fetch(
            """SELECT id FROM dataset_revisions WHERE dataset_id=$1
               AND ($2::bigint IS NULL OR revision_number < $2)
               ORDER BY revision_number DESC LIMIT $3""",
            dataset_id,
            before,
            limit,
        )
        return tuple(UUID(str(row["id"])) for row in rows)
