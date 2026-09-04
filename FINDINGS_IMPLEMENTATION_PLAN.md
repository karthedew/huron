# Huron — Findings Remediation Plan

Fifty-one suspected defects were raised while every module in `src/`, `migrations/`, `scripts/`
and `tests/` was read for the docstring standard. Each was then re-verified against the code with
quoted evidence and the design record (`design/api.html`, `design/auth.html`, `design/rbac.html`,
`design/roadmap.html`). This plan carries the **forty-one that survived** as mechanically
verifiable tasks, records the **two that were refuted**, and hands the **eight that belong to
other work** to where they belong (§1). Nothing here has been implemented.

Companion naming: `IMPLEMENTATION_PLAN.md` holds the shipped auth plan and
`API_IMPLEMENTATION_PLAN.md` the shipped API-tier plan; neither may be overwritten for shipped
work, so this plan has its own file.

## 0. How an implementer reads this plan

**The task is the atomic unit, not the milestone.** `/implement-markdown` runs the complete
validation gate after every task, so a task must leave the tree compiling, the gate green and no
half-applied contract behind it. Tasks inside a milestone are ordered; milestones are ordered by
consequence (security first) but are independent of each other except where a task's
**Depends on** line says otherwise.

**Resolved package path: `src/huron`.**

**The validation gate**, verbatim — this is exactly what `make lint` plus `make test` run:

```text
uv run ruff check .
uv run ruff format --check .
uv run pydoclint src migrations scripts
uv run mypy
uv run ty check
uv run lint-imports
uv run python scripts/check_schema_map.py
uv run radon cc src/huron --min C
uv run radon mi src/huron --min B
uv run complexipy src/huron --max-complexity-allowed 15
uv run pyscn check src/huron
uv run pytest --cov=huron --cov-report=term-missing
```

Facts about the gate the tasks below depend on, checked against `pyproject.toml`:

- `addopts = "-m unit --strict-markers"`: the gate's pytest line runs the `unit` marker only.
  Every task that touches a `stores/` module or a Protocol in `stores/ports.py` or `pkg/auth`
  additionally runs `uv run pytest -m contract` and reports it; that run needs a container runtime
  (testcontainers + PostgreSQL 16). If the host has none, the task stops and reports rather than
  declaring itself done with the step unrun.
- `[tool.coverage.report] fail_under = 89` — a ratchet: never lowered, raised when coverage climbs.
  Every file a task touches is at 100% line coverage unless a specific line is judged unreachable
  defensive code.
- `pydoclint` holds every docstring to its signature: a task that changes a signature or adds a
  `raise` updates the docstring's `Args`/`Returns`/`Raises` in the same edit, per
  `docs/getting-started/docstrings.md`. A route docstring keeps caller-facing prose before `\f`.
- `tests/unit/test_error_contract.py` enforces a **bijection** between `design/api.html` §7's
  error table and the `DomainError` classes: a task that adds an error class edits the table in
  the same task, and the design-first rule applies (the row is written before the class).
- `mypy --strict` and `ty` cover all of `src/huron`. Two pre-existing `type: ignore`s exist; no
  task adds one, and no task adds `# noqa`, `# pragma`, skip/xfail markers or config exclusions.

**Rule 1 — no DDL.** No task adds a migration. Two findings that would need one are handed off in
§1. Store tasks change Python and `SELECT`/`INSERT`/`UPDATE` text only.

**Rule 2 — design first.** Where a task changes a wire-visible contract, the corresponding sentence
in `design/api.html` (or `auth.html` / `rbac.html`) is edited in the same task, before the code.

**Rule 3 — decisions gate tasks, not milestones.** A task marked **GATED on D-n** is not started
until §2 records an answer; every other task in the same milestone proceeds.

**Rule 4 — delete and modify by symbol, never by line.** Line numbers below are receipts taken
on the 2026-09-03 tree (after the docstring sweep, commit `600ff2a` plus the sweep); they locate,
they do not instruct.

## 1. Goal and non-goals

**Goal.** Close every confirmed defect in the current code — the ones an operator or an API client
can hit today first, then the ones that become reachable the moment a planned caller appears —
without widening scope into features the roadmap schedules elsewhere.

**Non-goals, with the reason each is out:**

| Finding | Why it is not in this plan | Where it belongs |
|---|---|---|
| **B15** Browse/`GET` routes are authenticated but never authorized; `visible_project_ids` is called nowhere. | `design/roadmap.html` Phase 3 "Authorization & discoverability" (`todo`) *is* this work: "every list, count, facet, and cursor computed after restricting to discoverable resources… 404 for undiscoverable on direct fetch". A multi-route contract change with its own test strategy. | `/design-plan src/huron/service/api/routes` for Phase 3 |
| **B3** `Binding.maximum_classification` has no producer (`bindings_for` never reads `role_bindings.conditions`); `_has_clearance` ignores capabilities. | The column exists (`0001_foundations.py:154`, checked as an object by `0008`), but the consumer is Phase 3's visibility predicate and the producer is a new `CreateRoleBinding` field — a contract Phase 3 designs. | Phase 3, with B15 |
| **B6** `RoleBindingAuthorizer` is exported and unused. | It is the Phase 3 vehicle (`roadmap.html:203-213` lists it as a P1 deliverable awaiting its route). Deleting it would be premature; wiring it is B15. | Phase 3, with B15 |
| **B5** `amendments.py` refuses `data_classification` changes "requires metadata.reclassify", a capability that exists in neither `CAPABILITIES` nor `design/rbac.html`'s table of seventeen. | Adding a capability is a `capabilities`/`role_capabilities` data migration (Rule 1) and a design-table change, and `validate_amendment` has no route caller yet. | The plan that wires `POST /revisions/{id}:amend` |
| **C9** `fold_amendments` re-validates stored amendments on a read path. | Same feature, same plan; it decides whether a stored-but-now-forbidden amendment is skipped, surfaced or refused. | Same as B5 |
| **C13** `write_generation` is two ordered durable steps; a crash between them makes a same-number retry fail with `FileExistsError`. | Documented, intentional trade-off ("never publish an unwritten generation"). A recovery path belongs to the operator tooling that will replay a crashed write, not to the store. | Recorded as accepted; revisit with the reconciler |
| **C14** `commit_envelope`'s existence check is check-then-act. | The ingest lease (`IngestSession`, single writer per envelope) is the serialization point by design; `os.rename` is the atomic step. | Recorded as accepted |
| **A15** `bindings_for` filters expiry with the database `now()`; `created_at`/`expires_at` come from the process clock. | Bounded by NTP skew, invisible on the wire, and the fix (stamping from the database clock) changes the `RbacStore.grant_role` port for every implementation. Kept as an optional last task, M8.4, not a defect to chase. | M8.4 (optional) |

**Refuted — verified not defects, listed so nobody re-derives them:**

- **C5** "`attach_policy` cannot target SYSTEM scope." True and intended: `policies.py`'s module
  docstring says policies never attach at SYSTEM scope, no `*.policy_attach` capability exists at
  SYSTEM, and `design/rbac.html` §"Policies" names only organization/project/dataset attachment.
- **C7** "`Dataset.lifecycle_state: str` receives a `StrEnum` member." `DatasetLifecycle` is a
  `str` subtype; mypy passes and `canonical_bytes` serializes it as `"ACTIVE"`.

## 2. Human decision register

Eleven tasks change something a client, an operator or the security model can see. Each is
recorded as the question, the recommendation, the task it governs, and an **Answer** column that
is empty until the owner fills it. A task **GATED on** a row does not start until its answer is
recorded; every other task proceeds.

| ID | Decision | Evidence | Recommendation | Governs | **Answer** |
|---|---|---|---|---|---|
| **D-1** | A disabled user completes the OIDC code flow: refuse, or keep today's behaviour (a fresh session)? | `oidc.py` callback calls `upsert_oidc_user` then `create_session` unconditionally; `design/auth.html`: "an account disable… revoke[s] every session the subject holds". | **Refuse**, answering exactly what password login answers for a disabled user — `AuthError` → `401 INVALID_CREDENTIAL`, no new code. | M1.2 | **Refuse (401 INVALID_CREDENTIAL)** |
| **D-2** | An OIDC first login whose `idp_subject` equals an existing password user's `subject`: refuse, or auto-link the two identities? | Postgres `ON CONFLICT (idp_subject)` misses the `principals.subject` UNIQUE → raw `UniqueViolationError` (500); memory store silently creates a duplicate subject. | **Refuse**, both stores raising `PrincipalSubjectExists`, which the tier already renders as `409 USERNAME_TAKEN` ("some principal already holds that subject"). Auto-linking would let an IdP-controlled subject claim a local account. | M1.4 | **Refuse (`PrincipalSubjectExists` → 409 USERNAME_TAKEN)** |
| **D-3** | A malformed `If-Match` (`3W`, `//3`, `abc`) answers `412` today and `3W` even parses as version 3. Answer `422 REQUEST_INVALID` for a header that is not `"N"` or `W/"N"`? | `preconditions.py: int(if_match.strip('W/"'))`; §7 defines `PRECONDITION_FAILED` as "If-Match version did not match", not "header unparseable". | **Yes — `422 REQUEST_INVALID`**, the existing code for "did not satisfy the declared schema". `412` stays reserved for a well-formed header naming the wrong version. | M3.2 | **Yes — 422 REQUEST_INVALID for unparseable headers** |
| **D-4** | `GET /auth/session` reports `authentication_method: "session"` for every cookie caller; the stored `SessionRecord` knows `"password"` or `"oidc"`. Report the stored value? | `session.py` `session_info` reads `actor.authentication_method`, which `SessionResolver` hard-codes to `"session"`. | **Yes.** A client checking for the literal `"session"` breaks; none exists yet (the generated web client ships in P1). | M4.4 | **Yes — report the stored value** |
| **D-5** | `ScopeRoles.roles` and `SessionInfo.effective_roles` carry **capability codes** (`data.read`), never role names. Rename the fields to say so? | The schema's own docstring: "a compiled binding carries capability codes, not the role it was compiled from". `api.html:97` calls them "effective roles". | **Rename now** — `roles` → `capabilities`, `effective_roles` → `effective_capabilities` — while no generated client exists; update `api.html:97` and the D-8 wording it inherited. Reconstructing role names would reintroduce the drift the schema avoided on purpose. | M4.5 | **Rename now (`capabilities` / `effective_capabilities`)** |
| **D-6** | `POST /api/v1/auth/api-keys` **requires** an `Idempotency-Key` it never reads; a retry mints a second live key. Real replay is impossible — the secret is stored hashed and shown once. Drop the requirement, or record the key and answer `409 IDEMPOTENCY_KEY_REUSED` on any reuse? | `_require_idempotency_key`'s docstring: "its value is not read here". | **Drop the requirement** and say why in the route's prose: minting is not idempotent because the secret cannot be replayed; a client that loses the response revokes and re-mints. The alternative buys a 409 but no replay, and needs a place to remember keys. Compatible loosening. | M4.6 | **Drop the requirement** |
| **D-7** | A `PATCH` naming no field (or only the unchanged slug) advances `generation`/`version` and writes an identical generation document. Keep, or make it a no-op returning the record unchanged? | Proven live: `patch_organization(…, title=None, description=None)` went 1 → 2 and wrote a file. | **No-op**: no bump, no write, `200` with the current record. A version that changes without content invalidates every client's `If-Match` for nothing. | M5.2 | **No-op patch — no bump, no write** |
| **D-8** | `register_revision` silently replaces an existing `(dataset_id, number)` seed and never checks the dataset exists. Refuse duplicates, or keep replace-on-retry? | `repository.py` docstring: "registering the same pair again replaces the earlier seed". No HTTP route; the ingest commit path will be the caller. | **Refuse**: an unknown dataset is `ResourceNotFound`; a second registration of a number is a programming error (`RuntimeError`), because two revisions must never share a number. Retry-safety belongs to the ingest session, which already exists for that purpose. | M5.3 | **Refuse duplicates (`ResourceNotFound` / `RuntimeError`)** |
| **D-9** | `decide()` lets any applicable DENY win before the layer check, so a DENY restricted to `{"silver"}` denies `gold`. The engine docstring calls this intentional; `design/rbac.html` says "dataset-level bindings and layer restrictions only ever narrow". Which is right? | `rbac/__init__.py:511-512` short-circuits on DENY; `_permits_layer` runs only in the ALLOW loop. No API path creates DENY rows today (`grant_role` always inserts ALLOW); the schema allows them. | **Honour the restriction**: a DENY applies to the layers it names, `layers=None` meaning all. Fail-closed still holds — an unrestricted DENY denies everything — and the engine then matches the design's one sentence about layers. | M6.1 | **Honour the restriction — DENY respects `layers`** |
| **D-10** | API keys are minted with `scopes` (default `{"read"}`) and an optional `project_id`, both stored and both **ignored** by every authorization decision — a "read-only, project-A" key does everything its owner can do anywhere. What does each scope grant, and what does the project restriction deny? | `as_rbac_principal` drops both fields by design comment; `design/rbac.html`: "scopes (capability groups such as read, ingest, publish) and optional project restriction narrow the owner's live permissions; a key never… exceeds them". | **Scopes are capability groups intersected with the owner's bindings**: `read` → `{dataset.discover, data.read}`; `ingest` → `read` ∪ `{data.write, dataset.create, dataset.update}`; `publish` → `ingest` ∪ `{release.create}`; `admin` → no filter (the owner's full set). Unknown scope names are refused at minting (`422`). **Project restriction**: a decision whose scope is not the named project, one of its datasets, or SYSTEM-for-that-project's-organization is DENY; SYSTEM-scope and organization-scope bindings still count, but only inside that project's subtree. | M7.1 | **As recommended: `read`/`ingest`/`publish`/`admin` capability groups, project-subtree restriction** |
| **D-11** | Two authorization guards check the *layer rule* (`ensure_layer_writable`) before resolving the dataset, so a human asking to write `silver` on an unknown dataset gets `403`, not `404`. Reorder to 404-before-403? | `guards.py:256-260`; `scopes.py` module docstring: "404 before 403". | **Yes**, resolve the scope first. Same rule already applied by every other guard. | M4.2 | **Yes — resolve scope before layer check** |

**All other tasks are settled inside their own text and need no one.**

## 3. Milestone sequence

| Milestone | Closes | Reachable today via | Tasks |
|---|---|---|---|
| **M1** Disabled principals stay disabled | A1, A2, A13, B12, A5 | HTTP (OIDC callback, API keys, disable routes) | 4 |
| **M2** The composition root fails clean | A3, A4, B16, A6 | startup, `/readyz`, password login | 4 |
| **M3** Client mistakes are 4xx, never 500 | B7, B13, A12, A10, A11, C8, C10, C11 | HTTP + latent store paths | 4 |
| **M4** Route semantics match the design | B8, B10, B11, A7, A9, B14, B9 | HTTP | 6 — M4.2 superseded by P1 |
| **M5** Repository invariants | C1, C2, C3, C4, C6 | HTTP (create/patch) + seams | 3 — superseded by P1 |
| **M6** RBAC engine semantics | B1, B2, B4 | engine (latent for B1) | 2 |
| **M7** API-key restrictions are enforced | A8 | HTTP, every key-authenticated request | 1 |
| **M8** Rawstore, tooling and test hygiene | C12, C15, C16, C17, A14, B17, C18, C19, A15 | store/script/test | 4 |

Twenty-eight tasks. Suggested order is M1 → M2 → M3 → M4 → M5 → M6 → M7 → M8; only the
**Depends on** lines are binding.

## M1 — Disabled principals stay disabled

### Task M1.1 — `PostgresApiKeyStore.revoke_all_for` revokes every key a subject owns

**Intent.** The two implementations of one port disagree: `MemoryApiKeyStore.revoke_all_for`
(`pkg/auth/apikeys.py:135-155`) revokes every live key of the subject; `PostgresApiKeyStore`
(`stores/api_keys.py:123-149`) adds `AND owner_kind = 'service_account'`. The port's own docstring
says "whatever their `owner_kind`". M1.2 needs the Postgres store to revoke a *user's* keys and
would silently no-op against production without this.

**Modify.** `src/huron/service/api/stores/api_keys.py` — drop the `owner_kind` predicate from the
`UPDATE`; docstring says the store revokes regardless of kind.
`src/huron/service/api/stores/ports.py` — the port's `revoke_all_for` contract states it
explicitly.

**Tests.** `tests/contract/test_auth_store.py`: a user-owned key and a service-account key for two
subjects; `revoke_all_for(user_subject)` revokes only that subject's key, leaving the other live.
`tests/unit/test_api_service_accounts.py` keeps passing unchanged.

**Verify.**

```text
grep -n "owner_kind" src/huron/service/api/stores/api_keys.py
uv run pytest -m contract -q tests/contract/test_auth_store.py
<full validation gate>
```

**Acceptance criteria.** The grep shows `owner_kind` only in `INSERT`/`SELECT` column lists, never
in `revoke_all_for`'s `WHERE`. Both stores pass the same contract assertion. Gate clean.

**Status: done**

### Task M1.2 — Disabling a user revokes its API keys, and a disabled user cannot log in via OIDC — **GATED on D-1**

**Intent.** `design/rbac.html`: "revoking the user kills the keys". `users.py` `disable_user`
(`:154-178`) and `set_password` (`:117-145`) revoke sessions only; `ApiKeyResolver.resolve`
never consults `disabled_at`, so a self-issued key (`POST /api/v1/auth/api-keys`) keeps
authenticating for up to 400 days after the account is disabled. Separately the OIDC callback
(`routes/auth/endpoints/oidc.py:199-203`) creates a session from whatever `upsert_oidc_user`
returns, and both stores return disabled records ("the login route decides what that means" — it
never does), while password login hides disabled rows through `get_user_by_subject`.

**Modify.** `routes/v1/endpoints/users.py` — `disable_user` calls
`repository.api_keys.revoke_all_for(subject, disabled_at)` after the session revocation;
`set_password` does the same with the reset instant (a reset "logs the user out everywhere, by
design" — keys are a login that never ends). `routes/auth/endpoints/oidc.py` — after
`upsert_oidc_user`, a record with `disabled_at is not None` raises `AuthError` (→ `401
INVALID_CREDENTIAL`), before any session is created; the route's prose says a disabled account
cannot sign in by any method. `design/auth.html` — one sentence under the disable rule naming OIDC
explicitly.

**Depends on.** M1.1.

**Tests.** `tests/unit/test_api_users.py`: issue a key as alice, disable alice, the key answers
`401 APIKEY_REVOKED`; the same after `set_password`. `tests/unit/test_api_oidc.py`: a disabled
principal completing the callback gets `401` and no `huron_session` cookie; the principal store
fake records no `create_session`.

**Verify.**

```text
grep -n "revoke_all_for" src/huron/service/api/routes/v1/endpoints/users.py
grep -n "disabled_at" src/huron/service/api/routes/auth/endpoints/oidc.py
<full validation gate>
```

**Acceptance criteria.** Both greps find the new calls. `/auth/oidc/callback`'s `responses`
declares the `401`. The docstrings of `disable_user`, `set_password` and `oidc_callback` state
the guarantee. Gate clean.

**Status: done**

### Task M1.3 — `disable_service_account` is idempotent

**Intent.** Both stores overwrite `disabled_at` on a second disable (`stores/rbac.py:297-321` and
`:808-841`, each docstring: "Disabling twice replaces the timestamp"), and the route then re-runs
`revoke_all_for` with the later cutoff — the audit meaning of "when was it disabled" is lost.

**Modify.** `stores/rbac.py` — in-memory: set `disabled_at` only when `None`; Postgres: `UPDATE …
SET disabled_at = $2 WHERE id = $1 AND kind = 'service_account' AND disabled_at IS NULL`, and
when zero rows update, re-read the row: a present row is returned unchanged, an absent one is
`ResourceNotFound`. `routes/v1/endpoints/service_accounts.py` — `disable_service_account` skips
`revoke_all_for` when the returned `disabled_at` predates this call. `stores/ports.py` — the port
states idempotence.

**Tests.** `tests/unit/test_api_service_accounts.py`: disable twice, `disabled_at` equal across both
responses. `tests/contract/test_rbac_store.py`: the Postgres store returns the original instant on
the second call and answers `ResourceNotFound` for an unknown id.

**Verify.**

```text
grep -n "disabled_at IS NULL" src/huron/service/api/stores/rbac.py
uv run pytest -m contract -q tests/contract/test_rbac_store.py
<full validation gate>
```

**Acceptance criteria.** Grep finds the predicate; both stores satisfy the same unit assertion via
the port; gate clean.

**Status: done**

### Task M1.4 — An OIDC subject that collides with a local user's subject is refused on both stores — **GATED on D-2**

**Intent.** `stores/principals.py:97-107` upserts with `ON CONFLICT (idp_subject)`; `migrations/
versions/0002_rbac.py:31,33` define `subject UNIQUE` and `idp_subject UNIQUE` separately, so a new
`idp_subject` equal to a password user's `subject` raises a raw `asyncpg.UniqueViolationError`
(500). `MemoryPrincipalStore.upsert_oidc_user` (`pkg/auth/principals.py:274-292`) matches on
`idp_subject` only and inserts a duplicate `subject`, breaking the invariant every binding and key
lookup assumes.

**Modify.** `pkg/auth/principals.py` — the memory store refuses when another principal holds the
subject (`PrincipalSubjectExists`). `stores/principals.py` — catch `UniqueViolationError` whose
`constraint_name` is the `subject` constraint and raise `PrincipalSubjectExists`; the
`idp_subject` conflict keeps its `DO UPDATE` path. `routes/auth/endpoints/oidc.py` — the callback
lets `PrincipalSubjectExists` reach the existing handler (`409 USERNAME_TAKEN`), declares it in
`responses`, and its prose says a local account is never auto-linked to an IdP identity.
`stores/ports.py` / `pkg/auth/principals.py` — the `PrincipalStore.upsert_oidc_user` contract
names the refusal.

**Tests.** `tests/unit/test_auth_principals.py` and `tests/contract/test_auth_store.py`: create a
password user `S`, upsert an OIDC user with `idp_subject="S"` → `PrincipalSubjectExists` on both
stores, and the existing `idp_subject` upsert path still updates in place. `tests/unit/
test_api_oidc.py`: the callback answers `409 USERNAME_TAKEN`.

**Verify.**

```text
grep -n "constraint_name" src/huron/service/api/stores/principals.py
uv run pytest -m contract -q tests/contract/test_auth_store.py
<full validation gate>
```

**Acceptance criteria.** No `UniqueViolationError` can escape `upsert_oidc_user`; both stores raise
the same class for the same input; gate clean.

**Status: done**

## M2 — The composition root fails clean

### Task M2.1 — The lifespan owns every resource it opens

**Intent.** `app.py` `create_app` → `lifespan`: `_postgres_repository` opens the asyncpg pool
(`:223`), `_configure_oidc` is awaited (`:231`), and only then does the `try/finally` that closes
the pool begin (`:239-244`). A discovery failure with `store_backend="postgres"` leaks the pool's
connections on every restart of a crash loop.

**Modify.** `src/huron/service/api/app.py` — acquire the pool inside an `AsyncExitStack` (or move
`_configure_oidc` inside the existing `try`), so every acquired resource is released on any
exception before `yield`; the lifespan's `Yields`/prose state the guarantee.

**Tests.** `tests/unit/test_api_app.py`: with a fake `asyncpg.create_pool` returning a pool whose
`close()` records the call and an OIDC discovery that raises, entering the lifespan raises **and**
`close()` was awaited exactly once.

**Verify.**

```text
uv run pytest -q tests/unit/test_api_app.py
<full validation gate>
```

**Acceptance criteria.** The new test fails on the untouched tree and passes after; gate clean.

**Status: done**

### Task M2.2 — `OidcClient.discover` refuses an incomplete discovery document

**Intent.** `pkg/auth/oidc.py:280-292` indexes `document["issuer"]`, `["authorization_endpoint"]`,
`["token_endpoint"]`, `["jwks_uri"]` — a bare `KeyError` at startup, un-mapped by `problems.py`
and (until M2.1) leaking the pool.

**Modify.** `pkg/auth/oidc.py` — validate the four fields, plus that `issuer` equals the configured
issuer, and raise `AuthError` naming the missing field and the issuer; docstring `Raises` updated,
the sentence documenting `KeyError` removed.

**Tests.** `tests/unit/test_auth_oidc.py`: one case per missing field and one for an issuer
mismatch, each `AuthError` with the field named.

**Verify.** `uv run pytest -q tests/unit/test_auth_oidc.py` and the full gate.

**Acceptance criteria.** `grep -n "KeyError" src/huron/pkg/auth/oidc.py` is empty; gate clean.

**Status: done**

### Task M2.3 — `/readyz` bounds the raw-store probe

**Intent.** `app.py:313` awaits `asyncify(_raw_store_failure)` unbounded, while `_database_failure`
(`:337-358`) is under `asyncio.timeout(READINESS_TIMEOUT_SECONDS)`. A hung NFS mount makes the
readiness probe hang instead of answering `503` — the one outcome a readiness probe exists to
prevent.

**Modify.** `app.py` — wrap the raw-store probe in the same timeout; a timeout is reported as
`"raw_store": "did not answer within 2.0s"`. The docstring records the residual: the worker thread
blocked in `stat` is abandoned, not cancelled.

**Tests.** `tests/unit/test_api_app.py`: a `raw_store.root` whose `exists()` sleeps past the
timeout makes `/readyz` answer `503 DEPENDENCY_UNAVAILABLE` within the bound (mirror
`test_readyz_refuses_promptly_instead_of_hanging_on_a_wedged_pool`).

**Verify.** Full gate.

**Acceptance criteria.** Both probes sit under `asyncio.timeout`; the new test passes; gate clean.

**Status: done**

### Task M2.4 — Password login rehashes outdated credentials

**Intent.** `pkg/auth/password.py:184-199` `needs_rehash` is exported and tested and never called
(`login.py:17` imports only `AuthError, create_session, verify_password`). Raising Argon2's cost
parameters would leave every existing hash at the old cost forever.

**Modify.** `routes/auth/endpoints/login.py` — after a successful `verify_password`, when
`needs_rehash(stored_hash)`, compute the new hash off the loop under the same capacity limiter
(`asyncify` + the M1.2 limiter from the API plan) and `repository.credentials.upsert(...)` it with
`updated_by` the subject itself; a failure to write is logged and never fails the login.

**Tests.** `tests/unit/test_api_login.py`: a credential stored with a lower `time_cost` is replaced
after login (the stored hash changes, still verifies); a credential at current parameters is left
byte-identical; a store failure during the rewrite still answers `200`.

**Verify.** Full gate.

**Acceptance criteria.** `grep -n "needs_rehash" src/huron/service/api/routes/auth/endpoints/login.py`
finds the call; gate clean.

**Status: done**

## M3 — Client mistakes are 4xx, never 500

### Task M3.1 — `AttachPolicy.policy_id` is a `UUID`

**Intent.** Proven live: `POST …/policies:attach` with `policy_id: "not-a-uuid"` answers `500
INTERNAL_ERROR`, because `routes/v1/schema/policies.py:77` types it `str` and the three handlers
(`endpoints/policies.py:133,171,211`) call `UUID(body.policy_id)`. §7 reserves `500` for
unhandled failures; this is a schema violation, `422 REQUEST_INVALID`.

**Modify.** `schema/policies.py` — `policy_id: UUID`; the three handlers use `body.policy_id`
directly. Delete the three `UUID(...)` calls by symbol.

**Tests.** `tests/unit/test_api_policies.py`: one `422` case per attach route.

**Verify.** `grep -n "UUID(body.policy_id)" src/huron/service/api/routes/v1/endpoints/policies.py`
is empty; full gate.

**Status: done**

### Task M3.2 — `If-Match` is parsed, not stripped — **GATED on D-3**

**Intent.** `routes/v1/preconditions.py:44` `int(if_match.strip('W/"'))` treats the argument as a
character set: `3W` and `//3` parse as 3, and garbage answers `412` although the version did not
"not match" — it was never stated.

**Modify.** `preconditions.py` — accept exactly `"N"` and `W/"N"` (regex `^(?:W/)?"(\d+)"$`; if a
bare integer must stay accepted for existing clients, say so in the prose and add `|(\d+)`), raise
`RequestValidationError`-equivalent → `422 REQUEST_INVALID` otherwise; `412` only for a parsed
version that differs. `design/api.html` §7 — the `PRECONDITION_FAILED` row gains "a header that is
not `"N"` or `W/"N"` is `REQUEST_INVALID`".

**Tests.** New `tests/unit/test_api_preconditions.py`: `"3"` → 3, `W/"3"` → 3, `3W`, `//3`, `abc`,
`""` → `422`; a well-formed wrong version → `412` through a `PATCH` route.

**Verify.** Full gate.

**Status: done**

### Task M3.3 — Store exceptions are translated, and translated correctly

**Intent.** Three store gaps, all Postgres-only: (a) `stores/credentials.py:86-106` maps the
`local_credentials_kind_guard` trigger's one message to `ResourceNotFound("principal does not
exist")` even when the principal exists and is a service account (`0005_auth.py:49-57` raises the
same way for both); (b) `stores/rbac.py:697-724` `create_service_account` wraps two UNIQUE
constraints in one `except`, reporting a `principals.subject` collision as
`SERVICE_ACCOUNT_EXISTS`, whose §7 meaning is "that service-account name is taken in this
organization"; (c) `create_policy` (`:843-878`) has no `except` at all, `attach_policy`
(`:880-923`) ignores `CheckViolationError`, and `PostgresApiKeyStore.add` (`:86-108`) leaves a
`key_id` UNIQUE collision unmapped — all `500`s the class docstring promises not to produce
("every constraint violation a request can legitimately hit is translated"). `policy_type` is
already schema-validated (`schema/policies.py:35`), so (c) is hardening, not a live route bug.

**Modify.** `stores/credentials.py` — on the trigger error, look the principal up: absent →
`ResourceNotFound`; present with `kind != 'user'` → `PrincipalKindMismatch` (`409`, exists).
`stores/rbac.py` — branch on `exc.constraint_name`: the service-account name constraint →
`ServiceAccountExists`; the `principals.subject` constraint → `PrincipalSubjectExists` (`409
USERNAME_TAKEN`); `create_policy`/`attach_policy` translate `CheckViolationError` to the same
`RoleError`/`DomainError` the in-memory store raises for the same input (`ScopeNotBindable` for
`scope_type`; a `policy_type` that fails the regex cannot reach the store, so it maps to
`ValueError` documented as unreachable-from-HTTP). `stores/api_keys.py` — a `key_id` collision
raises `RuntimeError` with the key id (a 128-bit accident is a bug, not a client error).

**Tests.** `tests/unit/test_postgres_rbac_conflicts.py` (fake-pool harness, extend for
`CheckViolationError` and for `constraint_name` branching); `tests/contract/test_auth_store.py`
gains the service-account-principal case for `credentials.upsert`; `tests/contract/
test_rbac_store.py` gains the subject-collision case.

**Verify.** `uv run pytest -m contract -q` and the full gate.

**Acceptance criteria.** No raw `asyncpg` exception can leave any of the four methods for any input
the API can produce; each translated class matches the in-memory store's for the same input.

**Status: pending**

### Task M3.4 — Catalog pure functions raise typed errors and defend their invariants

**Intent.** Not reachable from any route yet (no caller of `validate_manifest`,
`validate_amendment`, `compute_upload_plan`, `IngestSession` outside `pkg/catalog` and its tests),
so this is the moment to fix them cheaply, before the ingest routes make every one of these a
`500`: (C8) `manifest.py:290-295` raises bare `ValueError` for a negative size or malformed digest
and `amendments.py:88-89` for an empty amendment, against `service/api/errors.py`'s "the tier
raises no untyped failure"; (C10) `ManifestEntry` accepts any digest spelling while
`compute_upload_plan` (`ingest.py:226-227`) compares digests as strings; (C11)
`IngestSession.transition`/`heartbeat` (`ingest.py:160-161`) compare an aware `now` with a
`lease.expires_at` nothing forces to be aware.

**Modify.** `design/api.html` §7 — two new live rows, written first: `MANIFEST_ENTRY_INVALID`
(`400`, "a manifest entry's size or digest is malformed"), `AMENDMENT_EMPTY` (`400`, "an amendment
changes nothing"); (`MANIFEST_MISMATCH` stays reserved — it is about uploaded bytes, not the
declaration). `pkg/catalog/errors.py` — the two classes. `manifest.py` — raise them;
`ManifestEntry.__post_init__` lower-cases a well-formed digest and refuses anything else with
`MANIFEST_ENTRY_INVALID`, so `compute_upload_plan`'s string comparison is sound by construction.
`amendments.py` — raise `AmendmentEmpty`. `ingest.py` — `IngestLease.__post_init__` refuses a naive
`expires_at` (`ValueError`, a programming error); `transition`/`heartbeat` document it.

**Tests.** New `tests/unit/test_catalog_manifest.py` and `tests/unit/test_catalog_amendments.py`
(neither module has a unit test today): every raise site, the digest normalization, the
`__post_init__` refusal; `tests/unit/test_catalog_ingest.py` gains the naive-datetime case;
`tests/unit/test_error_contract.py` passes with the two new rows.

**Verify.** `grep -n "raise ValueError" src/huron/pkg/catalog/manifest.py src/huron/pkg/catalog/amendments.py`
is empty; full gate.

**Status: pending**

## M4 — Route semantics match the design

### Task M4.1 — A service-account key keeps the project restriction it was minted with

**Intent.** `routes/v1/endpoints/service_accounts.py:178-184` calls `create_api_key(...)` without
`project_id=body.project_id`; the user-key route (`api_keys.py:65`) passes it. The caller asked
for a project-scoped key and silently received an organization-wide one.

**Modify.** One keyword argument. The `IssuedServiceAccountKey` view echoes `project_id` so the
caller can see what was minted (the user-key view already omits it deliberately — see
`test_an_issued_api_key_omits_the_project_id_the_request_supplied`; follow that precedent instead
if the omission is intentional for both, and say which in the prose).

**Tests.** `tests/unit/test_api_service_accounts.py`: after `POST …/api-keys` with `project_id`,
the stored `ApiKeyRecord` (via `repository.api_keys`) carries it; the same assertion added for the
user route in `tests/unit/test_api_api_keys.py`.

**Verify.** Full gate.

**Status: pending**

### Task M4.2 — 404 before 403, everywhere — **GATED on D-11**

**Intent.** (B10) `service_accounts.py:46-69` `_account_in_organization` answers `403 "belongs to a
different organization"` — confirming to an administrator of another organization that the
account exists — where `bindings.py:73-90` `_member` answers `404` for the same shape, per
`scopes.py`'s "404 before 403" and `api.html:197` ("a binding named from the wrong root is a
404"). (B11) `guards.py:256-260` `dataset_layer_writer` runs `ensure_layer_writable` before
`dataset_scope`, so an unknown dataset answers `403 LAYER_WRITE_FORBIDDEN`.

**Modify.** `_account_in_organization` raises `ResourceNotFound`; its two callers' prose and
`responses` already declare only `404`. `dataset_layer_writer` resolves the scope first.
`design/api.html` — the service-account rows say "named from the wrong organization: 404".

**Tests.** `tests/unit/test_api_service_accounts.py`: the two existing cross-organization tests
change their expectation from `403` to `404`. `tests/unit/test_authorization_guards.py`: unknown
dataset + `silver` → `404`.

**Verify.** `grep -n "Forbidden" src/huron/service/api/routes/v1/endpoints/service_accounts.py` is
empty; full gate.

Superseded 2026-09-03 — absorbed by `P1_IMPLEMENTATION_PLAN.md` (see `P1_DESIGN.md` § "Status addendum — 2026-09-03"); D-7/D-8/D-11 remain binding there.

**Status: superseded**

### Task M4.3 — One password-length constant

**Intent.** `schema/users.py:25,36` hard-code `Field(min_length=12)`; `pkg/auth/password.py:37`
defines `MIN_PASSWORD_LENGTH = 12` and `design/auth.html` names the constant as the rule.
`PasswordRejected` (`401`, per §7) is unreachable from HTTP only while the two agree.

**Modify.** `schema/users.py` imports and uses `MIN_PASSWORD_LENGTH`.

**Tests.** `tests/unit/test_api_users.py`: parametrize the boundary on the constant, not a literal.

**Verify.** `grep -rn "min_length=12" src/` is empty; full gate.

**Status: pending**

### Task M4.4 — `GET /auth/session` reports how the session was created — **GATED on D-4**

**Intent.** `routes/auth/endpoints/session.py:63-66` reads `actor.authentication_method`, which
`SessionResolver.resolve` (`pkg/auth/sessions.py:376-378`) sets to `"session"` for every cookie
caller; the `SessionRecord` beside it holds `"password"` or `"oidc"` (CHECK-constrained,
`0005_auth.py:70`).

**Modify.** `session_info` uses `session.authentication_method` when a session is present, the
principal's otherwise (`api-key`, bearer `oidc`, `dev-headers`). `design/auth.html` §"GET
/auth/session" lists the possible values.

**Tests.** A new `tests/unit/test_api_session.py` (the endpoint has no direct test): password login
→ `"password"`; OIDC login → `"oidc"`; API key → `"api-key"`.

**Verify.** Full gate.

**Status: pending**

### Task M4.5 — The session view names capabilities as capabilities — **GATED on D-5**

**Intent.** `ScopeRoles.roles` and `SessionInfo.effective_roles` (`routes/auth/schema/session.py`)
hold capability codes; the field names promise role names.

**Modify.** Rename to `capabilities` / `effective_capabilities` in the schema and endpoint; update
`design/api.html:97` and the `design/auth.html` session paragraph; `API_IMPLEMENTATION_PLAN.md`
is a shipped record and is **not** edited.

**Tests.** `tests/unit/test_api_session.py` (from M4.4) asserts the field carries capability codes
and the old names are absent from the JSON.

**Verify.** `grep -rn "effective_roles\|ScopeRoles.roles" src/ design/ docs/` is empty; full gate.

**Status: pending**

### Task M4.6 — `POST /api/v1/auth/api-keys` stops demanding a header it ignores — **GATED on D-6**

**Intent.** `routes/v1/endpoints/api_keys.py:26-34` `_require_idempotency_key` requires
`Idempotency-Key` "without reading its value"; a retry mints a second live key.

**Modify.** Delete `_require_idempotency_key` and its `dependencies=` entry by symbol; the route's
prose states why minting is not idempotent and what a client does after a lost response.
`design/api.html` — the `POST /api/v1/auth/api-keys` row drops any idempotency mention.

**Tests.** `tests/unit/test_api_api_keys.py`: a request without the header succeeds; two identical
requests mint two distinct keys (documenting the contract).

**Verify.** `grep -n "Idempotency" src/huron/service/api/routes/v1/endpoints/api_keys.py` is empty;
full gate.

**Status: pending**

## M5 — Repository invariants

### Task M5.1 — Idempotency fingerprints cover every settable field

**Intent.** Proven live: replaying `create_project` with the same key and a different
`data_classification` returned the original record. `repository.py:295` omits
`data_classification`; `:381-383` `create_dataset` omits `description`; `:527-529`
`create_release` fingerprints `title or ""` (so `None` and `""` collide) and omits `created_by`.
`create_organization` (`:229`) is the correct precedent. §7: `IDEMPOTENCY_KEY_REUSED` — "same
idempotency key, different request body".

**Modify.** The three fingerprints; `_fingerprint` takes a sentinel for `None` so it is distinct
from `""`.

**Tests.** `tests/unit/test_repository_hierarchy.py`: one replay-with-changed-field case per omitted
field, each `IdempotencyKeyReused`; the route-level twins in `test_api_catalog_hierarchy.py`.

**Verify.** Full gate.

Superseded 2026-09-03 — absorbed by `P1_IMPLEMENTATION_PLAN.md` (see `P1_DESIGN.md` § "Status addendum — 2026-09-03"); D-7/D-8/D-11 remain binding there.

**Status: superseded**

### Task M5.2 — A patch is durable before it is visible, and a no-op patch changes nothing — **the no-op half GATED on D-7**

**Intent.** `patch_organization` (`:789-791`), `patch_project` (`:848-851`), `patch_dataset`
(`:468-472`) mutate the live record and *then* call `_write_generation`; proven live, a failing
write leaves `generation == 3, version == 3, title == "new"` in memory with no generation-3
document on disk — the class docstring's own invariant ("the generation file… is written first,
then the in-memory map is updated") broken by the three methods that most need it. And a patch
naming no field still bumps both counters and writes an identical document.

**Modify.** Each `patch_*` builds the successor as a `dataclasses.replace(...)` copy, writes its
generation document, and only then swaps it into the map (make the three hierarchy records frozen
if they are not; nothing else mutates them). With D-7 answered as recommended: when no field's
value changes, return the current record without a write.

**Tests.** `tests/unit/test_repository_hierarchy.py`: per patch method, a raw-store write that
raises leaves `generation`, `version` and every field unchanged; a no-op patch returns an equal
record, the same generation file count, and the same `If-Match` still succeeds afterwards.

**Verify.** Full gate.

Superseded 2026-09-03 — absorbed by `P1_IMPLEMENTATION_PLAN.md` (see `P1_DESIGN.md` § "Status addendum — 2026-09-03"); D-7/D-8/D-11 remain binding there.

**Status: superseded**

### Task M5.3 — Repository reads check existence; revision seeds are refused, not replaced — **the seed half GATED on D-8**

**Intent.** `bindings_at` (`:951-969`) and `list_service_accounts` (`:1032-1044`) document that
they skip the existence check; every HTTP caller is guarded upstream today (`require_*` resolves
the scope first), so this is defense in depth for the next caller. `register_revision`
(`:580-595`) replaces an existing `(dataset_id, number)` and never checks the dataset.

**Modify.** `bindings_at`/`list_service_accounts` resolve their scope through the same
`get_organization`/`get_project`/`get_dataset` the `list_*` methods already use.
`register_revision` requires the dataset and raises `RuntimeError` on a duplicate number (D-8).
`tests/unit/test_repository_rbac.py:247` (which pins `bindings_at(PROJECT, uuid4()) == []`) changes
to expect `ResourceNotFound`.

**Tests.** The repository-level cases above; `register_revision` gains its first direct tests.

**Verify.** Full gate.

Superseded 2026-09-03 — absorbed by `P1_IMPLEMENTATION_PLAN.md` (see `P1_DESIGN.md` § "Status addendum — 2026-09-03"); D-7/D-8/D-11 remain binding there.

**Status: superseded**

## M6 — RBAC engine semantics

### Task M6.1 — DENY honours its layer restriction, and a layer question always names a layer — **DENY half GATED on D-9**

**Intent.** Proven live: a DENY with `layers={"silver"}` denies `data.read` on `gold`
(`rbac/__init__.py:511-512`); and `decide(..., layer=None)` is admitted by a silver-only binding
(`_permits_layer:466`, `layer is None or …`). Every current caller passes a layer for `data.*`
(`guards.py:260`, `datasets.py:348`), so the second is a trap for the next caller, not a live hole.

**Modify.** `pkg/rbac/__init__.py` — DENY bindings pass through `_permits_layer` before they
decide (D-9); `decide()` raises `ValueError` when a `data.read`/`data.write` question carries
`layer=None` (a programming error — fail loud, not open or closed); docstrings and the module prose
state both rules; `design/rbac.html` gains the DENY sentence.

**Tests.** New `tests/unit/test_rbac_engine.py` (the engine has no direct test of `Effect.DENY` —
no fixture in `tests/` builds one): DENY on `silver` does not touch `gold`; unrestricted DENY denies
every layer; a `data.read` question without a layer raises.

**Verify.** Full gate.

**Status: pending**

### Task M6.2 — Remove the dead principal-kind branch

**Intent.** `pkg/rbac/roles.py:326-335`: the third check (`principal_kind not in
definition.allowed_principal_kinds`) is unreachable — callers only ever pass `user` or
`service_account`, service accounts are refused one line earlier, and every role allows `user`.
Clean-sweep: dead vocabulary is deleted, not kept for a role that does not exist.

**Modify.** Delete the branch and `RoleDefinition.allowed_principal_kinds` if nothing else reads
it (`grep -rn allowed_principal_kinds src/ tests/`); `PrincipalKindNotAllowed`'s docstring
describes the one condition that remains.

**Tests.** `tests/unit/test_rbac_roles.py` keeps every existing assertion; a test pins that a
service-account principal is refused by every role.

**Verify.** Full gate.

**Status: pending**

## M7 — API-key restrictions are enforced

### Task M7.1 — Scopes and the project restriction narrow a key's authority — **GATED on D-10**

**Intent.** `pkg/auth/principal.py:31-37` carries `scopes` and `project_id`; `as_rbac_principal`
(`authorization/decisions.py:49-62`) drops them "and never influence a decision". A key minted as
`read`-only for project A is, in practice, its owner. `design/rbac.html`: "a key never… exceeds
[its owner]" and "scopes… and optional project restriction narrow the owner's live permissions".

**Modify.** `pkg/rbac` — a pure `narrow(bindings, *, capabilities, project)` (or an equivalent
inside `decide`) that intersects every binding's capabilities with the scope's capability set and
denies scopes outside the project subtree, exactly as D-10 records it; `authorization/decisions.py`
applies it whenever `principal.authentication_method == "api-key"`; `routes/v1/schema/api_keys.py`
refuses unknown scope names (`422`); `design/rbac.html` gains the scope table.

**Depends on.** M6.1 (the engine tests it extends).

**Tests.** `tests/unit/test_rbac_engine.py`: the intersection and the subtree rule as pure cases.
`tests/unit/test_api_api_keys.py`: a `read` key cannot `PATCH`; a project-A key answers `403` on
project B and `200` on A with the same owner bindings; an unknown scope name is `422`.

**Verify.** Full gate.

**Acceptance criteria.** Every existing key-authenticated test still passes (default scope `read`
is enough for every `GET` they make — if one is not, that test was relying on the defect and is
rewritten to mint the scope it needs, which is the point).

**Status: pending**

## M8 — Rawstore, tooling and test hygiene

### Task M8.1 — `write_part` is atomic and unambiguous; `seal` is durable

**Intent.** No caller of `write_part` exists (`grep -rln "write_part(" src tests` → the definition
only). `store.py:300-340` creates the final name with `O_EXCL` and streams into it — a crash
leaves a partial file under its permanent name — and its `staging` parameter means "the envelope's
`payload` directory" while `hardlink_from_parent` names that directory explicitly. `seal`
(`:157-184`) `chmod`s without an `fsync`.

**Modify.** `write_part` writes to a sibling temp name and `os.replace`s after `fsync`, mirroring
`atomic_replace`; the parameter is renamed `payload`. `seal` fsyncs each directory after the mode
changes (files inherit durability from the directory fsync only for names, so fsync the file
descriptors it reopens for `chmod`), or its docstring states that permission durability is
best-effort — one or the other, not the current silence.

**Tests.** New `tests/unit/test_rawstore_store.py` (no unit test of `store.py`/`commit.py` exists):
a `write_part` interrupted after the first chunk leaves no final file; a completed one matches
the streamed bytes and digest; `seal` calls `os.fsync` once per changed inode (count via
monkeypatch).

**Verify.** Full gate.

**Status: pending**

### Task M8.2 — Operator tooling reports what it swallowed

**Intent.** (C16) `scripts/bootstrap_buckets.py:399-405` discards `apply_lifecycle`'s error text for
`huron-raw`, so a malformed rule or a permission failure is indistinguishable from the tolerated
MinIO limitation. (C17) `migrations/_ddl.py:106-108` appends a trailing `--` comment as a statement
if a DDL block ever ends with one.

**Modify.** `bootstrap_buckets.py` prints the error as `[WARN]` for `huron-raw` and keeps the
non-fatal exit; `_ddl._split` drops a tail that holds only comment text.

**Tests.** New `tests/unit/test_bootstrap_buckets.py` (mocked `BaseClient`) and
`tests/unit/test_migrations_ddl.py` covering both.

**Verify.** Full gate.

**Status: pending**

### Task M8.3 — Records are values; the API-key touch reads what was already parsed

**Intent.** (A14) `records.py:155-174` `ServiceAccount` is the one hierarchy record not frozen, and
`InMemoryRbacStore.disable_service_account` mutates it in place — a reference handed out earlier
changes under its holder, which the Postgres store can never mimic. (B17) `authorization/
credentials.py:115-132` `_touch_api_key` re-parses the token `ApiKeyResolver.resolve` just parsed,
and its `except Exception` reads as a parse guard when it can only ever catch a store failure.

**Modify.** `ServiceAccount` becomes `frozen=True`; the in-memory store uses
`dataclasses.replace`. `_touch_api_key` takes the parsed `key_id`; the `except` names the store
failure it guards.

**Tests.** `tests/unit/test_repository_rbac.py`: a record fetched before a disable is unchanged
after it, on both stores. `tests/unit/test_authorization_credentials.py`: a raising
`touch_last_used` still yields the principal; `parse_api_key` is called once per request.

**Verify.** Full gate.

**Status: pending**

### Task M8.4 — Test hygiene, and the optional clock alignment

**Intent.** (C18) `tests/unit/test_authorization_guards.py:295-312` claims "regardless of bindings"
and grants none. (C19) fourteen unit modules define their own `_settings`/`_headers`
(`test_api_api_keys.py`, `test_api_bindings.py`, `test_api_catalog_hierarchy.py`,
`test_api_login.py`, `test_api_policies.py`, `test_api_rbac.py`, `test_api_roles.py`,
`test_api_router_composition.py`, `test_api_search.py`, `test_api_service_accounts.py`,
`test_api_users.py`, `test_authorization_cookies.py`, `test_authorization_credentials.py`,
`test_execution_model.py`) and `tests/unit/conftest.py` does not exist. (A15, optional) the clock
split from §1.

**Modify.** The guard test grants a `data.write` binding on the dataset first. A
`tests/unit/conftest.py` provides `dev_settings` (parametrizable for the OIDC / bootstrap-owner
variants those modules need) and `dev_headers`; the fourteen local copies are deleted. Optionally,
`PostgresRbacStore.grant_role` stamps `created_at` with `now()` and takes `expires_in` as a
`timedelta` so `expires_at = now() + $interval` — only if the port change is accepted; otherwise
this line is dropped from the task and A15 stays recorded in §1.

**Tests.** The suite is the test: `uv run pytest -q` passes with no behavioural change, and
`grep -rn "^def _settings\|^def _headers" tests/unit` is empty.

**Verify.** Full gate.

**Status: pending**

## 4. Risk register

### R1 — M1.2 and M7.1 change who is authenticated and what a key may do

Both are the point of the tasks, and both can lock a real caller out: an operator whose only
credential is a self-issued key on an account that was disabled, or an automation whose key was
minted `read` because that was the default. Mitigation: M7.1's acceptance criterion forces every
existing test that leaned on the defect to mint the scope it needs, which is the inventory of what
production callers may be doing; the release note for M7.1 lists the four scopes and the default.

### R2 — M4.5 and M4.6 are wire breaks with no consumer to break yet

The generated web client does not exist (P1). These are cheapest now; if they slip past P1 they
become coordinated breaks. Ship them before P1 generates `openapi/v1.json`.

### R3 — M3.4 adds two rows to the §7 table

The bijection test makes a missing row a gate failure, so the order (row first, class second)
is enforced mechanically; the risk is only naming — codes are permanent once shipped.

### R4 — M5.2's frozen records reach further than the three patch methods

Any code that assigns to a hierarchy record's attribute fails at runtime after the change; mypy
catches assignments to frozen dataclass fields, which is why the gate — not a grep — is the check.

### R5 — Contract tests need a container runtime

M1.1, M1.3, M1.4, M3.3 and M8.3 change store behaviour; `pytest -m contract` is mandatory for each
and unavailable on a host without Docker/Podman. The implementer stops and reports rather than
skipping.

## 5. Definition of done

Every task above is `Status: done`, the eleven §2 rows carry an answer (or the task they gate is
explicitly withdrawn with the reason written into the row), the §1 hand-offs are unchanged (nothing
from Phase 3 leaked in), the full gate is green on the final tree, the coverage floor is at or
above where it started, `design/api.html` §7 and `tests/unit/test_error_contract.py` agree, and
no `# noqa`, `# type: ignore`, `# pragma`, skip or xfail was added anywhere.
