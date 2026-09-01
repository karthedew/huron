# Huron — API Tier Implementation Plan

Companion to [`API_DESIGN.md`](API_DESIGN.md), which is the authoritative specification for
everything below. This file sequences that design into milestones and mechanically verifiable tasks;
it never restates the design. Every task names the `API_DESIGN.md` heading that specifies it, and an
implementer is expected to read that heading before editing.

This plan is executed by `/implement-markdown API_IMPLEMENTATION_PLAN.md`. It is deliberately named
apart from [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) (the shipped platform plan) and
[`RBAC_IMPLEMENTATION_PLAN.md`](RBAC_IMPLEMENTATION_PLAN.md).

---

## 0. How an implementer reads this plan

**The task is the atomic unit, not the milestone.** `/implement-markdown` runs the complete
validation gate after every task. A task therefore must leave the tree compiling, the gate green,
and no half-migrated surface behind it. Where a change genuinely cannot be split without breaking
the tree, this plan says so and gives the milestone exactly one large task rather than pretending it
splits.

**Resolved package path: `src/huron`** (`[tool.hatch.build.targets.wheel] packages = ["src/huron"]`).

**The validation gate**, verbatim, run from the repository root after every task:

```text
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run mypy
uv run lint-imports
uv run pytest --cov=src/huron --cov-report=term-missing
uv run radon cc src/huron --min C
uv run radon mi src/huron --min B
uv run complexipy src/huron --max-complexity-allowed 15
uv run pyscn check src/huron
```

Facts about this repository's gate that the tasks below depend on, checked against
`pyproject.toml` rather than assumed:

- `[tool.pytest.ini_options] addopts = "-m unit --strict-markers"`. **A bare `uv run pytest` runs
  the `unit` marker only.** The gate's pytest line therefore does *not* run `tests/contract/`. Any
  task that changes a Protocol or one of its implementations must additionally run
  `uv run pytest -m contract` and report it; this is called out per task where it applies. That run
  needs the container runtime named under **Environment prerequisites** below.
- Registered markers: `unit`, `contract`, `integration`, `acceptance`. No new marker may be added.
- `[tool.coverage.report] fail_under = 75`. This is a ratchet: never lower it, raise it when
  coverage climbs. Every file touched by a task is at 100% line coverage unless a specific line is
  judged unreachable defensive code.
- `mypy` is configured with `strict = true` and `files = ["src/huron/pkg", "src/huron/schema"]`;
  `[tool.ty.src] include` mirrors it. **Milestone 10 widens both to `src/huron`.** Until then, code
  under `src/huron/service` is not type-checked by either tool, which is why several tasks carry an
  explicit "run `uv run mypy --strict src/huron/service/...` by hand before declaring done"
  acceptance step — the gate will not catch it for you yet.
- `pyscn` is declared with a platform marker and will not install on every host; see **Environment
  prerequisites** below.
- Convenience targets that exist and may be used for fast local loops, but do **not** substitute for
  the gate: `make test` (`uv run pytest -m unit`), `make lint` (ruff check, ruff format --check,
  mypy, lint-imports).

**Environment prerequisites — check these once, before M1.1.** They are properties of the host the
plan runs on, not of the plan or of the repository. If any is unmet, **stop and report**; none of
them may be worked around by skipping, weakening or deleting a gate step (rule 2 below).

- **A container runtime** (Docker or Podman) reachable by `testcontainers`. Both modules under
  `tests/contract/` drive a migrated PostgreSQL, so every per-task `uv run pytest -m contract` step
  in this plan — M1.1, M2.1, M3.1, M8.1, M9.2 — and §5's final contract run depend on it. Without
  one, both contract modules fail with `FileNotFoundError` on the daemon socket, for reasons
  unrelated to the change under test. A task that cannot run its mandatory contract step is not
  done, and the step is not optional: stop and report.
- **An `x86_64` or `darwin` host**, because `pyscn` is declared with the marker
  `platform_machine == 'x86_64' or sys_platform == 'darwin'`. On any other host it will not install,
  `uv run pyscn check src/huron` fails with `Failed to spawn: pyscn`, and the gate's last line — and
  M3.2's `pyscn` acceptance criterion — cannot be satisfied. Stop and report; do not drop `pyscn`
  from the gate and do not declare a task done with that line red.
- **A clean mypy cache.** A stale `.mypy_cache/` in the working copy makes `uv run mypy` — the
  gate's fourth line, and part of `make lint` — exit 2 with `INTERNAL ERROR` before any task has
  changed anything, while the same check run with a fresh cache reports success. Clear
  `.mypy_cache/` (or pass a fresh `--cache-dir`) once before M1.1, and again on any `INTERNAL
  ERROR`. `.mypy_cache/` is gitignored, so this is a working-copy condition, never a gate failure to
  record against a task and never evidence of a defect in the change under test.

**Rules that bind every task in this plan.**

1. **No code comment, docstring, test name, commit note, or user-facing string may reference this
   plan, its milestones, task numbers, the design document, or checklist mechanics.** Comments
   explain enduring code intent — invariants, lifecycle rules, security boundaries, tradeoffs — and
   are rare. A test is named for the behavior it pins, never for the milestone that added it.
2. **Clean sweep.** No backwards-compatibility shim, no deprecation alias, no re-export left behind,
   no TODO, no speculative abstraction, no partial migration, no suppressed lint. `# noqa`,
   `# type: ignore`, `# pragma: no cover`, `skip` and `xfail` may not be introduced to make the gate
   pass. If the gate cannot be satisfied without one, stop and report.
3. **No migration.** No task in this plan may add, edit, or require a file under `migrations/`, and
   none may change SQL in `postgres_rbac.py` or `postgres_auth.py`. Only Python module boundaries
   move. If a task appears to need a migration, that is a plan defect — escalate.
4. **Deletions land with the change that makes them dead**, in the same task, never deferred.
5. **A gated task may not be started until its decision is recorded in section 2.** Recording a
   decision means the owner answered; it does not mean the recommendation was adopted. If the answer
   differs from `API_DESIGN.md`'s recommendation, stop — that is a design change and belongs back in
   `/design-plan`, not in an implementer's judgement.

---

## 1. Goal and non-goals

**Goal.** Bring `src/huron/service/api` to the target described in `API_DESIGN.md`: blocking work off
the event loop under one stated rule; a total, typed composition root with declared dependencies
instead of `Request`-threading; `repository.py` decomposed so storage adapters no longer import the
application service; a router tree where prefix, tags and authentication are declared once and the
whole versioned surface is closed to anonymous callers; a declared response type and a real
pagination envelope for every operation; one uniform `application/problem+json` error contract with a
mechanically checked code table; and the binding surface completed.

**Non-goals — explicitly out of scope for every task in this plan.**

- **`src/huron/schema` and `migrations/`.** Both are being changed concurrently by other work. No
  task here may edit either, and no task may require a migration. See rule 3 above.
- **`src/huron/pkg` beyond what a named design section requires.** The only permitted `pkg` edits
  are: `ResourceNotFound` and `InvalidCursor` added to `huron/pkg/catalog/errors.py` (M3, M6);
  `ClassificationUnknown` added there (M4); and M8's subtractive changes to
  `huron/pkg/catalog/errors.py` and the one attribute deletion in `huron/pkg/rbac/roles.py`.
  Nothing else in `pkg` is touched.
- **Documentation reconciliation.** `design/roadmap.html`, the ten Roadmap Drift entries in
  `API_DESIGN.md`, `CONTROL_PLANE_PLAN.md`'s ratified claim, `RBAC_IMPLEMENTATION_PLAN.md` R6's
  wording, and five of the six `design/api.html` edits listed under Design 6's *"Documentation edits
  handed to Phase 5"* belong to the roadmap-reconciliation phase, not to this plan. **The one
  exception is load-bearing and is in scope:** `design/api.html` §7 must become
  `<table id="error-codes">` in M8, because `tests/unit/test_error_contract.py` parses that `id` and
  is unsatisfiable without it. That single edit is task M8.3's; the other five are not.
- **`web/`.** No frontend code is written, built, or served. Design 8 settles that the API serves no
  assets; nothing in `web/` is edited.
- **Persistent hierarchy storage, keyset pagination pushed into queries, policy evaluation, ingest,
  release reachability, `GET /metrics`, and in-process rate limiting.** Each is named in
  `API_DESIGN.md` as future work with its seam recorded. No task anticipates any of them.
- **Every open question in section 2 that is still unanswered.** An unanswered decision blocks its
  task; it is never resolved by the implementer.

---

## 2. Human decision register

`API_DESIGN.md` raises **33 open questions** across its nine design sections. Eighteen are settled
inside the document by a recommendation that needs no external fact (for example Design 2's OQ3 on
`dependency_overrides`, Design 3's OQ1 on where `limit` descends, Design 6's OQ3 on the `NOT_FOUND`
collision); implementers follow those directly and this register does not repeat them.

The **fifteen below need a human**, because each is either a visible contract break, a capacity or
deployment number this repository cannot supply, or a policy choice about code that does not exist
yet. Each is stated as a question with the design's recommendation, the milestone it gates, and the
blast radius if the answer differs.

**D-16 is a sixteenth entry that does not come from one of the 33.** It is a wire-visible contract
break this plan surfaced while sequencing Design 3's `### Deletions`, which state the deletion but
not its effect on response bodies. It is recorded in the same table because it gates a milestone the
same way the other fifteen do.

| ID | Decision | Source | Recommendation | Gates |
|---|---|---|---|---|
| **D-1** | Is `huron.service.api.app:app` named by any deployment artifact outside this repository? Rename to `huron.service.api.main:app`. | D2 OQ1, D8 OQ1 | Rename; edit the **three** in-repo files (`Makefile:30`, `Containerfile` `CMD`, `docs/getting-started/local-development.md:131`) — Design 8 corrects Design 2's count of two. | M2 (operator gate — see note) |
| **D-2** | Does password hashing get its own capacity limiter, and at what size? | D1 OQ1 | Yes, default 4, passed at the `verify_password` call site. | M1.2 only |
| **D-3** | `GET /api/v1/roles` becomes `401` to anonymous callers. Contract break. | D4 OQ1 | Authenticate it. | M5 |
| **D-4** | `GET /api/v1/search` becomes `401` to anonymous callers and moves out of `app.py`. Contract break. | D4 OQ2 | Authenticate and relocate. | M5 |
| **D-5** | Twelve OpenAPI tags instead of seven; generated SDK shape changes. | D4 OQ3 | Adopt the finer set. | M5 |
| **D-6** | The envelope break: `count` is removed, `limit`/`after` are added, and an out-of-range `limit` becomes `422` instead of a silent clamp. Contract break on every collection. | D5a OQ3 + D5a `#### limit, after, …`, D5b OQ4 | Ship it. | M6, M7 |
| **D-7** | `GET /api/v1/roles` loses its `{"items": [...]}` wrapper and returns a bare `list[RoleView]`. Contract break. | D5b OQ4 | Ship it with D-6. | M7.1 |
| **D-8** | `GET /auth/session` gains `effective_roles: list[ScopeRoles]`, fetched on every page load; a principal bound at fifty datasets reports fifty entries. | D5a OQ1 | Ship as designed; the roadmap's `todo` applies to the frontend alone. | M6.3 |
| **D-9** | Is `GET /api/v1/roles` readable by every authenticated caller, or does it require `rbac.binding_manage`? | D5b OQ1 | Every authenticated caller; the catalog is vocabulary, not configuration. | M7.1 |
| **D-10** | What byte ceiling, if any, bounds `CreatePolicy.spec`? The design asks for a domain number it cannot supply. | D5b OQ2 | Bound the request, not the response. **If no number is supplied, ship no bound** and record that as the answer — do not invent one. | M7.3 |
| **D-11** | Rename the documented code `SESSION_EXPIRED` → `INGEST_SESSION_EXPIRED` (409, reserved) and add a new `SESSION_EXPIRED` (401, live). | D6 OQ4 | Rename. | M8.1 |
| **D-12** | `DELETE /api/v1/bindings/{binding_id}` narrows from "revoke any binding" to "revoke a SYSTEM binding"; the same id now answers `404` there. Contract break. | D7 OQ3 | Ship it with D-6. | M9.1 |
| **D-13** | Do the binding collections list grants that have already lapsed? | D7 OQ4 | Return them; `bindings_at` does not filter expiry and `expires_at` is published. If the owner prefers filtering, the filter belongs in `bindings_at` on **both** backends — which this plan forbids (rule 3) and which would return the work to `/design-plan`. | M9.2 |
| **D-14** | `POST /api/v1/datasets/{id}/releases` cannot succeed until P2 ingest lands. Is that accepted, and pinned by a test that drives `register_revision` directly? | D3 OQ2, D5a OQ4 | Accept and pin. | M4.2 |
| **D-15** | `[tool.mypy].files` / `[tool.ty.src].include` become `["src/huron"]` rather than three explicit surfaces, so future service tiers inherit `--strict` without opting in. | D8 OQ2 | `["src/huron"]`. | M10.1 |
| **D-16** | Deleting `Release.withdrawn_at` and `Release.withdrawn_reason` removes two documented keys from live response bodies: both records reach the wire through `jsonable` → `asdict`, so `GET /api/v1/datasets/{id}/releases` and `GET /api/v1/datasets/{id}/releases/{tag}` both change shape. Contract break. | Plan — D3 `### Deletions` orders the deletion but states only the persistence effect | Ship it with D-6, D-7 and D-12 as part of the one grouped release; the fields are always `null` today, but a removed key is still a removed key. | M3.2 (and, through M4.1's dependency on M3.2, all of M4) |

**Note on D-1 and the critical path.** D-1 is the only decision that touches a milestone the whole
chain depends on, and it is deliberately structured as an **operator gate rather than a code gate**:
the code shape is not in question. Design 2's `create_app` cannot build an app without settings, so
`main.py` must exist and must be the module that reads the environment; that is settled inside the
design. What a human must supply is the fact this repository cannot hold — whether a Kubernetes
manifest, Helm chart, systemd unit or CI deploy job outside this tree names the old string. M2 may
therefore be implemented while that check is outstanding, but **the result may not be deployed until
D-1 is answered.** If the answer is "yes, external artifacts name it", those artifacts are updated
outside this repository in the same release; no code changes.

**How the gates are arranged so the sequence is not blocked behind them.** M1 and M3.1 — the whole
execution-model change and the mechanical, contract-preserving half of the `repository.py`
decomposition — are ungated and can be implemented while the answers are collected. Two gates sit
inside otherwise-ungated milestones: M1.2 on D-2, which is one call-site argument, and **M3.2 on
D-16**, which is a visible contract break and therefore belongs to the grouped release. Because
M4.1 depends on M3.2, M4 inherits D-16 as well; M4 carries no gate of its own beyond D-14 on M4.2.
Every remaining gate (D-3 through D-13, plus D-16) is a visible contract break, and all of them
should ship as **one release**, not five; grouping them behind M3.2 and M5–M9 is what makes that
possible.

---

## 3. Milestone sequence

`API_DESIGN.md`'s `## Design Tasks` → `### Ordering` fixes the chain: 1 → 2 → 3 → 4 → 5 → 5b → 6 → 7,
with 8 free-floating. This plan follows it, splits Design 3 and Design 5 where the design itself
names the split, and lands Design 8 last because its type-check widening and Ruff `FAST` rules would
otherwise be enforced against code that six later milestones rewrite.

| # | Milestone | Design | Gated on | Shape |
|---|---|---|---|---|
| **M1** | Execution model: blocking I/O off the event loop | Design 1 | D-2 (task M1.2 only) | 2 tasks |
| **M2** | Composition root, `ApiRuntime`, injected dependencies, entrypoint module | Design 2 | D-1 (operator) | **1 task — atomic** |
| **M3** | `repository.py` decomposition and the record relocation | Design 3 | D-16 (task M3.2) | 2 tasks |
| **M4** | Repository query methods, classification enforcement, release pinning | Design 3 | D-14 (task M4.2); inherits D-16 via M4.1's dependency on M3.2 | 2 tasks |
| **M5** | Router composition and the authenticated surface | Design 4 | D-3, D-4, D-5 | **1 task — atomic** |
| **M6** | Response models for the resource surface, and the pagination envelope | Design 5 | D-6, D-8 | 3 tasks |
| **M7** | Response models for the administrative surface | Design 5b | D-6, D-7, D-9, D-10 | 3 tasks |
| **M8** | Error contract and `problem+json` coverage | Design 6 | D-11 | 4 tasks |
| **M9** | Binding surface completion | Design 7 | D-12, D-13 | 2 tasks |
| **M10** | Type-check scope, entrypoint rationale, Ruff `FAST` | Design 8 | D-15 (task M10.1) | 3 tasks |

**The atomic milestones, and why they do not split.** M2 and M5 are each one task because the change
has no green intermediate state:

- **M2** deletes `authorization.get_repository` and `get_settings` while making `create_app`'s
  `settings=` required. The moment either provider is deleted, all 44 `request: Request` path
  operations, both `_configure_oidc` call paths, the four `app.state` attributes and the eight test
  modules that construct apps break together. Keeping the old providers alongside the new
  `Annotated[..., Depends(...)]` aliases for one task would be exactly the compatibility shim rule 2
  forbids. It is a single ~55-file-touch task and is sized as one.
- **M5** moves `prefix=`, `tags=` and `dependencies=[Depends(current_principal)]` onto the routers,
  splits `endpoints/rbac.py` into three modules, renames `endpoints/auth.py`, and relocates
  `/api/v1/search`. The prefix cannot move to the router while the decorators still carry it, and the
  module split cannot land before the `include_router` calls that name the new modules. Every path in
  the tier is either byte-identical afterwards or is one of the two deliberate contract changes; a
  partial pass produces 404s on live routes.

M8's first task is atomic for the same reason at smaller scale — `DomainError` becoming abstract
breaks all fourteen bare raise sites in the same instant — but the `/readyz` rewrite, the bijection
test and the `responses={}` declarations are genuinely separable and are separate tasks.

---

## M1 — Execution model: blocking I/O off the event loop

Design: `API_DESIGN.md` → `## Design 1 — Execution model: blocking I/O off the event loop`.

### Task M1.1 — Apply the execution-model rule to every handler and blocking site

**Intent.** Move every blocking call in the tier off the event loop under one stated rule, so no
request can stall the loop for another.

**Design reference.** `## Design 1` → `#### The rule`, `#### Signatures — the eight that become
def`, `#### Signatures — the three that stay async def and wrap`, `#### Dependency: asyncer, yes`,
`#### Disposition of all 47 operations`, `#### Blocking sites outside handlers`,
`### Explicit contracts`, `### Constraint imposed on tasks 2 and 3`.

**Create.** `tests/unit/test_execution_model.py`.

**Modify.** `pyproject.toml` (`[project.dependencies]` — add `asyncer` via `uv add asyncer`; this
task owns that line, Design 8 owns `uvicorn`/`sqlalchemy`) and `uv.lock`. Handler keywords in every
module under `src/huron/service/api/routes/v1/endpoints/` and `routes/auth/endpoints/`, per the
disposition table — eight become `def`, three stay `async def` and wrap their blocking call with
`asyncer.asyncify(...)`, the rest are unchanged. `src/huron/service/api/app.py` (`readyz`'s
`root.exists()` stat), `src/huron/service/api/repository.py` (`HierarchyRepository.__init__`'s
`raw_store.initialize()`), `src/huron/service/api/authorization.py` (the `require_*` guards'
synchronous scope lookups) — each per `#### Blocking sites outside handlers`.

**Delete.** Nothing. Design 1's `### Deletions` says so explicitly, and both `RLock`s are kept
deliberately.

**Depends on.** Nothing. This is the first milestone.

**Verify.**

```text
uv add asyncer
uv run python -c "import asyncer, inspect; print('limiter' in inspect.signature(asyncer.asyncify).parameters)"
uv run pytest tests/unit/test_execution_model.py -m unit -q
uv run pytest -m contract -q
<full validation gate>
```

**Acceptance criteria.**

- `uv run python -c "import asyncer"` succeeds and `asyncer` appears in `[project.dependencies]`.
- The `python -c` probe above prints `True`, or the implementer records that it printed `False` and
  used `anyio.to_thread.run_sync(..., limiter=...)` as Design 1's stated fallback mechanism. This is
  the version check Design 1's Open question 1 requires before M1.2 can rely on `limiter=`.
- `grep -c 'async def' ` over the endpoint modules matches the disposition table exactly: the eight
  named operations are `def`, the three named are `async def`, and no other keyword changed. The
  table in `#### Disposition of all 47 operations` is the oracle; a mismatch on any row is a failure.
- `cancellable=True` appears at none of the three `asyncify` call sites
  (`! grep -rn 'cancellable' src/huron/service/api`).
- `tests/unit/test_execution_model.py` asserts, by parsing `src/huron/service/api/repository.py` with
  `ast`, that no `Await` node appears anywhere inside any mutating method of `HierarchyRepository`.
  This pins the contract stated verbatim in `### Explicit contracts` — *"no `await` may ever appear
  inside that critical section"* — which is a real invariant about the lock, not an implementation
  detail: an `await` there reintroduces the stall while a worker thread holds `_lock` across an
  `fsync`.
- The existing suite is unchanged in behavior: `401`, `403`, `404`, `422` and the mutating `2xx`
  statuses are identical before and after. `uv run pytest -m unit` passes with no test edited to
  accommodate a keyword change.
- `uv run pytest -m contract` passes (not covered by the gate's pytest line).
- Full validation gate clean.

**Status: pending**

### Task M1.2 — Dedicated capacity limiter for password hashing — **GATED on D-2**

**Intent.** Bound Argon2id's memory and CPU blast radius to a queue on `/auth/login` instead of the
shared 40-token threadpool limiter.

**Design reference.** `## Design 1` → `### Open questions` question 1, and `### Explicit contracts`
(*"Threadpool and request concurrency"*).

**Modify.** The `verify_password` `asyncify` call site in `routes/auth/endpoints/login.py`; wherever
the limiter object is constructed (module level, alongside the call site).

**Depends on.** M1.1 (the call site must exist and the `limiter=` probe must have been run). **Do not
start until D-2 is recorded in section 2 with a concrete integer.**

**Verify.**

```text
uv run pytest tests/unit/test_api_login.py -m unit -q
<full validation gate>
```

**Acceptance criteria.**

- The limiter is a module-level `anyio.CapacityLimiter` with the total the owner supplied, passed at
  exactly one call site; `grep -rn 'CapacityLimiter' src/huron` returns one construction.
- A unit test asserts the limiter's `total_tokens` equals the decided value, so the capacity decision
  is pinned in code rather than in a comment.
- Login behavior is unchanged: unknown-user and wrong-password still take the dummy-hash path and
  `tests/unit/test_api_login.py` passes untouched.
- Full validation gate clean.

**Status: pending**

---

## M2 — Composition root, `ApiRuntime`, injected dependencies, entrypoint module

Design: `API_DESIGN.md` → `## Design 2 — Composition root, app.state, and injected dependencies`.
Also `## Design 8` → `#### 1. Entrypoint — uvicorn stays; no fastapi-cli, no [tool.fastapi] table`
for the entrypoint string, whose in-repo occurrence count Design 8's Open question 1 corrects to
three.

### Task M2.1 — Make the composition root total and typed — **one atomic task**

**Intent.** Remove every path by which a request can reach unset composition-root state, and replace
`Request`-threading with declared dependencies.

**Design reference.** `## Design 2` → `#### New module: src/huron/service/api/runtime.py`,
`#### create_app`, `#### New module: src/huron/service/api/main.py`,
`#### authorization.py — the injected shape`, `#### Handler signatures — the shape every endpoint
module takes`, `#### app.state inventory — the decision on each of the six`,
`#### The four app-level routes`, `### Explicit contracts`, `### Deletions`. Design 1's
`### Constraint imposed on tasks 2 and 3` governs the providers' keyword.

**Create.** `src/huron/service/api/runtime.py` (the frozen `ApiRuntime`, `api_runtime`, and the named
`Annotated[..., Depends(...)]` aliases); `src/huron/service/api/main.py`.

**Modify.** `src/huron/service/api/app.py` (`create_app` signature and body, lifespan, `_configure_oidc`);
`src/huron/service/api/settings.py` (`settings_from_environment()`); `src/huron/service/api/authorization.py`;
`src/huron/service/api/__init__.py`; every module under `routes/v1/endpoints/` and
`routes/auth/endpoints/`; `Makefile:30`; `Containerfile` `CMD`;
`docs/getting-started/local-development.md:131`. Tests: `tests/unit/test_api_app.py`,
`tests/unit/test_api_authorization.py`, `tests/unit/test_repository_rbac.py` — the exact edits are
tabulated in Design 2's `### Explicit contracts` under *"Existing tests that must change"*.

**Delete.** Everything in Design 2's `### Deletions`, in full: `create_app`'s eager fallback block
and its four `app.state` assignments; the `settings or ApiSettings()` line and its `type: ignore`;
`app.state.database_pool` and `app.state.http_client`; `_configure_oidc`'s `app` parameter and its
six `app.state` writes; `readyz`'s `request.app.state.repository` read; the module-level
`app = create_app()`; `get_repository`, `get_settings` and the false docstring at
`authorization.py:85-88`; `_cookie_name` and `DEFAULT_SESSION_COOKIE_NAME`; the two
`request.state.binding_cache` create-if-missing blocks; three `__all__` entries; `app` from
`api/__init__.py` and its `__all__`; all **44** `request: Request` path-operation parameters; the
`del request` at `endpoints/rbac.py:43`; `oidc.py`'s `_oidc_client` helper; the test doubles
`_App`/`_State`, `_fake_request`, the two `_cookie_name` tests, and five `app.state.http_client` /
`app.state.database_pool` assertions.

**Explicitly not deleted** (Design 2 says so): `create_app`'s `repository=` and `oidc_verify=`
parameters, `_bootstrap`, `_postgres_repository`, both `RLock`s.

**Depends on.** M1.1 — this task edits the same signatures and must not change any `def`/`async def`
keyword M1 set. The five providers themselves are **`async def`**, per Design 1's constraint on
task 2; declaring them `def` is a defect, not a style choice.

**Verify.**

```text
uv run python -c "import huron.service.api as a; print(hasattr(a, 'app'))"
uv run python -c "from huron.service.api.app import create_app; create_app()" ; echo "expect TypeError above"
uv run python -c "from huron.service.api.main import app; print(type(app).__name__)"
grep -rn 'request: Request' src/huron/service/api/routes/ | wc -l
grep -rn 'request.app' src/huron/service/api/ | wc -l
grep -rn 'huron.service.api.app:app' Makefile Containerfile docs/ | wc -l
uv run pytest -m unit -q
uv run pytest -m contract -q
<full validation gate>
```

**Acceptance criteria.**

- `hasattr(huron.service.api, "app")` is `False`; importing the package builds no application.
- `create_app()` with no `settings=` raises `TypeError` at the call, not at request time.
- `from huron.service.api.main import app` yields a `FastAPI` instance; importing
  `huron.service.api.app` has no side effect.
- `grep -rn 'request: Request' src/huron/service/api/routes/` returns **zero** path-operation
  parameters; the only surviving `Request` uses in the tier are the three Design 2 enumerates and
  justifies (`login.py:64`, `session.py:19`, `authorization.py:225-280`).
- `grep -rn 'request.app' src/huron/service/api/` returns exactly **one** hit, inside `api_runtime`.
- `grep -rn 'get_repository\|get_settings' src/huron tests` returns nothing.
- `grep -rn 'huron.service.api.app:app' Makefile Containerfile docs/` returns **zero**; all three
  hand-maintained references name `huron.service.api.main:app`. (Matches under `site/` and `.cache/`
  are generated output and are not edited; they regenerate with `make docs`.)
- A test asserts that issuing a request against an app whose lifespan has not started produces a
  `500` and never a principal — the contract in Design 2's *"An application whose lifespan has not
  started serves no injected route"*.
- `uv run pytest -m unit` and `uv run pytest -m contract` both pass.
- `uv run mypy --strict src/huron/service/api/runtime.py src/huron/service/api/main.py` is clean when
  run by hand. The configured `files` list does not yet include the service tier (M10 widens it), so
  the gate will not catch a typing regression in these two new modules for you.
- Full validation gate clean.

**Status: pending**

---

## M3 — `repository.py` decomposition and the record relocation

Design: `API_DESIGN.md` → `## Design 3 — repository.py decomposition and query ownership`. Design 3
itself authorises this split — *"relocation first (mechanical, contract-preserving), query methods
second"* — and M3/M4 take it. The "contract-preserving" half is **M3.1 alone**: M3.2's field
deletion is wire-visible and is gated on D-16 (see §2).

### Task M3.1 — Split `repository.py` into `records` / `ports` / `memory_rbac` / `repository`

**Intent.** Fix the import direction so storage adapters no longer import the application-service
module, by moving the record dataclasses to a leaf with no project imports at all.

**Design reference.** `## Design 3` → `#### Module layout`,
`#### ResourceNotFound moves to huron.pkg.catalog.errors`, `#### The import lines that change`,
`#### records.py, in full at the parts that change`, and `### Explicit contracts` (import direction,
`RbacStore`/`ApiKeyWriter` conformance, `jsonable` semantics).

**Create.** `src/huron/service/api/records.py` (the nine dataclasses plus `jsonable()`, **no project
imports**), `src/huron/service/api/ports.py` (`RbacStore`, `ApiKeyWriter`),
`src/huron/service/api/memory_rbac.py` (`InMemoryRbacStore`).

**Modify.** `src/huron/service/api/repository.py` (retains `HierarchyRepository` and its private
helpers, imports the three new modules); `src/huron/pkg/catalog/errors.py` (add `ResourceNotFound`,
`code, status_code = "NOT_FOUND", 404`, and its `__all__` entry); `src/huron/service/api/postgres_rbac.py`
and `postgres_auth.py` (import lines only — **no SQL changes**); the five modules that imported
`common.jsonable`; `src/huron/service/api/routes/v1/common.py`;
`tests/unit/test_repository_rbac.py`; `tests/contract/test_rbac_store.py`.

**Delete.** `ResourceNotFound` from `repository.py:56-57`; `common.jsonable` (**`common.py:28-29`** —
delete by symbol, not by line: `common.py:31-32` is the blank line and `def expected_version(...)`,
which M6.1 must **keep** and moves verbatim to `preconditions.py`) with no re-export left behind; `repository.py`'s `# type: ignore[arg-type]` at `:845`, which is removed by
the move rather than carried; the public attribute name `rbac_store` (renamed `_rbac_store`; the
`rbac_store=` constructor keyword is unchanged).

**Depends on.** M2.1 — `runtime.py` imports `HierarchyRepository`, and this task moves what that name
refers to.

**Verify.**

```text
uv run python -c "import ast,sys; t=ast.parse(open('src/huron/service/api/records.py').read()); \
 print([n for n in ast.walk(t) if isinstance(n,(ast.Import,ast.ImportFrom)) and 'huron' in ast.dump(n)])"
grep -rn 'from huron.service.api' src/huron/service/api/postgres_auth.py
grep -rn 'import repository\|from .repository\|from huron.service.api.repository' src/huron/service/api/ src/huron/pkg/
uv run lint-imports
uv run pytest -m unit -q
uv run pytest -m contract -q
<full validation gate>
```

**Acceptance criteria.**

- The `ast` probe prints `[]`: `records.py` imports nothing from `huron`. This is the property the
  decomposition exists for — a leaf with no edges cannot be one end of a cycle.
- `postgres_auth.py` imports nothing from `huron.service.api` whatsoever (grep returns zero lines).
- `postgres_rbac.py` imports from `huron.service.api.records` and `huron.pkg.*` only.
- The only importers of `repository` in the tier are `app.py`, `runtime.py`, `authorization.py`
  (type-checking only) and the route modules — the invariant stated in `### Explicit contracts`.
- `git diff --stat -- src/huron/service/api/postgres_rbac.py src/huron/service/api/postgres_auth.py`
  shows changed import lines only; no SQL string is modified.
- `uv run pytest -m contract` passes. Protocol conformance for `PostgresRbacStore` and
  `PostgresApiKeyStore` is proven **only** by `tests/contract/`, which the gate's pytest line does not
  run; this task changes where those Protocols live, so the contract run is mandatory. It needs the
  container runtime named under §0's **Environment prerequisites**; if the host has none, stop and
  report rather than declaring this task done with the step unrun.
- `grep -rn 'jsonable' src/huron/service/api/routes/` finds imports from `records`, never from
  `common`, and `common.jsonable` no longer exists.
- Full validation gate clean.

**Status: pending**

### Task M3.2 — Delete the dead repository symbols — **GATED on D-16**

**Intent.** Remove the four dead symbols and the reader-with-no-writer pair the decomposition makes
visible, so the module states only what it can actually do.

**This task is not contract-preserving.** `Release.withdrawn_at` and `Release.withdrawn_reason` are
not persistence-only. `list_releases` and `resolve_release` both return their records through
`jsonable`, which is `asdict` over the dataclass, so deleting the two fields removes two documented
keys from `GET /api/v1/datasets/{id}/releases` and `GET /api/v1/datasets/{id}/releases/{tag}`.
Design 3's `### Deletions` names the deletion but records only its effect on the persisted release
tag document. D-16 is the register entry for the wire break, and M3.2 ships with the grouped
release, not ahead of it.

**Design reference.** `## Design 3` → `### Deletions` (including its *"Kept deliberately, with
reasons"* block, which is binding: `register_revision`, `RevisionSeed`, `self.revisions` and the
policy attachments are **not** deleted).

**Modify.** `src/huron/service/api/repository.py` (module docstring — the claim to "provide a local
API mode" goes with the function that was that mode); `src/huron/service/api/records.py`
(`Release` loses two fields).

**Delete.** `local_repository()`; `entity_ref()` and with it the `EntityRef` import;
`Release.withdrawn_at` and `Release.withdrawn_reason`, together with the `if item.withdrawn_at is not
None: raise TagWithdrawn(...)` branch in `resolve_release`.

**Depends on.** M3.1.

**Verify.**

```text
grep -rn 'local_repository\|entity_ref\|EntityRef\|withdrawn_at\|withdrawn_reason\|TagWithdrawn' src/ tests/ migrations/
uv run pytest -m unit -q
<full validation gate>
```

**Acceptance criteria.**

- The grep returns no hit in `src/huron/service`, `tests/` or `migrations/`. `TagWithdrawn` survives
  in `src/huron/pkg/catalog/errors.py` — the class is not the API tier's to delete — and M8 inherits
  the question of whether a code with no raiser keeps its table row.
- `pyscn check src/huron` reports no dead code in `repository.py`.
- The release tag document written by `_write_generation` no longer carries the two always-`null`
  keys; a unit test asserts the persisted document's key set.
- The two release **response bodies** lose the same two keys, and a unit test asserts the new key set
  of `GET /api/v1/datasets/{id}/releases` items and of `GET /api/v1/datasets/{id}/releases/{tag}`.
  This is the D-16 break: it is expected, it is pinned by a test, and any existing test that asserted
  the old key set is updated in this task rather than left to fail in a later one.
- `register_revision`, `RevisionSeed` and `self.revisions` still exist and are still reachable —
  a grep confirms they were not swept along.
- Full validation gate clean.

**Status: pending**

---

## M4 — Repository query methods, classification enforcement, release pinning

Design: `API_DESIGN.md` → `## Design 3`, second half.

### Task M4.1 — Move the four handler-side list queries into the repository

**Intent.** Give list logic one home, so a handler no longer filters process dicts and the future
persistent store has a signature to implement.

**Design reference.** `## Design 3` → `#### The four query methods`,
`#### HierarchyRepository's public surface`, `### Explicit contracts` (threading and snapshot
semantics — the query methods run on the event-loop thread and **must not** acquire `_lock`, and each
returns a `list(...)` copy), `### Open questions` question 1 (`limit`/`after` do **not** descend into
these signatures now).

**Modify.** `src/huron/service/api/repository.py` (four new synchronous query methods);
`routes/v1/endpoints/organizations.py`, `projects.py`, `datasets.py`.

**Delete.** The four dict comprehensions and their `sorted(...)` calls at `organizations.py:50-52`,
`projects.py:54-58`, `datasets.py:68-70`, `datasets.py:125-130` (the comprehension at `:125-129` and
the `sorted(...)` inside the return at `:130`), and the three redundant `repository.get_*(...)`
existence calls that precede them.

**M4.1 owns `list_releases`' response shape; M6.2 replaces it.** The `{"items": [...]}` envelope at
`datasets.py:130` is rebuilt here over the new query method, **not** deleted: this task's acceptance
criterion is that all four list responses stay byte-identical. M6.2 is the task that removes the
hand-built envelope, when `ReleaseView` and the paged envelope arrive together with D-6.

**Depends on.** M3.1, M3.2.

**Verify.**

```text
grep -rn 'for .* in .*\.values()\|sorted(' src/huron/service/api/routes/v1/endpoints/
uv run pytest -m unit -q
<full validation gate>
```

**Acceptance criteria.**

- No endpoint module iterates a repository dict; the grep finds no comprehension over `.values()` in
  `routes/v1/endpoints/`.
- Each of the four methods is `def`, not `async def` (Design 1's constraint on task 3), acquires no
  lock, and returns a new list.
- Unit tests cover each method directly: populated, empty, and the filtered-parent case where the
  parent exists but has no children — distinguished from the case where the parent does not exist,
  which still raises `ResourceNotFound`.
- A test asserts the ordering each method guarantees, since M6 keys a cursor on it: a query whose
  ordering disagrees with the cursor key silently drops items.
- Response bodies for the four list routes are byte-identical to before this task.
- Full validation gate clean.

**Status: pending**

### Task M4.2 — Enforce `classification_vocabulary`, and pin `create_release` — **GATED on D-14**

**Intent.** Close the gap where `data_classification` is accepted without being checked against the
configured vocabulary, and make the unreachable release route visible to the suite instead of silent.

**Design reference.** `## Design 3` → `#### classification_vocabulary is enforced in create_project`,
`### Open questions` question 2, and `### Explicit contracts` (*"`classification_vocabulary` is read
once at construction"*).

**Create.** A `ClassificationUnknown` `DomainError` subclass in `src/huron/pkg/catalog/errors.py`
with a stable code and status. Introduce it as a named subclass here rather than as a bare
`raise DomainError(...)`: M8's conversion table already assigns this refusal that name, and adding a
fifteenth bare raise for one milestone would be a partial migration. **Its `design/api.html` §7 row is
M8.3's, not this task's.**

**Modify.** `src/huron/service/api/repository.py` (`create_project`);
`tests/unit/` — a new or extended module that drives `create_release` end to end by calling
`register_revision(RevisionSeed(...))` directly.

**Depends on.** M4.1. **Do not start until D-14 is recorded.**

**Verify.**

```text
uv run pytest -m unit -q -k "classification or release"
<full validation gate>
```

**Acceptance criteria.**

- A project created with a classification outside the configured vocabulary is refused with
  `ClassificationUnknown`, and one inside it succeeds; both are unit-tested, including the boundary
  where the vocabulary is empty.
- A test drives `register_revision` and then `create_release`, and asserts a successful release —
  this is the pin that stops the route's unreachability from being invisible. A second test asserts
  that without a registered revision the route answers `404`, which is the behavior D-14 accepts.
- `ClassificationUnknown` subclasses `DomainError` and declares both `code` and `status_code`.
- Full validation gate clean.

**Status: pending**

---

## M5 — Router composition and the authenticated surface

Design: `API_DESIGN.md` → `## Design 4 — Router composition and the authenticated surface`.

### Task M5.1 — Rebuild the router tree and close the versioned surface — **one atomic task, GATED on D-3, D-4, D-5**

**Intent.** Declare prefix, tags and authentication once per router, so no `/api/v1` route can be
reached without a credential and no decorator repeats a path prefix.

**Design reference.** `## Design 4` → `#### The rule for where a guard is declared`,
`#### The multi-root prefix constraint, resolved`, `#### The router declarations`,
`#### The resulting surface — all 47 operations` (**the oracle for this task**),
`### Explicit contracts` (in particular *"What it cannot guarantee"* items 2 and 4, and the
bind-the-closure-once rule), `### Deletions`.

**Create.** `routes/v1/endpoints/search.py` (no schema module — no request body).

**Rename** (not delete — the contents move):
`routes/v1/endpoints/rbac.py` → `roles.py` + `bindings.py` + `service_accounts.py`;
`routes/v1/schema/rbac.py` → `schema/bindings.py` + `schema/service_accounts.py`;
`routes/v1/endpoints/auth.py` → `endpoints/api_keys.py`; `routes/v1/schema/auth.py` →
`schema/api_keys.py`.

**Modify.** `routes/v1/__init__.py` (the 18 `include_router` lines that *are* the v1 surface, and the
router-level `dependencies=[Depends(current_principal)]`); `routes/auth/__init__.py`;
`src/huron/service/api/app.py`; every endpoint module's `APIRouter(...)` construction and all 47
decorators; `src/huron/service/api/authorization.py`.

**Delete.** `@app.get("/api/v1/search")` and `search_unavailable` from `app.py`, with the
`ProjectionUnavailable` import narrowing out; the three-line comment at `app.py:189-191`; the
`prefix=` and `tags=` arguments on both `include_router` calls; all seven `tags=[...]` in
`routes/v1/__init__.py`; the **22** guard-only parameters enumerated in Design 4's `### Deletions`
(ten `_actor: CurrentPrincipal`, eleven `_actor: Annotated[Principal, Depends(require_*)]`, one
`_actor: _Actor`) — the sixteen value-reading `actor` parameters stay; `list_roles`'s remaining
parameter list, leaving it with no parameters at all; the full path prefix repeated on all 47
decorators.

**Depends on.** M2.1 (handlers declare Design 2's aliases, and no router may reintroduce
`get_repository(request)`), M3.1 (the renamed modules' import lines are rewritten against the new
`records`/`ports`/`memory_rbac` split), M4.1.

**Verify.**

```text
uv run python - <<'PY'
from huron.service.api.app import create_app
from huron.service.api.settings import ApiSettings
app = create_app(settings=ApiSettings(...))
for r in app.routes:
    print(getattr(r, "methods", None), getattr(r, "path", None), getattr(r, "tags", None))
PY
grep -rn '_actor' src/huron/service/api/routes/
grep -rn '"/api/v1' src/huron/service/api/app.py
grep -rn 'APIRouter(' src/huron/service/api/routes/v1/endpoints/
uv run pytest -m unit -q
<full validation gate>
```

**Acceptance criteria.**

- The printed route table matches `#### The resulting surface — all 47 operations` row for row:
  every path, method and tag. Any path that is not either byte-identical to today or one of the two
  decided contract changes is a defect.
- New tests pin both contract changes: anonymous `GET /api/v1/roles` returns
  `401 application/problem+json`, and anonymous `GET /api/v1/search` returns
  `401 application/problem+json` rather than `503`. An authenticated `GET /api/v1/search` still
  returns `503 PROJECTION_UNAVAILABLE`.
- A test pins that authentication is declared on the router and inherited two levels down: a route
  in a nested included router answers `401` anonymously with no per-operation dependency.
- `grep -rn '_actor' src/huron/service/api/routes/` returns nothing; no parameter in the tier begins
  with `_`.
- `app.py` contains no `/api/v1` path string.
- Every capability that appears both on a router and as a named parameter is bound to a single
  module-level closure — a test asserts the guard resolves once per request (a `require_*` factory
  called twice mints two closures and doubles the `decide()` calls).
- Twelve tags appear in the OpenAPI document and `auth` names exactly one surface.
- `tests/unit/test_api_rbac.py` passes **unedited**: Design 4 leaves the paths it drives
  byte-identical, so an edit there is evidence the restructure moved a live path.
- Full validation gate clean.

**Status: pending**

---

## M6 — Response models for the resource surface, and the pagination envelope

Design: `API_DESIGN.md` → `## Design 5 — Response models and the pagination envelope`. The envelope,
`PageLimit`/`PageCursor`, `paginate`, the `XView` naming rule and the `from_attributes` rule are
decided here and inherited unchanged by M7; M7 may not re-open any of them.

### Task M6.1 — The envelope, the precondition split, and the three paged hierarchy collections — **GATED on D-6**

**Intent.** Replace the untyped `page()`/`jsonable()` envelope with a declared generic and a keyset
cursor, and convert the three collections that used it.

**Design reference.** `## Design 5` → `#### Where response models live`, `#### The pagination
envelope`, `#### limit, after, and Design 3's Open question 1`, `#### The rule for which collections
get an envelope`, `#### The hierarchy views`, `### Explicit contracts` (`Page.next_cursor` semantics,
`from_attributes` rule, what every hierarchy view omits and why), `### Deletions`.

**Create.** `src/huron/service/api/routes/v1/pagination.py` (`Page`, `PageLimit`, `PageCursor`,
`paginate`, `encode_cursor`, `decode_cursor`); `src/huron/service/api/routes/v1/preconditions.py`
(`IdempotencyHeader`, `IfMatchHeader`, `expected_version`, moved verbatim);
`OrganizationView`, `ProjectView`, `DatasetView` in their existing schema modules.

**Modify.** `src/huron/pkg/catalog/errors.py` (add `InvalidCursor`, beside the `ResourceNotFound` M3
moved there); `routes/v1/endpoints/organizations.py`, `projects.py`, `datasets.py`; the import line
in **every** module that imported `common` — including the administrative modules M7 has not reached
yet, which repoint to `preconditions` and otherwise keep their current return types.

**Delete.** `src/huron/service/api/routes/v1/common.py` — **the module**, not just its symbols.
`page()` is deleted outright rather than moved; the `count` field goes with it; the silent
`max(1, min(limit, 200))` clamp is replaced by `Annotated[int, Query(ge=1, le=200)]`.

**Depends on.** M5.1 (each route's owning module is fixed), M4.1 (the query methods supply the
ordered sequences and the cursor keys).

**Verify.**

```text
test ! -f src/huron/service/api/routes/v1/common.py && echo "common.py gone"
grep -rn 'from .*common import\|common\.page\|common\.jsonable' src/huron tests
uv run pytest -m unit -q
<full validation gate>
```

**Acceptance criteria.**

- `routes/v1/common.py` does not exist and nothing imports it.
- `Page` is generic; `Page[OrganizationView]` appears in the OpenAPI schema as a distinct component.
- `?limit=0`, `?limit=201` and `?limit=-3` each answer **`422`** on all three collections — the
  contract change D-6 covers — and a malformed `after` answers `422` as well. Tests pin all four.
- A cursor-walk test at `limit=1` over a populated collection yields every item exactly once in key
  order and terminates with `next_cursor: null`. This is the contract stated as *"a caller that
  follows cursors until `null` sees every item exactly once"*.
- No response body contains `count`, and none contains `generation` — a test asserts the exact key
  set of an `OrganizationView`, so a record growing a field cannot leak it.
- `from_attributes=True` appears on the three `*View` models and on `Page` it does **not**; a test
  asserts `Page.model_validate(some_record)` fails.
- No handler in the three modules returns `dict[str, object]`.
- Full validation gate clean.

**Status: pending**

### Task M6.2 — Views for the remaining hierarchy operations

**Intent.** Give every remaining resource-surface operation a declared response type.

**Design reference.** `## Design 5` → `#### The hierarchy views`, `#### The handlers`,
`#### The 26 operations this section covers`, `### Deletions` (the `datasets.py` accumulator and the
hand-built release envelope), `### Open questions` question 4 (`ReleaseView` on a route that cannot
yet succeed is deliberate).

**Create.** `ReleaseView`, `LayerView`, `WriteIntent` and any remaining single-record views, in the
schema module of their owning endpoint module.

**Modify.** `routes/v1/endpoints/datasets.py`, and the release and layer operations.

**Delete.** `datasets.py:139-160`'s `items: list[dict[str, object]]` accumulator and its
`allowed: dict[str, bool]` keyed by `LayerAction.value`, replaced by the `may` closure and the
`LayerView` comprehension; `list_releases`' hand-built `{"items": [...]}` release envelope
(`datasets.py:130` on the pre-M4.1 tree — `:117-128` is the decorator, signature and existence call,
not the envelope — which M4.1 rebuilds over the repository query and this task replaces);
every remaining `-> dict[str, object]` / `-> dict[str, str]` annotation in the resource surface
except the two probes.

**Depends on.** M6.1.

**Verify.**

```text
grep -rn -- '-> dict\[str, ' src/huron/service/api/routes/v1/endpoints/
uv run pytest -m unit -q
<full validation gate>
```

**Acceptance criteria.**

- No `-> dict[...]` annotation remains in `routes/v1/endpoints/organizations.py`, `projects.py`,
  `datasets.py`, or the release/layer operations.
- `LayerView` is returned for every layer, and a test asserts the per-layer permission flags for a
  principal that may write one layer and not another.
- `version` appears on every versioned view and is the `If-Match` token; no `ETag` header is emitted
  by any route (a test asserts its absence, since the design deliberately declines it).
- A replayed `POST` with the same `Idempotency-Key` returns the same status and the same body, and
  no response carries a replay indicator.
- Full validation gate clean.

**Status: pending**

### Task M6.3 — The unversioned surface, and `effective_roles` — **GATED on D-8**

**Intent.** Model the unversioned responses and close Drift 8 by shipping effective roles per scope
on `GET /auth/session`.

**Design reference.** `## Design 5` → `#### The unversioned surface, and Drift 8`,
`#### Secret-bearing responses`, `### Open questions` question 1.

**Create.** `ScopeRoles`; `LoginResult` and any remaining unversioned response models, in
`routes/auth/schema/`.

**Modify.** `routes/auth/schema/session.py` (`SessionInfo` gains
`effective_roles: list[ScopeRoles]`); `routes/auth/endpoints/session.py`, `login.py`, `oidc.py`.

**Depends on.** M6.1 (the naming and `from_attributes` rules). **Do not start until D-8 is recorded.**

**Verify.**

```text
uv run pytest tests/unit/test_api_login.py tests/unit/test_api_oidc.py -m unit -q
<full validation gate>
```

**Acceptance criteria.**

- `GET /auth/session` returns `effective_roles`, resolved from the same binding set the guard chain
  consults. Tests cover: a `platform_owner` (one SYSTEM entry), a principal with bindings at two
  scopes (two entries, deterministically ordered), and an unbound principal (empty list).
- No unversioned response model carries `from_attributes`, and none can be filled from a record.
- Full validation gate clean.

**Status: pending**

---

## M7 — Response models for the administrative surface

Design: `API_DESIGN.md` → `## Design 5b — Response models for the administrative surface`, and
`## Design 5` → `### The split — brief for Design 5b`, which fixes what 5b inherits and may not
re-open.

### Task M7.1 — `roles` and `bindings` — **GATED on D-6, D-7, D-9**

**Intent.** Replace the hand-assembled role catalog and the two hand-built binding envelopes with
declared models.

**Design reference.** `## Design 5b` → `#### The 21 operations`, `#### Decision 1 — the ordering of
the three administrative collections`, `#### GET /api/v1/roles — a fixed enumeration, and not a
projection`, `#### Decision 2 — RoleBindingView and the UUID | None that task 7 must narrow`,
`### Explicit contracts`, `### Deletions`.

**Create.** `RoleView`, `LayerGrantView` in `schema/roles.py`-equivalent placement per Design 4's
layout; `RoleBindingView` in `schema/bindings.py`.

**Modify.** `routes/v1/endpoints/roles.py`, `routes/v1/endpoints/bindings.py`.

**Delete.** The hand-assembled `{"items": [...]}` role catalog of nested dicts
(`endpoints/rbac.py:44-63` before M5's split); the two `{"items": [jsonable(item) …]}` binding
envelopes (`:150`, `:160`); the `jsonable(record)` returns in those handlers; every
`-> dict[str, object]` annotation in the two modules.

**Depends on.** M6.1 (envelope), M5.1 (module split). **`RoleBindingView`'s treatment of
`scope_id: UUID | None` must match M9's narrowing** — Design 5b's Decision 2 says 5b follows task 7
rather than publishing a third shape. Read Design 7's `### Explicit contracts` before writing the
model; it is specified there and needs no new decision.

**Verify.**

```text
uv run pytest -m unit -q -k "roles or binding"
<full validation gate>
```

**Acceptance criteria.**

- `GET /api/v1/roles` returns a bare JSON array — no `items` wrapper, no envelope, no `limit` —
  containing every role in declaration order, with every nested collection field sorted ascending
  and `layer_grants` in `RoleDefinition`'s tuple order. A test asserts the array is a pure function
  of `ROLES`.
- The two binding collections return `Page[RoleBindingView]` sorted **in the handler**, not by the
  store's `ORDER BY`, and keyed on the same callable passed to `paginate`. A test asserts the
  ordering holds for the in-memory store; the contract suite continues to prove both backends.
- `RoleBindingView.scope_id` is `null` if and only if `scope_type` is `SYSTEM` — pinned by a test.
- `?limit=5000` answers `422` on both collections.
- Full validation gate clean.

**Status: pending**

### Task M7.2 — `service_accounts` and `api_keys`, and the two secret-bearing responses — **GATED on D-6**

**Intent.** Model the service-account surface and make the show-once rule for minted secrets
structural rather than conventional.

**Design reference.** `## Design 5b` → `#### Service accounts, and the two issued keys`,
`### Explicit contracts` (*"`IssuedApiKey` and `IssuedServiceAccountKey` are constructed field by
field"*, and the two deliberate omissions), `## Design 5` → `#### Secret-bearing responses`
(which defines both models; 5b writes the handlers, not the models).

**Create.** `ServiceAccountView` in `schema/service_accounts.py`; `IssuedApiKey` and
`IssuedServiceAccountKey` exactly as Design 5 writes them.

**Modify.** `routes/v1/endpoints/service_accounts.py`, `routes/v1/endpoints/api_keys.py`.

**Delete.** `issue_service_account_key`'s hand-built dict; the service-account collection's
`{"items": …}` envelope; `issue_api_key`'s hand-built dict; the remaining `jsonable(record)` returns
and `-> dict[str, object]` annotations in both modules.

**Depends on.** M7.1.

**Verify.**

```text
uv run pytest -m unit -q -k "service_account or api_key"
<full validation gate>
```

**Acceptance criteria.**

- Neither secret model declares `from_attributes`; a test asserts
  `IssuedServiceAccountKey.model_validate(<any dataclass instance>)` raises, and that the error is a
  model-type failure rather than a missing-field complaint.
- `secret` appears in exactly two response models and nowhere else in the OpenAPI document; a test
  asserts no other schema declares a `secret` or `secret_sha256` field.
- `GET .../service-accounts` returns `Page[ServiceAccountView]` keyed on `(name,)` — the column both
  stores order by and the one the uniqueness constraint covers — with the ordering established in
  the handler.
- `expires_at` on the issued-key response is a declared field with a declared type, not a raw
  `datetime` in an untyped dict.
- Full validation gate clean.

**Status: pending**

### Task M7.3 — `policies` and `users` — **GATED on D-6, D-10**

**Intent.** Model the last two administrative modules, and stop `GET /users` publishing
`idp_subject`.

**Design reference.** `## Design 5b` → `#### Decision 3 — PolicyView.spec is returned everywhere
PolicyView is`, `#### Users, and the second over-published field`, `#### The handlers`,
`### Deletions`, `### Open questions` question 2 (the `spec` size bound).

**Create.** `PolicyView`, `PolicyAttachmentView`, `UserView`, `PasswordReset` in their schema modules.

**Modify.** `routes/v1/endpoints/policies.py`, `routes/v1/endpoints/users.py`.

**Delete.** `GET /policies`'s `{"items": [...]}` envelope; four `jsonable(...)` returns in
`policies.py`; the `_actor: CurrentPrincipal` parameter at `policies.py:40` if M5 has not already
removed it; two `jsonable(principal)` returns in `users.py`; the `{"status": "password-reset"}` dict
literal; the eight remaining `-> dict[...]` annotations across both modules.

**Depends on.** M7.2. If D-10 supplied a byte ceiling, it is applied to `CreatePolicy.spec` here —
the only request-body change either half of task 5 makes. If D-10 answered "no bound", ship none and
add no comment about it.

**Verify.**

```text
grep -rn 'idp_subject' src/huron/service/api/routes/
grep -rn -- '-> dict\[str, ' src/huron/service/api/routes/
uv run pytest -m unit -q
<full validation gate>
```

**Acceptance criteria.**

- `UserView` declares exactly `id`, `subject`, `display_name`, `disabled_at`, `created_at` and omits
  `idp_subject` and `kind`; a test asserts the exact key set of a user response, and `idp_subject`
  appears nowhere under `routes/`.
- `PrincipalRecord.idp_subject` still exists in `pkg` — the OIDC login path writes it and
  `postgres_auth` reads it. Nothing in `pkg` is deleted by this task.
- `GET /policies` returns `Page[PolicyView]` keyed on `(name, id)`; `PolicyView.spec` stays
  `dict[str, object]`.
- `PUT /users/{id}/password` returns a `PasswordReset` model with a `Literal`, matching `SignOut`.
- **After this task, `grep -rn -- '-> dict\[str, ' src/huron/service/api/routes/` returns nothing at
  all** — the only two surviving `-> dict[str, str]` handlers in the tier are `/healthz` and
  `/readyz`, which live in `app.py` — and no route in the tier imports `jsonable` — the precondition for
  `records.jsonable`'s docstring becoming persistence-only. Update that docstring here if M6 has not.
- Full validation gate clean.

**Status: pending**

---

## M8 — Error contract and `problem+json` coverage

Design: `API_DESIGN.md` → `## Design 6 — Error contract and problem+json coverage`.

### Task M8.1 — `DomainError` becomes abstract, and the fourteen bare raises get names — **atomic, GATED on D-11**

**Intent.** Retire `DOMAIN_ERROR` as a wire code by making the base class unraisable, so "every error
has a code" is mechanical rather than aspirational.

**Design reference.** `## Design 6` → `#### The rule`, `#### New module:
src/huron/service/api/errors.py`, `#### DomainError becomes abstract, and DOMAIN_ERROR stops being a
wire code`, `#### New module: src/huron/service/api/problems.py`, `#### The full code table, after
reconciliation`, `#### The reconciliation, both directions`, `### Explicit contracts`,
`### Deletions` (including the fourteen-site conversion table, which is the work list).

**This task supersedes Design 6's `### Deletions` line numbers for
`src/huron/pkg/catalog/errors.py`. Delete by symbol, never by line.** Four of that block's citations
for this one file are stale, and two of them point at **live** error codes:

| Design 6 says | Actual, on this tree | What is at the design's lines |
|---|---|---|
| `class ApiKeyExpired` **:130-131** | **:138-139** | `:130-131` is `class ClassificationExceeded` — code `CLASSIFICATION_EXCEEDED`, 403, **live, keep** |
| `class ApiKeyRevoked` **:134-135** | **:142-143** | `:134-135` is `class ProductStaleInput` — code `PRODUCT_STALE_INPUT`, 409, **live, keep** |
| `_DOMAIN_ERROR_TYPES` **:143-176** | **:162-195** | `:143` is `ApiKeyRevoked`'s `code, status_code` line |
| `DomainError.code` / `.status_code` **:15-16** | **:14-15** | off by one; harmless, the symbols are unambiguous |

`all_domain_error_types()` (**:219-222**) and `error_codes()` (**:224-225**) are cited correctly.
An implementer who deletes the design's ranges verbatim removes `ClassificationExceeded` and
`ProductStaleInput` — two live codes with reserved rows in the §7 table, neither a duplicate of
anything in `pkg/auth` — and the failure surfaces three tasks later as M8.3's bijection test
reporting table rows with no class. The two classes this task deletes are named
`ApiKeyExpired` and `ApiKeyRevoked` and no others; confirm with
`grep -n '^class ' src/huron/pkg/catalog/errors.py` before editing.

**Create.** `src/huron/service/api/errors.py` (the service tier's own stable errors; imports
`huron.pkg.catalog.errors` and **nothing else**, so `records.py` and `repository.py` may import it
without acquiring FastAPI); `src/huron/service/api/problems.py` (`Problem`, `problem()`, the six
handlers, `install_error_handlers`, `wire_error_codes()`, the `responses` builders and the walker —
this is the only new module that imports `fastapi`/`starlette`).

**Modify.** `src/huron/pkg/catalog/errors.py` (`DomainError` gains unvalued `ClassVar` annotations
and a `TypeError` in `__init__`; `SessionExpired` → `IngestSessionExpired` with code
`INGEST_SESSION_EXPIRED`, and its two raise sites in `pkg/catalog/ingest.py`);
`src/huron/pkg/rbac/roles.py`; `src/huron/service/api/app.py`;
`src/huron/service/api/authorization.py`; `src/huron/service/api/repository.py`;
`src/huron/service/api/postgres_rbac.py` (raise sites only — no SQL);
`routes/v1/endpoints/users.py`; `routes/auth/endpoints/oidc.py`; `pyproject.toml` (the `N818`
per-file ignore moves to `errors.py`; the `authorization.py` and `repository.py` entries go).

**Delete.** `DomainError`'s `code`/`status_code` defaults; the duplicate `ApiKeyExpired` and
`ApiKeyRevoked` classes and their `_DOMAIN_ERROR_TYPES`/`__all__` entries; `_DOMAIN_ERROR_TYPES`,
`all_domain_error_types()` and `error_codes()`; `RoleError.code = "ROLE_VIOLATION"`; the three inline
`@app.exception_handler` bodies and the `JSONResponse` import; `Forbidden` from `authorization.py`
and its `__all__` entry (it moves to `errors.py`, and its four raise sites re-import); the tier's
only `HTTPException` import and raise in `oidc.py`.

**Why this cannot split.** Removing the base class's defaults makes all fourteen bare raise sites
fail at once, in `repository.py`, `postgres_rbac.py`, `endpoints/users.py` and `app.py`
simultaneously. There is no ordering in which the tree is green between the first and the last.

**Depends on.** M7.3 (this task annotates and constrains the models M6/M7 defined; Design 6's
ownership note is explicit that task 5 goes first and task 6 annotates), M4.2 (which already
introduced `ClassificationUnknown`, so it is not a fifteenth site).

**Verify.**

```text
uv run python -c "from huron.pkg.catalog.errors import DomainError; DomainError('x')" ; echo "expect TypeError"
grep -rn 'raise DomainError(' src/huron
grep -rn 'HTTPException' src/huron
grep -rn 'DOMAIN_ERROR\|ROLE_VIOLATION' src/huron
grep -n 'CLASSIFICATION_EXCEEDED\|PRODUCT_STALE_INPUT' src/huron/pkg/catalog/errors.py
uv run pytest -m unit -q
uv run pytest -m contract -q
<full validation gate>
```

**Acceptance criteria.**

- `DomainError("x")` raises `TypeError`.
- `grep -rn 'raise DomainError(' src/huron` returns nothing. Each of the fourteen sites raises the
  named subclass from Design 6's conversion table, **except** `repository.py`'s two `_require_scope`
  raises, which become `ValueError` — a condition no request can reach is a bug, not a client
  contract, and its honest answer is the 500 the `Exception` handler produces.
- `HTTPException` appears nowhere in `src/huron`.
- `DOMAIN_ERROR` and `ROLE_VIOLATION` appear nowhere in `src/huron`.
- `ClassificationExceeded` and `ProductStaleInput` still exist and still hold
  `CLASSIFICATION_EXCEEDED` and `PRODUCT_STALE_INPUT`. They are neighbours of the two classes this
  task deletes and are the classes Design 6's stale line ranges point at; deleting either is the
  failure mode this criterion exists to catch.
- `uv run lint-imports` passes: `problems.py` is the only new module importing `fastapi`/`starlette`,
  and **no import is added to any `pkg` module** — `huron/pkg/catalog/errors.py`'s change is
  subtractive plus a `typing.ClassVar` already imported there.
- A duplicate organization slug now answers `400` with code `SLUG_EXISTS` (or the table's name), not
  `DOMAIN_ERROR`; a test pins it.
- `uv run pytest -m contract` passes — the `pkg` error classes are shared with the contract suites.
  It needs the container runtime named under §0's **Environment prerequisites**.
- Full validation gate clean.

**Status: pending**

### Task M8.2 — `/readyz` probes its real dependencies

**Intent.** Make the readiness probe report the dependencies this instance needs, and return the
status an orchestrator acts on.

**Design reference.** `## Design 6` → `#### create_app and /readyz`, `### Explicit contracts` (the
per-class table row for `DomainError`), and Design 2's `### Open questions` question 2, which names
this as the change that adds `database_pool` to `ApiRuntime`.

**Modify.** `src/huron/service/api/app.py` (`readyz`, `_dependency_checks`, `_raw_store_failure`,
`_database_failure`); `src/huron/service/api/runtime.py` (`ApiRuntime` gains
`database_pool: asyncpg.Pool | None`, assigned from the lifespan local — the seam Design 2 named);
`src/huron/service/api/errors.py` (`DependencyUnavailable`).

**Delete.** The old `/readyz` body, including the bare `raise DomainError("raw root is unavailable")`
that answered `400` to a readiness probe.

**Depends on.** M8.1.

**Verify.**

```text
uv run pytest tests/unit/test_api_app.py -m unit -q
<full validation gate>
```

**Acceptance criteria.**

- With the raw-store root present and no pool configured, `/readyz` returns `200 {"status":"ready"}`.
- With the raw-store root missing, `/readyz` returns **`503 application/problem+json`** with code
  `DEPENDENCY_UNAVAILABLE` and a `context.checks` mapping naming the failed dependency — never a
  `4xx`. Both branches are tested, and so is the two-dependency case where the pool is configured and
  answers.
- The raw-store stat runs off the event loop (Design 1 owns that; this task preserves it).
- Full validation gate clean.

**Status: pending**

### Task M8.3 — The `design/api.html` §7 table and the bijection test — **GATED on D-11**

**Intent.** Make the error contract mechanically checkable in both directions, so a code added to
either side without the other fails CI.

**Design reference.** `## Design 6` → `#### The bijection test`, `#### The full code table, after
reconciliation`, `#### The reconciliation, both directions`, and the *"Documentation edits handed to
Phase 5"* list — **edit 1 only** is this task's; edits 2–6 are not.

**Create.** `tests/unit/test_error_contract.py`, marked `unit`, with the four assertions the design
specifies: bijection, status parity, uniform shape across all six handlers, and `DomainError("x")`
raising `TypeError`.

**Modify.** `design/api.html` §7: replace the code `<pre>` block with `<table id="error-codes">`,
four columns (code, HTTP status, live/reserved, meaning), populated exactly as
`#### The full code table, after reconciliation` tabulates it. **The `id` is load-bearing — the test
parses it.** Rewrite §7's note per the design's replacement text.

**Scope note.** This is the single documentation edit in scope for this plan (section 1). The other
five `design/api.html` edits Design 6 hands over — the `/readyz` sentence, the `If-Match ETags`
preamble phrase, and the rest — belong to the roadmap-reconciliation phase and are **not** made here.

**Depends on.** M8.1, M8.2.

**Verify.**

```text
uv run pytest tests/unit/test_error_contract.py -m unit -q
grep -c 'id="error-codes"' design/api.html
<full validation gate>
```

**Acceptance criteria.**

- `design/api.html` contains exactly one `<table id="error-codes">`.
- The test's bijection assertion passes and, when deliberately broken in either direction (a class
  with no row, a row with no class), names the offending codes. The implementer demonstrates this by
  temporarily adding a throwaway subclass, observing the failure message, and reverting — the
  demonstration is reported, not committed.
- Status parity holds: every `AuthError` descendant's row says 401, every `RoleError` descendant's
  says 422, and every `DomainError` subclass's row matches its `status_code`.
- The uniform-shape assertion provokes one response from each of the six handlers — including an
  unrouted path and a validation failure — and each is `application/problem+json` with the five
  required keys and a `code` in `wire_error_codes()`.
- `make docs` still builds (`uv run --group docs zensical build --strict`), since §7's markup changed.
- Full validation gate clean.

**Status: pending**

### Task M8.4 — `responses={}` declarations on the routers

**Intent.** Put the documented error codes into the OpenAPI document where the contract says they
are, declared once per router rather than on 47 decorators.

**Design reference.** `## Design 6` → `#### responses={} declarations`, `### Explicit contracts`
(*"What a future author does to add an error"*, step 3).

**Modify.** `routes/v1/__init__.py`, `routes/auth/__init__.py`, the endpoint modules' router
constructions, and the individual operations whose error set exceeds the router's shared set.

**Depends on.** M8.3, and M6/M7 for the 2xx models the entries sit beside.

**Verify.**

```text
uv run python -c "from huron.service.api.main import app; import json; \
 d=app.openapi(); print(sorted(d['components']['schemas']))"
uv run pytest -m unit -q
<full validation gate>
```

**Acceptance criteria.**

- `Problem` appears once in `components.schemas`, and every declared error response `$ref`s it.
- A router-level `responses=` entry is inherited by every operation beneath it through two levels of
  `include_router`, and a per-operation entry **adds to** rather than replaces the inherited set — a
  test asserts both against the generated document.
- No operation declares an error status the router already declares.
- Full validation gate clean.

**Status: pending**

---

## M9 — Binding surface completion

Design: `API_DESIGN.md` → `## Design 7 — Binding surface completion`.

### Task M9.1 — Scope-rooted revoke, and the end of the `type: ignore` cluster — **GATED on D-12**

**Intent.** Replace the flat any-scope revoke with four scope-rooted handlers whose narrowing the
type system accepts.

**Design reference.** `## Design 7` → `#### Target design`, `### Explicit contracts` (*"Guards, one
per root"*, *"DELETE semantics"*, *"The invariant that makes the type: ignores unnecessary"*, and
*"What the delete path must pin"*), `### Deletions`.

**Modify.** `routes/v1/endpoints/bindings.py`; `tests/unit/test_api_rbac.py` or a new module for the
delete-path contract.

**Delete.** `revoke_binding` — the flat handler — with its `ScopeType` dispatch, its `Scope.system()`
branch and its in-handler `await check(...)`; the three `# type: ignore[arg-type]` comments; the
imports that handler alone required (`Scope`, `check`, `organization_scope`, `project_scope`,
`dataset_scope`, `CurrentPrincipal`). `authorization.check` and the three `*_scope` helpers **stay** —
the `require_*` factories are their callers and a test imports `check` directly.

**Depends on.** M8.4 (all six prior decisions must be in place), M7.1 (`RoleBindingView`).

**Verify.**

```text
grep -rn 'type: ignore' src/huron/service
grep -rn 'await check(' src/huron/service/api/routes/
uv run pytest -m unit -q -k binding
<full validation gate>
```

**Acceptance criteria — the delete path is pinned by tests, not by a count.** Every bullet of Design
7's *"What the delete path must pin"* becomes an assertion:

- `204` with an empty body on a successful revoke **at each of the four roots**, and the binding
  absent from that root's `GET` afterwards.
- The revoked capability stops working: the principal gets `403` on a route it could reach one
  request earlier — this is what proves revocation reaches `bindings_for` and the per-request cache.
- `404` — not `204`, not `403` — when a binding id from one scope is named at another root; at
  minimum an organization binding named under `/bindings`, and a dataset binding named under an
  organization root.
- `404` for an unknown `binding_id` and for a repeated `DELETE`.
- `403` for a caller without `rbac.binding_manage` at that root, and `404` **before** `403` when the
  path scope itself does not exist.
- `grep -rn 'type: ignore' src/huron/service` no longer shows `rbac.py`/`bindings.py`; the tier's
  budget is down to the one in `settings_from_environment`.
- `check` is invoked only from inside `authorization.py`'s guard factories and `dataset_layer_writer`
  — the grep over `routes/` returns nothing.
- Full validation gate clean.

**Status: pending**

### Task M9.2 — The two missing binding collections — **GATED on D-13**

**Intent.** Close Drift 4 by adding the two absent collections, so all four scope roots are
symmetrical.

**Design reference.** `## Design 7` → `#### Target design`, `### Explicit contracts` (scope
inheritance, the platform-owner roster, ordering and cursor key).

**Create.** `GET /api/v1/bindings` (SYSTEM) and `GET /api/v1/datasets/{dataset_id}/bindings`, in
`routes/v1/endpoints/bindings.py`.

**Modify.** `routes/v1/endpoints/bindings.py` only. **No store method, no Protocol method and no
migration** — `bindings_at` and `get_role_binding` exist on both backends.

**Depends on.** M9.1.

**Verify.**

```text
uv run pytest -m unit -q -k binding
uv run pytest -m contract -q
<full validation gate>
```

**Acceptance criteria.**

- `GET /api/v1/bindings` returns `200` for the bootstrap `platform_owner`, `403` for an
  `organization_admin`, and `403` for an unbound authenticated caller.
- `GET /api/v1/datasets/{id}/bindings` returns `200` for a `project_admin` bound at the parent
  project and for an `organization_admin` bound at the grandparent organization, and `403` for a
  `reader` bound at that dataset — inheritance is the property being pinned.
- Both collections sort in the handler on `(principal, role_code)` and pass that same callable to
  `paginate`; a cursor walk at `limit=1` yields every binding exactly once and ends with
  `next_cursor: null`.
- Expired bindings are present in the results, and a test asserts it with `expires_at` in the past —
  making explicit that "the bindings at this scope" is deliberately not "the grants in force at this
  scope".
- No new error code is introduced; `ResourceNotFound` and `Forbidden` are the only errors raised.
- Full validation gate clean.

**Status: pending**

---

## M10 — Type-check scope, entrypoint rationale, Ruff `FAST`

Design: `API_DESIGN.md` → `## Design 8 — Entrypoint, ORM, frontend serving, and type-check scope`.
Landed last on purpose: widening the type gate and enabling new lint rules against code that M2–M9
rewrite would mean fixing the same errors twice.

### Task M10.1 — `src/huron/service` joins `mypy --strict` and `ty` — **GATED on D-15**

**Intent.** Remove the last un-checked surface, so `type: ignore` comments in this tier become live
assertions rather than unread comments.

**Design reference.** `## Design 8` → `#### 4. Type-check scope — src/huron/service joins both
gates, now`, `### Explicit contracts` (the `asyncpg` override), `### Deletions`,
`### Open questions` question 2.

**Modify.** `pyproject.toml` — `[tool.mypy].files` and `[tool.ty.src].include` become
`["src/huron"]`, plus the scoped override that makes `asyncpg` the one permitted untyped import.
Whatever type errors the widened scope surfaces, in the modules that carry them.

**Delete.** The three-line comment above `[tool.mypy].files` and the three-line comment inside
`[tool.ty.src]`; both assert a carve-out this task closes.

**Depends on.** M9.2 — every module this widens over has reached its final shape.

**Verify.**

```text
uv run mypy
uv run ty check
grep -rn 'ignore_missing_imports' pyproject.toml
<full validation gate>
```

**Acceptance criteria.**

- `uv run mypy` and `uv run ty check` both report zero errors with `files`/`include` set to
  `["src/huron"]`.
- No suppression was added to get there: `grep -rn 'type: ignore' src/huron` returns exactly **one**
  hit, the `call-arg` inside `settings_from_environment`. Any other ignore is either removed or is a
  finding to report.
- The `asyncpg` allowance is scoped by module pattern; there is no top-level
  `ignore_missing_imports`.
- `sqlmodel` appears nowhere; `sqlalchemy>=2` and `uvicorn[standard]` are still declared, and no
  dependency was removed.
- Full validation gate clean.

**Status: pending**

### Task M10.2 — Enable the Ruff `FAST` rules

**Intent.** Let the linter carry the FastAPI conventions the tier now follows.

**Design reference.** `## Design 8` → `#### 5. Ruff FAST rules — enable`. Design 1's Open question 3
is settled by this task and needs no separate decision: no `FAST` rule checks sync-vs-async body
content, so the execution-model disposition stays pinned by its docstring sentence, not by a lint.

**Modify.** `pyproject.toml` (`[tool.ruff.lint].select`), and whatever the new rules flag.

**Depends on.** M10.1.

**Verify.**

```text
uv run ruff check .
uv run ruff format --check .
<full validation gate>
```

**Acceptance criteria.**

- `FAST` is in `select` and `uv run ruff check .` reports zero diagnostics with no new per-file
  ignore and no `# noqa`.
- Full validation gate clean.

**Status: pending**

### Task M10.3 — Record the three deviations as decisions

**Intent.** Leave the entrypoint, ORM and frontend choices stated with their reasons, so no later
reader re-opens them as oversights.

**Design reference.** `## Design 8` → `#### 1. Entrypoint`, `#### 2. ORM`, `#### 3. Frontend`,
`### Explicit contracts`, `### Deletions`.

**Modify.** `Containerfile` (replace the header comment at `:1-5` with the version Design 8 writes;
the claim "always runs plain uvicorn" survives, the missing reason is supplied).

**Delete.** Nothing beyond the comment being replaced. Design 8's `### Deletions` states explicitly
that no dependency, symbol, module or route is deleted by this design.

**Depends on.** M2.1 (which already corrected the three entrypoint strings), M10.2.

**Verify.**

```text
grep -rn 'huron.service.api.main:app' Makefile Containerfile docs/
grep -rn 'fastapi-cli\|tool.fastapi\|sqlmodel' pyproject.toml
uv run --group docs zensical build --strict
<full validation gate>
```

**Acceptance criteria.**

- All three hand-maintained references name `huron.service.api.main:app`.
- Neither `fastapi-cli`, a `[tool.fastapi]` table, nor `sqlmodel` exists anywhere.
- No FastAPI route serves a static asset or HTML; `app.frontend()` appears nowhere.
- `make docs` builds `--strict`.
- Full validation gate clean.

**Status: pending**

---

## 4. Risk register

The five changes most likely to end in escalation, each with the symptom that says it is going wrong
and the point at which the decision stops being the implementer's.

### R1 — M2.1 is a ~55-file atomic change with no green intermediate state

**Symptom.** Verification attempt 1 returns a long fix list that is mostly the same error repeated —
a route still declaring `Request`, a test still building `_App`, a `getattr(app.state, …)` survivor.
Attempt 2 fixes half. Attempt 3 finds a new one.

**Why it happens.** The task deletes both providers and requires all 44 call sites plus eight test
modules to move in the same pass; a subagent that works module-by-module runs out of budget before
the tree compiles again, and reports partial success.

**Fallback decision point.** If verification 2 still shows unconverted call sites rather than
genuine defects, the task is too large for one subagent, not wrong. **Do not** reintroduce
`get_repository`/`get_settings` as a bridge — that is the shim rule 2 forbids and it makes the third
attempt worse. Escalate to `/architectural-review` with the specific question: *can Design 2's
provider replacement be staged by route tree — `routes/auth/` first, `routes/v1/` second — without a
compatibility path, given that `create_app`'s signature change is what forces both?*

### R2 — M5.1 moves every path in the tier at once

**Symptom.** A test that Design 4 predicted would pass unedited (`tests/unit/test_api_rbac.py`) fails
with a `404`, or the route-table probe prints a path with a doubled or missing segment.

**Why it happens.** Moving `prefix=` onto the router while a decorator still carries it produces
`/api/v1/organizations/organizations`; the multi-root modules (`datasets`, `projects`, `policies`)
are where this lands, because each declares more than one router.

**Fallback decision point.** The route-table probe against
`#### The resulting surface — all 47 operations` is the oracle and must be run **before** the test
suite, not after — a path diff is diagnosable, a `404` in a guard test is not. If a path cannot be
reproduced from the table because the table and the module split disagree, that is a design defect,
not an implementation one: stop and escalate rather than inventing a prefix.

### R3 — M8.1's abstract base surfaces raise sites the design's table did not enumerate

**Symptom.** The suite goes green but a route answers `500 application/problem+json` where it used to
answer `400` — because a bare raise the table missed now hits the `Exception` handler, which by
design reports nothing about the failure.

**Why it is dangerous here specifically.** This design's own safety net converts the mistake into a
generic 500 rather than a crash, so it will not show up as an error in any log the test suite reads.

**Fallback decision point.** M8.3's bijection test is the detector, and it must land in the same
milestone rather than being deferred — that is why it is a task and not a follow-up. If M8.1's
verification passes but M8.3 finds a code with no row or a route emitting a code outside
`wire_error_codes()`, treat it as an M8.1 defect and fix it there. If the missing site turns out to
be in `pkg` outside `huron.pkg.catalog.errors`, escalate: Design 6's walker reaches exactly two
modules, and a third would change the contract.

### R4 — The complexity gate rejects the restructured routers and `problems.py`

**Symptom.** `radon cc src/huron --min C` or `complexipy --max-complexity-allowed 15` fires on
`problems.py`'s handler dispatch, on `_dependency_checks`, or on a consolidated endpoint module.

**Why it happens.** Consolidating legacy paths concentrates branching that used to be spread across
duplicated code — the exact case `/implement-markdown` names.

**Fallback decision point.** The fix is a better decomposition along domain boundaries — one handler
per exception family, one builder per `responses` shape — never mechanical helper extraction to
satisfy the metric, and never a config exclusion. If a function genuinely requires the complexity to
express its domain logic, that is a plan defect to raise in the verification report, and the escalation
question is whether Design 6's six-handler shape should be five modules or one.

### R5 — The contract breaks ship piecemeal

**Symptom.** M5 lands and is deployed; a client discovers `/api/v1/roles` now answers `401` weeks
before `count` disappears from every collection in M6 and `DELETE /bindings/{id}` narrows in M9.

**Why it matters.** D-3, D-4, D-6, D-7, D-12 and D-16 are six separate visible breaks that this plan
deliberately groups so they can ship as one release. Landing them as six releases spends the same
client goodwill six times and makes each one look like an unrelated regression.

**Fallback decision point.** This is a release decision, not an implementation one: **hold the
release, never the milestones.** If the owner needs a partial deploy, the honest cut is everything
through **M3.1** — the execution-model change and the mechanical, contract-preserving half of the
repository decomposition, which together break no client contract — with **M3.2 onward** held
together. The cut is M3.1 and not M4 because M3.2 removes two keys from both release responses
(D-16), and M4.1 depends on M3.2, so no later milestone can be deployed without it.

---

## 5. Definition of done

The plan is complete when every task above is `Status: done`, every one passed the implement →
verify loop within its cap, and all of the following hold on the final tree.

**Gate.**

- The complete validation gate is clean from the repository root, with `[tool.mypy].files` and
  `[tool.ty.src].include` set to `["src/huron"]`.
- `uv run pytest -m contract` passes. It is not part of the gate's pytest line and must be run
  explicitly at the end, on a host with the container runtime named under §0's **Environment
  prerequisites**.
- Coverage is at or above the ratchet, and the ratchet has been **raised** to the new measured floor
  if coverage climbed. It is never lowered.
- No `# noqa`, `# type: ignore`, `# pragma: no cover`, `skip` or `xfail` was added anywhere in the
  run. `grep -rn 'type: ignore' src/huron` returns exactly one hit, in `settings_from_environment`.

**Structure.**

- `grep -rn 'request: Request' src/huron/service/api/routes/` returns nothing; exactly one function
  in the tier reads `request.app`.
- `records.py` imports nothing from `huron`; `postgres_auth.py` imports nothing from
  `huron.service.api`; `uv run lint-imports` keeps every contract.
- `routes/v1/common.py` does not exist. `jsonable` is imported by no route module and its docstring
  describes persistence only.
- `grep -rn -- '-> dict\[str, ' src/huron/service/api/routes/` returns nothing; the only two such
  handlers left in the tier are `/healthz` and `/readyz` in `app.py`.
- `grep -rn 'raise DomainError(\|HTTPException\|DOMAIN_ERROR' src/huron` returns nothing.
- No file under `migrations/` and no file under `src/huron/schema` was modified in the entire run —
  verifiable with `git diff --stat` against the run's base commit.

**Behavior.**

- Every `/api/v1` operation answers `401 application/problem+json` without a credential, and the
  requirement is declared on one router.
- Every response with status ≥ 400 is `application/problem+json` with the five required keys and a
  code that is a row in `design/api.html` §7 — including FastAPI's own 404, 405 and 422.
- `tests/unit/test_error_contract.py` passes and fails loudly in both directions when the code set
  and the table diverge.
- Every collection answers `422` to an out-of-range `limit` or a malformed `after`, and a cursor walk
  at `limit=1` enumerates it exactly once ending at `next_cursor: null`.
- No response body contains `generation`, `idp_subject`, `secret_sha256`, or `count`.
- `/readyz` answers `503` when a dependency is unavailable, never `4xx`.
- All four binding scope roots support create, list and revoke; a binding named from the wrong root
  is a `404`; no update verb exists at any scope.
- `make docs` builds `--strict`; `make test` and `make lint` pass; `make api` and the `Containerfile`
  `CMD` both name `huron.service.api.main:app`.

**Process.**

- Every one of the sixteen decisions in section 2 is recorded with the owner's answer. An unanswered
  decision means its milestone is not done, regardless of gate state.
- No code comment, docstring, test name or user-facing string references this plan, its milestones,
  its task numbers, `API_DESIGN.md`, or checklist mechanics anywhere in the diff.

---

## Verification

Adversarial plan verification, Phase 4. Coverage was checked in both directions against all nine
design sections (1, 2, 3, 4, 5, 5b, 6, 7, 8) including every `### Deletions` list; milestone ordering
was tested against the plan's own atomicity claims; every cited command was **executed** on the
working tree rather than reasoned about; and the new-contract test coverage was traced for Designs 5,
5b, 6 and 7.

**Result: 6 defects.** Coverage is complete in both directions — every design contract, interface and
deletion maps to a task, and every task carries a design basis. Ordering holds: no task depends on a
symbol an earlier task deletes or a module a later task creates, and the M2.1/M5.1/M8.1 atomicity
claims survive scrutiny (M2.1 because `create_app`'s required `settings=` and both deleted providers
fall in the same instant; M5.1 because a half-moved `prefix=` yields `/api/v1/organizations/organizations`;
M8.1 because all fourteen bare raise sites fail together). The defects are in executability and in one
unrecorded contract break.

### Defects

1. **`uv run pytest -m contract` cannot pass in this environment, and six places require it.**
   The plan makes the contract run a mandatory verify step in **M1.1, M2.1, M3.1, M8.1, M9.2** and in
   *§5 Definition of done*, and M3.1 calls it "mandatory" in prose. Both contract tests drive
   testcontainers against a migrated PostgreSQL, and no container runtime exists on the host.

   ```text
   $ uv run pytest -m contract -q
   FAILED tests/contract/test_auth_store.py::test_postgres_auth_stores_against_a_migrated_database
   FAILED tests/contract/test_rbac_store.py::test_postgres_rbac_and_api_key_stores_against_a_migrated_database
   2 failed, 212 deselected, 2 warnings in 1.05s
   E       FileNotFoundError: [Errno 2] No such file or directory
   .../docker/transport/unixconn.py:26: FileNotFoundError
   $ command -v docker podman ; echo $?
   1
   ```

   **Why it breaks execution.** A fresh subagent at M1.1 runs a step the plan declares mandatory,
   sees two hard failures unrelated to its change, and must either escalate on the first task or
   declare done with a red step. **Correction.** State the container-runtime precondition in §0
   beside the `pyscn` note and give the contract run the same disposition `pyscn` gets
   (stop-and-report), or mark it environment-conditional with a named skip condition.

2. **The plan's own stop-and-report condition is already triggered on the host it will run on, so no
   task can satisfy "Full validation gate clean".** §0's claim about the marker is **correct** —
   `pyscn>=1.30.0 ; platform_machine == 'x86_64' or sys_platform == 'darwin'` — and this host is
   `aarch64` / `linux`:

   ```text
   $ uname -m ; python3 -c "import sys; print(sys.platform)"
   aarch64
   linux
   $ uv run pyscn check src/huron
   error: Failed to spawn: `pyscn`
     Caused by: No such file or directory (os error 2)
   ```

   Every one of the 22 tasks ends in "Full validation gate clean", and the gate's last line is
   unsatisfiable. M3.2 additionally makes `pyscn check src/huron` an acceptance criterion in its own
   right. **Correction.** This needs a sixteenth entry in the §2 decision register — run on an
   x86_64/darwin host, or drop `pyscn` from the gate for this run — before M1.1 starts. Left as
   written, the plan self-blocks at task 1.

3. **M3.2 removes two fields from live API response bodies, inside a milestone the plan twice
   describes as breaking no client contract.** `Release.withdrawn_at` and `Release.withdrawn_reason`
   (`src/huron/service/api/repository.py:121-122`) are not persistence-only. They reach the wire:

   ```text
   $ sed -n '129p;137p' src/huron/service/api/routes/v1/endpoints/datasets.py
       return {"items": [jsonable(item) for item in sorted(items, key=lambda item: item.tag)]}
       return jsonable(get_repository(request).resolve_release(dataset_id, tag))
   $ sed -n '844,845p' src/huron/service/api/repository.py
   def _jsonable(item: object) -> dict[str, object]:
       values = asdict(item)  # type: ignore[arg-type]
   ```

   So `GET /api/v1/datasets/{id}/releases` and `GET .../releases/{tag}` both lose two documented keys
   at M3.2. M3.2's acceptance criterion mentions only "the release tag document written by
   `_write_generation`", and **R5** offers "everything through M4 — … which breaks no client contract
   at all" as the safe partial deploy. M3.2 is ungated and has no decision-register entry.

   **Why it breaks execution.** A milestone the plan certifies as contract-safe ships a silent
   response-shape change, and the release-grouping strategy in §2 and R5 is built on that certification.
   **Correction.** Either add a register entry for this break and group M3.2 with D-6/D-7/D-12, or
   scope M3.2's field deletion to the persisted document and let M6.2's `ReleaseView` remove the keys
   from the response with the rest of the envelope break.

4. **M8.1's delete list, taken via Design 6's `### Deletions`, points at the wrong classes; following
   the cited lines deletes two live error codes.** `API_DESIGN.md:5910-5911` says
   `class ApiKeyExpired` (**:130-131**) and `class ApiKeyRevoked` (**:134-135**) in
   `src/huron/pkg/catalog/errors.py`. Actual:

   ```text
   $ grep -n '^class \|^_DOMAIN_ERROR_TYPES' src/huron/pkg/catalog/errors.py | sed -n '/12[0-9]:\|13[0-9]:\|14[0-9]:\|16[0-9]:/p'
   130:class ClassificationExceeded(DomainError):
   134:class ProductStaleInput(DomainError):
   138:class ApiKeyExpired(DomainError):
   142:class ApiKeyRevoked(DomainError):
   162:_DOMAIN_ERROR_TYPES = (
   ```

   Lines 130-135 are `ClassificationExceeded` (`CLASSIFICATION_EXCEEDED`, 403) and `ProductStaleInput`
   (`PRODUCT_STALE_INPUT`, 409) — both live, both reserved table rows, neither a duplicate of anything
   in `pkg/auth`. The same block cites `_DOMAIN_ERROR_TYPES` at **:143-176**; it starts at **:162**
   (:143 is `ApiKeyRevoked`'s `code, status_code` line). `all_domain_error_types()` (:219) and
   `error_codes()` (:224) are the only two citations in that file that are right.

   **Why it breaks execution.** M8.1 is the atomic task with the largest blast radius and the plan
   directs it to Design 6's block as "the work list". An implementer that deletes by line removes two
   error classes M8.3's bijection test then reports as table rows with no class — surfacing as an M8.3
   failure whose cause is three tasks upstream. **Correction.** Fix the three citations in Design 6's
   `### Deletions` (`:138-139`, `:142-143`, `:162-196`), and have M8.1 name symbols rather than lines
   for that file.

5. **Two stale line citations in the plan itself, one of which collides with another task's deletion.**
   - **M3.1**: "`common.jsonable` (`common.py:31-32`)". `jsonable` is at `common.py:28-29`; lines
     31-32 are a blank line and `def expected_version(...)`, a symbol M6.1 must **keep** (it moves
     verbatim to `preconditions.py`).

     ```text
     $ sed -n '28,32p' src/huron/service/api/routes/v1/common.py
     def jsonable(item: object) -> dict[str, object]:
         return _jsonable(item)


     def expected_version(if_match: str) -> int:
     ```
   - **M6.2**: "`datasets.py:117-128`'s hand-built `{"items": [...]}` release envelope". The envelope
     is line **129**; 117-128 is the decorator, signature, existence call and comprehension. Worse,
     **M4.1 already deletes `datasets.py:124-129`** — the comprehension *and* the envelope return —
     as one of its four query-method conversions. Two tasks claim the same deletion and neither says
     which one owns `list_releases`' return shape.

   **Correction.** Repoint M3.1 at `common.py:28-29`; and state explicitly whether M4.1 or M6.2 owns
   `list_releases`' envelope (M4.1's own acceptance criterion — "response bodies for the four list
   routes are byte-identical to before this task" — implies M4.1 must rebuild it, not delete it).

6. **`uv run mypy` — the gate's fourth line — fails on this working copy before any task runs.**

   ```text
   $ uv run mypy ; echo "exit=$?"
   error: INTERNAL ERROR -- Please try using mypy master on GitHub:
   version: 2.3.1
   exit=2
   $ uv run mypy --show-traceback --cache-dir=/tmp/mypycache_v
   Success: no issues found in 26 source files
   ```

   The cause is a stale `.mypy_cache/` in the tree (gitignored, so it is a working-copy condition, not
   a repository one). **Why it breaks execution.** Every task's gate — and `make lint` — starts red
   for a reason unrelated to the change, and attempt 1 of M1.1 burns on it. **Correction.** Add a
   one-line preamble to §0: clear `.mypy_cache/` before the run.

### Commands executed, and what they returned

| Command | Result |
|---|---|
| `uv run ruff check .` | `All checks passed!` |
| `uv run ruff format --check .` | `95 files already formatted` |
| `uv run ty check` | `All checks passed!` |
| `uv run mypy` | **exit 2, INTERNAL ERROR** (defect 6); clean with a fresh `--cache-dir` |
| `uv run lint-imports` | `Contracts: 5 kept, 0 broken.` |
| `uv run pytest --cov=src/huron --cov-report=term-missing` | `212 passed, 2 deselected`; `TOTAL … 81%`; `Required test coverage of 75.0% reached. Total coverage: 80.52%` |
| `uv run pytest -m unit` (`make test`) | `212 passed, 2 deselected` |
| `uv run pytest -m contract -q` | **2 failed, 212 deselected** (defect 1) |
| `uv run radon cc src/huron --min C` | four C-grade items on the untouched tree (`ApiSettings`, `ApiSettings.refuse_unsafe_combinations`, `Binding.covers`, `parse_revision_dir`); exit 0 |
| `uv run radon mi src/huron --min B` | `repository.py - B` |
| `uv run complexipy src/huron --max-complexity-allowed 15` | `All functions are within the allowed complexity.` |
| `uv run pyscn check src/huron` | **`Failed to spawn: pyscn`** (defect 2) |
| `uv run ruff linter \| grep -i fast` | `FAST  FastAPI` — M10.2's rule family exists in ruff 0.16.3 |
| `uv run --group docs zensical build --strict` | not verifiable from this session (the sandbox blocks removal of `site/`; zensical panics with `site directory could not be cleaned: PermissionDenied`). Not a repository condition |

### Load-bearing claims tested and CONFIRMED

- **`addopts = "-m unit --strict-markers"` means the gate never runs `tests/contract/`.** Confirmed
  from `pyproject.toml` and by running both: the gate line reports `212 passed, 2 deselected`, and
  `-m contract` reports `212 deselected` with exactly the two contract modules selected
  (`pytestmark = pytest.mark.contract` at `tests/contract/test_auth_store.py:55` and
  `test_rbac_store.py:57`). The plan's per-task callouts are correctly placed.
- **`pyscn` is unsatisfiable off x86_64/darwin.** Confirmed from the dependency marker and by running
  it (see defect 2).
- **Counts.** All of the plan's load-bearing counts are exact on the current tree:
  `grep -rn 'request: Request' src/huron/service/api/routes/ | wc -l` → **44**;
  `grep -rn 'raise DomainError(' src/huron | wc -l` → **14**;
  path operations under `src/huron/service/api` → **47**;
  guard-only `_actor` parameters → **22** (10 `CurrentPrincipal` + 11 `Annotated[…, Depends(require_*)]`
  + 1 `_Actor`), value-reading `actor` → **16**; `type: ignore` in `src/huron/service` → **five**
  (`app.py:107`, `repository.py:845`, `rbac.py:172,174,176`), and the plan's terminal "exactly one,
  in `settings_from_environment`" is reachable: M2.1 creates that function with the `call-arg` ignore
  and deletes `app.py:107`, M3.1 removes `repository.py:845`, M9.1 removes the three in `rbac.py`.
- **Entrypoint string, three hand-maintained sites.** `Makefile:30`, `Containerfile:27`,
  `docs/getting-started/local-development.md:131` — all three confirmed at the exact lines D-1 cites.
- **Design heading references.** All 52 `###`/`####` headings the plan cites were checked against
  `API_DESIGN.md`; 47 match verbatim. The five that do not are truncations or ellipses, not wrong
  targets (see Observations).
- **Spot-checked line citations that are correct:** `app.py:101` (`settings: … | None = None`),
  `:107` (the `call-arg` ignore), `:127-136` (eager fallback), `:179-180` (`readyz`'s state read),
  `:185-187` (search), `:189-191` (the three-line comment — exact), `:192-193` (`include_router`);
  `authorization.py:75-76` (`Forbidden`), `:85-88` (the false docstring), `:225` (`cached_bindings_for`),
  `:400` (`__all__`); `repository.py:41` (`EntityRef` import), `:56-57` (`ResourceNotFound`),
  `:650` (the `withdrawn_at` branch), `:845` (the ignore), `:867` (`entity_ref`), `:871` (`local_repository`);
  `rbac.py:43` (`del request`), `:44-63` (role catalog), `:150`/`:160` (binding envelopes),
  `:172,174,176` (the three ignores); `organizations.py:50-52`, `projects.py:54-58`,
  `datasets.py:68-70`, `:124-129`, `:150`/`:153` (the accumulator and `allowed`); `policies.py:40`;
  `login.py:64`, `session.py:19`; `Containerfile:1-5`; `pkg/rbac/roles.py:91`;
  `pkg/catalog/ingest.py:77,87`. `design/api.html` has `<h2 id="errors">7. Error codes</h2>` with a
  `<pre>` at `:212` and **zero** occurrences of `id="error-codes"`, so M8.3's edit is genuinely required.

### New-contract test coverage

Traced and adequate. Design 6's bijection test is M8.3, correctly paired with the one in-scope
`design/api.html` edit in the same task — that pairing is coherent and necessary: the test parses
`id="error-codes"`, which does not exist today, so deferring the markup would make the test
unsatisfiable and deferring the test would leave R3's failure mode undetected. Design 7's delete-path
contract is pinned bullet-for-bullet in M9.1 (`204` at four roots, revoked capability, cross-root
`404`, repeated `DELETE`, `403`-vs-`404` ordering). Design 5's response-shape contracts are pinned in
M6.1 (exact key set, `422` on four bad-pagination cases, the cursor-walk-to-`null` test,
`Page.model_validate` failing) and M6.2 (`LayerView` flags, no `ETag`, idempotent replay); Design 5b's
in M7.1 (`RoleBindingView.scope_id` null iff SYSTEM, bare array for `/roles`), M7.2 (`secret` in
exactly two schemas, no `from_attributes` on either) and M7.3 (`UserView` key set, no `idp_subject`
under `routes/`). No new contract is introduced without a task that writes the test pinning it.

### Observations

Judgment calls and inaccuracies that do **not** stop a task from executing.

1. **"The eight test modules that construct apps" is five.** `grep -rln 'create_app' tests/` returns
   `test_api_login.py`, `test_api_app.py`, `test_api_rbac.py`, `test_api_oidc.py`, `test_api_users.py`,
   and `grep -rln 'TestClient' tests/` returns the same five. The number is inherited from
   `API_DESIGN.md` (which repeats it at :657, :676, :5505, :6227). M2.1's *Modify* list is
   nevertheless **correct** — Design 2's "Existing tests that must change" table (:1861-1871) names
   exactly the three that change and states the other four need none, and I confirmed all four already
   pass `settings=` and use `with TestClient(...)`. Only the sizing rationale in M2.1 and R1 carries
   the wrong figure.
2. **A fourth in-repo occurrence of the entrypoint string survives the run**:
   `IMPLEMENTATION_PLAN.md:874` (the shipped platform plan's `Containerfile` excerpt). D-1's "three
   in-repo files" is right for hand-maintained *runtime* references, and the file is out of scope, but
   the string is still there at the end.
3. **M5.1's route-table probe is not runnable as written** — `create_app(settings=ApiSettings(...))`
   contains a literal ellipsis. R2 makes this probe "the oracle … run **before** the test suite", so
   it is worth spelling out the settings construction the way `tests/unit/test_api_rbac.py:44` does.
4. **M2.1's `create_app()` probe swallows its exit status** — `uv run python -c "…" ; echo "expect
   TypeError above"` reports success whatever happens. A `|| echo OK` inversion would assert it.
5. **Five heading citations are abbreviations, not verbatim matches.** M10.3 cites `#### 1. Entrypoint`,
   `#### 2. ORM`, `#### 3. Frontend` (actual: `#### 1. Entrypoint — uvicorn stays; no fastapi-cli, no
   [tool.fastapi] table`, `#### 2. ORM — SQLModel is adopted nowhere; …`, `#### 3. Frontend — the API
   serves no frontend; …`); D-6's row cites `#### limit, after, …`; M9.1 cites Design 7's
   `#### Target design`, which is a `###`. All are findable; none is wrong.
6. **M8.3's `make docs` acceptance rests on a false premise.** It reads "`make docs` still builds …
   **since §7's markup changed**". `design/api.html` is not in the built site: `zensical.toml`'s `nav`
   names only pages under `docs/`, and its header says "The architecture lives in `design/` at the
   repository root". Editing that file cannot affect the docs build in either direction — which raises
   the stakes on the bijection test being the *only* checker of that markup.
7. **`[tool.mypy].files` lists two surfaces, not three.** M10.1's "rather than three explicit surfaces"
   should read two (`src/huron/pkg`, `src/huron/schema`).
8. **The `repository.py` N818 per-file-ignore is removed one milestone later than the design says.**
   Design 6 notes it "also goes, one design earlier"; M3.1 does not touch `pyproject.toml` and M8.1
   removes it. Harmless — an unneeded per-file-ignore produces no ruff diagnostic — but between M3.1
   and M8.1 the file carries an ignore for a class that has left.
9. **`radon cc src/huron --min C` already prints four items on the untouched tree** and exits 0.
   "Full validation gate clean" should not be read as "radon prints nothing", or R4's symptom will be
   misdiagnosed on the first run.
10. **Design 3's `Release.withdrawn_*` citation is off by one** (`:122-123` vs the actual `:121-122`),
    and Design 6's `DomainError` defaults citation likewise (`:15-16` vs `:14-15`). Both are harmless
    given the symbol names; noted only because defect 4 shows the same file's citations drifting.

---

### Re-verification (cycle 2)

Focused pass over the six corrections and their blast radius. Coverage, ordering and the
M2.1/M5.1/M8.1 atomicity claims were established in cycle 1 and were not re-derived. Every line
number below was checked against the source file, not against the correction's own report.

**Defect 1 — mandatory `pytest -m contract` unrunnable — CORRECTED.**
§0 gained an **Environment prerequisites** block (`:63-84`) whose first bullet names the container
runtime, names all five per-task sites *and* §5's final run, and gives the disposition
**stop and report** — explicitly refusing the skip/weaken workaround under rule 2. None of the
`pytest -m contract` steps were removed: they are still present at M1.1 (`:277`, `:301`), M2.1
(`:400`, `:421`), M3.1 (`:477`, `:491`), M8.1 (`:1100`, `:1122`), M9.2 (`:1324`) and §5 (`:1555`).
The cross-references at `:45`, `:56-57` and `:1555-1556` point at text that exists and reads as
claimed. That text is a bold lead-in, not a `#`-level heading, so it is a text reference rather than
a linkable anchor — cosmetic, recorded not fixed.

**Defect 2 — `pyscn` unsatisfiable off x86_64/darwin — CORRECTED.**
Second prerequisite bullet (`:72-76`) quotes the marker as
`platform_machine == 'x86_64' or sys_platform == 'darwin'`, verified verbatim against
`pyproject.toml:51`. It names both consequences (gate's last line, M3.2's acceptance criterion) and
forbids dropping `pyscn`. `pyscn` remains in the gate (`:36`) and remains M3.2's criterion (`:542`).
The correction chose the precondition route over the register-entry route the defect suggested as
one of two options; this is the stronger of the two, since a register entry could be answered
"drop `pyscn`", which rule 2 forbids.

**Defect 3 — M3.2's unrecorded wire break — CORRECTED, blast radius clean.**
D-16 exists as a full register row (`:184`) sourced to the plan rather than to one of the 33, with a
recommendation to ship it with D-6/D-7/D-12. The register intro (`:153-156`) explains the sixteenth
entry. Restatements checked exhaustively:

- `grep -ni 'ungated\|un-gated\|not gated\|no gate'` → `:189-192` and `:1679` only. `:189-192` says
  M1 and **M3.1** are ungated and names M3.2-on-D-16 explicitly, plus M4's inherited gate. `:1679`
  is inside the original defect statement and is correctly left alone. **No surviving claim that M3
  or M4 is entirely ungated.**
- `grep -ni 'fifteen\|sixteen'` → `:148`, `:153`, `:156`, `:623`, `:687`, `:1089`, `:1596`, `:1659`.
  `:148`/`:156` say "fifteen" about the entries that come from the 33, immediately qualified by
  `:153`'s sixteenth-entry paragraph — internally consistent. `:1596` (§5) now reads "sixteen
  decisions". `:623`, `:687`, `:1089` are the bare-raise and `actor`-parameter counts, unrelated.
  `:1659` is the original defect text. **No count says fifteen where it should say sixteen.**
- §3 milestone table: M3 row gated `D-16 (task M3.2)`; M4 row `D-14 (task M4.2); inherits D-16 via
  M4.1's dependency on M3.2`. M3's milestone intro (`:434-436`) scopes "contract-preserving" to M3.1
  alone. M3.2's heading carries `— **GATED on D-16**`, its body has a "This task is not
  contract-preserving" paragraph, and a new acceptance criterion pins the two response bodies losing
  the keys and requires updating any test that asserted the old key set. R5 (`:1532`, `:1538-1541`)
  now lists D-16 among the six breaks and moves the honest partial-deploy cut from "everything
  through M4" to **M3.1**, giving the reason.

**Defect 4 — Design 6's wrong delete-by-line citations — CORRECTED. Receipts from `errors.py`:**

| Plan's corrected claim | Source, verified |
|---|---|
| `ApiKeyExpired` **:138-139** | `138:class ApiKeyExpired` / `139:    code, status_code = "APIKEY_EXPIRED", 401` ✅ |
| `ApiKeyRevoked` **:142-143** | `142:class ApiKeyRevoked` / `143:    code, status_code = "APIKEY_REVOKED", 401` ✅ |
| `_DOMAIN_ERROR_TYPES` **:162-195** | `162:_DOMAIN_ERROR_TYPES = (` … `195:)` ✅ |
| `DomainError.code` / `.status_code` **:14-15** | `14:    code: str = "DOMAIN_ERROR"` / `15:    status_code: int = 400` ✅ |
| `:130-131` is `ClassificationExceeded` | `130:class ClassificationExceeded` / `131: … "CLASSIFICATION_EXCEEDED", 403` ✅ live |
| `:134-135` is `ProductStaleInput` | `134:class ProductStaleInput` / `135: … "PRODUCT_STALE_INPUT", 409` ✅ live |
| `all_domain_error_types()` **:219-222**, `error_codes()` **:224-225** cited correctly | confirmed ✅ |

M8.1 carries the supersession block at `:1039-1057`: **"This task supersedes Design 6's `###
Deletions` line numbers for `src/huron/pkg/catalog/errors.py`. Delete by symbol, never by line."**
It tabulates all four stale citations, names the two classes to delete and no others, and adds
`grep -n '^class ' src/huron/pkg/catalog/errors.py` as a pre-edit confirmation plus
`grep -n 'CLASSIFICATION_EXCEEDED\|PRODUCT_STALE_INPUT'` to its verify block.

**Defect 5 — the two stale citations — CORRECTED. Receipts:**

- `routes/v1/common.py`: `28:def jsonable(...)` / `29:    return _jsonable(item)`; `30-31` blank;
  `32:def expected_version(if_match: str) -> int:`. M3.1 (`:459-461`) now cites **`common.py:28-29`**,
  says "delete by symbol, not by line", and warns that `:31-32` is the blank line and
  `expected_version`, which M6.1 must keep. ✅
- `endpoints/datasets.py`: `119:@router.get(".../releases")`, `120-122` signature, `123` repository,
  `124` existence call, `125-129` comprehension, `130` `return {"items": [...]}`. M4.1 (`:576-577`)
  cites `datasets.py:125-130` and decomposes it exactly as `:125-129` comprehension + `sorted(...)`
  inside the return at `:130`. ✅
- **Ownership now agreed.** M4.1 gained a headed paragraph (`:579-582`): "**M4.1 owns
  `list_releases`' response shape; M6.2 replaces it.**" — the envelope at `:130` is *rebuilt* over
  the new query method, not deleted, per M4.1's byte-identical criterion. M6.2 (`:812-816`) deletes
  "`list_releases`' hand-built `{"items": [...]}` release envelope (`datasets.py:130` on the pre-M4.1
  tree … which M4.1 rebuilds over the repository query and this task replaces)". No double-deletion
  remains and neither task is silent about the other.

**Defect 6 — `uv run mypy` red from a stale cache — CORRECTED.**
Third prerequisite bullet (`:78-84`) states the condition, the symptom (`INTERNAL ERROR`, exit 2,
also via `make lint`), the fix (clear `.mypy_cache/` or pass a fresh `--cache-dir`), when to redo it,
and — the operative part — that it is a working-copy condition and is "never a gate failure to record
against a task and never evidence of a defect in the change under test." `.mypy_cache/` is still
present in the working tree, so the precondition is live and correctly stated.

**New defects introduced by the correction pass: none blocking.** One imprecision:

- **N-1 (non-blocking).** M6.2 `:815` parenthesises "`:117-128` is the decorator, signature and
  existence call, not the envelope". On the real file `:117-118` are blank and `:125-128` are the
  first four lines of the comprehension, so the *description* of the discarded range is loose. The
  operative claim — the envelope is `:130`, not `:117-128` — is correct, and M6.2 deletes by
  description, not by that range. Recorded, not fixed.

**Regression checks.**

- `## Verification` (`:1603` onward, above this subsection) is unmodified: defect 3 still reads "M3.2
  is ungated and has no decision-register entry", defect 4 still quotes the pre-correction citations,
  and defect 5 still quotes `common.py:31-32` — all correct, since that section records what cycle 1
  found, not what the plan now says.
- 23 `### Task M` headings, 23 `**Status: pending**`, zero non-`pending` statuses.
- `API_DESIGN.md` is **7,251 lines**, unchanged. `grep` for `D-16`, `Environment prerequisites`,
  `delete by symbol`, `162-195` and `:138-139` returns nothing in it, and Design 6's `### Deletions`
  block still carries the original `:130-131` / `:134-135` / `:143-176` citations — the correction
  superseded them inside the plan rather than editing the design, which is the right side of the
  boundary. Consequence recorded under the non-blocking list below.

**Gate re-run (this host).** `uv`'s default `.venv/` is the plan author's darwin venv mounted
read-only, so the run used `UV_PROJECT_ENVIRONMENT` outside the tree; this changes nothing about the
checks.

| Command | Result |
|---|---|
| `ruff check .` | `All checks passed!` — exit 0 |
| `ruff format --check .` | `95 files already formatted` — exit 0 |
| `ty check` | `All checks passed!` — exit 0 |
| `lint-imports` | `Contracts: 5 kept, 0 broken.` — exit 0 |
| `mypy --cache-dir=<fresh>` | `Success: no issues found in 26 source files` — exit 0 |
| `pytest -m unit -q` | `212 passed, 2 deselected` — exit 0 |
| `pyscn check src/huron` | not runnable on this `aarch64`/`linux` VM — a host property, documented in §0, **not a defect** |
| `pytest -m contract` | not runnable — no container runtime on this VM — documented in §0, **not a defect** |

§0's stated gate facts still match reality: `addopts = "-m unit --strict-markers"` (212 unit
selected, 2 contract deselected), `mypy` clean over 26 files under the two configured surfaces, and
the `pyscn` marker verbatim as quoted.

#### Re-verification result: VERIFIED

All six defects are corrected, the D-16 blast radius is internally consistent everywhere it is
restated, and every corrected line number was confirmed against the source. Nothing blocks execution.

**Blocking: none.**

**Non-blocking, recorded and accepted (final cycle):**

1. **N-1.** M6.2 `:815`'s parenthetical mis-describes which lines `:117-128` covers. Operative claim
   correct; no action.
2. **API_DESIGN.md Design 6 `### Deletions` still holds the four stale `errors.py` citations.** An
   implementer who reads the design directly rather than through M8.1 could still delete by the wrong
   lines. Mitigated — M8.1 is the only task that consumes that block, it opens with an explicit
   supersession notice, it names the two classes, and it requires a `grep -n '^class '` before
   editing. Accepted rather than editing the design document.
3. **`## Verification`'s defect 2 says "22 tasks"; there are 23.** Inside the cycle-1 record, which
   the correction pass was correctly told not to touch. Affects no instruction to an implementer.
4. **"Environment prerequisites" is a bold lead-in, not a heading,** so the three cross-references to
   it are textual rather than anchored. Cosmetic.
