"""The principal-provisioning seam: OIDC upsert-on-login, and the password
lookup that folds "unknown", "disabled", and "service account" into one
``None`` so a caller cannot distinguish them by branching."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from huron.pkg.auth.oidc import OidcUser
from huron.pkg.auth.principals import (
    MemoryPrincipalStore,
    PrincipalRecord,
    PrincipalSubjectExists,
)

pytestmark = pytest.mark.unit


def _oidc_user(idp_subject: str = "idp-sub-1", display_name: str = "Alice Example") -> OidcUser:
    return OidcUser(
        idp_subject=idp_subject,
        display_name=display_name,
        email="alice@example.org",
        groups=frozenset({"physics"}),
    )


async def test_upsert_oidc_user_creates_a_new_principal_keyed_on_idp_subject() -> None:
    store = MemoryPrincipalStore()
    record = await store.upsert_oidc_user(_oidc_user())
    assert record.idp_subject == "idp-sub-1"
    assert record.subject == "idp-sub-1"
    assert record.display_name == "Alice Example"
    assert record.kind == "user"
    assert record.disabled_at is None


async def test_upsert_oidc_user_updates_display_name_without_duplicating() -> None:
    store = MemoryPrincipalStore()
    first = await store.upsert_oidc_user(_oidc_user(display_name="Alice"))
    second = await store.upsert_oidc_user(_oidc_user(display_name="Alice Renamed"))
    assert second.id == first.id
    assert second.display_name == "Alice Renamed"
    assert len(store.records) == 1


async def test_get_user_by_subject_returns_none_for_an_unknown_subject() -> None:
    store = MemoryPrincipalStore()
    assert await store.get_user_by_subject("nobody") is None


async def test_get_user_by_subject_returns_none_for_a_disabled_user() -> None:
    record = PrincipalRecord(
        id=uuid4(),
        kind="user",
        subject="dana",
        display_name="Dana",
        idp_subject=None,
        disabled_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )
    store = MemoryPrincipalStore({record.id: record})
    assert await store.get_user_by_subject("dana") is None


async def test_get_user_by_subject_returns_none_for_a_service_account() -> None:
    record = PrincipalRecord(
        id=uuid4(),
        kind="service_account",
        subject="astro/pipeline",
        display_name="",
        idp_subject=None,
        disabled_at=None,
        created_at=datetime.now(UTC),
    )
    store = MemoryPrincipalStore({record.id: record})
    assert await store.get_user_by_subject("astro/pipeline") is None


async def test_get_user_by_subject_returns_the_matching_active_user() -> None:
    record = PrincipalRecord(
        id=uuid4(),
        kind="user",
        subject="bob",
        display_name="Bob",
        idp_subject=None,
        disabled_at=None,
        created_at=datetime.now(UTC),
    )
    store = MemoryPrincipalStore({record.id: record})
    assert await store.get_user_by_subject("bob") == record


# -- create_user / disable / get_by_id --------------------------------------


async def test_create_user_provisions_a_password_user_with_no_idp_subject() -> None:
    store = MemoryPrincipalStore()
    record = await store.create_user(subject="dana", display_name="Dana")
    assert record.kind == "user"
    assert record.subject == "dana"
    assert record.display_name == "Dana"
    assert record.idp_subject is None
    assert record.disabled_at is None


async def test_create_user_refuses_a_subject_an_oidc_login_already_claimed() -> None:
    store = MemoryPrincipalStore()
    await store.upsert_oidc_user(_oidc_user(idp_subject="dana", display_name="Dana"))
    with pytest.raises(PrincipalSubjectExists):
        await store.create_user(subject="dana", display_name="Dana Again")
    # The refusal must not have mutated anything: exactly the OIDC row remains.
    assert len(store.records) == 1


async def test_create_user_refuses_a_subject_another_password_user_already_holds() -> None:
    store = MemoryPrincipalStore()
    await store.create_user(subject="dana", display_name="Dana")
    with pytest.raises(PrincipalSubjectExists):
        await store.create_user(subject="dana", display_name="Impostor")
    assert len(store.records) == 1


async def test_get_by_id_returns_none_for_an_unknown_id() -> None:
    store = MemoryPrincipalStore()
    assert await store.get_by_id(uuid4()) is None


async def test_get_by_id_returns_the_matching_record_regardless_of_kind_or_disabled_state() -> None:
    store = MemoryPrincipalStore()
    record = await store.create_user(subject="dana", display_name="Dana")
    assert await store.get_by_id(record.id) == record


async def test_disable_sets_disabled_at_and_returns_the_updated_record() -> None:
    store = MemoryPrincipalStore()
    record = await store.create_user(subject="dana", display_name="Dana")
    moment = datetime.now(UTC)
    updated = await store.disable(record.id, disabled_at=moment)
    assert updated is not None
    assert updated.disabled_at == moment
    assert (await store.get_by_id(record.id)) == updated
    # A disabled user is unreachable through the password-login lookup.
    assert await store.get_user_by_subject("dana") is None


async def test_disable_returns_none_for_an_unknown_id() -> None:
    store = MemoryPrincipalStore()
    assert await store.disable(uuid4(), disabled_at=datetime.now(UTC)) is None
