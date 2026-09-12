# Huron — API Tier Implementation Plan

Companion to [`API_DESIGN.md`](API_DESIGN.md), which is the authoritative specification for
everything below. This file sequences that design into milestones and mechanically verifiable tasks;
it never restates the design. Every task names the `API_DESIGN.md` heading that specifies it, and an
implementer is expected to read that heading before editing.

This plan is executed by `/implement-markdown API_IMPLEMENTATION_PLAN.md`. It is deliberately named
apart from [`AUTH_IMPLEMENTATION_PLAN.md`](AUTH_IMPLEMENTATION_PLAN.md) (the shipped platform plan) and
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

- **A container runtime** (Docker or Podman) reachable by `testcontainers`. All **three** modules
  under `tests/contract/` — `test_auth_store.py`, `test_rbac_store.py` and `test_catalog_store.py`,
  each carrying `pytestmark = pytest.mark.contract` — drive a migrated PostgreSQL, so every per-task
  `uv run pytest -m contract` step in this plan — M1.1, M2.1, M3.1, M8.1, M9.2, M11.2, M11.3 — and
  §5's final contract run depend on it. Without one, all three contract modules fail with
  `FileNotFoundError` on the daemon socket, for reasons
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
3. **No migration; and no SQL change before M11.** No task in this plan may add, edit, or require a
   file under `migrations/`, and **for M1 through M10** none may change SQL in `postgres_rbac.py` or
   `postgres_auth.py` — through M10, only Python module boundaries move. **M11 is the exception, and
   it is the only one.** The owner has explicitly opened SQL for that milestone, because Design 10
   proved a live pagination defect that no boundary change can fix: walking a keyset cursor over a
   default-collation `ORDER BY` on the cluster this service actually deploys against loses four of
   fourteen rows and repeats one, and `ORDER BY name` on `policies` reorders its ties between two
   executions of the identical query. The fix is in the query, so the query changes. Inside M11 the
   opening is narrow: `SELECT` text, `COLLATE` and `ORDER BY` clauses in the store modules may
   change, and **DDL may not.** `migrations/` and `src/huron/schema` stay out of scope for M11
   exactly as they are for M1–M10 — no index, no constraint, no column, no table is added, dropped or
   altered, and Design 10's three candidate indexes are a hand-off to the 0008 schema track (§1), not
   work in this plan. If a task appears to need a migration, that is a plan defect — escalate.
4. **Deletions land with the change that makes them dead**, in the same task, never deferred.
5. **No task in this plan waits on a decision.** All **seventeen** entries in section 2 were
   answered by the owner on **2026-09-01**, and every task's answer is recorded in the row that names
   it. There is nothing to check before starting a task and nothing to escalate for want of an
   answer. Section 2 remains the source for *why* each settled choice is what it is — read the row
   your task cites, because an implementer still needs to know that `/api/v1/roles` is deliberately
   `401` rather than accidentally so. One answer, **D-10**, departs from the design's recommendation:
   `CreatePolicy.spec` gains a 1 MiB ceiling where Design 5b's Open question 2 recommended shipping
   none absent a number. That deviation is specified in section 2's D-10 row and in task M7.3, and
   those two places govern — do not re-derive it from `API_DESIGN.md`. The one item still outstanding
   anywhere is not a task gate: under D-1 the owner updates the external deployment artifacts that
   name `huron.service.api.app:app` before the release is deployed. M2 is implementable and buildable
   today; see section 2's note on D-1.

---

## 1. Goal and non-goals

**Goal.** Bring `src/huron/service/api` to the target described in `API_DESIGN.md`: blocking work off
the event loop under one stated rule; a total, typed composition root with declared dependencies
instead of `Request`-threading; `repository.py` decomposed so storage adapters no longer import the
application service; a router tree where prefix, tags and authentication are declared once and the
whole versioned surface is closed to anonymous callers; a declared response type and a real
pagination envelope for every operation; one uniform `application/problem+json` error contract with a
mechanically checked code table; the binding surface completed; `authorization.py` and the five
storage adapters decomposed into packages entered through their public surfaces; and the two
collation-and-tiebreak ordering defects fixed in the SQL that produces them.

**Non-goals — explicitly out of scope for every task in this plan.**

- **`src/huron/schema` and `migrations/`.** Both are being changed concurrently by other work. No
  task here may edit either, and no task may require a migration. See rule 3 above — which M11 opens
  for *queries* only: M11 changes `ORDER BY` clauses and adds `COLLATE "C"`, and it still writes no
  DDL and touches neither of these two trees. **Hand-off, not a decision and not a gate:** Design 10
  → `### Open questions` → item 3 hands the 0008 schema track three candidate indexes — a `UNIQUE`
  index on `policies (name COLLATE "C")`, recommended and behavior-changing, plus two deferred
  covering indexes for `service_accounts` and `role_bindings`, priced there with their query plans.
  None is required: every query M11 ships is correct without all three, so none of them gates M11 and
  none appears in §2. They belong to whoever owns `migrations/`.

  **Where that hand-off actually goes, checked 2026-09-01.** `0008_schema_conformance` has since
  merged to `main`, so the three candidate indexes are work for `0009`, not for `0008`. Design 10
  applied `0001`–`0007` and deliberately skipped `0008`, which was in flight at the time; that
  omission does **not** weaken its receipts, and three facts were re-checked against the merged
  migration to establish it:

  - `0008` adds no `COLLATE` anywhere and no uniqueness on `policies (name)` — it adds the CHECK
    `policies_spec_is_an_object` and nothing else to that table. The ordering hazard D-17 fixes is
    still live on `main`, and the `id` tiebreak is still load-bearing.
  - `0008` **already resolves** Design 10's incidental finding that `role_bindings_principal_scope`
    could not serve `bindings_at`: it drops that index as a strict subset of
    `role_bindings_no_duplicates` and adds `role_bindings_scope` for the scope-listing path. Do not
    re-report it.
  - `policies_spec_is_an_object` and D-10's `MAX_POLICY_SPEC_BYTES` are complementary, not
    overlapping: the database requires the spec to be a JSON object, the API bounds how large that
    object may be. Neither subsumes the other and M7.3 needs no change for it.
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
  `API_DESIGN.md` as future work with its seam recorded. No task anticipates any of them. **M11's SQL
  change is not the push-down** and must not be mistaken for its first half: no store method gains a
  `limit` or an `after` parameter, no `WHERE` predicate changes, and the boundary still windows. What
  M11 changes is the order the store returns, so that it is the order the boundary already assumes.
- **Reopening any decision in section 2.** All seventeen were answered on 2026-09-01 and are
  recorded there with the owner's answer. An implementer implements the recorded answer as written;
  revisiting one is a design change and belongs back in `/design-plan`, never in an implementer's
  judgement.

---

## 2. Human decision register

`API_DESIGN.md` raises **40 open questions** across its eleven design sections. Twenty-three are
settled inside the document by a recommendation that needs no external fact (for example Design 2's
OQ3 on `dependency_overrides`, Design 3's OQ1 on where `limit` descends, Design 6's OQ3 on the `NOT_FOUND`
collision, Design 9's three — `CookieSpec` replacing the six cookie names, the sixth import-linter
contract, and splitting the authorization test module — and Design 10's OQ2 and OQ4, on the
in-memory sort key and on `ports.py` living inside `stores/`); implementers follow those directly and
this register does not repeat them. **One more is neither settled here nor a decision:** Design 10's
OQ3 hands three candidate indexes to the 0008 schema track, recorded under §1's non-goals. The
arithmetic closes: 23 settled + 16 below + 1 handed off = 40.

The **sixteen below needed a human**, because each was either a visible contract break, a capacity
or deployment number this repository cannot supply, or a policy choice about code that does not exist
yet. Each is recorded as the question that was put, the design's recommendation, the milestone the
answer governs, and — in the last column — **the owner's answer**.

**All seventeen are ANSWERED, as of 2026-09-01.** No task in this plan is waiting on anyone. The
`GATED on` markers that stood on fifteen task headings are gone, and every `D-` reference that survives
elsewhere in this document cites the row as the **source of a settled choice**, never as a wait.
The one item still outstanding anywhere is a release-coordination step and not a gate: under D-1 the
owner updates the external deployment artifacts before the release is deployed (note below).

**D-16 is the one entry that does not come from one of the 40.** It is a wire-visible contract
break this plan surfaced while sequencing Design 3's `### Deletions`, which state the deletion but
not its effect on response bodies. It is recorded in the same table because it governs a milestone
the same way the other sixteen do.

| ID | Decision | Source | Recommendation | Governs | **Answer — all ANSWERED 2026-09-01** |
|---|---|---|---|---|---|
| **D-1** | Is `huron.service.api.app:app` named by any deployment artifact outside this repository? Rename to `huron.service.api.main:app`. | D2 OQ1, D8 OQ1 | Rename; edit the **three** in-repo files (`Makefile:30`, `Containerfile` `CMD`, `docs/getting-started/local-development.md:131`) — Design 8 corrects Design 2's count of two. | M2 (see the D-1 note below) | **Yes — external deployment artifacts do name `huron.service.api.app:app`.** The rename to `huron.service.api.main:app` proceeds; M2 edits the three in-repo files, and the owner updates the external artifacts in the same release. **Not a task gate:** the coordination is at deploy time, not build time, so M2 is implementable and buildable now. |
| **D-2** | Does password hashing get its own capacity limiter, and at what size? | D1 OQ1 | Yes, default 4, passed at the `verify_password` call site. | M1.2 only | **Yes — a dedicated limiter, size 4.** As recommended: `total_tokens = 4`, constructed once at module level and passed at the `verify_password` call site. |
| **D-3** | `GET /api/v1/roles` becomes `401` to anonymous callers. Contract break. | D4 OQ1 | Authenticate it. | M5 | **Accept.** `GET /api/v1/roles` becomes `401` to anonymous callers. Ships in the one grouped release. |
| **D-4** | `GET /api/v1/search` becomes `401` to anonymous callers and moves out of `app.py`. Contract break. | D4 OQ2 | Authenticate and relocate. | M5 | **Accept.** `GET /api/v1/search` becomes `401` and relocates out of `app.py`. Ships in the one grouped release. |
| **D-5** | Twelve OpenAPI tags instead of seven; generated SDK shape changes. | D4 OQ3 | Adopt the finer set. | M5 | **Accept.** Twelve OpenAPI tags, the finer set. |
| **D-6** | The envelope break: `count` is removed, `limit`/`after` are added, and an out-of-range `limit` becomes `422` instead of a silent clamp. Contract break on every collection. | D5a OQ3 + D5a `#### limit, after, …`, D5b OQ4 | Ship it. | M6, M7 | **Accept, in full.** `count` is removed, `limit`/`after` are added, and an out-of-range `limit` answers `422` rather than clamping silently. Ships in the one grouped release. |
| **D-7** | `GET /api/v1/roles` loses its `{"items": [...]}` wrapper and returns a bare `list[RoleView]`. Contract break. | D5b OQ4 | Ship it with D-6. | M7.1 | **Accept.** `GET /api/v1/roles` returns a bare `list[RoleView]`. Ships in the one grouped release. |
| **D-8** | `GET /auth/session` gains `effective_roles: list[ScopeRoles]`, fetched on every page load; a principal bound at fifty datasets reports fifty entries. | D5a OQ1 | Ship as designed; the roadmap's `todo` applies to the frontend alone. | M6.3 | **Ship as designed.** `effective_roles` on `GET /auth/session` for every scope the principal is bound at; no `?scopes=` filter and no other narrowing. |
| **D-9** | Is `GET /api/v1/roles` readable by every authenticated caller, or does it require `rbac.binding_manage`? | D5b OQ1 | Every authenticated caller; the catalog is vocabulary, not configuration. | M7.1 | **Every authenticated caller** may read `GET /api/v1/roles`. No `rbac.binding_manage` requirement — the catalog is vocabulary, not configuration. |
| **D-10** | What byte ceiling, if any, bounds `CreatePolicy.spec`? The design asks for a domain number it cannot supply. | D5b OQ2 | Bound the request, not the response. **If no number is supplied, ship no bound** and record that as the answer — do not invent one. | M7.3 | **A 1 MiB ceiling on `CreatePolicy.spec`** — `1_048_576` bytes, measured over RFC 8785 canonical JSON. **This is the one answer that deviates from its recommendation**, which was to ship no bound if no number was supplied: the owner supplied one. The mechanism is not a Pydantic `max_length` — `spec` is `dict[str, object]` — and is specified in full as task M7.3's third sub-item. |
| **D-11** | Rename the documented code `SESSION_EXPIRED` → `INGEST_SESSION_EXPIRED` (409, reserved) and add a new `SESSION_EXPIRED` (401, live). | D6 OQ4 | Rename. | M8.1 | **Rename.** `SESSION_EXPIRED` becomes `INGEST_SESSION_EXPIRED` (`409`, reserved), and a new live `SESSION_EXPIRED` (`401`) is added. |
| **D-12** | `DELETE /api/v1/bindings/{binding_id}` narrows from "revoke any binding" to "revoke a SYSTEM binding"; the same id now answers `404` there. Contract break. | D7 OQ3 | Ship it with D-6. | M9.1 | **Accept.** `DELETE /api/v1/bindings/{binding_id}` narrows to SYSTEM scope; a non-SYSTEM id answers `404` there. Ships in the one grouped release. |
| **D-13** | Do the binding collections list grants that have already lapsed? | D7 OQ4 | Return them; `bindings_at` does not filter expiry and `expires_at` is published. If the owner prefers filtering, the filter belongs in `bindings_at` on **both** backends — which this plan forbids (rule 3) and which would return the work to `/design-plan`. Rule 3's M11 opening does not reach this: it covers `ORDER BY` and collation, never a `WHERE` predicate. | M9.2 | **Return them.** The binding collections list grants that have already lapsed; `bindings_at` gains no `WHERE` predicate on either backend. |
| **D-14** | `POST /api/v1/datasets/{id}/releases` cannot succeed until P2 ingest lands. Is that accepted, and pinned by a test that drives `register_revision` directly? | D3 OQ2, D5a OQ4 | Accept and pin. | M4.2 | **Accept and pin.** The releases route stays unreachable until P2 ingest lands, pinned by a test that drives `register_revision` directly. |
| **D-15** | `[tool.mypy].files` / `[tool.ty.src].include` become `["src/huron"]` rather than three explicit surfaces, so future service tiers inherit `--strict` without opting in. | D8 OQ2 | `["src/huron"]`. | M10.1 | **`["src/huron"]`** for both `[tool.mypy].files` and `[tool.ty.src].include`. |
| **D-16** | Deleting `Release.withdrawn_at` and `Release.withdrawn_reason` removes two documented keys from live response bodies: both records reach the wire through `jsonable` → `asdict`, so `GET /api/v1/datasets/{id}/releases` and `GET /api/v1/datasets/{id}/releases/{tag}` both change shape. Contract break. | Plan — D3 `### Deletions` orders the deletion but states only the persistence effect | Ship it with D-6, D-7 and D-12 as part of the one grouped release; the fields are always `null` today, but a removed key is still a removed key. | M3.2 (and, through M4.1's dependency on M3.2, all of M4) | **Accept.** `Release.withdrawn_at` and `Release.withdrawn_reason` go, and the two keys leave both release responses. Ships in the one grouped release. |
| **D-17** | M11 changes shipped SQL. `PostgresRbacStore.list_policies` becomes `ORDER BY name COLLATE "C", id`, `list_service_accounts` becomes `ORDER BY sa.name COLLATE "C"`, and `InMemoryRbacStore.list_policies` sorts by `(item.name, str(item.id))` to match. No response model, cursor format or envelope changes — the boundary already sorts and publishes the order (D-6, Design 5b Decision 1) — but a keyset walk that silently dropped rows and repeated one starts returning each row exactly once, which is a change in what deployed clients receive from `GET /api/v1/policies` and `GET /api/v1/organizations/{id}/service-accounts`. | D10 OQ1 | Adopt. Design 5b withheld the `COLLATE "C"` and the `id` tiebreak only because it had no PostgreSQL to test against and said so; Design 10's Receipts 2–4 are that test, on the `postgres:16` image both `docker-compose.yml` and `tests/contract/` already use. §0 rule 3 records that the owner opened SQL for M11; this entry is where the specific queries are confirmed. **DDL is not part of the answer** — the `UNIQUE` index that would retire the `id` tiebreak is the schema track's (§1). | M11.3 | **Adopt** the SQL ordering fix exactly as stated — both `ORDER BY` changes and the in-memory sort key. DDL stays out; the `UNIQUE` index remains the schema track's. |

**Note on D-1: a release-coordination item, not a task gate.** D-1's answer is *yes* — deployment
artifacts outside this repository do name `huron.service.api.app:app` — and the rename proceeds
anyway. The code shape was never in question: Design 2's `create_app` cannot build an app without
settings, so `main.py` must exist and must be the module that reads the environment, and that is
settled inside the design. **M2 is implementable and buildable now**, and M2 edits the three in-repo
files (`Makefile:30`, `Containerfile` `CMD`, `docs/getting-started/local-development.md:131`). The
one outstanding item is the owner's: the external artifacts — Kubernetes manifest, Helm chart,
systemd unit or CI deploy job — are updated outside this tree **in the same release**, before that
release is deployed. That is a deploy-time coordination step. No code changes for it, no task waits
on it, and no milestone is held for it.

**D-10 is the one answer that departs from its recommendation.** Design 5b's Open question 2
recommended bounding the request and, absent a supplied number, shipping no bound at all rather than
inventing one. The owner supplied the number: **1 MiB**. Because the recommendation's conditional
never fired, this is a decision the design anticipated rather than a design change, and it needs no
return to `/design-plan`. It does need a mechanism, because `spec` is `dict[str, object]` and
Pydantic's `max_length` cannot express a byte ceiling over a decoded JSON object. **Task M7.3
specifies it in full** — where the check lives, what is measured, what the caller gets back, the
named constant, and the test that pins both sides of the boundary. M7.3 governs; do not re-derive
the mechanism from `API_DESIGN.md`.

**The grouped release, and why the breaks were accepted so readily.** Eight of the answers are
client-visible breaks — **D-3, D-4, D-5, D-6, D-7, D-12, D-16 and D-17** — and the owner's answer is
that they **ship as one release**, exactly as §4's R5 and each of those rows recommend. Worth
recording once, because a later reader will want it: **this repository contains no live consumer of
the API's response shapes.** `web/src/lib/api/client.ts` is a hand-written seam that reads from
`fixtures.ts`, and `web/src/lib/api/README.md` states that the real client is *generated* from
`openapi/v1.json` — a file that does not exist yet and first ships in P1. The sweep therefore lands
before the client that would have to be regenerated against it. That is a statement about this
repository, not a claim that no consumer exists anywhere: an external caller written against the
deployed surface would still see all eight breaks, which is why they ship together.

**How the sequence runs, now that nothing is gated.** M1 and M3.1 — the whole execution-model change
and the mechanical, contract-preserving half of the `repository.py` decomposition — break no client
contract and can be deployed alone if a partial deploy is ever needed (§4 R5). Everything from M3.2
onward carries part of the grouped release: M3.2 removes two keys from both release responses
(D-16), and M4.1 depends on M3.2, so M4 rides with it. M5 through M9 carry the rest, and M11.3's
ordering fix rides the same release because M11 is last. The sequencing constraint that remains is
therefore a **release** constraint — hold the release, never the milestones — and it is R5's, not a
decision's.

---

## 3. Milestone sequence

`API_DESIGN.md`'s `## Design Tasks` → `### Ordering` fixes the chain: 1 → 2 → 3 → 4 → 5 → 5b → 6 → 7,
with 8 free-floating. This plan follows it, splits Design 3 and Design 5 where the design itself
names the split, and lands Design 8 last because its type-check widening and Ruff `FAST` rules would
otherwise be enforced against code that six later milestones rewrite.

**Designs 9 and 10 stand outside that chain and land together as M11.** Neither is in `### Ordering`;
both were written against the tree the first ten milestones leave behind, and each says so — Design 9
enumerates the post-M10 contents of `authorization.py` name by name, and Design 10's package absorbs
Design 3's `ports.py` and `memory_rbac.py` and states its error table in Design 6's vocabulary. They
are one milestone rather than two because the second's package imports the first's, and because the
seventh import-linter contract names `huron.service.api.authorization.**` as a source module.

**No milestone is blocked.** The fourth column below used to read *Gated on*; every decision it
names was answered on 2026-09-01, so it now records **which settled decisions govern the milestone** —
the rows in §2 an implementer reads to know why the milestone's contract is what it is. It is not a
list of waits.

| # | Milestone | Design | Decisions that govern it (§2 — all settled) | Shape |
|---|---|---|---|---|
| **M1** | Execution model: blocking I/O off the event loop | Design 1 | D-2 — settled: limiter size 4 (task M1.2 only) | 2 tasks |
| **M2** | Composition root, `ApiRuntime`, injected dependencies, entrypoint module | Design 2 | D-1 — settled: rename proceeds. Buildable now; the owner's external-artifact update is a deploy-time step, not a gate | **1 task — atomic** |
| **M3** | `repository.py` decomposition and the record relocation | Design 3 | D-16 — settled: the two keys go (task M3.2) | 2 tasks |
| **M4** | Repository query methods, classification enforcement, release pinning | Design 3 | D-14 — settled: accept and pin (task M4.2); carries D-16's break via M4.1's dependency on M3.2 | 2 tasks |
| **M5** | Router composition and the authenticated surface | Design 4 | D-3, D-4, D-5 — all settled: accept | **1 task — atomic** |
| **M6** | Response models for the resource surface, and the pagination envelope | Design 5 | D-6, D-8 — settled: envelope break in full; `effective_roles` as designed | 3 tasks |
| **M7** | Response models for the administrative surface | Design 5b | D-6, D-7, D-9 — settled: accept; **D-10 — settled at 1 MiB, the one deviation, specified in M7.3** | 3 tasks |
| **M8** | Error contract and `problem+json` coverage | Design 6 | D-11 — settled: rename, plus a live `SESSION_EXPIRED` | 4 tasks |
| **M9** | Binding surface completion | Design 7 | D-12, D-13 — settled: narrow to SYSTEM; return lapsed grants | 2 tasks |
| **M10** | Type-check scope, entrypoint rationale, Ruff `FAST` | Design 8 | D-15 — settled: `["src/huron"]` (task M10.1) | 3 tasks |
| **M11** | The `authorization/` and `stores/` packages, and the ordering fix | Designs 9, 10 | D-17 — settled: adopt the ordering fix (task M11.3) | 4 tasks — **two atomic** |

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

**M11.1 and M11.2 are atomic in the same sense as M2.1 and M5.1**, and for a reason particular to
turning a module into a package: the moment `authorization.py` (or `postgres_rbac.py` and
`postgres_auth.py`) stops existing, every importer of it fails to import, and Python offers no state
between "the module" and "the package" that is neither a re-export shim nor a broken tree. A
half-moved package does not compile, so it cannot be a task boundary. What *is* separable is
everything that does not move a module: M11.3 changes three SQL statements and one sort key inside
the package M11.2 built, and M11.4 splits a test module and touches no source file at all.

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

**Status: done**

### Task M1.2 — Dedicated capacity limiter for password hashing — **capacity settled by D-2**

**Intent.** Bound Argon2id's memory and CPU blast radius to a queue on `/auth/login` instead of the
shared 40-token threadpool limiter.

**Design reference.** `## Design 1` → `### Open questions` question 1, and `### Explicit contracts`
(*"Threadpool and request concurrency"*).

**Modify.** The `verify_password` `asyncify` call site in `routes/auth/endpoints/login.py`; wherever
the limiter object is constructed (module level, alongside the call site).

**Depends on.** M1.1 alone — the call site must exist and the `limiter=` probe must have been run.
D-2 is settled in section 2: **the total is `4`**, on a limiter dedicated to password hashing.

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

**Status: done**

---

## M2 — Composition root, `ApiRuntime`, injected dependencies, entrypoint module

Design: `API_DESIGN.md` → `## Design 2 — Composition root, app.state, and injected dependencies`.
Also `## Design 8` → `#### 1. Entrypoint — uvicorn stays; no fastapi-cli, no [tool.fastapi] table`
for the entrypoint string, whose in-repo occurrence count Design 8's Open question 1 corrects to
three.

### Task M2.1 — Make the composition root total and typed — **one atomic task**

**Intent.** Remove every path by which a request can reach unset composition-root state, and replace
`Request`-threading with declared dependencies.

**D-1 is settled and this task is not waiting on it.** Deployment artifacts outside this repository
do name `huron.service.api.app:app`, and the rename to `huron.service.api.main:app` proceeds anyway.
**M2.1 is implementable and buildable today**; it edits the three in-repo references and nothing else
is owed to it. The one outstanding item is the owner's, and it is a deploy-time step: the external
artifacts are updated in the same release, before that release is deployed. Do not defer any part of
this task for it, and do not leave a compatibility alias at the old path — rule 2 forbids one.

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

**Status: done**

---

## M3 — `repository.py` decomposition and the record relocation

Design: `API_DESIGN.md` → `## Design 3 — repository.py decomposition and query ownership`. Design 3
itself authorises this split — *"relocation first (mechanical, contract-preserving), query methods
second"* — and M3/M4 take it. The "contract-preserving" half is **M3.1 alone**: M3.2's field
deletion is wire-visible, and D-16 settles it — the break is accepted and ships with the grouped
release (see §2).

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

**Status: done**

### Task M3.2 — Delete the dead repository symbols — **break settled by D-16**

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

**Status: done**

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

**Status: done**

### Task M4.2 — Enforce `classification_vocabulary`, and pin `create_release` — **settled by D-14**

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

**Depends on.** M4.1 alone. D-14 is settled in section 2: the route's unreachability until P2 is
accepted, and this task ships the test that pins it.

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

**Status: done**

---

## M5 — Router composition and the authenticated surface

Design: `API_DESIGN.md` → `## Design 4 — Router composition and the authenticated surface`.

### Task M5.1 — Rebuild the router tree and close the versioned surface — **one atomic task; contract settled by D-3, D-4, D-5**

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

**Status: done**

---

## M6 — Response models for the resource surface, and the pagination envelope

Design: `API_DESIGN.md` → `## Design 5 — Response models and the pagination envelope`. The envelope,
`PageLimit`/`PageCursor`, `paginate`, the `XView` naming rule and the `from_attributes` rule are
decided here and inherited unchanged by M7; M7 may not re-open any of them.

### Task M6.1 — The envelope, the precondition split, and the three paged hierarchy collections — **break settled by D-6**

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

**Status: done**

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

**Status: done**

### Task M6.3 — The unversioned surface, and `effective_roles` — **shape settled by D-8**

**Intent.** Model the unversioned responses and close Drift 8 by shipping effective roles per scope
on `GET /auth/session`.

**Design reference.** `## Design 5` → `#### The unversioned surface, and Drift 8`,
`#### Secret-bearing responses`, `### Open questions` question 1.

**Create.** `ScopeRoles`; `LoginResult` and any remaining unversioned response models, in
`routes/auth/schema/`.

**Modify.** `routes/auth/schema/session.py` (`SessionInfo` gains
`effective_roles: list[ScopeRoles]`); `routes/auth/endpoints/session.py`, `login.py`, `oidc.py`.

**Depends on.** M6.1 alone (the naming and `from_attributes` rules). D-8 is settled in section 2:
`effective_roles` ships as designed, with no `?scopes=` filter.

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

**Status: done**

---

## M7 — Response models for the administrative surface

Design: `API_DESIGN.md` → `## Design 5b — Response models for the administrative surface`, and
`## Design 5` → `### The split — brief for Design 5b`, which fixes what 5b inherits and may not
re-open.

### Task M7.1 — `roles` and `bindings` — **breaks settled by D-6, D-7, D-9**

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

**Status: done**

### Task M7.2 — `service_accounts` and `api_keys`, and the two secret-bearing responses — **break settled by D-6**

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

**Status: done**

### Task M7.3 — `policies` and `users` — **settled by D-6; `spec` ceiling settled by D-10**

**Intent.** Model the last two administrative modules, and stop `GET /users` publishing
`idp_subject`.

**Design reference.** `## Design 5b` → `#### Decision 3 — PolicyView.spec is returned everywhere
PolicyView is`, `#### Users, and the second over-published field`, `#### The handlers`,
`### Deletions`, `### Open questions` question 2 (the `spec` size bound).

**Create.** `PolicyView`, `PolicyAttachmentView`, `UserView`, `PasswordReset` in their schema modules.
In `routes/v1/schema/policies.py`: the module-level constant `MAX_POLICY_SPEC_BYTES = 1_048_576` and
the `field_validator` on `CreatePolicy.spec` that enforces it (the D-10 sub-item below).

**Modify.** `routes/v1/endpoints/policies.py`, `routes/v1/endpoints/users.py`,
`routes/v1/schema/policies.py` (`CreatePolicy` gains the validator; `AttachPolicy` is untouched).

**Delete.** `GET /policies`'s `{"items": [...]}` envelope; four `jsonable(...)` returns in
`policies.py`; the `_actor: CurrentPrincipal` parameter at `policies.py:40` if M5 has not already
removed it; two `jsonable(principal)` returns in `users.py`; the `{"status": "password-reset"}` dict
literal; the eight remaining `-> dict[...]` annotations across both modules.

**Depends on.** M7.2 alone.

#### The `CreatePolicy.spec` byte ceiling — D-10, settled at 1 MiB

D-10 is answered: **`CreatePolicy.spec` is bounded at 1 MiB**. This is the one settled answer that
departs from its recommendation — Design 5b's Open question 2 said to ship no bound if no number was
supplied, and a number was supplied — so this sub-item, not `API_DESIGN.md`, is the specification.
It is the only request-body change either half of task 5 makes.

**Where.** A `@field_validator("spec")` on `CreatePolicy` in `routes/v1/schema/policies.py`, so the
bound is applied to the request before anything is stored. Design 5b Decision 3 rests on this being a
write-side bound — `PolicyView.spec` is returned in full on both `POST /policies` and `GET /policies`
and gains no bound of its own, and the response side stays governed by `limit ≤ 200`.

**What is measured.** `len(canonical_bytes(spec))`, using
`huron.pkg.catalog.manifest.canonical_bytes` — the repository's existing RFC 8785 (JCS)
canonicalization, built on the already-declared `rfc8785` dependency and the same function
`content_identity` uses. Its signature is `canonical_bytes(doc: Mapping[str, object]) -> bytes`, which
takes `spec: dict[str, object]` unchanged, with no conversion and no cast. Reusing it keeps **one**
definition of "how many bytes is this document" in the codebase; a `json.dumps(...).encode()` would
introduce a second one whose answer moves with separator and key-ordering arguments, so that the same
document could be under the ceiling in one module and over it in another. `canonical_bytes` also
calls `_assert_ints_safe`, which raises `ValueError` for an integer outside the JCS safe range — do
**not** catch it: inside a `field_validator` Pydantic already converts a `ValueError` into a
validation error, so a spec that cannot be canonicalized lands on the same 422 path as one that is
too large, rather than escaping as a 500.

**The import is legal under the import-linter contracts**, checked rather than assumed. The layers
contract is `huron.service` → `huron.pkg` → `huron.schema`, so a `routes/v1/schema/` module importing
from `huron.pkg.catalog` runs with the layering, not against it; route modules already do exactly
this (`endpoints/users.py` imports from `huron.pkg.auth` and `huron.pkg.catalog.errors`). The
independence and framework-free contracts name only `huron.pkg.*` modules as sources and constrain
what `pkg` may import, never what imports `pkg`. Neither contract M11 adds names anything under
`routes/`. Nothing changes in `pyproject.toml` for this.

**What the caller gets.** A `field_validator` rejection on a request body raises inside FastAPI's
body parsing and surfaces as a **`RequestValidationError` → `422`** — the existing validation path,
**not** a new `DomainError`. Confirmed against Design 6's handler table rather than assumed: Design 6
maps `RequestValidationError` to `422 application/problem+json` with the five required keys plus
`context.errors` carrying the encoded pydantic error list, under the code `REQUEST_INVALID` ("the
request did not satisfy the declared schema"). No new error code, no new row in `design/api.html`
§7, and nothing added to M8.1's conversion table or M8.3's bijection test. Because M7.3 lands before
M8, the rejection is FastAPI's own `422 application/json` when this task ships and becomes
`problem+json` with every other `RequestValidationError` when M8.1 and M8.4 land; that is M8's
conversion, not a second contract.

**The constant.** `MAX_POLICY_SPEC_BYTES = 1_048_576`, module-level in
`routes/v1/schema/policies.py`, written as `1_048_576` and never as a bare literal inside the
validator. The validator reads the constant; the tests read the same constant, so the two cannot
drift.

**Acceptance criteria for this sub-item.**

- `grep -rn 'MAX_POLICY_SPEC_BYTES' src/huron` returns exactly one assignment, and its value is
  `1_048_576`.
- `POST /api/v1/policies` with a `spec` whose canonical form is exactly `MAX_POLICY_SPEC_BYTES`
  bytes is **accepted**; the same spec grown by one byte is **rejected with 422**. Both tests build
  their body from one shared construction so the boundary is exact rather than approximate, and both
  assert against `len(canonical_bytes(spec))` rather than against a hand-counted size.
- The validator is on `CreatePolicy` only. `PolicyView.spec`, `AttachPolicy` and every read path are
  unbounded and unchanged; `grep -rn 'field_validator' src/huron/service/api/routes/v1/schema/policies.py`
  returns one decorator.
- `uv run lint-imports` keeps every contract with the new `huron.pkg.catalog.manifest` import in
  place.

**Verify.**

```text
grep -rn 'idp_subject' src/huron/service/api/routes/
grep -rn -- '-> dict\[str, ' src/huron/service/api/routes/
grep -rn 'MAX_POLICY_SPEC_BYTES\|canonical_bytes' src/huron/service/api/
uv run lint-imports
uv run pytest -m unit -q
<full validation gate>
```

**Acceptance criteria.**

- `UserView` declares exactly `id`, `subject`, `display_name`, `disabled_at`, `created_at` and omits
  `idp_subject` and `kind`; a test asserts the exact key set of a user response, and `idp_subject`
  appears nowhere under `routes/`.
- `PrincipalRecord.idp_subject` still exists in `pkg` — the OIDC login path writes it and
  `postgres_auth` reads it. Nothing in `pkg` is deleted by this task.
- `GET /policies` returns `Page[PolicyView]` keyed on `(name, str(id))`; `PolicyView.spec` stays
  `dict[str, object]` and stays unbounded — the ceiling is on the request alone.
- The D-10 sub-item above is complete, with its four acceptance criteria met.
- `PUT /users/{id}/password` returns a `PasswordReset` model with a `Literal`, matching `SignOut`.
- **After this task, `grep -rn -- '-> dict\[str, ' src/huron/service/api/routes/` returns nothing at
  all** — the only two surviving `-> dict[str, str]` handlers in the tier are `/healthz` and
  `/readyz`, which live in `app.py` — and no route in the tier imports `jsonable` — the precondition for
  `records.jsonable`'s docstring becoming persistence-only. Update that docstring here if M6 has not.
- Full validation gate clean.

**Status: done** — landed with a folded-in fix for `search.py` (`response_model=None`/`-> NoReturn`
  per `API_DESIGN.md`'s Design 5), since no task in this plan's Create/Modify/Delete lists ever
  assigned that file's fix even though this task carries the tier-wide `-> dict[str, ` acceptance
  criterion. Recorded as a plan-decomposition gap, not an M7.3 defect.

---

## M8 — Error contract and `problem+json` coverage

Design: `API_DESIGN.md` → `## Design 6 — Error contract and problem+json coverage`.

### Task M8.1 — `DomainError` becomes abstract, and the fourteen bare raises get names — **atomic; code names settled by D-11**

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

**Status: done** — the duplicate-slug status is `409` (Design 6's actual `SlugExists` class and code
  table), not the `400` this criterion's prose states; `400` was the deleted `DomainError` base's old
  default, carried into the prose by mistake. Design 6's `code: ClassVar[str]` on `DomainError` is also
  incompatible with the pre-existing `PathRuleViolation` (proven: `mypy --strict` rejects it); `code` is
  a plain annotation instead, with abstractness enforced by the `TypeError` in `__init__`. Both recorded
  as design/plan imprecisions, not implementation defects. **Residual risk carried into M8.3:**
  `PathRuleViolation`'s six per-instance codes (`PATH_OUTSIDE_PAYLOAD`, `PATH_NOT_NFC`, `PATH_TOO_LONG`,
  `PATH_TRAVERSAL`, `PATH_CONTROL_CHARS`, `PATH_SEPARATOR`, all reachable on the wire from
  `manifest.py`) are invisible to `wire_error_codes()`, which reads only `cls.__dict__["code"]`. M8.3's
  bijection test will pass green comparing `PATH_RULE_VIOLATION` on both sides while these six
  undocumented codes stay emittable — the exact defect Design 6 exists to catch. M8.3 must account for
  this explicitly rather than trust a green bijection result at face value.

  **Correction recorded 2026-09-02, discovered by M10.1's verification:** this task's acceptance
  criterion "`DOMAIN_ERROR` and `ROLE_VIOLATION` appear nowhere in `src/huron`" was **not actually met**
  when this status was first set to done. `pkg/rbac/roles.py`'s `RoleError` retained its base-class
  default `code = "ROLE_VIOLATION"` — the Deletions list called for removing it, but it survived. Two
  tests (`test_api_problems.py::test_wire_error_codes_excludes_the_retired_dispatch_codes`,
  `test_error_contract.py::test_every_documented_code_has_a_class_and_every_class_has_a_row`) were red
  for this reason from M8.1 through M9 without being caught, because `src/huron/service` was outside
  the gate's type-check scope and no other check re-derived this specific criterion. M10.1 removed the
  stale default while fixing an unrelated `mypy`/`ty` finding on the same class, which incidentally
  closed this gap; M10.1's verification confirmed by mutation-restoring the old default that both tests
  go red without the fix. No further action needed — recorded here because a milestone was marked done
  with one of its own stated criteria silently unmet, which is worth knowing if this plan's process is
  revisited.

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

**Status: done**

### Task M8.3 — The `design/api.html` §7 table and the bijection test — **code names settled by D-11**

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

**Status: done** — closed the M8.1 residual risk (`PathRuleViolation`'s six per-instance codes were
  invisible to `wire_error_codes()`'s class-attribute walk): `problems.py` gained
  `_path_rule_violation_codes()`, which derives the codes from `manifest.py`'s actual
  `PathRuleViolation(...)` call sites via `ast`, so a future call site surfaces automatically instead
  of needing a parallel hand-maintained list. §7 now has 65 rows (46 live `DomainError` + 6 `AuthError`
  + 3 `RoleError` + framework/derived), verified row-by-row against the current tree — two things
  Design 6's own table got wrong here were corrected: `BAD_REQUEST` was missing entirely, and the
  reserved-catalog count is 19, not 18. **Note for the record:** `make docs`'s strict build does not
  actually exercise `design/api.html` — `zensical.toml`'s nav covers only `docs/`, so this acceptance
  criterion is satisfied but vacuous; the real protection against malformed §7 markup is
  `test_error_contract.py`'s `HTMLParser`-based parse, not the docs build.

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

**Status: done — Milestone 8 complete.** Two undocumented, non-blocking gaps recorded for whoever next
  touches Design 6 or `problems.py`: `ClassificationUnknown` (400, from `create_project`) is reachable
  from `POST .../projects` but falls outside Design 6's closed per-operation enumeration, so it carries
  no `responses=` entry; `/healthz`/`/readyz` are registered directly on `app` rather than under either
  router, so neither documents 422/500 the way every `/api/v1` and `/auth` operation does (harmless —
  neither takes a request parameter).

---

## M9 — Binding surface completion

Design: `API_DESIGN.md` → `## Design 7 — Binding surface completion`.

### Task M9.1 — Scope-rooted revoke, and the end of the `type: ignore` cluster — **break settled by D-12**

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

**Status: done**

### Task M9.2 — The two missing binding collections — **expiry semantics settled by D-13**

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

**Status: done — Milestone 9 complete.**

---

## M10 — Type-check scope, entrypoint rationale, Ruff `FAST`

Design: `API_DESIGN.md` → `## Design 8 — Entrypoint, ORM, frontend serving, and type-check scope`.
Landed last on purpose: widening the type gate and enabling new lint rules against code that M2–M9
rewrite would mean fixing the same errors twice.

### Task M10.1 — `src/huron/service` joins `mypy --strict` and `ty` — **scope settled by D-15**

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

**Status: done** — the widened scope surfaced and fixed five genuine type errors (a `RoleError.code`
  `ClassVar` declaration, an explicit `Layer` conversion at a service boundary, a parameter narrowing in
  `_write_generation`, a variable rename in `authorization.py`, and an unsound `app.openapi` monkeypatch
  replaced with a proper `FastAPI` subclass) — none behavior-changing. Also closed the M8.1
  `ROLE_VIOLATION` gap recorded above.

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

**Status: done** — zero-code-change enablement, confirmed genuinely live (not inert) via a scratch-file
  triple-violation probe. Note for whoever next edits Design 8 §5: `FAST` at the pinned Ruff version is
  three rules, not the two the design record discusses — `FAST003` (unused path parameter) is also
  enforced and currently passes, but the design gives no rationale for it.

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

**Status: done — Milestone 10 complete.**

---

## M11 — The `authorization/` and `stores/` packages, and the ordering fix

Design: `API_DESIGN.md` → ``## Design 9 — `authorization.py` decomposition`` and
`## Design 10 — Store adapter layout and query ownership`. Neither design is in `### Ordering`; both
are written against the tree M1–M10 leave behind and say so, which is why they land last and
together. M11 is also where §0 rule 3's SQL prohibition lifts — **for queries, in M11.3, and nowhere
else**: no task here writes DDL, and no task here edits `migrations/` or `src/huron/schema`.

### Task M11.1 — Turn `authorization.py` into the `authorization/` package — **one atomic task**

**Intent.** Give each of the five concerns fused in one module — the cookies this service issues,
the credential path, scope resolution, the binding decision, and the guards a route declares — one
home with one contract, behind a public surface a route cannot reach past.

**This task is atomic.** The moment `authorization.py` stops existing, every importer of it fails at
import time; there is no state between "the module" and "the package" that is not either a
re-export shim (rule 2 forbids it) or a tree that does not compile. The cookie change is part of the
same instant: `set_session_cookie` and its three siblings are deleted as `CookieSpec` arrives, and
the two `/auth` endpoint modules move with them.

**Design reference.** ``## Design 9 — `authorization.py` decomposition`` → `#### Layout`, the five
`#### authorization/*.py` blocks, `#### authorization/__init__.py`,
`#### Import direction inside the package`, `#### Import-linter: one new contract`,
`### Explicit contracts` (per-module guarantees and `#### The package boundary`), and
`### Deletions`.

**Create.** `src/huron/service/api/authorization/__init__.py` (re-exports only, `__all__` exactly
Design 9's nineteen names); `cookies.py` (`CookieSpec`, `session_cookie`, `login_flow_cookie`, the
module-private `LOGIN_FLOW_MAX_AGE`); `credentials.py` (`current_principal`, `CurrentPrincipal`,
`current_session`, `CurrentSession`, `_touch_api_key`, `_enforce_csrf`); `scopes.py` (the three
scope resolvers, bodies unchanged); `decisions.py` (`BindingCacheMap`, `request_binding_cache`,
`BindingCache`, `as_rbac_principal`, `_cached_bindings_for`, `bindings_for_principal`, `check`);
`guards.py` (the four `require_*` factories, `LayerWrite`, `dataset_layer_writer`).

**Modify.** `pyproject.toml` — the **sixth** import-linter contract, verbatim from
`#### Import-linter: one new contract`, including `allow_indirect_imports = true`, which is
load-bearing and not decoration: without it every legitimate package-level import reports as a
violation. `routes/auth/endpoints/login.py` and `routes/auth/endpoints/oidc.py` (the cookie call
sites, which change beyond their import line: `session_cookie(settings).issue(...)`,
`flow = login_flow_cookie(settings)` and `flow.read(request) or ""`);
`routes/auth/endpoints/session.py`, `routes/v1/endpoints/{organizations,projects,policies,datasets,users}.py`
and the three modules M5.1 split `endpoints/rbac.py` into (import path only);
`tests/unit/test_repository_rbac.py` (`:25`'s `cached_bindings_for` import and the two direct-call
tests at `:376-389`, which drive `bindings_for_principal` — it memoizes through the same dict — plus
the module docstring at `:3` and the in-test `_touch_api_key` import at `:338`, which follows the
symbol to `authorization.credentials`); `tests/unit/test_api_authorization.py` (the retired cookie
names only; the four-way split is M11.4 and does not belong in an atomic move);
`docs/getting-started/repository-layout.md:25`, whose tree diagram names `authorization.py` as a
file — that one line becomes `authorization/`, keeping its one-line gloss. **That doc edit is an
explicit carve-out from §1's "Documentation reconciliation" non-goal**, on D-1's precedent (which
carves out `docs/getting-started/local-development.md:131` the same way): the non-goal defers
reconciling documentation that is *already* stale, not correcting the single line this task itself
falsifies — and leaving it stale hands M11.2 a red `docs/` grep with no permitted fix.

**Delete.** `src/huron/service/api/authorization.py`, the file, in full — nothing stands at the old
path. By symbol: `set_session_cookie`, `clear_session_cookie`, `set_login_flow_cookie`,
`clear_login_flow_cookie`, `LOGIN_FLOW_COOKIE_NAME` and `LOGIN_FLOW_COOKIE_MAX_AGE` (six names
become three: two constructors and one frozen `CookieSpec`); `cached_bindings_for` as a public name.
No `pyproject.toml` deletion: the `TC00*` per-file ignore is a recursive glob that already covers the
package, and the `N818` entry for this file went with `Forbidden` at M8.1.

**The design's `__init__.py` snippet is internally consistent — transcribe it, do not adjust it.**
`#### authorization/__init__.py` imports `CurrentPrincipal, CurrentSession, current_principal` from
`.credentials`, and every name on every one of its import lines is among the nineteen in `__all__`.
There is nothing to prune and nothing to add: the implementer imports exactly the nineteen names the
snippet exports, `CurrentSession` among them. `current_session` is an implementation detail of
`credentials.py` — no `__init__.py` line names it and no route declares it — so it is neither a
twentieth export nor a missing one. Dropping `CurrentSession` in the belief that it is an unused
import would raise Ruff `F822` and break every route that declares it.

**Depends on.** **M8.1** — the last task that edits `authorization.py`'s contents (it deletes
`Forbidden`), and the tree Design 9 enumerates as its starting point is exactly the post-M8.1 one.
Through M8.1 this inherits **M2.1** (which adds `BindingCache`, `current_session` and the `cache`
/`repository` parameters this design moves unchanged) and **M5.1** (which produces the three
`endpoints/rbac.py` successors named in the import-line edits). **Not M9** — Design 7 adds no symbol
to this module — and **not M10**, though because M11 runs after M10.1 the new package is covered by
`uv run mypy` through the gate rather than by the by-hand `--strict` step earlier tasks carry.

**Verify.**

```text
test ! -e src/huron/service/api/authorization.py && ls src/huron/service/api/authorization/
uv run python -c "import huron.service.api.authorization as a; print(len(a.__all__), sorted(a.__all__))"
grep -rn 'authorization\.\(cookies\|credentials\|scopes\|decisions\|guards\)' src/
grep -rn 'authorization\.py' src/ tests/ docs/ Makefile
grep -rn 'set_session_cookie\|clear_session_cookie\|set_login_flow_cookie\|clear_login_flow_cookie\|LOGIN_FLOW_COOKIE_NAME\|LOGIN_FLOW_COOKIE_MAX_AGE\|cached_bindings_for' src/ tests/
grep -rn --include='*.py' 'set_cookie\|delete_cookie' src/huron/service/api/
uv run lint-imports
uv run pytest -m unit -q
<full validation gate>
```

**Acceptance criteria.**

- `authorization.py` does not exist; the package holds exactly the six files above.
- `len(a.__all__) == 19` and the list is Design 9's, name for name.
- The submodule grep returns nothing outside `src/huron/service/api/authorization/` itself: no route
  module, and no other module in the tier, names a submodule.
- `uv run lint-imports` reports **six** contracts kept, the new one by name. The contract is proven
  to bite: adding a single `from huron.service.api.authorization.guards import require_system` to a
  route module makes `lint-imports` fail, and the line is reverted. A contract nobody has seen fail
  is a contract nobody knows is wired.
- The six retired cookie names appear nowhere in `src/` or `tests/`, and `set_cookie`/`delete_cookie`
  appear only in `authorization/cookies.py` — one object owns each cookie's name, path and flags, so
  a clearing response cannot disagree with the response that set it.
- The four `Set-Cookie` headers are byte-identical to today's under both `secure` settings, pinned by
  a unit test over login, logout and the two OIDC legs rather than by inspection.
- `tests/unit/test_repository_rbac.py` no longer imports `cached_bindings_for`; per-request
  memoization is still pinned, through `bindings_for_principal`.
- `grep -rn 'authorization\.py' src/ tests/ docs/ Makefile` returns nothing: no import, no test and
  no line of prose still points at a file that no longer exists.
- **No `-m contract` run is required for this task**, and this is deliberate: it moves no Protocol
  and no implementation of one. `ApiKeyWriter` is still `ports.py`'s until M11.2, which does carry
  the mandatory contract step.
- No new module docstring, comment or test name references this plan, a milestone, a task number or
  `API_DESIGN.md` (§0 rule 1). The five module docstrings state the guarantee the module makes.
- Full validation gate clean.

**Status: done** — an accidental `git checkout --` on `organizations.py` mid-task (this repo carries no
  commits over its ~10-milestone working tree, so the command silently restored a pre-M2/M5 relic
  instead of undoing a two-line edit) was caught, disclosed, and the file reconstructed by hand from
  sibling modules and the repository/schema ground truth. Verification independently confirmed the
  reconstruction behaviorally sound on six axes, including 40+ matched `TestClient` scenarios against
  `projects.py`. **No `git checkout --`/`git reset --hard` on any path is safe for the remainder of this
  plan** — undo edits by hand.

### Task M11.2 — Move the five storage adapters into `stores/`, organized by port — **one atomic task**

**Intent.** Put every implementation of a port in one module with the port, so the next divergence
between two implementations of one interface is a diff on adjacent screens instead of an incident,
and so no adapter can import the application service by accident again.

**This task is atomic**, for M11.1's reason at larger scale: `postgres_rbac.py`, `postgres_auth.py`,
`ports.py` and `memory_rbac.py` are deleted and their contents redistributed in the same instant.
`repository.py`, `app.py`, `authorization/credentials.py` and both `tests/contract/` modules import
from them, and a half-moved package leaves the tree red.

**Design reference.** `## Design 10 — Store adapter layout and query ownership` → `#### Layout`,
`#### By port, not by backend — and why the choice is narrower than it looks`,
`#### stores/ports.py`, `#### stores/rows.py`,
`#### stores/__init__.py`, `#### The import lines that change`,
`#### Import-linter: one new contract`, `### Explicit contracts` (`#### The package`,
`#### ports.py`, `#### Error behavior, per store, after Design 6`, and `#### tests/contract/` item
4), and `### Deletions`. **`#### Half B — the concrete SQL` is not this task's** — it is M11.3's.

**Create.** `src/huron/service/api/stores/__init__.py` (re-exports only, `__all__` exactly the eight
names; `rows` is **not** re-exported); `ports.py` (`RbacStore`, `ApiKeyWriter`, body verbatim from
Design 3's `ports.py`); `rows.py` (the seven row mappers, losing their leading underscore because
they now cross a module boundary, plus one `affected_row_count`); `rbac.py` (`InMemoryRbacStore` and
`PostgresRbacStore`, ~490 lines, both implementations of one port in one module); `api_keys.py`;
`credentials.py`; `sessions.py`; `principals.py`.

**Modify.** `pyproject.toml` — the **seventh** import-linter contract, verbatim from the design,
`allow_indirect_imports = true` again load-bearing. `src/huron/service/api/repository.py` (one import
line replaces Design 3's two); `src/huron/service/api/authorization/credentials.py`
(`from ..stores import ApiKeyWriter`); `src/huron/service/api/app.py` (the two Postgres import blocks
in `_postgres_repository` become one); `tests/contract/test_rbac_store.py:63`;
`tests/contract/test_auth_store.py:48`; `tests/unit/test_repository_rbac.py`;
`tests/unit/test_api_postgres_auth_mapping.py`, whose subject is the row mappers themselves — it
imports `_affected_row_count`, `_credential_record_from_row`, `_principal_record_from_row` and
`_session_record_from_row` by their private names, which become the public names in
`huron.service.api.stores.rows`. That test imports the submodule directly and this is correct: the
seventh contract's `source_modules` are `repository`, `app`, `authorization.**` and `routes.**`, and
a test that pins a row mapper is the one caller that legitimately decodes a `Record` it staged.
Finally `docs/getting-started/repository-layout.md:27`, whose tree diagram names `postgres_rbac.py`:
that line becomes `stores/`, one gloss for the package that now owns both backends. Same explicit §1
carve-out and the same reason as M11.1's — this task's own `docs/` grep below returns that line
otherwise, and under the non-goal no later task would be permitted to clear it.

**Delete.** `src/huron/service/api/postgres_rbac.py`, `postgres_auth.py`, `ports.py` and
`memory_rbac.py` — all four entire, none replaced by a re-export. By symbol:
`postgres_rbac.py:450`'s hand-written `int(tag.rsplit(" ", 1)[-1])`, the second copy of what
`rows.affected_row_count` now defines once; the leading underscores on all seven row mappers.
`records.py` is **not** moved in — three unrelated consumers depend on it, and putting it inside the
package would make every route module import `stores`.

**Depends on.** **M3.1**, which creates `ports.py` and `memory_rbac.py` (this task absorbs both) and
`records.py` (which `rows.py` imports); **M8.1**, because Design 10 states this package's error table
in Design 6's vocabulary — `BindingExists`, `ServiceAccountExists`, `AttachmentExists`,
`PrincipalSubjectExists` from `errors.py` — and moving raise sites and renaming them in one task
would be two changes wearing one diff; and **M11.1**, because the seventh contract names
`huron.service.api.authorization.**` as a source module, a package that exists only after M11.1.

**Verify.**

```text
test ! -e src/huron/service/api/postgres_rbac.py && test ! -e src/huron/service/api/postgres_auth.py
test ! -e src/huron/service/api/ports.py && test ! -e src/huron/service/api/memory_rbac.py
ls src/huron/service/api/stores/
uv run python -c "import huron.service.api.stores as s; print(len(s.__all__), sorted(s.__all__))"
uv run python -c "from huron.service.api.stores import api_keys, ports, rbac; print(ports.RbacStore not in rbac.PostgresRbacStore.__mro__, ports.RbacStore not in rbac.InMemoryRbacStore.__mro__, ports.ApiKeyWriter not in api_keys.PostgresApiKeyStore.__mro__)"
grep -rn 'rsplit' src/huron/service/api/stores/
grep -rn 'postgres_rbac\|postgres_auth\|memory_rbac\|api import ports\|api\.ports' src/ tests/ docs/ Makefile
grep -rn 'stores\.rows\|from \.rows\|from \.\.stores\.' src/
uv run lint-imports
uv run pytest -m unit -q
uv run pytest -m contract -q
<full validation gate>
```

**Acceptance criteria.**

- The four old modules do not exist; `stores/` holds exactly the eight files above;
  `len(s.__all__) == 8` and `rows` is not among them.
- The three-way conformance probe prints `True True True`, and the same assertion lands in
  `tests/contract/` (Design 10's `#### tests/contract/` item 4) rather than only in this verify
  block — the Protocols and two of their implementations now share a package, and inheritance became
  a one-line temptation that would end structural conformance.
- `grep -rn 'rsplit' src/huron/service/api/stores/` returns exactly one line, in `rows.py`: one
  definition of the command-tag parse, two callers.
- Inside `src/`, `rows` is imported only by the store modules that own the SELECTs it decodes.
- The `postgres_rbac\|postgres_auth\|memory_rbac\|api import ports\|api\.ports` grep over
  `src/ tests/ docs/ Makefile` returns nothing, `docs/` included — the carve-out above is what makes
  that last directory clearable rather than a permanently red step.
- **No SQL text changes in this task.** A `git diff` of the moved store bodies shows changed import
  lines, the row-mapper renames and the two `affected_row_count` call sites, and nothing inside any
  SQL string literal. The ordering fix is M11.3, separated so this move is reviewable as a move.
- The per-store error table in `### Explicit contracts` holds unchanged after the move: each named
  error is still raised by the same method on the same `asyncpg` exception class, and the memory
  store still raises the same class for the same input wherever it has the operation.
- `uv run lint-imports` reports **seven** contracts kept. The seventh is proven to bite the same way
  the sixth was: a direct `from huron.service.api.stores.rbac import PostgresRbacStore` in `app.py`
  fails the check and is reverted.
- `uv run pytest -m contract` passes, and is **mandatory**: this task moves both Protocols and all
  five implementations, and `tests/contract/` is the only proof both backends still conform — the
  gate's pytest line runs `-m unit` only. It needs the container runtime named under §0's
  **Environment prerequisites**; if the host has none, stop and report rather than declaring the task
  done with the step unrun.
- No module docstring, comment or test name references this plan, a milestone or `API_DESIGN.md`
  (§0 rule 1).
- Full validation gate clean.

**Status: done** — verified across two passes. Attempt 1 confirmed all fifteen acceptance criteria against
  the live tree (file layout, `__all__`, the three-way structural-conformance probe pinned in
  `tests/contract/` and mutation-killed, the single `rsplit` in `rows.py`, `rows`'s importer set, no SQL
  text changed — 30 literals byte-identical across all 34 method bodies, the two ordering defects
  correctly left untouched for M11.3, the per-store error table, the seventh import-linter contract
  proven to bite by an independent violation, the mandatory `pytest -m contract` run, and the
  `credentials.py`/`records.py` package-boundary reasoning) and flagged two non-blocking hygiene gaps:
  a stale `docs/getting-started/repository-layout.md` gloss (predated this task, cleared under this
  task's carve-out) and two contract test names whose prose incidentally contained
  `postgres_rbac`/`postgres_auth` as substrings. Both were fixed and attempt 2 confirmed the fixes
  precisely, with no collateral change, and a fully clean gate. The `postgres_rbac` substring
  necessarily survives in the second test's new name (`test_the_postgres_rbac_and_api_key_stores_...`)
  since the rename only added a prefix; both verification passes judged this inert prose, not a live
  reference — the four deleted module paths (`postgres_rbac.py`, `postgres_auth.py`, `ports.py`,
  `memory_rbac.py`) are unreachable from anywhere in the tree.

### Task M11.3 — Make the store order the order the cursor assumes — **SQL change settled by D-17**

**Intent.** Fix the two ordering defects in the SQL that produces them, so that walking a keyset
cursor over a collection returns every row exactly once on the cluster this service actually deploys
against.

**This is the one task in the plan that changes shipped SQL**, and the only one with a runtime
contract to pin rather than a module boundary to move. §0 rule 3 opens SQL for M11 and for M11 only;
D-17 is where the specific queries are confirmed. The opening does not extend to DDL: the `UNIQUE`
index that would retire the `id` tiebreak is handed to the 0008 schema track (§1) and does not gate
this task.

**Design reference.** `## Design 10` → `#### Half B — the concrete SQL`, `### Explicit contracts` →
`#### The ordering contract, per collection` and `#### tests/contract/` items 1–3, and
`### Open questions` item 1.

**Modify.** `src/huron/service/api/stores/rbac.py` — `PostgresRbacStore.list_policies` becomes
`ORDER BY name COLLATE "C", id`; `PostgresRbacStore.list_service_accounts` becomes
`ORDER BY sa.name COLLATE "C"` with **no** tiebreak, because
`service_accounts_organization_id_name_key` makes `name` unique within the one organization the
`WHERE` fixes; `InMemoryRbacStore.list_policies` sorts by `(item.name, str(item.id))` — `str(item.id)`
so the expression reads identically to the boundary's key — and its docstring states the order.
`tests/contract/test_rbac_store.py` — the three assertions below.

**Delete.** Nothing. `bindings_at` is already correct
(`ORDER BY principal COLLATE "C", role_code COLLATE "C"`, total under
`role_bindings_no_duplicates`) and gains no tiebreak: a redundant one would suggest the uniqueness is
in doubt. `InMemoryRbacStore.list_service_accounts` and `bindings_at` already match their SQL and do
not change.

**Depends on.** **M11.2** — both implementations of `list_policies` must be in one module before the
"same sequence from both backends" assertion is a diff rather than a two-file comparison, which is
the arrangement that produced the defect. **M7.3**, **M7.2** and **M7.1**, which introduce the three
boundary keys this task must agree with: `(name, str(id))` for policies, `(name,)` for service
accounts, and `(principal, role_code)` for bindings — the third collection acceptance criterion 1
pins alongside the other two. **D-17 is settled in §2** — adopt, exactly these three statements, and
no DDL — which is what makes this task's SQL change sanctioned rather than a rule 3 violation.

**Verify.**

```text
grep -rn 'ORDER BY' src/huron/service/api/stores/
grep -rn 'COLLATE' src/huron/service/api/stores/
grep -rni 'create index\|create unique\|alter table\|drop \|create table' src/huron/service/api/stores/
git diff --stat -- migrations/ src/huron/schema/
uv run pytest -m contract -q
uv run pytest -m unit -q
<full validation gate>
```

**Acceptance criteria.**

- Three `ORDER BY` clauses in the package, and **every text component of every one of them carries
  `COLLATE "C"`.** This is correctness, not style: `COLLATE "C"` is byte order, which is exactly
  Python's `str` comparison, and the database default this service deploys against folds case and
  ignores punctuation at the primary level.
- The DDL grep returns nothing and `git diff --stat -- migrations/ src/huron/schema/` is empty — the
  M11 boundary of §0 rule 3, checked rather than asserted.
- `tests/contract/` gains and passes the three pins, each of which **fails when its fix is reverted**
  — reverted once by hand per SQL change, so that neither the `COLLATE "C"` nor the `id` tiebreak can
  be deleted later as decoration: (1) the ordering agreement, for all three collections, seeded
  identically into `InMemoryRbacStore` and `PostgresRbacStore`, asserting both return the same
  sequence and that it equals `sorted(records, key=<the boundary key>)`; (2) the collation is byte
  order, over names differing only in case, in a hyphen and in an accent; (3) the duplicate-name walk
  — three policies, two sharing a name, walked at `limit=1` to `next_cursor is None`, every row
  exactly once.
- `uv run pytest -m contract` passes and is **mandatory**: it is the only proof both backends order
  alike, and it is where the deployed collation is exercised. It needs the container runtime named
  under §0's **Environment prerequisites**; stop and report if the host has none.
- No store method gained a `limit` or an `after` parameter and no `WHERE` predicate changed — this is
  not the push-down (§1), and `git diff` touches no file under `routes/`: no response model, cursor
  format or envelope moves with it. That is D-17's blast radius, and it is bounded to what clients
  receive from two collections, not to how they ask for it.
- No comment, docstring or test name references this plan, a milestone or `API_DESIGN.md` (§0 rule
  1); the new tests are named for the ordering property they pin.
- Full validation gate clean.

**Status: done** — verified on attempt 1. `PostgresRbacStore.list_policies` now orders
  `name COLLATE "C", id`, `list_service_accounts` orders `sa.name COLLATE "C"` with no tiebreak
  (`service_accounts_organization_id_name_key` makes it total under the query's `WHERE`), and
  `InMemoryRbacStore.list_policies` sorts by `(item.name, str(item.id))`. `bindings_at` and
  `InMemoryRbacStore.list_service_accounts` were already correct and are untouched. Three ordering
  pins were added to `tests/contract/test_rbac_store.py` and mutation-proven twice over — once by the
  implementer and again independently by verification, which reverted all four individual changes
  (both `COLLATE`s, the `id` tiebreak, and the in-memory key) by hand, confirmed each produces exactly
  one distinct failing assertion with the other two pins still green, and confirmed the `id`-tiebreak
  mutation manifests as a genuinely lost row through a real `paginate` walk — the defect D-17 exists to
  close. Verification additionally traced all three boundary keys against their live route handlers
  (not just the tests) and confirmed exact agreement, and established that the shipped fix's
  correctness rests on defined properties (`COLLATE "C"` is byte order by definition; `uuid` primary
  keys make the sort total) rather than any Postgres-incidental tie behavior — only the *demonstration*
  of the `id`-tiebreak mutation depends on today's observed engine behavior, not the fix itself. No DDL,
  no `routes/` changes, no new store parameters. Full gate and `pytest -m contract` clean.

### Task M11.4 — Split the authorization test module to mirror the package

**Intent.** Stop one 230-line test module from standing against five source modules, so a failure
names the surface that broke.

**Design reference.** `## Design 9` → `### Open questions` item 3, which is settled inside the
document — it needs no external fact — and is therefore followed directly, per §2's intro.

**Create.** `tests/unit/test_authorization_credentials.py` (credential precedence, CSRF, the
dev-header fallback); `tests/unit/test_authorization_cookies.py` (issue, revoke, read, and the
`secure` rule); `tests/unit/test_authorization_decisions.py` (cache lifetime, service-account
synthesis, `check`); `tests/unit/test_authorization_guards.py` (the four factories and the
layer-write two-stage rule).

**Modify.** Nothing under `src/`.

**Delete.** `tests/unit/test_api_authorization.py`, with no content left unplaced: every test in it
lands in exactly one of the four, moved rather than rewritten.

**Depends on.** **M11.1** only. It is separable from M11.1 precisely because it touches no source
file: the module M11.1 leaves behind imports the package's public surface and passes, so this split
is a reorganization the gate can verify on its own.

**Verify.**

```text
test ! -e tests/unit/test_api_authorization.py && ls tests/unit/test_authorization_*.py
git diff --stat -- src/
uv run pytest -m unit -q
uv run pytest --cov=src/huron --cov-report=term-missing
<full validation gate>
```

**Acceptance criteria.**

- The four modules exist, the old one does not, and `git diff --stat -- src/` is **empty**: this task
  changes no source file.
- The collected unit-test count is not lower than before the split, and no test was dropped in the
  move.
- Every file under `src/huron/service/api/authorization/` is at 100% line coverage. `scopes.py` has
  no test module of its own and is covered through the guards, as the design directs — five modules
  do not require five test modules, four do the work.
- No test name or docstring references this plan, a milestone, a task number or `API_DESIGN.md` (§0
  rule 1). Each module is named for the surface it pins.
- Full validation gate clean.

**Status: done — Milestone 11 complete. Plan complete.** `tests/unit/test_api_authorization.py` (18 tests,
  covering only `cookies.py` and `credentials.py`) split into four modules mirroring the package:
  `test_authorization_cookies.py`, `test_authorization_credentials.py` (18 moved verbatim, name-identical,
  behaviorally equivalent — independently reconstructed via `git show HEAD:...` plus pytest's cross-run
  node-id cache, not taken on trust), `test_authorization_decisions.py` and `test_authorization_guards.py`
  (23 new tests, since the old module had never directly exercised `decisions.py` or `guards.py` at all).
  All six `authorization/` files at 100% line coverage, `scopes.py` reached purely through the guards
  tests as the design directs, overall coverage unchanged at 90.20%. Zero source files under `src/`
  touched by this task — proven independently by mtime ordering (no `src/` file, of any extension, carries
  an mtime at or after the first new test file's), not accepted from the implementer's account, since the
  acceptance criterion's literal `git diff --stat -- src/` wording is unsatisfiable in a repository with no
  commits over its working tree and would have equally failed M11.1–M11.3. Four non-blocking follow-ups
  recorded by verification for whoever next touches `authorization/`: no direct test for `current_session`
  or the `hk_` API-key branch of `current_principal` (100% only via route tests); the live-service-account
  synthesis test asserts presence, not which capabilities; `CookieSpec.read` untested for a jar present but
  missing the configured name; `test_authorization_credentials.py` still imports the private `_enforce_csrf`
  directly, inherited verbatim from the pre-split module.

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

**Why it matters.** **The grouping is now a decision, not a proposal.** The owner settled all
seventeen entries in §2 on 2026-09-01 and settled with them that the **eight** client-visible
changes — **D-3** (`/roles` becomes 401), **D-4** (`/search` becomes 401 and relocates), **D-5** (the
twelve OpenAPI tags, which change generated SDK shape), **D-6** (the envelope break), **D-7**
(`/roles` loses its `items` wrapper), **D-12** (`DELETE /bindings/{id}` narrows to SYSTEM), **D-16**
(the two release keys) and **D-17** (the ordering fix, a fix rather than a break: a cursor walk that
dropped rows stops dropping them) — **ship as one release.** Because M11 is last, D-17 rides that
release without a separate decision. Landing them as eight releases would spend the same client
goodwill eight times and make each one look like an unrelated regression.

**Fallback decision point.** The residual risk is no longer *whether* to group but whether a partial
deploy is ever forced; the answer is a release decision, not an implementation one: **hold the
release, never the milestones.** If the owner needs a partial deploy, the honest cut is everything
through **M3.1** — the execution-model change and the mechanical, contract-preserving half of the
repository decomposition, which together break no client contract — with **M3.2 onward** held
together. The cut is M3.1 and not M4 because M3.2 removes two keys from both release responses
(D-16), and M4.1 depends on M3.2, so no later milestone can be deployed without it. Holding the
release never holds a milestone: every task in this plan is implementable today.

---

## 5. Definition of done

The plan is complete when every task above is `Status: done` — **twenty-seven tasks across eleven
milestones** — every one passed the implement → verify loop within its cap, and all of the following
hold on the final tree.

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
- `records.py` imports nothing from `huron`; no store module imports anything from
  `huron.service.api` beyond `records` and `errors`; `uv run lint-imports` keeps every contract, and
  there are **seven** of them — the five this repository started with, plus one per package M11
  creates.
- `authorization.py`, `postgres_rbac.py`, `postgres_auth.py`, `ports.py` and `memory_rbac.py` do not
  exist. `src/huron/service/api/authorization/` and `src/huron/service/api/stores/` do, each entered
  through an `__init__.py` that holds re-exports and no logic — nineteen names and eight — and no
  module outside either package names a submodule of it.
- `grep -rn --include='*.py' 'set_cookie\|delete_cookie' src/huron/service/api/` returns hits only
  in `authorization/cookies.py`, and `grep -rn 'rsplit' src/huron/service/api/stores/` returns exactly
  one line.
- `routes/v1/common.py` does not exist. `jsonable` is imported by no route module and its docstring
  describes persistence only.
- `grep -rn -- '-> dict\[str, ' src/huron/service/api/routes/` returns nothing; the only two such
  handlers left in the tier are `/healthz` and `/readyz` in `app.py`.
- `grep -rn 'raise DomainError(\|HTTPException\|DOMAIN_ERROR' src/huron` returns nothing.
- No file under `migrations/` and no file under `src/huron/schema` was modified in the entire run —
  verifiable with `git diff --stat` against the run's base commit. M11's SQL opening (§0 rule 3)
  changed `ORDER BY` clauses and nothing else: no DDL statement exists anywhere under
  `src/huron/service/api/stores/`.

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
- Every text component of every `ORDER BY` in `stores/` carries `COLLATE "C"`; `list_policies`
  returns `(name, str(id))` order from both backends and `list_service_accounts` returns
  `name COLLATE "C"`; a cursor walk at `limit=1` over policies sharing a name enumerates each row
  exactly once, proven against the `postgres:16` container rather than against the in-memory store
  alone.
- `RbacStore` and `ApiKeyWriter` appear in no implementation's `__mro__`: conformance is structural
  on both backends, asserted in `tests/contract/`.
- `make docs` builds `--strict`; `make test` and `make lint` pass; `make api` and the `Containerfile`
  `CMD` both name `huron.service.api.main:app`.

**Process.**

- Every one of the **seventeen** decisions in section 2 is recorded with the owner's answer —
  **all seventeen were answered on 2026-09-01**, so this condition is already met and no milestone
  can be held for want of one. What remains verifiable here is that the shipped code matches the
  recorded answers, D-10's 1 MiB `CreatePolicy.spec` ceiling included.
- The eight client-visible changes (D-3, D-4, D-5, D-6, D-7, D-12, D-16, D-17) went out as **one**
  release, and the external deployment artifacts that name `huron.service.api.app:app` were updated
  by the owner before that release was deployed (D-1).
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
   `AUTH_IMPLEMENTATION_PLAN.md:874` (the shipped platform plan's `Containerfile` excerpt). D-1's "three
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

### M11 verification

Scope: M11 only, plus the amendments made for it and whether adding it broke the existing plan.
M1–M10 were not re-verified. **Six defects**, none of them a blocker for M11.1/M11.2/M11.4 as
written; defects 1 and 2 will stop an implementer mid-task.

#### Defects

1. **M11.1's "One conflict in the design" paragraph resolves a conflict that does not exist, and its
   instruction cannot be executed as written.** `API_DESIGN.md:7451`, inside
   `#### `authorization/__init__.py``, reads
   `from .credentials import CurrentPrincipal, CurrentSession, current_principal`. It does **not**
   import `current_session`, and all three names it does import are in the nineteen-name `__all__`.
   The paragraph asserts the snippet "imports `current_session` from `.credentials` but does not list
   it in the nineteen-name `__all__`, which Ruff reports as an unused import", and directs "The
   import line drops the name." There is no such name on that line. The nearest candidate,
   `CurrentSession`, **is** in `__all__`; an implementer following the instruction literally drops it
   and gets Ruff `F822` (undefined name in `__all__`) plus an `AttributeError` on
   `authorization.CurrentSession` from every route that declares it — precisely the failure the
   paragraph claims to prevent. *Correction:* delete the paragraph, or replace it with "the design's
   `__init__.py` snippet is internally consistent — import exactly the nineteen names it exports."

2. **M11.2's verify block greps `docs/`, which holds a reference the task is neither told to fix nor
   permitted to.** `docs/getting-started/repository-layout.md:27` names `postgres_rbac.py` (and `:25`
   names `authorization.py`). M11.2's verify runs
   `grep -rn 'postgres_rbac\|postgres_auth\|memory_rbac\|api import ports\|api\.ports' src/ tests/ docs/ Makefile`,
   which returns that line after the move. The file is absent from M11.2's **Modify** list, and §1's
   "Documentation reconciliation" non-goal excludes every doc edit except `design/api.html` §7. The
   implementer is left with a red verify step, no instruction, and a rule forbidding the obvious fix.
   The same stale line survives M11.1 unseen, because M11.1's greps cover only `src/` and `tests/`.
   *Correction:* either add `docs/getting-started/repository-layout.md` to M11.1's and M11.2's Modify
   lists with an explicit §1 carve-out (D-1 already carves out `docs/getting-started/local-development.md:131`,
   so the precedent exists), or drop `docs/` from the grep and record the stale line as a hand-off to
   the roadmap-reconciliation phase.

3. **§2's opening sentence still carries a stale section count.** `:166` — "**40 open questions**
   across its **ten** design sections". The pre-amendment text said "33 … across its **nine** design
   sections", and nine was the count of `^## Design ` headings (1, 2, 3, 4, 5, 5b, 6, 7, 8). By that
   same convention the count is now **eleven**, not ten — `grep -c '^## Design '` returns 12, of
   which one is `## Design Tasks`. The `40` itself is correct (counted below). *Correction:* "eleven
   design sections". This is the only surviving old number found; every other corrected count
   reconciles.

4. **Two of M11's nineteen `API_DESIGN.md` heading references are not verbatim, so a literal search
   fails.** `:1508` and `:1526` cite `## Design 9 — authorization.py decomposition`; the heading is
   ``## Design 9 — `authorization.py` decomposition`` (backticks around the filename). `:1628` cites
   `#### By port, not by backend`; the heading is
   `#### By port, not by backend — and why the choice is narrower than it looks`. Navigation only —
   no task changes meaning — but the plan's own convention is verbatim citation, and the other
   seventeen references match `grep -Fx` exactly. *Correction:* restore the backticks and the tail.

5. **M7.3 and M11.3 state the policies boundary key differently, while M11.3 asserts they are
   identical.** M11.3 specifies `InMemoryRbacStore.list_policies` sorts by `(item.name, str(item.id))`
   — "`str(item.id)` so the expression reads identically to the boundary's key" — and its acceptance
   criterion 1 requires the contract test to assert both stores equal
   `sorted(records, key=<the boundary key>)`. M7.3's acceptance (`:1059`) publishes that key as
   `Page[PolicyView]` **keyed on `(name, id)`**. Design 10's `#### The ordering contract, per collection`
   says `(name, str(id))`. The two orderings coincide for canonical lowercase UUID strings, so this is
   not a runtime failure — but M11.3's stated rationale is false against M7.3 as written, and the
   contract test's `<the boundary key>` is ambiguous at the point it is written. *Correction:* make
   M7.3's acceptance read `(name, str(id))`.

6. **M11.3's Depends-on omits the task that establishes the third collection's boundary key.** Its
   acceptance criterion 1 requires the ordering-agreement pin "for all three collections", which
   includes `bindings_at` and its `(principal, role_code)` key (Design 10's ordering table). That key
   comes from M7.1 (`RoleBindingView`) / M9.2, not from M7.2 or M7.3, which are the only M7 tasks the
   Depends-on names. M11 runs after all of M1–M10, so this cannot fail in execution; the dependency
   line is incomplete rather than wrong, and an incomplete one is what makes a later re-sequence
   unsafe. *Correction:* add M7.1, or narrow criterion 1 to the two collections M11.3 changes.

#### Dependency claims tested — all four held

- **M11.1 on M8.1.** `grep -n 'authorization\.py' API_IMPLEMENTATION_PLAN.md` returns every task that
  names the file: M1.1 (`:308`), M2.1 (`:409`, `:421`), M5.1 (`:725`), M8.1 (`:1116`, `:1119`,
  `:1124`). The only later hit is M9.1 `:1343`, which is an **acceptance criterion** asserting where
  `check` is invoked — M9.1's Modify list is `routes/v1/endpoints/bindings.py` and a test module, and
  its Delete list explicitly says "`authorization.check` and the three `*_scope` helpers **stay**".
  M10.1–M10.3 do not name it, consistent with Design 9's statement that `src/huron/service` already
  passes Ruff `FAST` clean. **M8.1 is the last task that edits `authorization.py`. CONFIRMED.**
- **M11.2 on M3.1.** M3.1's Create list (`:494-495`) is
  `src/huron/service/api/ports.py` (`RbacStore`, `ApiKeyWriter`) and
  `src/huron/service/api/memory_rbac.py` (`InMemoryRbacStore`) — byte-identical paths to the two
  M11.2 deletes and absorbs. M3.1 also creates `records.py` (`:493`), which `rows.py` imports.
  **CONFIRMED.**
- **M11.3 on M7.2 and M7.3.** M7.2's acceptance: "`GET .../service-accounts` returns
  `Page[ServiceAccountView]` keyed on `(name,)`" — matches M11.3's `(name,)`. M7.3's acceptance:
  "`GET /policies` returns `Page[PolicyView]` keyed on `(name, id)`" — matches in substance, differs
  in expression (defect 5). **CONFIRMED, with defect 5.**
- **No task touches a module after M11.2 deletes it.** Every plan hit for
  `postgres_rbac|postgres_auth|memory_rbac|ports.py` outside M11 is at or before M8.1 (M3.1 `:494`,
  M3.2 `:499-500`, M8.1 `:1117`), except §5's definition of done (`:1956`) and the pre-existing
  `## Verification` record. M11.3 modifies `stores/rbac.py`, the post-move path. **CONFIRMED.**

#### The SQL amendment — checked, and it holds

Rule 3 (`:95-107`) scopes the freeze to "**for M1 through M10**", names M11 as "the exception, and it
is the only one", permits "`SELECT` text, `COLLATE` and `ORDER BY` clauses in the store modules", and
states "**DDL may not**" with `migrations/` and `src/huron/schema` out of scope for M11 exactly as for
M1–M10. No M11 task requires DDL: M11.3's Modify list is `src/huron/service/api/stores/rbac.py` and
`tests/contract/test_rbac_store.py` and nothing else; its acceptance carries a DDL grep and
`git diff --stat -- migrations/ src/huron/schema/`. Design 10's three candidate indexes are recorded
as a hand-off in §1's non-goals ("None is required … none of them gates M11 and none appears in §2"),
matching Design 10 `### Open questions` item 3 ("None is required: every query above is correct
without them"); D-17 closes with "**DDL is not part of the answer**". `grep -c '^| \*\*D-'` returns
**17** — no index appears as a decision. The three current `ORDER BY` clauses were read on disk:
`postgres_rbac.py:230` already `principal COLLATE "C", role_code COLLATE "C"` (M11.3 correctly leaves
it), `:311` `ORDER BY sa.name`, `:384` `ORDER BY name` — exactly the two M11.3 changes.
`repository.py:415` is `sorted(self._policies.values(), key=lambda item: item.name)` — the one
in-memory key M11.3 changes.

#### Coverage, Designs 9 and 10, both directions

Design 10's four module deletions all carry: `postgres_rbac.py`, `postgres_auth.py`, `ports.py`,
`memory_rbac.py` are named in M11.2's **Delete** and re-checked in its verify (`test ! -e` ×4) and in
§5. The by-symbol deletion (`postgres_rbac.py:450`'s hand-written `int(tag.rsplit(" ", 1)[-1])`) is
named, and the line is on disk at `:450`. Design 9's eleven names that stop being public all carry:
the six cookie names and `cached_bindings_for` are in M11.1's **Delete** by symbol; `BindingCacheMap`,
`request_binding_cache`, `current_session` and `_enforce_csrf` are carried by placement in submodules
plus the `len(a.__all__) == 19` acceptance, which is enforceable. Design 9's per-module contracts map
to the five Create entries; `#### The package boundary` maps to the sixth import-linter contract and
its "proven to bite" criterion. Design 10's `#### Error behavior, per store` maps to M11.2's error-table
criterion, `#### tests/contract/` item 4 to the three-way conformance probe, items 1–3 to M11.3's three
pins, `#### stores/__init__.py` to `len(s.__all__) == 8` with `rows` excluded. Every M11 task has a
basis: M11.1 ← Design 9; M11.2 ← Design 10 Half A; M11.3 ← Design 10 Half B + OQ1; M11.4 ← Design 9
OQ3. No orphan task, no uncarried deletion.

#### Counts, checked on disk

| Claim | Checked | Result |
|---|---|---|
| 11 milestones | `grep -c '^## M'` | **11** |
| 27 tasks | `grep -c '^### Task M'` | **27** |
| 0 pending, 27 done | `grep -c '^\*\*Status: pending\*\*'` / `grep -c '^\*\*Status: done'` | **0** / **27** |
| 17 decisions | `grep -c '^\| \*\*D-'` | **17** — D-1…D-17, `:1999` says "seventeen" |
| 40 open questions | counted per `### Open questions` | D1 3, D2 3, D3 4, D4 3, D5 4, D5b 4, D6 4, D7 4, D8 4, D9 3, D10 4 = **40** |
| 23 + 16 + 1 = 40 | §2 arithmetic | **reconciles** |
| 19 / 8 `__all__` | counted in the design snippets | **19** and **8** |
| 6 / 7 contracts | `grep -c '\[\[tool.importlinter.contracts\]\]' pyproject.toml` = 5; no M1–M10 task adds one | **sixth and seventh are correct** |
| stale old numbers | grep over §0–§5 for 33 / nine / eighteen / fifteen / "ten milestones" / "23 tasks" | one miss — defect 3 |

#### Mechanical executability

Every file and line M11 names was checked on disk. `authorization.py` is 426 lines (Design 9's figure);
`postgres_rbac.py` 465, `postgres_auth.py` 256, `test_api_authorization.py` 230 — all as stated.
`tests/contract/test_rbac_store.py:63` is `from huron.service.api.postgres_rbac import …`;
`test_auth_store.py:48` is `from huron.service.api.postgres_auth import (`;
`tests/unit/test_repository_rbac.py:3` (docstring), `:25` (`cached_bindings_for` import), `:338`
(`_touch_api_key`), `:376-389` (the two direct-call tests) — **all four exact**, and `:338` is an
addition the plan makes over Design 9's Deletions list, correctly. `postgres_rbac.py:450` is the
`rsplit` line. M11.1's claim that only `test_api_authorization.py` names the retired cookie names in
`tests/` was tested by grep across the whole tree: the only test hits are
`test_api_authorization.py:21,23,142,145,147,158,160,166,168`; `test_api_login.py` and
`test_api_oidc.py` do not name them. `routes/auth/endpoints/{login,oidc,session}.py` and the five
`routes/v1/endpoints/*.py` M11.1 lists all exist today. Every verify command in M11 was executed:
all five greps, `test ! -e`, and `git diff --stat -- migrations/ src/huron/schema/` run cleanly. All
nineteen `API_DESIGN.md` heading references were checked with `grep -Fxc`; seventeen matched, two did
not (defect 4).

#### Regression

`git diff --numstat` — `API_DESIGN.md` **1224 insertions, 0 deletions**, one hunk, `@@ -7251,0 +7252,1224 @@`:
a pure append of Designs 9 and 10, nothing else touched. `API_IMPLEMENTATION_PLAN.md` 425 insertions,
22 deletions; the highest-numbered hunk is `@@ -1596,2 +1999,2 @@`, and `## Verification` begins at
`:2006`. **The `## Verification` section is byte-unchanged.**

#### Gate

Run on this host with `UV_PROJECT_ENVIRONMENT=$HOME/gatevenv`, mypy on a fresh `--cache-dir` outside
the tree.

| Command | Result |
|---|---|
| `uv run ruff check .` | `All checks passed!` |
| `uv run ruff format --check .` | `101 files already formatted` |
| `uv run ty check` | `All checks passed!` |
| `uv run mypy --cache-dir=…` | `Success: no issues found in 27 source files` |
| `uv run lint-imports` | `Contracts: 5 kept, 0 broken.` |
| `uv run pytest -m unit -q` | `218 passed, 3 deselected, 2 warnings in 4.85s` |

`pyscn` and the container runtime are unavailable on this host and are not recorded as defects — §0's
**Environment prerequisites** document both as properties of the host.

#### Observations

- §0's environment-prerequisite bullet, amended in this change to add M11.2 and M11.3, still says
  "**Both** modules under `tests/contract/` drive a migrated PostgreSQL". There are **three**:
  `test_auth_store.py:55`, `test_rbac_store.py:66` and `test_catalog_store.py:134` all carry
  `pytestmark = pytest.mark.contract`. Design 10's `#### tests/contract/` repeats the same "Two
  modules today". Pre-existing wording, outside the M11 diff, but M11.2 and M11.3 now rest on it.
- M11.1's acceptance reads `grep -rn 'set_cookie\|delete_cookie' src/huron/service/api/` as returning
  hits only in `authorization/cookies.py`. On a working copy with a stale `__pycache__` that grep also
  prints `binary file matches` for the old `.pyc`. Adding `--include='*.py'` would make the criterion
  mean what it says.
- M11.3's DDL grep includes the bare alternative `drop ` under `-i`, which matches ordinary prose. It
  is a screening grep followed by `git diff --stat`, so a false positive costs a read, not a failure.
- Design 10's Layout table cites `InMemoryRbacStore.list_policies` at `repository.py:406`; it is at
  `:415` today. Design-side only — every line reference the **plan** makes was exact.
- M11.1's "Not M9 … and not M10" note and M11.2's three-part dependency rationale are the two places
  where this milestone's sequencing reasoning is strongest; both survived testing against the tasks
  they name.
