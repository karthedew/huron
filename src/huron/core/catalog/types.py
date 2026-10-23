"""Immutable hierarchy entities, their references and versioned descriptive changes."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import TYPE_CHECKING, Self

from huron.core.foundation.errors import PreconditionFailed

from .errors import SlugImmutable

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


class PlatformRoot(Enum):
    """The explicit parent of organizations in the catalog hierarchy."""

    ROOT = "platform"


@dataclass(frozen=True, slots=True)
class DescriptionChange:
    """A versioned descriptive change; None retains fields and empty strings replace them."""

    expected_version: int
    slug: str | None = None
    title: str | None = None
    description: str | None = None


@dataclass(frozen=True, slots=True)
class EntityRef:
    """An entity's stable identity and path-safe slug."""

    id: UUID
    slug: str


@dataclass(frozen=True, slots=True)
class Organization:
    """A tenant with immutable identity and versioned descriptive fields."""

    id: UUID
    slug: str
    title: str
    description: str
    generation: int
    version: int
    created_at: datetime

    def describe(
        self,
        *,
        expected_version: int,
        slug: str | None,
        title: str | None,
        description: str | None,
    ) -> Self:
        """Change descriptive fields while protecting identity and version invariants.

        Args:
            expected_version: The version observed by the caller.
            slug: The current slug or None; renaming is forbidden.
            title: Replacement title or None.
            description: Replacement description or None.

        Returns:
            The current record for a no-op, otherwise its descriptive successor.
        """
        return _describe(self, "organization", expected_version, slug, title, description)


@dataclass(frozen=True, slots=True)
class Project:
    """A classified project owned by one organization."""

    id: UUID
    organization_id: UUID
    slug: str
    title: str
    description: str
    data_classification: str
    generation: int
    version: int
    created_at: datetime

    def describe(
        self,
        *,
        expected_version: int,
        slug: str | None,
        title: str | None,
        description: str | None,
    ) -> Self:
        """Change descriptive fields while protecting identity and version invariants.

        Args:
            expected_version: The version observed by the caller.
            slug: The current slug or None; renaming is forbidden.
            title: Replacement title or None.
            description: Replacement description or None.

        Returns:
            The current record for a no-op, otherwise its descriptive successor.
        """
        return _describe(self, "project", expected_version, slug, title, description)


@dataclass(frozen=True, slots=True)
class Dataset:
    """A stable dataset configuration, independent of each submitted revision."""

    id: UUID
    project_id: UUID
    slug: str
    title: str
    description: str
    profile_name: str
    profile_version: str
    entry_layer: str
    lifecycle_state: str
    generation: int
    version: int
    created_at: datetime

    def describe(
        self,
        *,
        expected_version: int,
        slug: str | None,
        title: str | None,
        description: str | None,
    ) -> Self:
        """Change descriptive fields while protecting identity and version invariants.

        Args:
            expected_version: The version observed by the caller.
            slug: The current slug or None; renaming is forbidden.
            title: Replacement title or None.
            description: Replacement description or None.

        Returns:
            The current record for a no-op, otherwise its descriptive successor.
        """
        return _describe(self, "dataset", expected_version, slug, title, description)


def _describe[ItemT: Organization | Project | Dataset](
    item: ItemT,
    kind: str,
    expected_version: int,
    slug: str | None,
    title: str | None,
    description: str | None,
) -> ItemT:
    """Apply one immutable descriptive update without weakening no-op preconditions.

    Args:
        item: Current record.
        kind: Entity kind for diagnostics.
        expected_version: Required current version.
        slug: Current slug or None.
        title: Replacement title or None.
        description: Replacement description or None.

    Returns:
        The current record or a successor advancing both counters once.

    Raises:
        SlugImmutable: If the caller attempts a rename.
        PreconditionFailed: If the version is stale, including for a no-op.
    """
    if slug is not None and slug != item.slug:
        raise SlugImmutable(f"{kind} slugs cannot be changed")
    if expected_version != item.version:
        raise PreconditionFailed(
            f"expected version {expected_version}, current version is {item.version}"
        )
    next_title = item.title if title is None else title
    next_description = item.description if description is None else description
    if (next_title, next_description) == (item.title, item.description):
        return item
    return replace(
        item,
        title=next_title,
        description=next_description,
        generation=item.generation + 1,
        version=item.version + 1,
    )
