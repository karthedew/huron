"""Token exchange and the caller's identity."""

from __future__ import annotations

from fastapi import APIRouter

from huron.applications.api.authorization import ActorDep
from huron.applications.api.dependencies import RuntimeDep
from huron.applications.api.routes.v1.schema.auth import ExchangeIn, ExchangeOut, RoleOut, WhoAmI
from huron.core.security.rbac import Authorizer

__all__ = ["router"]

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/exchange")
async def exchange(body: ExchangeIn, runtime: RuntimeDep) -> ExchangeOut:
    """Exchange a company ID token for a Huron token carrying the user's LDAP groups."""
    result = await (await runtime.exchange()).exchange(body.company_token)
    claims = result.claims
    return ExchangeOut(
        huron_token=result.token,
        expires_at=claims.exp,
        subject=claims.sub,
        name=claims.name,
        groups=list(claims.groups),
    )


@router.get("/whoami")
async def whoami(actor: ActorDep, runtime: RuntimeDep) -> WhoAmI:
    """The caller, their groups and the roles those groups hold now."""
    async with runtime.store.transaction() as tx:
        roles = await Authorizer(tx.grants).roles_for(actor)
    return WhoAmI(
        subject=actor.subject,
        name=actor.display_name,
        groups=sorted(actor.groups),
        roles=[
            RoleOut(
                scope=str(scope.type),
                scope_id=None if scope.id is None else str(scope.id),
                role=str(role),
            )
            for scope, role in sorted(
                roles, key=lambda pair: (str(pair[0].type), str(pair[0].id), pair[1])
            )
        ],
    )
