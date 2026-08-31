"""API keys for programmatic access.

Who-am-I moved to ``GET /auth/session`` (unversioned): an API key is a
resource, so its issuance route stays versioned, but identity introspection
is a login concern, not a v1 resource.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Request

from huron.pkg.auth import create_api_key
from huron.service.api.authorization import CurrentPrincipal, get_repository
from huron.service.api.routes.v1.common import IdempotencyHeader
from huron.service.api.routes.v1.schema.auth import CreateApiKey

router = APIRouter()


@router.post("/auth/api-keys", status_code=201)
async def issue_api_key(
    request: Request,
    body: CreateApiKey,
    actor: CurrentPrincipal,
    _idempotency_key: IdempotencyHeader,
) -> dict[str, object]:
    """Issue a key for the CALLING principal - keys never escalate.

    The key inherits the caller's subject and kind, so everything the key can
    do is exactly what the caller's role bindings already allow.
    """
    record, token = create_api_key(
        actor.subject,
        name=body.name,
        scopes=frozenset(body.scopes),
        project_id=body.project_id,
        ttl=timedelta(days=body.expires_in_days),
        owner_kind=actor.kind,
    )
    await get_repository(request).api_keys.add(record)
    return {
        "id": record.key_id,
        "name": record.name,
        "secret": token,
        "scopes": sorted(record.scopes),
        "expires_at": record.expires_at,
    }
