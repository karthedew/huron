"""Datasets, release tags, and the layer-scoped data-plane guards."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from huron.pkg.auth import Principal
from huron.pkg.catalog.layers import (
    LAYER_ORDER,
    LAYER_SPECS,
    Layer,
    LayerAction,
    required_capability,
)
from huron.pkg.rbac import Decision, decide
from huron.service.api.authorization import (
    BindingCache,
    CurrentPrincipal,
    LayerWrite,
    as_rbac_principal,
    bindings_for_principal,
    dataset_layer_writer,
    dataset_scope,
    require_dataset,
    require_project,
)
from huron.service.api.problems import problem_response
from huron.service.api.records import Dataset, Release
from huron.service.api.routes.v1.pagination import Page, PageCursor, PageLimit, paginate
from huron.service.api.routes.v1.preconditions import (
    IdempotencyHeader,
    IfMatchHeader,
    expected_version,
)
from huron.service.api.routes.v1.schema.datasets import (
    CreateDataset,
    CreateRelease,
    DatasetView,
    LayerCapabilities,
    LayerView,
    PatchDataset,
    ReleaseView,
    WriteIntent,
)
from huron.service.api.runtime import Repository

project_datasets = APIRouter(prefix="/projects/{project_id}/datasets", tags=["datasets"])
router = APIRouter(prefix="/datasets", tags=["datasets"])


def _key(item: Dataset) -> tuple[str, str]:
    return (item.slug, str(item.id))


def _release_key(item: Release) -> tuple[str]:
    return (item.tag,)


@project_datasets.post(
    "",
    status_code=201,
    dependencies=[Depends(require_project("dataset.create"))],
    responses={
        404: problem_response("no such project"),
        409: problem_response("dataset slug already exists"),
    },
)
def create_dataset(
    project_id: UUID,
    body: CreateDataset,
    idempotency_key: IdempotencyHeader,
    repository: Repository,
) -> DatasetView:
    """Persist one dataset; the durable write runs in the threadpool."""
    return DatasetView.model_validate(
        repository.create_dataset(
            project_id,
            slug=body.slug,
            title=body.title,
            description=body.description,
            profile_name=body.profile_name,
            profile_version=body.profile_version,
            entry_layer=body.entry_layer,
            idempotency_key=idempotency_key,
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
    project_id: UUID, repository: Repository, limit: PageLimit = 50, after: PageCursor = None
) -> Page[DatasetView]:
    return paginate(
        repository.list_datasets(project_id), DatasetView, key=_key, limit=limit, after=after
    )


@router.get("/{dataset_id}", responses={404: problem_response("no such dataset")})
async def get_dataset(dataset_id: UUID, repository: Repository) -> DatasetView:
    return DatasetView.model_validate(repository.get_dataset(dataset_id))


@router.patch(
    "/{dataset_id}",
    dependencies=[Depends(require_dataset("dataset.update"))],
    responses={
        404: problem_response("no such dataset"),
        409: problem_response("the slug on an existing dataset cannot change"),
        412: problem_response("If-Match does not match the current version"),
    },
)
def patch_dataset(
    dataset_id: UUID,
    body: PatchDataset,
    if_match: IfMatchHeader,
    repository: Repository,
) -> DatasetView:
    """Persist the patch; the durable rewrite runs in the threadpool."""
    return DatasetView.model_validate(
        repository.patch_dataset(
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
def create_release(
    dataset_id: UUID,
    body: CreateRelease,
    idempotency_key: IdempotencyHeader,
    repository: Repository,
    actor: Annotated[Principal, Depends(require_dataset("release.create"))],
) -> ReleaseView:
    """Persist one release tag; the durable write runs in the threadpool."""
    return ReleaseView.model_validate(
        repository.create_release(
            dataset_id,
            tag=body.tag,
            revision_number=body.revision_number,
            title=body.title,
            created_by=actor.subject,
            idempotency_key=idempotency_key,
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
    dataset_id: UUID, repository: Repository, limit: PageLimit = 50, after: PageCursor = None
) -> Page[ReleaseView]:
    return paginate(
        repository.list_releases(dataset_id),
        ReleaseView,
        key=_release_key,
        limit=limit,
        after=after,
    )


@router.get(
    "/{dataset_id}/releases/{tag}", responses={404: problem_response("no such release tag")}
)
async def resolve_release(dataset_id: UUID, tag: str, repository: Repository) -> ReleaseView:
    return ReleaseView.model_validate(repository.resolve_release(dataset_id, tag))


@router.get("/{dataset_id}/layers", responses={404: problem_response("no such dataset")})
async def list_layers(
    dataset_id: UUID, actor: CurrentPrincipal, repository: Repository, cache: BindingCache
) -> list[LayerView]:
    """The layer workflow, annotated with what THIS caller may do per layer."""
    dataset = repository.get_dataset(dataset_id)
    scope = dataset_scope(repository, dataset_id)
    rbac_actor = as_rbac_principal(actor)
    bindings = await bindings_for_principal(cache, repository, rbac_actor)

    def may(layer: Layer, action: LayerAction) -> bool:
        capability, layer_code = required_capability(action, layer)
        return decide(bindings, rbac_actor, capability, scope, layer=layer_code) is Decision.ALLOW

    return [
        LayerView(
            layer=layer,
            derived_from=list(LAYER_SPECS[layer].derived_from),
            principal_writable=LAYER_SPECS[layer].principal_writable,
            accepts_direct_entry=LAYER_SPECS[layer].accepts_direct_entry,
            is_entry_layer=layer.value == dataset.entry_layer,
            produced_by=LAYER_SPECS[layer].produced_by,
            caller_may=LayerCapabilities(
                read=may(layer, LayerAction.READ), write=may(layer, LayerAction.WRITE)
            ),
        )
        for layer in LAYER_ORDER
    ]


@router.post(
    "/{dataset_id}/layers/{layer}/write-intents",
    status_code=201,
    responses={404: problem_response("no such dataset")},
)
async def create_write_intent(
    dataset_id: UUID,
    grant: Annotated[LayerWrite, Depends(dataset_layer_writer)],
) -> WriteIntent:
    """Authorize a commit to one layer of one dataset.

    Reaching the body means the layer rule and the role bindings both allow
    the write; the ingest/commit machinery (P2) and the credential vendor
    (P8) hang their work off this authorization.
    """
    return WriteIntent(
        dataset_id=dataset_id,
        layer=grant.layer,
        granted_to=grant.principal.subject,
        principal_kind=grant.principal.kind,
        capability=f"data.write@{grant.layer.value}",
    )
