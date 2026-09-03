"""The static role catalog: what each role can do and who may hold it.

The catalog is defined in code, identical on every deployment, and readable
by any credential; there is nothing here to create or change, only the
vocabulary a role binding refers to by code.
"""

from __future__ import annotations

from fastapi import APIRouter

from huron.pkg.catalog.layers import Layer
from huron.pkg.rbac.roles import ROLES, RoleDefinition
from huron.service.api.routes.v1.schema.roles import LayerGrantView, RoleView

router = APIRouter(prefix="/roles", tags=["roles"])


def _role_view(role: RoleDefinition) -> RoleView:
    """Render one role definition as the API publishes it.

    Every collection is sorted, since the role model holds them as
    frozensets whose iteration order is not stable across processes; a
    layer grant that reaches every layer keeps ``layers`` as None rather
    than expanding it.

    Args:
        role: The role definition from the catalog.

    Returns:
        The role's public view.
    """
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
    """List every role in the catalog.

    The role catalog: what each role can do and who may hold it. Each role
    carries its control-plane capabilities, its layer-scoped data-plane
    grants, the scopes it may be bound at and the kinds of principal that
    may hold it. The catalog is fixed per deployment, so the whole of it is
    returned at once and there is nothing to page.
    \f
    Returns:
        Every role, in catalog order.
    """
    return [_role_view(role) for role in ROLES.values()]
