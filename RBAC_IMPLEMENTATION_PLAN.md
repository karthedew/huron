# Huron — RBAC and Layer-Governance Implementation Plan

Scope: the role-based access-control system for the control plane — who can create and edit
organizations, projects, and datasets; who can grant roles and attach policies; and, first
among equals, **who can write which storage layer**. Companion to the repo-root
[`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) (this fills in the authorization half of
P5 — Governance — and the credential story P8 depends on). `design/` remains authoritative;
where this plan decides something design/ is silent on, the decision should be recorded there
in the same PR that ships it.

Steps R1–R8 are **implemented and verified** (all four static gates plus the unit suite are
green; both migrations were applied to a clean PostgreSQL 16 and the binding-guard trigger
was exercised negative-case by negative-case) — **with one exception: R6's binding surface is
partial**, and R6 states what is missing and what completes it. R9–R13 are the remaining work,
in order.

---

## 0. The model in one page

Three concepts, kept separate:

- **Capability** — the atomic thing checked: `organization.update`, `dataset.create`,
  `rbac.binding_manage`, and the two data-plane capabilities `data.read` / `data.write`,
  which carry a **layer** (`raw` / `bronze` / `silver` / `gold`) as a separate dimension.
- **Role** — a named capability bundle. Five system roles, below.
- **Role binding** — `(principal, role, scope)` where scope is SYSTEM, an organization, a
  project, or a dataset. Bindings **inherit downward**: bound at the organization, a role
  applies to every project and dataset beneath it. `DENY` bindings exist and win.

Principals are `user:{subject}`, `group:{name}`, or `sa:{subject}` (service account). The
layer rule is a *principal-kind invariant*, not a per-user judgement:

| Capability | reader | developer | project_admin | organization_admin | platform_owner |
|---|---|---|---|---|---|
| organization.create / .delete | | | | | ✓ |
| organization.update / .policy_attach | | | | ✓ | ✓ |
| service_account.manage | | | | ✓ | ✓ |
| project.create | | | | ✓ | ✓ |
| project.update / .policy_attach | | | ✓ | ✓ | ✓ |
| dataset.create | | ✓ | ✓ | | ✓ |
| dataset.update | | ✓ | ✓ | | ✓ |
| dataset.policy_attach | | | ✓ | ✓ | ✓ |
| release.create | | ✓ | ✓ | | ✓ |
| rbac.binding_manage | | | ✓ | ✓ | ✓ |
| data.read (all layers) | ✓ | ✓ | ✓ | ✓ | ✓ |
| data.write @raw / @bronze | | ✓ | | | |
| data.write @silver, @gold | | | | | |
| bindable scopes | org/proj/ds | org/proj/ds | org/proj | org | system |

**Service accounts hold no roles** (2026-08-31, migration `0007_roleless_service_accounts` —
replaced the `pipeline`/`ingest_pipeline` pair): an SA's authority is intrinsic to the principal
kind — `dataset.create`/`dataset.update`/`dataset.discover` plus `data.read`+`data.write` on
**silver and gold only**, scoped to its owning organization, synthesized at decision time from
the `service_accounts` row, never from bindings. The database refuses any role binding whose
principal is `sa:*`. No role in the vocabulary carries silver/gold write, so no binding can leak
it to a human. Huron's internal platform services (intake, builder, canonicalizer, retention)
run under deployment identities, not org service accounts. See `design/rbac.html`
§2 `#service-accounts`.

*(`data_steward` removed 2026-08-31, migration `0006_role_simplification` — its only delta over
`developer` was `dataset.policy_attach`, which the admin roles already hold. See
`design/rbac.html` §2–3: governance by inherited policy, datasets ACTIVE on creation.)*

A feed whose data originates outside the lake — a streaming feed, an instrument, published
reference data — mints the dataset it is about to fill through its intrinsic `dataset.create`
(`design/layer-silver.html#direct-entry`), under the same inherited policies as a human
creation. (Historical: this was the `ingest_pipeline` role from 0004 until the 2026-08-31
roleless-SA change.)

Two deliberate absences: **admins hold no `data.write` anywhere** (administration and data
production are separate concerns — being able to grant a write is not the same as holding
one), and **no human role reaches silver/gold**. Admins and analysts decide what those
layers contain by configuring the pipelines; the pipelines run as service accounts, which
only holders of `service_account.manage` (org admins and above) may create.

Where each concern lives (`service → pkg → schema`, per the import-linter contracts):

```
src/huron/pkg/rbac/__init__.py      pure decision engine: Binding, Scope, decide()   (existed)
src/huron/pkg/rbac/roles.py         THE role model: ROLES, validate/compile          (R1)
src/huron/pkg/catalog/layers.py      layer workflow: specs, promotion, writability    (R2)
src/huron/pkg/identity/__init__.py   API keys, OIDC resolver, principal kinds         (R3)
migrations/versions/0002_rbac.py     tables, guard triggers, role/capability seed     (R4)
migrations/schema.sql                whole-architecture summary (documentation)       (R4)
src/huron/service/api/authorization.py  Depends chain: credential → principal → check (R5)
src/huron/service/api/routes/v1/     schemas.py + endpoints/{organizations,projects,
                                     datasets,rbac,policies,auth}.py                  (R6–R7)
src/huron/service/api/app.py         composition root only                            (R7)
tests/unit/test_{rbac_roles,catalog_layers,api_rbac}.py                              (R8)
```

(The requested `datalake/` tree maps onto the established layout: `pkg/rbac` + `roles.py`
(briefly named `pkg/authz` during initial build, renamed to `pkg/rbac` on 2026-08-29 to match
the original ask and what the package actually implements — a role-based engine, not a general
authorization framework), `pkg/api_keys` → `pkg/identity`, `applications/api` → `service/api`,
`deploy/alembic` → `migrations/` at the repo root, where Alembic already lives.)

---

## R1 — Role model in `pkg/rbac/roles.py`  ✅ implemented

**Why first:** everything else (migration seed, API guards, tests) derives from one Python
source of truth, so it must exist before anything references role codes.

The pure engine (`decide()`) already evaluated capability bindings with scope inheritance,
layer restrictions, DENY-wins, and expiry. R1 adds vocabulary and validation on top —
enforcement stays in the one existing function.

Key decisions, worth keeping when extending:

- `RoleDefinition` separates `capabilities` (control-plane, no layer) from
  `layer_grants: tuple[LayerGrant, ...]`, because one binding cannot say "read every layer
  but write only raw+bronze" — `compile_binding()` therefore expands a role into one binding
  for the control-plane set plus one per layer grant.
- `allowed_principal_kinds` on the role makes principal-kind constraints data, not code;
  `bindable_scopes` does the same for "platform_owner binds only at SYSTEM".
- `validate_binding(role, kind, scope_type)` raises typed `RoleError` subclasses that the API
  maps to 422; `compile_binding` calls it, so there is no unvalidated path to a stored grant.
- `rbac.Principal` gained `kind` ("user" | "service_account"); a service account's identity
  is `sa:{subject}`, so user and SA namespaces cannot collide.

## R2 — Layer workflow in `pkg/catalog/layers.py`  ✅ implemented

The catalog owns *what the layers mean*; it performs no I/O. `LayerSpec` records each layer's
`derived_from`, `principal_writable`, `accepts_direct_entry`, and producing deployable. The
functions the rest of the system uses:

- `required_capability(action, layer) -> ("data.write", "silver")` — the vocabulary bridge
  into rbac.
- `ensure_layer_writable(layer, principal_kind)` — refuses any human on silver/gold
  **independently of bindings** (defense in depth: a mis-seeded binding still cannot let a
  user through, because this check does not consult bindings at all).
- `validate_promotion(source, target)` — raw→bronze→silver→gold(+bronze); the pipeline
  services will call this before deriving.
- `validate_entry(layer)` / `parse_entry_layer(value)` / `entry_layers()` — the *entry* rule,
  orthogonal to both of the above. `derived_from` says what a promotion may read; it never
  said promotion is the only way in. Raw, bronze and silver accept data that is already in
  that form when it reaches Huron (external provenance, not a lower-layer reference); gold
  refuses, because invariant K requires a derivation record on every product version. Note
  the two rules are genuinely independent: silver refuses *human writers* and still accepts
  *direct entry* — one says who may commit, the other says where the bytes came from.

## R3 — Principal kinds in `pkg/identity`  ✅ implemented

`Principal.kind` and `ApiKeyRecord.owner_kind` (default `"user"`), threaded through
`create_api_key(..., owner_kind=)` and `ApiKeyResolver.resolve()`. A key minted for a service
account therefore *authenticates as* a service-account principal, and every downstream check
(role validation, `ensure_layer_writable`) sees the right kind. OIDC-resolved principals are
always users.

## R4 — Migration `0002_rbac` + `migrations/schema.sql`  ✅ implemented, applied on PG16

New tables (3NF): `principals` (class supertype; `kind`, unique `subject`, optional
`idp_subject` for the OIDC `sub` claim), `service_accounts` (owned by an organization,
`UNIQUE (organization_id, name)`), `roles`, `capabilities`, `role_capabilities` (the M:N with
the single role-dependent attribute, `layers text[]`, NULL = every layer), `policies`,
`policy_attachments`. `role_bindings` reworked: the free-form `capabilities text[]` column
from 0001 is dropped, `role` becomes `role_code REFERENCES roles`, and
`UNIQUE NULLS NOT DISTINCT (principal, role_code, scope_type, scope_id)` (PG15+) closes the
"two identical SYSTEM bindings" gap that plain UNIQUE leaves open with a NULL scope_id.

The invariants live in the database, not only the app:

- `role_bindings_guard` (BEFORE INSERT OR UPDATE): derives the principal kind from the
  `user:`/`group:`/`sa:` prefix and rejects a binding whose kind or scope level the role
  does not allow. Verified rejections: any `sa:` principal → any role (since `0007` all five
  roles are user-only, so this is the whole principal-kind case), platform_owner→ORGANIZATION
  scope, bad prefix, exact duplicate.
- `service_account_kind_guard`: a `service_accounts` row must reference a
  `kind='service_account'` principal.

The role/capability **seed mirrors `rbac/roles.py`** — change the Python first, then write a
follow-up data migration. `migrations/schema.sql` is the human-readable summary of the whole
metastore (all six sections; it covered `0001`+`0002` when this step landed and now spans
`0001`–`0007`); it is documentation, never executed.

## R5 — The Depends chain in `service/api/authorization.py`  ✅ implemented

One module, four stages, so routes contain zero authorization logic:

```python
@router.post("/projects/{project_id}/datasets", status_code=201)
async def create_dataset(
    request: Request, project_id: UUID, body: CreateDataset,
    idempotency_key: IdempotencyHeader,
    _actor: Annotated[Principal, Depends(require_project("dataset.create"))],
): ...
```

- `current_principal(request)` — credential → principal. `Bearer hk_*` resolves as an API
  key; any other bearer token goes to the injected OIDC verifier (401 if none configured);
  `X-Huron-Subject`/`X-Huron-Groups` headers work only when `auth_mode == "dev-headers"`,
  which settings refuse outside development. Holding a `Principal` from a `require_*`
  dependency IS the proof the check passed.
- Scope builders `organization_scope` / `project_scope` / `dataset_scope` load the resource
  (404 before 403 for unknown ids) and fill in ancestry so inherited bindings match.
- `require_system/organization/project/dataset(capability)` — dependency factories; FastAPI
  merges their path parameter with the route's own.
- `dataset_layer_writer` — the data-plane guard: `parse_layer` → `ensure_layer_writable`
  (kind rule) → `check(..., layer=...)` (binding rule). Two independent gates.

## R6 — Route modules under `routes/v1/`  ⚠️ partially implemented

`schemas.py` (request bodies; `CreateRoleBinding.principal` is regex-validated to the three
prefixes), `common.py` (pagination, If-Match parsing), and six endpoint modules. The RBAC
surface: `GET /roles`; `POST /{scope}/bindings` at all four scope levels, each guarded by
`rbac.binding_manage` *at that scope*, and `GET /{scope}/bindings` at the **organization and
project levels only** — `GET /bindings` and `GET /datasets/{id}/bindings` answer 405, so this
plan's earlier claim of "`POST`+`GET` at all four scope levels" was never true (receipts:
`API_DESIGN.md` § "Roadmap Drift" → "Drift 4"). No binding path carries an update verb on any
backend, so the shipped shape is binding **create, list and revoke — no update verb**, not CRUD.
`DELETE /bindings/{id}` re-derives the binding's own scope and checks there (a project admin
cannot revoke an org binding); service accounts and
their keys under `/organizations/{id}/service-accounts...`, guarded by
`service_account.manage`; policy attach routes guarded by the per-resource
`*.policy_attach`. `POST /auth/api-keys` issues only for the caller — keys inherit subject
and kind, so they can never escalate.

**Completion is designed, not shipped.** `API_DESIGN.md` § "Design 7 — Binding surface completion"
adopts the scope-rooted shape as the target: the two missing `GET` collections, and `DELETE` moved
under each scope root so `DELETE /bindings/{binding_id}` revokes a SYSTEM binding only. It is
sequenced as `API_IMPLEMENTATION_PLAN.md` § "M9 — Binding surface completion" (tasks M9.1 and
M9.2), both `Status: pending` and both gated on a human decision — **D-12** (the `DELETE` narrowing
is a contract break) and **D-13** (whether the collections list lapsed grants). This heading
becomes `✅ implemented` when M9 lands, not before.

## R7 — `app.py` as pure composition root  ✅ implemented

Wiring only: settings, repository, optional `oidc_verify` callable → `OidcResolver`,
exception mapping (`DomainError`→its status, `IdentityError`→401, `RoleError`→422, all
problem+json), health probes, `include_router(v1.router, prefix="/api/v1")`. Bootstrap:
`HURON_BOOTSTRAP_PLATFORM_OWNER` grants that subject one SYSTEM `platform_owner` binding at
startup (idempotent) — the single way into an empty deployment; unset it once real bindings
exist. Repository additions backing all this are in-memory for now (`grant_role` compiles
via `compile_binding` and stores both the record and its compiled bindings;
`bindings_for(identifiers)` feeds `decide()`).

## R8 — Tests  ✅ implemented (14 passing)

- `test_rbac_roles.py` — the matrix invariants: service accounts are the only intrinsic
  silver/gold writers; admin roles carry no `data.write`; platform_owner binds only at SYSTEM;
  compiled developer bindings allow raw, deny silver; org-scope binding inherits to dataset
  scope and not across organizations.
- `test_catalog_layers.py` — writability by kind; promotion graph; capability pairs.
- `test_api_rbac.py` — the full delegation story over HTTP: root seeds org → delegates to
  alice (org admin) → alice grants bob developer → bob writes raw/bronze, is refused
  silver/gold; alice (admin) is refused raw; a service-account role binding is 422; alice creates
  the roleless SA + key; the SA writes silver/gold, is refused raw/bronze; disabling the SA
  revokes its keys and removes access. Plus policy-attach guards and key-inheritance.

---

## Remaining steps (small, in order)

### R9 — PostgreSQL-backed stores behind the existing seams  ✅ implemented and verified

Replace the in-memory maps with asyncpg/SQLAlchemy repositories, one Protocol at a time,
without touching routes or guards:

1. `BindingStore` Protocol in `pkg/catalog/ports.py` (or a new `pkg/rbac` port consumed via
   injection): `bindings_for(identifiers) -> tuple[Binding, ...]`,
   `grant/revoke/list_at(scope)`. The SQL for `bindings_for` joins
   `role_bindings → role_capabilities` and builds `Binding` values; scope ancestry stays in
   Python (the scope builders already carry org/project ids), so no recursive CTE is needed.
2. Same for api_keys (`api_keys` table already exists; add `last_used_at` touch) and
   service accounts (insert the `principals` row + `service_accounts` row in one
   transaction; the DB trigger backstops the kind).
3. Cache `bindings_for` per request at most (the guard runs once per request); add a
   process-level TTL cache only when measured.
4. Contract test (`-m contract`, testcontainers): migrate, then diff the seeded
   roles/capabilities against `rbac.roles.ROLES` — the test that keeps Python and SQL from
   drifting. Extend the trigger negative cases exercised manually in R4 into this test.

R9 landed as a `RbacStore`/`ApiKeyWriter` Protocol split, following the same DI idiom as
`pkg/catalog/ports.py`: `InMemoryRbacStore` (the lifted, now-async original logic — still the
default) and `PostgresRbacStore`/`PostgresApiKeyStore` (asyncpg, opted into via
`ApiSettings.rbac_backend: Literal["memory", "postgres"] = "memory"`, deliberately *not*
inferred from "no repository injected" after that inference briefly became the default and
crashed on FK violations, since the organization/project/dataset hierarchy is still in-memory
and can't satisfy `service_accounts.organization_id` / `api_keys.project_id`). `bindings_for`
reconstructs `Binding` values in exactly the shape `compile_binding()` produces, verified by
direct comparison against a live Postgres 16 instance — every one of the contract test's 13
assertions (seed-vs-`ROLES`, seed-vs-`CAPABILITIES`, grant/read/revoke round trips, service
account and policy round trips, API key round trip, all 5 trigger negative cases) was executed
for real, not just read for correctness. `pytest -m contract` itself still needs a Docker-
capable machine to run as-authored (testcontainers) — the live check here bypassed that one
dependency by running the schema DDL directly and calling the test module's own
`_assert_against()` against a hand-started Postgres, which is a permanent gap for any sandboxed
verification environment, not a defect in the test.

Two production bugs were caught in review before landing: `create_app()` called
`asyncio.run()` inside its own synchronous body to bootstrap the platform-owner binding, which
crashes if `create_app()` is ever invoked from a running event loop, and double-bootstraps
when both `repository` and `settings` are injected — fixed by making the lifespan the sole
bootstrap path. And the wiring bug above (FK violations surfacing as unhandled 500s) — fixed
by catching `asyncpg.ForeignKeyViolationError` and mapping it to `ResourceNotFound`, and by
making Postgres wiring an explicit opt-in rather than an inferred default.

### R10 — Real JWT verification for the UI path

`OidcResolver` already accepts any `verify: Callable[[str], Mapping]`. Provide one in the
composition root (services may use httpx; `pkg/` may not): fetch the issuer's JWKS (cache by
`kid`, respect cache headers), verify signature + `iss` + `aud` + `exp` with `pyjwt`
(add dependency; `PyJWK` handles the key types), map `sub`→subject and the groups claim from
settings (`oidc_issuer`, `oidc_audience`, `oidc_groups_claim`). On first login, upsert the
`principals` row keyed on `idp_subject`. Group-based bindings (`group:...`) then work with
zero extra machinery because `Principal.identifiers` already includes them.

### R11 — Make the layer rule bite at storage

The catalog check is necessary, not sufficient, while NFS/RGW are directly reachable:

- Object store (bronze/silver/gold): per-layer prefixes; bucket policy grants writes only to
  STS credentials minted by `pkg/credentials`, and the credential vendor mints a write grant
  **only when handed a `WriteIntent`** produced by the guarded
  `/datasets/{id}/layers/{layer}/write-intents` route (persist the intent + expiry when the
  vendor lands in P8; today the route returns the authorization proof).
- Raw (NFS): scientists commit through the ingest API (P2 machinery) running as the API's
  service user; human POSIX access to `/data/raw` is read-only. Reads can later move to the
  same grant flow (invariant L: grants read-only for non-service principals, always expire).

### R12 — Audit + discovery filtering

Emit an `audit_events` row for every DENY and every 2xx mutation (actor, capability,
resource, decision) — the partitioned table exists. Then use the already-present
`RoleBindingAuthorizer.visible_project_ids` (dataset.discover + classification clearance) to
filter listings and the search projection instead of returning every org/project to any
authenticated principal.

### R13 — Design record + UI

Add the role matrix and the SA-only invariant to `design/` (a governance page anchor P5 can
cite; include the "admins don't write data" rationale), and surface bindings in the UI
Grafana-style — one row per binding, "Add permission" row, explicit inherited-vs-set
indicators — per the direction already recorded for the catalog explorer.

---

## Verification ledger (this change)

`ruff check` and `ruff format --check` clean; `mypy --strict` over `pkg/` + `schema/` clean;
all four import-linter contracts KEPT (rbac and catalog remain framework-free — the role
model and layer workflow import nothing but stdlib + rbac); `pytest -m unit`: 14 passed.
Migrations 0001+0002 applied to a clean PostgreSQL 16; `role_bindings_guard` rejected
pipeline-for-user, platform_owner-at-org, malformed principal, and duplicate-SYSTEM-binding;
seed counts per role match the Python matrix.

### Entry layers + `ingest_pipeline` (2026-08-30)

`design/` was updated first (index decision 15, architecture invariant N, layer-silver §4
direct entry, layer-gold §1 derivation-defined, a staleness banner on the retired role
taxonomy in rbac.html §2). Then: `accepts_direct_entry` + `validate_entry` /
`parse_entry_layer` / `entry_layers` in `pkg/catalog/layers.py`; the `ingest_pipeline` role;
`schema/documents/snapshot-provenance-v1.json` (promotion | external | derivation, with the
negative cases tested); migration `0004_entry_layers` adding `datasets.entry_layer` and the
two invariant-N CHECKs on `snapshots.provenance`; `entry_layer` threaded through
`CreateDataset` → repository → the `/datasets/{id}/layers` response.
