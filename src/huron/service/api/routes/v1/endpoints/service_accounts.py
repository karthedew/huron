"""Service accounts: roleless identities owned by one organization.

Every route hangs under the owning organization, and every one of them
requires ``service_account.manage`` there: accounts are created only by
holders of that capability on the owning organization, who also mint the
keys that authenticate as an account and disable it when its work is done.
A service account holds no roles - its authority is intrinsic to the kind
and reaches only its own organization - and disabling one revokes every
key it holds.
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
    """Return the service account, provided this organization owns it.

    The router's guard proved the caller administers service accounts in
    *this* organization and nothing about any other, so an account owned
    elsewhere is refused even though it exists.

    Args:
        repository: The wired hierarchy repository.
        organization_id: The organization the route is addressed under.
        principal_id: The service account the request named.

    Returns:
        The account, owned by ``organization_id``.

    Raises:
        Forbidden: If the account belongs to a different organization.
    """
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
    """Create a service account in an organization.

    Requires ``service_account.manage`` on the organization. ``name`` must
    be slug-shaped and unique within the organization: a malformed name is
    refused with 400 and a duplicate with 409. The account's subject - the
    identity its keys authenticate as - is derived from the organization's
    slug and the name. An unknown organization is 404.
    \f
    Args:
        organization_id: The organization that will own the account.
        body: The account's name.
        repository: The wired hierarchy repository.
        actor: The administrator creating the account, recorded as its
            creator.

    Returns:
        The account as the API renders it.
    """
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
    """List the service accounts of an organization.

    Requires ``service_account.manage`` on the organization. Accounts are
    ordered by name, disabled ones included. ``after`` continues from the
    cursor a previous page returned; a cursor that is not a valid
    continuation is refused with 400. An unknown organization is 404.
    \f
    Args:
        organization_id: The organization whose accounts to list.
        repository: The wired hierarchy repository.
        limit: The most accounts to return in this page.
        after: The ``next_cursor`` of the previous page, or None for the first.

    Returns:
        One page of service accounts and the cursor to the next, if any.
    """
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
    """Issue an API key that authenticates as a service account.

    Requires ``service_account.manage`` on the organization. The key
    authenticates AS the service account: it carries the account's
    intrinsic authority and nothing of the caller's own. An account owned
    by a different organization, or one that has been disabled, is refused
    with 403; an unknown account is 404. The response is the only time the
    key's secret is shown; it is never stored and cannot be recovered.
    \f
    Args:
        organization_id: The organization that owns the account.
        principal_id: The service account the key is issued for.
        body: The key's name, scopes and lifetime in days.
        repository: The wired hierarchy repository.

    Returns:
        The issued key with its cleartext secret and the subject it
        authenticates as.

    Raises:
        Forbidden: If the service account has been disabled.
    """
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
    """Disable a service account and revoke every key it holds.

    Requires ``service_account.manage`` on the organization. Once disabled,
    no key issued to the account authenticates and no new key can be issued
    for it; the API offers no way to re-enable it. Disabling is idempotent:
    calling it again on an already-disabled account reports the original
    ``disabled_at`` and does not revoke keys a second time. An account
    owned by a different organization is refused with 403; an unknown
    account is 404.
    \f
    Args:
        organization_id: The organization that owns the account.
        principal_id: The service account to disable.
        repository: The wired hierarchy repository.

    Returns:
        The account as the API renders it, with ``disabled_at`` set.
    """
    await _account_in_organization(repository, organization_id, principal_id)
    disabled_at = datetime.now(UTC)
    account = await repository.disable_service_account(principal_id, disabled_at=disabled_at)
    if account.disabled_at is not None and account.disabled_at < disabled_at:
        # Already disabled before this call: its keys were revoked at the
        # original disable and must not be re-processed with a later,
        # wrong timestamp.
        return ServiceAccountView.model_validate(account)
    await repository.api_keys.revoke_all_for(account.subject, disabled_at)
    return ServiceAccountView.model_validate(account)
