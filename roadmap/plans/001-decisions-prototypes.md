# Phase 001: decisions and bounded prototype qualification

Status: blocked — schema prototype independently qualified; remaining decisions, probes and downstream reconciliation pending

## Context and outcome

Huron currently has Project entities, submission-only Raw revisions plus tags,
numbered-part uploads, separate raw/rawstore owners, handwritten DDL without
SQLAlchemy metadata, and a fixture-backed frontend. Complete MVP instead includes
Collection catalog, required versioned scientific metadata, full-copy releases,
tus, PostgreSQL search/export, Google-first identity, separate external directory
membership authority, lightweight Client SDK and real frontend integration.
Raw stays POSIX/NFS; later Bronze/Silver/Gold exclusively Icechunk/Zarr/S3.

This phase closes decisions and produces reproducible experiments before product
implementation. Accepted rules: extensions add fields only; later omitted metadata
inherits exact pinned-base metadata/schema even if latest changed; directory itself
guards writes by stable configured huron-admin membership; directory admin implies
no Huron owner/data-reader role; nominate hardware before setting time SLO.

User decisions recorded 2026-10-06 in [planning pause](../planning-pause-2026-10-06.md):
no existing Huron data needs preservation/conversion; plan a fresh deployment.
Schema bootstrap/Alembic initialization remains required. Nonempty deployment targets
must refuse and surface operator action, never reset; unrelated files/data/volumes
remain untouched. This is not deletion or production implementation authorization.
Current implemented behavior remains until each atomic owned semantic cutover.

Fail-on-stale-base is approved: keep the pinned base immutable throughout upload.
For an uncommitted attempt, compare expected base with current head atomically in the
catalog publication transaction under the serialization protocol to be qualified;
concurrent first pushes compare against expected empty head. The loser conflicts:
candidate hidden, no published lineage/receipt, cleanup recoverable, no unpublished
success acknowledgement. No implicit merge/rebase. After current authorization,
same-identity COMMITTED replay returns its original outcome even if head advanced.
Explicit retry against a newly resolved newer base uses a new operation identity and
fingerprint; never mutate the frozen attempt. Omitted metadata inherits the exact
newly pinned pair, not accidentally latest. Rawstore owns the typed conflict;
illustrative HTTP 409 and SDK/UI review-and-retry mapping remain proposed, not shipped.
Publication authority rechecks, nondisclosure and DB/FS crash evidence remain required.

## Prototype evidence

At initial planning none had executed. The schema experiment below has since been
independently qualified under the user's implementation authorization; other probes
and phase completion remain pending. Initial installed inspection: FastAPI 0.141.1, Pydantic 2.13.4,
SQLAlchemy 2.0.52, asyncpg 0.31.0, Alembic 1.19.1, jsonschema 4.26.0, HTTPX 0.28.1.
Current `migrations/env.py` says `target_metadata = None`; the existing
`scripts/check_schema_map.py` compares a docstamp, not reflected DB objects.
Empty user-owned `src/huron/core/catalog/interface/catalog_search.py` is not
prototype evidence. Old PyCasbin or 9 GiB receipts do not establish new contracts.

Bounded assignments, to create and run only in a separately authorized prototype
turn (all cwd root; all paths below proposed, currently absent):

| Probe owner / path and exact command | Scope and falsifiable result |
| --- | --- |
| Schema owner: `uv run python roadmap/prototypes/schema_bundle.py` | 30-case corpus: disjoint base/extensions; overlap/weakening rejected; nested fields/format policy; pinned controlled refs; invalid/cyclic/network refs; omitted/null/empty; schema publish between submission/retry. SDK and backend validator entry points agree on every case. Proposed Draft 2020-12 compile-then-close, not closed-base allOf. |
| Storage owner: `uv run python roadmap/prototypes/tus_crash.py --root roadmap/prototypes/data --bytes 1048576` | Two independent writers, variable PATCH, wrong offset, disconnect and process death around write/fsync/offset commit. HEAD never acknowledges bytes not durable; same-file fence survives process death; zero-length passes; bounded RAM. Local result is not NFS proof. |
| Publication owner: `uv run python roadmap/prototypes/release_crash.py --root roadmap/prototypes/data --bytes 1048576` | Base + add/delete/replace, independent inode copies, pins versus purge, crash each storage/DB boundary, idempotent outcome, ENOSPC/cancel and revocation. Real disposable PostgreSQL 16; never existing data. |
| Identity owner: `uv run python roadmap/prototypes/directory_authority.py` | Local signed OIDC fixture and external directory process: issuer/subject identity, email collision, stable admin group, nesting/cycles, version/TTL, revoke/outage; directory admin denied Huron read without role and Huron owner denied directory write without group. Token issuer/broker choice must precede SDK-token experiment. |
| Packaging owner: `uv run python roadmap/prototypes/sdk_isolation.py` | Build candidate SDK wheel, install into a clean temporary environment and inspect wheel/dependency graph; `from huron.client import Client` and `from huron.catalog import Dataset` work without server distribution/Core/asyncpg/SQLAlchemy. Also test coexistence without overwriting server huron files. |
| Query owner: `uv run python roadmap/prototypes/search_plan.py` | Disposable PostgreSQL 16; deterministic mixed-visible corpus; authorization before LIMIT/count, keyset ties, JSONB/FTS indexes via EXPLAIN ANALYZE, concurrent publish/search freshness and pinned export despite title edit. |
| Web owner: `npm run check` in a copied ignored `roadmap/prototypes/web-session/` after defining its package | Early fixture-only SSR browse/search + session + tus screen and same-origin routing/cookie/CSRF topology. Use local signed OIDC/session and directory/HTTP fixtures, proposed DTO examples explicitly labelled non-authoritative; inspect no tokens in browser storage. Named Playwright session and e2e. No dependency on 002 stack, 003 Google/directory receipts or later generated DTOs. Real backend mapping and Google/directory acceptance belong to 009 after 003–008. Package/script ownership is this prototype, not an existing root command. |
| Performance owner: `k6 run --vus 2 --iterations 2 roadmap/prototypes/k6-buffers.js` | Choose and record exact k6 binary version/image digest and version-matched official filesystem API before running. With a 1 MiB fixture and a disposable fixture HEAD/PATCH endpoint, qualify seek/read, variable bounded chunks, offset reconciliation/retries, RSS, fd cleanup and shared-file semantics; no whole-file-per-VU allocation. Pin plus minimal API/buffer receipt feeds 002. No dependency on product tus, real Google, 009, NFS or full load; 010 owns those qualifications. |

Prototype authors create those scripts with deterministic fixtures and small data;
record exact versions, commands, exits, observations, failed cases and limitations
inline in each downstream phase. No 500 GiB probe here. External-primary docs for
tus and pinned k6 APIs must be consulted at the installed version before coding.

## Exact scope and ownership

Only `roadmap/prototypes/{schema_bundle,tus_crash,release_crash,directory_authority,sdk_isolation,search_plan}.py`,
`roadmap/prototypes/web-session/`, `roadmap/prototypes/k6-buffers.js` and its
disposable fixture endpoint/data, ignored evidence, and decision updates to
`design/raw-first.md`/`CONTEXT.md` with explicit ownership. No product source,
existing test rewrites, active volume deletion, Compose or auth-server invention.
Read `core/raw/_impl/ingestion.py`, `rawstore/{materialize,commit}.py`,
`core/security/{oidc,roles}.py`, `core/catalog/types.py`, `migrations/env.py`,
Makefile, pyproject, Compose, web API README before each affected experiment.
No compatibility shims or legacy-data conversion requirement; fresh schema bootstrap
still needs a separately authorized isolated target, never an existing-volume reset.

## Interfaces and implementation examples

Existing: `RawIngestionService.receive_part(session_id, file_id, part, chunks,
content_length=...)`; `Dataset.project_id`; `MetadataSubmission(BaseModel)`.
Proposed (illustrative, not installed):

```python
bundle = registry.resolve(organization_version, collection_extension_version)
pair = submission_metadata.resolve(supplied=field_presence, base=exact_base, bundle=bundle)
receipt = await releases.publish(actor, submission_id, idempotency_key)
```

Do not use Python `None` for both absent and explicit JSON null. Publication owns
permission rechecks, pins and atomic DB receipt/lineage; storage owns durability;
applications map transport. Prototype public seams, not classes for every helper.

## Serial task slices

1. Decision approved 2026-10-06: fresh deployment, no legacy-data conversion. Pending:
   qualify bootstrap/nonempty-target refusal; never infer deletion approval.
2. Pending: identity owner/user compares SDK issuer/broker and Keycloak roles;
   operator/user nominates NFS hardware. Stale-base conflict policy approved above;
   publication owner still must qualify its atomic serialization/recovery algorithm.
3. Pending: schema + packaging probes one writer/reviewer at a time; publish corpus
   and exact move inventory for 002/004. No product deletions.
4. Pending: storage/tus/publication crash probes, then directory probe; carry real
   adapter evidence and failures to 003/005/006, not a generic “prototype passed”.
5. Pending: PostgreSQL query/export and early fixture-only SSR/session/topology probes;
   produce candidate 007/009 interface examples and operation-to-screen inventory.
   Current/proposed wire gaps stay explicit; 009 resolves against actual backend DTOs.
6. Pending: minimal pinned-k6 API/bounded-buffer probe against its fixture endpoint;
   hand pin, exact reproduction command and memory limitations to 002 and 010.
   No NFS or full-load claim. This probe needs no outputs from phases 002–010.
Each slice uses skills below for its area and the exact gate subset below; baseline
and independent rerun per slice; max three reviews, then plan escalation.

## Skills

Read `.agents/skills/design-plan/SKILL.md`, `.agents/skills/prototype/SKILL.md`,
`.agents/skills/implementation-plan/SKILL.md`, `.agents/skills/oop-design/SKILL.md`,
`.agents/skills/fastapi/SKILL.md`, `.agents/skills/postgresql-table-design/SKILL.md`,
`.agents/skills/svelte-code-writer/SKILL.md`,
`.agents/skills/svelte-core-bestpractices/SKILL.md`,
`.agents/skills/playwright-cli/SKILL.md`; Tailwind skill only if styling the probe.

## Acceptance and complete applicable gates

For completion, decision records name approver/date/evidence; unresolved outputs
keep affected downstream product work BLOCKED. Every
prototype has deterministic positive/negative/recovery results and limitations.
Do not fabricate results. Cwd root: `make docs`, `git diff --check`,
`python roadmap/check_docs.py`; check new ignored text whitespace. Node 22.23.2
PATH `/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH`, cwd `.agents/`:
`npm run check`, `npm test` if agent cross references change. Prototype commands
above are runnable only after this phase owns/creates their scripts.

No product Python gate for ignored probes alone. If a proposed change needs product
code, stop and replan instead. UI prototype uses its own package cwd: autofixer on
every changed `.svelte`, `npm run check`, `npm test`, `npm run lint`, `npm run build`,
`npm run test:e2e` after declaring those scripts; named-session local Playwright CLI
mobile/816px/wide/light-dark/keyboard/error-state checks, with owned server/browser.
No weakened assertions/skips; preserve existing fixtures; infrastructure unavailability
is BLOCKED. Capture commands/cwd/version/exit/log path and independent reviewer ID.

## Blockers and readiness

**Entry prerequisites:** reviewed bounded assignment, explicit separate authorization
for decision work or the named prototype, named owner and isolated-resource preflight.
Phase 000 tooling is the only prior phase dependency. Missing decisions and probe
outputs are this phase's work, not prerequisites to begin producing them. This
documentation-only turn authorizes neither experiments nor service/browser startup.

**Per-slice prerequisites:** slices 1–2 need the relevant decision owners, not prior
approval of their answers. Schema/packaging, local storage, query and fixture-only
web/k6 probes need their own reviewed hypotheses and disposable fixtures; they do
not require the implemented stack or all other probes. The SDK-token experiment
within slice 4 needs the issuer/broker choice from slice 2; publication conflict
cases use the approved policy above. Experiments use separately owned disposable
resources, not existing data. Local storage tests do not require nominated NFS.

**Completion criteria:** record actual decisions and all assigned probe receipts,
limitations, inventories and independent reviews; inline the applicable outputs in
downstream plans. Fresh deployment and explicit stale-base conflict are approved;
identity owner/user still owns credential flow, operator/user hardware nomination.
Recommend replaceable audience-bound token provider and baseline-before-SLO.
Missing outputs block affected downstream product
execution, not separately authorized work to obtain them. Actual NFS/full-load
evidence and eventual SLO approval are 010 outputs, not 001 completion criteria.

## Execution ledger

### Schema evidence — independent review 2 PASS (2026-10-05)

Isolated artifacts are under `roadmap/prototypes/schema/`, replacing only the older
flat-path illustration for this experiment. Reproduce from root:
`.venv/bin/python -B roadmap/prototypes/schema/schema_bundle.py` and
`.venv/bin/python -B roadmap/prototypes/schema/reproduce_numeric.py`.

Writer `ses_ef54624e6ffeD4LI60hgCgwJ1l` (preparatory) produced the restricted
compile-then-close validator and two candidate caller seams. Maximum review 1
`ses_ef53be358ffePC58OGZ2ioSv6K` found a JCS numeric freeze/identity defect despite
43 passing cases. Maximum prototype fix `ses_ef530bd00ffeP74SHc4LbotQmI` corrected
admission without weakening the original cases or limits. Fresh maximum review 2
`ses_ef523c37dffeU9gzrARyTKHFS2` returned PASS, terminal observed 07:11:45 UTC.

Independently verified: 430 cases per seam / 860 outcomes, 0/4 numeric counterexamples
remaining; an additional 6,020 numeric and 186 structural outcomes plus two state/
identity scenarios passed. Full bounded gate passed, including strict `make docs`,
`git diff --check`, `python roadmap/check_docs.py`, ignore checks and source/index
preservation. Original 43-case fingerprint and all 535 Git-visible files/index
unchanged. Runtime network guards observed zero attempts.

Evidence supports disjoint additive composition followed by nested closure,
controlled pinned references, presence-aware exact base inheritance, immutable
candidate pairs and bounded validation. Versions: Python 3.12.4, jsonschema 4.26.0,
referencing 0.37.0, rfc8785 0.1.4. Proposed profile 2 requires value- and byte-stable
ordinary-JSON/JCS round trips; notably it rejects integral floats with
`2**53 <= abs(x) < 1e21` while permitting compatible exponent-form values. This is
narrower than RFC8785 and is NOT approved product policy or shipped code. Both
candidate seams share a validator, so common-mode risk remains. No database,
authorization, built SDK/backend, durable retry, NFS or tus proof is established.

Downstream 004/008 plans must explicitly reconcile this numerical-profile proposal
and inline the evidence/limits before execution. This bounded PASS does not clear
the whole phase, other missing probes, tooling skill-resolution issue or user-owned
identity/hardware/SLO decisions. Fresh/stale-base choices were subsequently approved
on 2026-10-06; they do not qualify the serialization algorithm. Historical planning ledger below
describes its earlier state, not the current experiment count.

Current 2026-10-06 evidence update: SDK independent review 1 has successful bounded
checks but complete FAIL solely from 2,330 unchanged root-checker artifact whitespace
findings; no SDK defect found. Starlight writer FAIL (search-error/mobile tables),
independent review pending. Numeric comparison recommends correct codec/canonical
bytes authority rather than an artificial 1e20 restriction; unqualified proposal,
not approved policy. Restricted profile 2 remains qualified only as an experiment.
See [prerequisite receipt](../prerequisite-review-2026-10-06.md); no new PASS here.

Historical initial planning receipt: planning writer attempt 1; no execution/baseline/reviewer child for this phase;
review count 0; no prototype outcomes. Owned artifact is this ignored plan. Parent
must commission independent review. Runtime progress at least every 15 minutes;
parent polls at least once/minute; record role/model/session/times/current command.

## Escalation / final receipt

Not implemented. After review and separate authorization, decision-owner discussion
or `/prototype` with one bounded assignment above may produce its missing output;
it does not need all phase outputs in advance. Fill receipts only after actual work.
No MVP execution or prototype is authorized by this draft or this correction turn.
