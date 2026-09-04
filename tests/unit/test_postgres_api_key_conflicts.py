"""``PostgresApiKeyStore.add`` translates the constraint violations an insert can hit.

The SQL itself is proven against a real database in
``tests/contract/test_rbac_store.py``; this pins only the translation,
against a fake pool that stands in for the database returning the one
error each site is written to catch, rather than letting a raw ``asyncpg``
exception escape the storage seam.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

import asyncpg
import pytest

from huron.pkg.auth import ApiKeyRecord
from huron.pkg.catalog.errors import ResourceNotFound
from huron.service.api.stores import PostgresApiKeyStore

pytestmark = pytest.mark.unit


class _FakePool:
    """Stands in for ``asyncpg.Pool``; every ``execute`` raises the given error."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def execute(self, *args: object, **kwargs: object) -> str:
        raise self._exc


def _record() -> ApiKeyRecord:
    """Builds a fresh, otherwise-valid ``ApiKeyRecord`` fixture."""
    return ApiKeyRecord(
        key_id="conflicttestkey",
        subject="diana",
        name="diana-laptop",
        secret_sha256="0" * 64,
        scopes=frozenset({"read"}),
        project_id=str(uuid4()),
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )


async def test_add_translates_a_foreign_key_violation_into_resource_not_found() -> None:
    """``add`` translates a missing-project foreign key violation into ``ResourceNotFound``."""
    exc = asyncpg.ForeignKeyViolationError("violates foreign key constraint")
    store = PostgresApiKeyStore(cast("asyncpg.Pool", _FakePool(exc)))
    with pytest.raises(ResourceNotFound):
        await store.add(_record())


async def test_add_translates_a_key_id_collision_into_runtime_error() -> None:
    """A ``key_id`` collision is a service bug, reported as ``RuntimeError``, not a client error."""
    exc = asyncpg.UniqueViolationError("duplicate key value")
    store = PostgresApiKeyStore(cast("asyncpg.Pool", _FakePool(exc)))
    with pytest.raises(RuntimeError, match="conflicttestkey"):
        await store.add(_record())
