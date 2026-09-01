# Huron — Authentication Implementation Plan (OIDC login, passwords, sessions)

Scope: interactive login for the control plane — an OIDC authorization-code flow, an
admin-provisioned username/password option, server-side sessions for the browser, the
database migration behind them, and a compose stack that runs the whole application locally
under Podman or Docker. Companion to [`RBAC_IMPLEMENTATION_PLAN.md`](RBAC_IMPLEMENTATION_PLAN.md)
(authorization; R1–R9 shipped) — this plan supplies the authentication half and **subsumes R10**
("real JWT verification for the UI path" and the principals-upsert-on-login it called for).
`design/` remains authoritative; decisions made here that design/ is silent on get recorded
there in the same PR that ships them (A13).

Nothing here is implemented yet. Steps A1–A13 are ordered so every step leaves the tree green
(all four static gates + unit suite); code blocks are the intended implementation, written
against the tree as of 2026-08-30, and may be lifted verbatim.

---

## 0. The model in one page

Four ways to authenticate, one `Principal` out the other end:

| Credential | Carrier | Resolver | Audience |
|---|---|---|---|
| API key (`hk_…`) | `Authorization: Bearer` | `ApiKeyResolver` (exists) | programmatic |
| OIDC access/ID JWT | `Authorization: Bearer` | `OidcResolver` + **real JWKS verify** (A4) | programmatic / SPA-with-own-token |
| **Session cookie** (`hs_…`) | `huron_session` HttpOnly cookie | `SessionResolver` (A3/A7) | **the web UI — new** |
| Dev headers | `X-Huron-*` | `DevHeaderResolver` (exists) | development only |

Decisions already made (with Karl, 2026-08-30):

- **Server-side sessions**, not Huron-issued JWTs: login writes a `sessions` row; the browser
  holds an opaque HttpOnly cookie. Revocation is a row update; the SvelteKit shell needs no
  token-refresh plumbing. Bearer credentials are untouched.
- **Password accounts are admin-provisioned only.** No self-registration, no email
  verification, no self-service reset — an admin creates the user and sets/resets the
  password. Keeps the surface proportional to a control plane.
- **`pkg/identity` is absorbed into `pkg/auth`** (A1). All AuthN — API keys, OIDC, passwords,
  sessions — is one package; `pkg/rbac` stays a separate, independent sibling (AuthN produces
  the `Principal` that `rbac.decide()` consumes; neither imports the other).
- **Keycloak in compose** as the local IdP, realm pre-seeded, so the full code flow runs
  end-to-end on a laptop.
- **Auth routes are unversioned** — mounted at `/auth`, not `/api/v1/auth`. Login is a
  protocol surface negotiated with browsers and IdPs (redirect URLs live in IdP config);
  it does not version alongside the resource API. `GET /api/v1/auth/whoami` **moves** to
  `GET /auth/session` (no back-compat, per project invariant); `POST /api/v1/auth/api-keys`
  **stays versioned** — an API key is a resource, not a login step.
- **`routes/v1/schemas.py` splits into `routes/v1/schema/*`**, one file per endpoints module
  (A10), and the new auth routes are born with that layout.

The login flows end-to-end:

```
password  POST /auth/login {username, password}
          → principal lookup (kind=user, not disabled) → argon2id verify
          → INSERT sessions → Set-Cookie huron_session=hs_… → 200 {subject, csrf_token}

OIDC      GET  /auth/oidc/start
          → 302 to IdP authorize URL; state+nonce+PKCE verifier in a short-lived
            HMAC-signed huron_login cookie (no server state for pending logins)
          GET  /auth/oidc/callback?code&state
          → verify state against cookie → exchange code (client_secret + PKCE)
          → verify ID token (issuer, audience, nonce, exp, sig via cached JWKS)
          → UPSERT principals ON idp_subject   ← the R10 upsert
          → INSERT sessions → Set-Cookie → 302 to the web app

any       later requests: cookie → SessionResolver → Principal(method="session")
          POST /auth/logout → revoked_at=now() → cleared cookie
```

New dependencies: `pyjwt[crypto]` (JWKS + RS256/ES256 verification — already the pick named in
R10) and `argon2-cffi` (argon2id hashing). Both go in `[project].dependencies`.

---

## A1 — Absorb `pkg/identity` into `pkg/auth`

Same shape as the authz→rbac rename (2026-08-29): mechanical, complete, no compat shims.

New layout (module-per-concern, `__init__.py` is a re-export shim only — the established
pattern; nothing but imports and `__all__` in it):

```
src/huron/pkg/auth/
    __init__.py        re-exports: the public names below, nothing else
    errors.py          AuthError (was IdentityError) + subclasses
    principal.py       Principal                        (moved from identity.py, unchanged)
    apikeys.py         ApiKeyRecord, ApiKeyStore, MemoryApiKeyStore,
                       create_api_key, parse_api_key, ApiKeyResolver   (moved, unchanged)
    dev.py             DevHeaderResolver                (moved, unchanged)
    oidc.py            OidcResolver (moved) + JwksVerifier, OidcClient, LoginFlow   (A4)
    password.py        hash_password, verify_password, CredentialRecord, CredentialStore  (A2)
    sessions.py        SessionRecord, SessionStore, MemorySessionStore,
                       create_session, SessionResolver, parse_session_token          (A3)
```

Renames (project-wide, zero survivors, verified by grep as with authz→rbac):

- `huron.pkg.identity` → `huron.pkg.auth` in every import (`app.py`, `authorization.py`,
  `repository.py`, `postgres_rbac.py`, `routes/v1/endpoints/auth.py`, tests).
- `IdentityError` → `AuthError`. The class keeps `code = "INVALID_CREDENTIAL"` and its
  subclasses (`ApiKeyExpired`, `ApiKeyRevoked`) so the 401 problem-json contract in `app.py`
  is unchanged apart from the exception-handler's type annotation.
- pyproject: in the **packages-independence contract**, `huron.pkg.identity` →
  `huron.pkg.auth`; ruff per-file N818 ignore repoints from `pkg/identity/identity.py` to
  `pkg/auth/errors.py`.
- Add `huron.pkg.auth` to the framework-free forbidden contract **for the web/DB frameworks
  only**: `fastapi`, `starlette`, `uvicorn`, `sqlalchemy`, `asyncpg`, `alembic`. `httpx` is
  deliberately **allowed** in `pkg/auth` (the OIDC client is IO, like `rawstore`'s use of the
  filesystem); `pyjwt` and `argon2-cffi` likewise. Rename the contract or add a second one —
  cleanest is a second contract so "catalog and rbac are framework-free" keeps its meaning:

```toml
[[tool.importlinter.contracts]]
name = "auth is web-framework-free"
type = "forbidden"
source_modules = ["huron.pkg.auth"]
forbidden_modules = [
    "fastapi", "starlette", "uvicorn", "sqlalchemy", "asyncpg", "alembic",
]
```

`design/roadmap.html` §1's package tree changes `identity` → `auth` in the same PR (A13 also
touches design/, but the tree edit ships with the rename that invalidates it).

Postgres implementations of the new stores do **not** go in `pkg/auth` — they follow the
`postgres_rbac.py` precedent and live in the service (A6), keeping asyncpg out of pkg.

---

## A2 — Passwords: `pkg/auth/password.py`

argon2id via `argon2-cffi`, RFC-9106 low-memory parameters, per-hash salts handled by the
library. The store is a Protocol; Postgres rows come in A5/A6.

```python
"""Admin-provisioned password credentials.

Hashing policy lives here so the service layer never sees a bare hash. No
self-registration and no reset tokens exist by design: an admin sets or
replaces the password through the guarded v1 user routes (A9).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError

from huron.pkg.auth.errors import AuthError

if TYPE_CHECKING:
    from uuid import UUID

# RFC 9106 second recommendation (64 MiB, t=3, p=4): fine for a control plane
# with human-frequency logins; revisit only with measurements in hand.
_HASHER = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=4)

#: Verified against on every miss so "unknown user" and "wrong password" cost
#: the same wall-clock time. Generated once at import from a random secret.
_DUMMY_HASH = _HASHER.hash("huron-dummy-password-for-timing-equalization")

MIN_PASSWORD_LENGTH = 12


class PasswordRejected(AuthError):
    code = "PASSWORD_REJECTED"


@dataclass(frozen=True, slots=True)
class CredentialRecord:
    principal_id: UUID
    password_hash: str
    updated_at: datetime
    updated_by: str


class CredentialStore(Protocol):
    async def get(self, principal_id: UUID) -> CredentialRecord | None: ...

    async def upsert(self, record: CredentialRecord) -> None: ...


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordRejected(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    return _HASHER.hash(password)


def verify_password(record: CredentialRecord | None, password: str) -> bool:
    """Constant-shape verification: hash work happens on every call."""
    expected = record.password_hash if record is not None else _DUMMY_HASH
    try:
        _HASHER.verify(expected, password)
    except (VerifyMismatchError, VerificationError):
        return False
    return record is not None


def needs_rehash(record: CredentialRecord) -> bool:
    return _HASHER.check_needs_rehash(record.password_hash)


def make_credential(
    principal_id: UUID, password: str, *, updated_by: str, now: datetime | None = None
) -> CredentialRecord:
    return CredentialRecord(
        principal_id=principal_id,
        password_hash=hash_password(password),
        updated_at=now or datetime.now(UTC),
        updated_by=updated_by,
    )
```

`MemoryCredentialStore` (a dict keyed by `principal_id`, same shape as `MemoryApiKeyStore`)
also lives here for the in-memory backend and tests.

---

## A3 — Sessions: `pkg/auth/sessions.py`

Token format mirrors API keys: `hs_{session_id}_{secret}`; only `sha256(secret)` is stored.
Two clocks: an **idle** timeout that slides on use and an **absolute** lifetime that never
extends. A per-session CSRF token rides along (checked in A7).

```python
"""Server-side browser sessions.

The cookie value is ``hs_{session_id}_{secret}``; the database keeps only the
secret's SHA-256, so a leaked sessions table cannot mint cookies. Expiry is
double-bounded: ``idle_expires_at`` slides forward on activity,
``absolute_expires_at`` is fixed at login. Revocation is a row update and
takes effect on the next request.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from huron.pkg.auth.errors import AuthError
from huron.pkg.auth.principal import Principal


class SessionExpired(AuthError):
    code = "SESSION_EXPIRED"


class SessionRevoked(AuthError):
    code = "SESSION_REVOKED"


IDLE_TTL = timedelta(hours=12)
ABSOLUTE_TTL = timedelta(days=7)
#: last_seen/idle sliding is persisted at most this often, so a busy UI does
#: not turn every GET into a session-table write.
TOUCH_INTERVAL = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class SessionRecord:
    id: UUID
    secret_sha256: str
    csrf_token: str
    #: Denormalized principal snapshot taken at login. Groups refresh at next
    #: login, not mid-session - same tradeoff as an OIDC token's lifetime.
    subject: str
    groups: frozenset[str]
    authentication_method: str  # "oidc" | "password"
    created_at: datetime
    last_seen_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime
    revoked_at: datetime | None = None


class SessionStore(Protocol):
    async def get(self, session_id: UUID) -> SessionRecord | None: ...

    async def add(self, record: SessionRecord) -> None: ...

    async def touch(
        self, session_id: UUID, last_seen_at: datetime, idle_expires_at: datetime
    ) -> None: ...

    async def revoke(self, session_id: UUID, revoked_at: datetime) -> None: ...

    async def revoke_all_for(self, subject: str, revoked_at: datetime) -> int: ...


def create_session(
    subject: str,
    *,
    groups: frozenset[str] = frozenset(),
    authentication_method: str,
    now: datetime | None = None,
) -> tuple[SessionRecord, str]:
    """Return the record to persist and the ``hs_…`` cookie value (shown once)."""
    created_at = now or datetime.now(UTC)
    session_id = uuid4()
    secret = secrets.token_urlsafe(32)
    record = SessionRecord(
        id=session_id,
        secret_sha256=hashlib.sha256(secret.encode()).hexdigest(),
        csrf_token=secrets.token_urlsafe(32),
        subject=subject,
        groups=groups,
        authentication_method=authentication_method,
        created_at=created_at,
        last_seen_at=created_at,
        idle_expires_at=created_at + IDLE_TTL,
        absolute_expires_at=created_at + ABSOLUTE_TTL,
    )
    return record, f"hs_{session_id.hex}_{secret}"


def parse_session_token(token: str) -> tuple[UUID, str]:
    prefix, _, remainder = token.partition("_")
    raw_id, separator, secret = remainder.partition("_")
    try:
        session_id = UUID(hex=raw_id)
    except ValueError:
        session_id = None  # type: ignore[assignment]
    if prefix != "hs" or not separator or session_id is None or not secret:
        raise AuthError("invalid session token format")
    return session_id, secret


class SessionResolver:
    def __init__(self, store: SessionStore):
        self.store = store

    async def resolve(self, token: str, *, now: datetime | None = None) -> tuple[Principal, SessionRecord]:
        session_id, secret = parse_session_token(token)
        record = await self.store.get(session_id)
        candidate = hashlib.sha256(secret.encode()).hexdigest()
        expected = record.secret_sha256 if record is not None else "0" * 64
        if record is None or not hmac.compare_digest(candidate, expected):
            raise AuthError("invalid session")
        moment = now or datetime.now(UTC)
        if record.revoked_at is not None:
            raise SessionRevoked("session has been revoked")
        if moment >= record.idle_expires_at or moment >= record.absolute_expires_at:
            raise SessionExpired("session has expired")
        if moment - record.last_seen_at >= TOUCH_INTERVAL:
            new_idle = min(moment + IDLE_TTL, record.absolute_expires_at)
            await self.store.touch(record.id, moment, new_idle)
            record = replace(record, last_seen_at=moment, idle_expires_at=new_idle)
        principal = Principal(
            subject=record.subject,
            groups=record.groups,
            authentication_method="session",
            kind="user",
        )
        return principal, record
```

`MemorySessionStore` (dict + the obvious method bodies) completes the module. Sessions are
always `kind="user"` — service accounts never log in interactively, which keeps the
silver/gold SA-only invariant untouched by this whole plan.

---

## A4 — OIDC for real: `pkg/auth/oidc.py`

Three additions around the existing (kept) `OidcResolver`:

**`JwksVerifier`** — the concrete `verify` callable the composition root injects, replacing
the current "no OIDC verifier configured" hole. PyJWT's `PyJWKClient` caches keys and
re-fetches on unknown `kid`:

```python
class JwksVerifier:
    """Validate signature, issuer, audience, and expiry against the IdP's JWKS."""

    def __init__(self, *, issuer: str, audience: str, jwks_url: str):
        import jwt

        self.issuer = issuer
        self.audience = audience
        self._jwks = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=300)

    def __call__(self, token: str) -> Mapping[str, object]:
        import jwt

        try:
            key = self._jwks.get_signing_key_from_jwt(token).key
            return jwt.decode(
                token,
                key,
                algorithms=["RS256", "ES256"],
                issuer=self.issuer,
                audience=self.audience,
                options={"require": ["exp", "iat", "sub"]},
            )
        except jwt.PyJWTError as error:
            raise AuthError(f"OIDC token rejected: {error}") from error
```

**`OidcClient`** — discovery + the code flow. Endpoints come from
`{issuer}/.well-known/openid-configuration`, fetched once at startup (fail fast on a bad
issuer). `httpx.AsyncClient` is injected by the service so tests use `respx`.

```python
@dataclass(frozen=True, slots=True)
class OidcProviderConfig:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    end_session_endpoint: str | None


@dataclass(frozen=True, slots=True)
class OidcUser:
    """What the callback hands the service: enough to upsert a principal."""

    idp_subject: str
    display_name: str
    email: str | None
    groups: frozenset[str]


class OidcClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        provider: OidcProviderConfig,
        *,
        client_id: str,
        client_secret: str,
        redirect_url: str,
        scopes: tuple[str, ...] = ("openid", "profile", "email"),
        groups_claim: str = "groups",
    ): ...

    @classmethod
    async def discover(cls, http: httpx.AsyncClient, issuer: str, **kwargs) -> OidcClient: ...

    def authorization_url(self, *, state: str, nonce: str, code_challenge: str) -> str: ...

    async def exchange_code(self, *, code: str, code_verifier: str, nonce: str) -> OidcUser:
        """POST the token endpoint, then verify the ID token (sig, iss, aud,
        exp via JwksVerifier; nonce here) and map claims to OidcUser."""
```

**`LoginFlow`** — the pending-login state (no server storage; an HMAC-signed cookie carries
it between `/auth/oidc/start` and the callback):

```python
@dataclass(frozen=True, slots=True)
class LoginFlow:
    state: str
    nonce: str
    code_verifier: str
    issued_at: int
    return_to: str  # path-only; validated to start with "/" and not "//"

    def encode(self, secret: bytes) -> str:
        payload = json.dumps(dataclasses.asdict(self), separators=(",", ":")).encode()
        signature = hmac.new(secret, payload, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(payload + b"." + signature).decode()

    @classmethod
    def decode(cls, value: str, secret: bytes, *, max_age: int = 600) -> LoginFlow:
        """Reject bad signatures and flows older than ten minutes."""
```

PKCE (`code_verifier` → S256 `code_challenge`) is used **in addition to** the client secret —
free hardening, and Keycloak supports it out of the box.

---

## A5 — Migration `0005_auth` + `migrations/schema.sql`

Follows the raw-DDL style of 0001/0002, with the same trigger-enforced kind guards. The
existing `principals` table (0002) already carries `idp_subject text UNIQUE` and the
`CHECK (kind = 'user' OR idp_subject IS NULL)` — the OIDC upsert needs no schema change.
Two new tables:

```sql
-- ------------------------------------------------------- local credentials
-- At most one password per principal; users only. Password hashes are
-- argon2id strings (self-describing parameters). Admin-provisioned: rows are
-- written exclusively through the guarded v1 user routes.
CREATE TABLE local_credentials (
    principal_id uuid PRIMARY KEY REFERENCES principals(id),
    password_hash text NOT NULL CHECK (password_hash LIKE '$argon2id$%'),
    updated_at timestamptz NOT NULL,
    updated_by text NOT NULL
);

CREATE FUNCTION local_credentials_kind_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE principal_kind text;
BEGIN
    SELECT kind INTO principal_kind FROM principals WHERE id = NEW.principal_id;
    IF principal_kind IS DISTINCT FROM 'user' THEN
        RAISE EXCEPTION 'local_credentials.principal_id must reference a user principal';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER local_credentials_kind_guard BEFORE INSERT OR UPDATE ON local_credentials
FOR EACH ROW EXECUTE FUNCTION local_credentials_kind_guard();

-- ------------------------------------------------------------------ sessions
-- One row per interactive browser session. The cookie carries the secret;
-- only its SHA-256 lands here. subject/groups are a login-time snapshot.
CREATE TABLE sessions (
    id uuid PRIMARY KEY,
    secret_sha256 text NOT NULL CHECK (secret_sha256 ~ '^[0-9a-f]{64}$'),
    csrf_token text NOT NULL,
    subject text NOT NULL,
    groups text[] NOT NULL DEFAULT '{}',
    authentication_method text NOT NULL CHECK (authentication_method IN ('oidc', 'password')),
    created_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL,
    idle_expires_at timestamptz NOT NULL,
    absolute_expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    CHECK (idle_expires_at <= absolute_expires_at)
);
CREATE INDEX sessions_subject_active ON sessions (subject) WHERE revoked_at IS NULL;
```

Plus the role-model seed for A9's capability (same style as 0002's seed, and mirrored in
`pkg/rbac/roles.py` first — roles.py is the source of truth, the seed follows it):

```sql
INSERT INTO capabilities (code, title) VALUES ('user.manage', 'Create and administer password users');
INSERT INTO role_capabilities (role_code, capability_code) VALUES ('platform_owner', 'user.manage');
```

`migrations/schema.sql` gains the same DDL; the downgrade drops
`sessions, local_credentials` and deletes the two seed rows. Expired-session cleanup is a
`DELETE FROM sessions WHERE absolute_expires_at < now() - interval '30 days'` owned by the
future sweeper service — noted there, not built here.

---

## A6 — Settings and the composition root

`ApiSettings` grows an OIDC block, session/cookie knobs, and renames nothing existing except
one honest generalization: `rbac_backend` becomes **`store_backend`** — it now selects the
Postgres implementations for RBAC *and* auth stores together (they share the pool and the
same "FK targets must be real rows" caveat). Same values, same default, same explicit opt-in.

```python
class OidcSettings(BaseModel):
    issuer: str
    client_id: str
    client_secret: str
    redirect_url: str            # e.g. http://localhost:8080/auth/oidc/callback
    scopes: tuple[str, ...] = ("openid", "profile", "email")
    groups_claim: str = "groups"
    #: Audience expected in bearer ID/access tokens; defaults to client_id.
    audience: str | None = None


class ApiSettings(BaseSettings):
    ...
    auth_mode: Literal["oidc", "dev-headers"]
    oidc: OidcSettings | None = None          # HURON_OIDC__ISSUER etc. (env_nested_delimiter)
    password_login_enabled: bool = True
    #: Signs the transient huron_login flow cookie. Required outside development.
    login_flow_secret: str = ""
    session_cookie_name: str = "huron_session"
    #: Where /auth/oidc/callback lands the browser after login.
    web_app_url: str = "http://localhost:5173"
    store_backend: Literal["memory", "postgres"] = "memory"

    @model_validator(mode="after")
    def refuse_unsafe_combinations(self) -> Self:
        ...existing checks...
        if self.auth_mode == "oidc" and self.oidc is None:
            raise ValueError("auth_mode=oidc requires the HURON_OIDC__* settings")
        if self.env != "development" and not self.login_flow_secret:
            raise ValueError("login_flow_secret is required outside development")
        return self
```

(`model_config` adds `env_nested_delimiter="__"` so `HURON_OIDC__CLIENT_SECRET` works.)

`create_app` wiring, in the lifespan next to the existing store selection:

- `store_backend == "postgres"` → `PostgresCredentialStore(pool)` and
  `PostgresSessionStore(pool)` from a new **`service/api/postgres_auth.py`** (asyncpg, same
  file conventions as `postgres_rbac.py`); memory otherwise.
- `HierarchyRepository.__init__` gains `credential_store` / `session_store` /
  `principal_store` parameters with memory defaults, exposed as `repository.credentials`,
  `repository.sessions`, `repository.principals` — the `principals` store is the thin
  `upsert_oidc_user(OidcUser) -> Principal-row` + `get_by_subject()` seam both login paths
  and A9's admin routes share.
- When `settings.oidc` is set: `http = httpx.AsyncClient()`,
  `app.state.oidc_client = await OidcClient.discover(http, settings.oidc.issuer, ...)`, and
  `app.state.oidc_resolver = OidcResolver(JwksVerifier(issuer=..., audience=..., jwks_url=provider.jwks_uri))`.
  The `oidc_verify` test-injection parameter on `create_app` stays — tests keep injecting a
  fake verifier exactly as today.
- Close the httpx client on shutdown alongside the pool.

---

## A7 — `current_principal` learns cookies; CSRF for session-authed writes

`authorization.current_principal` gains one branch, ordered so bearer credentials keep
absolute priority (a programmatic caller with a cookie jar must never be downgraded):

```python
async def current_principal(request: Request) -> Principal:
    authorization = request.headers.get("authorization")
    if authorization:
        ...unchanged: hk_ → API key, else OIDC bearer...
    token = request.cookies.get(_cookie_name(request))
    if token:
        resolver = SessionResolver(get_repository(request).sessions)
        principal, session = await resolver.resolve(token)
        _enforce_csrf(request, session)
        request.state.session = session
        return principal
    ...unchanged: dev-headers fallback / 401...


def _enforce_csrf(request: Request, session: SessionRecord) -> None:
    """Cookie-authenticated state changes must echo the session's CSRF token.

    Bearer paths are exempt (headers cannot be set cross-site); GET/HEAD are
    exempt (they must stay side-effect-free anyway). The token reaches the
    frontend in the login response and GET /auth/session.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    supplied = request.headers.get("x-huron-csrf", "")
    if not hmac.compare_digest(supplied, session.csrf_token):
        raise AuthError("missing or invalid X-Huron-CSRF header")
```

Cookie attributes, set in one helper used by login/callback/logout (A8): `HttpOnly`,
`SameSite=Lax`, `Path=/`, `Secure` unless `settings.env == "development"`, `Max-Age` =
`ABSOLUTE_TTL`. SameSite=Lax + the CSRF header is belt-and-braces, deliberately.

Everything downstream — `require_*`, `check`, `cached_bindings_for`, the layer guards — is
untouched: a session resolves to a plain `Principal` and RBAC neither knows nor cares how
the caller authenticated.

---

## A8 — Unversioned routes: `routes/auth/`

New package, born with the endpoints/schema split (A10's layout):

```
src/huron/service/api/routes/auth/
    __init__.py            router = APIRouter(); includes login, oidc, session
    endpoints/login.py     POST /auth/login, POST /auth/logout
    endpoints/oidc.py      GET /auth/oidc/start, GET /auth/oidc/callback
    endpoints/session.py   GET /auth/session, GET /auth/providers
    schema/login.py        PasswordLogin
    schema/session.py      SessionInfo, ProviderInfo (response models)
```

Mounted in `app.py` **without a version prefix**:

```python
from .routes import auth as auth_routes, v1

app.include_router(auth_routes.router, prefix="/auth", tags=["auth"])
app.include_router(v1.router, prefix="/api/v1")
```

The handlers (abridged to the decisions that matter):

```python
# endpoints/login.py
@router.post("/login")
async def password_login(request: Request, response: Response, body: PasswordLogin) -> dict[str, object]:
    settings = request.app.state.settings
    if not settings.password_login_enabled:
        raise AuthError("password login is disabled")
    repository = get_repository(request)
    row = await repository.principals.get_user_by_subject(body.username)  # None if missing/disabled/sa
    credential = await repository.credentials.get(row.id) if row else None
    if not verify_password(credential, body.password):   # constant-shape on every miss
        raise AuthError("invalid username or password")
    record, token = create_session(row.subject, authentication_method="password")
    await repository.sessions.add(record)
    set_session_cookie(response, settings, token)
    return {"subject": row.subject, "display_name": row.display_name, "csrf_token": record.csrf_token}


@router.post("/logout")
async def logout(request: Request, response: Response, actor: CurrentPrincipal) -> dict[str, str]:
    session = getattr(request.state, "session", None)
    if session is not None:
        await get_repository(request).sessions.revoke(session.id, datetime.now(UTC))
    clear_session_cookie(response, request.app.state.settings)
    return {"status": "signed-out"}
```

```python
# endpoints/oidc.py
@router.get("/oidc/start")
async def oidc_start(request: Request, return_to: str = "/") -> RedirectResponse:
    client = _oidc_client_or_404(request)
    flow = LoginFlow.new(return_to=_safe_return_path(return_to))
    url = client.authorization_url(
        state=flow.state, nonce=flow.nonce, code_challenge=s256(flow.code_verifier)
    )
    response = RedirectResponse(url, status_code=302)
    response.set_cookie("huron_login", flow.encode(_flow_secret(request)),
                        max_age=600, httponly=True, samesite="lax", path="/auth")
    return response


@router.get("/oidc/callback")
async def oidc_callback(request: Request, code: str, state: str) -> RedirectResponse:
    flow = LoginFlow.decode(request.cookies.get("huron_login", ""), _flow_secret(request))
    if not hmac.compare_digest(state, flow.state):
        raise AuthError("OIDC state mismatch")
    client = _oidc_client_or_404(request)
    user = await client.exchange_code(code=code, code_verifier=flow.code_verifier, nonce=flow.nonce)
    repository = get_repository(request)
    row = await repository.principals.upsert_oidc_user(user)      # R10's upsert, keyed on idp_subject
    record, token = create_session(row.subject, groups=user.groups, authentication_method="oidc")
    await repository.sessions.add(record)
    response = RedirectResponse(_app_url(request, flow.return_to), status_code=302)
    set_session_cookie(response, request.app.state.settings, token)
    response.delete_cookie("huron_login", path="/auth")
    return response
```

```python
# endpoints/session.py
@router.get("/session")     # replaces /api/v1/auth/whoami — delete that route
async def session_info(request: Request, actor: CurrentPrincipal) -> dict[str, object]:
    session = getattr(request.state, "session", None)
    return {
        "subject": actor.subject, "kind": actor.kind, "groups": sorted(actor.groups),
        "authentication_method": actor.authentication_method,
        "csrf_token": session.csrf_token if session else None,
        "expires_at": session.absolute_expires_at if session else None,
    }


@router.get("/providers")   # unauthenticated: the login page renders from this
async def providers(request: Request) -> dict[str, object]:
    settings = request.app.state.settings
    return {
        "password": settings.password_login_enabled,
        "oidc": settings.oidc is not None,
        "oidc_start_url": "/auth/oidc/start" if settings.oidc is not None else None,
    }
```

`/auth/providers`, `/auth/login`, `/auth/oidc/*` are the only unauthenticated routes in the
service besides `/healthz` and `/readyz` — worth a one-line comment at the mount site.

**Reserved slugs:** the web login page lands at `/login` (and the API owns `/auth` if the
shell ever proxies it). Add `'auth'` and `'login'` to `RESERVED_ROOT_SLUGS` in **both**
`web/src/lib/reserved-slugs.ts` and `pkg/catalog/paths.py` — the API-side validation exists
now (`validate_org_slug`), so this is two one-line edits plus the UI test fixture.

---

## A9 — Admin user management (v1, guarded)

Password users have to come from somewhere. Smallest sufficient surface, versioned because
users are resources:

```
routes/v1/endpoints/users.py     POST /users               require_system("user.manage")
                                 PUT  /users/{principal_id}/password        same guard
                                 POST /users/{principal_id}/disable         same guard
routes/v1/schema/users.py        CreateUser, SetPassword
```

- `user.manage` is added to `pkg/rbac/roles.py` first (source of truth), on
  **`platform_owner` only** — admin-provisioning is a platform act; org admins manage
  service accounts, not humans. The 0005 seed (A5) mirrors it; the roles unit test's
  invariants pick it up automatically.
- `POST /users {username, display_name, password}` → `principals` row
  (`kind='user'`, `subject=username`, no `idp_subject`) + `local_credentials` row, both via
  `repository.principals` / `repository.credentials`. Refuse a subject that already exists —
  never silently attach a password to an OIDC identity.
- `PUT …/password` replaces the hash and calls `sessions.revoke_all_for(subject)` — a reset
  logs the user out everywhere, by design.
- `POST …/disable` sets `principals.disabled_at` and also revokes all sessions.
- Schemas:

```python
class CreateUser(BaseModel):
    username: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,62}$")
    display_name: str = Field(min_length=1)
    password: str = Field(min_length=12)


class SetPassword(BaseModel):
    password: str = Field(min_length=12)
```

The existing bootstrap path still works unchanged: `bootstrap_platform_owner=karl` grants
the SYSTEM binding, then that subject (arriving via OIDC or dev-headers) creates password
users through these routes. For a fully-offline first login, A11's compose seeds one
password user via a tiny `scripts/seed-dev-auth.py` invoked by `make bootstrap` — dev
convenience, not a production path.

---

## A10 — Split `routes/v1/schemas.py` into `routes/v1/schema/*`

One schema file per endpoints module, names matching 1-to-1; a model lives in the file of
the endpoints module that owns its route, and other endpoint modules import across when they
share one (only `CreateApiKey` does today):

```
routes/v1/schema/__init__.py       docstring only (the "authorization never happens
                                   here" preamble moves here); NO re-exports - import
                                   from the named module, per the layout convention
routes/v1/schema/organizations.py  CreateOrganization, PatchOrganization
routes/v1/schema/projects.py       CreateProject, PatchProject
routes/v1/schema/datasets.py       CreateDataset, PatchDataset, CreateRelease
routes/v1/schema/rbac.py           CreateRoleBinding, CreateServiceAccount, PRINCIPAL_PATTERN
routes/v1/schema/policies.py       CreatePolicy, AttachPolicy
routes/v1/schema/auth.py           CreateApiKey
routes/v1/schema/users.py          CreateUser, SetPassword                  (new, A9)
```

`schemas.py` is deleted in the same commit; the six import sites repoint, e.g.:

```python
from huron.service.api.routes.v1.schema.datasets import CreateDataset, CreateRelease, PatchDataset
```

(`endpoints/rbac.py` imports `CreateApiKey` from `schema.auth` — cross-module imports within
the schema package are fine; duplicating models is not.) Pure move: no model changes, so the
only test impact is import paths. Note the package is `routes/v1/schema/`, a different thing
from top-level `src/huron/schema/` — the FastAPI request bodies never migrate there, since
`huron.schema` is the framework-free dependency floor.

---

## A11 — Run the whole application under Podman/Docker

Three pieces: a `Containerfile`, compose growth (Keycloak always; the app behind a profile),
and Makefile targets. Existing behavior is preserved — `make up` still starts infra only and
`make api` still runs uvicorn on the host with reload; Postgres stays published on **5433**
(5432 is taken by marimohub on Karl's machine).

**`Containerfile`** (uv official image, multi-stage, non-root):

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS build
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --frozen --no-dev

FROM python:3.12-slim-bookworm
RUN useradd --system --uid 1001 huron
WORKDIR /app
COPY --from=build --chown=huron:huron /app /app
ENV PATH="/app/.venv/bin:$PATH"
USER huron
EXPOSE 8080
CMD ["uvicorn", "huron.service.api.app:app", "--host", "0.0.0.0", "--port", "8080"]
```

**`docker-compose.yml` additions** (postgres/minio unchanged):

```yaml
  keycloak:
    image: quay.io/keycloak/keycloak:26.3
    command: ["start-dev", "--import-realm", "--http-port=8081"]
    environment:
      KC_BOOTSTRAP_ADMIN_USERNAME: admin
      KC_BOOTSTRAP_ADMIN_PASSWORD: admin
      # One issuer string valid from the host AND from inside the network:
      # containers resolve the service name; the host gets it from make hosts
      # (adds "127.0.0.1 keycloak" to /etc/hosts) - or use localhost:8081 when
      # running the API on the host, which needs no hosts entry at all.
      KC_HOSTNAME: http://keycloak:8081
      KC_HOSTNAME_BACKCHANNEL_DYNAMIC: "false"
    ports:
      - "8081:8081"
    volumes:
      - ./scripts/keycloak/huron-realm.json:/opt/keycloak/data/import/huron-realm.json:ro
    healthcheck:
      test: ["CMD-SHELL", "exec 3<>/dev/tcp/localhost/8081 && echo ok"]
      interval: 5s
      timeout: 5s
      retries: 30

  migrate:
    profiles: ["app"]
    build:
      context: .
      dockerfile: Containerfile
    command: ["alembic", "upgrade", "head"]
    environment:
      HURON_DATABASE_URL: postgresql://huron:huron@postgres:5432/huron
    depends_on:
      postgres:
        condition: service_healthy

  api:
    profiles: ["app"]
    build:
      context: .
      dockerfile: Containerfile
    ports:
      - "8080:8080"
    environment:
      HURON_ENV: development
      HURON_AUTH_MODE: oidc
      HURON_DATABASE_URL: postgresql://huron:huron@postgres:5432/huron
      HURON_STORE_BACKEND: postgres
      HURON_OIDC__ISSUER: http://keycloak:8081/realms/huron
      HURON_OIDC__CLIENT_ID: huron-web
      HURON_OIDC__CLIENT_SECRET: dev-only-secret
      HURON_OIDC__REDIRECT_URL: http://localhost:8080/auth/oidc/callback
      HURON_LOGIN_FLOW_SECRET: dev-only-flow-secret
      HURON_WEB_APP_URL: http://localhost:5173
      HURON_BOOTSTRAP_PLATFORM_OWNER: karl
      HURON_CLASSIFICATION_VOCABULARY: '[{"code":"internal","order":0,"discoverable":true}]'
    depends_on:
      keycloak:
        condition: service_healthy
      migrate:
        condition: service_completed_successfully
```

The `migrate` service only works once Alembic stops hard-coding its URL: today
`alembic.ini` pins `sqlalchemy.url = postgresql+asyncpg://huron:huron@localhost:5433/huron`.
Teach `migrations/env.py` to prefer the service's own env var, normalizing the driver:

```python
import os

if (env_url := os.environ.get("HURON_DATABASE_URL")) is not None:
    config.set_main_option(
        "sqlalchemy.url", env_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    )
```

`make migrate` on the host is unaffected (no env var set → alembic.ini's 5433 URL).

The issuer question, decided: **one issuer URL, `http://keycloak:8081/realms/huron`.** OIDC
breaks whenever the browser and the backend see different issuer strings; the service-name
URL is valid inside the network for free, and on the host after one `/etc/hosts` line that a
`make hosts` target adds (idempotently, with sudo prompt). Developers who skip the `app`
profile and run `make api` on the host can instead set
`HURON_OIDC__ISSUER=http://localhost:8081/realms/huron` in `.env` — the host reaches the
published port directly and no hosts entry is needed. Both modes are documented in the
README in this step.

**`scripts/keycloak/huron-realm.json`** — realm `huron`; confidential client `huron-web`
(secret `dev-only-secret`, redirect URIs `http://localhost:8080/auth/oidc/callback` and
`http://keycloak:8081/*`, standard flow + PKCE S256); a `groups` client scope mapping realm
roles into a `groups` claim; users `karl` (password `karl-dev-password`, group
`platform-admins`) and `sam` (a plain scientist). Exported once from a hand-configured
instance, committed, imported forever after.

**Makefile**:

```make
up:      ## Start PostgreSQL, MinIO, and Keycloak (infra only).
	$(COMPOSE) up -d --wait postgres minio keycloak

stack:   ## Build and run the WHOLE app (api + migrations) in containers.
	$(COMPOSE) --profile app up -d --build --wait

hosts:   ## Idempotently add "127.0.0.1 keycloak" for the app profile.
	grep -q "127.0.0.1 keycloak" /etc/hosts || echo "127.0.0.1 keycloak" | sudo tee -a /etc/hosts
```

`podman-compose` supports `profiles`, `service_completed_successfully`, and build contexts
at the versions current on Karl's setup; the `COMPOSE` autodetect line already handles the
docker/podman split. One caveat carried over from memory: after the Mac sleeps, Podman
machine clock drift can surface as `RequestTimeTooSkewed` from MinIO (and now as token
`iat`/`exp` weirdness from Keycloak) — `podman machine stop && podman machine start`.

---

## A12 — Tests

Unit (`tests/unit/`, extending the existing style — plain asyncio tests, no network):

- `test_auth_password.py` — round-trip verify; rejection under `MIN_PASSWORD_LENGTH`; the
  dummy-hash path returns False for a `None` record (and executes the hasher).
- `test_auth_sessions.py` — token format golden + malformed variants; idle expiry slides,
  absolute expiry doesn't; `TOUCH_INTERVAL` throttling (store.touch call count); revoked →
  `SessionRevoked`; wrong secret with valid id → generic `AuthError`.
- `test_auth_oidc.py` — `LoginFlow` encode/decode: signature tamper, age-out, `return_to`
  sanitization (`//evil.example` refused); `exchange_code` against a `respx`-mocked token
  endpoint + a static test JWKS: happy path, wrong nonce, wrong audience, expired token.
- `test_api_login.py` — `create_app` with memory stores: password login sets the cookie and
  the session resolves on the next request; wrong password is a 401 with the generic
  message; CSRF: session-authed POST without `X-Huron-CSRF` → 401, with it → 200, bearer
  POST without it → 200; logout revokes; `/auth/providers` reflects settings; disabled
  user cannot log in; a `sa:` principal with a password row is unreachable (kind guard).
- `test_api_users.py` — `user.manage` guard (403 for organization_admin, 200 for
  platform_owner); duplicate-subject refusal; password reset revokes all sessions.
- Extend `test_catalog_paths.py` for the two new reserved slugs.

Contract (`tests/contract/`, live PG16 via testcontainers, pattern of `test_rbac_store.py`):

- `test_auth_store.py` — `PostgresCredentialStore`/`PostgresSessionStore` round-trips;
  the `local_credentials` kind-guard trigger negative case (service_account principal
  refused); `revoke_all_for` touches only the subject's active rows; upsert-on-login
  keyed by `idp_subject` creates then updates (display-name change) without duplicating.

Acceptance (deferred until `tests/acceptance` grows a harness): a Playwright login journey
against `make stack` + the seeded Keycloak realm — noted in the ledger as future work.

---

## A13 — Design record

`design/` is the authoritative record; this plan ends by making it true there:

- `design/roadmap.html` §1: package tree `identity` → `auth` with the submodule list (done
  in A1's PR), plus the `routes/auth/` and `routes/v1/schema/` layout.
- A new **authentication section** (in `design/architecture.html`, or a `design/auth.html`
  page if it outgrows a section): the four-credential table from §0, the session model
  (double-bounded expiry, hash-at-rest, CSRF), the admin-provisioned password policy and
  its rationale, the unversioned-`/auth` decision, and the one-issuer-URL local-dev topology.
- `design/rbac.html` is already flagged stale; the `user.manage` capability lands in the
  same rewrite (R13) rather than patching a stale page here.

---

## Suggested step → PR grouping

| PR | Steps | Leaves green because |
|---|---|---|
| 1 | A1 | pure move/rename; contracts + grep verify |
| 2 | A2 + A3 + A4 + A12(unit pkg tests) | new pkg code, nothing wired yet |
| 3 | A5 + A6 + A7 + A12(contract) | migration + wiring + resolver, behind settings |
| 4 | A8 + A9 + A10 + A12(api tests) | routes land with their schema split |
| 5 | A11 | infra only |
| 6 | A13 | docs |

## Verification ledger (to fill as steps land)

- [ ] `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run lint-imports`
- [ ] `grep -rn "pkg.identity\|IdentityError" src tests migrations pyproject.toml` → zero
- [ ] `0005_auth` applied to a clean PG16; both triggers exercised negative-case
- [ ] unit + contract suites green
- [ ] `make up` → password + OIDC login both succeed against host-run `make api`
- [ ] `make hosts && make stack` → full containerized flow: browser → Keycloak (`karl`) →
      callback → `GET /auth/session` shows an oidc session; then `POST /api/v1/organizations`
      succeeds with the CSRF header and 401s without it
- [ ] Podman path: the ledger line above repeated with `podman-compose`
