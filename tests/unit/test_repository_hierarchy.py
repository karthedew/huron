"""Direct unit tests for ``RepositoryFixture``'s write paths, over the in-memory hierarchy store.

Idempotent replay (including a request that changes only a field the old
fingerprint used to ignore), slug and classification refusals, optimistic-
concurrency preconditions, the no-op patch, the durable-before-visible
ordering when the document write fails, and the execution-model guarantee
that the document write runs off the event loop.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

import pytest

from huron.core.security import AccessPolicy
from huron.core.catalog import (
    DatasetCollection,
    OrganizationCollection,
    ProjectCollection,
)
from huron.core.catalog.types import DescriptionChange, PlatformRoot
from huron.core.foundation.retry import request_sha256, IdempotencyClaim
from huron.core.security.principal import Principal
from huron.core.catalog.errors import ClassificationUnknown, SlugImmutable, SlugExists
from huron.core.foundation.errors import (
    IdempotencyKeyReused,
    PreconditionFailed,
    ResourceNotFound,
)
from huron.core.catalog.paths import dataset_dir, organization_dir, project_dir
from huron.core.metastore import InMemoryHierarchyStore, InMemoryRbacStore
from huron.core.rawstore import PosixGenerationStore
from huron.core.security.rules import RoleBindingAuthorizer, ScopeType, Visibility
from tests.catalog_creation_support import creation_for
from tests.repository_fixture import RepositoryFixture

if TYPE_CHECKING:
    from uuid import UUID

pytestmark = pytest.mark.unit


async def _repository(tmp_path: Path) -> RepositoryFixture:
    """Build a storage bundle at ``tmp_path`` over a fresh in-memory hierarchy store."""
    repository = RepositoryFixture(
        PosixGenerationStore(tmp_path / "raw"),
        InMemoryHierarchyStore(),
        InMemoryRbacStore(),
    )

    await repository.rbac.grant_role(
        principal="user:tester",
        role_code="platform_owner",
        scope_type=ScopeType.SYSTEM,
        scope_id=None,
        created_by="bootstrap",
    )
    return repository


@dataclass(frozen=True, slots=True)
class _Collections:
    """The three typed collections one actor-bound test needs together."""

    organizations: OrganizationCollection
    projects: ProjectCollection
    datasets: DatasetCollection


def _descriptions(repository: RepositoryFixture, visibility: Visibility) -> _Collections:
    """Bind actual authorized collections to an owner or an undiscovering actor."""
    actor = Principal("tester" if visibility.unrestricted else "outsider")
    access = AccessPolicy(actor, repository.hierarchy, repository.rbac, RoleBindingAuthorizer())
    return _Collections(
        OrganizationCollection(access, repository.hierarchy, repository.raw_store),
        ProjectCollection(access, repository.hierarchy, repository.raw_store),
        DatasetCollection(access, repository.hierarchy, repository.raw_store),
    )


def _claim(operation: str, *parts: str, key: str) -> IdempotencyClaim:
    """Build an idempotency claim staked by ``tester`` over one operation's digest parts."""
    return IdempotencyClaim(
        principal="tester", key=key, request_sha256=request_sha256(operation, *parts)
    )


async def _hierarchy(repository: RepositoryFixture) -> tuple[UUID, UUID, UUID]:
    """Create one organization/project/dataset and return their ids."""
    organization = await (await creation_for(repository)).create_organization(
        slug="astro",
        title="Astro",
        description="",
        claim=_claim("organization", "astro", "Astro", "", key="org-1"),
    )
    project = await (await creation_for(repository)).create_project(
        organization.id,
        slug="sims",
        title="Sims",
        description="",
        data_classification="open",
        claim=_claim("project", str(organization.id), "sims", "Sims", "", "open", key="proj-1"),
    )
    dataset = await (await creation_for(repository)).create_dataset(
        project.id,
        slug="run-0001",
        title="Run 1",
        description="",
        profile_name="mcnp-run",
        profile_version="1.0",
        claim=_claim(
            "dataset",
            str(project.id),
            "run-0001",
            "Run 1",
            "",
            "mcnp-run",
            "1.0",
            "raw",
            key="ds-1",
        ),
    )
    return organization.id, project.id, dataset.id


def _data_root(repository: RepositoryFixture) -> PurePosixPath:
    """Return the raw store's root in the form the layout functions take."""
    return PurePosixPath(repository.raw_store.root)


def _generation_files(entity_dir: object) -> list[Path]:
    """List the generation documents written under a hierarchy entity's directory."""
    return sorted((Path(str(entity_dir)) / "generations").glob("*.json"))


# -- create_organization ------------------------------------------------


async def test_create_organization_replays_an_identical_request(tmp_path: Path) -> None:
    """Replaying ``create_organization`` with the same claim returns the identical object."""
    repository = await _repository(tmp_path)
    claim = _claim("organization", "astro", "Astro", "", key="k1")
    first = await (await creation_for(repository)).create_organization(
        slug="astro", title="Astro", description="", claim=claim
    )
    second = await (await creation_for(repository)).create_organization(
        slug="astro", title="Astro", description="", claim=claim
    )
    assert second == first


async def test_create_organization_rejects_reuse_of_a_key_with_different_arguments(
    tmp_path: Path,
) -> None:
    """Reusing an idempotency key with a different title raises ``IdempotencyKeyReused``."""
    repository = await _repository(tmp_path)
    await (await creation_for(repository)).create_organization(
        slug="astro",
        title="Astro",
        description="",
        claim=_claim("organization", "astro", "Astro", "", key="k1"),
    )
    with pytest.raises(IdempotencyKeyReused):
        await (await creation_for(repository)).create_organization(
            slug="astro",
            title="Renamed",
            description="",
            claim=_claim("organization", "astro", "Renamed", "", key="k1"),
        )


async def test_create_organization_rejects_a_duplicate_slug(tmp_path: Path) -> None:
    """A second organization with the same slug but a new idempotency key raises ``SlugExists``."""
    repository = await _repository(tmp_path)
    await (await creation_for(repository)).create_organization(
        slug="astro",
        title="Astro",
        description="",
        claim=_claim("organization", "astro", "Astro", "", key="k1"),
    )
    with pytest.raises(SlugExists, match="organization slug already exists"):
        await (await creation_for(repository)).create_organization(
            slug="astro",
            title="Astro Again",
            description="",
            claim=_claim("organization", "astro", "Astro Again", "", key="k2"),
        )


async def test_a_create_whose_document_write_raises_leaves_no_row_and_no_idempotency_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A document write that raises rolls back the whole transaction, row and claim alike."""
    repository = await _repository(tmp_path)

    def _raising_write_generation(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(repository.raw_store, "write_generation", _raising_write_generation)
    claim = _claim("organization", "astro", "Astro", "", key="k1")
    with pytest.raises(OSError, match="disk full"):
        await (await creation_for(repository)).create_organization(
            slug="astro", title="Astro", description="", claim=claim
        )

    window = await repository.hierarchy.organizations.browse(
        PlatformRoot.ROOT, Visibility.ALL, limit=10, after=None
    )
    assert window.items == []

    monkeypatch.undo()
    created = await (await creation_for(repository)).create_organization(
        slug="astro", title="Astro", description="", claim=claim
    )
    assert created.slug == "astro"


async def test_the_generation_document_write_executes_off_the_event_loop_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``create_organization``'s document write runs on a worker thread, not the event loop."""
    repository = await _repository(tmp_path)
    real_write_generation = repository.raw_store.write_generation
    ran_on_the_event_loop: list[bool] = []

    def _tracking_write_generation(*args: object, **kwargs: object) -> None:
        try:
            asyncio.get_running_loop()
            ran_on_the_event_loop.append(True)
        except RuntimeError:
            ran_on_the_event_loop.append(False)
        real_write_generation(*args, **kwargs)

    monkeypatch.setattr(repository.raw_store, "write_generation", _tracking_write_generation)
    await (await creation_for(repository)).create_organization(
        slug="astro",
        title="Astro",
        description="",
        claim=_claim("organization", "astro", "Astro", "", key="k1"),
    )
    assert ran_on_the_event_loop == [False]


# -- create_project -------------------------------------------------------


async def test_create_project_replays_an_identical_request(tmp_path: Path) -> None:
    """Replaying ``create_project`` with the same idempotency claim returns the identical object."""
    repository = await _repository(tmp_path)
    organization_id, _, _ = await _hierarchy(repository)
    claim = _claim("project", str(organization_id), "second", "Second", "", "open", key="k1")
    first = await (await creation_for(repository)).create_project(
        organization_id,
        slug="second",
        title="Second",
        description="",
        data_classification="open",
        claim=claim,
    )
    second = await (await creation_for(repository)).create_project(
        organization_id,
        slug="second",
        title="Second",
        description="",
        data_classification="open",
        claim=claim,
    )
    assert second == first


async def test_create_project_rejects_a_duplicate_slug(tmp_path: Path) -> None:
    """A second project with an existing slug in the same organization raises ``SlugExists``."""
    repository = await _repository(tmp_path)
    organization_id, _, _ = await _hierarchy(repository)
    with pytest.raises(SlugExists, match="project slug already exists"):
        await (await creation_for(repository)).create_project(
            organization_id,
            slug="sims",
            title="Sims Again",
            description="",
            data_classification="open",
            claim=_claim(
                "project", str(organization_id), "sims", "Sims Again", "", "open", key="k2"
            ),
        )


async def test_create_project_accepts_a_classification_in_the_configured_vocabulary(
    tmp_path: Path,
) -> None:
    """A classification listed in the configured vocabulary is accepted and stored."""
    repository = await _repository(tmp_path)
    organization_id, _, _ = await _hierarchy(repository)
    project = await (await creation_for(repository)).create_project(
        organization_id,
        slug="second",
        title="Second",
        description="",
        data_classification="open",
        claim=_claim("project", str(organization_id), "second", "Second", "", "open", key="k2"),
    )
    assert project.data_classification == "open"


async def test_create_project_rejects_a_classification_outside_the_configured_vocabulary(
    tmp_path: Path,
) -> None:
    """A classification outside the configured vocabulary raises ``ClassificationUnknown``."""
    repository = await _repository(tmp_path)
    organization_id, _, _ = await _hierarchy(repository)
    with pytest.raises(ClassificationUnknown):
        await (await creation_for(repository)).create_project(
            organization_id,
            slug="second",
            title="Second",
            description="",
            data_classification="top-secret",
            claim=_claim(
                "project", str(organization_id), "second", "Second", "", "top-secret", key="k2"
            ),
        )


async def test_create_project_with_an_empty_vocabulary_refuses_every_classification(
    tmp_path: Path,
) -> None:
    """With an empty classification vocabulary, even a plausible classification is refused."""
    repository = await _repository(tmp_path)
    organization = await (
        await creation_for(repository, classifications=(), visible=True)
    ).create_organization(
        slug="astro",
        title="Astro",
        description="",
        claim=_claim("organization", "astro", "Astro", "", key="org-1"),
    )
    with pytest.raises(ClassificationUnknown):
        await (await creation_for(repository, classifications=(), visible=True)).create_project(
            organization.id,
            slug="sims",
            title="Sims",
            description="",
            data_classification="open",
            claim=_claim("project", str(organization.id), "sims", "Sims", "", "open", key="proj-1"),
        )


async def test_create_project_replay_with_a_different_classification_is_a_reuse(
    tmp_path: Path,
) -> None:
    """Reusing a project-create key with only the classification changed is a reuse.

    The old fingerprint left ``data_classification`` out; the digest now
    covers it, so a request differing in only that field is caught.
    """
    repository = await _repository(tmp_path)
    organization = await (
        await creation_for(repository, classifications=("open", "restricted"), visible=True)
    ).create_organization(
        slug="astro",
        title="Astro",
        description="",
        claim=_claim("organization", "astro", "Astro", "", key="org-1"),
    )
    await (
        await creation_for(repository, classifications=("open", "restricted"), visible=True)
    ).create_project(
        organization.id,
        slug="sims",
        title="Sims",
        description="",
        data_classification="open",
        claim=_claim("project", str(organization.id), "sims", "Sims", "", "open", key="k1"),
    )
    with pytest.raises(IdempotencyKeyReused):
        await (
            await creation_for(repository, classifications=("open", "restricted"), visible=True)
        ).create_project(
            organization.id,
            slug="sims",
            title="Sims",
            description="",
            data_classification="restricted",
            claim=_claim(
                "project", str(organization.id), "sims", "Sims", "", "restricted", key="k1"
            ),
        )


async def test_create_project_under_an_invisible_organization_is_not_found(
    tmp_path: Path,
) -> None:
    """Creating a project under an organization the caller cannot discover is 404, not 409/400."""
    repository = await _repository(tmp_path)
    organization = await (await creation_for(repository)).create_organization(
        slug="astro",
        title="Astro",
        description="",
        claim=_claim("organization", "astro", "Astro", "", key="org-1"),
    )
    with pytest.raises(ResourceNotFound):
        await (
            await creation_for(repository, classifications=("open",), visible=False)
        ).create_project(
            organization.id,
            slug="sims",
            title="Sims",
            description="",
            data_classification="open",
            claim=_claim("project", str(organization.id), "sims", "Sims", "", "open", key="proj-1"),
        )


# -- create_dataset ---------------------------------------------------------


async def test_create_dataset_replays_an_identical_request(tmp_path: Path) -> None:
    """Replaying ``create_dataset`` with the same idempotency claim returns the identical object."""
    repository = await _repository(tmp_path)
    _, project_id, _ = await _hierarchy(repository)
    claim = _claim(
        "dataset", str(project_id), "second", "Second", "", "mcnp-run", "1.0", "raw", key="k1"
    )
    first = await (await creation_for(repository)).create_dataset(
        project_id,
        slug="second",
        title="Second",
        description="",
        profile_name="mcnp-run",
        profile_version="1.0",
        claim=claim,
    )
    second = await (await creation_for(repository)).create_dataset(
        project_id,
        slug="second",
        title="Second",
        description="",
        profile_name="mcnp-run",
        profile_version="1.0",
        claim=claim,
    )
    assert second == first


async def test_create_dataset_rejects_a_duplicate_slug(tmp_path: Path) -> None:
    """A second dataset with an existing slug in the same project raises ``SlugExists``."""
    repository = await _repository(tmp_path)
    _, project_id, _ = await _hierarchy(repository)
    with pytest.raises(SlugExists, match="dataset slug already exists"):
        await (await creation_for(repository)).create_dataset(
            project_id,
            slug="run-0001",
            title="Run 1 Again",
            description="",
            profile_name="mcnp-run",
            profile_version="1.0",
            claim=_claim(
                "dataset",
                str(project_id),
                "run-0001",
                "Run 1 Again",
                "",
                "mcnp-run",
                "1.0",
                "raw",
                key="k2",
            ),
        )


async def test_create_dataset_replay_with_a_different_description_is_a_reuse(
    tmp_path: Path,
) -> None:
    """Reusing a dataset-create key with only the description changed is a reuse.

    The old fingerprint left ``description`` out; the digest now covers it,
    so a request differing in only that field is caught.
    """
    repository = await _repository(tmp_path)
    _, project_id, _ = await _hierarchy(repository)
    await (await creation_for(repository)).create_dataset(
        project_id,
        slug="second",
        title="Second",
        description="first description",
        profile_name="mcnp-run",
        profile_version="1.0",
        claim=_claim(
            "dataset",
            str(project_id),
            "second",
            "Second",
            "first description",
            "mcnp-run",
            "1.0",
            "raw",
            key="k1",
        ),
    )
    with pytest.raises(IdempotencyKeyReused):
        await (await creation_for(repository)).create_dataset(
            project_id,
            slug="second",
            title="Second",
            description="different description",
            profile_name="mcnp-run",
            profile_version="1.0",
            claim=_claim(
                "dataset",
                str(project_id),
                "second",
                "Second",
                "different description",
                "mcnp-run",
                "1.0",
                "raw",
                key="k1",
            ),
        )


async def test_create_dataset_under_an_invisible_project_is_not_found(tmp_path: Path) -> None:
    """Creating a dataset under a project the caller cannot discover is 404, not 409/400."""
    repository = await _repository(tmp_path)
    _, project_id, _ = await _hierarchy(repository)
    with pytest.raises(ResourceNotFound):
        await (
            await creation_for(repository, classifications=("open",), visible=False)
        ).create_dataset(
            project_id,
            slug="second",
            title="Second",
            description="",
            profile_name="mcnp-run",
            profile_version="1.0",
            claim=_claim(
                "dataset",
                str(project_id),
                "second",
                "Second",
                "",
                "mcnp-run",
                "1.0",
                "raw",
                key="k1",
            ),
        )


# -- patch_dataset ------------------------------------------------------


async def test_patch_dataset_rejects_a_slug_change(tmp_path: Path) -> None:
    """``patch_dataset`` refuses to change the slug, raising ``SlugImmutable``."""
    repository = await _repository(tmp_path)
    _, _, dataset_id = await _hierarchy(repository)
    with pytest.raises(SlugImmutable):
        await _descriptions(repository, Visibility.ALL).datasets.describe(
            dataset_id,
            DescriptionChange(expected_version=1, slug="renamed", title=None, description=None),
        )


async def test_patch_dataset_rejects_a_stale_expected_version(tmp_path: Path) -> None:
    """``patch_dataset`` refuses a stale ``expected_version``, raising ``PreconditionFailed``."""
    repository = await _repository(tmp_path)
    _, _, dataset_id = await _hierarchy(repository)
    with pytest.raises(PreconditionFailed):
        await _descriptions(repository, Visibility.ALL).datasets.describe(
            dataset_id,
            DescriptionChange(expected_version=99, slug=None, title="New Title", description=None),
        )


async def test_patch_dataset_naming_no_field_is_a_no_op(tmp_path: Path) -> None:
    """A patch naming neither ``title`` nor ``description`` writes no new generation document."""
    repository = await _repository(tmp_path)
    organization_id, project_id, dataset_id = await _hierarchy(repository)
    organization = await repository.hierarchy.organizations.get(organization_id, Visibility.ALL)
    project = await repository.hierarchy.projects.get(project_id, Visibility.ALL)
    dataset = await repository.hierarchy.datasets.get(dataset_id, Visibility.ALL)
    before = _generation_files(dataset_dir(_data_root(repository), organization, project, dataset))

    patched = await _descriptions(repository, Visibility.ALL).datasets.describe(
        dataset_id, DescriptionChange(expected_version=1, slug=None, title=None, description=None)
    )

    assert patched == dataset
    assert patched.version == 1
    after = _generation_files(dataset_dir(_data_root(repository), organization, project, dataset))
    assert after == before


async def test_patch_dataset_naming_the_current_values_is_a_no_op(tmp_path: Path) -> None:
    """A patch whose title and description already match the stored values is also a no-op."""
    repository = await _repository(tmp_path)
    organization_id, project_id, dataset_id = await _hierarchy(repository)
    organization = await repository.hierarchy.organizations.get(organization_id, Visibility.ALL)
    project = await repository.hierarchy.projects.get(project_id, Visibility.ALL)
    dataset = await repository.hierarchy.datasets.get(dataset_id, Visibility.ALL)
    before = _generation_files(dataset_dir(_data_root(repository), organization, project, dataset))

    patched = await _descriptions(repository, Visibility.ALL).datasets.describe(
        dataset_id,
        DescriptionChange(
            expected_version=1, slug=None, title=dataset.title, description=dataset.description
        ),
    )

    assert patched == dataset
    assert patched.version == 1
    after = _generation_files(dataset_dir(_data_root(repository), organization, project, dataset))
    assert after == before


@pytest.mark.parametrize("kind", ("organization", "project", "dataset"))
async def test_a_failing_document_write_during_patch_leaves_the_stored_record_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    """A patch whose document write raises leaves the row at its pre-patch state.

    The row update and the document write are one transaction: the store
    must never advance a record's version without the matching generation
    document landing beside it.
    """
    repository = await _repository(tmp_path)
    organization_id, project_id, dataset_id = await _hierarchy(repository)
    target_id, read, patch = {
        "organization": (
            organization_id,
            repository.hierarchy.organizations.get,
            _descriptions(repository, Visibility.ALL).organizations.describe,
        ),
        "project": (
            project_id,
            repository.hierarchy.projects.get,
            _descriptions(repository, Visibility.ALL).projects.describe,
        ),
        "dataset": (
            dataset_id,
            repository.hierarchy.datasets.get,
            _descriptions(repository, Visibility.ALL).datasets.describe,
        ),
    }[kind]
    original = await read(target_id, Visibility.ALL)

    def _raising_write_generation(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(repository.raw_store, "write_generation", _raising_write_generation)
    with pytest.raises(OSError, match="disk full"):
        await patch(
            target_id,
            DescriptionChange(expected_version=1, slug=None, title="Renamed", description=None),
        )

    monkeypatch.undo()
    assert await read(target_id, Visibility.ALL) == original


async def test_undiscoverable_patch_targets_hide_slug_and_version_errors(tmp_path: Path) -> None:
    """Every hierarchy patch checks discovery before reporting identity or version details."""
    repository = await _repository(tmp_path)
    organization_id, project_id, dataset_id = await _hierarchy(repository)
    for target_id, patch in (
        (organization_id, _descriptions(repository, Visibility()).organizations.describe),
        (project_id, _descriptions(repository, Visibility()).projects.describe),
        (dataset_id, _descriptions(repository, Visibility()).datasets.describe),
    ):
        with pytest.raises(ResourceNotFound):
            await patch(
                target_id,
                DescriptionChange(
                    expected_version=99, slug="renamed", title="Invisible", description=None
                ),
            )


# -- patch_organization / patch_project ------------------------------------


async def test_patch_organization_rejects_a_stale_expected_version(tmp_path: Path) -> None:
    """``patch_organization`` refuses a stale version, raising ``PreconditionFailed``."""
    repository = await _repository(tmp_path)
    organization_id, _, _ = await _hierarchy(repository)
    with pytest.raises(PreconditionFailed):
        await _descriptions(repository, Visibility.ALL).organizations.describe(
            organization_id,
            DescriptionChange(expected_version=99, slug=None, title="New", description=None),
        )


async def test_patch_organization_updates_description_only(tmp_path: Path) -> None:
    """Patching only the description leaves the title unchanged and still bumps the version."""
    repository = await _repository(tmp_path)
    organization_id, _, _ = await _hierarchy(repository)
    patched = await _descriptions(repository, Visibility.ALL).organizations.describe(
        organization_id,
        DescriptionChange(expected_version=1, slug=None, title=None, description="updated"),
    )
    assert patched.description == "updated"
    assert patched.title == "Astro"
    assert patched.version == 2


async def test_patch_organization_naming_no_field_is_a_no_op(tmp_path: Path) -> None:
    """A patch naming neither ``title`` nor ``description`` writes no new generation document."""
    repository = await _repository(tmp_path)
    organization_id, _, _ = await _hierarchy(repository)
    organization = await repository.hierarchy.organizations.get(organization_id, Visibility.ALL)
    before = _generation_files(organization_dir(_data_root(repository), organization))

    patched = await _descriptions(repository, Visibility.ALL).organizations.describe(
        organization_id,
        DescriptionChange(expected_version=1, slug=None, title=None, description=None),
    )

    assert patched == organization
    after = _generation_files(organization_dir(_data_root(repository), organization))
    assert after == before


async def test_patch_project_updates_title_and_description(tmp_path: Path) -> None:
    """Patching a project's title and description updates both and bumps the version."""
    repository = await _repository(tmp_path)
    _, project_id, _ = await _hierarchy(repository)
    patched = await _descriptions(repository, Visibility.ALL).projects.describe(
        project_id,
        DescriptionChange(expected_version=1, slug=None, title="Renamed", description="updated"),
    )
    assert patched.title == "Renamed"
    assert patched.description == "updated"
    assert patched.version == 2


async def test_patch_project_rejects_a_slug_change(tmp_path: Path) -> None:
    """``patch_project`` refuses to change the slug, raising ``SlugImmutable``."""
    repository = await _repository(tmp_path)
    _, project_id, _ = await _hierarchy(repository)
    with pytest.raises(SlugImmutable):
        await _descriptions(repository, Visibility.ALL).projects.describe(
            project_id,
            DescriptionChange(expected_version=1, slug="renamed", title=None, description=None),
        )


async def test_patch_project_rejects_a_stale_expected_version(tmp_path: Path) -> None:
    """``patch_project`` refuses a stale ``expected_version``, raising ``PreconditionFailed``."""
    repository = await _repository(tmp_path)
    _, project_id, _ = await _hierarchy(repository)
    with pytest.raises(PreconditionFailed):
        await _descriptions(repository, Visibility.ALL).projects.describe(
            project_id,
            DescriptionChange(expected_version=99, slug=None, title="New", description=None),
        )


async def test_patch_project_naming_no_field_is_a_no_op(tmp_path: Path) -> None:
    """A patch naming neither ``title`` nor ``description`` writes no new generation document."""
    repository = await _repository(tmp_path)
    organization_id, project_id, _ = await _hierarchy(repository)
    organization = await repository.hierarchy.organizations.get(organization_id, Visibility.ALL)
    project = await repository.hierarchy.projects.get(project_id, Visibility.ALL)
    before = _generation_files(project_dir(_data_root(repository), organization, project))

    patched = await _descriptions(repository, Visibility.ALL).projects.describe(
        project_id, DescriptionChange(expected_version=1, slug=None, title=None, description=None)
    )

    assert patched == project
    after = _generation_files(project_dir(_data_root(repository), organization, project))
    assert after == before


# -- reads: invisible ids -----------------------------------------------


async def test_organization_project_and_dataset_reads_are_not_found_under_no_visibility(
    tmp_path: Path,
) -> None:
    """Every point read is ``ResourceNotFound`` for a caller with empty ``Visibility``."""
    repository = await _repository(tmp_path)
    organization_id, project_id, dataset_id = await _hierarchy(repository)
    for read in (
        lambda: repository.hierarchy.organizations.get(organization_id, Visibility()),
        lambda: repository.hierarchy.projects.get(project_id, Visibility()),
        lambda: repository.hierarchy.datasets.get(dataset_id, Visibility()),
    ):
        with pytest.raises(ResourceNotFound):
            await read()
