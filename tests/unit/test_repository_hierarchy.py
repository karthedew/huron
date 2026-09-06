"""Direct unit tests for ``HierarchyRepository``'s write paths, over the in-memory hierarchy store.

Idempotent replay (including a request that changes only a field the old
fingerprint used to ignore), slug and classification refusals, optimistic-
concurrency preconditions, the no-op patch, the release tag's two
independent guards (the store's own uniqueness and the raw store's once-only
write), the durable-before-visible ordering when the document write fails,
and the execution-model guarantee that the document write runs off the
event loop.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from huron.pkg.catalog.errors import (
    ClassificationUnknown,
    IdempotencyKeyReused,
    PreconditionFailed,
    ResourceNotFound,
    SlugImmutable,
    TagExists,
)
from huron.pkg.catalog.paths import dataset_dir, organization_dir, project_dir, release_tag_file
from huron.pkg.rawstore import PosixRawStore
from huron.pkg.rbac import Visibility
from huron.service.api.errors import SlugExists
from huron.service.api.repository import HierarchyRepository, request_sha256
from huron.service.api.stores import IdempotencyClaim, InMemoryHierarchyStore, InMemoryRbacStore
from tests.hierarchy_contract import committed_revision

if TYPE_CHECKING:
    from uuid import UUID

pytestmark = pytest.mark.unit


def _repository(
    tmp_path: Path, *, classifications: tuple[str, ...] = ("open",)
) -> HierarchyRepository:
    """Build a ``HierarchyRepository`` at ``tmp_path`` over a fresh in-memory hierarchy store."""
    return HierarchyRepository(
        PosixRawStore(str(tmp_path / "raw")),
        InMemoryHierarchyStore(),
        classification_vocabulary=classifications,
        rbac_store=InMemoryRbacStore(),
    )


def _claim(operation: str, *parts: str | None, key: str) -> IdempotencyClaim:
    """Build an idempotency claim staked by ``tester`` over one operation's digest parts."""
    return IdempotencyClaim(
        principal="tester", key=key, request_sha256=request_sha256(operation, *parts)
    )


async def _hierarchy(repository: HierarchyRepository) -> tuple[UUID, UUID, UUID]:
    """Create one organization/project/dataset and return their ids."""
    organization = await repository.create_organization(
        slug="astro",
        title="Astro",
        description="",
        claim=_claim("organization", "astro", "Astro", "", key="org-1"),
    )
    project = await repository.create_project(
        organization.id,
        Visibility.ALL,
        slug="sims",
        title="Sims",
        description="",
        data_classification="open",
        claim=_claim("project", str(organization.id), "sims", "Sims", "", "open", key="proj-1"),
    )
    dataset = await repository.create_dataset(
        project.id,
        Visibility.ALL,
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


def _generation_files(entity_dir: object) -> list[Path]:
    """List the generation documents written under a hierarchy entity's directory."""
    return sorted((Path(str(entity_dir)) / "generations").glob("*.json"))


# -- create_organization ------------------------------------------------


async def test_create_organization_replays_an_identical_request(tmp_path: Path) -> None:
    """Replaying ``create_organization`` with the same claim returns the identical object."""
    repository = _repository(tmp_path)
    claim = _claim("organization", "astro", "Astro", "", key="k1")
    first = await repository.create_organization(
        slug="astro", title="Astro", description="", claim=claim
    )
    second = await repository.create_organization(
        slug="astro", title="Astro", description="", claim=claim
    )
    assert second == first


async def test_create_organization_rejects_reuse_of_a_key_with_different_arguments(
    tmp_path: Path,
) -> None:
    """Reusing an idempotency key with a different title raises ``IdempotencyKeyReused``."""
    repository = _repository(tmp_path)
    await repository.create_organization(
        slug="astro",
        title="Astro",
        description="",
        claim=_claim("organization", "astro", "Astro", "", key="k1"),
    )
    with pytest.raises(IdempotencyKeyReused):
        await repository.create_organization(
            slug="astro",
            title="Renamed",
            description="",
            claim=_claim("organization", "astro", "Renamed", "", key="k1"),
        )


async def test_create_organization_rejects_a_duplicate_slug(tmp_path: Path) -> None:
    """A second organization with the same slug but a new idempotency key raises ``SlugExists``."""
    repository = _repository(tmp_path)
    await repository.create_organization(
        slug="astro",
        title="Astro",
        description="",
        claim=_claim("organization", "astro", "Astro", "", key="k1"),
    )
    with pytest.raises(SlugExists, match="organization slug already exists"):
        await repository.create_organization(
            slug="astro",
            title="Astro Again",
            description="",
            claim=_claim("organization", "astro", "Astro Again", "", key="k2"),
        )


async def test_a_create_whose_document_write_raises_leaves_no_row_and_no_idempotency_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A document write that raises rolls back the whole transaction, row and claim alike."""
    repository = _repository(tmp_path)

    def _raising_write_generation(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(repository, "_write_generation", _raising_write_generation)
    claim = _claim("organization", "astro", "Astro", "", key="k1")
    with pytest.raises(OSError, match="disk full"):
        await repository.create_organization(
            slug="astro", title="Astro", description="", claim=claim
        )

    window = await repository.organizations(Visibility.ALL, limit=10, after=None)
    assert window.items == []

    monkeypatch.undo()
    created = await repository.create_organization(
        slug="astro", title="Astro", description="", claim=claim
    )
    assert created.slug == "astro"


async def test_the_generation_document_write_executes_off_the_event_loop_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``create_organization``'s document write runs on a worker thread, not the event loop."""
    repository = _repository(tmp_path)
    real_write_generation = repository._write_generation
    ran_on_the_event_loop: list[bool] = []

    def _tracking_write_generation(*args: object, **kwargs: object) -> None:
        try:
            asyncio.get_running_loop()
            ran_on_the_event_loop.append(True)
        except RuntimeError:
            ran_on_the_event_loop.append(False)
        real_write_generation(*args, **kwargs)

    monkeypatch.setattr(repository, "_write_generation", _tracking_write_generation)
    await repository.create_organization(
        slug="astro",
        title="Astro",
        description="",
        claim=_claim("organization", "astro", "Astro", "", key="k1"),
    )
    assert ran_on_the_event_loop == [False]


# -- create_project -------------------------------------------------------


async def test_create_project_replays_an_identical_request(tmp_path: Path) -> None:
    """Replaying ``create_project`` with the same idempotency claim returns the identical object."""
    repository = _repository(tmp_path)
    organization_id, _, _ = await _hierarchy(repository)
    claim = _claim("project", str(organization_id), "second", "Second", "", "open", key="k1")
    first = await repository.create_project(
        organization_id,
        Visibility.ALL,
        slug="second",
        title="Second",
        description="",
        data_classification="open",
        claim=claim,
    )
    second = await repository.create_project(
        organization_id,
        Visibility.ALL,
        slug="second",
        title="Second",
        description="",
        data_classification="open",
        claim=claim,
    )
    assert second == first


async def test_create_project_rejects_a_duplicate_slug(tmp_path: Path) -> None:
    """A second project with an existing slug in the same organization raises ``SlugExists``."""
    repository = _repository(tmp_path)
    organization_id, _, _ = await _hierarchy(repository)
    with pytest.raises(SlugExists, match="project slug already exists"):
        await repository.create_project(
            organization_id,
            Visibility.ALL,
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
    repository = _repository(tmp_path)
    organization_id, _, _ = await _hierarchy(repository)
    project = await repository.create_project(
        organization_id,
        Visibility.ALL,
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
    repository = _repository(tmp_path)
    organization_id, _, _ = await _hierarchy(repository)
    with pytest.raises(ClassificationUnknown):
        await repository.create_project(
            organization_id,
            Visibility.ALL,
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
    repository = _repository(tmp_path, classifications=())
    organization = await repository.create_organization(
        slug="astro",
        title="Astro",
        description="",
        claim=_claim("organization", "astro", "Astro", "", key="org-1"),
    )
    with pytest.raises(ClassificationUnknown):
        await repository.create_project(
            organization.id,
            Visibility.ALL,
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
    repository = _repository(tmp_path, classifications=("open", "restricted"))
    organization = await repository.create_organization(
        slug="astro",
        title="Astro",
        description="",
        claim=_claim("organization", "astro", "Astro", "", key="org-1"),
    )
    await repository.create_project(
        organization.id,
        Visibility.ALL,
        slug="sims",
        title="Sims",
        description="",
        data_classification="open",
        claim=_claim("project", str(organization.id), "sims", "Sims", "", "open", key="k1"),
    )
    with pytest.raises(IdempotencyKeyReused):
        await repository.create_project(
            organization.id,
            Visibility.ALL,
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
    repository = _repository(tmp_path)
    organization = await repository.create_organization(
        slug="astro",
        title="Astro",
        description="",
        claim=_claim("organization", "astro", "Astro", "", key="org-1"),
    )
    with pytest.raises(ResourceNotFound):
        await repository.create_project(
            organization.id,
            Visibility(),
            slug="sims",
            title="Sims",
            description="",
            data_classification="open",
            claim=_claim("project", str(organization.id), "sims", "Sims", "", "open", key="proj-1"),
        )


# -- create_dataset ---------------------------------------------------------


async def test_create_dataset_replays_an_identical_request(tmp_path: Path) -> None:
    """Replaying ``create_dataset`` with the same idempotency claim returns the identical object."""
    repository = _repository(tmp_path)
    _, project_id, _ = await _hierarchy(repository)
    claim = _claim(
        "dataset", str(project_id), "second", "Second", "", "mcnp-run", "1.0", "raw", key="k1"
    )
    first = await repository.create_dataset(
        project_id,
        Visibility.ALL,
        slug="second",
        title="Second",
        description="",
        profile_name="mcnp-run",
        profile_version="1.0",
        claim=claim,
    )
    second = await repository.create_dataset(
        project_id,
        Visibility.ALL,
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
    repository = _repository(tmp_path)
    _, project_id, _ = await _hierarchy(repository)
    with pytest.raises(SlugExists, match="dataset slug already exists"):
        await repository.create_dataset(
            project_id,
            Visibility.ALL,
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
    repository = _repository(tmp_path)
    _, project_id, _ = await _hierarchy(repository)
    await repository.create_dataset(
        project_id,
        Visibility.ALL,
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
        await repository.create_dataset(
            project_id,
            Visibility.ALL,
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
    repository = _repository(tmp_path)
    _, project_id, _ = await _hierarchy(repository)
    with pytest.raises(ResourceNotFound):
        await repository.create_dataset(
            project_id,
            Visibility(),
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
    repository = _repository(tmp_path)
    _, _, dataset_id = await _hierarchy(repository)
    with pytest.raises(SlugImmutable):
        await repository.patch_dataset(
            dataset_id,
            Visibility.ALL,
            expected_version=1,
            slug="renamed",
            title=None,
            description=None,
        )


async def test_patch_dataset_rejects_a_stale_expected_version(tmp_path: Path) -> None:
    """``patch_dataset`` refuses a stale ``expected_version``, raising ``PreconditionFailed``."""
    repository = _repository(tmp_path)
    _, _, dataset_id = await _hierarchy(repository)
    with pytest.raises(PreconditionFailed):
        await repository.patch_dataset(
            dataset_id,
            Visibility.ALL,
            expected_version=99,
            slug=None,
            title="New Title",
            description=None,
        )


async def test_patch_dataset_naming_no_field_is_a_no_op(tmp_path: Path) -> None:
    """A patch naming neither ``title`` nor ``description`` writes no new generation document."""
    repository = _repository(tmp_path)
    organization_id, project_id, dataset_id = await _hierarchy(repository)
    organization = await repository.organization(organization_id, Visibility.ALL)
    project = await repository.project(project_id, Visibility.ALL)
    dataset = await repository.dataset(dataset_id, Visibility.ALL)
    before = _generation_files(dataset_dir(repository.data_root, organization, project, dataset))

    patched = await repository.patch_dataset(
        dataset_id, Visibility.ALL, expected_version=1, slug=None, title=None, description=None
    )

    assert patched == dataset
    assert patched.version == 1
    after = _generation_files(dataset_dir(repository.data_root, organization, project, dataset))
    assert after == before


async def test_patch_dataset_naming_the_current_values_is_a_no_op(tmp_path: Path) -> None:
    """A patch whose title and description already match the stored values is also a no-op."""
    repository = _repository(tmp_path)
    organization_id, project_id, dataset_id = await _hierarchy(repository)
    organization = await repository.organization(organization_id, Visibility.ALL)
    project = await repository.project(project_id, Visibility.ALL)
    dataset = await repository.dataset(dataset_id, Visibility.ALL)
    before = _generation_files(dataset_dir(repository.data_root, organization, project, dataset))

    patched = await repository.patch_dataset(
        dataset_id,
        Visibility.ALL,
        expected_version=1,
        slug=None,
        title=dataset.title,
        description=dataset.description,
    )

    assert patched == dataset
    assert patched.version == 1
    after = _generation_files(dataset_dir(repository.data_root, organization, project, dataset))
    assert after == before


async def test_a_failing_document_write_during_patch_leaves_the_stored_record_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A patch whose document write raises leaves the row at its pre-patch state.

    The row update and the document write are one transaction: the store
    must never advance a record's version without the matching generation
    document landing beside it.
    """
    repository = _repository(tmp_path)
    _, _, dataset_id = await _hierarchy(repository)

    def _raising_write_generation(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(repository, "_write_generation", _raising_write_generation)
    with pytest.raises(OSError, match="disk full"):
        await repository.patch_dataset(
            dataset_id,
            Visibility.ALL,
            expected_version=1,
            slug=None,
            title="Renamed",
            description=None,
        )

    monkeypatch.undo()
    current = await repository.dataset(dataset_id, Visibility.ALL)
    assert current.title == "Run 1"
    assert current.version == 1


# -- create_release -------------------------------------------------------


async def _commit_revision(
    repository: HierarchyRepository, dataset_id: UUID, *, number: int = 1
) -> None:
    """Commit one revision directly through the hierarchy store's writer."""
    revision = committed_revision(dataset_id, number, manifest_sha256="a" * 64)
    async with repository._hierarchy.transaction() as writer:
        await writer.insert_revision(revision)


async def test_create_release_replays_an_identical_request(tmp_path: Path) -> None:
    """Replaying ``create_release`` with the same idempotency claim returns the identical object."""
    repository = _repository(tmp_path)
    _, _, dataset_id = await _hierarchy(repository)
    await _commit_revision(repository, dataset_id)
    claim = _claim("release", str(dataset_id), "v1", "1", None, "alice", key="k1")
    first = await repository.create_release(
        dataset_id,
        Visibility.ALL,
        tag="v1",
        revision_number=1,
        title=None,
        created_by="alice",
        claim=claim,
    )
    second = await repository.create_release(
        dataset_id,
        Visibility.ALL,
        tag="v1",
        revision_number=1,
        title=None,
        created_by="alice",
        claim=claim,
    )
    assert second == first


async def test_create_release_rejects_a_duplicate_tag(tmp_path: Path) -> None:
    """A second release with an already-used tag raises ``TagExists`` under a new key too."""
    repository = _repository(tmp_path)
    _, _, dataset_id = await _hierarchy(repository)
    await _commit_revision(repository, dataset_id)
    await repository.create_release(
        dataset_id,
        Visibility.ALL,
        tag="v1",
        revision_number=1,
        title=None,
        created_by="alice",
        claim=_claim("release", str(dataset_id), "v1", "1", None, "alice", key="k1"),
    )
    with pytest.raises(TagExists):
        await repository.create_release(
            dataset_id,
            Visibility.ALL,
            tag="v1",
            revision_number=1,
            title=None,
            created_by="alice",
            claim=_claim("release", str(dataset_id), "v1", "1", None, "alice", key="k2"),
        )


async def test_create_release_translates_a_raw_store_collision_into_tag_exists(
    tmp_path: Path,
) -> None:
    """A tag already written to disk still raises ``TagExists`` even under a fresh key.

    The store's own uniqueness and the raw store's once-only write are two
    independent guards against the same race.
    """
    repository = _repository(tmp_path)
    organization_id, project_id, dataset_id = await _hierarchy(repository)
    await _commit_revision(repository, dataset_id)
    organization = await repository.organization(organization_id, Visibility.ALL)
    project = await repository.project(project_id, Visibility.ALL)
    dataset = await repository.dataset(dataset_id, Visibility.ALL)
    tag_path = release_tag_file(repository.data_root, organization, project, dataset, "v1")
    Path(str(tag_path)).parent.mkdir(parents=True, exist_ok=True)
    Path(str(tag_path)).write_bytes(b"{}")

    with pytest.raises(TagExists):
        await repository.create_release(
            dataset_id,
            Visibility.ALL,
            tag="v1",
            revision_number=1,
            title=None,
            created_by="alice",
            claim=_claim("release", str(dataset_id), "v1", "1", None, "alice", key="k1"),
        )


async def test_create_release_persists_a_tag_document_with_no_withdrawal_keys(
    tmp_path: Path,
) -> None:
    """A release's tag document on disk has exactly these keys and no fields for withdrawal."""
    repository = _repository(tmp_path)
    organization_id, project_id, dataset_id = await _hierarchy(repository)
    await _commit_revision(repository, dataset_id)
    await repository.create_release(
        dataset_id,
        Visibility.ALL,
        tag="v1",
        revision_number=1,
        title=None,
        created_by="alice",
        claim=_claim("release", str(dataset_id), "v1", "1", None, "alice", key="k1"),
    )
    organization = await repository.organization(organization_id, Visibility.ALL)
    project = await repository.project(project_id, Visibility.ALL)
    dataset = await repository.dataset(dataset_id, Visibility.ALL)
    tag_path = release_tag_file(repository.data_root, organization, project, dataset, "v1")
    document = json.loads(Path(str(tag_path)).read_text())

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


async def test_create_release_replay_with_a_title_of_none_differs_from_the_empty_string(
    tmp_path: Path,
) -> None:
    """A missing title and an explicit empty-string title no longer digest the same way."""
    repository = _repository(tmp_path)
    _, _, dataset_id = await _hierarchy(repository)
    await _commit_revision(repository, dataset_id)
    await repository.create_release(
        dataset_id,
        Visibility.ALL,
        tag="v1",
        revision_number=1,
        title=None,
        created_by="alice",
        claim=_claim("release", str(dataset_id), "v1", "1", None, "alice", key="k1"),
    )
    with pytest.raises(IdempotencyKeyReused):
        await repository.create_release(
            dataset_id,
            Visibility.ALL,
            tag="v1",
            revision_number=1,
            title="",
            created_by="alice",
            claim=_claim("release", str(dataset_id), "v1", "1", "", "alice", key="k1"),
        )


async def test_create_release_replay_with_a_different_created_by_is_a_reuse(
    tmp_path: Path,
) -> None:
    """Reusing a release-create key with only ``created_by`` changed is a reuse."""
    repository = _repository(tmp_path)
    _, _, dataset_id = await _hierarchy(repository)
    await _commit_revision(repository, dataset_id)
    await repository.create_release(
        dataset_id,
        Visibility.ALL,
        tag="v1",
        revision_number=1,
        title=None,
        created_by="alice",
        claim=_claim("release", str(dataset_id), "v1", "1", None, "alice", key="k1"),
    )
    with pytest.raises(IdempotencyKeyReused):
        await repository.create_release(
            dataset_id,
            Visibility.ALL,
            tag="v1",
            revision_number=1,
            title=None,
            created_by="bob",
            claim=_claim("release", str(dataset_id), "v1", "1", None, "bob", key="k1"),
        )


async def test_create_release_under_an_invisible_dataset_is_not_found(tmp_path: Path) -> None:
    """A dataset the caller cannot discover is 404, before the revision is ever resolved."""
    repository = _repository(tmp_path)
    _, _, dataset_id = await _hierarchy(repository)
    await _commit_revision(repository, dataset_id)
    with pytest.raises(ResourceNotFound):
        await repository.create_release(
            dataset_id,
            Visibility(),
            tag="v1",
            revision_number=1,
            title=None,
            created_by="alice",
            claim=_claim("release", str(dataset_id), "v1", "1", None, "alice", key="k1"),
        )


async def test_create_release_without_a_registered_revision_is_not_found(tmp_path: Path) -> None:
    """Creating a release naming an unregistered revision raises ``ResourceNotFound``."""
    repository = _repository(tmp_path)
    _, _, dataset_id = await _hierarchy(repository)
    with pytest.raises(ResourceNotFound):
        await repository.create_release(
            dataset_id,
            Visibility.ALL,
            tag="v1",
            revision_number=1,
            title=None,
            created_by="alice",
            claim=_claim("release", str(dataset_id), "v1", "1", None, "alice", key="k1"),
        )


# -- patch_organization / patch_project ------------------------------------


async def test_patch_organization_rejects_a_stale_expected_version(tmp_path: Path) -> None:
    """``patch_organization`` refuses a stale version, raising ``PreconditionFailed``."""
    repository = _repository(tmp_path)
    organization_id, _, _ = await _hierarchy(repository)
    with pytest.raises(PreconditionFailed):
        await repository.patch_organization(
            organization_id,
            Visibility.ALL,
            expected_version=99,
            slug=None,
            title="New",
            description=None,
        )


async def test_patch_organization_updates_description_only(tmp_path: Path) -> None:
    """Patching only the description leaves the title unchanged and still bumps the version."""
    repository = _repository(tmp_path)
    organization_id, _, _ = await _hierarchy(repository)
    patched = await repository.patch_organization(
        organization_id,
        Visibility.ALL,
        expected_version=1,
        slug=None,
        title=None,
        description="updated",
    )
    assert patched.description == "updated"
    assert patched.title == "Astro"
    assert patched.version == 2


async def test_patch_organization_naming_no_field_is_a_no_op(tmp_path: Path) -> None:
    """A patch naming neither ``title`` nor ``description`` writes no new generation document."""
    repository = _repository(tmp_path)
    organization_id, _, _ = await _hierarchy(repository)
    organization = await repository.organization(organization_id, Visibility.ALL)
    before = _generation_files(organization_dir(repository.data_root, organization))

    patched = await repository.patch_organization(
        organization_id,
        Visibility.ALL,
        expected_version=1,
        slug=None,
        title=None,
        description=None,
    )

    assert patched == organization
    after = _generation_files(organization_dir(repository.data_root, organization))
    assert after == before


async def test_patch_project_updates_title_and_description(tmp_path: Path) -> None:
    """Patching a project's title and description updates both and bumps the version."""
    repository = _repository(tmp_path)
    _, project_id, _ = await _hierarchy(repository)
    patched = await repository.patch_project(
        project_id,
        Visibility.ALL,
        expected_version=1,
        slug=None,
        title="Renamed",
        description="updated",
    )
    assert patched.title == "Renamed"
    assert patched.description == "updated"
    assert patched.version == 2


async def test_patch_project_rejects_a_slug_change(tmp_path: Path) -> None:
    """``patch_project`` refuses to change the slug, raising ``SlugImmutable``."""
    repository = _repository(tmp_path)
    _, project_id, _ = await _hierarchy(repository)
    with pytest.raises(SlugImmutable):
        await repository.patch_project(
            project_id,
            Visibility.ALL,
            expected_version=1,
            slug="renamed",
            title=None,
            description=None,
        )


async def test_patch_project_rejects_a_stale_expected_version(tmp_path: Path) -> None:
    """``patch_project`` refuses a stale ``expected_version``, raising ``PreconditionFailed``."""
    repository = _repository(tmp_path)
    _, project_id, _ = await _hierarchy(repository)
    with pytest.raises(PreconditionFailed):
        await repository.patch_project(
            project_id,
            Visibility.ALL,
            expected_version=99,
            slug=None,
            title="New",
            description=None,
        )


async def test_patch_project_naming_no_field_is_a_no_op(tmp_path: Path) -> None:
    """A patch naming neither ``title`` nor ``description`` writes no new generation document."""
    repository = _repository(tmp_path)
    organization_id, project_id, _ = await _hierarchy(repository)
    organization = await repository.organization(organization_id, Visibility.ALL)
    project = await repository.project(project_id, Visibility.ALL)
    before = _generation_files(project_dir(repository.data_root, organization, project))

    patched = await repository.patch_project(
        project_id, Visibility.ALL, expected_version=1, slug=None, title=None, description=None
    )

    assert patched == project
    after = _generation_files(project_dir(repository.data_root, organization, project))
    assert after == before


# -- reads: invisible ids -----------------------------------------------


async def test_organization_project_and_dataset_reads_are_not_found_under_no_visibility(
    tmp_path: Path,
) -> None:
    """Every point read is ``ResourceNotFound`` for a caller with empty ``Visibility``."""
    repository = _repository(tmp_path)
    organization_id, project_id, dataset_id = await _hierarchy(repository)
    for read in (
        lambda: repository.organization(organization_id, Visibility()),
        lambda: repository.project(project_id, Visibility()),
        lambda: repository.dataset(dataset_id, Visibility()),
    ):
        with pytest.raises(ResourceNotFound):
            await read()
