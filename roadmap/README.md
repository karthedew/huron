# Raw-first complete MVP: local delivery map

Status: prior planning/documentation independently reviewed, PASS on attempt 2;
current execution discovery and Starlight design await independent review.
Current authority: user now authorizes Raw MVP implementation, Docker and workspace
writes without asking, and detailed developer/user documentation using Starlight
under docs. Never sudo; preserve unknown work/data. Authorization does not resolve
decisions, qualify prototypes or make phases 002–010 ready. This assigned writer
turn is DESIGN-PLAN only: no product edits, services or prototype execution.
See [current execution record](execution-2026-10-05.md) and
[DOCS workstream design](starlight-design.md). The dated record name is the assigned
execution label; this worker's environment reports 2026-10-04.
Earlier restrictive authorization and pending-work statements below are historical
receipts, not current authority; their evidence and decision limitations still apply.

## Goal, scope and authority

Complete MVP is metadata/schema governance + Organization → Collection → Dataset +
Google-first identity/separate directory and Huron authorities + tus full-copy Raw
releases + PostgreSQL search/export + lightweight production Client SDK + integrated
frontend + qualified developer/operations stack. Raw uses POSIX/NFS; later
Bronze/Silver/Gold exclusively Icechunk/Zarr/S3. Durable decisions live in
`design/raw-first.md`; vocabulary in `CONTEXT.md`. This directory is ignored.

Initial state: extensive user/tooling changes already existed in .agents/config,
AGENTS, CONTEXT, design/docs/web READMEs, web API files, and catalog/interface;
root legacy plans and minihuron files were already deleted. Initial tracked/untracked
state is captured by `git status --short` in this writer transcript. This writer
owns only the documentation assignment and ignored roadmap; source/tests/Compose/
skills/plugin/config/global work is preserved. No commits/stash/reset/clean.

## Verified current state

| Claim | Direct evidence inspected | Classification |
| --- | --- | --- |
| Seven Core owners remain enforced | pyproject.toml import contracts | Implemented graph, not future grouping |
| Project and revision/tag still exist | core/catalog/types.py Project/Dataset.project_id; core/raw/__init__.py | Implemented, target migration pending |
| Numbered PUT parts | core/raw/_impl/ingestion.py receive_part(part, chunks, content_length) | Implemented, tus absent |
| Shared Pydantic metadata | core/raw/metadata.py MetadataSubmission | Implemented; new registry/pair semantics absent |
| Metadata schema drift gate absent | migrations/env.py target_metadata=None; scripts/check_schema_map.py | Docstamp only |
| Catalog interface files empty | core/catalog/interface/catalog_search.py inspected empty | User scaffold, not SDK/search completion |
| Search endpoint is unavailable | applications/api/routes/v1/endpoints/search.py search_unavailable raises ProjectionUnavailable | 503 placeholder, not PostgreSQL search |
| Stack lacks frontend/directory/Raw volume/k6 | docker-compose.yml and Makefile | Target containers absent |
| Web fixture seam and preview session | web/src/lib/api/README.md; web/playwright.config.ts | Production integration pending |
| Unit defaults and gate prerequisites | Makefile, pyproject.toml, .github/workflows/ci.yml | Plain pytest is units; CI exit 5 is not integration proof |

Installed probe (not prototype): FastAPI 0.141.1, Pydantic 2.13.4, SQLAlchemy
2.0.52, asyncpg 0.31.0, Alembic 1.19.1, jsonschema 4.26.0, HTTPX 0.28.1.

## Phase overview and readiness/dependency matrix

Every row has a self-contained plan under `roadmap/plans/`. Status concerns that
phase alone. No product row is ready merely because its document exists.

| ID / plan filename | Outcome | Depends on | Status / blocker |
| --- | --- | --- | --- |
| 000-agent-tooling.md | Canonical tooling/lifecycle | Prior tooling slice | VERIFIED: independent attempt 2 PASS supplied by parent |
| 001-decisions-prototypes.md | Decisions, local/fixture probes, early session topology and minimal pinned-k6 API/buffer proof | 000; owner availability and reviewed bounded assignment | Broad user authorization received; individual probe preflight/review and decision outputs still pending. Historical plan authorization text needs reconciliation by its owner before execution |
| 002-environment-interfaces.md | Fixture-qualified dev topology, pinned minimal k6 profile, public owner cutover, isolated SDK skeleton/contracts | 001 packaging/fixture-topology/k6/data decisions | BLOCKED: early receipts/inventory and approved migration; no 009/010 prerequisite |
| 003-identity-directory-access.md | Google login, separate directory authority, simple roles | 001 credential/freshness; 002 | BLOCKED: issuer/broker/freshness evidence |
| 004-collection-metadata.md | Collection rename and immutable additive schema registry | 001 schema/data; 002,003 | BLOCKED: migration decision/validator corpus |
| 005-tus-transfer.md | Durable interoperable per-file tus transfer | 001 fencing; 002–004 | BLOCKED: durable-offset prototype |
| 006-release-publication.md | Full-copy pinned-base releases/receipts/recovery | 001 conflict/data; 003–005 | BLOCKED: stale-base decision/crash prototype |
| 007-search-export.md | PostgreSQL search and reproducible export | 001 query/freshness; 004,006 | BLOCKED: query/freshness/export prototype |
| 008-production-sdk.md | Lightweight Client service implementation | 001 packaging/credential decisions; 002–007 | BLOCKED: credential issuer/isolation/interoperability |
| 009-integrated-frontend.md | Integrated session/projection acceptance and all delivered backend features in real UI | 001 fixture session/topology; 002–008, including 003 Google/directory receipts | BLOCKED: early probe/backend gates; integrated receipt produced in slice 1 |
| 010-performance-operations.md | Actual NFS, full-load baseline, then approved-SLO rerun and recovery qualification | 001 hardware/local-storage/pinned-k6 probes; implemented 002–009 | BLOCKED: hardware/capacity/early receipts/stack; SLO approval gates final rerun, not baseline |

Separate named workstream **DOCS** (not phase 011; no renumbering or new backward
edge): Starlight design → bounded locked content/link/search prototype → reviewed
self-contained implementation plan → site/build migration → detailed developer/user
guides synchronized with verified product slices. Design: `roadmap/starlight-design.md`.
Site foundation can proceed independently of 002–010; executable scientist examples
and operational claims wait for their owning product receipts. No docs implementation
or DOCS readiness is claimed. Future named plan must retain the phase template/gates;
the checker permits additional named plans while preserving unique 000–010 checks.

Each phase is split into small serial writer/reviewer slices, max three reviews
per slice. Independent baselines and final reruns are mandatory for future execution.
No nested delegation in this assigned worker-only planning turn.

### Entry, per-slice prerequisites and completion

The matrix lists entry dependencies, not each phase's own completion outputs.
001 may undertake user-authorized, reviewed bounded decision/prototype assignments
without already having their results. Each probe uses disposable local fixtures;
none consumes implemented 002–010 output. Its token experiment alone waits for the
issuer/broker choice, and conflict cases for the stale-base decision within 001.
The current writer assignment remains documentation-only; parent commissions those
assignments separately within the user's broader authorization.

Single-owner evidence sequence:

- 001 owns early fixture-only session/topology and candidate projection examples,
  local storage crash proofs, and the initial exact k6 pin/API/bounded-buffer proof.
- 002 consumes these receipts for fixture topology and a minimal pinned profile;
  003 owns actual identity/Google/directory implementation and authority receipts.
- 009 consumes 003–008 and qualifies actual backend DTO mapping plus integrated
  Google/session/directory behavior. Its receipt is not a prerequisite for 001/002.
- 010 owns actual-NFS qualification and full-load/generator-at-scale evidence.
  After hardware/capacity, early probes and implemented-stack entry gates, its
  slice 1 preflight precedes slice 2 NFS proof, then slice 3 baseline. Slice 4 seeks
  SLO approval from that baseline before the qualification rerun. Approved SLO plus
  that rerun is a completion gate; it never gates the baseline that informs it.

Direct phase edges (prerequisite → consumer) remain topologically ordered 000–010:
001←000; 002←001; 003←001,002; 004←001,002,003; 005←001,002,003,004;
006←001,003,004,005; 007←001,004,006; 008←001,002,003,004,005,006,007;
009←001,002,003,004,005,006,007,008; 010←001,002,003,004,005,006,007,008,009.
References to later acceptance/handoffs are not backward prerequisite edges.

## Decisions and blockers

| Owner | Decision | Recommended option / consequence |
| --- | --- | --- |
| User/data owner | Preserve/migrate existing data vs fresh MVP deployment | Inventory and backed-up rehearsal first; fresh needs explicit data disposition. No compatibility does not authorize deletion. |
| Identity owner + user | SDK API-token issuer/broker; existing Keycloak role | Qualify replaceable provider/broker, audience-bound API tokens. Never use Google ID token as Huron bearer or invent an auth server. |
| User/product owner | Stale-base publication | Fail conflict rather than silent merge; explicit new base/retry preserves provenance. |
| Operator + user | NFS hardware and time SLO | Nominate topology and benchmark baseline first; then approve SLO. |
| Prototype owners | Schema profile, directory freshness, local fencing, packaging, search, fixture UI topology and k6 API/buffers | Commission reviewed bounded 001 assignments under current authority; inline receipts into affected plans. 009 owns integrated mappings/Google/directory UI acceptance; 010 owns actual NFS/full load. |

Accepted: additive-only collection extensions; exact pinned-base metadata/schema
inheritance; separate directory membership-write and Huron role authorities; hardware
baseline before time SLO. Do not reopen these as unspecified product choices.

## Relocation and historical evidence

The prior writer reports copying the initially dirty `design/roadmap.html` unchanged
to `roadmap/archive/design-roadmap.html`. This fix does not alter the archive; HEAD
cannot independently prove equality to that initial dirty byte copy.
Root IMPLEMENTATION_PLAN.md, P3_DESIGN.md and P3_IMPLEMENTATION_PLAN.md were absent
before this writer began. They were not recreated from Git, which could lose unseen
unfinished edits. Their pre-existing deletions remain untouched. Historical completed
receipts are tracked in `docs/history.md`; public docs link durable records, never
ignored plans. Old archive-relative links are preserved as original content, not
presented as live navigation.

## Planning self-check ledger

- Writer attempt 1, sole assigned planning role; no child/reviewer spawned. Model:
  openai/gpt-6-astra; reasoning variant not independently inspected in this session.
- Baseline root `make docs`: exit 0, strict build no issues (before document edits).
- Baseline root `python roadmap/check_docs.py`: exit 1, eight missing links to the
  already-absent root plans. No existing local checker was found; ignored checker
  was created before documentation edits and covers Markdown/HTML local fragments.
- After link reconciliation: same checker exit 0. Final complete gates and direct
  plan review are recorded below when actually run, not inferred from this result.
- Own planning slice awaits independent review. Prior 000 PASS is not this slice's PASS.

### Final writer checks (2026-10-04; not independent review)

| Cwd | Exact command | Outcome |
| --- | --- | --- |
| root | `make docs` | Exit 0; strict Zensical build, no issues; final run after durable edits |
| root | `git diff --check` | Exit 0; no whitespace diagnostics |
| root | `python roadmap/check_docs.py` | Exit 0; public Markdown/HTML local links/fragments, all tracked Markdown/HTML ignored-plan links, owned/new text whitespace, 10 new phase section sets and canonical skill paths |
| .agents | `PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH npm run check` | Exit 0; TypeScript, 11 canonical skills, four commands/templates/references |
| .agents | `PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH npm test` | Exit 0; all 15 passed, no failures/skips/cancellations |
| root | `PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH node --version` | Exit 0; v22.23.2 |
| root | `git check-ignore -v roadmap/README.md roadmap/check_docs.py roadmap/archive/design-roadmap.html roadmap/plans/000-agent-tooling.md roadmap/plans/001-decisions-prototypes.md roadmap/plans/002-environment-interfaces.md roadmap/plans/003-identity-directory-access.md roadmap/plans/004-collection-metadata.md roadmap/plans/005-tus-transfer.md roadmap/plans/006-release-publication.md roadmap/plans/007-search-export.md roadmap/plans/008-production-sdk.md roadmap/plans/009-integrated-frontend.md roadmap/plans/010-performance-operations.md` | Exit 0; every path matches .gitignore:40 /roadmap/ |
| root | `git ls-files roadmap` | Exit 0; empty |

Direct writer review covered each phase's current/proposed examples, scope/deletions,
prototype reproduction assignment, local skills, gates/prerequisites, acceptance,
blockers and ledger. All 001–010 remain BLOCKED, with unrun prototypes explicitly
stated. New SDK/drift/load commands have assigned future script/config owners and
are not represented as currently runnable. Self-review corrected environment topology
versus directory implementation sequencing and backend versus UI Collection cutover
dependency. Exact remaining symbol inventories and packaging/API selections are
readiness blockers, not implied approvals. Review count for this planning slice: 0.

Baseline attribution: strict docs already passed; eight local legacy-plan references
were broken before edits and now pass. The site build alone never covered all design
HTML. Local checker does not fetch external URLs or validate archived links inside
the historical ignored roadmap. It checks live public local links/fragments;
historical remote receipts remain explicitly historical. No Python/frontend production
gate, browser QA, services, migrations, load or product prototypes ran in this docs-only
turn. Terminal output is in the writer transcript. Root legacy files remained absent.

Owned durable edits: CONTEXT.md, README.md, design/raw-first.md and relevant design
pages/atlases (atlas edits only repair links), docs/history.md/ADR-0002, backend/index/
development/testing/layout docs and both web READMEs. AGENTS.md changed only the
local-plan relocation cross-reference; docs/agents/domain.md only its stale relocation
reference. Existing tooling/source/test/Compose/config/skill/global work preserved.

## Independent planning review attempt 1 — fix attempt 1 (2026-10-04)

Role: sole documentation fix worker, openai/gpt-6-astra; no nested agents. Initial
`git status --short --untracked-files=all` captured in this fix transcript before
edits. All pre-existing modifications/deletions/untracked files are user/parent
work, including the five already-dirty public documents and ignored planning files.
Only the incremental owned changes listed below belong to this fix. No archive,
tooling/config/skills/product source/tests/Compose change is owned or made here.

Review count: independent planning attempt 1 reported three findings; corrected
draft awaits re-review (maximum three reviews). Prior writer review-count-zero and
pending-review statements above are historical. The user supplied that prior
executable gates passed; this fix reruns them rather than treating that as evidence.

| Finding | Correction | Disposition |
| --- | --- | --- |
| HIGH dependency cycles (002 k6 ↔ 010; 001/002 session ↔ 003/009; unassigned 001 NFS/k6 evidence) | 001 owns fixture-only session/topology and minimal exact-pin k6 API/buffer probes; 002 consumes their receipts; 003 owns actual identity/directory receipts; 009 owns integrated session/projection acceptance; 010 owns actual NFS and full-load qualification. README matrix and four affected plans agree. | Addressed by fix author; independent re-review pending |
| MEDIUM readiness cycles (001 outputs block own work; SLO approval blocks baseline) | Explicit entry, per-slice and completion criteria in 001/009/010 and README. Separately authorized 001 decision/probe work can produce its outputs; 010 baseline follows preflight/NFS/stack, SLO approval gates final rerun only. | Addressed by fix author; no prototype/run authorization or readiness claimed |
| MEDIUM competing public targets | Overview marks catalog-first/numbered baseline and glossary historical; current Client/direct namespaces, Collection and rawstore/interface decisions are explicit. Catalog facade/engine/registry history cannot override current target. Auth 15-minute TTL and older provider proposals are historical; Keycloak role remains unresolved. Developer navigation leads to current release semantics. Bibliography retained. | Addressed by fix author; independent re-review pending |

Owned files: `roadmap/README.md`, `roadmap/check_docs.py`, plans
`001-decisions-prototypes.md`, `002-environment-interfaces.md`,
`009-integrated-frontend.md`, `010-performance-operations.md`,
`design/index.html`, `design/catalog-search.html`, `design/auth.html`, `docs/index.md`,
and the tightly related historical freshness link/label in `design/rbac.html`.
Checker changes are additive: retain all existing checks, add all untracked UTF-8
text whitespace, unique 000–010 plans, exact phase-filename cross-references and
local skill paths. It does not claim to mechanically prove semantic readiness.

Direct dependency/readiness self-audit read every plan 000–010 in full:

- 000 remains the supplied prior tooling receipt; not reclassified as product proof.
- 001 has no implemented-product prerequisite; decision slices produce choices and
  fixture probes produce early evidence. Their per-experiment prerequisites are local.
- 002 consumes 001 receipts only; identity/UI/full-load completion are later handoffs.
- 003 consumes 001 authority choices/probe and 002 topology/interfaces; no 009 UI prerequisite.
- 004 consumes 001 schema/data and 002/003; SDK/UI renames are downstream handoffs.
- 005 consumes 001 local fencing and 002–004; NFS acceptance is deferred explicitly
  to 010, not a prerequisite for local tus implementation.
- 006 consumes 001 crash/data/conflict and 003–005; no full-load/NFS receipt assumed.
- 007 consumes 001 query experiment, 004 schema and 006 publication; no SDK/UI input.
- 008 consumes 001/002 packaging and 003–007 contracts; SDK behavior is its output.
- 009 consumes early 001 fixtures and implemented 002–008; its integrated mapping
  receipt is slice 1 output, then a prerequisite for subsequent UI slices.
- 010 consumes early 001 receipts and implemented 002–009. Preflight → actual NFS
  proof → baseline → SLO decision → rerun is acyclic; SLO approval is not baseline entry.

All 001–010 remain DRAFT/BLOCKED for product execution. Remaining user-owned choices:
existing-data migration versus fresh disposition; SDK issuer/broker and Keycloak role;
stale-base policy; nominated hardware/capacity and, after baseline, the time SLO.
Prototype owners still owe qualified schema/freshness/fencing/packaging/query/session/
k6 evidence, exact inventories and independent review. No result is inferred from
a future phase. Future full Python/frontend/real-adapter gates are preserved.

### Fix attempt 1 validation (fresh self-checks)

All commands below ran in this fix turn and exited 0; output is retained in the
tool transcript. These are fix-author self-checks, never an independent PASS.

| Cwd | Exact command | Result |
| --- | --- | --- |
| root | `make docs` | Strict Zensical build: no issues; rerun after the related RBAC correction |
| root | `git diff --check` | No diagnostics |
| root | `python roadmap/check_docs.py` | Public local links/fragments, no tracked ignored-plan dependencies, owned/untracked text whitespace, 000–010 cross-references/local skills and all 10 product phase structures pass |
| .agents | `PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH npm run check` | TypeScript and asset checks pass: 11 canonical skills, four commands, templates/references |
| .agents | `PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH npm test` | 15 passed; zero failed, skipped or cancelled |
| root | `PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH node --version` | v22.23.2 |
| root | `git check-ignore -v roadmap/README.md roadmap/check_docs.py roadmap/archive/design-roadmap.html roadmap/plans/000-agent-tooling.md roadmap/plans/001-decisions-prototypes.md roadmap/plans/002-environment-interfaces.md roadmap/plans/003-identity-directory-access.md roadmap/plans/004-collection-metadata.md roadmap/plans/005-tus-transfer.md roadmap/plans/006-release-publication.md roadmap/plans/007-search-export.md roadmap/plans/008-production-sdk.md roadmap/plans/009-integrated-frontend.md roadmap/plans/010-performance-operations.md` | All 14 paths match `.gitignore:40:/roadmap/` |
| root | `git ls-files roadmap` | Empty |

Direct semantic audit is recorded above, not inferred from the checker. Related
public headings/navigation and bibliography were inspected; the remaining RBAC
15-minute link now explicitly names a historical proposal. No archive edits or
independent initial-dirty-copy equality claim. No product
Python/frontend gates apply to these prose/local-checker edits. No services,
browsers, migrations, prototypes or load runs are authorized or executed here.

## Independent planning review attempt 2 — PASS (2026-10-04)

Recorded by the orchestrator from reviewer session
`ses_ef6f04eecffeCukg30YALrUP8A`, using `openai/gpt-6-astra`, low reasoning.
The reviewer inspected every product phase plan and confirmed that the three
attempt-1 findings were resolved, the prerequisite graph was acyclic and readiness
distinguished entry conditions from the work's own outputs. No findings remained.

Independent reruns passed: root `make docs`, `git diff --check`,
`python roadmap/check_docs.py`; `.agents/` `npm run check` and `npm test` using
Node 22.23.2 (15 passed, no failures/skips); explicit ignore checks for all 14 local
artifact paths; and `git ls-files roadmap` returned no tracked files. The reviewer
also audited 44 public documents, 1,467 local links and 97 whitespace inputs.

This is a documentation/planning PASS, separate from the earlier tooling PASS.
Historical pending-review statements above describe the state of those attempts.
No product prototypes, services, migrations, browser sessions or load runs were
executed. Existing-data disposition, API-token issuer/broker, stale-base policy,
hardware and subsequent SLO choices remain open as recorded above.

## Review and next step

Commission reviewed decision work or bounded 001 prototypes under current authority,
and the separate DOCS prototype after independent design review; insert actual outputs/limitations,
then review affected executable slices before invoking
`/implement-markdown roadmap/plans/<id>-<name>.md`. Do not require a slice's own
outputs before authorizing the work to produce them; downstream consumers still wait
for the applicable evidence and user choices. 010 baseline precedes SLO approval.
Do not execute any product plan from this planning turn.
