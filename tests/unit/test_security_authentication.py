"""Reusable Security login, credential and self-access contracts without HTTP routes."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Event, Lock
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import httpx
import pytest
from argon2 import PasswordHasher

from huron.core.metastore import MemoryCredentialStore, MemorySessionStore
from huron.core.security import (
    CredentialAuthentication,
    OidcAuthentication,
    PasswordAuthentication,
    Principal,
    bootstrap_platform_owner,
    self_access_summary,
    terminate_session,
)
from huron.core.foundation.errors import AuthError, Forbidden
from huron.core.security.apikeys import ApiKeyResolver, create_api_key
from huron.core.security.authentication_errors import ApiKeyExpired
from huron.core.security.dev import DevHeaderResolver
from huron.core.security.errors import OidcNotConfigured, UsernameTaken
from huron.core.security.oidc import (
    JwksVerifier,
    LoginFlow,
    OidcClient,
    OidcProviderConfig,
    OidcResolver,
    code_challenge_s256,
)
from huron.core.security.password import make_credential, needs_rehash
from huron.core.security.principals import PrincipalRecord
from huron.core.security.rules import ScopeType
from huron.core.security.sessions import (
    ABSOLUTE_TTL,
    IDLE_TTL,
    TOUCH_INTERVAL,
    SessionExpired,
    SessionResolver,
    SessionRevoked,
    create_session,
)
from tests.unit.support import FakeClock, memory_stores

pytestmark = pytest.mark.unit
NOW = datetime(2026, 9, 16, tzinfo=UTC)
PASSWORD = "correct-horse-battery-staple"
SECRET = b"flow-secret"


def _password_auth(stores, clock, *, enabled=True):
    """Wire the public password operation to test persistence and time."""
    return PasswordAuthentication(
        stores.principals, stores.credentials, stores.sessions, clock=clock, enabled=enabled
    )


def _credentials(stores, clock, *, oidc=None, development=None):
    """Wire credential resolution with optional provider and development authority."""
    return CredentialAuthentication(
        stores.api_keys, stores.sessions, clock=clock, oidc=oidc, development=development
    )


async def _user(stores, *, stale=False):
    """Persist a user and credential, optionally with outdated hashing parameters."""
    user = await stores.principals.create_user(subject="alice", display_name="Alice")
    credential = make_credential(user.id, PASSWORD, updated_by="administrator")
    if stale:
        credential = replace(
            credential,
            password_hash=PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(PASSWORD),
        )
    await stores.credentials.upsert(credential)
    return user, credential


async def test_password_login_persists_before_return_and_preserves_rehash_provenance():
    """A successful login upgrades only the hash and returns a usable, persisted session."""
    stores, clock = memory_stores(), FakeClock(NOW)
    user, original = await _user(stores, stale=True)
    result = await _password_auth(stores, clock).login("alice", PASSWORD)
    stored = await stores.credentials.get(user.id)
    assert stored != original and not needs_rehash(stored)
    assert (stored.updated_by, stored.updated_at) == (original.updated_by, original.updated_at)
    assert result.display_name == "Alice"
    assert await stores.sessions.get(result.session.id) == result.session
    assert result.session.created_at == NOW
    assert result.session.absolute_expires_at == NOW + ABSOLUTE_TTL
    resolved = await _credentials(stores, clock).resolve(session_token=result.token)
    assert resolved.actor.subject == "alice"
    assert resolved.actor.authentication_method == "session"


@pytest.mark.parametrize("failure", ["missing", "disabled", "service-account", "wrong-password"])
async def test_password_refusals_have_identical_errors_and_issue_no_sessions(failure):
    """Unknown, disabled, non-user and wrong-password attempts all fail generically."""
    stores, clock = memory_stores(), FakeClock(NOW)
    user, _ = await _user(stores)
    username, password = "alice", PASSWORD
    if failure == "missing":
        username = "unknown"
    elif failure == "disabled":
        await stores.principals.disable(user.id, disabled_at=NOW)
    elif failure == "service-account":
        stores.principals.records[user.id] = replace(user, kind="service_account")
    else:
        password = "wrong"
    with pytest.raises(AuthError, match=r"^invalid username or password$"):
        await _password_auth(stores, clock).login(username, password)
    assert not stores.sessions.records


async def test_disabled_password_login_refuses_before_hash_work(monkeypatch):
    """Deployment disablement prevents credential work and session issuance."""

    def unexpected(*args):
        raise AssertionError("password hashing must not run")

    monkeypatch.setattr(
        "huron.core.security._impl.password_authentication.verify_password", unexpected
    )
    with pytest.raises(AuthError, match="password login is disabled"):
        await _password_auth(memory_stores(), FakeClock(NOW), enabled=False).login(
            "alice", PASSWORD
        )


async def test_optional_rehash_failure_is_logged_but_session_failure_propagates(caplog):
    """Housekeeping failure cannot refuse a verified password; durable issuance failure can."""

    class UnavailableCredentials(MemoryCredentialStore):
        async def upsert(self, record):
            raise OSError("credential persistence unavailable")

    class UnavailableSessions(MemorySessionStore):
        async def add(self, record):
            raise OSError("session persistence unavailable")

    stores, clock = memory_stores(), FakeClock(NOW)
    user, original = await _user(stores, stale=True)
    stores = replace(stores, credentials=UnavailableCredentials(stores.credentials.records))
    login = await _password_auth(stores, clock).login("alice", PASSWORD)
    assert await stores.sessions.get(login.session.id) == login.session
    assert await stores.credentials.get(user.id) == original
    assert "failed to rehash the password credential for alice" in caplog.text
    stores = replace(stores, sessions=UnavailableSessions())
    with pytest.raises(OSError, match="session persistence unavailable"):
        await _password_auth(stores, clock).login("alice", PASSWORD)


async def test_password_workers_are_off_loop_and_globally_bounded_to_four(monkeypatch):
    """Concurrent operation instances share a four-worker limit without blocking the loop."""
    import huron.core.security._impl.password_authentication as implementation

    release, four_started, lock = Event(), Event(), Lock()
    active = peak = 0

    def verify(record, password):
        nonlocal active, peak
        with pytest.raises(RuntimeError, match="no running event loop"):
            asyncio.get_running_loop()
        with lock:
            active += 1
            peak = max(peak, active)
            if active == 4:
                four_started.set()
        assert release.wait(5)
        with lock:
            active -= 1
        return False

    monkeypatch.setattr(implementation, "verify_password", verify)
    stores, clock = memory_stores(), FakeClock(NOW)
    tasks = [
        asyncio.create_task(_password_auth(stores, clock).login("nobody", "wrong"))
        for _ in range(8)
    ]
    try:
        assert await asyncio.to_thread(four_started.wait, 5)
        await asyncio.sleep(0.02)
        assert peak == 4
    finally:
        release.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)
    assert all(isinstance(result, AuthError) for result in results)
    assert peak == 4


async def test_rehash_also_runs_off_loop(monkeypatch):
    """Optional hash generation uses a worker just like password comparison."""
    import huron.core.security._impl.password_authentication as implementation

    original = implementation.hash_password
    observed = []

    def hash_password(password):
        with pytest.raises(RuntimeError, match="no running event loop"):
            asyncio.get_running_loop()
        observed.append(password)
        return original(password)

    monkeypatch.setattr(implementation, "hash_password", hash_password)
    stores = memory_stores()
    await _user(stores, stale=True)
    await _password_auth(stores, FakeClock(NOW)).login("alice", PASSWORD)
    assert observed == [PASSWORD]


@pytest.mark.parametrize("bearer_token", ["jwt", ""])
async def test_present_bearer_token_always_wins_over_session_and_development(bearer_token):
    """A present token, even empty, reaches verification rather than falling back."""
    stores, clock = memory_stores(), FakeClock(NOW)
    session, token = create_session("session-user", authentication_method="password", now=NOW)
    await stores.sessions.add(session)
    seen = []

    def verify(token):
        seen.append(token)
        return {"sub": "bearer-user"}

    resolved = await _credentials(stores, clock, oidc=OidcResolver(verify)).resolve(
        bearer_token=bearer_token,
        session_token=token,
        development_headers={"x-huron-subject": "dev-user"},
    )
    assert seen == [bearer_token]
    assert resolved.actor.subject == "bearer-user"
    assert resolved.session is None


async def test_api_key_scopes_and_project_survive_resolution_and_logout():
    """Resolution preserves narrow credential values; bearer logout never revokes the key."""
    stores, clock = memory_stores(), FakeClock(NOW)
    key, token = create_api_key("alice", name="key", project_id="project", now=NOW)
    await stores.api_keys.add(key)
    authentication = _credentials(stores, clock)
    resolved = await authentication.resolve(bearer_token=token)
    assert resolved.actor.scopes == frozenset({"read"})
    assert resolved.actor.project_id == "project"
    assert stores.api_keys.touched == [key.key_id]
    await terminate_session(resolved.actor, resolved.session, stores.sessions, clock=clock)
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
    """Invalid bearer/session credentials never become a trusted development assertion."""
    stores, clock = memory_stores(), FakeClock(NOW)
    auth = _credentials(stores, clock, development=DevHeaderResolver("development"))
    headers = {"x-huron-subject": "alice", "x-huron-groups": " physics, ,math "}
    result = await auth.resolve(bearer_token=None, development_headers=headers)
    assert result.actor.groups == frozenset({"physics", "math"})
    for credentials in (
        {"bearer_token": "jwt"},
        {"bearer_token": ""},
        {"bearer_token": "hk_bad"},
        {"session_token": "bad"},
    ):
        with pytest.raises(AuthError):
            await auth.resolve(**credentials, development_headers=headers)
    with pytest.raises(AuthError, match="a bearer credential is required"):
        await _credentials(stores, clock).resolve(development_headers=headers)


async def test_present_empty_bearer_refuses_instead_of_using_a_valid_session() -> None:
    """An empty extracted token is present and invalid, unlike an absent bearer credential."""
    stores, clock = memory_stores(), FakeClock(NOW)
    record, token = create_session("alice", authentication_method="password", now=NOW)
    await stores.sessions.add(record)
    authentication = _credentials(stores, clock)
    with pytest.raises(AuthError, match="no OIDC verifier configured"):
        await authentication.resolve(bearer_token="", session_token=token)
    resolved = await authentication.resolve(bearer_token=None, session_token=token)
    assert resolved.session == record


async def test_session_activity_slides_only_after_interval_and_never_past_absolute_expiry():
    """Credential orchestration preserves touch throttling and the absolute lifetime."""
    stores, clock = memory_stores(), FakeClock(NOW)
    record, token = create_session("alice", authentication_method="password", now=NOW)
    record = replace(record, absolute_expires_at=NOW + timedelta(hours=1))
    await stores.sessions.add(record)
    auth = _credentials(stores, clock)
    clock.advance(TOUCH_INTERVAL - timedelta(seconds=1))
    assert (await auth.resolve(session_token=token)).session.last_seen_at == NOW
    clock.advance(timedelta(seconds=1))
    touched = (await auth.resolve(session_token=token)).session
    assert touched.last_seen_at == clock.now()
    assert touched.idle_expires_at == record.absolute_expires_at
    clock.set(record.absolute_expires_at)
    with pytest.raises(SessionExpired):
        await auth.resolve(session_token=token)


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


@pytest.mark.parametrize("deadline", ["idle_expires_at", "absolute_expires_at"])
async def test_session_expiring_during_lookup_is_rejected_without_activity_touch(
    monkeypatch: pytest.MonkeyPatch,
    deadline: str,
) -> None:
    """Either session deadline crossed during lookup refuses without persisting activity."""
    stores, clock = memory_stores(), FakeClock(NOW)
    record, token = create_session("alice", authentication_method="password", now=NOW)
    record = replace(
        record, last_seen_at=NOW - TOUCH_INTERVAL, **{deadline: NOW + timedelta(seconds=1)}
    )
    await stores.sessions.add(record)
    lookup = stores.sessions.get
    touches = []

    async def delayed_lookup(session_id: UUID):
        await asyncio.sleep(0)
        clock.advance(timedelta(seconds=2))
        return await lookup(session_id)

    async def touch(*args):
        touches.append(args)

    monkeypatch.setattr(stores.sessions, "get", delayed_lookup)
    monkeypatch.setattr(stores.sessions, "touch", touch)
    with pytest.raises(SessionExpired):
        await _credentials(stores, clock).resolve(session_token=token)
    assert touches == []
    assert stores.sessions.records[record.id] == record


async def test_session_activity_uses_postlookup_time_for_throttle_and_idle_extension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lookup delay crossing the touch interval causes a slide from the later instant."""
    stores, clock = memory_stores(), FakeClock(NOW)
    record, token = create_session("alice", authentication_method="password", now=NOW)
    record = replace(record, last_seen_at=NOW - TOUCH_INTERVAL + timedelta(seconds=1))
    await stores.sessions.add(record)
    lookup = stores.sessions.get

    async def delayed_lookup(session_id: UUID):
        await asyncio.sleep(0)
        clock.advance(timedelta(seconds=2))
        return await lookup(session_id)

    monkeypatch.setattr(stores.sessions, "get", delayed_lookup)
    result = await _credentials(stores, clock).resolve(session_token=token)
    assert result.session.last_seen_at == NOW + timedelta(seconds=2)
    assert result.session.idle_expires_at == NOW + timedelta(seconds=2) + IDLE_TTL
    assert stores.sessions.records[record.id] == result.session


async def test_resolver_explicit_now_overrides_the_injected_clock() -> None:
    """Existing direct callers can still pin evaluation time even with a later injected clock."""
    stores, clock = memory_stores(), FakeClock(NOW + timedelta(seconds=2))
    key, key_token = create_api_key("alice", name="key", now=NOW, ttl=timedelta(seconds=1))
    await stores.api_keys.add(key)
    key_resolver = ApiKeyResolver(stores.api_keys, clock=clock)
    assert (await key_resolver.resolve(key_token, now=NOW)).subject == "alice"
    with pytest.raises(ApiKeyExpired):
        await key_resolver.resolve(key_token)

    session, session_token = create_session("alice", authentication_method="password", now=NOW)
    session = replace(session, idle_expires_at=NOW + timedelta(seconds=1))
    await stores.sessions.add(session)
    session_resolver = SessionResolver(stores.sessions, clock=clock)
    assert (await session_resolver.resolve(session_token, now=NOW))[1] == session
    with pytest.raises(SessionExpired):
        await session_resolver.resolve(session_token)


async def test_self_session_termination_refuses_another_actor_and_revokes_persistently():
    """Only the authenticated session owner can terminate it; subsequent resolution refuses."""
    stores, clock = memory_stores(), FakeClock(NOW)
    record, token = create_session("alice", authentication_method="password", now=NOW)
    await stores.sessions.add(record)
    auth = _credentials(stores, clock)
    resolved = await auth.resolve(session_token=token)
    for actor in (Principal("other", authentication_method="session"), Principal("alice")):
        with pytest.raises(Forbidden):
            await terminate_session(actor, record, stores.sessions, clock=clock)
        with pytest.raises(Forbidden):
            await self_access_summary(actor, record, stores.rbac)
    await terminate_session(resolved.actor, resolved.session, stores.sessions, clock=clock)
    assert (await stores.sessions.get(record.id)).revoked_at == NOW
    with pytest.raises(SessionRevoked):
        await auth.resolve(session_token=token)


async def test_bootstrap_is_idempotent_and_summary_uses_sorted_capabilities():
    """Trusted startup preserves one attributed system grant and self-summary capability codes."""
    stores = memory_stores()
    await bootstrap_platform_owner(stores.rbac, None)
    assert await stores.rbac.bindings_at(ScopeType.SYSTEM, None) == []
    await bootstrap_platform_owner(stores.rbac, "alice")
    first = await stores.rbac.bindings_at(ScopeType.SYSTEM, None)
    await bootstrap_platform_owner(stores.rbac, "alice")
    assert await stores.rbac.bindings_at(ScopeType.SYSTEM, None) == first
    assert len(first) == 1 and first[0].created_by == "bootstrap"
    summary = await self_access_summary(Principal("alice"), None, stores.rbac)
    assert len(summary.scopes) == 1
    scope = summary.scopes[0]
    assert scope.scope_type == "SYSTEM" and scope.scope_id is None
    assert tuple(sorted(scope.capabilities)) == scope.capabilities
    assert (
        "organization.create" in scope.capabilities and "platform_owner" not in scope.capabilities
    )
    assert summary.csrf_token is summary.expires_at is None
    assert not (await self_access_summary(Principal("stranger"), None, stores.rbac)).scopes


async def test_summary_orders_scopes_and_preserves_absolute_session_expiry():
    """Summary order is scope type then ID, with the session's absolute rather than idle expiry."""
    stores = memory_stores()
    for kind, scope_id in (
        (ScopeType.PROJECT, UUID(int=3)),
        (ScopeType.ORGANIZATION, UUID(int=2)),
        (ScopeType.ORGANIZATION, UUID(int=1)),
    ):
        await stores.rbac.grant_role(
            principal="user:alice",
            role_code="reader",
            scope_type=kind,
            scope_id=scope_id,
            created_by="administrator",
        )
    session, _ = create_session("alice", authentication_method="password", now=NOW)
    summary = await self_access_summary(
        Principal("alice", authentication_method="session"), session, stores.rbac
    )
    assert [scope.scope_id for scope in summary.scopes] == [UUID(int=1), UUID(int=2), UUID(int=3)]
    assert summary.csrf_token == session.csrf_token
    assert summary.expires_at == session.absolute_expires_at


@pytest.fixture
async def oidc(monkeypatch):
    """Real code exchange with controlled external HTTP and token-verification boundaries."""
    stores, clock, requests, claims = memory_stores(), FakeClock(NOW), [], {}

    def exchange(request):
        requests.append(parse_qs(request.content.decode()))
        return httpx.Response(200, json={"id_token": "verified-at-external-boundary"})

    monkeypatch.setattr(JwksVerifier, "__call__", lambda self, token: claims)
    async with httpx.AsyncClient(transport=httpx.MockTransport(exchange)) as http:
        client = OidcClient(
            http,
            OidcProviderConfig(
                "https://idp",
                "https://idp/authorize",
                "https://idp/token",
                "https://idp/jwks",
                None,
            ),
            client_id="huron",
            client_secret="secret",
            redirect_url="https://api/callback",
        )
        authentication = OidcAuthentication(
            client, stores.principals, stores.sessions, clock=clock, flow_secret=SECRET
        )
        started = authentication.begin(return_to="/datasets")
        flow = LoginFlow.decode(started.flow_token, SECRET, now=NOW)
        claims.update(sub="alice", name="Alice", groups=["physics"], nonce=flow.nonce)
        yield authentication, started, flow, stores, clock, requests, claims


async def test_oidc_begin_finish_owns_pkce_nonce_provisioning_and_session(oidc):
    """Direct OIDC operations bind state, nonce and PKCE through persisted provisioned login."""
    auth, started, flow, stores, _clock, requests, claims = oidc
    query = parse_qs(urlsplit(started.authorization_url).query)
    assert query["state"] == [flow.state] and query["nonce"] == [flow.nonce]
    assert query["code_challenge"] == [code_challenge_s256(flow.code_verifier)]
    result = await auth.finish(flow_token=started.flow_token, code="code", state=flow.state)
    assert result.return_to == "/datasets"
    assert requests[0]["code"] == ["code"]
    assert requests[0]["code_verifier"] == [flow.code_verifier]
    assert result.login.session.groups == frozenset({"physics"})
    assert result.login.session.authentication_method == "oidc"
    assert await stores.sessions.get(result.login.session.id) == result.login.session
    principal = await stores.principals.get_user_by_subject("alice")
    assert principal.idp_subject == "alice"
    claims["name"] = "Updated Alice"
    repeated = await auth.finish(flow_token=started.flow_token, code="new-code", state=flow.state)
    assert repeated.login.display_name == "Updated Alice"
    assert (await stores.principals.get_user_by_subject("alice")).id == principal.id


@pytest.mark.parametrize(
    "failure",
    [
        "state",
        "missing",
        "forged",
        "expired",
        "future",
        "nonce",
        "subject",
        "collision",
        "disabled",
    ],
)
async def test_oidc_failure_does_not_issue_a_session(oidc, failure):
    """Untrusted flow/provider claims and colliding or disabled identities never issue sessions."""
    auth, started, flow, stores, clock, requests, claims = oidc
    token, state, error = started.flow_token, flow.state, AuthError
    if failure == "state":
        state = "wrong"
    elif failure == "missing":
        token = ""
    elif failure == "forged":
        token = flow.encode(b"different-secret")
    elif failure == "expired":
        clock.advance(timedelta(seconds=601))
    elif failure == "future":
        clock.advance(timedelta(seconds=-1))
    elif failure == "nonce":
        claims["nonce"] = "wrong"
    elif failure == "subject":
        claims.pop("sub")
    elif failure == "collision":
        await stores.principals.create_user(subject="alice", display_name="Local Alice")
        error = UsernameTaken
    else:
        principal = PrincipalRecord(uuid4(), "user", "alice", "Alice", "alice", NOW, NOW)
        stores.principals.records[principal.id] = principal
    with pytest.raises(error):
        await auth.finish(flow_token=token, code="code", state=state)
    assert not stores.sessions.records
    if failure in {"state", "missing", "forged", "expired", "future"}:
        assert not requests
    if failure == "collision":
        assert (await stores.principals.get_user_by_subject("alice")).idp_subject is None


async def test_oidc_accepts_the_600_second_boundary(oidc):
    """The exact ten-minute flow boundary remains accepted, matching the existing decoder."""
    auth, started, flow, _stores, clock, _requests, _claims = oidc
    clock.advance(timedelta(seconds=600))
    result = await auth.finish(flow_token=started.flow_token, code="code", state=flow.state)
    assert result.login.session.created_at == clock.now()


async def test_oidc_session_persistence_failure_is_not_a_successful_login(oidc, monkeypatch):
    """Provisioning may survive a session-store outage, but no session secret is returned."""

    async def unavailable(record):
        raise OSError("session persistence unavailable")

    auth, started, flow, stores, _clock, _requests, _claims = oidc
    monkeypatch.setattr(stores.sessions, "add", unavailable)
    with pytest.raises(OSError, match="session persistence unavailable"):
        await auth.finish(flow_token=started.flow_token, code="code", state=flow.state)
    assert (await stores.principals.get_user_by_subject("alice")).idp_subject == "alice"


def test_unconfigured_oidc_is_refused_before_any_flow_input():
    """Missing provider configuration is refused during wiring, before callback validation."""
    stores = memory_stores()
    with pytest.raises(OidcNotConfigured):
        OidcAuthentication(
            None, stores.principals, stores.sessions, clock=FakeClock(NOW), flow_secret=SECRET
        )
