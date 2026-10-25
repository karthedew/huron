"""Principal identity upsert, lookup, collisions and disablement."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from huron.core.security.oidc import OidcUser
from huron.core.metastore import MemoryPrincipalStore
from huron.core.security.principals import (
    PrincipalRecord,
    PrincipalSubjectExists,
)

pytestmark = pytest.mark.unit


def _oidc_user(idp_subject: str = "idp-sub-1", display_name: str = "Alice Example") -> OidcUser:
    """An OidcUser with a default subject and display name, both overridable."""
    return OidcUser(
        idp_subject=idp_subject,
        display_name=display_name,
        email="alice@example.org",
        groups=frozenset({"physics"}),
    )


async def test_upsert_oidc_user_creates_a_new_principal_keyed_on_idp_subject() -> None:
    """The first OIDC login for a subject creates an enabled user keyed on that idp_subject."""
    store = MemoryPrincipalStore()
    record = await store.upsert_oidc_user(_oidc_user())
    assert record.idp_subject == "idp-sub-1"
    assert record.subject == "idp-sub-1"
    assert record.display_name == "Alice Example"
    assert record.kind == "user"
    assert record.disabled_at is None


async def test_upsert_oidc_user_updates_display_name_without_duplicating() -> None:
    """A later OIDC login for the same subject updates the display name, not a new row."""
    store = MemoryPrincipalStore()
    first = await store.upsert_oidc_user(_oidc_user(display_name="Alice"))
    second = await store.upsert_oidc_user(_oidc_user(display_name="Alice Renamed"))
    assert second.id == first.id
    assert second.display_name == "Alice Renamed"
    assert len(store.records) == 1


async def test_upsert_oidc_user_refuses_a_first_login_whose_subject_another_identity_holds() -> (
    None
):
    """A first-ever OIDC login is refused, not auto-linked, when its subject is a local username."""
    record = PrincipalRecord(uuid4(), "user", "dana", "Dana", None, None, datetime.now(UTC))
    store = MemoryPrincipalStore({record.id: record})
    with pytest.raises(PrincipalSubjectExists):
        await store.upsert_oidc_user(_oidc_user(idp_subject="dana", display_name="Impostor"))
    # The refusal must not have mutated anything: exactly the original identity remains.
    assert len(store.records) == 1


async def test_upsert_oidc_user_still_updates_in_place_once_the_idp_subject_is_known() -> None:
    """A later login for an already-known ``idp_subject`` still updates the same row."""
    store = MemoryPrincipalStore()
    created = await store.upsert_oidc_user(_oidc_user(idp_subject="dana", display_name="Dana"))
    updated = await store.upsert_oidc_user(
        _oidc_user(idp_subject="dana", display_name="Dana Renamed")
    )
    assert updated.id == created.id
    assert updated.display_name == "Dana Renamed"
    assert len(store.records) == 1


# -- disable / get_by_id ---------------------------------------------------


async def test_get_by_id_returns_none_for_an_unknown_id() -> None:
    """``get_by_id`` returns None for an id no principal has."""
    store = MemoryPrincipalStore()
    assert await store.get_by_id(uuid4()) is None


async def test_get_by_id_returns_the_matching_record_regardless_of_kind_or_disabled_state() -> None:
    """``get_by_id`` returns the exact record stored for a principal's id."""
    store = MemoryPrincipalStore()
    record = await store.upsert_oidc_user(_oidc_user(idp_subject="dana", display_name="Dana"))
    assert await store.get_by_id(record.id) == record


async def test_disable_sets_disabled_at_and_returns_the_updated_record() -> None:
    """``disable`` stamps disabled_at and returns the updated identity."""
    store = MemoryPrincipalStore()
    record = await store.upsert_oidc_user(_oidc_user(idp_subject="dana", display_name="Dana"))
    moment = datetime.now(UTC)
    updated = await store.disable(record.id, disabled_at=moment)
    assert updated is not None
    assert updated.disabled_at == moment
    assert (await store.get_by_id(record.id)) == updated


async def test_disable_returns_none_for_an_unknown_id() -> None:
    """``disable`` returns None for an id no principal has."""
    store = MemoryPrincipalStore()
    assert await store.disable(uuid4(), disabled_at=datetime.now(UTC)) is None
