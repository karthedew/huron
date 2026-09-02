"""Service accounts: roleless identities created only by holders of
``service_account.manage`` on the owning organization.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from huron.pkg.auth import Principal, create_api_key
from huron.service.api.authorization import require_organization
from huron.service.api.errors import Forbidden
from huron.service.api.problems import problem_response
from huron.service.api.records import ServiceAccount
from huron.service.api.routes.v1.pagination import Page, PageCursor, PageLimit, paginate
from huron.service.api.routes.v1.schema.api_keys import CreateApiKey
from huron.service.api.routes.v1.schema.service_accounts import (
    CreateServiceAccount,
    IssuedServiceAccountKey,
    ServiceAccountView,
)
from huron.service.api.runtime import Repository

_manage = require_organization("service_account.manage")
router = APIRouter(
    prefix="/organizations/{organization_id}/service-accounts",
    tags=["service-accounts"],
    dependencies=[Depends(_manage)],
)


def _key(item: ServiceAccount) -> tuple[str]:
    return (item.name,)


async def _account_in_organization(
    repository: Repository, organization_id: UUID, principal_id: UUID
) -> ServiceAccount:
    account = await repository.get_service_account(principal_id)
    if account.organization_id != organization_id:
        raise Forbidden("service account belongs to a different organization")
    return account


@router.post(
    "",
    status_code=201,
    responses={
        404: problem_response("no such organization"),
        409: problem_response("service account already exists"),
    },
)
async def create_service_account(
    organization_id: UUID,
    body: CreateServiceAccount,
    repository: Repository,
    actor: Annotated[Principal, Depends(_manage)],
) -> ServiceAccountView:
    record = await repository.create_service_account(
        organization_id, name=body.name, created_by=actor.subject
    )
    return ServiceAccountView.model_validate(record)


@router.get(
    "",
    responses={
        404: problem_response("no such organization"),
        400: problem_response("cursor is not a valid continuation"),
    },
)
async def list_service_accounts(
    organization_id: UUID, repository: Repository, limit: PageLimit = 50, after: PageCursor = None
) -> Page[ServiceAccountView]:
    records = await repository.list_service_accounts(organization_id)
    return paginate(
        sorted(records, key=_key), ServiceAccountView, key=_key, limit=limit, after=after
    )


@router.post(
    "/{principal_id}/api-keys",
    status_code=201,
    responses={404: problem_response("no such service account")},
)
async def issue_service_account_key(
    organization_id: UUID,
    principal_id: UUID,
    body: CreateApiKey,
    repository: Repository,
) -> IssuedServiceAccountKey:
    """Mint a key that authenticates AS the service account."""
    account = await _account_in_organization(repository, organization_id, principal_id)
    if account.disabled_at is not None:
        raise Forbidden("service account is disabled")
    record, token = create_api_key(
        account.subject,
        name=body.name,
        scopes=frozenset(body.scopes),
        ttl=timedelta(days=body.expires_in_days),
        owner_kind="service_account",
    )
    await repository.api_keys.add(record)
    return IssuedServiceAccountKey(
        id=record.key_id,
        name=record.name,
        scopes=sorted(record.scopes),
        expires_at=record.expires_at,
        secret=token,
        subject=account.subject,
    )


@router.post(
    "/{principal_id}/disable", responses={404: problem_response("no such service account")}
)
async def disable_service_account(
    organization_id: UUID,
    principal_id: UUID,
    repository: Repository,
) -> ServiceAccountView:
    await _account_in_organization(repository, organization_id, principal_id)
    disabled_at = datetime.now(UTC)
    account = await repository.disable_service_account(principal_id, disabled_at=disabled_at)
    await repository.api_keys.revoke_all_for(account.subject, disabled_at)
    return ServiceAccountView.model_validate(account)
