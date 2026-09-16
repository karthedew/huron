"""``PostgresCredentialStore`` tells an unknown principal apart from one of the wrong kind.

The SQL itself is proven against a real database in
``tests/contract/test_auth_store.py``; this pins only the translation,
against a fake pool that stands in for the database returning the trigger's
one error message for both an unknown principal and a service account,
rather than letting a raw ``asyncpg`` exception escape the storage seam.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import asyncpg
import pytest

from huron.core.security.password import CredentialRecord
from huron.core.foundation.errors import ResourceNotFound
from huron.core.security.errors import PrincipalKindMismatch
from huron.core.metastore import PostgresCredentialStore

pytestmark = pytest.mark.unit


class _FakePool:
    """Stands in for ``asyncpg.Pool``: ``execute`` raises a trigger error, ``fetchval`` answers it.

    ``kind`` is what the fallback lookup ``upsert`` runs after the trigger
    fires finds for the principal: None for "does not exist", a string for
    its actual kind. ``row`` is what ``get`` reads back, or None for no
    stored credential.
    """

    def __init__(self, *, kind: str | None = None, row: dict[str, object] | None = None) -> None:
        self._kind = kind
        self._row = row

    async def execute(self, *args: object, **kwargs: object) -> str:
        raise asyncpg.exceptions.RaiseError(
            "local_credentials.principal_id must reference a user principal"
        )

    async def fetchval(self, *args: object, **kwargs: object) -> str | None:
        return self._kind

    async def fetchrow(self, *args: object, **kwargs: object) -> dict[str, object] | None:
        return self._row


def _record(principal_id: object = None) -> CredentialRecord:
    """Builds a credential fixture for ``principal_id``, or a fresh random one."""
    return CredentialRecord(
        principal_id=principal_id or uuid4(),
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ$aGFzaGVkcGFzc3dvcmQ",
        updated_at=datetime.now(UTC),
        updated_by="admin",
    )


async def test_get_returns_none_for_an_unknown_principal() -> None:
    """``get`` returns None rather than raising when no credential row exists."""
    store = PostgresCredentialStore(cast("asyncpg.Pool", _FakePool()))
    assert await store.get(uuid4()) is None


async def test_get_decodes_a_stored_credential() -> None:
    """``get`` decodes a found row into the ``CredentialRecord`` it represents."""
    principal_id = uuid4()
    stored = _record(principal_id)
    row = {
        "principal_id": stored.principal_id,
        "password_hash": stored.password_hash,
        "updated_at": stored.updated_at,
        "updated_by": stored.updated_by,
    }
    store = PostgresCredentialStore(cast("asyncpg.Pool", _FakePool(row=row)))
    assert await store.get(principal_id) == stored


async def test_upsert_translates_the_trigger_error_into_resource_not_found_when_absent() -> None:
    """The guard trigger's error becomes ``ResourceNotFound`` when the principal does not exist."""
    store = PostgresCredentialStore(cast("asyncpg.Pool", _FakePool(kind=None)))
    with pytest.raises(ResourceNotFound):
        await store.upsert(_record())


async def test_upsert_translates_the_trigger_error_into_kind_mismatch_when_present() -> None:
    """The same trigger error becomes ``PrincipalKindMismatch`` for an existing service account."""
    store = PostgresCredentialStore(cast("asyncpg.Pool", _FakePool(kind="service_account")))
    with pytest.raises(PrincipalKindMismatch):
        await store.upsert(_record())
