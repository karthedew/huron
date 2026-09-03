"""Direct unit tests for ``HierarchyRepository``'s write paths and listing snapshots.

Idempotent replay, slug conflicts, optimistic-concurrency preconditions,
the release tag's two independent guards (the in-memory index and the raw
store's own once-only write), and each ``list_*`` method's ordering,
scoping and copy-on-read isolation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from huron.pkg.catalog.errors import (
    ClassificationUnknown,
    IdempotencyKeyReused,
    PreconditionFailed,
    ResourceNotFound,
    SlugImmutable,
    TagExists,
)
from huron.pkg.catalog.paths import release_tag_file
from huron.pkg.rawstore import PosixRawStore
from huron.service.api.errors import SlugExists
from huron.service.api.repository import HierarchyRepository, RevisionSeed, _fingerprint

if TYPE_CHECKING:
    from uuid import UUID

pytestmark = pytest.mark.unit


def _repository(tmp_path: Path) -> HierarchyRepository:
    """Build a ``HierarchyRepository`` at ``tmp_path`` with only "open" classification allowed."""
    return HierarchyRepository(
        PosixRawStore(str(tmp_path / "raw")), classification_vocabulary=("open",)
    )


def _hierarchy(repository: HierarchyRepository) -> tuple[UUID, UUID, UUID]:
    """Create one organization/project/dataset and return their ids."""
    organization = repository.create_organization(
        slug="astro", title="Astro", description="", idempotency_key="org-1"
    )
    project = repository.create_project(
        organization.id,
        slug="sims",
        title="Sims",
        description="",
        data_classification="open",
        idempotency_key="proj-1",
    )
    dataset = repository.create_dataset(
        project.id,
        slug="run-0001",
        title="Run 1",
        description="",
        profile_name="mcnp-run",
        profile_version="1.0",
        idempotency_key="ds-1",
    )
    return organization.id, project.id, dataset.id


# -- create_organization ------------------------------------------------


def test_create_organization_replays_an_identical_request(tmp_path: Path) -> None:
    """Replaying ``create_organization`` with the same key returns the identical object."""
    repository = _repository(tmp_path)
    first = repository.create_organization(
        slug="astro", title="Astro", description="", idempotency_key="k1"
    )
    second = repository.create_organization(
        slug="astro", title="Astro", description="", idempotency_key="k1"
    )
    assert second is first


def test_create_organization_rejects_reuse_of_a_key_with_different_arguments(
    tmp_path: Path,
) -> None:
    """Reusing an idempotency key with a different title raises ``IdempotencyKeyReused``."""
    repository = _repository(tmp_path)
    repository.create_organization(
        slug="astro", title="Astro", description="", idempotency_key="k1"
    )
    with pytest.raises(IdempotencyKeyReused):
        repository.create_organization(
            slug="astro", title="Renamed", description="", idempotency_key="k1"
        )


def test_create_organization_rejects_a_duplicate_slug(tmp_path: Path) -> None:
    """A second organization with the same slug but a new idempotency key raises ``SlugExists``."""
    repository = _repository(tmp_path)
    repository.create_organization(
        slug="astro", title="Astro", description="", idempotency_key="k1"
    )
    with pytest.raises(SlugExists, match="organization slug already exists"):
        repository.create_organization(
            slug="astro", title="Astro Again", description="", idempotency_key="k2"
        )


def test_create_organization_rejects_a_replay_whose_stored_result_has_the_wrong_type(
    tmp_path: Path,
) -> None:
    """A stored idempotency result of the wrong type raises ``RuntimeError`` instead of trust.

    Each call site replays into its own type; a stored result of any other
    type means the idempotency store itself was corrupted, and every call
    site guards against trusting it.
    """
    repository = _repository(tmp_path)
    fingerprint = _fingerprint("organization", "astro", "Astro", "")
    repository._idempotency["k1"] = (fingerprint, object())

    with pytest.raises(RuntimeError, match="unexpected result type"):
        repository.create_organization(
            slug="astro", title="Astro", description="", idempotency_key="k1"
        )


# -- create_project -------------------------------------------------------


def test_create_project_replays_an_identical_request(tmp_path: Path) -> None:
    """Replaying ``create_project`` with the same idempotency key returns the identical object."""
    repository = _repository(tmp_path)
    organization_id, _, _ = _hierarchy(repository)
    first = repository.create_project(
        organization_id,
        slug="second",
        title="Second",
        description="",
        data_classification="open",
        idempotency_key="k1",
    )
    second = repository.create_project(
        organization_id,
        slug="second",
        title="Second",
        description="",
        data_classification="open",
        idempotency_key="k1",
    )
    assert second is first


def test_create_project_rejects_a_duplicate_slug(tmp_path: Path) -> None:
    """A second project with an existing slug in the same organization raises ``SlugExists``."""
    repository = _repository(tmp_path)
    organization_id, _, _ = _hierarchy(repository)
    with pytest.raises(SlugExists, match="project slug already exists"):
        repository.create_project(
            organization_id,
            slug="sims",
            title="Sims Again",
            description="",
            data_classification="open",
            idempotency_key="k2",
        )


def test_create_project_accepts_a_classification_in_the_configured_vocabulary(
    tmp_path: Path,
) -> None:
    """A classification listed in the configured vocabulary is accepted and stored."""
    repository = _repository(tmp_path)
    organization_id, _, _ = _hierarchy(repository)
    project = repository.create_project(
        organization_id,
        slug="second",
        title="Second",
        description="",
        data_classification="open",
        idempotency_key="k2",
    )
    assert project.data_classification == "open"


def test_create_project_rejects_a_classification_outside_the_configured_vocabulary(
    tmp_path: Path,
) -> None:
    """A classification outside the configured vocabulary raises ``ClassificationUnknown``."""
    repository = _repository(tmp_path)
    organization_id, _, _ = _hierarchy(repository)
    with pytest.raises(ClassificationUnknown):
        repository.create_project(
            organization_id,
            slug="second",
            title="Second",
            description="",
            data_classification="top-secret",
            idempotency_key="k2",
        )


def test_create_project_with_an_empty_vocabulary_refuses_every_classification(
    tmp_path: Path,
) -> None:
    """With an empty classification vocabulary, even a plausible classification is refused."""
    repository = HierarchyRepository(
        PosixRawStore(str(tmp_path / "raw")), classification_vocabulary=()
    )
    organization = repository.create_organization(
        slug="astro", title="Astro", description="", idempotency_key="org-1"
    )
    with pytest.raises(ClassificationUnknown):
        repository.create_project(
            organization.id,
            slug="sims",
            title="Sims",
            description="",
            data_classification="open",
            idempotency_key="proj-1",
        )


# -- create_dataset ---------------------------------------------------------


def test_create_dataset_replays_an_identical_request(tmp_path: Path) -> None:
    """Replaying ``create_dataset`` with the same idempotency key returns the identical object."""
    repository = _repository(tmp_path)
    _, project_id, _ = _hierarchy(repository)
    first = repository.create_dataset(
        project_id,
        slug="second",
        title="Second",
        description="",
        profile_name="mcnp-run",
        profile_version="1.0",
        idempotency_key="k1",
    )
    second = repository.create_dataset(
        project_id,
        slug="second",
        title="Second",
        description="",
        profile_name="mcnp-run",
        profile_version="1.0",
        idempotency_key="k1",
    )
    assert second is first


def test_create_dataset_rejects_a_duplicate_slug(tmp_path: Path) -> None:
    """A second dataset with an existing slug in the same project raises ``SlugExists``."""
    repository = _repository(tmp_path)
    _, project_id, _ = _hierarchy(repository)
    with pytest.raises(SlugExists, match="dataset slug already exists"):
        repository.create_dataset(
            project_id,
            slug="run-0001",
            title="Run 1 Again",
            description="",
            profile_name="mcnp-run",
            profile_version="1.0",
            idempotency_key="k2",
        )


# -- patch_dataset ------------------------------------------------------


def test_patch_dataset_rejects_a_slug_change(tmp_path: Path) -> None:
    """``patch_dataset`` refuses to change the slug, raising ``SlugImmutable``."""
    repository = _repository(tmp_path)
    _, _, dataset_id = _hierarchy(repository)
    with pytest.raises(SlugImmutable):
        repository.patch_dataset(
            dataset_id, expected_version=1, slug="renamed", title=None, description=None
        )


def test_patch_dataset_rejects_a_stale_expected_version(tmp_path: Path) -> None:
    """``patch_dataset`` refuses a stale ``expected_version``, raising ``PreconditionFailed``."""
    repository = _repository(tmp_path)
    _, _, dataset_id = _hierarchy(repository)
    with pytest.raises(PreconditionFailed):
        repository.patch_dataset(
            dataset_id, expected_version=99, slug=None, title="New Title", description=None
        )


# -- create_release / resolve_release ------------------------------------


def test_create_release_replays_an_identical_request(tmp_path: Path) -> None:
    """Replaying ``create_release`` with the same idempotency key returns the identical object."""
    repository = _repository(tmp_path)
    _, _, dataset_id = _hierarchy(repository)
    repository.register_revision(
        RevisionSeed(id=uuid4(), dataset_id=dataset_id, number=1, manifest_sha256="a" * 64)
    )
    first = repository.create_release(
        dataset_id,
        tag="v1",
        revision_number=1,
        title=None,
        created_by="alice",
        idempotency_key="k1",
    )
    second = repository.create_release(
        dataset_id,
        tag="v1",
        revision_number=1,
        title=None,
        created_by="alice",
        idempotency_key="k1",
    )
    assert second is first


def test_create_release_rejects_a_duplicate_tag(tmp_path: Path) -> None:
    """A second release with an already-used tag raises ``TagExists`` under a new key too."""
    repository = _repository(tmp_path)
    _, _, dataset_id = _hierarchy(repository)
    repository.register_revision(
        RevisionSeed(id=uuid4(), dataset_id=dataset_id, number=1, manifest_sha256="a" * 64)
    )
    repository.create_release(
        dataset_id,
        tag="v1",
        revision_number=1,
        title=None,
        created_by="alice",
        idempotency_key="k1",
    )
    with pytest.raises(TagExists):
        repository.create_release(
            dataset_id,
            tag="v1",
            revision_number=1,
            title=None,
            created_by="alice",
            idempotency_key="k2",
        )


def test_create_release_translates_a_raw_store_collision_into_tag_exists(
    tmp_path: Path,
) -> None:
    """With the in-memory release index entry dropped, the tag still raises ``TagExists``.

    The in-memory index and the raw store's once-only write are two
    independent guards against the same race; dropping the in-memory entry
    while the tag file on disk survives proves the second guard still
    refuses the write on its own.
    """
    repository = _repository(tmp_path)
    _, _, dataset_id = _hierarchy(repository)
    repository.register_revision(
        RevisionSeed(id=uuid4(), dataset_id=dataset_id, number=1, manifest_sha256="a" * 64)
    )
    repository.create_release(
        dataset_id,
        tag="v1",
        revision_number=1,
        title=None,
        created_by="alice",
        idempotency_key="k1",
    )
    del repository.releases[(dataset_id, "v1")]

    with pytest.raises(TagExists):
        repository.create_release(
            dataset_id,
            tag="v1",
            revision_number=1,
            title=None,
            created_by="alice",
            idempotency_key="k2",
        )


def test_resolve_release_raises_for_an_unknown_tag(tmp_path: Path) -> None:
    """``resolve_release`` raises ``ResourceNotFound`` for a tag that was never created."""
    repository = _repository(tmp_path)
    _, _, dataset_id = _hierarchy(repository)
    with pytest.raises(ResourceNotFound):
        repository.resolve_release(dataset_id, "does-not-exist")


def test_create_release_persists_a_tag_document_with_no_withdrawal_keys(
    tmp_path: Path,
) -> None:
    """A release's tag document on disk has exactly these keys and no fields for withdrawal."""
    repository = _repository(tmp_path)
    organization_id, project_id, dataset_id = _hierarchy(repository)
    repository.register_revision(
        RevisionSeed(id=uuid4(), dataset_id=dataset_id, number=1, manifest_sha256="a" * 64)
    )
    repository.create_release(
        dataset_id,
        tag="v1",
        revision_number=1,
        title=None,
        created_by="alice",
        idempotency_key="k1",
    )
    tag_path = release_tag_file(
        repository.data_root,
        repository.get_organization(organization_id),
        repository.get_project(project_id),
        repository.get_dataset(dataset_id),
        "v1",
    )
    document = json.loads(Path(tag_path).read_text())

    assert document.keys() == {
        "id",
        "dataset_id",
        "tag",
        "revision_id",
        "revision_number",
        "title",
        "created_by",
        "created_at",
    }


# -- patch_organization / patch_project ------------------------------------


def test_patch_organization_rejects_a_stale_expected_version(tmp_path: Path) -> None:
    """``patch_organization`` refuses a stale version, raising ``PreconditionFailed``."""
    repository = _repository(tmp_path)
    organization_id, _, _ = _hierarchy(repository)
    with pytest.raises(PreconditionFailed):
        repository.patch_organization(
            organization_id, expected_version=99, slug=None, title="New", description=None
        )


def test_patch_organization_updates_description_only(tmp_path: Path) -> None:
    """Patching only the description leaves the title unchanged and still bumps the version."""
    repository = _repository(tmp_path)
    organization_id, _, _ = _hierarchy(repository)
    patched = repository.patch_organization(
        organization_id, expected_version=1, slug=None, title=None, description="updated"
    )
    assert patched.description == "updated"
    assert patched.title == "Astro"
    assert patched.version == 2


def test_patch_project_updates_title_and_description(tmp_path: Path) -> None:
    """Patching a project's title and description updates both and bumps the version."""
    repository = _repository(tmp_path)
    _, project_id, _ = _hierarchy(repository)
    patched = repository.patch_project(
        project_id, expected_version=1, slug=None, title="Renamed", description="updated"
    )
    assert patched.title == "Renamed"
    assert patched.description == "updated"
    assert patched.version == 2


def test_patch_project_rejects_a_slug_change(tmp_path: Path) -> None:
    """``patch_project`` refuses to change the slug, raising ``SlugImmutable``."""
    repository = _repository(tmp_path)
    _, project_id, _ = _hierarchy(repository)
    with pytest.raises(SlugImmutable):
        repository.patch_project(
            project_id, expected_version=1, slug="renamed", title=None, description=None
        )


def test_patch_project_rejects_a_stale_expected_version(tmp_path: Path) -> None:
    """``patch_project`` refuses a stale ``expected_version``, raising ``PreconditionFailed``."""
    repository = _repository(tmp_path)
    _, project_id, _ = _hierarchy(repository)
    with pytest.raises(PreconditionFailed):
        repository.patch_project(
            project_id, expected_version=99, slug=None, title="New", description=None
        )


# -- list_organizations / list_projects / list_datasets / list_releases -----


def test_list_organizations_orders_by_slug(tmp_path: Path) -> None:
    """``list_organizations`` returns organizations ordered by slug, not creation order."""
    repository = _repository(tmp_path)
    repository.create_organization(slug="zeta", title="Zeta", description="", idempotency_key="k1")
    repository.create_organization(
        slug="astro", title="Astro", description="", idempotency_key="k2"
    )

    items = repository.list_organizations()

    assert [item.slug for item in items] == ["astro", "zeta"]


def test_list_organizations_returns_the_empty_list_when_none_exist(tmp_path: Path) -> None:
    """``list_organizations`` returns an empty list when no organization exists."""
    repository = _repository(tmp_path)
    assert repository.list_organizations() == []


def test_list_organizations_returns_a_snapshot_that_mutation_cannot_corrupt(
    tmp_path: Path,
) -> None:
    """Clearing a ``list_organizations`` result does not affect the repository's stored data."""
    repository = _repository(tmp_path)
    repository.create_organization(
        slug="astro", title="Astro", description="", idempotency_key="k1"
    )

    items = repository.list_organizations()
    items.clear()

    assert len(repository.list_organizations()) == 1


def test_list_projects_orders_by_slug_and_excludes_other_organizations(tmp_path: Path) -> None:
    """``list_projects`` returns only the given organization's projects, ordered by slug."""
    repository = _repository(tmp_path)
    organization_id, _, _ = _hierarchy(repository)
    other_organization = repository.create_organization(
        slug="biolab", title="Biolab", description="", idempotency_key="org-2"
    )
    repository.create_project(
        organization_id,
        slug="zeta",
        title="Zeta",
        description="",
        data_classification="open",
        idempotency_key="p1",
    )
    repository.create_project(
        other_organization.id,
        slug="other",
        title="Other",
        description="",
        data_classification="open",
        idempotency_key="p2",
    )

    items = repository.list_projects(organization_id)

    assert [item.slug for item in items] == ["sims", "zeta"]


def test_list_projects_returns_the_empty_list_when_the_organization_has_no_projects(
    tmp_path: Path,
) -> None:
    """``list_projects`` returns an empty list for an organization with no projects."""
    repository = _repository(tmp_path)
    organization = repository.create_organization(
        slug="astro", title="Astro", description="", idempotency_key="k1"
    )
    assert repository.list_projects(organization.id) == []


def test_list_projects_raises_for_an_unknown_organization(tmp_path: Path) -> None:
    """``list_projects`` raises ``ResourceNotFound`` for an unknown organization id."""
    repository = _repository(tmp_path)
    with pytest.raises(ResourceNotFound):
        repository.list_projects(uuid4())


def test_list_projects_returns_a_snapshot_that_mutation_cannot_corrupt(tmp_path: Path) -> None:
    """Clearing a ``list_projects`` result does not affect the repository's stored data."""
    repository = _repository(tmp_path)
    organization_id, _, _ = _hierarchy(repository)

    items = repository.list_projects(organization_id)
    items.clear()

    assert len(repository.list_projects(organization_id)) == 1


def test_list_datasets_orders_by_slug_and_excludes_other_projects(tmp_path: Path) -> None:
    """``list_datasets`` returns only the given project's datasets, ordered by slug."""
    repository = _repository(tmp_path)
    organization_id, project_id, _ = _hierarchy(repository)
    repository.create_dataset(
        project_id,
        slug="aardvark",
        title="Aardvark",
        description="",
        profile_name="mcnp-run",
        profile_version="1.0",
        idempotency_key="ds-2",
    )
    other_project = repository.create_project(
        organization_id,
        slug="other",
        title="Other",
        description="",
        data_classification="open",
        idempotency_key="p2",
    )
    repository.create_dataset(
        other_project.id,
        slug="excluded",
        title="Excluded",
        description="",
        profile_name="mcnp-run",
        profile_version="1.0",
        idempotency_key="ds-3",
    )

    items = repository.list_datasets(project_id)

    assert [item.slug for item in items] == ["aardvark", "run-0001"]


def test_list_datasets_returns_the_empty_list_when_the_project_has_no_datasets(
    tmp_path: Path,
) -> None:
    """``list_datasets`` returns an empty list for a project with no datasets."""
    repository = _repository(tmp_path)
    organization_id, _, _ = _hierarchy(repository)
    project = repository.create_project(
        organization_id,
        slug="empty",
        title="Empty",
        description="",
        data_classification="open",
        idempotency_key="p2",
    )
    assert repository.list_datasets(project.id) == []


def test_list_datasets_raises_for_an_unknown_project(tmp_path: Path) -> None:
    """``list_datasets`` raises ``ResourceNotFound`` for an unknown project id."""
    repository = _repository(tmp_path)
    with pytest.raises(ResourceNotFound):
        repository.list_datasets(uuid4())


def test_list_datasets_returns_a_snapshot_that_mutation_cannot_corrupt(tmp_path: Path) -> None:
    """Clearing a ``list_datasets`` result does not affect the repository's stored data."""
    repository = _repository(tmp_path)
    _, project_id, _ = _hierarchy(repository)

    items = repository.list_datasets(project_id)
    items.clear()

    assert len(repository.list_datasets(project_id)) == 1


def test_list_releases_orders_by_tag(tmp_path: Path) -> None:
    """``list_releases`` returns a dataset's releases ordered by tag, not creation order."""
    repository = _repository(tmp_path)
    _, _, dataset_id = _hierarchy(repository)
    repository.register_revision(
        RevisionSeed(id=uuid4(), dataset_id=dataset_id, number=1, manifest_sha256="a" * 64)
    )
    repository.create_release(
        dataset_id,
        tag="v2",
        revision_number=1,
        title=None,
        created_by="alice",
        idempotency_key="r1",
    )
    repository.create_release(
        dataset_id,
        tag="v1",
        revision_number=1,
        title=None,
        created_by="alice",
        idempotency_key="r2",
    )

    items = repository.list_releases(dataset_id)

    assert [item.tag for item in items] == ["v1", "v2"]


def test_list_releases_returns_the_empty_list_when_the_dataset_has_no_releases(
    tmp_path: Path,
) -> None:
    """``list_releases`` returns an empty list for a dataset with no releases."""
    repository = _repository(tmp_path)
    _, _, dataset_id = _hierarchy(repository)
    assert repository.list_releases(dataset_id) == []


def test_list_releases_raises_for_an_unknown_dataset(tmp_path: Path) -> None:
    """``list_releases`` raises ``ResourceNotFound`` for an unknown dataset id."""
    repository = _repository(tmp_path)
    with pytest.raises(ResourceNotFound):
        repository.list_releases(uuid4())


def test_list_releases_returns_a_snapshot_that_mutation_cannot_corrupt(tmp_path: Path) -> None:
    """Clearing a ``list_releases`` result does not affect the repository's stored data."""
    repository = _repository(tmp_path)
    _, _, dataset_id = _hierarchy(repository)
    repository.register_revision(
        RevisionSeed(id=uuid4(), dataset_id=dataset_id, number=1, manifest_sha256="a" * 64)
    )
    repository.create_release(
        dataset_id,
        tag="v1",
        revision_number=1,
        title=None,
        created_by="alice",
        idempotency_key="r1",
    )

    items = repository.list_releases(dataset_id)
    items.clear()

    assert len(repository.list_releases(dataset_id)) == 1
