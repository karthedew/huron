"""API keys for programmatic access.

Who-am-I moved to ``GET /auth/session`` (unversioned): an API key is a
resource, so its issuance route stays versioned, but identity introspection
is a login concern, not a v1 resource.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends

from huron.pkg.auth import create_api_key
from huron.service.api.authorization import CurrentPrincipal
from huron.service.api.routes.v1.preconditions import IdempotencyHeader
from huron.service.api.routes.v1.schema.api_keys import CreateApiKey, IssuedApiKey
from huron.service.api.runtime import Repository

router = APIRouter(prefix="/auth/api-keys", tags=["api-keys"])


def _require_idempotency_key(idempotency_key: IdempotencyHeader) -> None:
    """The header is required of this route; its value is not read here."""


@router.post("", status_code=201, dependencies=[Depends(_require_idempotency_key)])
async def issue_api_key(
    body: CreateApiKey,
    repository: Repository,
    actor: CurrentPrincipal,
) -> IssuedApiKey:
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
    await repository.api_keys.add(record)
    return IssuedApiKey(
        id=record.key_id,
        name=record.name,
        scopes=sorted(record.scopes),
        expires_at=record.expires_at,
        secret=token,
    )
