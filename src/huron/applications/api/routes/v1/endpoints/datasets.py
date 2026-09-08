"""Datasets, release tags, and the layer workflow's read side.

Creating a dataset hangs under its project and needs ``dataset.create``
there; everything else is addressed by dataset id. Reading a dataset, its
releases or its layer workflow needs only a credential and the caller's
visibility, editing needs ``dataset.update``, and tagging a release needs
``release.create``. Slugs are chosen once, at creation, and never change.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from huron.applications.api.authorization import (
    BindingCache,
    CurrentPrincipal,
    CurrentVisibility,
    require_dataset,
    require_project,
)
from huron.applications.api.dependencies import Catalog as Repository
from huron.applications.api.problems import problem_response
from huron.applications.api.routes.v1.pagination import (
    Page,
    PageCursor,
    PageLimit,
    page,
    slug_cursor_key,
    tag_cursor_key,
)
from huron.applications.api.routes.v1.preconditions import (
    IdempotencyHeader,
    IfMatchHeader,
    expected_version,
)
from huron.applications.api.routes.v1.schema.datasets import (
    CreateDataset,
    CreateRelease,
    DatasetView,
    LayerView,
    PatchDataset,
    ReleaseView,
)
from huron.core.idempotency import request_sha256
from huron.pkg.auth import Principal
from huron.pkg.catalog.records import Dataset, Release
from huron.pkg.metastore import IdempotencyClaim

project_datasets = APIRouter(prefix="/projects/{project_id}/datasets", tags=["datasets"])
router = APIRouter(prefix="/datasets", tags=["datasets"])


def _key(item: Dataset) -> tuple[str, str]:
    return (item.slug, str(item.id))


def _release_key(item: Release) -> tuple[str]:
    return (item.tag,)


@project_datasets.post(
    "",
    status_code=201,
    responses={
        404: problem_response("no such project"),
        409: problem_response("dataset slug already exists"),
    },
)
async def create_dataset(
    project_id: UUID,
    body: CreateDataset,
    idempotency_key: IdempotencyHeader,
    repository: Repository,
    visibility: CurrentVisibility,
    actor: Annotated[Principal, Depends(require_project("dataset.create"))],
) -> DatasetView:
    """Create a dataset in a project.

    Requires ``dataset.create`` on the project. The slug must be unique
    within the project and can never change afterwards; a duplicate is
    refused with 409. ``entry_layer`` names where the dataset's data first
    arrives: ``raw`` by default, or ``bronze`` or ``silver`` for data the
    lake does not originate. The dataset is active from creation. A project
    id that is absent or not discoverable by the caller is 404. Replaying
    the same ``Idempotency-Key`` with the same request returns the original
    dataset instead of a 409; reusing the key for a different request is
    refused with 409.
    \f
    Args:
        project_id: The project the dataset belongs to.
        body: The slug, title, description, profile and entry layer to store.
        idempotency_key: The caller's ``Idempotency-Key`` header.
        repository: The wired hierarchy repository.
        visibility: The caller's discovery rights, used to resolve
            ``project_id``.
        actor: The caller, whose subject scopes the idempotency claim.

    Returns:
        The dataset as the API renders it.
    """
    claim = IdempotencyClaim(
        principal=actor.subject,
        key=idempotency_key,
        request_sha256=request_sha256(
            "dataset",
            str(project_id),
            body.slug,
            body.title,
            body.description,
            body.profile_name,
            body.profile_version,
            body.entry_layer,
        ),
    )
    return DatasetView.model_validate(
        await repository.create_dataset(
            project_id,
            slug=body.slug,
            title=body.title,
            description=body.description,
            profile_name=body.profile_name,
            profile_version=body.profile_version,
            entry_layer=body.entry_layer,
            claim=claim,
        )
    )


@project_datasets.get(
    "",
    responses={
        404: problem_response("no such project"),
        400: problem_response("cursor is not a valid continuation"),
    },
)
async def list_datasets(
    project_id: UUID,
    repository: Repository,
    visibility: CurrentVisibility,
    limit: PageLimit = 50,
    after: PageCursor = None,
) -> Page[DatasetView]:
    """List the datasets of a project that the caller may discover.

    Datasets are ordered by slug. ``after`` continues from the cursor a
    previous page returned; a cursor that is not a valid continuation is
    refused with 400. A project id that is absent or not discoverable by
    the caller is 404, never an empty page.
    \f
    Args:
        project_id: The project whose datasets to list.
        repository: The wired hierarchy repository.
        visibility: The caller's discovery rights.
        limit: The most datasets to return in this page.
        after: The ``next_cursor`` of the previous page, or None for the first.

    Returns:
        One page of datasets and the cursor to the next, if any.
    """
    window = await repository.datasets(project_id, limit=limit, after=slug_cursor_key(after))
    return page(window, DatasetView, key=_key)


@router.get("/{dataset_id}", responses={404: problem_response("no such dataset")})
async def get_dataset(
    dataset_id: UUID, repository: Repository, visibility: CurrentVisibility
) -> DatasetView:
    """Fetch one dataset by id.

    An id that is absent or not discoverable by the caller is 404.
    \f
    Args:
        dataset_id: The dataset to fetch.
        repository: The wired hierarchy repository.
        visibility: The caller's discovery rights.

    Returns:
        The dataset as the API renders it, including the ``version`` that
        ``If-Match`` carries back on a PATCH.
    """
    dataset = await repository.dataset(dataset_id)
    return DatasetView.model_validate(dataset)


@router.patch(
    "/{dataset_id}",
    responses={
        404: problem_response("no such dataset"),
        409: problem_response("the slug on an existing dataset cannot change"),
        412: problem_response("If-Match does not match the current version"),
    },
)
async def patch_dataset(
    dataset_id: UUID,
    body: PatchDataset,
    if_match: IfMatchHeader,
    repository: Repository,
    visibility: CurrentVisibility,
    _actor: Annotated[Principal, Depends(require_dataset("dataset.update"))],
) -> DatasetView:
    """Update a dataset's title or description.

    Requires ``dataset.update`` on the dataset. ``If-Match`` must carry the
    dataset's current ``version``; a stale value is refused with 412 and
    nothing changes, and a header that does not name a version at all is
    refused with 422. Slugs are immutable: a ``slug`` that differs from the
    current one is refused with 409. Every successful update advances
    ``version`` by one. An id that is absent or not discoverable by the
    caller is 404.
    \f
    Args:
        dataset_id: The dataset to update.
        body: The fields to change; a field left out or null keeps its value.
        if_match: The caller's ``If-Match`` header.
        repository: The wired hierarchy repository.
        visibility: The caller's discovery rights.
        _actor: The caller, held only as proof the capability check passed.

    Returns:
        The updated dataset as the API renders it.
    """
    return DatasetView.model_validate(
        await repository.patch_dataset(
            dataset_id,
            expected_version=expected_version(if_match),
            slug=body.slug,
            title=body.title,
            description=body.description,
        )
    )


@router.post(
    "/{dataset_id}/releases",
    status_code=201,
    responses={
        404: problem_response("no such dataset"),
        409: problem_response("release tag already exists"),
    },
)
async def create_release(
    dataset_id: UUID,
    body: CreateRelease,
    idempotency_key: IdempotencyHeader,
    repository: Repository,
    visibility: CurrentVisibility,
    actor: Annotated[Principal, Depends(require_dataset("release.create"))],
) -> ReleaseView:
    """Tag a revision of a dataset as a release.

    Requires ``release.create`` on the dataset. A tag resolves to exactly
    one revision, forever: a tag the dataset already has is refused with
    409, and the revision it names must already exist or the request is
    404, as is a dataset id that is absent or not discoverable by the
    caller. Replaying the same ``Idempotency-Key`` with the same request
    returns the original release instead of a 409; reusing the key for a
    different request is refused with 409.
    \f
    Args:
        dataset_id: The dataset whose revision is being tagged.
        body: The tag, the revision number it names and an optional title.
        idempotency_key: The caller's ``Idempotency-Key`` header.
        repository: The wired hierarchy repository.
        visibility: The caller's discovery rights, used to resolve
            ``dataset_id``.
        actor: The caller, recorded as the release's creator and whose
            subject scopes the idempotency claim.

    Returns:
        The release as the API renders it.
    """
    claim = IdempotencyClaim(
        principal=actor.subject,
        key=idempotency_key,
        request_sha256=request_sha256(
            "release",
            str(dataset_id),
            body.tag,
            str(body.revision_number),
            body.title,
            actor.subject,
        ),
    )
    return ReleaseView.model_validate(
        await repository.create_release(
            dataset_id,
            tag=body.tag,
            revision_number=body.revision_number,
            title=body.title,
            created_by=actor.subject,
            claim=claim,
        )
    )


@router.get(
    "/{dataset_id}/releases",
    responses={
        404: problem_response("no such dataset"),
        400: problem_response("cursor is not a valid continuation"),
    },
)
async def list_releases(
    dataset_id: UUID,
    repository: Repository,
    visibility: CurrentVisibility,
    limit: PageLimit = 50,
    after: PageCursor = None,
) -> Page[ReleaseView]:
    """List the releases of a dataset the caller may discover.

    Releases are ordered by tag. ``after`` continues from the cursor a
    previous page returned; a cursor that is not a valid continuation is
    refused with 400. A dataset id that is absent or not discoverable by
    the caller is 404, never an empty page.
    \f
    Args:
        dataset_id: The dataset whose releases to list.
        repository: The wired hierarchy repository.
        visibility: The caller's discovery rights.
        limit: The most releases to return in this page.
        after: The ``next_cursor`` of the previous page, or None for the first.

    Returns:
        One page of releases and the cursor to the next, if any.
    """
    window = await repository.releases(dataset_id, limit=limit, after=tag_cursor_key(after))
    return page(window, ReleaseView, key=_release_key)


@router.get(
    "/{dataset_id}/releases/{tag}", responses={404: problem_response("no such release tag")}
)
async def resolve_release(
    dataset_id: UUID, tag: str, repository: Repository, visibility: CurrentVisibility
) -> ReleaseView:
    """Resolve a release tag to the revision it names.

    A tag resolves to the same revision forever. A tag the dataset does not
    have is 404, and so is a tag on a dataset that is absent or not
    discoverable by the caller.
    \f
    Args:
        dataset_id: The dataset the tag belongs to.
        tag: The release tag to resolve.
        repository: The wired hierarchy repository.
        visibility: The caller's discovery rights.

    Returns:
        The release, including the id and number of the revision it names.
    """
    release = await repository.release(dataset_id, tag)
    return ReleaseView.model_validate(release)


@router.get("/{dataset_id}/layers", responses={404: problem_response("no such dataset")})
async def list_layers(
    dataset_id: UUID,
    actor: CurrentPrincipal,
    repository: Repository,
    cache: BindingCache,
    visibility: CurrentVisibility,
) -> list[LayerView]:
    """List a dataset's layer workflow, annotated with what the caller may do in each layer.

    Every layer is returned in promotion order (raw, bronze, silver, gold)
    with what a promotion into it may read from, whether human principals
    may write it, whether data may enter the lake there directly, whether it
    is this dataset's entry layer, which deployable produces it, and - for
    THIS caller - whether they may read and write it. A dataset id that is
    absent or not discoverable by the caller is 404.
    \f
    Args:
        dataset_id: The dataset whose layers to describe.
        actor: The authenticated caller whose permissions annotate each layer.
        repository: The wired hierarchy repository.
        cache: The per-request role-binding cache.
        visibility: The caller's discovery rights, used to resolve
            ``dataset_id``.

    Returns:
        One entry per layer, in promotion order.
    """
    return [LayerView.model_validate(item) for item in await repository.layers(dataset_id)]
