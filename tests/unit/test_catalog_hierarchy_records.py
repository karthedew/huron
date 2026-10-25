"""Hierarchy entities enforce the same immutable descriptive-update contract."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from huron.core.foundation.errors import PreconditionFailed
from huron.core.hierarchy.errors import SlugImmutable
from huron.core.hierarchy.types import Dataset, Organization, Project

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 9, tzinfo=UTC)
_ENTITIES = (
    Organization(
        id=UUID(int=1),
        slug="observatory",
        title="Original title",
        description="Original description",
        generation=7,
        version=4,
        created_at=_NOW,
    ),
    Project(
        id=UUID(int=2),
        organization_id=UUID(int=1),
        slug="survey",
        title="Original title",
        description="Original description",
        data_classification="restricted",
        generation=7,
        version=4,
        created_at=_NOW,
    ),
    Dataset(
        id=UUID(int=3),
        project_id=UUID(int=2),
        slug="exposures",
        title="Original title",
        description="Original description",
        profile_name="survey",
        profile_version="1.0.0",
        entry_layer="raw",
        lifecycle_state="active",
        generation=7,
        version=4,
        created_at=_NOW,
    ),
)


@pytest.mark.parametrize("entity", _ENTITIES, ids=("organization", "project", "dataset"))
@pytest.mark.parametrize(
    ("title", "description"),
    (("New title", None), (None, "New description"), ("", "")),
)
def test_descriptive_changes_advance_counters_and_preserve_every_other_field(
    entity: Organization | Project | Dataset, title: str | None, description: str | None
) -> None:
    """A successor changes supplied descriptions only, with independent counter increments."""
    successor = entity.describe(
        expected_version=4,
        slug=entity.slug,
        title=title,
        description=description,
    )

    assert successor == replace(
        entity,
        title=entity.title if title is None else title,
        description=entity.description if description is None else description,
        generation=8,
        version=5,
    )
    assert entity.version == 4
    assert entity.generation == 7
    assert entity.title == "Original title"
    assert entity.description == "Original description"


@pytest.mark.parametrize("entity", _ENTITIES, ids=("organization", "project", "dataset"))
@pytest.mark.parametrize("explicit", (False, True))
def test_omitted_or_unchanged_descriptions_return_the_original_entity(
    entity: Organization | Project | Dataset, explicit: bool
) -> None:
    """Omitted fields and explicit current values create no successor or generation."""
    assert (
        entity.describe(
            expected_version=4,
            slug=entity.slug if explicit else None,
            title=entity.title if explicit else None,
            description=entity.description if explicit else None,
        )
        is entity
    )


@pytest.mark.parametrize("entity", _ENTITIES, ids=("organization", "project", "dataset"))
@pytest.mark.parametrize("title", (None, "New title"))
def test_stale_versions_fail_for_changed_and_unchanged_descriptions(
    entity: Organization | Project | Dataset, title: str | None
) -> None:
    """The caller must hold the current version even when the update is a no-op."""
    with pytest.raises(PreconditionFailed, match="expected version 3, current version is 4"):
        entity.describe(expected_version=3, slug=None, title=title, description=None)


@pytest.mark.parametrize("entity", _ENTITIES, ids=("organization", "project", "dataset"))
@pytest.mark.parametrize("expected_version", (3, 4))
def test_slug_changes_fail_before_version_checks(
    entity: Organization | Project | Dataset, expected_version: int
) -> None:
    """Renaming always reports the entity-specific immutable-slug error."""
    kind = type(entity).__name__.lower()
    with pytest.raises(SlugImmutable, match=f"{kind} slugs cannot be changed"):
        entity.describe(
            expected_version=expected_version,
            slug="renamed",
            title=None,
            description=None,
        )
