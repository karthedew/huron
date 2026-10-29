# Phase 003: identity, external directory and independent access control

Status: BLOCKED — credential/broker decision, authority prototype and phase 002.

## Context and outcome

Current Security root exposes OidcAuthentication, PasswordAuthentication,
CredentialAuthentication, AccessPolicy, Bindings, Policies, IdentityService and
ServiceAccounts. Metastore supplies credential/role facts; Compose uses Keycloak.
The target uses Google-first code+PKCE login and separate replaceable AccessControl.
It removes configurable policy definitions/attachments, retaining simple Huron
scope-role bindings. Collection will replace Project in 004; no extra level.

External directory mock runs in a dev Docker container and owns stable group IDs,
LDAP-like membership facts and create-group/add-member/remove-member operations.
Accepted separate authorities: directory itself guards its writes by trusted
membership in configured stable huron-admin group. Huron consumes facts and owns
resource grants. Directory admin is not automatically Huron owner or scientist reader.
Gateway UI must preserve this boundary. Accounts map verified issuer+subject to
stable account/directory IDs, never email-only. Browser credentials stay server-side.

## Prototype evidence

No new auth prototype run. Current `core/security/__init__.py` and Compose inspect
as above; Google login is not proof of a Huron API-token issuer. 001 identity owner
must create/run root `uv run python roadmap/prototypes/directory_authority.py`
against local signed OIDC and directory fixtures. Required outcomes: both directions
of admin separation, issuer collision/email collision, nested groups/cycles, revoke,
cache expiry, timeout, wrong issuer/audience, replay and multi-process visibility.
Record exact freshness TTL and invalidation limits. Proposed complete effective
membership snapshots, cycle rejection and fail-closed stale writes are not evidence.
No invented authorization server; qualify approved broker/provider for SDK tokens.

## Exact scope and ownership

- Current `src/huron/core/security/{oidc,ports,principal,principals,sessions,roles,rules,facts}.py`,
  `_impl/{oidc_authentication,credential_authentication,identity,access,bindings,bootstrap}.py`:
  move/expose through `security/interface/{identity,access,groups,ports,errors}.py`
  after 002 inventory. Preserve account/session invariants and cookie/CSRF transport.
- Proposed `security/_impl/directory.py`, `security/_impl/access_control.py`;
  `core/database/repositories/{identity,groups,bindings}.py` after 002 move;
  `core/database/schema/security.py`, new Alembic migration, API runtime/settings/
  dependencies and `applications/api/routes/auth/`.
- External application proposed `dev/directory/{app,authority,store}.py`, its Docker
  build/health config from 002; persistent directory data distinct from Huron tables.
  `scripts/oidc-test/` signed fixture, Google deployment configuration documentation.
- Delete current `core/security/_impl/policies.py`, `applications/api/routes/v1/endpoints/policies.py`
  and corresponding schema exports/routers, obsolete policy persistence/SQL definitions
  at the reviewed fresh-schema/code cutover, never live data deletion. Inventory policy tests/fixtures and replace meaningful
  grant/inheritance coverage; no weakening. Password/API-key retirement inventory
  waits for approved credential choice; do not remove them speculatively.
- Add `tests/unit/core/security/`, `tests/contract/core/security/`,
  `tests/integration/test_directory_authority.py` using existing auth/RBAC fixtures.
  UI gateway implementation belongs to 009; API contract belongs here.

Fresh deployment approved 2026-10-06 removes legacy account/group/grant/policy
conversion from MVP acceptance. Stable identity mapping and role constraints still
apply to newly created data; SQLAlchemy/Alembic schema bootstrap remains required.
Nonempty targets refuse with operator action, never reset or delete existing data.
No auto email links or role promotion from directory admin. Remove obsolete owned
code/schema definitions only at the reviewed atomic cutover, not live legacy tables.
No old policy compatibility endpoints unless specifically approved.

## Interfaces and implementation examples

Existing `OidcAuthentication.begin/finish` creates persisted sessions; `AccessPolicy`
binds actor and resolves scope. Proposed signatures (not installed):

```python
class AccessControl(Protocol):
    async def require(self, actor: Actor, action: str, resource: ResourceRef) -> None: ...
    async def visibility(self, actor: Actor) -> Visibility: ...

class DirectoryFacts(Protocol):
    async def effective_groups(self, identity: ExternalIdentity) -> GroupSnapshot: ...
```

Domain-owned values carry stable IDs and version/as-of/expiry; no transport Pydantic
models here. Authentication validates issuer, subject, audience, nonce/state/PKCE;
application owns cookies and redirects. Directory writes derive admin group from
trusted authenticated server facts, never request headers or supplied group names.
Huron binding changes+audit share one asyncpg transaction with generation fencing;
local revocation applies on next authorized operation across replicas. External
freshness/outage semantics must be explicit for reads as well as writes. Publication
rechecks current source read and target write, never trusts early HTTP guard alone.
Errors distinguish credential invalid, expired facts, forbidden and undiscoverable
404 without revealing hidden scope/group details.

## Serial task slices

1. Pending: qualified identity mapping and session/broker configuration. Scope auth
   interface/routes/settings; no email linking. Full backend gate below.
2. Pending: external directory service persistence and group operations, trusted
   huron-admin bootstrap/revocation; prove authority separation. Real directory HTTP
   integration, not a fake group header. Full backend gate plus owned stack probe.
3. Pending: Huron AccessControl/simple bindings/freshness and SQL visibility; delete
   obsolete policy APIs/table definitions at fresh-schema/code cutover. Unit matrix + real PG contracts.
4. Pending: cross-process revocation, outage/expiry and publication recheck contract,
   OpenAPI and gateway authorization contract. Full backend/recovery integration.
Each slice uses all area skills below and independent baseline/final reruns; max 3
reviews. Keep current meaningful tests/fixtures; no batch rewriting for renamed files.

## Skills

`.agents/skills/oop-design/SKILL.md`, `.agents/skills/fastapi/SKILL.md`,
`.agents/skills/postgresql-table-design/SKILL.md`,
`.agents/skills/implementation-plan/SKILL.md`; consult official installed OIDC/JWT
documentation (PyJWT version from lock) before changing verification APIs.

## Acceptance and complete applicable gates

Root cwd with locked uv/Python >=3.12: `make lint`;
`uv run pytest -m unit --cov=src/huron --cov-report=term-missing`;
`uv run pytest -m contract`; `uv run pytest -m integration`; `make docs`;
`git diff --check`; `uv run python scripts/check_openapi.py --check` after 002
creates that script. No frontend gate until UI changed; no ingest acceptance for
identity-only slices. If publication workflow code changes, add `make test-acceptance`
with >=25 GiB. Retain 96.01% floor, imports, radon C+/MI B+ diagnostic gate,
complexipy 15 and no new/growing duplication at 0.80; no suppressions/skips/xfails.

Prerequisites: disposable PG16/testcontainers; isolated Linux/Podman controlled-cutover
runner and required Git object for complete integration; owned directory and local
OIDC fixture, agreed issuer/audience; real Google login manual receipt on approved
configuration, no production credentials in logs. Reuse tests/contract/test_auth_store.py,
test_rbac_store.py and tests/unit auth fixtures. Real adapters prove locking/revocation;
only external provider boundary may be simulated deterministically. Zero collected
tests or unavailable infrastructure is BLOCKED. Directory service tests/build scripts
must be owned/registered in its package during slice 2, not invented as already present.
Capture commands/cwd/versions/exits/logs and independent reviewer results.

## Blockers and readiness

User+identity owner choose SDK token issuer/broker and Keycloak role; prototype owner
qualifies freshness/nesting/outage and stable mapping;
002 interfaces/stack complete. Recommend replaceable provider with audience-bound
tokens, never Google ID token bearer. Keycloak as Google broker and Huron API-token
issuer is a recommendation, NOT a user-approved selection. Plan independent review required before
`/implement-markdown roadmap/plans/003-identity-directory-access.md`.

## Execution ledger

Planning writer attempt 1; no product tests/prototypes executed; review count 0.
Future parent records role/model/session/start/last update/commands and preserves
dirty work; progress every 15 minutes, polling every minute, serial writer/reviewer.

## Escalation / final receipt

BLOCKED draft. Final receipt must name removed policy paths, fresh schema bootstrap and
authority-separation/freshness evidence, not only successful Google login.
