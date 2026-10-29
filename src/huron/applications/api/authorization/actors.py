"""``current_actor``: a Huron bearer token becomes the request's actor."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from huron.applications.api.dependencies import RuntimeDep
from huron.core.security.rbac import Actor
from huron.pkg.errors import Unauthenticated

__all__ = ["ActorDep", "current_actor"]


async def current_actor(request: Request, runtime: RuntimeDep) -> Actor:
    """The actor named by the ``Authorization: Bearer`` Huron token."""
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise Unauthenticated("a Huron bearer token is required")
    claims = (await runtime.verifier()).verify(token.strip())
    return Actor(claims.sub, claims.name, frozenset(claims.groups))


ActorDep = Annotated[Actor, Depends(current_actor)]
