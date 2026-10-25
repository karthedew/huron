"""API keys for programmatic access, issued to the calling principal.

A key is minted for whoever calls and never for anyone else: it inherits the
caller's subject and kind, so it can do exactly what the caller's own role
bindings allow and nothing more. Identity comes from the request credential;
API-key issuance belongs to the versioned resource API.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends

from huron.applications.api.authorization import CurrentPrincipal
from huron.applications.api.dependencies import Identity
from huron.applications.api.routes.preconditions import IdempotencyHeader
from huron.applications.api.routes.v1.schema.api_keys import CreateApiKey, IssuedApiKey

router = APIRouter(prefix="/auth/api-keys", tags=["api-keys"])


def _require_idempotency_key(idempotency_key: IdempotencyHeader) -> None:
    """Require an ``Idempotency-Key`` header without reading its value.

    The header is required of this route; its value is not read here.

    Args:
        idempotency_key: The caller's ``Idempotency-Key`` header, whose
            presence is all this dependency checks.
    """


@router.post("", status_code=201, dependencies=[Depends(_require_idempotency_key)])
async def issue_api_key(
    body: CreateApiKey,
    identity: Identity,
    actor: CurrentPrincipal,
) -> IssuedApiKey:
    """Issue an API key for the calling principal.

    The key is issued to the CALLING principal and keys never escalate: it
    inherits the caller's subject and kind, so everything the key can do is
    exactly what the caller's role bindings already allow. An
    ``Idempotency-Key`` header is required. The response is the only time
    the key's secret is shown; it is never stored and cannot be recovered,
    so a caller that loses it issues another key.
    \f
    Args:
        body: The key's name, scopes, optional project restriction and
            lifetime in days.
        identity: The actor-bound identity service.
        actor: The authenticated caller the key is issued to.

    Returns:
        The issued key with its cleartext secret.
    """
    record, token = await identity.issue_key(
        name=body.name,
        scopes=frozenset(body.scopes),
        project_id=body.project_id,
        ttl=timedelta(days=body.expires_in_days),
    )
    return IssuedApiKey(
        id=record.key_id,
        name=record.name,
        scopes=sorted(record.scopes),
        expires_at=record.expires_at,
        secret=token,
    )
