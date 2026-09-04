"""``PostgresRbacStore`` translates a unique-constraint violation into its named conflict error.

The SQL itself is proven against a real database in
``tests/contract/test_rbac_store.py``; this pins only the translation,
against a fake pool that stands in for the database returning the one
error code each site is written to catch, rather than letting a raw
``asyncpg`` exception escape the storage seam.
"""

from __future__ import annotations

from typing import cast
from uuid import uuid4

import asyncpg
import pytest

from huron.pkg.catalog.errors import ResourceNotFound
from huron.pkg.rbac import ScopeType
from huron.pkg.rbac.roles import ScopeNotBindable
from huron.service.api.errors import (
    AttachmentExists,
    BindingExists,
    ServiceAccountExists,
    UsernameTaken,
)
from huron.service.api.stores import PostgresRbacStore

pytestmark = pytest.mark.unit

#: The constraint names Postgres assigns the two UNIQUE constraints a
#: service-account insert can hit, mirroring stores/rbac.py's own constants.
_SERVICE_ACCOUNT_NAME_CONSTRAINT = "service_accounts_organization_id_name_key"
_PRINCIPAL_SUBJECT_CONSTRAINT = "principals_subject_key"


def _unique_violation(constraint_name: str | None) -> asyncpg.UniqueViolationError:
    """Builds a ``UniqueViolationError`` carrying the given ``constraint_name``, as asyncpg does."""
    exc = asyncpg.UniqueViolationError("duplicate")
    exc.constraint_name = constraint_name
    return exc


def _check_violation() -> asyncpg.exceptions.CheckViolationError:
    """Builds a bare ``CheckViolationError``, as asyncpg raises for a failed CHECK constraint."""
    return asyncpg.exceptions.CheckViolationError("check constraint violated")


class _FakePool:
    """Stands in for ``asyncpg.Pool``; every ``execute`` raises the given error.

    As if a unique index had refused the insert.
    """

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def execute(self, *args: object, **kwargs: object) -> str:
        raise self._exc

    def acquire(self) -> _FakeAcquireContext:
        return _FakeAcquireContext(self._exc)


class _FakeAcquireContext:
    """An async context manager that yields a ``_FakeConnection`` wrapping the given error."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def __aenter__(self) -> _FakeConnection:
        return _FakeConnection(self._exc)

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


class _FakeConnection:
    """A fake connection whose ``execute`` raises the given error; its transaction is a no-op."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def transaction(self) -> _FakeTransactionContext:
        return _FakeTransactionContext()

    async def execute(self, *args: object, **kwargs: object) -> str:
        raise self._exc


class _FakeTransactionContext:
    """A no-op async transaction context manager."""

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


def _store_that_refuses_with(exc: Exception) -> PostgresRbacStore:
    """Build a ``PostgresRbacStore`` backed by a pool whose every write raises ``exc``."""
    return PostgresRbacStore(cast("asyncpg.Pool", _FakePool(exc)))


async def test_grant_role_translates_a_unique_violation_into_binding_exists() -> None:
    """``grant_role`` translates a unique violation on the binding into ``BindingExists``."""
    store = _store_that_refuses_with(asyncpg.UniqueViolationError("duplicate"))
    with pytest.raises(BindingExists):
        await store.grant_role(
            principal="user:bob",
            role_code="platform_owner",
            scope_type=ScopeType.SYSTEM,
            scope_id=None,
            created_by="alice",
        )


async def test_create_service_account_translates_a_name_collision() -> None:
    """A collision on the organization/name constraint becomes ``ServiceAccountExists``."""
    store = _store_that_refuses_with(_unique_violation(_SERVICE_ACCOUNT_NAME_CONSTRAINT))
    with pytest.raises(ServiceAccountExists):
        await store.create_service_account(uuid4(), name="dup", subject="org/dup", created_by="a")


async def test_create_service_account_translates_a_subject_collision() -> None:
    """A collision on ``principals.subject`` is ``UsernameTaken``, not ``ServiceAccountExists``.

    The two UNIQUE constraints an insert can hit mean two different
    conflicts: this one says some other principal already holds the
    derived subject, not that the organization already has this name.
    """
    store = _store_that_refuses_with(_unique_violation(_PRINCIPAL_SUBJECT_CONSTRAINT))
    with pytest.raises(UsernameTaken):
        await store.create_service_account(uuid4(), name="new", subject="org/taken", created_by="a")


async def test_create_service_account_translates_a_foreign_key_violation() -> None:
    """An unknown ``organization_id`` becomes ``ResourceNotFound``, not a raw foreign key error."""
    store = _store_that_refuses_with(asyncpg.ForeignKeyViolationError("violates foreign key"))
    with pytest.raises(ResourceNotFound):
        await store.create_service_account(
            uuid4(), name="orphan", subject="nowhere/orphan", created_by="a"
        )


async def test_create_service_account_reraises_an_unmapped_unique_violation() -> None:
    """A unique violation on neither known constraint is left for the caller, not misreported."""
    store = _store_that_refuses_with(_unique_violation("some_other_constraint"))
    with pytest.raises(asyncpg.UniqueViolationError):
        await store.create_service_account(uuid4(), name="new", subject="org/new", created_by="a")


async def test_create_policy_translates_a_check_violation_into_value_error() -> None:
    """A ``policy_type`` that fails the column's CHECK is refused with ``ValueError``, not a 500."""
    store = _store_that_refuses_with(_check_violation())
    with pytest.raises(ValueError, match="policy_type"):
        await store.create_policy(
            policy_type="not a valid type", name="bad", spec={}, created_by="alice"
        )


async def test_attach_policy_translates_a_foreign_key_violation() -> None:
    """An unknown ``policy_id`` becomes ``ResourceNotFound``, not a raw foreign key error."""
    store = _store_that_refuses_with(asyncpg.ForeignKeyViolationError("violates foreign key"))
    with pytest.raises(ResourceNotFound):
        await store.attach_policy(
            uuid4(),
            scope_type=ScopeType.ORGANIZATION,
            scope_id=uuid4(),
            attached_by="alice",
        )


async def test_attach_policy_translates_a_unique_violation_into_attachment_exists() -> None:
    """``attach_policy`` translates a unique violation into ``AttachmentExists``."""
    store = _store_that_refuses_with(asyncpg.UniqueViolationError("duplicate"))
    with pytest.raises(AttachmentExists):
        await store.attach_policy(
            uuid4(),
            scope_type=ScopeType.ORGANIZATION,
            scope_id=uuid4(),
            attached_by="alice",
        )


async def test_attach_policy_translates_a_check_violation() -> None:
    """A ``scope_type`` the CHECK refuses becomes ``ScopeNotBindable``, not a 500."""
    store = _store_that_refuses_with(_check_violation())
    with pytest.raises(ScopeNotBindable):
        await store.attach_policy(
            uuid4(),
            scope_type=ScopeType.SYSTEM,
            scope_id=uuid4(),
            attached_by="alice",
        )
