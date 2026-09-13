# P3 M1b — Authority and reverification: implementation plan

Design: `P3_M1B_AUTHORITY_DESIGN.md` (read it in full before any milestone; every task
below cites the design section that specifies it and never restates it). Rationale:
`docs/adr/0001-controller-generation-is-the-verification-epoch.md`. Executed by
`.claude/commands/implement-markdown.md`: one implementation subagent per **milestone**,
then one verification subagent, at most three verification attempts, then escalation.
Tasks inside a milestone are the implementer's ordered checklist and are not gated
individually; the gate runs on the milestone's final tree.

## 1. Goal and non-goals

**Goal.** Resolve M1b authority and reverification so that a maintenance caller can never
make stale or revoked evidence usable without a fresh complete scan: the controller's
durably persisted generation becomes the sole verification epoch (`establish` mints it;
every failed observation, client-declared `abandon` and controller restart ends it), a
stateless `validate` replaces `certify`/`validate_certificate`, the fence binds the
maintenance database identity, and every `prepare` appends a new report/record pair.
Later P3 scope is preserved unchanged.

**Non-goals (out of scope for every milestone).**

- M1c: `lakectl protocol init`, API startup gating, activation of the new role or
  deployment. Only `lakectl protocol cutover --validate --sequence N` moves into this plan
  (roadmap drift recorded in the design, "Design: T3b", "Roadmap drift recorded here").
- M2–M7 of `P3_IMPLEMENTATION_PLAN.md`; D3b+ duplication reduction work; `design/roadmap.html`
  (Phase 5's edit).
- Any NFS, multi-host or production certification claim; a PostgreSQL standby fixture
  (T4 open question 2: standby wording is designed, not executed).
- Pool sizing at either `asyncpg.create_pool(url)` call site (T3a open question 2).
- Independent verification of M1b. This plan's final gate is the implementation's own
  validation record; M1b remains unverified until an independent verification pass.

**Human decisions the design flagged, with the default this plan assumes.** Each task's
recommended option is assumed unless a later section overruled it; T5b's rulings supersede
T2's numbers and T2 §8 (d)/(k).

| Question (design section) | Assumed default |
| --- | --- |
| T1 §6.1 `datname` containing `/` | keep the strict pattern; refusal at `establish` |
| T1 §6.2 position of `database` | declared last |
| T2 §6.1 claim-release failure outside the abandon span | stays outside; record stays admissible via `validate` |
| T2 §6.2 double's failed observation | superseded by T5b ruling 1: `DeploymentBoundary.check` advances on `valid == False` |
| T3a §6.1 `_advance()` ordering | `try/finally` (memory never behind disk), not the task's literal "disk leads memory" |
| T3a §6.2 pool sizing | keep `create_pool(url)` defaults |
| T3b §6.1 `--validate` opens the maintenance pool | accept |
| T3b §6.2 one exit code for refusal and lost reply | keep exit 1 with the one fixed message |
| T4 §6.1 fallback query if `pg_control_system()` is not executable | decided by the contract receipt (M1 task M1.6, else M6); contingency is one change set, never a second code path |
| T4 §6.2 standby refusal wording | accept as designed; no fixture |
| T5a §6.1 `post_release_close` proves S-lostack | keep `test_lost_return_after_release_keeps_the_record_admissible` as designed |
| T5a §6.2 old `release` fault | dropped; nine observation faults |
| T5b §6.1 observation-ended runs report `abandoned == []` | accept (ruling 1) |
| T5b §6.2 keep `fence_intact` parameter | keep |
| T5b §6.3 contract regex literal | keep the literal |
| T6 §6.1 docs stay "designed" after code lands | yes; status sentences point at this plan and the roadmap |
| T6 §6.2 untracked `design/core-map.html` | edit and `git add` it with the other docs; no commit |
| T6 §6.3 "1,628 units" in dated receipts | leave |

## 2. Execution rules

Carried from `P3_IMPLEMENTATION_PLAN.md` and the review's E.6 handoff; every subagent
assignment includes them.

1. **Lint scope is `src/` only**, as the user directed: `make lint` is the canonical static
   gate (ruff, ruff format, pydoclint, mypy, ty, lint-imports, schema map, radon cc/mi,
   complexipy, pyscn check, duplication). Tests are not type-checked.
2. **Duplication threshold stays 90/100.** Its current failure at 60/100 (213/935
   fragments, 253 pairs, 58 groups) is a user-authorized functional-progress exception: it
   is measured and reported at every milestone (`uv run --locked python
   scripts/check_duplication.py src`, the same invocation `make lint` runs, plus the
   `make lint` exit code, which is 2 at that final step only; `src/` holds only `huron/`, so
   `src` and `src/huron` are the same file set and one measurement) and does not halt work. It must not get worse by more than the
   lines this plan adds; do not tune detection or exclusions.
3. **No fourth M1b fix pass outside this plan.** A milestone that fails verification three
   times escalates per `implement-markdown.md`; do not patch around it.
4. **Coverage floor 95.88 (`pyproject.toml [tool.coverage.report] fail_under`) is a
   ratchet.** If a milestone's measured total exceeds it, raise `fail_under` to the measured
   value rounded down to two decimals in that milestone; never lower it. Every file touched
   in a milestone is at 100% line coverage. No `# pragma: no cover`, `# noqa`,
   `# type: ignore`, skip or xfail markers, no config exclusions.
5. **No Podman or PostgreSQL against the development stack** (`make up`/`make stack` are
   never run). Contract and integration tests use disposable containers only
   (`testcontainers` `PostgresContainer("postgres:16")` inline in the contract module; the
   integration suite's own conftest). Stop and remove what you start; record `podman ps`
   before and after.
6. **Acceptance** (`make test-acceptance`, the 9 GiB run) needs ≥ 25 GiB free; check
   `df -h .` first and record the figure. If the space is absent, record the gap; do not
   fake the run.
7. **Keep unrelated user work untouched.** The working tree carries user changes
   (`.opencode/package-lock.json`, `.opencode/package.json`, `design/index.html`,
   untracked `.pyscn/`, `scripts/main.py`, `tests/unit/test_books_upload_script.py`,
   `docs/adr/`, `P3_M1B_ARCHITECTURAL_REVIEW.md`). Never revert, stage or edit them.
   `git status --porcelain` after every milestone shows exactly those plus the milestone's
   intended files.
8. **No commit, no push.** `git mv` and `git add` of the files named in a task are
   allowed; nothing else touches the index.
9. **Clean sweep.** No backwards compatibility unless a task says so explicitly (none
   does). Replaced signatures are not kept alongside; deleted names are deleted, not
   deprecated. No plan/phase references in code, comments, docstrings or test names.
10. **Skills.** `oop-design` for `src/huron/pkg` and `src/huron/core`;
    `postgresql-table-design` only for T4's catalog query; no `fastapi` (the API service is
    untouched); no Svelte/Tailwind.
11. **Design line numbers are locators**, pinned against HEAD `e22d000`; re-pin with `grep`
    on the quoted text before editing.

## 3. Milestone sequence

Dependency direction `schema → pkg → core → applications → tests → docs` holds inside every
milestone. Every milestone leaves the tree compiling, `make lint` clean except rule 2, and
the full unit suite passing with all touched files at 100%.

**Why this shape differs from the suggested one.** The suggested M1 (T1 + T4 + their unit
tests only) is not green: once `FenceEvidence.database` is required and the two Protocols
change, `cutover.py` still calls `certify` (mypy, via `make lint`), `controller._evidence()`
omits a required field (every `establish` test fails at runtime),
`controller.py:213–215` calls the two-parameter `check` (mypy) and `wiring.py` passes
adapters that no longer satisfy the ports (mypy). The clean-sweep rule forbids the only
other way to keep it green (new methods beside old ones). The design's production change
therefore splits along *semantic* seams, each independently complete and shim-free:

| Milestone | Content | Design basis | Why it is green on its own |
| --- | --- | --- | --- |
| M0 | baseline receipts | Roadmap Drift "Receipts" | no change |
| M1 | database identity binding: `FenceEvidence.database`, `DatabaseExclusion` port, schema regeneration, T4 adapter, identity captured by the controller (`identify()` through a lazy pool, async `establish`), every double and `FenceEvidence` construction, contract file edits | T1 (models/DatabaseExclusion/schema), T4, T3a (state field, settings-once, `_database()`, async `establish`, `_evidence()`), T2 (`exclude(evidence)`, `roles.check(evidence)`), T5a (`IDENTITY`, `EmptyDatabaseBoundary`, `database_boundary`, async sites), T5b (`Fence`, `RoleDatabaseBoundary`, contract, script) | `WriterExclusion` and the endorsement model are untouched; every caller of the changed `DatabaseExclusion` and every `FenceEvidence` producer changes in the same milestone |
| M2 | append-only sequencing and claim-before-establish | T2 §1–§2 (sequence invariant, claim span), `models.py` `bind` | independent of the port rename; `certify` still runs after the claim release |
| M3 | operator `--validate` path: `_reply`, `wiring._deployment`/`validate`, `main --validate --sequence` | T3b §1 (`exclusion.py` `_reply`, `wiring.py`, `main.py`), T5a (wiring/main/`_reply` tests) | additive over `CutoverService.validate`, which already exists |
| M4 | the epoch cutover (atomic): four-method `WriterExclusion`, `CertificationIndeterminateError` deleted, `_abandoning`, controller `_advance`/`_observing`/unconditional mint/`abandon`/`validate`, server/client rename, doubles and every replaced test | T1 (WriterExclusion, deletions), T2 §1 (`_abandoning`, `validate`), T3a §1–§3, T3b §1–§3, T5a, T5b | the one change that cannot be split green; sized by moving every *additive* proof to M5 |
| M5 | epoch behaviour proofs: nine-fault observation matrix, composition tests with kernel interceptors, three controller tests, deleted-operation payloads | T5a §1 | additive tests only |
| M6 | contract and integration on disposable containers; T4 contingency if still open | T5b (contract test, `controlled_deployment.py`), T4 §6.1 | runs the suites written in M1/M4 |
| M7 | documentation reconciliation | T6 | prose only, after every message string exists |
| M8 | final full gate, ratchet, evidence and report | all | no code change except the ratchet |

Deletions happen at the earliest green point: the two-parameter `DatabaseExclusion`
signatures, the live `MaintenanceSettings.load` and inline `create_pool` in
`_validate_evidence` (M1); `_transition` and same-run reuse (M2); the inline reply tail
(M3); `certify`, `validate_certificate`, `CertificationIndeterminateError`, `_certificate`,
the named catch tuples, the cumulative writer union and conditional mint (M4).

Milestone sizes (one subagent each): M0 ≈10k, M1 ≈45k, M2 ≈25k, M3 ≈30k, M4 ≈45–50k,
M5 ≈25k, M6 ≈25k plus container time, M7 ≈30k, M8 ≈15k tokens.

## 4. Milestones and tasks

Command reference (all exist in this repository; run from the repository root):

```text
make lint                                                     # canonical static gate; exit 2 only at the last (duplication) step
uv run ruff check src ; uv run ruff format --check src ; uv run pydoclint src
uv run mypy src ; uv run ty check src ; uv run lint-imports
uv run radon cc src --min C ; uv run radon mi src --min B ; uv run complexipy src --max-complexity-allowed 15
uv run --locked pyscn check src
uv run --locked python scripts/check_duplication.py src   # measured native score; expected exit 1 (rule 2)
uv run pytest -q tests/unit --cov=src/huron --cov-report=term-missing
uv run pytest -q --co tests/unit ; uv run pytest -q --co -m contract ; uv run pytest -q --co -m integration
uv run pytest -q -m contract ; uv run pytest -q -m integration -s ; make test-acceptance
make docs ; git diff --check ; git status --porcelain
```

Unit collection today: 1634 (`tests/unit`), 48 (`-m contract`), 14 (`-m integration`).
Expected after the plan: ≈1677 unit (design per-module targets: `test_protocol_documents`
+5, `test_maintenance_adapters` 17→21, `test_integrity_cutover` 25→25, T5a's five modules
57→91), 49 contract, 14 integration. Counts are expectations; the hard criterion is that
every named test exists and passes and every deleted test is absent. Reconcile any count
deviation in the milestone report.

### M0 — Baseline receipts

Status: complete

#### Task M0.1 — Capture the untouched-tree baseline

Intent: prove the tree is green (except rule 2) before any change, so every later failure
is attributable.

- Create: `p3-evidence/m1b-authority/m0-baseline/` with the receipts in §5.
- Modify/delete: nothing.
- Design basis: "Roadmap Drift" → "Receipts" and "Clean".
- Verification: the §5 recipe. Expected: unit `1634 passed`, TOTAL 95.88%, the 17 M1b
  files at 100%; `make lint` exit 2 with every step before duplication clean and the
  native score 60/100 recorded; `--co` 1634/48/14; `git status --porcelain` equal to rule
  7's list.
- Dependencies: none.

Status: complete

### M1 — Database identity binding

Status: complete

Design basis for the whole milestone: "Design: T1" §1 (`models.py`, `DatabaseExclusion`,
schema regeneration, `test_protocol_documents.py`), §2, §3 (only the `DatabaseExclusion`
signatures and `generations.py:24`); "Design: T4" §1–§3; "Design: T3a" §1 (the
`ControllerState.database` field, `__init__` loading `MaintenanceSettings` once,
`_database()`, `_evidence()` with `database`, `identify()` captured in `establish`),
§2 "identify() position in establish", "Pool and settings lifecycle"; "Design: T2" §8
(T4's two call sites); "Design: T5a" §1 (`EmptyDatabaseBoundary`, `database_boundary`,
the `establish` call-site table), §2 (`EmptyDatabaseBoundary`, `database_boundary`);
"Design: T5b" §1 (`test_maintenance_adapters.py`, `tests/contract/test_writer_exclusion.py`,
`tests/controlled_deployment.py` `Fence`/`fence_database()`/`:375`), §2 (`RoleDatabaseBoundary`,
the contract fence value, the decision rule), §3 (the two-parameter sites).

Not in M1: `WriterExclusion`, `certify`/`validate_certificate`/`CertificationIndeterminateError`,
`_advance`/`_observing`, the report path, `abandon`, `validate`. The controller keeps its
endorsement model in M1; only what the identity needs changes.

#### Task M1.1 — Core model and `DatabaseExclusion` contract

Intent: give the fence a required database identity and the database port its
identity-first shape.

- Modify: `src/huron/core/integrity/models.py` (`FenceEvidence.database`, declared last,
  T1's pattern); `src/huron/core/integrity/ports.py` (`DatabaseExclusion.identify/exclude(fence)/check(fence)`
  verbatim from T1 §1; `WriterExclusion` unchanged in this milestone);
  `src/huron/core/integrity/generations.py` (docstring "certifying" → "verifying").
- Delete: the two-parameter `exclude`/`check` signatures.
- Design basis: T1 §1, §2 ("`FenceEvidence.database` invariant", "Equality is whole-value",
  "Structural compatibility"), §3 first and third bullets.
- Acceptance: `mypy src`/`ty check src` clean after M1.3–M1.4; `FenceEvidence` equality
  distinguishes `database`.
- Dependencies: none.

Status: complete

#### Task M1.2 — Regenerate the protocol schemas and their tests

Intent: keep both `protocol-*-v1.json` equal to the model under unchanged `$id`s.

- Modify: `src/huron/schema/documents/protocol-inventory-v1.json`,
  `protocol-transition-v1.json` (regenerated from `model_json_schema(by_alias=True)` +
  `$schema` + `$id`, `json.dump(indent=2)` plus trailing newline — T1 §1 "Schema
  regeneration"); `tests/unit/test_protocol_documents.py` (`inventory()` gains
  `database="7367538914089103371/16384/huron"`; new `test_fence_binds_one_bounded_database_identity`
  parametrized over the five bad values, plus the missing-`database` assertion).
- Design basis: T1 §1 "Schema regeneration", "`tests/unit/test_protocol_documents.py`".
- Acceptance: `$defs.FenceEvidence.required` ends with `"database"` in both files;
  `test_protocol_schema_loading_map_stays_in_sync_with_runtime_contracts` passes unedited;
  `uv run pytest -q --co tests/unit/test_protocol_documents.py` shows +5.
- Dependencies: M1.1.

Status: complete

#### Task M1.3 — PostgreSQL adapter (T4)

Intent: identify the primary and compare the fence identity before any role change.

- Modify: `src/huron/pkg/metastore/maintenance.py` to T4 §1 verbatim (`_IDENTITY_SQL`,
  `DatabaseFence`, `identify`, `exclude(fence)`, `check(fence)`, `_require_identity`;
  helpers unchanged). No `huron.core` import.
- Delete: the two-parameter signatures and `await self.check(old_roles, new_role)`.
- Design basis: T4 §1, §2, §3; apply `postgresql-table-design` to the query only.
- Acceptance: `uv run lint-imports` "9 kept, 0 broken"; `pydoclint` silent (DOC502 note in
  T4 §5); M1.5's adapter tests pass.
- Dependencies: M1.1.

Status: complete

#### Task M1.4 — Callers of the changed port and the identity producer

Intent: every production caller uses the fence form and the controller emits the identity.

- Modify: `src/huron/core/integrity/cutover.py` (`await self._roles.exclude(evidence)`;
  `_Fence.check` → `await self.roles.check(self.evidence)` — T4 §8 → T2);
  `src/huron/applications/lakectl/settings.py` (`ControllerState.database: str | None = None`);
  `src/huron/applications/lakectl/controller.py`: `self._maintenance = MaintenanceSettings.load(...)`
  in `__init__`; `@asynccontextmanager _database()` creating the pool lazily with the single
  positional `asyncpg.create_pool(url)`; `establish` becomes `async`, calls
  `await roles.identify()` after the writer inventory and before the state copy/persist,
  and writes `database` into the state with `run_id`/`operator`; `_evidence()` emits
  `database`; `_validate_evidence` obtains the adapter through `_database()` and calls
  `await roles.check(transition.fence)`; `src/huron/applications/lakectl/server.py`
  (`establish` runs under `asyncio.run`).
- Delete: `controller.py`'s live `MaintenanceSettings.load` and inline `create_pool` in
  `_validate_evidence`; the two-parameter `check` call there.
- Design basis: T3a §1 (`__init__`, `_database`, `_evidence`, `settings.py`), §2 "identify()
  position in establish", "Pool and settings lifecycle", "Threading and sync/async"; T3b §1
  operation table row `establish`; T4 §8 (T3a).
- Acceptance: `make lint` clean except rule 2; no eager pool in `__init__` (construction
  tests need no `create_pool` patch).
- Dependencies: M1.1, M1.3.

Status: complete

#### Task M1.5 — Unit doubles, fixtures and adapter tests

Intent: one identity string shared by every test seam; the adapter's identity behaviour
proven through the SQL double.

- Modify: `tests/unit/test_lakectl_wiring.py` (`IDENTITY`; `EmptyDatabaseBoundary.identity`
  / `failure` and the `fetchval` routing verbatim from T5a §1; `ControllerBoundary.establish`
  returns `database=IDENTITY`); `tests/unit/test_managed_controller.py` (`database_boundary`
  fixture verbatim; the ten `establish` sites become `await` inside `async def` tests that
  request `database_boundary`; `:105–107` adds `evidence.database == database_boundary.identity`);
  `tests/unit/test_controller_certificates.py` (`prepared` requests `database_boundary`
  before construction and `await`s `establish`; nothing else yet);
  `tests/unit/test_controller_transport.py` (in M1 only
  `test_client_authenticates_describes_establishes_and_checks_real_requests` (`:63`) needs
  `database_boundary`, because the server's `establish` now calls `identify()`; the two
  tests at `:205–266` already patch `create_pool` inline with `EmptyDatabaseBoundary`; add
  `from tests.unit.test_managed_controller import database_boundary as database_boundary`
  beside the module's existing `test_managed_controller` imports (`:19–20`), the re-export
  pattern `test_controller_certificates.py:17` already uses; T5a §1);
  `tests/unit/test_integrity_cutover.py` (`DeploymentBoundary`: `database=IDENTITY` in its
  evidence, `identify()`, `exclude(self, fence)`, `check(self, evidence)` replacing the
  `*arguments` signature; the retained `certify` (`:66`) and `validate_certificate` (`:71`)
  change their `await self.check()` to `await self.check(transition.fence)` so the M1.7,
  M2.3 and M3.4 gates stay green until M4.5 replaces both with T5b's `validate` (design
  basis T5b §1 "`validate(transition)` is `await self.check(transition.fence)`", T1 §8
  (T5b)); the two subclass overrides `RecoveringBoundary.check` (`:415`) and
  `ObservationBoundary.check` (`:529`) need only the `(self, evidence)` signature, since
  neither calls `self.check()`; `ControllerBoundary` (`test_lakectl_wiring.py:91–98`)
  already takes `evidence` and its `certify`/`validate_certificate` are no-ops, and
  `AcknowledgementBoundary` (`test_lakectl_main.py:71`) overrides only `certify` without
  calling `check`, so no other retained double changes (`grep -n "check(" tests/unit/
  test_integrity_cutover.py tests/unit/test_lakectl_wiring.py tests/unit/test_lakectl_main.py
  tests/unit/test_controller_transport.py` shows `:66`/`:71` as the only no-argument calls);
  semantics otherwise unchanged until M2/M4);
  `tests/unit/test_maintenance_adapters.py` (`Fence` dataclass,
  `RoleDatabaseBoundary(EmptyDatabaseBoundary)` verbatim from T5b §1, `:64,:84` fence calls,
  the three new tests of T5b's table); every other `FenceEvidence(...)` construction under
  `tests/` gains `database=IDENTITY` (`grep -rn "FenceEvidence(" tests`).
- Design basis: T5a §1 "Doubles and helpers", §2 (`EmptyDatabaseBoundary`, `database_boundary`);
  T5b §1 (`test_maintenance_adapters.py`), §2 (`RoleDatabaseBoundary`); T1 §8 (T5a, T5b).
- Acceptance: `uv run pytest -q tests/unit --cov=src/huron --cov-report=term-missing`
  green, TOTAL ≥ floor, the 17 M1b files at 100%; named tests present:
  `test_role_adapter_identifies_the_primary_and_refuses_an_empty_identity`,
  `test_role_adapter_refuses_a_foreign_fence_before_any_role_change[exclude|check]`,
  `test_role_adapter_observes_identity_before_every_role_statement`,
  `test_fence_binds_one_bounded_database_identity[5]`; `--co`: `test_maintenance_adapters`
  21, `test_managed_controller` 21, unit total 1643 expected.
- Dependencies: M1.1–M1.4.

Status: complete

#### Task M1.6 — Contract test and Linux script call sites (written now, run on containers)

Intent: move every two-parameter site outside `src/` to the fence form and write the E.5
item 1 receipt test.

- Modify: `tests/contract/test_writer_exclusion.py` (`Fence`, `_fence()`, the ten call
  sites per T5b's table, `test_identify_binds_cluster_and_database_and_refuses_a_foreign_fence`
  verbatim); `tests/controlled_deployment.py` (module-level `Fence` dataclass;
  `fence_database()` returns the identity via `identify()` and excludes with a local
  `Fence`; `:375` `evidence = asyncio.run(controller.establish(0, uuid.uuid4()))` and
  `assert evidence.database == identity`).
- Design basis: T5b §1 (contract, script), §2 "The contract fence value", "Decision rule";
  T4 §8 (T5b).
- Verification: `uv run pytest -q --co -m contract` → 49; `uv run pytest -q --co -m
  integration` → 14. **If a container runtime is available**, run
  `uv run pytest -q -m contract tests/contract/test_writer_exclusion.py` on a disposable
  `PostgresContainer` and apply T5b §2's decision rule: (a) pass → primary query ships;
  (b) `asyncpg.InsufficientPrivilegeError` at the `probe` `identify()` → apply T4 §6.1's
  contingency as one change set in this milestone (query, T1 pattern
  `^[0-9]{1,10}/[^/]{1,63}$`, `IDENTITY = "16384/huron"`, doubles routing on
  `NOT pg_is_in_recovery`, the test's `expected`/regex, ADR third consequence); (c) any
  other failure is an adapter defect to fix. If no runtime is available, record that in
  the milestone report; M6 decides.
- Dependencies: M1.3, M1.5.

Status: complete

#### Task M1.7 — Milestone gate and evidence

- Run the §5 recipe into `p3-evidence/m1b-authority/m1-identity/`.
- Acceptance: unit green with coverage ≥ floor (raise the ratchet if exceeded); `make lint`
  exit 2 at duplication only, score recorded; `git diff --check` clean; `git status`
  shows rule 7's list plus exactly the files named in M1.1–M1.6.

Status: complete

### M2 — Append-only sequencing and claim-before-establish

Status: complete

#### Task M2.1 — Report named by sequence; next-free allocation; claim first

Intent: report and record of one `prepare` share one sequence number; nothing under
`protocol/` is reused; the kernel lock is taken before `establish`.

- Modify: `src/huron/core/integrity/models.py` (`bind`: `report_path=f"reports/{sequence:06d}.json"`
  and the `sequence` docstring line — T2 §1 "`models.py:269`");
  `src/huron/core/integrity/cutover.py`: `prepare` order `authenticate → grant check →
  claim() → establish → root/operator compare → _prepare_owned`, claim released before the
  trailing `certify` (which stays until M4); `_record` allocates `sequence` via
  `_next_sequence`/`_occupied` (verbatim, `itertools.count`) under the claim and publishes
  `reports/{sequence:06d}.json` then `{sequence:06d}.json`; `prepare`'s docstring becomes
  T2 §1's text minus the sentence "an invocation that does not return ends its own epoch"
  (added in M4); `src/huron/applications/lakectl/controller.py` `_validate_evidence` reads
  `protocol/reports/{transition.sequence:06d}.json`.
- Delete: `_transition` and the same-run reuse; the `f"reports/{run_id}.json"` paths; the
  "crash can repeat this operation with the same run" docstring sentence.
- Design basis: T2 §1, §2 "Order and spans" (claim span), "Sequence invariant",
  "Concurrency"; T2 §3; T2 §8 (T1, T3a).
- Acceptance: no `run_id` appears in any `protocol/` path (`grep -n "run_id}" src/huron`
  empty); `radon`/`complexipy` clean.
- Dependencies: M1.

Status: complete

#### Task M2.2 — Sequence and path expectations in the unit tests

Intent: tests assert appends, not replays.

- Modify: `tests/unit/test_integrity_cutover.py`: report paths `:121,:193,:278,:302,:316`
  → `reports/000001.json`; `:126` second `prepare` → `sequence == 2`, `report_path ==
  "reports/000002.json"`, both `000002` files exist, `000001.json` bytes unchanged (rename
  to `test_cutover_writes_bound_report_before_record_and_a_second_run_appends`); `:201–224`
  → `test_stranded_report_is_history_and_retry_appends` (retry `sequence == 2`,
  `000001.json` still absent, `reports/000001.json` bytes unchanged); `:332` → 2 for both
  parameters, `:334` third `prepare` `sequence == 3` and `!= result`; `:373` → `sequence
  == 2`; `:398` → retry `sequence == 2`; `:468` → `sequence == 2`; the three write
  interceptors keyed on `"000001.json"` unchanged. Generation and `abandoned` assertions
  are M4's. `tests/unit/test_controller_certificates.py` `prepared` writes the report at
  `record.report_path`. `tests/controlled_deployment.py`: any `reports/{run_id}` reference
  (grep) → sequence form.
- Design basis: T2 §8 (T5b) items (a)–(h) sequence parts and (l); T5b §1 table (names).
- Acceptance: `test_integrity_cutover` collects 25 and passes; unit total unchanged (1643
  expected); `test_independent_cutovers_cannot_share_a_live_same_run_owner` still raises
  `BlockingIOError` (now before `establish`).
- Dependencies: M2.1.

Status: complete

#### Task M2.3 — Milestone gate and evidence

- §5 recipe into `p3-evidence/m1b-authority/m2-sequencing/`; same acceptance as M1.7.

Status: complete

### M3 — Operator `--validate` path

Status: complete

#### Task M3.1 — Client reply parsing

Intent: a lost or truncated reply is a transport failure, never a parse of half a message.

- Modify: `src/huron/applications/lakectl/exclusion.py`: module-level `_reply(payload)`
  verbatim from T3b §1 (bound check before newline check); `_call` returns
  `_reply(response.readline(65537))`.
- Delete: the inline reply tail; the `KeyError`/`TypeError` a non-object reply raised.
- Design basis: T3b §1 "`exclusion.py`", §2 "Client error mapping".
- Dependencies: none.

Status: complete

#### Task M3.2 — `wiring.validate` and the `--validate --sequence N` command

Intent: one composition root serves both entry points; the CLI resolves a lost reply
without a rescan.

- Modify: `src/huron/applications/lakectl/wiring.py` (`prepare`, `validate`, `_deployment`
  verbatim; `ProtocolTransition` becomes a runtime import; `prepare`'s `Raises` section
  deleted with its `raise` statements); `src/huron/applications/lakectl/main.py`
  (mutually exclusive `--prepare`/`--validate`, `--sequence` with `_sequence`, the pairing
  check through `cutover.error`, the `validate` branch printing `canonical`; the
  `CertificationIndeterminateError` branch stays until M4).
- Delete: `wiring.py`'s inline composition; `main.py`'s `required=True` on `--prepare` and
  the bare `else`.
- Design basis: T3b §1 "`wiring.py`", "`main.py`", "Exact argparse surface", "Exit codes";
  §2 "Wiring and CLI"; §5 second bullet (why not composed in `main.py`).
- Acceptance: `uv run lakectl protocol cutover --help` lists `--prepare`, `--validate`,
  `--sequence`; `pydoclint` silent.
- Dependencies: M3.1 (shared file set only).

Status: complete

#### Task M3.3 — Tests for the operator path

- Modify: `tests/unit/test_controller_transport.py` (socket-free
  `test_reply_maps_bound_newline_shape_and_refusal[8]` over `_reply`, T5a's table);
  `tests/unit/test_lakectl_wiring.py` (`test_wiring_validates_a_stored_record_through_the_same_boundaries`);
  `tests/unit/test_lakectl_main.py` (`test_validate_command_prints_the_admitted_record_and_refuses_an_absent_sequence`,
  `test_cutover_usage_errors_exit_two[8]` with `raising` guards on `cli.prepare`/`cli.validate`
  — add the `raising` helper to `tests/unit/test_managed_controller.py` now, verbatim
  from T5a §1 (its designed home), and import it here; `generation_on_disk` waits for M4).
  `test_command_failures_do_not_echo_connection_material` unchanged.
- Design basis: T5a §1 "`test_controller_transport.py`" (new socket-free test),
  "`test_lakectl_wiring.py`", "`test_lakectl_main.py`"; T3b §8 (T5a).
- Acceptance: `wiring.py`, `main.py`, `exclusion.py` at 100%; `--co`: wiring 3, main +9,
  transport +8; unit total 1661 expected.
- Dependencies: M3.1, M3.2.

Status: complete

#### Task M3.4 — Milestone gate and evidence

- §5 recipe into `p3-evidence/m1b-authority/m3-validate-path/`; acceptance as M1.7.

Status: complete

### M4 — The epoch cutover (atomic)

Status: complete

This milestone is the one change that cannot be split green: `certify`/`validate_certificate`
→ `abandon`/`validate` runs through port, coordinator, client, server and controller at
once. Work strictly in the order below; the tree is red between tasks and green at M4.9.
Everything additive (the observation matrix, composition tests, extra controller tests,
extra malformed payloads) is M5, not here.

#### Task M4.1 — `WriterExclusion` contract and the deleted error

- Modify: `src/huron/core/integrity/ports.py` (`WriterExclusion` four methods verbatim
  from T1 §1); `src/huron/core/integrity/models.py` (delete `CertificationIndeterminateError`).
- Design basis: T1 §1 "`ports.py`", §2 "Error classes at the ports", "Lifecycle", §3.
- Dependencies: M1–M3.

Status: complete

#### Task M4.2 — Coordinator: abandon on failure, validate after release

- Modify: `src/huron/core/integrity/cutover.py`: `prepare` = T2 §1 verbatim (`claim →
  establish → _abandoning → compare → _prepare_owned`, then `await self._writers.validate(result)`
  outside the claim; the docstring sentence deferred from M2 added now); `validate` =
  T2 §1 verbatim (`writers.validate(transition)`, new messages); `_abandoning`
  (`@asynccontextmanager`, `except BaseException`, `suppress(Exception)` around `abandon`,
  re-raise); imports `asynccontextmanager, suppress`, `AsyncIterator` under `TYPE_CHECKING`.
- Delete: `certify`/`validate_certificate` calls; the "certificate" wording in docstrings
  and the two `PermissionError` messages.
- Design basis: T2 §1, §2 "Order and spans" (abandon span, outside both), the epoch table,
  "Error text"; T2 §5 (why a private context manager); T2 §8 (T3a, T3b).
- Dependencies: M4.1.

Status: complete

#### Task M4.3 — Controller epoch mechanics

- Modify: `src/huron/applications/lakectl/controller.py` to T3a §1 verbatim: `__init__`
  (`_load_state`, `_check_volume`, `_advance`), `restart`/`describe` under `_observing`,
  `establish` (three guarded spans, `_advance(run_id=…, operator=…, writers=…, database=…)`,
  per-call `writers`), `check` (guarded observation, pure comparisons, three messages),
  `abandon`, `validate`, `_validate_evidence` (claim span over exactly the two `_stored`
  reads, then pure refusals, then guarded `roles.check`), `_load_state` (no mint),
  `_advance` (`try/finally`), `_persist(state)`, `_observing`, `_live`, `_evidence`,
  module-level `_stored`. `settings.py` needs no further change.
- Delete: T3a §3 in full (`_certificate` and its six touch points, `certify`,
  `validate_certificate`, `check`'s `try/except`, the cumulative union, the conditional
  mint, the `_load_state` mint, the old `run_id` message).
- Design basis: T3a §1, §2 (I1–I5, the entry point × failure table, the four `_advance()`
  sites, `_validate_evidence` step order, "Messages tests may match on"), §3; T2 §8 (T3a);
  T3b §8 (T3a).
- Acceptance (checked in M4.9): exactly four `_advance()` call sites; `self._state` is
  assigned only in `__init__` and `_advance`'s `finally`; `radon cc --min C` and
  `complexipy` clean without helper extraction that hides domain structure.
- Dependencies: M4.1.

Status: complete

#### Task M4.4 — Server and client rename; CLI branch deletion

- Modify: `src/huron/applications/lakectl/server.py` (`handle` with `except Exception`;
  `_dispatch` and `_require_request_fields` verbatim from T3b §1);
  `src/huron/applications/lakectl/exclusion.py` (`abandon`, `validate` verbatim);
  `src/huron/applications/lakectl/main.py` (delete the `CertificationIndeterminateError`
  import and branch; `main()` equals T3b §1's listing).
- Delete: `server.py`'s `asyncpg`/`httpx` imports and four-class tuple, the
  `certify`/`validate_certificate` branch and field entries; `exclusion.py`'s `asyncio`
  import, `certify` with the indeterminate mapping, `validate_certificate`.
- Design basis: T3b §1 (server, `exclusion.py` methods, `main.py`), §2 "Server", §3; T3a
  §8 (T3b).
- Acceptance: `grep -rn "certify\|validate_certificate\|CertificationIndeterminateError\|indeterminate" src/huron`
  empty; `ControllerClient` satisfies `MaintenanceAuthority` and `WriterExclusion` (`mypy src`).
- Dependencies: M4.1–M4.3.

Status: complete

#### Task M4.5 — Core test double and cutover semantics

- Modify: `tests/unit/test_integrity_cutover.py`: `DeploymentBoundary` verbatim from T5b
  §1 (start receipt generation 1, `_advance`, `check` advancing on `valid == False`,
  `abandon` recording and advancing only for the live receipt, `validate`); the two
  subclasses delegate via `super().check(evidence)`; every row of T5b's edit table
  (generation numbers, `abandoned`, `excluded`, `match` strings, renames
  `test_failed_directory_sync_leaves_a_complete_record_that_no_epoch_admits`); module
  docstring.
- Delete: T5b §3's `test_integrity_cutover.py` items.
- Design basis: T5b §1 (`DeploymentBoundary`, edit table), §2 "`DeploymentBoundary`
  invariants", rulings 1–2; T5b §3.
- Acceptance: 25 collected, all pass; no `"endorsement"`, `"certificate"`, `"replay"` in
  the file.
- Dependencies: M4.2.

Status: complete

#### Task M4.6 — Controller tests: `test_managed_controller.py` and `test_controller_epoch.py`

- `git mv tests/unit/test_controller_certificates.py tests/unit/test_controller_epoch.py`.
- Modify: `tests/unit/test_managed_controller.py` (`generation_on_disk` helper verbatim;
  `raising` exists since M3.3; `:105–107` adds `generation_on_disk(...) == evidence.generation`; `:109` same-run
  re-`establish` mints `generation + 1`, `terminated_writers == ()`, old receipt →
  `"generation changed"`; `:113` `match="another maintenance operator"` on the live receipt);
  `tests/unit/test_controller_epoch.py` (header docstring; `prepared` verbatim — async,
  `database_boundary` first, report at `record.report_path`, `validate` once;
  `test_mismatched_receipt_is_refused_without_ending_the_epoch[peer, operator, run,
  absent, record, report]`; `test_complete_record_validates_repeatedly_and_a_restarted_controller_refuses_it`;
  `test_abandon_ends_only_the_live_epoch`).
- Delete: T5a §3's `test_controller_certificates.py` items (all old tests; the observation
  faults return in M5 as the matrix).
- Design basis: T5a §1 ("Doubles and helpers", the `test_managed_controller.py` table,
  "`test_controller_epoch.py`" fixture, mismatch matrix table, "Remaining named tests"),
  §2 (`generation_on_disk`, `raising`, "Messages matched", "Fixture lifecycle"), §3.
- Acceptance: named tests present; `controller.py` at 100% (the `_observing` except path
  is executed by `test_surviving_or_reappearing_writer_invalidates_exclusion`; `_stored`'s
  `None` branch by `absent`; `abandon`'s both branches by `test_abandon_ends_only_the_live_epoch`);
  no test reads `_state` or any private attribute.
- Dependencies: M4.3, M4.4.

Status: complete

#### Task M4.7 — Transport, wiring and CLI tests

- Modify: `tests/unit/test_controller_transport.py` (`…_authenticates_describes_establishes_and_checks_real_requests`
  gains `abandon` over the wire, on-disk advance and a refused `check`;
  `test_real_transport_validates_exact_durable_evidence`;
  `test_lost_reply_is_resolved_by_validating_again` via a dropped
  `socketserver._SocketWriter.write`); `tests/unit/test_lakectl_wiring.py`
  (`ControllerBoundary.abandon`/`validate` with `abandoned`; `test_wiring_runs_actual_core…`
  asserts `controller.abandoned == []`); `tests/unit/test_lakectl_main.py` (delete the
  `lost_acknowledgement` parametrization, `AcknowledgementBoundary` and the `"indeterminate"`
  assertions; `test_cutover_command_prints_the_exact_canonical_transition` unparametrized).
- Delete: T5a §3's transport, main and wiring items.
- Design basis: T5a §1 ("`test_controller_transport.py`" first three bullets,
  "`test_lakectl_wiring.py`", "`test_lakectl_main.py`"), §3; T3b §8 (T5a).
- Acceptance: `server.py`, `exclusion.py`, `main.py`, `wiring.py` at 100%;
  `grep -rn "endorsement\|indeterminate\|certificate" tests/unit` empty.
- Dependencies: M4.4.

Status: complete

#### Task M4.8 — Linux deployment script: validate twice, observe the advance

- Modify: `tests/controlled_deployment.py`: `_generation_on_disk(settings)` helper
  (local import of `ControllerState`); `:480–500` per T5b's table (`prepare`, `check`,
  `validate` twice, generation unchanged, `ALTER ROLE new_app LOGIN` → `PermissionError`
  and generation +1, `NOLOGIN` → still refused and unchanged, fresh `prepare` → `sequence
  == 2`, `validate`); `:503–510` `before = _generation_on_disk(settings)` before
  `process.terminate()` and `== before + 1` after `_await_controller`.
- Delete: the four `validate_certificate` calls and the `"revived endorsement"` text.
- Design basis: T5b §1 (`tests/controlled_deployment.py` table), §2 "contract with the
  daemon", §3; T3a §8 (T5b).
- Acceptance: `uv run pytest -q --co -m integration` → 14; the script imports and compiles
  (`uv run python -c "import ast,sys; ast.parse(open('tests/controlled_deployment.py').read())"`);
  the `print` markers asserted by `tests/integration/test_protocol_cutover.py` unchanged.
  Executed in M6.
- Dependencies: M4.4.

Status: complete

#### Task M4.9 — Milestone gate and evidence

- §5 recipe into `p3-evidence/m1b-authority/m4-epoch-cutover/`.
- Acceptance: unit green (1659 expected), coverage ≥ floor (ratchet raised if exceeded),
  all 17 M1b files at 100%; `make lint` exit 2 at duplication only;
  `grep -rn "certify\|validate_certificate\|CertificationIndeterminateError" src tests --include='*.py'`
  empty; `git status` shows the rename as `R` and only the intended files.

Status: complete

### M5 — Epoch behaviour proofs

Status: complete

#### Task M5.1 — Observation matrix and remaining controller tests

- Modify: `tests/unit/test_controller_epoch.py` (`observation_fault(...)` helper and
  `test_failed_observation_ends_the_epoch_before_the_refusal[engine_connect,
  engine_inventory, foreign_writer, volume_identity, database_identity, sql_error,
  sql_pool, store_owner, cancelled]` per T5a's table: class unchanged, exactly one on-disk
  advance, then `"generation changed"`, refusal pure, `describe` still answers);
  `tests/unit/test_managed_controller.py`
  (`test_establish_mints_before_terminating_and_a_survivor_ends_the_new_epoch`,
  `test_engine_failure_during_describe_or_restart_ends_the_epoch[describe, restart]`,
  `test_check_and_abandon_refuse_before_any_epoch_is_established`).
- Design basis: T5a §1 (observation matrix table, "Implementation shape", the three
  dedicated `test_managed_controller.py` tests), §2 "Kernel interceptors" not needed here.
- Acceptance: the three former repro behaviours are refused with the design's messages —
  repro 1 (`test_observed_unreachable_engine_permanently_revokes_receipt`) →
  `[engine_connect]`: `httpx.ConnectError` propagates, then `validate` raises
  `ValueError("controller exclusion generation changed")`; repro 2
  (`…changed_maintenance_database_configuration…`) → `[database_identity]`:
  `ValueError("maintenance database identity differs from the fence")` then
  `"generation changed"`; repro 3 (`…revoked_receipt_cannot_be_reendorsed…`) →
  `[foreign_writer]`: `"foreign writer"` then `"generation changed"` with no operation
  able to re-admit (the `certify` operation no longer exists; M5.2 proves the server
  refuses it). `p3-evidence/m1b/verification3/test_authority_repro.py` stays an untouched
  historical receipt and is never collected.
- Dependencies: M4.

Status: complete

#### Task M5.2 — Composition tests with kernel interceptors; deleted-operation payloads

- Modify: `tests/unit/test_controller_epoch.py` (`LocalControllerTransport`, `composed`
  fixture verbatim — imports `EmptyCatalog` from `test_integrity_cutover`;
  `test_interrupted_prepare_ends_the_real_controllers_epoch[post_install_fsync,
  release_fence_loss]`; `test_lost_return_after_release_keeps_the_record_admissible`);
  `tests/unit/test_controller_transport.py` (`test_server_refuses_malformed_oversized_and_actor_supplied_requests`
  gains `{"operation":"certify","transition":{}}` and `{"operation":"validate","transition":{}}`).
- Design basis: T5a §1 "Composition (no socket)", §2 "`LocalControllerTransport`",
  "Kernel interceptors"; §6.1; T5a §8 (T2).
- Acceptance: interceptors key on the `protocol/` directory inode and the lock inode only
  (the controller's `_persist` is never faulted); `generation_on_disk` 3 / 3 / 2 for the
  three composition outcomes; next `prepare` returns sequence 2, generation 4.
- Dependencies: M5.1.

Status: complete

#### Task M5.3 — Milestone gate and evidence

- §5 recipe into `p3-evidence/m1b-authority/m5-behaviour-proofs/`; unit total 1677
  expected; per-module `--co` reconciled in the report against the named-test counts
  25 / 20 / 25 / 3 / 18 (`test_managed_controller`, `test_controller_epoch`,
  `test_controller_transport`, `test_lakectl_wiring`, `test_lakectl_main`; sum 91; unit
  total ≈1677 unchanged) rather than the design's 26 / 21 / 22 / 3 / 19:
  `test_server_refuses_malformed_oversized_and_actor_supplied_requests`
  (`tests/unit/test_controller_transport.py:96`) is parametrized, so M5.2's two payloads
  add two collected items. Presence of every named test is the hard criterion; the counts
  are reconciliation aids, not gates.

Status: complete

### M6 — Contract and integration on disposable containers

Status: complete

#### Task M6.1 — Contract suite (PostgreSQL testcontainer)

- Run `uv run pytest -q -m contract` (49 expected) with a disposable
  `PostgresContainer("postgres:16")` per test function. If M1.6 deferred the T4 §6.1
  decision, apply T5b §2's rule now; a contingency is one change set (query, pattern,
  `IDENTITY`, routing token, contract `expected`/regex, ADR consequence) followed by the
  full unit gate again.
- Design basis: T5b §1 (contract), §2 "Decision rule"; T4 §6.1, §7 "Not tested".
- Acceptance: `contract.log` exit 0; `test_identify_binds_cluster_and_database_and_refuses_a_foreign_fence`
  passes as the non-superuser `probe`; `podman ps` shows nothing left running.

Status: complete

#### Task M6.2 — Integration suite (Linux, Podman, `controlled_deployment.py`)

- Run `uv run pytest -q -m integration -s` (14 expected). The script's new assertions
  (`validate` twice, advance after a real SQL loss, pure refusal, `sequence == 2`, restart
  delta) are the integration-level form of the `database_identity` row.
- Design basis: T5b §1 (`tests/controlled_deployment.py`), §2 "contract with the daemon".
- Acceptance: `integration.log` exit 0; all `print` markers observed; cleanup logged.

Status: complete on the runnable subset (13 of 14); the deployment-script node is unrunnable on this host (no root/`sudo -n`, no Podman) and is recorded as an environment gap in `p3-evidence/m1b-authority/m6-containers/environment.md`

#### Task M6.3 — Milestone gate and evidence

- §5 recipe into `p3-evidence/m1b-authority/m6-containers/` plus `contract.log`,
  `integration.log`, `podman-before.log`, `podman-after.log`, `df.log`.

Status: complete

### M7 — Documentation reconciliation (T6)

Status: complete

#### Task M7.1 — Apply the literal edit list

- Modify: `P3_DESIGN.md` (T6 §1.1, texts A–C), `docs/operations/controlled-cutover.md`
  (§1.2, texts D–E), `P3_M1B_VALIDATION.md` (§1.3), `P3_EXECUTION.md` (§1.4, texts F–G, the
  2026-09-12 entry), `P3_IMPLEMENTATION_PLAN.md` (§1.5, including M1c item 1's single drift
  statement and the `### Resolution` subsection), `design/layer-raw.html` (§1.6),
  `design/core-map.html` (§1.7; then `git add design/core-map.html`), `CONTEXT.md` (§1.8).
  Re-pin every locator with T6 receipt R4's method first. Replacements are literal (T6 §2).
- Delete: T6 §3's sentences and symbols.
- Design basis: T6 §1.0 rules, §1.1–§1.9, §2, §3.
- Verification: `make docs` exit 0; the two §2 invariant greps (status, banned senses)
  match exactly the residual historical lines T6 §2 lists; `git diff --check`.
- Acceptance: no document claims implementation or verification status beyond "designed"
  and "delivery tracked by this plan"; `grep -c "M1c item 1"` finds the cross-references
  and exactly one drift statement.
- Dependencies: M4 (message strings exist), M6.

Status: complete

#### Task M7.2 — Milestone gate and evidence

- §5 recipe (unit + lint unchanged from M5; `docs.log`; the two grep logs) into
  `p3-evidence/m1b-authority/m7-docs/`.

Status: complete

### M8 — Final full gate, ratchet and report

Status: complete

#### Task M8.1 — Full gate on the final tree

- Run, in order, capturing each log and exit code: `uv run pytest -q tests/unit
  --cov=src/huron --cov-report=term-missing --cov-report=json:p3-evidence/m1b-authority/m8-final/coverage.json`;
  `make lint`; `uv run --locked python scripts/check_duplication.py src`;
  `uv run pytest -q -m contract`; `uv run pytest -q -m integration -s`; `df -h .` then
  `make test-acceptance` if ≥ 25 GiB free (else record the gap); `make docs`;
  `git diff --check`; `--co` for unit/contract/integration; `git status --porcelain`.
- Ratchet: if TOTAL > `fail_under`, set `fail_under` to the measured value rounded down to
  two decimals in `pyproject.toml` and rerun the unit command.
- Acceptance: every command exit 0 except `make lint`/`check_duplication.py` (duplication
  only, score recorded and ≥ M0's 60 minus the effect of added lines, reported not gated);
  all 17 M1b files plus every new production file at 100%; unit ≈1677, contract 49,
  integration 14.

Status: complete

#### Task M8.2 — Report and ledger

- Create `p3-evidence/m1b-authority/m8-final/report.md`: per-milestone attempt counts,
  gate outputs, coverage at baseline and completion, native duplication score at baseline
  and completion, the three repro behaviours and the tests that refuse them, the T4
  decision taken, acceptance run or gap, and the statement that independent verification
  has not started.
- Modify: `P3_EXECUTION.md` — append one dated line under T6's 2026-09-12 section:
  implementation plan executed, evidence at `p3-evidence/m1b-authority/`, independent
  verification not started (no other status claim, per T6 §1.0 "Status").
- Acceptance: `git status --porcelain` = rule 7's list + this plan's intended files +
  `p3-evidence/m1b-authority/`; nothing committed.

Status: complete

## 5. Evidence capture

Every milestone writes `p3-evidence/m1b-authority/<milestone>/` following the
`p3-evidence/m1b/` file convention: each command's stdout+stderr in `<name>.log` paired with
its exit code in `<name>.exit`, pytest's `coverage.json`, and a source inventory (the
existing runs keep `source-inventory*.json`/`artifact-hashes.json`; this plan records
`source-inventory.sha256` instead, so the layout is the same convention, not a mirror).
Directory names:
`m0-baseline`, `m1-identity`, `m2-sequencing`, `m3-validate-path`, `m4-epoch-cutover`,
`m5-behaviour-proofs`, `m6-containers`, `m7-docs`, `m8-final`. Recipe (run from the root;
`E` is the directory):

```sh
E=p3-evidence/m1b-authority/<milestone>; mkdir -p "$E"
git rev-parse HEAD > "$E/head.txt"; git status --porcelain > "$E/git-status.log"
uv run pytest -q tests/unit --cov=src/huron --cov-report=term-missing \
  --cov-report=json:"$E/coverage.json" > "$E/unit.log" 2>&1; echo $? > "$E/unit.exit"
make lint > "$E/lint.log" 2>&1; echo $? > "$E/lint.exit"
uv run --locked python scripts/check_duplication.py src > "$E/duplication.log" 2>&1; echo $? > "$E/duplication.exit"
git diff --check > "$E/diff-check.log" 2>&1; echo $? > "$E/diff-check.exit"
{ uv run pytest -q --co tests/unit | tail -1; uv run pytest -q --co -m contract | tail -1; \
  uv run pytest -q --co -m integration | tail -1; } > "$E/collect.log" 2>&1
find src/huron tests -name '*.py' -not -path '*__pycache__*' -print0 | sort -z | xargs -0 sha256sum > "$E/source-inventory.sha256"
```

Milestones that run containers or docs add `contract.log`, `integration.log`,
`acceptance.log`, `docs.log`, `podman-before.log`, `podman-after.log`, `df.log`, each with
its `.exit`. M8 adds `report.md`. Evidence files are never edited after capture.

## 6. Risk register

| # | Change | Symptom | Decision point and fallback |
| --- | --- | --- | --- |
| 1 | `pg_control_system()` privilege for the deployed role (T4 §6.1) | `asyncpg.InsufficientPrivilegeError` at the `probe` `identify()` in the contract test | M1.6 if a runtime is available, else M6.1. Fallback is the contingency as one change set (query, T1 pattern, `IDENTITY`, routing token, test expectation, ADR consequence); any other failure is an adapter defect, never a fallback trigger |
| 2 | `claim()` before `establish` (T2 §2) | `test_independent_cutovers_cannot_share_a_live_same_run_owner` or `controlled_deployment.py`'s foreign-claim checks see an `establish` before the `BlockingIOError`, or the controller's own `claim()` in `_validate_evidence` contends with the coordinator's | M2.2 / M4.3. `prepare` must release its claim before `validate`; the controller's claim spans exactly the two reads. If contention appears, the design's ordering is wrong and the milestone escalates — do not widen or narrow the claim ad hoc |
| 3 | `asyncio.run` per request with a lazily created pool (T3a §2 "Pool and settings lifecycle") | `RuntimeError: Event loop is closed` or a pool bound to a dead loop if any pool outlives its request; unpatched construction tests opening a pool | M1.4. No pool is created outside `_database()`; `create_pool` stays a single positional call so `lambda url: EmptyDatabaseBoundary()` patches hold. If a loop error appears, the pool escaped its request — fix the scope, never share a loop |
| 4 | Coverage ratchet after deletions (rule 4) | TOTAL below 95.88 although every touched file is at 100%: deleting fully covered lines lowers the ratio (≈0.0006 pp per line; a net deletion of ~70 lines breaches the floor) | Every milestone's gate. Never lower the floor or add pragmas; cover currently-missed lines in the modules the milestone already touches, or add direct unit tests for missed lines in adjacent production modules without changing production code. Raise the floor when the run exceeds it |
| 5 | M4 is atomic and near the size ceiling | Verification attempt 3 fails on incompleteness rather than defects | M4.9. No fourth pass; escalate per `implement-markdown.md` with the escalation report naming which of M4.1–M4.8 were complete. Do not pull M5 content forward |
| 6 | Untracked `design/core-map.html` and other user working-tree changes (rule 7) | The docs milestone stages or edits `design/index.html`, `.opencode/*` or other user files; or `core-map.html` is left untracked after edit | M7.1. Edit only the T6 §1.7 rows; `git add design/core-map.html` only; `git status --porcelain` is the acceptance check |
| 7 | Kernel interceptors keyed by inode (T5a §2) | Composition tests flake or fault the controller's `_persist` | M5.2. Trigger only when `os.fstat(fd).st_ino` equals the `protocol/` directory or lock inode and `protocol/000001.json` exists; install under `monkeypatch.context()` around one `prepare` only |

## 7. Definition of done

- The three verification-3 repro behaviours are refused: an observed engine transport
  failure, a changed maintenance database identity and an observed foreign writer each
  advance the generation on disk before the refusal and every later `validate` raises
  `ValueError("controller exclusion generation changed")`; no operation re-admits a record
  under an ended epoch (`certify` does not exist; the server answers `CONTROLLER_REFUSED`).
  Evidence: M5.1's matrix rows `[engine_connect]`, `[database_identity]`, `[foreign_writer]`
  and M5.2's payload test.
- `certify`, `validate_certificate`, `CertificationIndeterminateError`, the endorsement
  state, the same-run reuse and every two-parameter `exclude`/`check` are gone from `src`
  and `tests`; the fence carries `database`; both protocol schemas equal the model under
  the unchanged `$id`s; every `prepare` appends `reports/{N:06d}.json` and `{N:06d}.json`.
- All suites pass on the final tree: unit (≈1677, coverage ≥ the ratcheted floor, all 17
  M1b files and every new production file at 100%), contract (49), integration (14), and
  acceptance if ≥ 25 GiB was free (otherwise the gap is recorded in `report.md`).
- `make lint` passes every step except the recorded duplication exception (native score
  measured and reported at ≥ 90 not required; the 60/100 baseline and the final score are
  both in `report.md`); `make docs` strict build passes; `git diff --check` is clean.
- Evidence exists under `p3-evidence/m1b-authority/` for M0–M8 per §5, with `report.md`
  in `m8-final/`; `P3_EXECUTION.md` carries T6's entry plus M8.2's line.
- The working tree shows only this plan's intended files plus rule 7's pre-existing user
  changes; nothing is committed or pushed.
- **M1b remains unverified.** This plan ends with the implementation's own gate. Independent
  verification is `/implement-markdown`'s verification subagent per milestone and a final
  independent pass; no document written by this plan claims "verified".

## Verification

Cycle 1 of 2, 2026-09-12, against HEAD `e22d000` (read-only; no source, test, design or
documentation file changed; Podman and PostgreSQL not started). Method: both documents read
in full; every design `§1/§2/§3/§8` item mapped to a plan task and every plan task checked
for a cited design heading; M1–M3 traced concretely against the current bodies of
`cutover.py`, `controller.py`, `server.py`, `wiring.py`, `main.py` and the five test doubles
under the changed `DatabaseExclusion` port and required `FenceEvidence.database`; every
command, marker, threshold, path and line pin the plan relies on checked by execution.

### Defects

1. **Blocking — M1.5 leaves `test_integrity_cutover.py` red through M1–M3.**
   `DeploymentBoundary.certify` (`tests/unit/test_integrity_cutover.py:66`) and
   `validate_certificate` (`:71`) call `await self.check()` with no argument. M1.5 replaces
   `check(self, *arguments)` with `check(self, evidence)` and keeps `certify`/
   `validate_certificate` until M4.5, and `CutoverService.prepare` keeps its trailing
   `certify` call through M3 (`cutover.py:105`, deleted only at M4.2). Every cutover test that
   reaches `certify` or `validate_certificate` therefore raises `TypeError` at the M1.7 gate,
   and the same failure persists at M2.3 and M3.4. Correction: M1.5 must state that the two
   retained double methods become `await self.check(transition.fence)` (the receipt
   comparison itself still arrives with the T5b `check` body in M4.5; design basis T5b §1
   "`validate(transition)` is `await self.check(transition.fence)`", T1 §8 (T5b)). The two
   subclass overrides (`:415`, `:529`) need only the signature change M1.5 already names.

2. **Non-blocking — M5.3 per-module targets are the design's figures and do not follow from
   the design's own test inventory.** `test_server_refuses_malformed_oversized_and_actor_supplied_requests`
   is parametrized (`tests/unit/test_controller_transport.py:96`), so M5.2's two payloads
   add two collected items; counting the named tests gives `test_managed_controller` 25,
   `test_controller_epoch` 20, `test_controller_transport` 25, `test_lakectl_wiring` 3,
   `test_lakectl_main` 18 (sum 91; unit total 1677 unchanged, so M3.3's 1661, M4.9's 1659
   and §4's ≈1677 all hold). Correction: replace "26 / 21 / 22 / 3 / 19" in M5.3 with
   "25 / 20 / 25 / 3 / 18" so the reconciliation step is not chasing phantom tests.

### Milestone trace

- **§3's claim that the suggested M1 is red is confirmed**: `cutover.py:128,212` and
  `controller.py:213–215` are two-parameter calls; `controller.py:294–305` `_evidence()`
  omits `database`; `server.py:87` calls `establish` synchronously. M1 as planned changes
  every one of those sites in the same milestone.
- **M1** (after defect 1 is corrected): `controller.check` short-circuits on `run_id is None`
  (`controller.py:158`) before `_evidence()`, so a pre-`establish` state with `database=None`
  is never validated; the transport tests at `:205–266` already patch `create_pool` inline and
  use `record.report_path`; `test_lakectl_main.py` reaches `FenceEvidence` only through
  `ControllerBoundary` (`test_lakectl_wiring.py:81`), which M1.5 edits; the three
  `FenceEvidence(` sites under `tests/` are all named by M1.2/M1.5; the port/adapter
  parameter types are structurally compatible per T1 R4/T4 R3. No other red path found.
- **M2**: no test under `tests/` hard-codes `reports/<uuid>` except
  `test_integrity_cutover.py:316` (named in M2.2); `test_controller_certificates.py` and both
  transport tests write `record.report_path`, so `bind`'s change and the controller's
  `reports/{sequence:06d}.json` read move together; `tests/controlled_deployment.py`
  contains no `reports/` literal. `ProtocolTransition` stays a runtime import in `cutover.py`
  (`bind` in `_record`). Traces green.
- **M3**: `wiring.validate` → `CutoverService.validate` → `writers.validate_certificate`,
  a no-op on `ControllerBoundary` (`test_lakectl_wiring.py:97`), so both new M3.3 tests pass
  before M4; `main.py`'s retained `CertificationIndeterminateError` branch stays covered by
  the `lost_acknowledgement=True` case until M4.7 deletes both. Traces green.
- **M4** is atomic by construction; M4.6's 100% claim for `controller.py` holds under line
  coverage (`_live` is one line; `abandon`'s ignored branch has no separate line).
- Deletions map: T1 §3 → M1.1/M4.1; T2 §3 → M1.4/M2.1/M4.2; T3a §3 → M1.4/M2.1/M4.3;
  T3b §3 → M3.1/M3.2/M4.4; T4 §3 → M1.3; T5a §3 → M4.6/M4.7; T5b §3 → M1.5/M1.6/M2.2/M4.5/M4.8;
  T6 §3 → M7.1. Every §8 handoff has a receiving task; every task cites a design heading.

### Receipts

| Command | Observed |
| --- | --- |
| `uv run pytest -q --co tests/unit \| tail -1` | `1634 tests collected` |
| `uv run pytest -q --co -m contract \| tail -1` | `48/1697 tests collected` |
| `uv run pytest -q --co -m integration \| tail -1` | `14/1697 tests collected` |
| per-module `--co` | adapters 17, managed_controller 21, integrity_cutover 25, controller_certificates 9, transport 15, wiring 2, main 10, protocol_documents 18 |
| `pyproject.toml` | markers `unit/contract/integration/acceptance` registered; `addopts="-m unit --strict-markers"`; `[tool.coverage.report] fail_under = 95.88` (`:261`); `[project.scripts] lakectl` (`:33`) |
| `Makefile` | `lint` = ruff, ruff format, pydoclint, `mypy`, `ty check`, lint-imports, `check_schema_map.py`, radon cc/mi, complexipy, `pyscn check src`, `check_duplication.py src`; `test-acceptance` exists; `docs` = `zensical build --strict` |
| `scripts/` | `check_duplication.py` (positional package, exit 0/1/2, threshold 90), `check_schema_map.py`, `main.py` (untracked, user's) present |
| `p3-evidence/m1b/` | `attempt1 fix1 fix2 verification1 verification2 verification3`; `.log`/`.exit`/`coverage.json` convention present (18 `.exit` files); `verification3/test_authority_repro.py` exists |
| `git rev-parse HEAD` | `e22d0003…` — design and plan locators are pinned to the current tree |
| 37 `sed -n` pins (`controller.py:213–215`, `cutover.py:128,212`, `models.py:224,269`, `generations.py:24`, `test_managed_controller.py:105,109,113`, `test_integrity_cutover.py:121,126,193,201,278,302,316,332,334,373,398,468`, `test_maintenance_adapters.py:64,84`, `controlled_deployment.py:365,375,482,500,503`, `test_controller_transport.py:205,236`, `test_lakectl_wiring.py:94`, `test_lakectl_main.py:15,58,70`, `test_controller_certificates.py:24`, `test_controller_settings.py:69`, `test_writer_exclusion.py:40,186`) | every line contains the text the plan or design quotes |
| `grep -rn 'reports/' tests --include='*.py'` | only `test_integrity_cutover.py:316` and `test_integrity_storage.py:111–117` (unrelated `reports/run.json`) |
| `grep -rn 'FenceEvidence(' tests --include='*.py'` | `test_integrity_cutover.py:33`, `test_lakectl_wiring.py:81`, `test_protocol_documents.py:32` |
| `grep -n 'self.check()' tests/unit/test_integrity_cutover.py` | `:66`, `:71` (defect 1) |
| `grep -n 'parametrize' tests/unit/test_controller_transport.py` | `:96` (`…malformed…`), `:176` (defect 2) |
| `ls src` | `huron` only — `check_duplication.py src` and `src/huron` analyse the same files |

### Observations

- §2 rule 2, §4 and the §5 recipe run `check_duplication.py src/huron` while `make lint`
  runs it on `src`; the file set is identical (`src/` holds only `huron/`), so the recorded
  score is one measurement, but saying so in rule 2 would remove the apparent mismatch.
- §5 says the evidence layout "mirrors `p3-evidence/m1b/`"; the existing runs keep
  `source-inventory*.json`/`artifact-hashes.json` rather than a `.sha256` listing. The
  recipe is executable as written; the mirroring claim is approximate, not load-bearing.
- M1.5's transport bullet ("tests that `establish` request `database_boundary`") applies in
  M1 only to `test_client_authenticates_describes_establishes_and_checks_real_requests`
  (`:63`); the two tests at `:205–266` already patch `create_pool` inline. The module will
  need `from tests.unit.test_managed_controller import database_boundary as database_boundary`
  (the pattern `test_controller_certificates.py:17` already uses); worth one clause.
- `make lint` invokes `uv run mypy`/`uv run ty check` without a path; `files=["src"]` and
  `include=["src"]` make the plan's `mypy src`/`ty check src` equivalent.
- Cycle verdict: **not VERIFIED** — one blocking defect (1) and one non-blocking (2).

### Fix pass 1

Applied 2026-09-12 to this file only (no source, test, design or documentation file
changed; Podman and PostgreSQL not started). The verifier's findings above are unchanged.

1. **Defect 1 (blocking) → M1.5**, `test_integrity_cutover.py` bullet: added the
   instruction that the retained `certify` (`:66`) and `validate_certificate` (`:71`)
   become `await self.check(transition.fence)` until M4.5, citing T5b §1 / T1 §8 (T5b);
   recorded that `RecoveringBoundary.check` (`:415`) and `ObservationBoundary.check`
   (`:529`) need only the signature change, and that `ControllerBoundary`
   (`test_lakectl_wiring.py:91–98`) and `AcknowledgementBoundary`
   (`test_lakectl_main.py:71`) need nothing (verified by `grep -n "check("` over the four
   test modules: `:66`/`:71` are the only no-argument `self.check()` calls).
2. **Defect 2 (non-blocking) → M5.3**, first bullet: "26 / 21 / 22 / 3 / 19" replaced by
   the named-test counts "25 / 20 / 25 / 3 / 18" (sum 91, total ≈1677 unchanged) with the
   parametrized `test_server_refuses_malformed_oversized_and_actor_supplied_requests`
   (`test_controller_transport.py:96`) named as the reason; named-test presence stays the
   hard criterion.
3. **Observation (a) → §2 rule 2, §4 gate block, M8.1, §5 recipe**: every
   `check_duplication.py src/huron` above the Verification section is now
   `check_duplication.py src`, matching `make lint`; rule 2 states that `src/` holds only
   `huron/`, so both are one file set and one measurement.
4. **Observation (b) → §5 first paragraph**: "mirroring `p3-evidence/m1b/`" reworded to
   describe the actual convention (`<name>.log` paired with `<name>.exit`, `coverage.json`,
   a source inventory; existing runs keep `source-inventory*.json`/`artifact-hashes.json`,
   this plan records `source-inventory.sha256`).
5. **Observation (c) → M1.5**, `test_controller_transport.py` bullet: names
   `test_client_authenticates_describes_establishes_and_checks_real_requests` (`:63`) as the
   one transport test needing `database_boundary` in M1 (`:205–266` already patch
   `create_pool` inline) and the required import
   `from tests.unit.test_managed_controller import database_boundary as database_boundary`
   beside the module's `:19–20` imports, per T5a §1.
6. Observation (d) (`mypy src`/`ty check src` equivalence) needed no plan change.

### Verification cycle 2

Cycle 2 of 2, 2026-09-12, against HEAD `e22d000` (read-only; no source, test, design or
documentation file changed; Podman and PostgreSQL not started). Scope: the six corrections
listed under Fix pass 1, re-traced against the tree rather than the fix-pass text.

**Verdict: VERIFIED.** No blocking or non-blocking defect remains.

Receipts:

| Check | Observed |
| --- | --- |
| `grep -n "check(" tests/unit/test_integrity_cutover.py tests/unit/test_lakectl_wiring.py tests/unit/test_lakectl_main.py tests/unit/test_controller_transport.py` | no-argument `self.check()` only at `test_integrity_cutover.py:66,71`; `check` defs at `:59,:415,:529` (`*arguments`) and `test_lakectl_wiring.py:91` (`evidence`); `test_controller_transport.py:74` already `client.check(evidence)` — M1.5's instruction covers every site |
| `grep -rn "def check(\|\.check()\|def certify(\|def validate_certificate(" tests` (all of `tests/`, not just the four modules) | no double outside those four files; `test_lakectl_main.py:71` `AcknowledgementBoundary.certify` raises or returns, never calls `check` |
| `RecoveringBoundary.check` (`:415–418`), `ObservationBoundary.check` (`:529–533`) | bodies use only the events; neither calls `self.check()` — signature change alone suffices |
| `src/huron/core/integrity/models.py:218,237` | `ProtocolTransition.fence: FenceEvidence` exists, so `await self.check(transition.fence)` is well-typed |
| M1→M3 trace with the fix applied | `cutover.py:105` `certify(result)` and `:122` `validate_certificate(transition)` reach the double's `check` with one argument; `:211` `writers.check(self.evidence)` is one argument today and `:212` becomes one argument at M1.4 (same milestone, gated at M1.7); `cutover.py:129,153,164,171,193,195,222` `fence.check()` are the internal `_Fence`-style object's own `check(self)` (`:206`), not the port. Every `test_integrity_cutover.py` test that reaches `certify`/`validate_certificate` stays green at M1.7, M2.3 and M3.4 |
| `tests/unit/test_controller_transport.py:63–74` | `test_client_authenticates_describes_establishes_and_checks_real_requests` calls `client.establish` with no `create_pool` patch — the one M1 test needing `database_boundary`; imports at `:19–20` are the `test_managed_controller` lines M1.5 cites |
| `tests/unit/test_controller_certificates.py:17` | `from tests.unit.test_managed_controller import EngineBoundary, engine_boundary as engine_boundary` — the re-export pattern exists |
| `grep -n check_duplication P3_M1B_AUTHORITY_IMPLEMENTATION_PLAN.md` | above `## Verification`: `:70` (§2 rule 2), `:152` (§4 gate block), `:794` (M8.1), `:840` (§5 recipe) — all `check_duplication.py src`; the only `src/huron` mentions are `:975`/`:1009` quoting the old text inside `## Verification`. Exactly the four locations Fix pass 1 item 3 names |
| `ls src` | `huron` only |
| M5.3 | `25 + 20 + 25 + 3 + 18 = 91`; §4 `≈1677`, M3.3 1661, M4.9 1659 untouched |
| §5 first paragraph | describes `<name>.log`/`<name>.exit`, `coverage.json`, source inventory; `ls p3-evidence/m1b/verification3` shows `*.log`, `*.exit`, `coverage.json`, `artifact-hashes.json` — claim now matches |
| `git status --porcelain`; `ls -l` mtimes | no test or source file modified (plan 12:41, `test_integrity_cutover.py` 07:35) — every source/test line pin in the plan still points at the quoted text |
| plan-internal references | the plan cites its own sections by heading, never by line, so the M1.5/§5 growth moved nothing |
| `uv run pytest -q --co` over the five affected unit modules | `73 tests collected` = 25 + 15 + 10 + 2 + 21, identical to cycle 1 |

Note (no action): M1.5's inline grep command wraps across a line inside backticks
(`tests/unit/` / `test_integrity_cutover.py`); the path is one token when typed.
