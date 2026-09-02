"""The static role catalog: what each role can do and who may hold it."""

from __future__ import annotations

from fastapi import APIRouter

from huron.pkg.catalog.layers import Layer
from huron.pkg.rbac.roles import ROLES, RoleDefinition
from huron.service.api.routes.v1.schema.roles import LayerGrantView, RoleView

router = APIRouter(prefix="/roles", tags=["roles"])


def _role_view(role: RoleDefinition) -> RoleView:
    return RoleView(
        code=role.code,
        title=role.title,
        description=role.description,
        capabilities=sorted(role.capabilities),
        layer_grants=[
            LayerGrantView(
                capability=grant.capability,
                layers=sorted(Layer(layer) for layer in grant.layers)
                if grant.layers is not None
                else None,
            )
            for grant in role.layer_grants
        ],
        bindable_scopes=sorted(role.bindable_scopes),
        allowed_principal_kinds=sorted(role.allowed_principal_kinds),
    )


@router.get("")
async def list_roles() -> list[RoleView]:
    """The role catalog: what each role can do and who may hold it."""
    return [_role_view(role) for role in ROLES.values()]
