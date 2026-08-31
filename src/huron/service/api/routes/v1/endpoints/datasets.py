"""Datasets, release tags, and the layer-scoped data-plane guards."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from huron.pkg.auth import Principal
from huron.pkg.catalog.layers import (
    LAYER_ORDER,
    LAYER_SPECS,
    LayerAction,
    required_capability,
)
from huron.pkg.rbac import Decision, decide
from huron.service.api.authorization import (
    CurrentPrincipal,
    LayerWrite,
    as_rbac_principal,
    cached_bindings_for,
    dataset_layer_writer,
    dataset_scope,
    get_repository,
    require_dataset,
    require_project,
)
from huron.service.api.routes.v1.common import (
    IdempotencyHeader,
    IfMatchHeader,
    expected_version,
    jsonable,
    page,
)
from huron.service.api.routes.v1.schema.datasets import CreateDataset, CreateRelease, PatchDataset

router = APIRouter()


@router.post("/projects/{project_id}/datasets", status_code=201)
async def create_dataset(
    request: Request,
    project_id: UUID,
    body: CreateDataset,
    idempotency_key: IdempotencyHeader,
    _actor: Annotated[Principal, Depends(require_project("dataset.create"))],
) -> dict[str, object]:
    return jsonable(
        get_repository(request).create_dataset(
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


@router.get("/projects/{project_id}/datasets")
async def list_datasets(
    request: Request, project_id: UUID, _actor: CurrentPrincipal, limit: int = 50
) -> dict[str, object]:
    repository = get_repository(request)
    repository.get_project(project_id)
    items = [item for item in repository.datasets.values() if item.project_id == project_id]
    return page(sorted(items, key=lambda item: (item.slug, item.id)), limit)


@router.get("/datasets/{dataset_id}")
async def get_dataset(
    request: Request, dataset_id: UUID, _actor: CurrentPrincipal
) -> dict[str, object]:
    return jsonable(get_repository(request).get_dataset(dataset_id))


@router.patch("/datasets/{dataset_id}")
async def patch_dataset(
    request: Request,
    dataset_id: UUID,
    body: PatchDataset,
    if_match: IfMatchHeader,
    _actor: Annotated[Principal, Depends(require_dataset("dataset.update"))],
) -> dict[str, object]:
    return jsonable(
        get_repository(request).patch_dataset(
            dataset_id,
            expected_version=expected_version(if_match),
            slug=body.slug,
            title=body.title,
            description=body.description,
        )
    )


@router.post("/datasets/{dataset_id}/releases", status_code=201)
async def create_release(
    request: Request,
    dataset_id: UUID,
    body: CreateRelease,
    idempotency_key: IdempotencyHeader,
    actor: Annotated[Principal, Depends(require_dataset("release.create"))],
) -> dict[str, object]:
    return jsonable(
        get_repository(request).create_release(
            dataset_id,
            tag=body.tag,
            revision_number=body.revision_number,
            title=body.title,
            created_by=actor.subject,
            idempotency_key=idempotency_key,
        )
    )


@router.get("/datasets/{dataset_id}/releases")
async def list_releases(
    request: Request, dataset_id: UUID, _actor: CurrentPrincipal
) -> dict[str, object]:
    repository = get_repository(request)
    repository.get_dataset(dataset_id)
    items = [
        item
        for (item_dataset_id, _), item in repository.releases.items()
        if item_dataset_id == dataset_id
    ]
    return {"items": [jsonable(item) for item in sorted(items, key=lambda item: item.tag)]}


@router.get("/datasets/{dataset_id}/releases/{tag}")
async def resolve_release(
    request: Request, dataset_id: UUID, tag: str, _actor: CurrentPrincipal
) -> dict[str, object]:
    return jsonable(get_repository(request).resolve_release(dataset_id, tag))


@router.get("/datasets/{dataset_id}/layers")
async def list_layers(
    request: Request, dataset_id: UUID, actor: CurrentPrincipal
) -> dict[str, object]:
    """The layer workflow, annotated with what THIS caller may do per layer."""
    repository = get_repository(request)
    dataset = repository.get_dataset(dataset_id)
    scope = dataset_scope(repository, dataset_id)
    rbac_actor = as_rbac_principal(actor)
    bindings = await cached_bindings_for(request, repository, rbac_actor.identifiers)
    items: list[dict[str, object]] = []
    for layer in LAYER_ORDER:
        spec = LAYER_SPECS[layer]
        allowed: dict[str, bool] = {}
        for action in (LayerAction.READ, LayerAction.WRITE):
            capability, layer_code = required_capability(action, layer)
            allowed[action.value] = (
                decide(bindings, rbac_actor, capability, scope, layer=layer_code) is Decision.ALLOW
            )
        items.append(
            {
                "layer": layer.value,
                "derived_from": [item.value for item in spec.derived_from],
                "principal_writable": spec.principal_writable,
                "accepts_direct_entry": spec.accepts_direct_entry,
                "is_entry_layer": layer.value == dataset.entry_layer,
                "produced_by": spec.produced_by,
                "caller_may": allowed,
            }
        )
    return {"items": items}


@router.post("/datasets/{dataset_id}/layers/{layer}/write-intents", status_code=201)
async def create_write_intent(
    dataset_id: UUID,
    grant: Annotated[LayerWrite, Depends(dataset_layer_writer)],
) -> dict[str, object]:
    """Authorize a commit to one layer of one dataset.

    Reaching the body means the layer rule and the role bindings both allow
    the write; the ingest/commit machinery (P2) and the credential vendor
    (P8) hang their work off this authorization.
    """
    return {
        "dataset_id": str(dataset_id),
        "layer": grant.layer.value,
        "granted_to": grant.principal.subject,
        "principal_kind": grant.principal.kind,
        "capability": f"data.write@{grant.layer.value}",
    }
