# MVP pre-production planning checkpoint

Status: **planning backlog; NOT READY, not revised executable phases or completion evidence**.
Snapshot: 2026-10-06; implementation/planning attempt 1, preparatory profile (configured
Astra Low; provider effort acceptance not proven). Dispatch
`2ff59d35-5fe0-4c74-8980-d4f4fc74c04d`; worker `ses_ef11a6f57ffeBIn9TXfYkp3gAW`.

## Authority and evidence boundary

The latest [user scope](planning-pause-2026-10-06.md) authorizes planning,
prerequisite checks and isolated experiments/corrections. **Pause before production
code, migrations, deployment or live documentation migration.** No prototype is
automatically promoted. Historical initial writer scope: only this new ignored file; existing plans,
source, design and other workers' artifacts remain untouched. Claims: source:repo
read, plan:raw-phases read, plan:mvp-readiness write. No services, builds, installs,
shared checks, SDK run-directory inspection or delegation occurred.

Current correction 2026-10-06: fix/planning attempt 1, dispatch
`3c455769-440b-4cca-a0fb-b37f4e9376bd`, configured preparatory/Astra Low; provider
effort acceptance not proven. Owns existing product plans 001–010 and this checkpoint
only (plan:raw-phases write, plan:mvp-readiness write, source:repo read). No phase000,
checker plan/code, prototypes, tracked design/CONTEXT, source/config or services changed.
Tracked durable records still carry the earlier unanswered questions; reconciliation
is deferred to separately owned/authorized work, not silently rewritten here.

### Approved product policies — current, not implementation evidence

User approved 2026-10-06: **fresh deployment; no existing Huron data to preserve or
convert**. Legacy Project/accounts/grants/active uploads/revisions/tags conversion
and backup/conversion rehearsal are not MVP acceptance. SQLAlchemy/Alembic schema
bootstrap remains required. Nonempty targets refuse and surface operator action,
never reset; unrelated files/data/volumes remain untouched. Current behavior stays
until each atomic owned code/schema/test cutover. Crash recovery/durability/auth/
replay, full integration/acceptance and all thresholds remain mandatory; fresh is
not permission to delete tests to bypass the no-sudo runner blocker.

**Explicit stale-base conflict, no silent merge** is approved. Base is immutable
during upload. For an uncommitted attempt compare expected base/current head
atomically with catalog publication in the chosen serialization/transaction; first
push races require expected empty head. Loser candidate remains hidden, no lineage
or receipt published, cleanup recoverable, no unpublished success acknowledgement.
After authorization, same-identity COMMITTED replay returns its original outcome
even after head advances. Explicit retry resolves a newer base with new operation
identity/fingerprint; never mutate the frozen attempt or reuse identity with changed
inputs. Omitted metadata inherits the exact newly pinned pair, never latest by accident.
SDK/UI surface typed conflict (illustrative HTTP 409) and caller review/retry; no
automatic repin or implicit merge/rebase. Preserve publication authority rechecks,
nondisclosure and DB/FS recovery. Serialization choice/crash evidence remain blocked.
These policies remove only two product decisions, not the production approval pause.

Read all ten product plans, the [cutover inventory receipt](raw-cutover-inventory-receipt.md),
[SDK dispatch receipt](sdk-isolation-dispatch-receipt.md), [target](../design/raw-first.md),
[vocabulary](../CONTEXT.md), canonical planning/OOP/PostgreSQL/FastAPI skills and
orchestration/verification/templates. No Svelte code was inspected. Gate evidence
includes actual Makefile, pyproject, CI and controlled-cutover test, not just plans.

Current source remains authoritative: seven Core owners and type-only import edges
are enforced by pyproject; Catalog still exports ProjectCollection; Alembic still
has target_metadata=None. Foundation DomainError currently renders HTTP problems.
The target Collection/combined rawstore/SQLAlchemy metadata/SDK/UI is not delivered
by these documents. Existing untracked Catalog interface files are user-owned.

### Evidence ledger (do not upgrade these claims)

| Subject | Current recorded status (historical scope noted above) | Consequence / next action |
| --- | --- | --- |
| Schema bounded experiment | Independent maximum review 2 PASS recorded in 001: 430 cases per seam / 860 outcomes; additional numeric/structural probes; common validator shared by both seams | Narrower numeric profile 2 is **unapproved product policy**, not general RFC8785 acceptance or production SDK/backend parity. Reconcile in 004/008, never silently change canonicalization in 002. |
| SDK isolation | Independent review 1 terminal: bounded checks successful, complete **FAIL** solely from 2,330 unchanged root-checker artifact whitespace findings; no SDK defect found | Two fresh runs each: 59 observations, 595 outcomes, 340 subcommands; 6,408 RECORD rows/26 environments without overlaps. Await checker correction and independent full rerun, not SDK code fix. See prerequisite receipt; no run directories inspected here. |
| Starlight | Terminal writer reports working builds but failed search-error state and mobile table readability; independent qualification not established | Separate owned ignored fix/review queue; no live docs migration. Root checker artifact-discovery failure is known, not PASS. |
| Raw cutover inventory | Preparatory read-only inventory; 18 Raw, 7 Rawstore, 17 Metastore, 7 Foundation files | Useful input, not exhaustive Security/transitive/string closure or phase002 readiness. |
| Remaining tus/publication/directory/query/web-session/k6 probes | No qualified receipts in supplied plans | Commission bounded isolated assignments; schema/SDK evidence reconciled in this correction without blanket phase PASS. |
| Product baseline / full integration | No new application run here | Obtain owned baseline later; no-sudo controlled-runner prerequisite remains unresolved. |

## Dependency-ordered prerequisite queue

Owners below are responsibilities for the parent to assign, not new dispatches.
Every experiment needs an exact reviewed assignment, private data/cache/environment,
owned ports/processes, canonical skills, deterministic positive/negative cases,
cleanup receipt and terminal writer before independent maximum qualification.
The commands in P rows are **proposed phase001 commands**, not claims that scripts
exist or are runnable. Do not run them until their owner creates/reviews them and
records versions and isolated resources. All cwd are repository root unless noted.

| Order / owner | Exact deliverable and dependencies | Acceptance / evidence / next action |
| --- | --- | --- |
| Q0 Parent + current reviewers | SDK review 1 complete FAIL despite bounded success; Starlight writer FAIL search-error/mobile tables, independent review pending; checker-plan review 1 FAIL under separate planner correction | No new PASS inferred. Root docs/checker commands below deferred until terminal writers and output ownership permit independent complete reruns. |
| Q1 Platform/test owner | Runner readiness receipt: locked Python >=3.12, PG16/testcontainers, isolated Linux/Podman root-capable controlled runner, historical object, disk and cache ownership; untouched full baseline | Application gate below; missing authority/services is BLOCKED. Historical object `db5fc84cd7bfe049692ef2abb16fb32570ccf5a2` must exist and archive match test. No sudo attempt here; provision approved runner rather than deselecting test. Can investigate readiness before product decisions. |
| Q2 Core cutover planner + independent reviewer | Exhaustive symbol/source/destination/caller/test/string-reference matrix and acyclic target graph for 002; exact adapter construction and error mapping decisions | Read-only closure first; inspect all runtime and TYPE_CHECKING edges. Later owned `uv run lint-imports` (root) plus full application gate only after approved cutover. Current graph cannot be weakened to simulate target readiness. See mandatory closure below. |
| Q3 Schema owner + product/data consumer | Numeric-policy comparison and decision note; qualified restricted schema corpus/limits now noted in 001/004/008 | Comparison recommends correct codec/canonical bytes authority rather than artificial 1e20 restriction: unqualified proposal, not approved. Existing bounded commands: `.venv/bin/python -B roadmap/prototypes/schema/schema_bundle.py` and `.venv/bin/python -B roadmap/prototypes/schema/reproduce_numeric.py`, root, only after artifact/environment claims assigned. User approves material scientific-value policy; no replay here. |
| Q4 Packaging owner + independent reviewer | Namespace/distribution decision and full requalification for 002/008; resolve sync/async Client surface separately | Review 1 bounded matrix succeeded including two fresh runs; complete FAIL due only to root checker. Retain SDK-only/dependency/HTTP/RECORD/install-order/uninstall/editable/split-path/Python3.12 acceptance on full rerun. Actual artifacts under roadmap/prototypes/sdk-isolation; flat sdk_isolation.py is an old illustration. No production initializer removal. |
| P1 Storage owner | Local tus durable-offset/fence crash receipt; reviewed isolated PG16 and local filesystem; no NFS prerequisite | Proposed `uv run python roadmap/prototypes/tus_crash.py --root roadmap/prototypes/data --bytes 1048576`. HEAD never acknowledges undurable bytes; two writers/process death, wrong offset, variable/zero-byte transfers, bounded memory. Owner must replace shared illustrative data root with uniquely claimed location before dispatch. |
| P2 Publication owner | Storage-first/DB receipt state table and local crash/pin/cleanup proof; PG16 plus filesystem and P1 fence assumptions | Proposed `uv run python roadmap/prototypes/release_crash.py --root roadmap/prototypes/data --bytes 1048576`. Independent copies, hidden candidates, atomic head comparison/lineage/receipt, first-push empty-head race, committed replay after head advance, explicit new-identity retry, revocation, ENOSPC, lost reply and pin/purge race. Isolate data root. Policy approved; algorithm/evidence still blocked. |
| P3 Identity owner | Issuer options note plus directory authority/nesting/freshness/outage receipt using signed fixture | Proposed `uv run python roadmap/prototypes/directory_authority.py`. Both directions of admin separation, issuer/email collisions, cycle rejection, TTL/version/invalidation and read/write outage semantics. Fixture tests need no real issuer choice; actual SDK token/refresh and Google acceptance do. Recommend fail-closed stale writes/publication, explicitly qualify read policy. |
| P4 Query owner | PostgreSQL visibility/keyset/JSONB/FTS EXPLAIN and reproducible export receipt; disposable PG16, deterministic 10k corpus | Proposed `uv run python roadmap/prototypes/search_plan.py`. Authorization before LIMIT/count/facets; tie-key walk, revocation, publication freshness and export stable across title/schema edits. Recommend small synchronous projection in publication transaction, subject to measured cost; no fabricated time SLO. |
| P5 Web topology owner | Early fixture-only SSR/session/same-origin/CSRF/tus topology and operation-to-screen candidate inventory | Copied ignored web-session package cwd: `npm run check`, `npm test`, `npm run lint`, `npm run build`, `npm run test:e2e`, per-component autofixer and named browser QA below. First declare package/scripts and private resources. No dependency on implemented 002/003/009; fixture DTOs explicitly non-authoritative. Both Svelte skills required before inspecting components. |
| P6 Performance owner | Exact k6 version/image digest and official version-matched filesystem API/bounded-buffer receipt | Proposed `k6 run --vus 2 --iterations 2 roadmap/prototypes/k6-buffers.js`; private fixture HEAD/PATCH endpoint and 1 MiB data. Prove seek/chunk/retry/RSS/fd/shared-file behavior; no product tus, real identity, NFS or 500 GiB requirement. Pin feeds 002 minimal profile, then 010 actual-stack qualification. |
| Q5 Bootstrap owner + operator | Fresh deployment approved; exact schema initialization and nonempty-target refusal contract | No legacy ID/FK/path/role/account/policy/session/revision/tag conversion required. Qualify Alembic bootstrap/constraints/drift on owned disposable empty targets and refusal/operator action for nonempty targets. No reset/deletion authority; preserve controlled-cutover/recovery tests and runner requirement. |
| Q6 Starlight owner + docs/checker owner | Isolated search failure-state and mobile table fix receipts; precise checker generated-artifact discovery defect reproduction/correction; independent rerun | Working builds alone insufficient. Parent assigns exact prototype/checker claims; root checker is currently shared-owned. Preserve meaningful link coverage, not blanket exclusions to force PASS. Live documentation migration remains paused. Not a substitute for P5 product UI probe. |
| Q7 Plan writers + independent plan reviewers | Self-contained revisions in sequence below, with concrete signatures/errors/deletions, evidence limits, full gates and approved decisions | Review each terminal subject writer independently, maximum 3 reviews/slice; unresolved gaps remain BLOCKED. Final complete qualification requires maximum, not this preparatory synthesis. |
| Q8 Parent + user | Consolidated reviewed handoff: decisions, unresolved infrastructure, plan statuses, exact proposed execution boundary | Explicitly request implementation approval and PAUSE. Do not start product code simply because planning authorization is broad. |

### Mandatory phase002 closure (technical work, not a user architecture quiz)

The inventory must resolve **exact paths and every symbol**, not authorize deletions
by globs. Preserve existing Project, numbered-part, revision/tag and policy behavior
until their separately scoped semantic cutovers. Required decisions:

- Foundation slug/path rules and shared errors are consumed by Security while
  Catalog already depends on Security. Moving everything into Catalog creates a
  forbidden reverse edge. Decide consumer-owned claim/clock contracts, slug-rule
  owner and error ownership with a final acyclic graph including type-only edges.
- DomainError inheritance currently affects Security denial catches, Integrity
  failures and HTTP registration/rendering. Map each raise/catch/code/status/context
  to owner-specific errors and application transport, retaining 404 nondisclosure,
  authorization-before-replay and stable observable error semantics during relocation.
- Name supported factories/construction boundaries for private filesystem adapters;
  API and lakectl cannot import newly private modules. Include runtime/dependencies,
  API problems/errors/expiry/guards/DTOs, all lakectl wiring/controllers,
  scripts/main.py, tests/controlled_deployment.py and private-coupled durability tests.
- Resolve MetadataSubmission and Integrity evidence/persistence Pydantic boundaries;
  relocation changes no byte formats. Preserve canonicalization pending Q3.
  UUIDv7 domain/DB callers and SystemClock/clock ports need injected construction
  without Core importing Applications or applications importing sibling applications.
- Review duplication path relocation accounting without new/growing clones, changing
  counts or similarity 0.80. Preserve transaction/crash/maintenance/scale coverage.
- SDK regular server package owns huron/__init__.py today. Shared site-packages
  success is insufficient: split-path/editable discovery and uninstall survival must
  qualify native namespace or another explicit remedy. Public imports remain
  huron.client/huron.catalog; no second wheel owning the initializer, no server alias.

## Minimum user questions, asked only before their downstream dependency

1. **Data — answered 2026-10-06:** fresh deployment; no existing Huron data to convert.
   Not a remaining approval blocker and not deletion authority. Bootstrap and
   nonempty-target refusal still need technical evidence.
2. **Identity:** Which API-token issuer/broker is approved, and is Keycloak retained
   as Google broker or only local test provider? Identity owner should first present
   a short feasible options/security/operations comparison. Current recommendation:
   Keycloak as Google broker and Huron API-token issuer, replaceable provider issuing
   audience-bound Huron tokens; USER NOT YET APPROVED. Google ID tokens are
   login evidence, never the SDK bearer shortcut. Needed before real token qualification.
3. **Concurrent publication — answered 2026-10-06:** explicit stale-base conflict and
   explicit retry against newer base, no silent merge. Atomic serialization and
   recovery qualification remain technical work, not pending policy approval.
4. **Scientific numbers:** After the technical comparison, is schema profile 2's
   narrower round-trip-stable numeric admission acceptable for actual scientific
   metadata? Do not assume approval. Prefer no unexpected narrowing without user
   validation; the prototype PASS proves only the chosen bounded experiment. The
   correct-codec/canonical-bytes recommendation is not yet qualified or approved.
5. **Hardware now, SLO later:** Who nominates NFS server/client/mount/network/API and
   generator topology and reserves peak capacity above 500 GiB? After a measured
   baseline, what completion/search/freshness SLO is acceptable on that hardware?
   No numerical SLO question needs answering before baseline. Real NFS correctness
   requires nominated resources; final performance qualification requires later approval.

The no-sudo runner is an operator provisioning issue, not a request to weaken tests
or have this worker elevate privileges. Technical TTLs, graph destinations, packaging,
sync/async surface, search projection and chunk/fence designs should be investigated
by their owners, escalating only material user-visible tradeoffs for approval.

## What proceeds now and what can overlap

Before those answers: Q1 runner discovery, Q2 exact closure, Q3 numeric comparison,
Q4 packaging requalification, P1 local storage, P2 approved-policy recovery, fixture P3,
P4 queries, P5 early UI and P6 k6 feasibility can proceed under separate assignments.
Do not impose all 001 outputs as prerequisites to obtaining any one output.

Read-only source inventories can overlap unrelated ignored planners. Independent
prototype subjects may overlap only with disjoint exact directories, databases,
ports, browser profiles, caches and Python environments; shared illustrative
roadmap/prototypes/data is NOT such isolation. Writer -> review -> fix is terminally
serial for each subject. Docs build/checker and root Python environment are currently
deferred until terminal subject writers and explicit output claims; no competing invocation.
Any live source/config/tool
correction requires parent reconciliation and exclusive maximum code dispatch,
never prototype relabelling; production changes still require user approval.

## Proposed sequence of self-contained plan revisions

1. Revise 001 evidence ledger and per-probe entry/completion gates; replace stale flat
    illustrations only with actual reviewed receipts. Fresh/stale-base decisions are
    approved; identity/numeric/hardware/SLO choices remain unresolved as applicable.
2. Revise 002 into bounded runner/topology, exact structural-cutover and packaging/
   OpenAPI slices with closure from Q2/Q4/P5/P6. No new schema semantics, Project
   rename or global graph weakening hidden inside relocation.
3. Revise 003 from identity/freshness receipt and broker choice; revise 004 from
    schema evidence/numeric decision and fresh bootstrap. These writers can be
   separate nonconflicting plan claims after 002 paths are resolved, then reconcile
   role/Collection dependencies. SQLAlchemy definitions + direct asyncpg + real
   reflected drift check must include constraints/indexes/defaults/triggers.
4. Revise 005 from durable tus and bootstrap refusal; 006 from crash/pins and approved
    stale-base policy; 007 from query/export evidence. No legacy conversion. Keep backend
   dependencies 003/004 -> 005 -> 006 -> 007 explicit without making local probes
   depend on their eventual implementations.
5. Revise 008 after packaging/API/credential/metadata/tus receipts: exact SDK lint,
   coverage/import/complexity/generation commands and sync/async decision. Revise
   009 candidate route inventory now, final wire mapping only against authoritative
   backend contracts; all operation-to-screen rows and real persistence remain required.
6. Revise 010 with early k6 pin, nominated hardware and exact run/capacity ownership.
   Its baseline produces evidence for later SLO approval; it cannot require that
   future SLO as a prerequisite to measuring the baseline. Then independent plan
   reviews and consolidated approval checkpoint; no automatic execution.

## Complete downstream application gate (not run by this planning worker)

Root cwd, locked uv/Python >=3.12, owned output/cache resources:

```sh
make lint
uv run pytest -m unit --cov=src/huron --cov-report=term-missing
uv run pytest -m contract
uv run pytest -m integration
make test-acceptance
make docs
git diff --check
```

Full affected backend/storage cutovers require all above: PG16/testcontainers, real
filesystem, >=25 GiB acceptance space and isolated Linux/Podman controlled runner.
The current controlled test invokes `sudo -n` when non-root and its helper requires
Linux root; this assignment prohibits sudo. A Docker socket alone cannot qualify it.
No runner authority or historical-object availability was tested here. CI accepts
integration exit 5 today; qualification must not. `make test` is unit-only.

Keep 96.01% coverage, existing import contracts, complexipy 15, radon C+/MI B+
diagnostic findings even on exit 0, pyscn and duplication 0.80 no-new/no-growth.
No exclusions/skips/xfails/suppressions/weaker assertions or baseline regeneration
to manufacture PASS. Reuse scoped fixtures and public-behavior tests; real PG/disk
for transaction/locking/crash claims. Record exact exits, counts, coverage and limits.

After owned scripts exist, additive root commands are
`uv run python scripts/check_openapi.py --check`,
`uv run python scripts/check_sdk_distribution.py` (002), and
`uv run python scripts/check_database_schema.py` (004). These are future commands,
not current runnable checks. SDK cwd after package/lock/config exist: `uv sync --locked`,
`uv run ruff check src tests`, `uv run ruff format --check src tests`,
`uv run mypy src`, `uv run pytest --cov=src/huron --cov-report=term-missing`, `uv build`.
SDK floor at least 96.01%; exact additional complexity/import wiring unresolved.

Frontend cwd web, locked dependencies and supported Node (recorded local 22.23.2):

```sh
npx @sveltejs/mcp svelte-autofixer <path> --svelte-version 5
npm run check
npm test
npm run lint
npm run build
npm run test:e2e
```

Autofixer each changed Svelte component with valid findings resolved; both Svelte
skills, Tailwind for styling and local Playwright skill. Named-session real-browser
QA on owned endpoint/profile: mobile, 816px, wide, light/dark, keyboard/focus,
loading/empty/long/validation/error/unauthorized, overflow/hydration/console. Real
backend/auth persistence for 009, not fixture success. No frontend source analysis
or browser check by this worker. NFS/load qualification later requires actual mount,
bounded generator, 50 distinct authenticated users x 10 GiB / 50 datasets,
committed-readable/digest receipts plus search, separate retained-copy/contention,
and measured baseline then approved SLO rerun. Existing 9 GiB test proves none of that.

## This checkpoint's validation and handoff

Current bounded correction self-check (not independent qualification): root status,
diff whitespace, exact owned text/heading/local-link checks, ignore and no-tracked-
roadmap checks. Before hashes recorded for all 11 owned files and a Git-visible/index
fingerprint; exact edits retained in apply_patch tool evidence. No extra receipt or
prototype files created. Full gate is deferred below while the separate planner
writes; known checker FAIL remains, not PASS. No phase is READY/verified by this fix.

The following describes the historical initial checkpoint writer, not this correction:

Initial root `git status --short --untracked-files=all` and `git diff --check` exited
0; 51 dirty tracked entries and four untracked source/design files were pre-existing.
New target was absent before creation. Final status/diff, new-text whitespace and
Markdown local-link existence checks, `git check-ignore roadmap/mvp-planning-checkpoint.md`
and `git ls-files roadmap` are the non-writing self-checks; results accompany handoff.
No claim of independent review or source-content fingerprint comparison is made.

Deferred, **not PASS**: root
`UV_CACHE_DIR=/tmp/opencode/huron-effort-uv-cache make docs` and
`python roadmap/check_docs.py`, for later independent reviewer with shared output
ownership. Known root checker artifact-discovery failure remains unresolved until
that owner's evidence says otherwise. No application/source changes: application
suites nonapplicable to this checkpoint; the downstream gate remains mandatory.
Agent assets unchanged: agent npm gates nonapplicable. Parent must obtain independent
review of this new planning artifact, reconcile receipts, then retain the explicit
pause before any production implementation or live documentation migration.
