"""Reusable bearer credential and trusted bootstrap contracts without HTTP routes."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from huron.core.security import (
    CredentialAuthentication,
    bootstrap_platform_owner,
)
from huron.core.foundation.errors import AuthError
from huron.core.security.apikeys import ApiKeyResolver, create_api_key
from huron.core.security.authentication_errors import ApiKeyExpired
from huron.core.security.dev import DevHeaderResolver
from huron.core.security.oidc import (
    OidcResolver,
)
from huron.core.security.rules import ScopeType
from tests.unit.support import FakeClock, memory_stores

pytestmark = pytest.mark.unit
NOW = datetime(2026, 9, 16, tzinfo=UTC)


def _credentials(stores, clock, *, oidc=None, development=None):
    """Wire credential resolution with optional provider and development authority."""
    return CredentialAuthentication(
        stores.api_keys, clock=clock, oidc=oidc, development=development
    )


@pytest.mark.parametrize("bearer_token", ["jwt", ""])
async def test_present_bearer_token_always_wins_over_development(bearer_token):
    """A present token, even empty, reaches verification rather than falling back."""
    stores, clock = memory_stores(), FakeClock(NOW)
    seen = []

    async def verify(token):
        seen.append(token)
        return {"sub": "bearer-user"}

    resolved = await _credentials(
        stores, clock, oidc=OidcResolver(verify, subject_claim="sub")
    ).resolve(
        bearer_token=bearer_token,
        development_headers={"x-huron-subject": "dev-user"},
    )
    assert seen == [bearer_token]
    assert resolved.actor.subject == "bearer-user"


async def test_api_key_scopes_and_project_survive_resolution():
    """Resolution preserves narrow credential values and records successful use."""
    stores, clock = memory_stores(), FakeClock(NOW)
    key, token = create_api_key("alice", name="key", project_id="project", now=NOW)
    await stores.api_keys.add(key)
    authentication = _credentials(stores, clock)
    resolved = await authentication.resolve(bearer_token=token)
    assert resolved.actor.scopes == frozenset({"read"})
    assert resolved.actor.project_id == "project"
    assert stores.api_keys.touched == [key.key_id]
    assert (await authentication.resolve(bearer_token=token)).actor == resolved.actor


@pytest.mark.parametrize(
    "ttl", [timedelta(0), timedelta(seconds=-1), timedelta(days=400, microseconds=1)]
)
def test_api_key_ttl_outside_one_second_to_400_days_is_refused(ttl: timedelta) -> None:
    """No key is minted that is expired on arrival or that outlives 400 days."""
    with pytest.raises(ValueError, match="between 1 second and 400 days"):
        create_api_key("alice", name="key", now=NOW, ttl=ttl)


@pytest.mark.parametrize("ttl", [timedelta(seconds=1), timedelta(days=400)])
def test_api_key_ttl_at_either_bound_expires_exactly_that_long_after_creation(
    ttl: timedelta,
) -> None:
    """The shortest and the longest accepted lifetimes both mint a key expiring on time."""
    record, _ = create_api_key("alice", name="key", now=NOW, ttl=ttl)
    assert record.expires_at == NOW + ttl


async def test_unknown_api_key_is_an_invalid_credential() -> None:
    """A well-formed key naming no stored record is refused exactly as a wrong secret is.

    Both answer the generic ``INVALID_CREDENTIAL`` with one message, so a
    caller probing key ids learns nothing from the refusal.
    """
    stores = memory_stores()
    record, token = create_api_key("alice", name="key", now=NOW)
    await stores.api_keys.add(record)
    resolver = ApiKeyResolver(stores.api_keys, clock=FakeClock(NOW))
    assert (await resolver.resolve(token)).subject == "alice"
    refusals = []
    for credential in ("hk_unknownkeyid_not-the-secret", f"hk_{record.key_id}_not-the-secret"):
        with pytest.raises(AuthError) as refused:
            await resolver.resolve(credential)
        refusals.append((type(refused.value), refused.value.code, str(refused.value)))
    assert refusals == [(AuthError, "INVALID_CREDENTIAL", "invalid API key")] * 2


@pytest.mark.parametrize("env", ["production", "staging", "Development", ""])
def test_dev_header_resolver_refuses_other_environments(env: str) -> None:
    """Only the exact ``development`` environment can build a resolver that trusts headers."""
    with pytest.raises(ValueError, match="dev headers are refused outside development"):
        DevHeaderResolver(env)


async def test_credential_fallback_and_failures_do_not_downgrade():
    """Invalid bearer credentials never become a trusted development assertion."""
    stores, clock = memory_stores(), FakeClock(NOW)
    auth = _credentials(stores, clock, development=DevHeaderResolver("development"))
    headers = {"x-huron-subject": "alice", "x-huron-groups": " physics, ,math "}
    result = await auth.resolve(bearer_token=None, development_headers=headers)
    assert result.actor.groups == frozenset({"physics", "math"})
    for credentials in (
        {"bearer_token": "jwt"},
        {"bearer_token": ""},
        {"bearer_token": "hk_bad"},
    ):
        with pytest.raises(AuthError):
            await auth.resolve(**credentials, development_headers=headers)
    with pytest.raises(AuthError, match="a bearer credential is required"):
        await _credentials(stores, clock).resolve(development_headers=headers)


async def test_key_expiring_during_lookup_is_rejected_without_last_used_touch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expiry is judged after the awaited key lookup, before any last-used write."""
    stores, clock = memory_stores(), FakeClock(NOW)
    record, token = create_api_key("alice", name="key", now=NOW, ttl=timedelta(seconds=1))
    await stores.api_keys.add(record)
    lookup = stores.api_keys.get

    async def delayed_lookup(key_id: str):
        await asyncio.sleep(0)
        clock.advance(timedelta(seconds=2))
        return await lookup(key_id)

    monkeypatch.setattr(stores.api_keys, "get", delayed_lookup)
    with pytest.raises(ApiKeyExpired):
        await _credentials(stores, clock).resolve(bearer_token=token)
    assert stores.api_keys.touched == []


async def test_resolver_explicit_now_overrides_the_injected_clock() -> None:
    """Existing direct callers can still pin evaluation time even with a later injected clock."""
    stores, clock = memory_stores(), FakeClock(NOW + timedelta(seconds=2))
    key, key_token = create_api_key("alice", name="key", now=NOW, ttl=timedelta(seconds=1))
    await stores.api_keys.add(key)
    key_resolver = ApiKeyResolver(stores.api_keys, clock=clock)
    assert (await key_resolver.resolve(key_token, now=NOW)).subject == "alice"
    with pytest.raises(ApiKeyExpired):
        await key_resolver.resolve(key_token)


async def test_bootstrap_is_idempotent():
    """Trusted startup preserves one attributed system grant."""
    stores = memory_stores()
    await bootstrap_platform_owner(stores.rbac, None)
    assert await stores.rbac.bindings_at(ScopeType.SYSTEM, None) == []
    await bootstrap_platform_owner(stores.rbac, "alice")
    first = await stores.rbac.bindings_at(ScopeType.SYSTEM, None)
    await bootstrap_platform_owner(stores.rbac, "alice")
    assert await stores.rbac.bindings_at(ScopeType.SYSTEM, None) == first
    assert len(first) == 1 and first[0].created_by == "bootstrap"
