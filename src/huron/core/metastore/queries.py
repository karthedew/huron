"""Private typed execution for fixed discoverable catalog projections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from huron.core.catalog.types import Dataset, Organization, PlatformRoot, Project
from huron.core.foundation.errors import ResourceNotFound
from huron.core.foundation.paging import Window

from . import rows

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID

    import asyncpg

    from huron.core.security.rules import Visibility


@dataclass(frozen=True)
class _Projection[ItemT]:
    """A trusted SQL selection and its explicit record decoder."""

    selection: str
    decode: Callable[[asyncpg.Record], ItemT]
    kind: str


_ORGANIZATIONS = _Projection[Organization](
    """SELECT o.id, o.slug, o.title, o.description, o.generation, o.version, o.created_at
    FROM organizations o
    WHERE ($1::boolean OR o.id = ANY($2::uuid[])
      OR EXISTS (SELECT 1 FROM projects p
                 WHERE p.organization_id = o.id AND p.id = ANY($3::uuid[]))
      OR EXISTS (SELECT 1 FROM datasets d JOIN projects p ON p.id = d.project_id
                 WHERE p.organization_id = o.id AND d.id = ANY($4::uuid[])))""",
    rows.organization,
    "organization",
)
_PROJECTS = _Projection[Project](
    """SELECT p.id, p.organization_id, p.slug, p.title, p.description,
              p.classification_default, p.generation, p.version, p.created_at
    FROM projects p
    WHERE ($1::boolean OR p.id = ANY($3::uuid[])
      OR EXISTS (SELECT 1 FROM datasets d
                 WHERE d.project_id = p.id AND d.id = ANY($4::uuid[])))
      AND $2::uuid[] IS NOT NULL""",
    rows.project,
    "project",
)
_DATASETS = _Projection[Dataset](
    """SELECT d.id, d.project_id, d.slug, d.title, d.description, d.profile_name,
              d.profile_version, d.entry_layer, d.lifecycle_state,
              d.generation, d.version, d.created_at
    FROM datasets d
    WHERE ($1::boolean OR d.project_id = ANY($3::uuid[]) OR d.id = ANY($4::uuid[]))
      AND $2::uuid[] IS NOT NULL""",
    rows.dataset,
    "dataset",
)


class _PostgresCollection[ItemT, ParentT]:
    """Required lookup and bounded keyset execution for a fixed visible selection."""

    def __init__(
        self, pool: asyncpg.Pool, projection: _Projection[ItemT], parent_column: str | None
    ) -> None:
        """Bind trusted selection and parent column once at adapter construction.

        Args:
            pool: The connection pool owned by application wiring.
            projection: Fixed SQL and explicit decoder for this collection.
            parent_column: Fixed parent column, absent at the platform root.
        """
        self._pool = pool
        self._projection = projection
        self._parent_column = parent_column

    async def get(self, resource_id: UUID, visibility: Visibility) -> ItemT:
        """Return an admitted record or raise the same error as an absent record.

        Args:
            resource_id: The exact entity identifier.
            visibility: Discovery rights evaluated inside SQL.

        Returns:
            The decoded entity.

        Raises:
            ResourceNotFound: If the selection admits no matching row.
        """
        row = await self._pool.fetchrow(
            f"SELECT * FROM ({self._projection.selection}) visible WHERE id = $5 LIMIT 1",
            *_visibility_parameters(visibility),
            resource_id,
        )
        if row is None:
            raise ResourceNotFound(f"{self._projection.kind} does not exist: {resource_id}")
        return self._projection.decode(row)

    async def browse(
        self,
        parent: ParentT,
        visibility: Visibility,
        *,
        limit: int,
        after: tuple[str, UUID] | None,
    ) -> Window[ItemT]:
        """Fetch at most limit plus one visible records in C-collated cursor order.

        Args:
            parent: The owning identifier or platform root.
            visibility: Discovery rights evaluated before LIMIT.
            limit: Maximum returned records.
            after: Exclusive slug and UUID cursor.

        Returns:
            A typed page and visible further-row flag.
        """
        after_slug, after_id = after if after is not None else (None, None)
        parent_filter = (
            f"{self._parent_column} = $5::uuid"
            if self._parent_column is not None
            else "$5::uuid IS NULL"
        )
        fetched = await self._pool.fetch(
            f"""SELECT * FROM ({self._projection.selection}) visible
            WHERE {parent_filter}
              AND ($6::text IS NULL OR (slug COLLATE "C", id) > ($6 COLLATE "C", $7::uuid))
            ORDER BY slug COLLATE "C", id LIMIT $8""",
            *_visibility_parameters(visibility),
            None if isinstance(parent, PlatformRoot) else parent,
            after_slug,
            after_id,
            limit + 1,
        )
        return Window(
            items=[self._projection.decode(row) for row in fetched[:limit]],
            has_more=len(fetched) > limit,
        )


def _visibility_parameters(
    visibility: Visibility,
) -> tuple[bool, list[UUID], list[UUID], list[UUID]]:
    """Bind the same visibility facts to each trusted projection.

    Args:
        visibility: The caller's current discovery facts.

    Returns:
        Unrestricted admission and organization, project, dataset grants.
    """
    return (
        visibility.unrestricted,
        list(visibility.organization_ids),
        list(visibility.project_ids),
        list(visibility.dataset_ids),
    )
