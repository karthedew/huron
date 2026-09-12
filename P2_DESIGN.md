# P2 — Raw ingest & commit: design record

Phase 0 (this section, `## Authority order`, `## Roadmap Drift`, `## Clean` and
`## Verification receipts`) is a documentation grill only: it records where the project's own
documents describe P2 — Raw ingest & commit differently from what the code does. Nothing below
proposes a design; the design and the implementation plan build on top of it.

Grilled against `main` at `c5e35c7` (2026-09-04), working tree clean at the time of the grill
(`git status --short | wc -l` → 0). Other agents were active in the same checkout; every receipt
below names the commit it was taken at.

## Authority order

Reused from `P1_DESIGN.md` § "Authority order" and extended for P2:

- **Authoritative:** `design/` (per `CLAUDE.md`). `design/roadmap.html` carries *status* as well
  as intent; the P1 row's rule "Where this row and the code disagree, the code wins" is honored
  for status; `design/` wins on intent. For P2 the intent documents are `design/layer-raw.html`
  (§4 sessions and locking, §5 commit protocol, §6 dedup and sealing, §7 descriptive documents,
  §9 sweeper/reconciler), `design/api.html` §3 (the `/ingest-sessions` and `/transfer` rows) and
  §7 (error codes), `design/workflows.html` §4 (path A), `design/architecture.html`.
- **Executable schema truth:** `migrations/versions/0001_foundations.py` (the `ingest_sessions`,
  `dataset_revisions`, `ingest_files`, `outbox_events` DDL) and `0008_schema_conformance.py` (the
  revision guard trigger and `one_claim_per_revision_number`). `migrations/schema.sql` is derived
  (hand-maintained map, `Reflects: 0008_schema_conformance`, checked by
  `scripts/check_schema_map.py`).
- **Code contracts that P2 will implement against — checked as documents in their own right:**
  `src/huron/pkg/catalog/ports.py` (`RawStore`, `Metastore` Protocols); their docstrings are
  claims about intended behaviour and one of them is wrong (Drift 2).
- **Derived:** `docs/backend-design.md` (defers to the roadmap), `README.md`, `AGENTS.md`.
- **Sibling design records with their own grills, cited not repeated:** `P1_DESIGN.md`
  § "Roadmap Drift" (Drift 6 — release tags need a revision no HTTP path writes; Drift 7 —
  no property tests; both re-verified below), `SCHEMA_DESIGN.md` S7/S7a (reservation semantics)
  and `schema_audit.md` F8, `API_DESIGN.md` § "Roadmap Drift".
- **Retired:** `_to_delete/` (no ingest or rawstore tests ever lived there).
- **Shipped plans, history only:** `AUTH_IMPLEMENTATION_PLAN.md` (auth), `API_IMPLEMENTATION_PLAN.md`,
  `SCHEMA_IMPLEMENTATION_PLAN.md`, `RBAC_IMPLEMENTATION_PLAN.md`, `CONTROL_PLANE_PLAN.md`,
  `FINDINGS_IMPLEMENTATION_PLAN.md`, and `P1_IMPLEMENTATION_PLAN.md` (one status line still
  wrong — Drift 7).

Verification levels, matching `P1_DESIGN.md`: **L1** ran it, **L2** read the code that would run,
**L3** read a generated artifact (the OpenAPI document from `create_app`), **L4** read another
document. A live PostgreSQL was **not** reachable (`localhost:5433` refused; no container started,
per instructions), so every contract-suite claim is L2 — the test code was read, not run.

## Roadmap Drift

Ranked by consequence for a P2 design. Work tagged `todo` whose code does not exist (the
`/ingest-sessions` and `/transfer` routes, the sweeper, `record_revision`'s outbox transaction,
resumable parts) is not listed; it is the roadmap working as designed.

### Drift 1 — "implemented and unit-tested": the commit primitives, upload plan, sealing and the transition table have no tests

**Claim.** `design/roadmap.html:338-339` (P2 row): "Domain logic and the commit primitives are
implemented and unit-tested (`pkg/catalog/ingest.py`, `pkg/rawstore/`)"; restated at
`design/roadmap.html:557-558` (T2 milestone 8): "session state machine, upload planning,
hashing/dedup, staging + atomic-rename commit, all unit-tested".
**Reality.** (L1) `uv run pytest tests/unit/test_catalog_ingest.py tests/unit/test_rawstore_generation.py …`
→ 45 passed. (L2) `tests/unit/test_catalog_ingest.py` holds **three** tests, all about the lease
(`transition` refused past expiry, `heartbeat` refused past expiry, `heartbeat` refused when
terminal); `tests/unit/test_rawstore_generation.py` holds **five**, all about `write_generation` /
`CURRENT.json` / `write_tag_once`. `grep -rl` over `tests/` for `compute_upload_plan`,
`commit_envelope`, `write_part`, `seal(`, `hardlink_from_parent`, `create_staging`, `fsync_tree`,
`CrossDeviceCommitError` → **0 files each**. `git log --diff-filter=D` finds no deleted test that
ever referenced them. Untested therefore: the transition table itself (`ingest.py:48-62`,
including the "COMMITTING cannot be aborted" edge), `compute_upload_plan` (`ingest.py:200-236`),
`commit_envelope`'s four refusals and its retry-after-rename silence (`commit.py:139-157`),
`fsync_tree`, `assert_same_filesystem`, `seal` (`store.py:157-184`), `write_part`'s O_EXCL and
digest (`store.py:306-346`), `hardlink_from_parent` and its copy fallback (`store.py:104-140`),
`_safe_relative` (`store.py:349-374`).
**Class.** Claimed done, not done — the code exists; "unit-tested" is true of the lease arithmetic
and the P1 generation documents only.
**Consequence.** A P2 plan that "adds the HTTP surface over shipped, tested primitives" inherits
untested primitives; the crash-matrix, dedup and racing-`BeginIngest` gates have no unit
foundation to build on. The plan must own these tests before, not after, the routes.

### Drift 2 — `Metastore.begin_ingest` says "numbers are not reused"; `0008` and the roadmap say a retry re-takes the number

**Claim.** `src/huron/pkg/catalog/ports.py:142-145` (`Metastore.begin_ingest`): "the number is
unique within the dataset for the life of the session even if the session is later aborted;
numbers are not reused."
**Reality.** (L2) `migrations/versions/0008_schema_conformance.py:394-406`: "A reservation that
ends ABORTED or FAILED was never redeemed, so the number returns to the pool and the next session
takes it", enforced by `CREATE UNIQUE INDEX one_claim_per_revision_number ON ingest_sessions
(dataset_id, revision_number) WHERE state NOT IN ('ABORTED', 'FAILED')` after dropping `0001`'s
total `UNIQUE (dataset_id, revision_number)`. `design/roadmap.html:278-282` says the same and
calls it "what makes P2's gap-free numbering gate reachable at all". Pinned (L2, not run) by
`tests/contract/test_catalog_store.py:1292-1394` (retry re-takes an ABORTED and a FAILED number;
the dead row keeps its number) and `:1515-1579` (gap-free over two dead attempts). The allocator
both documents name is `max(committed) + 1` (`0008:116`, `design/layer-raw.html:252-253`).
**Class.** Documentation is wrong — the port docstring; `design/` and the DDL agree and win.
**Consequence.** High. An allocator written to the port's contract ("never reuse") burns a number
per failed attempt and fails the 1..100 gap-free gate; one written to `0008` passes. P2 must
rewrite this docstring alongside the first implementation of `begin_ingest`.

### Drift 3 — "streaming in-flight hashing": `write_part` takes the whole upload as a list

**Claim.** `design/roadmap.html:335-336` (P2 row): "streaming in-flight hashing";
`design/api.html:130`: `PUT /transfer/uploads/{file_id}/parts/{n}` "streamed, hashed in flight;
resumable"; `design/roadmap.html:558`: "hashing/dedup … all unit-tested".
**Reality.** (L2) `src/huron/pkg/rawstore/store.py:306-308`:
`def write_part(self, staging, rel_path, chunks: list[bytes]) -> tuple[int, str]` — the digest is
folded chunk by chunk as bytes are *written* (`store.py:339-342`), but the signature requires the
caller to have materialized every chunk first. Nothing accepts an iterator or an async byte
stream. `RawStore` in `ports.py:42-129` does not declare `write_part` at all (only
`create_staging`, `hardlink_from_parent`, `commit_envelope`, `seal`, `write_tag_once`).
**Class.** Code has diverged — the documents describe streaming from the request body; the code
buffers. Not a documentation fix.
**Consequence.** Medium-high. The P2 gate's 9 GiB file cannot pass through this signature without
9 GiB of process memory per part. P2's design must change `write_part` to consume an iterator (and
add it to the `RawStore` port), which is a contract change, not an addition.

### Drift 4 — the P2 row does not say which of its seven deliverables are "implemented", and two have no owner

**Claim.** `design/roadmap.html:335-340` (P2 row, `partial`): Delivers "Session state machine
(dataset-scoped lock), upload plan with hardlink dedup, streaming in-flight hashing, the POSIX
commit protocol (staging → fsync → atomic rename), sealing, download capabilities, `INDEX.json`.
Domain logic and the commit primitives are implemented …; the HTTP surface is milestone 8 in §3."
**Reality.** (L2) Item by item: state machine — `ingest.py:27-62` exists. Dataset-scoped lock —
only the DDL (`0001_foundations.py:131` `one_open_ingest_per_dataset`, pinned at L2 by
`test_catalog_store.py:1440-1466`), the `DatasetLocked` class (`errors.py:70-73`, raised
nowhere) and the `Metastore.begin_ingest` Protocol; `grep -rn "def begin_ingest" src/` → the
Protocol only, **no implementation**. Upload plan with hardlink dedup — `compute_upload_plan` and
`hardlink_from_parent` exist. Streaming hashing — Drift 3. Commit protocol — `commit.py` exists.
Sealing — `store.seal` exists. Download capabilities — **no code**: `grep -rn "capability"
src/huron` finds only RBAC capability bindings; nothing issues or checks a download capability.
`INDEX.json` — **no code**: zero occurrences under `src/` or `tests/`. Milestone 8's "Adds:" list
(`roadmap.html:559-566`) names neither download capabilities nor `INDEX.json`;
`design/layer-raw.html:290` assigns `INDEX.json` to "Best-effort … (reconciler owns it)", i.e.
P3, while the P2 row lists it as a P2 deliverable.
**Class.** Documentation is ambiguous (clarity), with an ownership gap for two items.
**Consequence.** Medium. A reader of the row cannot tell that the lock has no allocator behind it,
and `INDEX.json` and download capabilities belong to no milestone's "Adds". **Decision needed
(owner):** recommend `INDEX.json` be written best-effort at commit by P2 (layer-raw §5 step 8) and
its *regeneration* owned by P3's reconciler; download capabilities (`api.html:135`
`GET /revisions/{id}/files/{path}`) be added explicitly to milestone 8's "Adds".

### Drift 5 — layer-raw §7 says generation files are `O_EXCL` and allocated under a PostgreSQL row lock; the code replaces and uses a version guard, by P1 decision

**Claim.** `design/layer-raw.html:348-351`: "write `generations/{n+1:06d}.json` with `O_EXCL`
(never overwritten), then atomically replace `CURRENT.json` … Generation numbers are allocated
under a PostgreSQL row lock, so two concurrent edits cannot pick the same n."
**Reality.** (L2) `store.py:227-262` `write_generation` writes the numbered file through
`atomic_replace`, and its docstring explains why (a file already at that number can only be a
crashed attempt that never reached the row commit). (L1) `tests/unit/test_rawstore_generation.py:26`
`test_writing_the_same_generation_twice_replaces_its_document` pins it. `P1_DESIGN.md:620-622`
records the decision: "The numbered generation file is written with `atomic_replace`, not
`write_once`. Immutability … is guaranteed … by the committed `UPDATE ... WHERE version =
$expected` — not by `O_EXCL`." `stores/hierarchy.py:1033-1037` is that optimistic
compare-and-swap (`WHERE id = $1 AND version = $7`), not a row lock.
**Class.** Documentation is wrong — `design/layer-raw.html` was not updated when P1 decided this.
**Consequence.** Low for P2's own code; matters for P3's reconciler ("torn `CURRENT.json` →
repoint at the highest generation", `layer-raw.html:413-414`), whose reasoning must not assume a
stray higher-numbered file is committed. Record for the roadmap write-back.

### Drift 6 — P1 row is `partial` for a deliverable the row itself hands to T0-1 *(owner-decided)*

**Claim.** `design/roadmap.html:221` `P1 — Foundations … partial`; the Delivers cell,
`roadmap.html:244-248`: "OpenAPI published, TS + Python client cores generated `todo` … T0
milestone 1 owns both, marks them `todo` independently, and is this row's only remaining open
item."
**Reality.** Every clause of the gate column (`roadmap.html:265-271`) is met by what the tree
holds: (L1) `uv run lint-imports` → "Contracts: 7 kept, 0 broken"; (L1) `uv run pytest -q` →
674 passed; (L3) the OpenAPI document lists `POST/GET /api/v1/datasets/{dataset_id}/releases` and
`GET …/releases/{tag}`; (L2) the release-tag clause is proven exactly as the row says — see
`## Clean`, item 2. The only open item is one T0-1 owns and tags `todo` on its own row
(`roadmap.html:245-247`).
**Class.** Documentation is wrong (the tag). **Resolution decided by the owner:** move "OpenAPI
published, TS + Python client cores generated" to T0-1 outright; the P1 row reads `done`.
**Consequence.** Bookkeeping; it stops the P1 row from being re-grilled every phase.

### Drift 7 — `P1_IMPLEMENTATION_PLAN.md` M6.3 reads `Status: pending`; its write-back is in `c5e35c7`

**Claim.** `P1_IMPLEMENTATION_PLAN.md:1130` `**Status: pending**` under "Task M6.3 —
Documentation write-back".
**Reality.** (L1) `git show c5e35c7 --stat`: `design/roadmap.html` (68 lines), `design/api.html`
(4), `SCHEMA_IMPLEMENTATION_PLAN.md` (80), `FINDINGS_IMPLEMENTATION_PLAN.md` (8),
`API_IMPLEMENTATION_PLAN.md` (2), `P1_IMPLEMENTATION_PLAN.md` (2) — M6.3's "Modify" list. The one
status line the commit flipped in the P1 plan is **M6.2's** (the `+**Status: done**` sits
directly above the `#### Task M6.3` heading); M6.3's own line was left. Its verification, run
today: `grep -n "common.py\|platform_admin\|eleven packages\|twelve services\|ObjectRepoStore"
design/roadmap.html design/api.html` → nothing (pass); `grep -c "Status: pending"
SCHEMA_IMPLEMENTATION_PLAN.md` → 0 (pass); `grep -c "^\*\*Status: superseded\*\*"
FINDINGS_IMPLEMENTATION_PLAN.md` → 4 (pass); `grep -c "^\*\*Status: pending\*\*"
FINDINGS_IMPLEMENTATION_PLAN.md` → **14**, the plan expects 19 (the FINDINGS plan progressed
independently after M6.3 was written; not M6.3's to control); `grep -n "Schema conformance" -A 1
design/roadmap.html` → `done` (pass). `make docs` (`uv run --group docs zensical build --strict`)
was **not** run — the docs dependency group is not installed in the shared `.venv` and I did not
install it.
**Class.** Documentation is wrong (bookkeeping). **Resolution decided by the owner:**
`Status: done`. Recommend also replacing the stale "is 19" with the count at close, or dropping
the number, so the task's verification does not drift with another plan.

### Drift 8 — API §7 marks `ILLEGAL_INGEST_TRANSITION` `live` and its four siblings `reserved`; the column is undefined and unasserted

**Claim.** `design/api.html:230` `ILLEGAL_INGEST_TRANSITION | 409 | live`; `:238-242`
`MANIFEST_MISMATCH`, `INGEST_SESSION_EXPIRED`, `DATASET_LOCKED`, `DUPLICATE_CONTENT` `reserved`.
**Reality.** (L2) All five have classes in `pkg/catalog/errors.py` (`:39`, `:70`, `:76`, `:82`,
`:100`). Raise sites in `src/`: `IllegalIngestTransition` and `IngestSessionExpired` in
`ingest.py:162-192` (pure domain, no route); the other three nowhere. (L3) The OpenAPI document
has 0 ingest or transfer paths in 52 operations, so none can answer on the wire.
`grep -n reserved design/api.html | grep -v "<tr>"` → nothing: no sentence defines the column.
`tests/unit/test_error_contract.py:37-80` parses the disposition and never asserts on it.
**Class.** Documentation is wrong (inconsistent), whichever reading of "live" applies:
by "has a class" all five are live; by "raisable by a shipped route" none is.
**Consequence.** Low. When milestone 8 lands, P2 flips the ingest rows; the write-back should
define the column in one sentence (recommend: live = raisable by a shipped route) so the
error-contract test can assert it.

### Drift 9 — layer-raw naming: `.staging/{ingest_id}/` and `orgs/`

**Claim.** `design/layer-raw.html:128-130` `.staging/{ingest_id}/`; `:406` the sweeper "never
descends into `orgs/`".
**Reality.** (L2) `store.py:99` names the envelope `ingest_id.hex` (no hyphens); the root is
`organization/` (`store.py:78`, `paths.py:8`, and layer-raw's own tree at `:131`).
**Class.** Documentation is wrong. Cosmetic; the tree at `:128-148` is otherwise exactly what the
code and `paths.py` produce.

### Already recorded elsewhere — not repeated

`P1_DESIGN.md` Drift 6 (release tags need a revision no HTTP path writes) still holds and is the
P2 starting point; it is re-verified under `## Clean` item 2. `P1_DESIGN.md` Drift 7 (no
Hypothesis tests): `tests/unit/test_catalog_properties.py` now exists and is in the 674 — closed
for the pure core; nothing property-tests the ingest state machine or the upload plan (folded into
Drift 1). `P1_DESIGN.md` Status addendum decision 9 (`Metastore.record_revision` vs
`dataset_revisions.metadata_sha256 NOT NULL`) is an open design input for P2, not drift.

## Clean

Checked, no drift found. Later phases need not re-check these.

1. **`0008` reservation semantics and the revision guard** (roadmap "Schema conformance — `0008`"
   row, `roadmap.html:273-296`). (L2) `0008:373-391` `ingest_session_revision_guard()` fires
   `BEFORE INSERT OR UPDATE … WHEN (NEW.state = 'COMMITTED')`, requires the
   `dataset_revisions` row to exist with matching `(id, dataset_id, revision_number,
   manifest_sha256)` under `FOR KEY SHARE`; `0008:401-406` swaps the total unique for
   `one_claim_per_revision_number`; `0001:131` `one_open_ingest_per_dataset` survives as the lock.
   Pinned by `tests/contract/test_catalog_store.py:1106-1290` (guard: five assertions incl. the
   ABORTED/FAILED control at `:1237-1278`) and `:1281-1579` (six on the reservation lifecycle).
   (L1) `scripts/check_schema_map.py` → rc 0; `migrations/schema.sql:10` `Reflects:
   0008_schema_conformance`, `:143-149` names the trigger and both partial indexes. Design input
   for P2: the commit transaction must `INSERT` the revision row **before** flipping the session
   to `COMMITTED`, in one transaction (`layer-raw.html:288`), or the guard refuses it.
2. **P1 release-tag clause** (`roadmap.html:251-253`, `:269-271`). (L2)
   `tests/contract/test_hierarchy_store.py:186-200` `_insert_revision` inserts a `COMMITTED`
   `dataset_revisions` row by SQL "standing in for the P2 ingest writer";
   `tests/hierarchy_contract.py:222-233` seeds it, inserts release `v1`, and proves the second
   insert raises `TagExists`. (L2) `grep -rn "dataset_revisions" src/` → three `SELECT`/`JOIN`
   sites (`stores/hierarchy.py:1274, 1307, 1478`), zero writers; `grep -rn "ingest_sessions"
   src/` → nothing. `register_revision` exists only on the in-memory store
   (`hierarchy.py:700`). The clause is exactly true.
3. **API §3 ingest rows vs the live surface.** (L3) OpenAPI from `create_app`: 52 operations, 39
   paths, **0** `ingest`/`transfer` paths; present are the write-intent and three release
   operations. Expected — milestone 8 is `todo` — and no document claims otherwise:
   `datasets.py:453` ("The ingest/commit machinery and the credential vendor hang their work off
   this authorization") describes a dependency, not an existing route.
4. **`design/layer-raw.html` §4–§6 against the code.** State machine and its terminal set
   (`:249-250` ↔ `ingest.py:27-62`); TTL 2 h renewed by heartbeat (`:270` ↔ `ingest.py:168`);
   commit protocol steps 5–6, retry-after-rename treated as done (`:286-299` ↔
   `commit.py:139-157`); fsync-before-rename and fsync of the target's parent (`:320-321` ↔
   `commit.py:150-157`); `st_dev` checked at startup (`:325-326` ↔ `store.py:68-79`); sealing
   `0444`/`0555` (`:339` ↔ `store.py:157-184`); hardlink with copy fallback behind the same plan
   entry (`:342-344` ↔ `store.py:104-140`); the on-disk tree at `:128-148` ↔ `paths.py:1-23`.
5. **Path-rejection codes** (P2 gate, `roadmap.html:347`; API §7). (L2) codes raised in
   `pkg/catalog/manifest.py`/`paths.py`: `PATH_OUTSIDE_PAYLOAD`, `PATH_NOT_NFC`, `PATH_TOO_LONG`,
   `PATH_TRAVERSAL`, `PATH_CONTROL_CHARS`, `PATH_SEPARATOR`, `PATH_COLLISION`, `EMPTY_REVISION`,
   `PATH_RULE_VIOLATION` — exactly the nine `live` rows. (L1) `tests/unit/test_error_contract.py`
   green in the 674. The over-HTTP half awaits milestone 8.
6. **`Idempotency-Key` semantics** (`design/api.html:86`: principal-scoped, 24 h, reuse with a
   different body is `409 IDEMPOTENCY_KEY_REUSED`). (L2) `stores/hierarchy.py:48`
   `_CLAIM_TTL = timedelta(hours=24)`; `test_hierarchy_store.py:542` and `:610` pin serialization
   and expiry take-over. P2's `:commit` reuses this mechanism.
7. **Schema registry at ingest** (`design/catalog-search.html:400`; roadmap P5 `partial`, out of
   P2 scope). (L2) `src/huron/schema/__init__.py` exports `load_schema`, `validator`, `validate`
   over six packaged documents (`manifest-v1`, `metadata-v1`, `generation-v1`,
   `science-profile-v1`, `snapshot-provenance-v1`, `mcnp-run-1.0`); no `/schemas` route. Not a
   P2 claim.
8. **Derived and intent-only documents:** `docs/backend-design.md`, `README.md`, `AGENTS.md` make
   no present-tense ingest claims; `design/workflows.html` §4 and `design/architecture.html`
   describe intent only; `design/roadmap.html` §4 sequencing ("P2 before everything derived") is
   intent.
9. **Independence and the gate:** (L1) `uv run lint-imports` → 7 kept, 0 broken;
   `uv run pytest -q` → 674 passed, 10 deselected.

## Verification receipts

All at `c5e35c7`, 2026-09-04.

- `uv run pytest tests/unit/test_catalog_ingest.py tests/unit/test_rawstore_generation.py tests/unit/test_catalog_paths.py tests/unit/test_catalog_properties.py -q` → `45 passed`.
- `uv run pytest -q` → `674 passed, 10 deselected` (default `-m unit`).
- `for s in compute_upload_plan commit_envelope write_part "seal(" hardlink_from_parent create_staging fsync_tree CrossDeviceCommitError; do grep -rl "$s" tests/ | wc -l; done` → `0` for every symbol; `IngestSession(` / `IngestLease(` → 1 file each.
- `git log --diff-filter=D --name-only … | grep -i "test.*\(ingest\|rawstore\|commit\)"` → nothing.
- `grep -rn "def begin_ingest\|def record_revision\|def register_revision" src/huron` → `ports.py:139`, `ports.py:158` (Protocols), `stores/hierarchy.py:700` (in-memory).
- `grep -rn "INDEX.json" src/ tests/` → nothing; `grep -rn "capability" src/huron` → RBAC bindings only.
- OpenAPI walk (`create_app(settings=_oidc_settings(tmp), stores=memory_stores()).openapi()["paths"]`) → 52 operations / 39 paths; 0 containing `ingest` or `transfer`.
- `uv run lint-imports` → `Contracts: 7 kept, 0 broken.`
- `uv run python scripts/check_schema_map.py` → rc 0.
- `asyncpg.connect('postgresql://huron:huron@localhost:5433/huron')` → connection refused (contract suites not run).
- `git show c5e35c7 --stat` → the six documents listed in Drift 7; `git show c5e35c7 -U6 -- P1_IMPLEMENTATION_PLAN.md` → the flipped line is M6.2's.
- M6.3 greps → pass, pass (0), pass (4), **14 ≠ 19**, pass (`done`).
- `uv run mkdocs build --strict` → `Failed to spawn: mkdocs`; `Makefile:69` uses `uv run --group docs zensical build --strict`, not run.

No split is needed; the scope fit the budget.

## Current State

Phase 1 discovery, mapped against `main` at `c5e35c7` (2026-09-04), working tree clean. This
section is factual and structural: what exists, what it does, which conventions it follows, and
what is empty. It contains no recommendations. Every grill finding above is treated as
established and cited by drift number where the map touches it. Line references are to the files
as they stand at `c5e35c7`. Where a claim was proven by running code it says so (**proved**);
everything else is from reading.

### The tree in one paragraph

`src/huron` is 72 modules, 18,469 lines, in exactly three surfaces whose dependency runs one way,
enforced by import-linter (`pyproject.toml:165-169`): `huron.service` → `huron.pkg` →
`huron.schema`. `pkg/` holds four packages — `auth` (2,217 lines), `catalog` (2,403), `rawstore`
(590), `rbac` (1,340) — declared mutually independent (`pyproject.toml:174-179`); `catalog` and
`rbac` are additionally forbidden from importing any web framework, storage SDK or database driver
(`:195-215`). `service/api` (7,807 lines) is the only service. `schema/` is one module and six
JSON Schema documents. Everything P2 touches is in `pkg/catalog`, `pkg/rawstore`, `service/api`
and `migrations/`.

### `pkg/catalog` — the domain P2 drives

| Module | Lines | What it holds | P2 relevance |
|---|---|---|---|
| `ingest.py` | 236 | `IngestState` (7 members, `:27-44`), `TERMINAL_STATES` (`:47`), `_TRANSITIONS` (`:48-62`), `UploadAction`/`UploadPlanEntry` (`:65-86`), `IngestLease` (`:89-110`: ingest_id, dataset_id, revision_id, revision_number, expires_at), `IngestSession` (`:113-197`: lease, state, manifest_sha256, etag=1; `transition()` and `heartbeat(ttl=2h)` return copies with etag+1), `compute_upload_plan` (`:200-236`) | The whole state machine. `IngestSession` carries no committer, no parent revision, no manifest (only its digest), no per-file progress. |
| `ports.py` | 297 | Nine Protocols: `Clock`, `RawStore` (5 methods, `:42-128`), `Metastore` (3 async methods, `:131-186`), `SearchProjection`, `ScopedCredentials`, `CredentialVendor`, `JobDispatcher`, `Principal`, `PrincipalResolver` | The two ports P2 implements against. `Metastore.begin_ingest`'s docstring is wrong (Drift 2). `RawStore` omits `write_part` (Drift 3). |
| `models.py` | 102 | `EntityRef`, `RevisionRef` (id, dataset_id, number, manifest_sha256), `RevisionRecord` (`:56-83`: id, dataset_id, number, manifest_sha256, revision_path, committed_by, committed_at, file_count, total_bytes), `OutboxEvent` (`:87-102`: kind, subject_id, payload) | `RevisionRecord` has no `metadata_sha256`; the DDL column is `NOT NULL` (`0001:66`). `OutboxEvent` has no `id` or `created_at`; the DDL needs both (`0001:191-197`). |
| `errors.py` | 349 | `DomainError` (code, status_code, detail, context, `as_problem()`), 35 subclasses | P2 codes with classes: `DatasetLocked` 409 (`:70`), `IngestSessionExpired` 409 (`:76`), `ManifestMismatch` 400 (`:82`), `DuplicateContent` 409 (`:100`), `IllegalIngestTransition` 409 (`:305`), `PathCollision`, `EmptyRevision`, `FileTooLarge`/`TooManyFiles`/`RevisionTooLarge` 413, `IdempotencyKeyReused`, `PreconditionFailed` 412, `PathRuleViolation`, `ResourceNotFound`, `QuotaExceeded` 413. |
| `manifest.py` | 326 | `ManifestEntry` (path, size, sha256, media_type), `Manifest` (files sorted by path; `.sha256` = RFC 8785 identity; `.total_bytes`), `canonical_bytes`, `content_identity`, `validate_manifest_path`, `validate_manifest(entries, *, max_file_bytes=10 GiB, max_files=10_000, max_revision_bytes=1 TiB)` (`:238-312`) | The nine path codes (Clean item 5). Limits are module constants (`:32-34`), not settings. |
| `paths.py` | 513 | `revision_dir` → `{dataset}/raw/revision/{NNNNNN}--{id.hex}` (`:260-297`), `staging_dir` → `{root}/.staging/{id.hex}` (`:374-390`), `release_tag_file`, `dataset_dir`, `parse_revision_dir`, `RevisionPath`, `Slugged` | The layout P2's commit publishes into. |
| `ids.py`, `lifecycle.py`, `layers.py`, `amendments.py` | 52, 26, 327, 123 | `uuid7`; `DatasetLifecycle`; `Layer`, `LayerAction`, `required_capability` (`:168`), `ensure_layer_writable` (`:206-231`), `LayerWriteForbidden`; `Amendment`, `fold_amendments` | `layers.py` decides who may write `raw` (see "Observations"). Amendments are `:amend`, outside the P2 row. |

`pkg/catalog/__init__.py` re-exports the ingest, manifest and model surface; `paths`, `layers`,
`lifecycle`, `errors` and `ports` are imported by module.

### `pkg/rawstore` — the POSIX mechanics

`store.py` (416 lines) is `PosixRawStore(root, *, hardlink_fallback_copy=True)`; everything is
synchronous. `commit.py` (157 lines) holds the crash-safe primitives. Method by method:

| Symbol | Lines | Behaviour as coded |
|---|---|---|
| `initialize()` | `store.py:68-79` | mkdir `.staging` and `organization`, then `assert_same_filesystem` (`st_dev`). Called by `HierarchyRepository.__init__` (`repository.py:124`). |
| `create_staging(ingest_id)` | `:81-102` | `.staging/{hex}` and `payload/` both `0o700`; `mkdir` without `exist_ok`, so a second call raises `FileExistsError`. Returns `Path`. |
| `hardlink_from_parent(parent_payload, staging_payload, rel_path)` | `:104-140` | `_safe_relative` check, `os.link`, `_copy_exclusive` fallback (`O_EXCL`, `0o600`, fsync). |
| `commit_envelope(staging, final)` | `:142-155` → `commit.py:103-157` | Refusals in order: `final` exists and is not a completed retry → `FileExistsError`; `staging` not a dir → `FileNotFoundError`; no `COMMITTED` marker → `ValueError`; cross-device → `CrossDeviceCommitError`. Then `fsync_tree(staging)`, `os.rename`, `fsync_dir(final.parent)`. Retry with staging gone and `final/COMMITTED` present returns silently. |
| `seal(revision_dir)` | `:157-184` | files `0o444`, directories deepest-first `0o555`, root `0o555`. |
| `write_once`, `write_tag_once` | `:186-225` | `O_EXCL`, write-all, fsync file, fsync parent dir. |
| `write_generation`, `atomic_replace` | `:227-304` | P1's generation documents (Drift 5 — replace, not `O_EXCL`). |
| `write_part(staging, rel_path, chunks: list[bytes]) -> (size, hexdigest)` | `:306-346` | `O_EXCL` `0o600`, folds SHA-256 per chunk, fsyncs the **file only** — unlike `write_once` it does not `fsync_dir` the parent (`fsync_tree` at commit covers the entry). Not on the `RawStore` port (Drift 3). |
| `_safe_relative` | `:349-374` | refuses absolute, empty, `.`/`..` components; strips a leading `payload`. |
| `fsync_dir`, `fsync_tree`, `assert_same_filesystem`, `CrossDeviceCommitError(OSError)` | `commit.py:25-100` | as documented in Clean item 4. |

**Proved** (scratch root, `uv run python`, `c5e35c7`): `write_part` accepts a generator at
runtime — the body only iterates `chunks` — so the `list[bytes]` contract is the annotation's,
not the code's (`size=6`, digest correct); a second `write_part` at the same path →
`FileExistsError`; `chunks=[]` → `(0, sha256(b""))`; `rel_path="../escape"` → `ValueError`;
`commit_envelope` publishes and a second call after the rename returns silently; `seal` leaves
`0o444`/`0o555` and a write into the sealed payload raises `PermissionError` (euid 501,
non-root). Nothing in `src/` writes the `COMMITTED` marker, `manifest.json` or `metadata.json`
into a staging envelope; `commit.py:140,145` only tests for `COMMITTED`'s presence.

### `schema/` — the documents

`schema/__init__.py` (94 lines) exports `load_schema`, `validator`, `validate` over Draft
2020-12 with a `FormatChecker`. Six documents under `documents/`:

| Document | `$id` | Required members |
|---|---|---|
| `manifest-v1.json` | `urn:huron:manifest:1` | `schema`, `hash_algorithm`, `files` — the shape `Manifest.as_dict()` (`manifest.py:93-104`) emits. |
| `metadata-v1.json` | `urn:huron:metadata:1` | `schema`, `organization`, `project`, `dataset`, `revision_number`, `title`, `creators`, `committed_by`, `committed_at`, `data_classification`, `manifest_sha256`; optional `description`, `tags`, `source`, `coverage`, `extensions`. |
| `generation-v1.json` | `urn:huron:generation:1` | P1's descriptive documents (`repository.py:1188`). |
| `science-profile-v1.json`, `snapshot-provenance-v1.json`, `mcnp-run-1.0.json` | — | P5/P4; not P2. |

No document describes `COMMITTED`, `INDEX.json`, `CURRENT.json` or a release tag file (the tag is
`jsonable(Release)`, `repository.py:647`). **`huron.schema` has zero importers in `src/`**
outside its own package (`grep -rn "huron.schema" src/huron`): the manifest is validated by
`validate_manifest`, never against `manifest-v1.json`.

### `service/api` — the tier P2 extends

**Composition root.** `app.py:152-304` `create_app(*, settings, stores=None, oidc_verify=None)`.
The lifespan (`:188-256`) opens `asyncpg.create_pool(settings.database_url)` unless `stores` is
injected, builds `HierarchyRepository(PosixRawStore(settings.data_root), wired.hierarchy,
classification_vocabulary=…, rbac_store=wired.rbac)` (`:223-230`), a `RoleBindingAuthorizer`,
the optional OIDC resolver, and publishes one frozen `ApiRuntime` on `app.state.runtime`
(`:238-249`), then runs `_bootstrap`. `install_error_handlers(app)` (`:259`); `/healthz`,
`/readyz` (`:261-300`; the raw-root `stat` runs through `asyncify`, `:354`); `auth_routes.router`
and `v1.router` included (`:302-303`). `main.py` builds `app` from `settings_from_environment()`.

```mermaid
flowchart LR
    subgraph lifespan["create_app lifespan (app.py:188-256)"]
        S[ApiSettings] --> P{"stores injected?"}
        P -- no --> POOL[asyncpg.Pool]
        POOL --> PG6["_postgres_stores: 6 Postgres stores<br/>(hierarchy, rbac, api_keys,<br/>credentials, sessions, principals)"]
        P -- yes --> MEM["ApiStores from the caller<br/>(tests: memory_stores())"]
        S --> RS["PosixRawStore(settings.data_root)"]
        RS --> REPO["HierarchyRepository<br/>(calls raw_store.initialize())"]
        PG6 --> REPO
        MEM --> REPO
        S --> AUTHZ[RoleBindingAuthorizer]
        S --> OIDC["_configure_oidc → resolver | None"]
        REPO --> RT["ApiRuntime (frozen)<br/>settings · repository · authorizer ·<br/>api_keys · credentials · sessions ·<br/>principals · oidc_* · database_pool"]
        AUTHZ --> RT
        OIDC --> RT
        RT --> STATE["app.state.runtime"]
        REPO --> BOOT["_bootstrap: platform_owner grant"]
    end
    STATE --> DEP["runtime.py: api_runtime(request)<br/>→ Runtime, Repository, Settings,<br/>ApiKeys, Credentials, Sessions, Principals"]
    DEP --> ROUTES["routes/v1/* path operations"]
```

`runtime.py` (208 lines): `ApiStores` has exactly six fields (`:44-49`); `ApiRuntime` ten
(`:66-75`); seven `Annotated[…, Depends(...)]` aliases (`:184-189`). The raw store is reachable
from a request only as `runtime.repository.raw_store` (`app.py:374`); there is no `RawStore`
member on `ApiRuntime` and no alias for the authorizer.

**Settings** (`settings.py:55-125`): `env`, `auth_mode`, `data_root="/data"`, `database_url`,
`bootstrap_platform_owner`, `classification_vocabulary`, `oidc`, `password_login_enabled`,
`login_flow_secret`, `session_cookie_name`, `web_app_url`. Every one has at least one reader
(grep over `settings.<name>` in `src/`); none is ingest-related — no TTL, no part size, no
manifest limits, no sweep interval.

**Errors and problem+json.** `service/api/errors.py` adds nine tier codes (`Forbidden` 403,
`SlugExists`, `BindingExists`, `ServiceAccountExists`, `AttachmentExists`, `UsernameTaken`,
`PrincipalKindMismatch` 409, `OidcNotConfigured` 404, `DependencyUnavailable` 503).
`problems.py:97-219` installs six handlers: `DomainError` → its own status and `as_problem()`
body; `AuthError` → 401 + `WWW-Authenticate: Bearer`; `RoleError` → 422;
`StarletteHTTPException`; `RequestValidationError` → 422 `REQUEST_INVALID`; `Exception` → 500
`INTERNAL_ERROR`. `wire_error_codes()` (`:280-299`) enumerates every descendant of the three
bases; `tests/unit/test_error_contract.py` parses `design/api.html` §7 and asserts code and status
bijection (disposition parsed, never asserted — Drift 8). `problem_response(description)`
(`:305`) is what every `responses={…}` entry uses; `AUTHENTICATED_ERRORS` (`:334-338`) is the
v1 router's default set.

**Routes.** `routes/v1/__init__.py:28-32`: `APIRouter(prefix="/api/v1",
dependencies=[Depends(current_principal)], responses=AUTHENTICATED_ERRORS)`; ten endpoint modules
each with a twin under `routes/v1/schema/` holding only Pydantic bodies and views. The template
(`endpoints/datasets.py`): two routers per module where a collection hangs under a parent
(`project_datasets = APIRouter(prefix="/projects/{project_id}/datasets", tags=["datasets"])`,
`router = APIRouter(prefix="/datasets", tags=["datasets"])`, `:69-70`); every path operation is
`async def`, returns a view model with `model_config = ConfigDict(from_attributes=True)`, declares
`responses={404: problem_response(...), 409: …}`, and its docstring puts caller-facing prose
before `\f` and `Args`/`Returns` after (ruff `D301` waived for `endpoints/*.py`,
`pyproject.toml:95`). A creating POST takes `idempotency_key: IdempotencyHeader`, builds
`IdempotencyClaim(principal=actor.subject, key=…, request_sha256=request_sha256("dataset", …))`
(`datasets.py:122-134`) and passes it to the repository; the guard is
`actor: Annotated[Principal, Depends(require_project("dataset.create"))]` (`:99`).
`preconditions.py`: `IdempotencyHeader` (required, min 1), `IfMatchHeader`, `expected_version()`
accepting `"N"`, `W/"N"` or bare `N` (`:32-67`). `pagination.py`: `Page[ItemT]`, `PageLimit`
(1..200), `PageCursor` (`v1:` prefix), `page(window, View, key=…)` over a store `Window`, and
per-level cursor key codecs.

The write-intent stub: `datasets.py:436-471` `POST /{dataset_id}/layers/{layer}/write-intents`
takes `grant: Annotated[LayerWrite, Depends(dataset_layer_writer)]` and returns a `WriteIntent`
view (`schema/datasets.py:124-131`) whose `capability` is the string `f"data.write@{layer}"`.
Nothing is persisted and no token is minted; its docstring names the ingest machinery as a future
consumer (Clean item 3).

**Authorization** (`authorization/`, entered only through `__init__`, `pyproject.toml:233-238`):
`current_principal` → `Principal` (`pkg/auth/principal.py:17-37`: subject, groups, scopes,
project_id, authentication_method, `kind` = `"user"` | `"service_account"`);
`dataset_scope(repository, dataset_id, visibility)` reads the dataset under the caller's
visibility then its project unrestricted, so 404 precedes 403 (`scopes.py:70-99`);
`check(cache, repository, principal, capability, scope, *, layer=None)` is the one allow-or-403
call (`decisions.py:151-192`); `require_dataset(capability)` / `require_project(capability)`
factories (`guards.py:124-222`); `dataset_layer_writer` → `LayerWrite(principal, layer)` runs
scope → `parse_layer` → `ensure_layer_writable(layer, principal.kind)` → `check(..., "data.write",
layer=…)` (`guards.py:239-279`). Capability vocabulary (`pkg/rbac/roles.py:64-84`): 17 names;
layer-scoped are `data.read`/`data.write` with the layer passed separately (`layers.py:168-181`).
`SERVICE_ACCOUNT_CAPABILITIES = {dataset.create, dataset.update, dataset.discover}` (`:49-51`);
`SERVICE_ACCOUNT_LAYERS = {silver, gold}` (`:44`). There is no `dataset.read_raw` capability
(`design/api.html:135` names one for downloads).

**Repository.** `repository.py` (1,217 lines) `HierarchyRepository(raw_store: PosixRawStore,
hierarchy: HierarchyStore, *, classification_vocabulary, rbac_store: RbacStore)` — typed against
the **concrete** `PosixRawStore`, not the `RawStore` port (`:101`). Its documented invariant
(`:79-93`): one store transaction per write, row first, then the durable document via
`await asyncify(...)`, then `writer.remember(claim, Replay(...))`, all before the transaction
commits (`create_release`, `:624-654`, is the closest analogue to a P2 commit). `_claimed_result`
(`:141-164`) is the replay short-circuit. `request_sha256(operation, *parts)` (`:1198-1217`)
NUL-joins the operation name and fields. The RBAC methods (`:844-1121`) pass through to the RBAC
store. There is no revision or ingest method; `revision_ref` is read for release creation only.

**Stores.** `stores/__init__.py` is the only public surface (`pyproject.toml:244-254`).
`stores/ports.py` declares four tier-owned Protocols — `RbacStore`, `ApiKeyWriter`,
`HierarchyWriter` (`:405-557`: `claim`, `remember`, `insert_organization/project/dataset/release`,
`update_*` with `expected_version`), `HierarchyStore` (`:559-762`: `transaction() ->
AbstractAsyncContextManager[HierarchyWriter]`, point reads taking `Visibility`,
`revision_ref(dataset_id, revision_number)` taking none (`:633-648`), windows,
`project_visibilities`, `dataset_parents`) — and three values: `Window`, `IdempotencyClaim`
(principal, key, request_sha256), `Replay(kind: Literal["organization", "project", "dataset",
"release"], resource_id)` (`:392-402`). `stores/hierarchy.py` (1,523 lines) holds both
implementations of the hierarchy port: `InMemoryHierarchyStore` (`:389`, with a test-only
`register_revision` at `:700`) and `PostgresHierarchyStore(pool, *, clock=None)` (`:1111`). The
Postgres conventions, which every P2 store would be measured against:

- `transaction()` is `async with self._pool.acquire() as connection, connection.transaction():
  yield _PostgresTransactionWriter(connection, self._clock)` (`:1139-1148`); reads go straight to
  `self._pool.fetchrow(...)`.
- SQL is inline triple-quoted text with `$n` parameters and explicit casts (`$4::timestamptz`,
  `$3::uuid[]`); rows are decoded by `stores/rows.py` functions (`rows.release`,
  `rows.revision_ref`), never by the store itself.
- Visibility is threaded as a SQL predicate ahead of `LIMIT`: `($3::boolean OR d.project_id =
  ANY($4::uuid[]) OR d.id = ANY($5::uuid[]))` (`:1277-1278`, `:1169-1170`).
- Idempotency (`:782-864`): `INSERT INTO idempotency_records ... ON CONFLICT (principal, key) DO
  UPDATE ... WHERE idempotency_records.expires_at <= EXCLUDED.created_at RETURNING key`; on no row,
  `SELECT ... FOR UPDATE` and compare `request_sha256` → `IdempotencyKeyReused`; `remember` stores
  `{"kind","id"}` with `status_code = 201`; TTL 24 h (`_CLAIM_TTL`, `:48`; Clean item 6).
- Optimistic concurrency is `UPDATE ... WHERE id = $1 AND version = $expected` (`:1033-1037`,
  Drift 5), raising `PreconditionFailed` on zero rows.
- A `Clock` (`pkg/catalog/ports.py:29`) is injected for timestamps; the only implementation is the
  private `_SystemClock` (`hierarchy.py:51`).

**Execution model** (`API_DESIGN.md` § "Design 1", rule at its line 19-23): a path operation is
`async def` iff its body must `await`; any blocking call inside one — filesystem, `fsync`,
password hashing — is `await asyncify(callable)(...)`. Uses in `src/`: `repository.py` (six
`_write_generation`, one `write_tag_once`), `app.py:354`, `users.py:105,151`,
`login.py:68,130` (with a limiter). `tests/unit/test_execution_model.py` is the tripwire that
raw-store filesystem calls never run on the loop thread; all 52 operations are coroutines.

### `migrations/` — the DDL P2 writes to

Migrations are Alembic revisions whose `upgrade()`/`downgrade()` call `op.execute` on
module-level raw-SQL strings, with a long module docstring explaining each block
(`0008_schema_conformance.py:1-150`, `:452-460`). Head is `0008`. `migrations/schema.sql` is a
hand-maintained map with `-- Reflects: 0008_schema_conformance` (`:10`) and `-- [db]`
annotations per mechanism (`:143-149` name the guard trigger and both partial indexes);
`scripts/check_schema_map.py` fails `make lint` when the stamp is not the Alembic head, so a P2
migration must also move the stamp and update the map. Only `0001` and `0008` touch the P2 tables.

| Table | Columns (type, constraint) | Mechanisms | Writers in `src/` |
|---|---|---|---|
| `ingest_sessions` (`0001:115-132`) | `id uuid PK`; `dataset_id uuid NOT NULL FK datasets`; `revision_id uuid NOT NULL UNIQUE`; `revision_number int CHECK 1..999999`; `manifest_sha256 text` (64-hex CHECK); `state text CHECK IN (PREPARING, UPLOADING, VERIFYING, COMMITTING, COMMITTED, ABORTED, FAILED)`; `etag int > 0 DEFAULT 1`; `expires_at`, `created_at`, `updated_at timestamptz`; `created_by text` | `one_open_ingest_per_dataset` UNIQUE `(dataset_id) WHERE state NOT IN (COMMITTED, ABORTED, FAILED)` (`0001:131`) — the dataset lock; `one_claim_per_revision_number` UNIQUE `(dataset_id, revision_number) WHERE state NOT IN (ABORTED, FAILED)` (`0008:404-406`, replacing `0001:129`'s total UNIQUE); trigger `ingest_sessions_revision_guard` BEFORE INSERT OR UPDATE WHEN `NEW.state = 'COMMITTED'` requiring a `dataset_revisions` row matching `(id, dataset_id, revision_number, manifest_sha256)` under `FOR KEY SHARE` (`0008:373-391`) | **none** |
| `ingest_files` (`0001:134-144`) | `file_id uuid PK`; `ingest_id uuid FK ingest_sessions ON DELETE CASCADE`; `path text`; `size bigint >= 0`; `expected_sha256` (64-hex); `action text CHECK IN (upload, hardlink)`; `state text DEFAULT 'PENDING'` (**no vocabulary CHECK**); `completed_parts jsonb DEFAULT '[]'` (array CHECK, `0008:323-325`); `UNIQUE (ingest_id, path)` | — | **none** |
| `dataset_revisions` (`0001:61-75`) | `id uuid PK`; `dataset_id FK`; `revision_number int 1..999999`; `manifest_sha256`, `metadata_sha256` (both 64-hex, **both NOT NULL**); `revision_path text NOT NULL UNIQUE`; `file_count int > 0`; `total_bytes bigint >= 0`; `state text DEFAULT 'COMMITTED'` CHECK IN (COMMITTED, EXPIRED_PARTIAL, EXPIRED, PURGED, DEGRADED) (`0008:249-251`); `committed_by text`; `committed_at timestamptz`; `UNIQUE (dataset_id, revision_number)`; `UNIQUE (dataset_id, manifest_sha256)` — the DDL behind `DUPLICATE_CONTENT`; `UNIQUE (id, dataset_id)` (`0008:165-166`, the composite-FK target for `releases`) | `releases_revision_dataset_fk` references it | **none**; three read sites (`hierarchy.py:1274, 1307, 1478`) |
| `audit_events` (`0008:416-445`, rebuilt as a plain table) | `id uuid PK`; `kind text` (lowercase dotted CHECK, 2..63); `actor text`; `subject_kind text`; `subject_id uuid NULL`; `payload jsonb` (object CHECK); `created_at timestamptz` | index `(created_at, id)` | **none** |
| `outbox_events` (`0001:191-199`) | `id uuid PK`; `kind text` (same format CHECK, `0008:292-295`); `subject_id uuid NOT NULL`; `payload jsonb` (object CHECK); `created_at`; `processed_at NULL` | partial index `outbox_unprocessed (created_at, id) WHERE processed_at IS NULL` | **none** |
| `idempotency_records` (`0001:201-210`) | `(principal, key) PK`; `request_sha256`; `status_code int`; `response jsonb`; `created_at`, `expires_at` | — | `stores/hierarchy.py` only |

Neither `ingest_sessions` nor `dataset_revisions` has a parent-revision column; `ingest_files`
has no column for the digest actually observed on upload and no `media_type`. `ingest_sessions`
has no full index on `dataset_id` (the two partial unique indexes lead with it; `0008`'s FK-index
sweep at `:178-188` did not touch this table). The `jobs`, `revision_amendments` and
`reconciliation_findings` tables have no reference in `src/` either.

### Tests and the validation gate

- **Suites** (`pyproject.toml:147-156`, `docs/getting-started/testing.md`): `unit` (default via
  `addopts = "-m unit --strict-markers"`), `contract` (Docker; testcontainers
  `PostgresContainer("postgres:16")`, migrated with the project's own Alembic via `_migrate`,
  `tests/contract/test_hierarchy_store.py:84-114`), `integration` (Compose stack), `acceptance`
  (full stack). `tests/integration/` and `tests/acceptance/` each contain only `__init__.py`
  (**proved**: `find … -name "*.py" | xargs wc -l` → 1 line each). CI (`ci.yml`) runs `lint`,
  `unit` with `--cov=src/huron`, `contract` (`-m contract`), and `integration` treating "no tests
  collected" (rc 5) as success; **there is no acceptance job.** Coverage floor `fail_under = 89`
  (`pyproject.toml:263`), a ratchet.
- **Gate** (`Makefile:66-77` `lint`): `ruff check`, `ruff format --check`, `pydoclint src
  migrations scripts`, `mypy` (strict over `src/huron`), `ty check`, `lint-imports` (7
  contracts), `check_schema_map.py`, `radon cc --min C`, `radon mi --min B`, `complexipy
  --max-complexity-allowed 15`, `pyscn check`. Docstrings: Google style, `Args`/`Returns`/
  `Yields`/`Raises` matching the signature, enforced by ruff `D` + pydoclint
  (`docs/getting-started/docstrings.md`); tests need a one-line summary on every module, class,
  test and fixture (`D105`, `D107` waived under `tests/**`).
- **Unit conventions**: 49 modules named `tests/unit/test_<area>_<module>.py`; tests are
  `test_<sentence>`; API tests build `TestClient(create_app(settings=ApiSettings(env=
  "development", auth_mode="dev-headers", data_root=str(tmp_path / "data"),
  database_url="postgresql://unused", classification_vocabulary=[…],
  bootstrap_platform_owner="root"), stores=memory_stores()))` **as a context manager** so the
  lifespan runs (`test_api_catalog_hierarchy.py:77-89`); principals are bound with the
  `X-Huron-Subject` dev header and a fresh `Idempotency-Key: uuid4()` per call (`:66-68`);
  `tests/unit/support.py:15` `memory_stores()` builds the six in-memory stores. Hypothesis is a
  dev dependency and used by `test_catalog_properties.py`.
- **Contract conventions**: module-level `pytestmark = pytest.mark.contract`; one synchronous
  test per container that `asyncio.run`s a set of scenarios; backend-agnostic scenarios live in
  `tests/hierarchy_contract.py` (`seed_hierarchy`, `scenario_1..9`) and run against both the
  in-memory and Postgres stores; `_insert_revision` (`test_hierarchy_store.py:185-200`) is the raw
  SQL stand-in for the P2 writer (Clean item 2); `test_catalog_store.py` pins the `0008`
  mechanisms with raw SQL and deletes its `ingest_sessions` rows afterwards (`:1281-1290`). Its
  module docstring (`:14-17`) still says the hierarchy "has no Postgres-backed store of its own
  yet", which `PostgresHierarchyStore` has since made stale.
- **P2's own tests today**: `test_catalog_ingest.py` — three lease tests (`:32-65`);
  `test_rawstore_generation.py` — five generation tests. Nothing else (Drift 1).

### Diagram (a) — the ingest state machine, coded vs documented

```mermaid
stateDiagram-v2
    [*] --> PREPARING
    PREPARING --> UPLOADING
    UPLOADING --> VERIFYING
    VERIFYING --> COMMITTING
    COMMITTING --> COMMITTED
    PREPARING --> ABORTED
    UPLOADING --> ABORTED
    VERIFYING --> ABORTED
    PREPARING --> FAILED
    UPLOADING --> FAILED
    VERIFYING --> FAILED
    COMMITTING --> FAILED
    COMMITTED --> [*]
    ABORTED --> [*]
    FAILED --> [*]
    note right of COMMITTING
        Coded (ingest.py:58): no ABORTED edge.
        layer-raw §4 (:249-250) says only
        "ABORTED/FAILED terminal"; it does not
        name this exception. §4 (:270) also gives
        a project admin a force-abort — the code
        has no path for it.
    end note
    note left of PREPARING
        Every transition() first checks the lease
        (ingest.py:160-162): past expires_at a
        non-terminal session raises
        INGEST_SESSION_EXPIRED before the table
        is consulted. The DDL (0001:121-123) admits
        the same seven names and no others;
        one_open_ingest_per_dataset releases the
        lock only on a flip into one of the three
        terminal states — expiry alone does not.
    end note
```

### Diagram (b) — where a P2 request would attach to today's seams

A map of the existing seams a `POST /ingest-sessions` … `:commit` flow would pass through, in
the order `design/layer-raw.html` §5 prescribes; dashed participants do not exist.

```mermaid
sequenceDiagram
    participant C as Client
    participant R as routes/v1 (async def)
    participant G as authorization<br/>current_principal → dataset_scope →<br/>ensure_layer_writable → check(data.write, layer=raw)
    participant F as facade seam<br/>(HierarchyRepository today;<br/>no ingest facade exists)
    participant M as ingest persistence port<br/>(Metastore: Protocol only,<br/>no implementation)
    participant DB as PostgreSQL<br/>ingest_sessions · ingest_files ·<br/>dataset_revisions · audit_events · outbox_events
    participant S as PosixRawStore (sync,<br/>via await asyncify(...))
    participant FS as raw root<br/>.staging/{hex} → organization/…/raw/revision/{NNNNNN}--{hex}

    C->>R: POST /ingest-sessions (manifest, metadata draft, Idempotency-Key)
    R->>G: guard
    G-->>R: LayerWrite(principal, raw) or 404/403/409
    R->>F: validate_manifest → Manifest.sha256; compute_upload_plan(parent manifest?)
    F->>M: begin_ingest(dataset_id, manifest_sha256)
    M->>DB: INSERT ingest_sessions (state=PREPARING, number=max(committed)+1)<br/>one_open_ingest_per_dataset → DATASET_LOCKED
    M-->>F: IngestLease
    F->>S: create_staging(ingest_id)
    S->>FS: mkdir .staging/{hex}/payload (0o700)
    F-->>C: 201 session + UploadPlan (upload | hardlink)
    C->>R: PUT part n (request body stream)
    R->>S: write_part(staging/payload, rel_path, chunks)  ← list today (Drift 3)
    S->>FS: O_EXCL create, hash in flight, fsync file
    R->>M: record part / file digest (ingest_files) — no port method exists
    C->>R: POST :verify
    R->>F: compare observed digests to manifest → MANIFEST_MISMATCH
    F->>S: hardlink_from_parent(...) per HARDLINK entry
    C->>R: POST :commit (If-Match etag, Idempotency-Key)
    R->>M: lock session row, assert VERIFYING + etag + digest [layer-raw §5 step 2]
    R->>S: write manifest.json, metadata.json, COMMITTED; seal [steps 4-5] — no writer exists
    S->>FS: commit_envelope: fsync_tree → rename → fsync parent [step 6, durability point]
    R->>M: record_revision(RevisionRecord, [OutboxEvent])
    M->>DB: ONE transaction: INSERT dataset_revisions → UPDATE ingest_sessions COMMITTED<br/>(guard trigger fires here) → audit_events → outbox_events → idempotency remember [step 7]
    R-->>C: 201 Revision
```

### Conventions the design must follow or explicitly reject

1. **Two port conventions coexist.** Consumer-owned ports for what the catalog needs from outside
   live in `pkg/catalog/ports.py` and are satisfied structurally by another package
   (`RawStore` ← `PosixRawStore`). Tier-owned storage ports live in `service/api/stores/ports.py`
   and are satisfied by one in-memory and one Postgres adapter in the same package, exported only
   through `stores/__init__.py`. Both are `typing.Protocol`; neither uses inheritance
   (`test_hierarchy_store.py:668` pins this).
2. **One endpoints module, one schema twin**, routers declared with prefix and tags, included in
   `routes/v1/__init__.py`; the credential requirement is on the v1 router, never per route.
3. **Errors are `DomainError` subclasses whose class name mirrors the code**; the code must also be
   a row of `design/api.html` §7 or `test_error_contract.py` fails. No route raises `HTTPException`.
4. **Idempotency**: `IdempotencyHeader` required on creating POSTs; `IdempotencyClaim` scoped to
   `actor.subject`; `request_sha256(operation, *fields)`; claim → write → `remember` inside one
   store transaction; replay returns the original resource. `Replay.kind` is a four-member
   `Literal`.
5. **`If-Match`** carries an integer `version`; `expected_version()` parses it; the store's
   compare-and-swap raises `PreconditionFailed`.
6. **Blocking I/O is off the loop**: `await asyncify(sync_callable)(...)`, pinned by
   `test_execution_model.py`. `PosixRawStore` is entirely synchronous.
7. **SQL style**: inline parameterised text on `asyncpg`, explicit casts, `rows.py` decoders,
   visibility predicate ahead of `LIMIT`, `FOR UPDATE` where a row is read-then-written.
8. **Migrations**: raw SQL through `op.execute`, an explanatory module docstring, an exact
   `downgrade()`, `schema.sql` map and `Reflects:` stamp updated in the same change, contract tests
   that pin each new mechanism by raw SQL.
9. **Records** are frozen/slotted dataclasses (`records.py`, `models.py`); views are Pydantic with
   `from_attributes=True`; `jsonable()` renders UUIDs and `Z`-suffixed datetimes for on-disk
   documents; on-disk JSON is RFC 8785 canonical (`canonical_bytes`).
10. **Docstrings on everything**, Google style, `\f` in route docstrings, no lint suppressions,
    no references to plans or phases anywhere in code or tests.
11. **Import contracts**: nothing in `service/api/routes/**`, `repository`, `app` or
    `authorization` imports a `stores.*` submodule; routes never import `authorization.*`
    submodules; `pkg/*` packages never import each other; `catalog`/`rbac` never import
    `asyncpg`, `fastapi`, `starlette`, `httpx`, `structlog`, `prometheus_client`.

### Emptiness findings

Each verified at `c5e35c7` by the grep shown or by running the code.

1. `ingest_sessions`, `ingest_files`, `audit_events`, `outbox_events`, `revision_amendments`,
   `jobs`, `reconciliation_findings`: **zero references in `src/`** (`for t in …; grep -rl $t
   src/huron`). `dataset_revisions`: read at three sites, written nowhere. `idempotency_records`:
   written by the hierarchy store only.
2. Catalog Protocols with **no implementation**: `Metastore` (`begin_ingest`,
   `record_revision`, `resolve_tag` — `grep -rn "def begin_ingest\|def record_revision\|def
   resolve_tag" src/huron` → `ports.py` only), `SearchProjection`, `CredentialVendor`,
   `JobDispatcher`. `PrincipalResolver`: `pkg/auth` has resolvers with a `resolve(credential)`
   shape (`oidc.py`, `apikeys.py`) but nothing in `src/` is typed against the port. `Clock`: one
   private implementation, `_SystemClock` (`hierarchy.py:51`).
3. **`RawStore` has no consumer**: `grep -rn "\bRawStore\b" src/huron` finds only its definition
   and two docstring mentions; `HierarchyRepository` is typed against `PosixRawStore`
   (`repository.py:101`).
4. `RawStore` vs `PosixRawStore` (Drift 3): the port declares `create_staging`,
   `hardlink_from_parent`, `commit_envelope`, `seal`, `write_tag_once`; the implementation adds
   `initialize`, `staging_root`, `write_once`, `write_generation`, `atomic_replace`, `write_part`.
   Nothing in `src/` calls `create_staging`, `hardlink_from_parent`, `commit_envelope`, `seal` or
   `write_part` (grep over `src/huron` outside `rawstore/`).
5. **No writer** for `COMMITTED`, `manifest.json`, `metadata.json` or `INDEX.json` in `src/`;
   `commit.py:140,145` only reads `COMMITTED`'s presence. `huron.schema.validate` has **zero
   callers** in `src/`.
6. **Packages the design names that do not exist**: `metastore` (7 mentions across
   `design/roadmap.html`, `design/architecture.html`, `docs/getting-started/repository-layout.md`),
   `job runner`/`jobrunner` (10), `sweeper` (5), `telemetry` (4), `lakectl` (4). `src/huron/pkg`
   holds `auth`, `catalog`, `rawstore`, `rbac`; `src/huron/service` holds `api`; `scripts/` has no
   `lakectl` or sweeper (`grep -rln "lakectl\|sweeper\|reconcil" src/ scripts/` → nothing).
7. **Error codes with a class and no raise site** (Drift 8): `DatasetLocked`, `ManifestMismatch`,
   `DuplicateContent`, `QuotaExceeded` (`grep -rn "… (" src/huron | grep raise` → only the two
   `IngestSessionExpired` and one `IllegalIngestTransition` raises in `ingest.py:162-192`).
   `design/api.html:135` names a `dataset.read_raw` capability that is not in
   `CAPABILITIES` (`roles.py:64-84`).
8. **Settings with no reader**: none. **Ingest settings**: none exist; the manifest limits are
   constants in `manifest.py:32-34`, the lease TTL a default argument in `ingest.py:168`.
9. **Test suites with no tests**: `integration`, `acceptance` (and no CI job for the latter).
10. `Replay.kind` (`stores/ports.py:401`) admits four hierarchy kinds; no ingest or revision kind.
11. `RevisionRecord` lacks `metadata_sha256` (DDL `NOT NULL`, `0001:66`; P1 status addendum
    decision 9 left this open); `OutboxEvent` lacks `id` and `created_at` (DDL `0001:192,196`).
12. `ingest_files.state` has a default and no vocabulary CHECK; every other state column in the
    schema has one (`0008:227-266`).

### Observations that shape the design (factual, no recommendation)

- **Transaction-across-file-I/O is a stated P1 invariant and a stated P2 prohibition.**
  `repository.py:81-84` documents that a hierarchy write holds the store transaction across the
  `asyncify`'d document write (`create_release`, `:624-654`, does so). `design/layer-raw.html`
  §3 (the paragraph before §4) says "no database transaction is ever held across file I/O or
  hashing", and §5 step 7 is "ONE short PG transaction" after the rename. Both are authoritative
  for their own writes; the P2 design must say which discipline the revision commit follows and
  why the two coexist.
- **The lock and expiry are decoupled in the DDL.** `one_open_ingest_per_dataset` is released
  only by a state flip to a terminal value; `expires_at` does not enter the predicate. A session
  that expires without being flipped still holds the dataset lock, and `IngestSession.transition`
  refuses to advance it (`ingest.py:160-162`). Some actor — the next `begin_ingest`, a sweep, or
  the client's abort — has to perform the flip; nothing in `src/` does.
- **Numbering and the lock are two mechanisms.** `one_claim_per_revision_number` (partial on
  `ABORTED`/`FAILED`) and `one_open_ingest_per_dataset` (partial on all three terminals) are pinned
  separately by `test_catalog_store.py` (Clean item 1). `max(committed) + 1` is named by
  `0008:116` and `layer-raw.html:252-253`; the DDL alone does not serialise two concurrent
  allocators reading the same `max` — a `UniqueViolation` on one of the two indexes is what
  decides the race.
- **Service accounts cannot write `raw`.** `ensure_layer_writable` (`layers.py:206-231`) admits
  `service_account` on `silver`/`gold` only and `SERVICE_ACCOUNT_LAYERS` excludes `raw`, while
  milestone 8 (`roadmap.html:559-566`) has "an organization service account, whose dataset-CRUD
  authority is intrinsic" creating datasets at intake. Under the current rules such an account can
  mint the dataset (`SERVICE_ACCOUNT_CAPABILITIES`) but never obtain `data.write@raw`.
- **The commit guard fixes the order of the commit transaction.** `ingest_sessions_revision_guard`
  fires on the `UPDATE … SET state = 'COMMITTED'` and requires the `dataset_revisions` row to
  already exist in the same transaction (Clean item 1); the revision `INSERT` must precede the
  session flip, and `metadata_sha256` must be known by then.
- **Upload transport is undecided in the code.** `design/api.html:130-131` gives `PUT
  /transfer/uploads/{file_id}/parts/{n}` and `:complete`; milestone 8 says "resumable multipart
  upload with per-part progress"; `ingest_files.completed_parts` is the ledger; `write_part`
  writes a whole file once with `O_EXCL`. Nothing in `src/` reads a request body as a stream.
- **`INDEX.json` is claimed by two phases** (Drift 4): the P2 row's Delivers and
  `layer-raw.html:290` step 8 ("Best-effort … reconciler owns it") and `:412` ("Stale
  `INDEX.json` → regenerate"). The on-disk tree puts it at `raw/revision/INDEX.json` beside the
  revision directories (`layer-raw.html:138`). Nothing specifies its content.
- **`metadata.json` needs inputs the session does not carry.** `metadata-v1` requires `creators`,
  `data_classification`, `title`, `committed_by`, `committed_at` and the org/project/dataset
  names; the API row (`api.html:123`) says the `POST /ingest-sessions` body carries a "metadata
  draft"; the DDL has no column for it and `IngestSession` no field.
- **Parent-revision resolution has one source in the design and none in the code.**
  `layer-raw.html:263-266`: hardlink sources come from the parent revision's `manifest.json`
  "read from the filesystem — storage is consulted as the authority on every ingest".
  `compute_upload_plan` takes a `Manifest`; nothing reads one back from disk.

## Design Tasks

Seven tasks, each sized for one design subagent in a 30k–50k token budget. Ordered so that
contracts precede the implementations that consume them: 1 → 2 → 3 → 4 → 5 → 6 → 7. Each says
what it owns, what it must not decide, and where its budget goes. Documentation write-back for
the owner-decided drifts (6, 7) and the cosmetic ones (5, 9) is a plan milestone, not a design
task; the two write-backs that need a decision — the `begin_ingest` docstring (Drift 2) and the
§7 disposition column (Drift 8) — are assigned below.

### Design 1 — Ingest session domain model and state machine

**Scope.** The pure domain in `pkg/catalog`: what an `IngestSession` and its lease carry so the
service can drive every route in milestone 8 and every clause of the P2 gate without reaching
past the domain; the transition table's edges including the coded "COMMITTING cannot be aborted"
rule and the documented project-admin force-abort; the lease policy (2 h, renewed by heartbeat
and — per `layer-raw.html:270` — by any successful part upload); the per-file progress model that
`ingest_files` and the upload plan imply; the `RevisionRecord` and `OutboxEvent` shapes against
the DDL they must fill (`metadata_sha256`, event `id`/`created_at`); and the domain-level
verification step (declared manifest vs observed digests → `ManifestMismatch`,
`compute_upload_plan` against a parent manifest). It also owns the unit-test contract for all of
this (Drift 1's untested transition table and upload plan; property tests for both).

**Acceptance criteria.**
- Every route in milestone 8 (create, heartbeat, upload, verify, commit, abort, sweep) is
  expressible as a named domain operation on the session value with a stated precondition, state
  edge, lease effect and error class.
- The transition table is written out edge by edge with the `COMMITTING → ABORTED` refusal and
  the force-abort path each decided and justified against `layer-raw.html` §4.
- `RevisionRecord` and `OutboxEvent` are reconciled with `dataset_revisions` and `outbox_events`
  column by column; every `NOT NULL` column has a named source.
- The per-file model states what a file's states are and what `completed_parts` means for a
  whole-file `O_EXCL` write.
- The `Metastore.begin_ingest` docstring is rewritten to the `0008` semantics (Drift 2).
- Lists the unit and property tests, by module and name, that pin each rule.

**Files.** `pkg/catalog/ingest.py`, `models.py`, `errors.py`, `manifest.py:200-312`, `ports.py:
131-186`, `migrations/versions/0001_foundations.py:61-75, 115-144`, `0008:360-406`,
`design/layer-raw.html` §4, `tests/unit/test_catalog_ingest.py`, `test_catalog_properties.py`.
**Settled from** the artifacts plus `layer-raw.html` §4–§5. **Resolves** Drift 1 (domain half),
Drift 2. **Ownership.** Owns every domain shape; Design 3 must not add fields to `IngestSession`
or `RevisionRecord`, and Design 4 must not invent request-level state the domain lacks.

### Design 2 — The `RawStore` port and `PosixRawStore`'s streaming, document and commit contract

**Scope.** The port that P2 actually consumes and the implementation's contract behind it: adding
`write_part` to `RawStore` with an iterator input (Drift 3 — the runtime already accepts one,
**proved**; the annotation and the port do not), and whether the port gains a consumer at all
(today `HierarchyRepository` is typed against the concrete class); the per-part durability
question (`write_part` fsyncs the file, not its directory entry); how the envelope's
`manifest.json`, `metadata.json` and `COMMITTED` are written durably and in what order relative to
`seal` and `commit_envelope` (`layer-raw.html` §5 steps 4–6); how the parent's `manifest.json` is
read back for hardlink resolution (`layer-raw.html:263-266`); the hardlink-then-seal interaction
(a `0o444` parent file linked into a `0o700` staging tree; `seal` afterwards); the resumable /
partial-write story for a file that `O_EXCL` refuses to reopen; `CrossDeviceCommitError`'s
surfacing at startup vs at commit; the staging-name write-back (Drift 9). It owns the unit tests
for every primitive Drift 1 lists as untested (`commit_envelope`'s four refusals and retry
silence, `fsync_tree`, `assert_same_filesystem`, `seal`, `write_part`, `hardlink_from_parent`
with and without fallback, `_safe_relative`), including the crash-injection technique the
crash-matrix gate will reuse (patching `os.rename`/`os.fsync`).

**Acceptance criteria.**
- `RawStore` lists every method P2 calls, each with its invariant, error behaviour and durability
  guarantee stated; every method has exactly one `PosixRawStore` implementation and the port has
  at least one typed consumer.
- The input contract of `write_part` is stated for a request-body stream, including chunk
  ownership, back-pressure and what happens on a mid-stream failure (the `O_EXCL` file that now
  exists).
- The order of the six on-disk steps of a commit (documents, seal, fsync, rename, parent fsync,
  retry) is written as a sequence with the crash state after each step named against
  `layer-raw.html` §5's table.
- Says whether the sync store stays sync and is dispatched via `asyncify`, or gains an async
  surface, and why.
- Names the tests, by module and name, for each primitive.

**Files.** `pkg/rawstore/store.py`, `commit.py`, `pkg/catalog/ports.py:42-128`,
`repository.py:99-139, 1161-1189`, `app.py:330-374`, `design/layer-raw.html` §2, §5, §6,
`API_DESIGN.md` § "Design 1", `tests/unit/test_rawstore_generation.py`,
`tests/unit/test_execution_model.py`. **Settled from** code and design documents, with scratch-
filesystem proofs. **Resolves** Drift 3, Drift 9, Drift 1 (rawstore half); records Drift 5 for
the write-back. **Ownership.** Owns mechanics only; the *content* of `manifest.json`,
`metadata.json`, `COMMITTED` and `INDEX.json` belongs to Design 5, which must hand this task the
byte payloads and nothing more.

### Design 3 — Ingest persistence: the port and its PostgreSQL implementation

**Scope.** Where the ingest store lives and what it guarantees. Which of the two port conventions
applies (`pkg/catalog/ports.py` `Metastore` vs a tier-owned `stores/ports.py` Protocol with an
in-memory twin, which is what every existing route is tested against); the `begin_ingest`
allocator — `max(committed) + 1` and the lock — including how two racing calls are serialised so
exactly one wins with a `DATASET_LOCKED` for the other (the DDL leaves this to a
`UniqueViolation` on one of two partial indexes; the design must say which row lock or index
error is the arbiter and which error each maps to); what an expired-but-open session means to the
allocator (Observations: the lock is released only by a state flip); heartbeat and transition
compare-and-swap on `etag`; per-file rows in `ingest_files` and their state vocabulary (today
unchecked); the commit transaction in `layer-raw.html` §5 step 7 order — `dataset_revisions`
INSERT, session flip (guard fires), `audit_events`, `outbox_events`, idempotency `remember` —
with the transaction-across-file-I/O question from Observations settled for this write; the
`DUPLICATE_CONTENT` mapping of `UNIQUE (dataset_id, manifest_sha256)`; `Replay.kind`'s extension;
and whether a migration `0009` is needed (candidates seen: `ingest_files.state` CHECK, an
observed-digest column, a parent-revision column, a `dataset_id` FK index, `metadata_sha256`'s
source) with the `schema.sql` map and `check_schema_map` consequences.

**Acceptance criteria.**
- Names the port, its module, its two adapters, and every method with SQL-level semantics (which
  statements, which locks, which unique index or trigger is relied on for each refusal).
- The racing-`BeginIngest` and gap-free 1..100 gates each trace to a specific lock or index and a
  specific error mapping.
- The commit transaction is written as an ordered statement list satisfying
  `ingest_sessions_revision_guard`.
- The expired-session rule is decided: who flips it, when, and which error the next
  `begin_ingest` sees while it is unflipped.
- If a migration is needed: the DDL, the `downgrade()`, the `schema.sql` map lines and the
  contract assertions that pin each mechanism; if not, says so and why each candidate was rejected.
- The in-memory adapter's contract-scenario list (`hierarchy_contract.py` style) covers every
  method.

**Files.** `stores/ports.py`, `stores/hierarchy.py:48-160, 761-870, 1111-1148, 1268-1320`,
`stores/rows.py`, `pkg/catalog/ports.py:131-186`, `migrations/versions/0001_foundations.py:61-75,
115-144, 179-210`, `0008_schema_conformance.py:245-251, 285-295, 323-325, 360-445`,
`migrations/schema.sql`, `scripts/check_schema_map.py`, `SCHEMA_DESIGN.md` S7/S7a,
`tests/contract/test_catalog_store.py:1106-1579`, `tests/hierarchy_contract.py`,
`design/layer-raw.html` §4–§5. **Needs** code, DDL and design documents; a scratch PostgreSQL
(testcontainers) for proof of the allocator race. **Resolves** Drift 2 (implementation half),
Drift 4's "lock has no allocator". **Ownership.** Owns all persistence and locking semantics,
including the expiry rule; Design 6 owns only where and when a sweep runs; Design 1's shapes are
inputs, not this task's to change.

### Design 4 — The `/ingest-sessions` HTTP surface

**Scope.** Milestone 8's routes as the service tier would write them, consuming Designs 1–3 and
5: the endpoints module and its schema twin; the routes create (with dataset-creation-at-intake
under `dataset.create` and the service-account-on-`raw` tension from Observations), get,
heartbeat, upload transport (the `PUT /transfer/uploads/{file_id}/parts/{n}` row vs a
per-file streamed `PUT`, resumability via `completed_parts`, streaming the request body into
`write_part` without materialising it), verify, commit (`If-Match` on the session `etag`,
`Idempotency-Key` through the existing claim machinery, 201 with a revision view), abort; the
authorization dependency (`dataset_layer_writer` for `data.write@raw`; the write-intent stub's
fate); the error rows this surface makes `live` and the one-sentence definition of the §7
disposition column (Drift 8); the facade question — extend `HierarchyRepository` or introduce a
sibling facade — against `API_DESIGN.md` § "Design 3"'s decomposition; the `ApiRuntime`/
`ApiStores` wiring for the new store; the execution-model rule for a streaming route; the
unit tests over `TestClient` with in-memory stores.

**Acceptance criteria.**
- Every route has: method, path, request body/headers, guard, domain operation called, success
  status and view, and the full list of error codes with the condition that raises each; the
  list reconciles with `design/api.html` §3 and §7 and with `test_error_contract.py`'s bijection.
- The upload transport is decided with its resumability semantics and its memory bound stated.
- The intake authorization matrix (human with `dataset.create` + `data.write@raw`; organization
  service account) is written out with the `ensure_layer_writable` consequence resolved or
  escalated as an open question with a recommendation.
- The facade decision is made with reference to the API sweep's conclusion, not re-derived.
- The §7 disposition column has a definition and the set of rows to flip is enumerated.
- Names the unit tests (module and test names) that reach every route and every error code.

**Files.** `routes/v1/endpoints/datasets.py`, `routes/v1/schema/datasets.py`,
`routes/v1/__init__.py`, `preconditions.py`, `pagination.py`, `authorization/guards.py:174-279`,
`decisions.py:151-192`, `scopes.py:70-99`, `pkg/rbac/roles.py:44-84`,
`pkg/catalog/layers.py:168-231`, `repository.py:69-165, 575-654`, `runtime.py`, `app.py:152-304`,
`problems.py:97-219, 280-338`, `design/api.html` §3 (`:118-140`), §7 (`:226-244`),
`API_DESIGN.md` § "Design 1"–"Design 3", `tests/unit/test_api_catalog_hierarchy.py:60-100`,
`tests/unit/test_error_contract.py`, `tests/unit/test_execution_model.py`, the `fastapi` skill.
**Needs** code and design documents. **Resolves** Drift 8, Drift 4 (milestone 8's "Adds" list
for download capabilities, jointly with Design 5). **Ownership.** Owns everything on the wire and
the facade; must not redefine domain shapes (Design 1), store semantics (Design 3) or document
content (Design 5).

### Design 5 — Revision documents on disk: `manifest.json`, `metadata.json`, `COMMITTED`, `INDEX.json`, sealing and download capabilities

**Scope.** The content contracts of everything a commit leaves on disk and the read side that
serves it: `manifest.json` (`urn:huron:manifest:1`, from `Manifest.as_dict()`), `metadata.json`
(`urn:huron:metadata:1` — where each required member comes from, given the session carries no
metadata draft and the DDL has no column for it; whether `huron.schema.validate` is finally
called), `COMMITTED` (the reconciler's reconstruction record per `layer-raw.html:303-306`:
digests, counts, committer, timestamp; no schema exists), `INDEX.json` (content, location at
`raw/revision/INDEX.json`, write-at-commit best-effort vs P3 regeneration — **Drift 4's open
ownership question, carried here with the grill's recommendation: P2 writes it best-effort at
commit, P3's reconciler owns regeneration; do not decide, present both with consequences**),
`metadata_sha256` as the digest of `metadata.json`'s canonical bytes, sealing's place in the
sequence (before the rename per §5 step 5), and the download side — `GET /revisions/{id}/manifest`
streamed from disk and `GET /revisions/{id}/files/{path}` issuing a short-lived download
capability re-authorised per file (`api.html:134-135`; the named `dataset.read_raw` capability
does not exist and `data.read@raw` does) — **the second Drift 4 open question: whether download
capabilities are in milestone 8's "Adds", carried with the grill's recommendation to add them
explicitly.**

**Acceptance criteria.**
- Each document has its schema (existing `$id` or a proposed new one under `schema/documents/`),
  its exact member sources, its canonicalisation and its writer's durability primitive.
- The source of every `metadata-v1` required member at intake is named; any member that cannot be
  sourced from the request, the session or the hierarchy is flagged as an open question.
- `INDEX.json` and download capabilities are each presented as an open question with two
  options, consequences for P2 and P3, and a recommendation; neither is decided.
- The download path's authorization (capability name, per-file re-check, TTL) is specified
  against the existing `data.read`/layer model.
- Names the tests that prove a round trip (manifest written → read back → identical identity)
  and the NFC/NFD, zero-byte and 8-level-nesting cases at the document level.

**Files.** `src/huron/schema/__init__.py`, `schema/documents/manifest-v1.json`,
`metadata-v1.json`, `pkg/catalog/manifest.py:36-125, 161-197`, `models.py`, `paths.py:260-297`,
`records.py:197-221`, `pkg/rbac/roles.py:44-84`, `design/layer-raw.html` §2 (`:120-148`), §5
(`:278-330`), §6, §9 (`:396-420`), `design/api.html:118-140`, `design/roadmap.html:335-347,
557-566`. **Settled from** the artifacts and design documents. **Resolves** Drift 4 (as open
questions with recommendations). **Ownership.** Owns content and the read routes' contract;
Design 2 owns how bytes reach disk, Design 4 owns the ingest routes, Design 3 owns the
`metadata_sha256` column's write.

### Design 6 — Expiry sweep and lease reaping

**Scope.** Milestone 8's "expiry sweep" as a P2 deliverable, distinct from P3's staging-only
sweeper with fraction guard and dry-run (`roadmap.html` P3 row; `layer-raw.html` §9). What the
P2 sweep does (flip expired non-terminal sessions so the dataset lock is released — the rule
itself is Design 3's; this task takes it as given), where it runs (a periodic task in the
lifespan, a `lakectl` command that does not exist, or the next `begin_ingest` lazily), how it is
clocked (`Clock` injection for tests), its idempotency and bound per pass, whether it deletes
staging directories at all in P2 or leaves that to P3, what it audits, and how it is tested
without wall-clock waits.

**Acceptance criteria.**
- The sweep's contract: input (which rows), effect (which flip, which audit event), bound, and
  the exact boundary with P3's sweeper stated in one sentence each.
- The placement decision with its failure mode under multiple API replicas.
- The tests, by name, that prove an expired session releases the lock for the next
  `begin_ingest` and that a live one is untouched.

**Files.** `app.py:188-256`, `runtime.py`, `pkg/catalog/ports.py:29-39`, `ingest.py:135-197`,
`stores/hierarchy.py:46-62`, `design/layer-raw.html` §4 (`:268-272`), §9,
`design/roadmap.html` P3 row and milestone 8. **Settled from** the artifacts. **Resolves** the
"expiry sweep" clause of milestone 8. **Ownership.** Does not own the expiry rule (Design 3);
owns the runner and its schedule.

### Design 7 — Test strategy for the P2 gate

**Scope.** Mapping every clause of the P2 gate (`roadmap.html:341-347`) and milestone 8's gate
(`:567-569`) to a suite, a fixture and a named test, given that `integration` and `acceptance`
are empty and `acceptance` has no CI job: round trip with NFC/NFD pairs, a zero-byte file,
8-level nesting and the 9 GiB file (how a 9 GiB file is exercised in CI — sparse file, reduced
size behind a marker, or a nightly job); the crash matrix (kill after each of §5's eight steps;
the injection technique from Design 2; the reconciler half is P3 and must be scoped out
explicitly); two racing `BeginIngest` calls and gap-free 1..100 (contract suite, real PostgreSQL);
replayed commit; dedup 1-of-500 with an independently complete revision (link counts, sealed
modes); every path-rejection code over HTTP; the "resume re-sends only incomplete files" clause;
the both-backends contract pattern for the new store; property tests for the state machine and
upload plan; the coverage ratchet and the `radon`/`complexipy` ceilings a streaming route must
stay under; the CI change if a new suite is to run.

**Acceptance criteria.**
- A table: gate clause → suite marker → fixture(s) → test module and name → what it asserts →
  whether it needs Docker, the Compose stack, or nothing.
- Every P2 gate clause and every milestone-8 gate clause appears exactly once; clauses that belong
  to P3 are listed as excluded with the reason.
- The 9 GiB and crash-matrix techniques are stated concretely enough to implement.
- Says which CI job runs each new suite and what changes in `ci.yml` and `pyproject.toml`
  markers, if anything.

**Files.** `pyproject.toml:147-156, 259-263`, `.github/workflows/ci.yml`, `Makefile:60-77`,
`tests/unit/support.py`, `tests/unit/test_api_catalog_hierarchy.py:60-100`,
`tests/contract/test_hierarchy_store.py:1-115, 185-240`, `tests/hierarchy_contract.py`,
`tests/contract/test_catalog_store.py:1281-1400`, `tests/unit/test_catalog_properties.py`,
`docs/getting-started/testing.md`, `design/roadmap.html:341-347, 567-569`. **Settled from** the
artifacts once Designs 1–6 have named their symbols. **Resolves** Drift 1 (the "unit-tested" claim
becomes true or the row is corrected). **Ownership.** Owns suite placement and fixtures; the
tests each earlier design names are inputs it arranges, not re-decides.

### Ordering and shared objects

| Object | Touched by | Decision owner |
|---|---|---|
| `IngestSession`, `IngestLease`, `RevisionRecord`, `OutboxEvent` | 1, 3, 4 | 1 |
| `RawStore` port, `write_part`, `commit_envelope` sequence | 2, 4, 5 | 2 |
| Allocator, dataset lock, expiry rule, commit transaction, migration `0009` | 3, 6, 4 | 3 |
| Routes, views, error rows made live, §7 column definition, facade | 4, 5 | 4 |
| `manifest.json`, `metadata.json`, `COMMITTED`, `INDEX.json`, download capability | 5, 2, 4 | 5 (open questions carried, not decided) |
| Sweep placement and schedule | 6, 3 | 6 |
| Suite placement, fixtures, CI | 7, all | 7 |
| `Metastore.begin_ingest` docstring (Drift 2) | 1, 3 | 1 |
| Write-back of Drifts 5, 6, 7, 9 | plan | owner-decided; plan milestone |

The Phase 1 scope fit the budget; no split of this discovery pass is recommended.

## Design 1 — Ingest session domain model and state machine

Designed against `main` at `c5e35c7`. Everything below stays inside `pkg/catalog`'s import
contract (no framework, driver or SDK); persistence, locking, file mechanics, wire format and
document content are stated as contracts on Designs 2–6, not decided here. Claims marked
**proved** were run (see § Receipts).

### Target design

**Module layout.** No new modules. Three existing modules change and one docstring moves:

| Module | Change |
|---|---|
| `pkg/catalog/ingest.py` | `IngestState` docstring rewritten; `TRANSITIONS` made public; `LEASE_TTL`, `PART_BYTES` constants; `IngestSession` gains `created_by`, `parent_revision_id` and the named operations below, loses `transition`/`heartbeat`; new `FileState`, `IngestFile`; `UploadPlanEntry` loses `parent_path`, gains `part_count`; `compute_upload_plan` gains `part_bytes` and the hash-algorithm guard; new `revision_record` and `revision_committed` factories. |
| `pkg/catalog/models.py` | `RevisionRecord` gains `metadata_sha256`; `OutboxEvent` gains `id`, `created_at`. |
| `pkg/catalog/ports.py` | `Metastore.begin_ingest` docstring replaced (text below); signature widened to return the session. |
| `pkg/catalog/__init__.py` | re-exports `FileState`, `IngestFile`, `UploadAction`, `UploadPlanEntry`, `revision_record`, `revision_committed`, `LEASE_TTL`, `PART_BYTES`. |

**Types and interfaces** (`pkg/catalog/ingest.py` unless noted; every dataclass
`frozen=True, slots=True`; every operation returns a new value; `now` is always required — the
domain never reads the wall clock, the caller passes `Clock.now()`):

```python
LEASE_TTL = timedelta(hours=2)          # layer-raw §4: renewed by heartbeat and by every accepted part
PART_BYTES = 64 * 1024**2               # one upload part; a file has max(1, ceil(size / PART_BYTES)) parts

class IngestState(StrEnum):
    """The states of one ingest session; PREPARING → UPLOADING → VERIFYING → COMMITTING → COMMITTED."""
    PREPARING, UPLOADING, VERIFYING, COMMITTING, COMMITTED, ABORTED, FAILED

TERMINAL_STATES: frozenset[IngestState]
TRANSITIONS: Mapping[IngestState, frozenset[IngestState]]   # the table in the next subsection, as data

class FileState(StrEnum):
    """Whether a planned file's bytes are in the envelope and proven: PENDING until then, COMPLETE after."""
    PENDING, COMPLETE

@dataclass(frozen=True, slots=True)
class IngestLease:                       # unchanged
    ingest_id: UUID; dataset_id: UUID; revision_id: UUID; revision_number: int; expires_at: datetime

@dataclass(frozen=True, slots=True)
class IngestFile:
    """One manifest entry's progress through the session: what was planned, what has arrived, what is proven."""
    file_id: UUID
    path: str                            # the manifest path, NFC, beginning with payload/
    size: int
    expected_sha256: str
    action: UploadAction
    part_count: int                      # >= 1 for UPLOAD, 0 for HARDLINK
    state: FileState = FileState.PENDING
    completed_parts: frozenset[int] = frozenset()

    @property
    def received(self) -> bool:
        """Return whether every planned part has arrived (vacuously false for a HARDLINK file)."""
    def part_received(self, part: int) -> IngestFile:
        """Record part ``part`` (1-based) as durably in the envelope; idempotent for a part already held."""
        # Raises ValueError if part not in 1..part_count; IllegalIngestTransition if action is HARDLINK or state is COMPLETE
    def completed(self, *, observed_size: int, observed_sha256: str) -> IngestFile:
        """Prove the received bytes against the manifest: COMPLETE on a match, ManifestMismatch otherwise."""
        # Raises IllegalIngestTransition unless action is UPLOAD, state is PENDING and received is True;
        # ManifestMismatch(context={"path", "expected_size", "observed_size", "expected_sha256", "observed_sha256"})
    def linked(self) -> IngestFile:
        """Record that the parent's bytes were linked in; a HARDLINK file inherits the parent's digest unhashed."""
        # Raises IllegalIngestTransition unless action is HARDLINK; idempotent when already COMPLETE

@dataclass(frozen=True, slots=True)
class UploadPlanEntry:
    file: ManifestEntry
    action: UploadAction
    part_count: int                      # as IngestFile.part_count

def compute_upload_plan(
    manifest: Manifest, parent_manifest: Manifest | None = None, *, part_bytes: int = PART_BYTES
) -> tuple[UploadPlanEntry, ...]:
    """Plan every manifest file: HARDLINK when the parent holds the same path, size and digest under the same algorithm; UPLOAD otherwise."""

@dataclass(frozen=True, slots=True)
class IngestSession:
    """One session's durable state: its lease, its position in the machine, what it promised, who owns it."""
    lease: IngestLease
    state: IngestState
    manifest_sha256: str
    created_by: str                      # ingest_sessions.created_by; the only principal (besides an admin abort) who may drive it
    parent_revision_id: UUID | None      # the COMMITTED revision the plan was computed against; None for a first revision
    etag: int = 1                        # bumped by every state edge, never by renew

    def open(self, *, now: datetime) -> IngestSession:
        """PREPARING → UPLOADING once the staging envelope exists; lease must be live."""
    def renew(self, *, now: datetime, ttl: timedelta = LEASE_TTL) -> IngestSession:
        """Extend the lease to ``now + ttl`` in any non-terminal state; the etag is unchanged."""
    def require(self, state: IngestState, *, now: datetime) -> None:
        """Refuse unless the session is in ``state`` with a live lease; the guard every per-file step runs first."""
    def verify(self, files: Sequence[IngestFile], *, now: datetime) -> IngestSession:
        """UPLOADING → VERIFYING when every planned file is COMPLETE; the ledger is the authority, nothing is rehashed."""
    def begin_commit(self, *, manifest_sha256: str, now: datetime) -> IngestSession:
        """VERIFYING → COMMITTING under a live lease when the caller names the declared manifest; fences later drivers by etag."""
    def commit(self) -> IngestSession:
        """COMMITTING → COMMITTED after the rename is durable; storage leads, so the lease is not consulted."""
    def fail(self) -> IngestSession:
        """Any non-terminal state → FAILED when the service cannot finish; the lease is not consulted."""
    def abort(self) -> IngestSession:
        """PREPARING/UPLOADING/VERIFYING → ABORTED for the client, an admin force-abort or the expiry sweep; never from COMMITTING."""
    def expire(self, *, now: datetime) -> IngestSession:
        """``abort`` for the sweep: refuses (ValueError) unless ``now >= lease.expires_at``."""

def revision_record(
    session: IngestSession, manifest: Manifest, *,
    metadata_sha256: str, revision_path: str, committed_by: str, committed_at: datetime,
) -> RevisionRecord:
    """Build the row a COMMITTING session publishes; refuses (ValueError) a manifest whose identity is not the session's."""

def revision_committed(record: RevisionRecord, *, event_id: UUID, created_at: datetime) -> OutboxEvent:
    """The ``revision.committed`` outbox event: subject is the revision, payload is its identity and location."""
```

`pkg/catalog/models.py`:

```python
@dataclass(frozen=True, slots=True)
class RevisionRecord:
    id: UUID; dataset_id: UUID; number: int
    manifest_sha256: str
    metadata_sha256: str                 # new: content_identity(metadata.json), Design 5 supplies the document
    revision_path: str; committed_by: str; committed_at: datetime; file_count: int; total_bytes: int

@dataclass(frozen=True, slots=True)
class OutboxEvent:
    id: UUID                             # new: uuid7() at the raise site
    kind: str                            # invariant: matches outbox_events_kind_format (^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$, 2–63)
    subject_id: UUID
    payload: dict[str, object]           # invariant: a JSON object
    created_at: datetime                 # new: Clock.now() at the raise site
```

**Transition table, edge by edge.** The lease guard is `now >= lease.expires_at` (**proved**: the
boundary instant itself is refused, `ingest.py:161,191`). "Lease" says what the edge does to
`expires_at`; "etag" is always `+1` on a state edge and unchanged otherwise.

| From | Operation | Guard | To | Lease | Refusal |
|---|---|---|---|---|---|
| PREPARING | `open` | lease live | UPLOADING | unchanged | `IngestSessionExpired`, else `IllegalIngestTransition` |
| PREPARING, UPLOADING, VERIFYING | `abort` | none (lease ignored) | ABORTED | unchanged | `IllegalIngestTransition` from COMMITTING or a terminal |
| PREPARING, UPLOADING, VERIFYING | `expire` | `now >= expires_at` | ABORTED | unchanged | `ValueError` if live (caller bug); `IllegalIngestTransition` from COMMITTING/terminal |
| PREPARING, UPLOADING, VERIFYING, COMMITTING | `fail` | none (lease ignored) | FAILED | unchanged | `IllegalIngestTransition` from a terminal |
| UPLOADING | `require(UPLOADING)` then a file step | lease live, state equal | UPLOADING (no edge) | `renew` after each accepted part | `IngestSessionExpired`, `IllegalIngestTransition` |
| UPLOADING | `verify` | lease live; `files` non-empty and all COMPLETE | VERIFYING | unchanged | `IngestSessionExpired`; `ManifestMismatch(context={"incomplete": [paths]})`; `ValueError` on an empty ledger |
| VERIFYING | `begin_commit` | lease live; `manifest_sha256 == session.manifest_sha256` | COMMITTING | unchanged | `IngestSessionExpired`; `ManifestMismatch`; `IllegalIngestTransition` |
| COMMITTING | `commit` | none (lease ignored) | COMMITTED | unchanged | `IllegalIngestTransition` from any other state |
| COMMITTING | `abort` / `expire` | — | **refused** | — | `IllegalIngestTransition` |
| any non-terminal | `renew` | lease live | same | `now + ttl` | `IngestSessionExpired` (lapsed or terminal) |
| COMMITTED, ABORTED, FAILED | anything | — | refused | — | `IllegalIngestTransition` (never `IngestSessionExpired`: the error names the real reason, as today `ingest.py:139-142`) |

Decisions and why, against `layer-raw.html` §4:

- **`COMMITTING → ABORTED` stays refused, including for force-abort.** §4 (`:270-271`) puts the
  crashed client, the 2 h TTL and the admin force-abort in one sentence: they are one problem,
  client-side abandonment. COMMITTING is server-driven inside a single request; between step 6
  (rename) and step 7 (PG) the envelope is already published, and an abort would record a revision
  as never having happened. The coded rule (`ingest.py:33-35`) is right; force-abort is the same
  `abort` edge with a different guard (project admin, Design 4) and audit kind (Design 3).
- **`abort`, `fail` and `commit` ignore the lease.** Today `transition` refuses every edge of an
  expired session (**proved**: the whole expired-lease row is `INGEST_SESSION_EXPIRED`), so a
  client cannot abort its own expired session and nothing can release the dataset lock the DDL
  ties to a terminal flip (Observations). Backward edges release a lock; refusing them past
  expiry is the opposite of what expiry is for. `commit` ignores the lease because the durability
  point has passed (§5 "storage leads; the catalog follows"); a lease lapsing during a long
  `fsync_tree` must not strand a published envelope in COMMITTING.
- **Forward edges (`open`, `verify`, `begin_commit`) and every per-file step are lease-fenced.**
  A driver that lost its lease cannot advance a session that may have been reclaimed.
- **`renew` does not bump the etag.** Renewal is monotone and commutative; a client uploading files
  in parallel would otherwise race its own `If-Match`. Only state edges are compare-and-swapped.
- **Expiry lands in ABORTED, not FAILED.** ABORTED is "the client gave up", FAILED is "the service
  could not finish"; an abandoned session is the former. A fourth terminal would need a migration
  and both partial indexes rewritten for no information the audit event does not carry.
- **COMMITTING is never swept.** The sweep cannot tell "crashed before the rename" from "crashed
  after it" without consulting storage; that is the reconciler's job (§5 table, P3). See Open
  question 1 for the P2 consequence.

**Per-file model.** A file's states are `PENDING` and `COMPLETE`; there is no third. `PENDING`
means "the ledger does not vouch for these bytes" whether none, some or all parts have arrived, or
a mismatch was discarded. `completed_parts` is the set of 1-based part numbers whose bytes are
durably in the envelope; `received` is `completed_parts == set(range(1, part_count + 1))`.
`COMPLETE` for an UPLOAD file means every part arrived and the whole-file observation
(`observed_size`, `observed_sha256`) equalled the manifest entry; for a HARDLINK file it means the
parent's inode was linked in (`completed_parts` stays empty, `part_count` is 0, nothing is
rehashed — §4 `:268-269`). For a whole-file `O_EXCL` write (today's `write_part`) a file has
exactly one part: `part_received(1)` and `completed(...)` happen in the same request, and
`completed_parts` is `{}` or `{1}`. A zero-byte file is one zero-length part whose digest is
`sha256(b"")` (**proved** a zero-byte entry validates and plans). Resume is "re-send every part not
in `completed_parts` of every UPLOAD file that is not COMPLETE" — the P2 gate's "only incomplete
files" and milestone 8's "without re-sending completed parts" are the same rule at the two
granularities. Setting `PART_BYTES` to `DEFAULT_MAX_FILE_BYTES` makes every file one part with no
other change (Open question 2). A mismatch never becomes a state: `completed` raises, the caller
discards the bytes and persists `IngestFile(..., completed_parts=frozenset())` — the file is
`PENDING` again and a retry re-sends it.

**Milestone-8 route → domain operation.** Guards, persistence and mechanics are the other
designs'; this column is what the route calls on the domain and in what order.

| Route | Precondition | Domain operations (in order) | Edge | Lease | Error classes raised by the domain |
|---|---|---|---|---|---|
| `POST /ingest-sessions` | dataset writable (D4) | `validate_manifest` → `Manifest`; parent = latest COMMITTED revision (D3) and its `Manifest` (D2/D5); `compute_upload_plan(manifest, parent)`; `begin_ingest` → session PREPARING + one `IngestFile` per entry (D3); `create_staging` (D2); `session.open(now)` | PREPARING → UPLOADING | set at `begin_ingest` to `now + LEASE_TTL` | the nine path codes, `EmptyRevision`, `TooManyFiles`, `FileTooLarge`, `RevisionTooLarge`, `PathCollision` (manifest); `DatasetLocked`, `DuplicateContent` (D3) |
| `GET /ingest-sessions/{id}` | — | none; renders session + files | — | — | — |
| `POST …:heartbeat` | — | `session.renew(now)` | — | `now + LEASE_TTL` | `IngestSessionExpired` |
| `PUT /transfer/uploads/{file_id}/parts/{n}` | — | `session.require(UPLOADING, now)`; stream to store (D2) ; `file.part_received(n)`; if `part_count == 1`: `file.completed(observed…)`; `session.renew(now)` | none | renewed | `IngestSessionExpired`, `IllegalIngestTransition`, `ManifestMismatch` |
| `POST /transfer/uploads/{file_id}:complete` | `part_count > 1` | `session.require(UPLOADING, now)`; store assembles and reports the whole-file observation (D2); `file.completed(observed…)`; `session.renew(now)` | none | renewed | as above |
| `POST …:verify` | — | `session.require(UPLOADING, now)`; for each HARDLINK file: link from `parent_revision_id`'s payload (D2) then `file.linked()`; `session.verify(files, now)` | UPLOADING → VERIFYING | unchanged | `IngestSessionExpired`, `IllegalIngestTransition`, `ManifestMismatch` |
| `POST …:commit` | `If-Match` = etag, `Idempotency-Key` (D4) | `session.begin_commit(manifest_sha256, now)` (CAS on etag, D3); `committed_at = now`; documents, seal, rename (D2/D5); `revision_record(...)`; `revision_committed(...)`; `session.commit()`; one transaction (D3). On a failure before the rename: `session.fail()` | VERIFYING → COMMITTING → COMMITTED (or FAILED) | unchanged | `IngestSessionExpired`, `IllegalIngestTransition`, `ManifestMismatch`; `PreconditionFailed`, `IdempotencyKeyReused`, `DuplicateContent` (D3/D4) |
| `POST …:abort` (owner or project admin) | — | `session.abort()` | → ABORTED | unchanged | `IllegalIngestTransition` |
| expiry sweep (D6) | `expires_at <= now`, state ∉ {COMMITTING, terminal} | `session.expire(now)` | → ABORTED | unchanged | none client-facing |

**`RevisionRecord` ↔ `dataset_revisions`** (`0001_foundations.py:61-75`; `state` has a
`DEFAULT` and the record has no field for it — a record is only ever COMMITTED):

| Column | NOT NULL | Field | Source |
|---|---|---|---|
| `id` | yes | `id` | `session.lease.revision_id` |
| `dataset_id` | yes | `dataset_id` | `session.lease.dataset_id` |
| `revision_number` | yes | `number` | `session.lease.revision_number` |
| `manifest_sha256` | yes | `manifest_sha256` | `manifest.sha256`, asserted `== session.manifest_sha256` by `revision_record` |
| `metadata_sha256` | yes | `metadata_sha256` (new) | `content_identity(metadata.json document)` — Design 5 builds the document, its digest is passed in |
| `revision_path` | yes, UNIQUE | `revision_path` | `str(paths.revision_dir(...))` for the session's dataset, number and revision id — the rename target of step 6 |
| `file_count` | yes, `> 0` | `file_count` | `len(manifest.files)`; `EmptyRevision` guarantees the CHECK |
| `total_bytes` | yes, `>= 0` | `total_bytes` | `manifest.total_bytes` |
| `state` | default `'COMMITTED'` | — | DDL default; Design 3 does not bind it |
| `committed_by` | yes | `committed_by` | the principal driving `:commit` (`actor.subject` form, Design 4) |
| `committed_at` | yes | `committed_at` | one `Clock.now()` taken at `begin_commit`, reused verbatim in `metadata.json` and `COMMITTED` (Design 5) so the three agree |

**`OutboxEvent` ↔ `outbox_events`** (`0001:191-199`, `0008:293-296`):

| Column | NOT NULL | Field | Source |
|---|---|---|---|
| `id` | yes, PK | `id` (new) | `uuid7()` at the raise site (`revision_committed(event_id=uuid7())`) |
| `kind` | yes, format CHECK | `kind` | `"revision.committed"` — the one P2 kind |
| `subject_id` | yes | `subject_id` | `record.id` |
| `payload` | yes, object CHECK | `payload` | `{"revision_id", "dataset_id", "revision_number", "manifest_sha256", "revision_path"}` rendered by `jsonable` conventions (UUID → str) |
| `created_at` | yes | `created_at` (new) | the same `committed_at` instant |
| `processed_at` | no | — | NULL at insert; the consumer's column |

Audit rows (`audit_events`: `kind`, `actor`, `subject_kind`, `subject_id`, `payload`,
`created_at`) have no catalog shape today and get none here; the commit, abort, force-abort and
expiry audit kinds are Design 3's tier-owned records.

**Replacement `Metastore.begin_ingest` docstring** (for the recommended signature
`async def begin_ingest(self, dataset_id: UUID, manifest_sha256: str, *, created_by: str, parent_revision_id: UUID | None) -> IngestSession`;
if Design 3 relocates the port, the text moves with it unchanged):

```text
Open an ingest session in ``PREPARING`` and reserve the revision it will commit as.

The revision id and number are allocated here, before any byte is
uploaded, so the final storage path is known from the start. The number
is ``max(committed) + 1`` for the dataset, taken under the per-dataset
ingest lock: exactly one non-terminal session may exist per dataset, and
the number is held only while the session is open or committed. A session
that ends ``ABORTED`` or ``FAILED`` never redeemed its reservation, so its
number returns to the pool and the next session takes it again; the dead
row stays as the record of the attempt. This is what keeps a dataset's
numbering gap-free across retries. The manifest identity is recorded with
the session so the commit can be checked against what was declared.

Args:
    dataset_id: The dataset the revision is being added to.
    manifest_sha256: The content identity of the declared manifest.
    created_by: The principal opening the session; the only one, besides a
        project admin aborting it, allowed to drive it.
    parent_revision_id: The committed revision the upload plan was computed
        against, or None for a dataset's first revision.

Returns:
    The session in ``PREPARING`` with its lease: the reserved revision id
    and number, and when the lease lapses unless renewed.

Raises:
    DatasetLocked: If another session for the dataset is not yet terminal,
        whether or not its lease has lapsed.
    DuplicateContent: If the dataset already holds a committed revision with
        this manifest identity.
```

### Explicit contracts

**Invariants the domain enforces** (tested in § Tests):

- `TRANSITIONS` is the only source of edges; every operation that changes `state` consults it and
  bumps `etag` by exactly one; `renew` and every `IngestFile` operation leave `etag` unchanged.
- The lease guard is `now >= lease.expires_at`; `open`, `verify`, `begin_commit`, `require`,
  `renew` apply it; `abort`, `fail`, `commit` do not; `expire` requires its negation.
- A terminal session refuses every operation with `IllegalIngestTransition`, never with
  `IngestSessionExpired`.
- `IngestFile`: `part_count >= 1 ⇔ action is UPLOAD`; `completed_parts ⊆ {1..part_count}`;
  `state is COMPLETE` implies (`action is UPLOAD and received`) or (`action is HARDLINK`);
  `completed` is refused until `received`; a COMPLETE file refuses `part_received`.
- `compute_upload_plan` returns one entry per manifest file in manifest order; an entry is
  HARDLINK iff the parent has the same path with equal `sha256` and `size` and both manifests share
  `hash_algorithm`; a media-type change alone is a HARDLINK (**proved**); paths are compared as
  strings, which is sound because `validate_manifest_path` refuses any non-NFC path
  (**proved**: a lone NFD path → `PATH_NOT_NFC`) — a `Manifest` cannot carry two spellings.
- `revision_record` refuses a manifest whose `sha256` differs from the session's, and a session
  not in COMMITTING (`ValueError` both: caller bugs, not client errors).
- `OutboxEvent.kind` satisfies `outbox_events_kind_format`; `payload` is a JSON object.

**Error behaviour.** No new error code. `IllegalIngestTransition`'s docstring widens to "the
session, or one of its files, is not in a state that permits the operation" — it now covers
`require` and the per-file refusals; its `context` carries `{"state": …, "operation": …}`.
`ManifestMismatch` carries the per-file observation at `completed` and `{"incomplete": [paths]}`
at `verify`. `IngestSessionExpired` carries `{"expires_at": iso}`.

**Requirements on the other designs:**

- **Design 2 (raw store).** (a) Report the whole-file `(observed_size, observed_sha256)` for
  every UPLOAD file, at the single-part write or at `:complete`, so `completed` can run; nothing
  else in the domain hashes. (b) A part write for a part not in `completed_parts`, or any write to
  a file whose ledger state is PENDING, may find bytes from a crashed or mismatched attempt and
  must replace them (unlink then `O_EXCL`); the ledger, not the filesystem, is the authority for
  what has arrived. (c) Provide a discard for a mismatched file so the route can return it to
  PENDING. (d) Linking a HARDLINK file is idempotent (an existing link to the same inode is
  success), because `:verify` may be retried after a partial run. (e) The parent `Manifest` handed
  to `compute_upload_plan` is read from `parent_revision_id`'s `manifest.json` and rebuilt through
  `validate_manifest` (with Design 5), so its paths are NFC and its digests lower-case.
- **Design 3 (persistence).** (a) Persist `created_by` and `parent_revision_id` on
  `ingest_sessions` (the latter a nullable `uuid REFERENCES dataset_revisions(id)`); persist
  `IngestFile` one-to-one on `ingest_files` with `state` CHECK `IN ('PENDING','COMPLETE')`,
  `part_count integer NOT NULL CHECK ((action = 'hardlink' AND part_count = 0) OR (action = 'upload' AND part_count >= 1))`,
  and `completed_parts` as the sorted JSON array of the set. No observed-digest column: the
  observation is compared and discarded. (b) State edges are `UPDATE … WHERE id = $1 AND etag = $2`
  and raise `PreconditionFailed` on zero rows; `renew` is
  `SET expires_at = GREATEST(expires_at, $3) WHERE id = $1 AND state NOT IN (terminals)` with no
  etag predicate; the sweep's flip additionally fences on `expires_at <= $now` because `renew`
  does not move the etag. (c) Per-file updates fence on `(file_id, state = 'PENDING')`, never on
  the session etag, so parallel part uploads do not serialise. (d) `begin_ingest` resolves the
  parent as the dataset's highest-numbered revision in state `COMMITTED` under the lock, so the
  hardlink source's payload is on disk. (e) The commit transaction consumes `RevisionRecord` and
  `OutboxEvent` as given and inserts nothing the record does not carry except `state`'s default.
  (f) The expired-session rule must let a client `abort` and the sweep `expire` a lapsed session
  in PREPARING/UPLOADING/VERIFYING; a lapsed COMMITTING session is left alone.
- **Design 4 (HTTP).** (a) Every route in the table above calls the operations in that order
  and invents no state beyond `IngestSession`, `IngestFile` and the plan; `ETag` is `etag`;
  `If-Match` is required on `:commit` only. (b) `:commit` takes `manifest_sha256` in its body
  (layer-raw `:278`) and the descriptive metadata document (Open question 3). (c) Force-abort is
  `abort` under a project-admin guard; the domain does not know who is aborting. (d) The upload
  plan view carries `part_count` and echoes `PART_BYTES`; `GET` carries each file's `state` and
  `completed_parts`.
- **Design 5 (documents).** Supply `metadata_sha256` as `content_identity` of the canonical
  `metadata.json`; write `committed_at` and `committed_by` into `metadata.json` and `COMMITTED`
  from the same values `revision_record` receives.
- **Design 6 (sweep).** Select `state IN ('PREPARING','UPLOADING','VERIFYING') AND expires_at <= now`,
  call `expire`, persist with Design 3's fence; never select COMMITTING.

### Deletions

- `pkg/catalog/ingest.py`: `IngestSession.transition` (public, guard-bypassing; replaced by the
  named operations), `IngestSession.heartbeat` (replaced by `renew` with different etag
  semantics), the `now: datetime | None = None` fallbacks to `datetime.now(UTC)` (the domain no
  longer reads a clock), `UploadPlanEntry.parent_path` (always `file.path` or `None`, **proved**;
  the link source is the same relative path), the `_TRANSITIONS` name (becomes `TRANSITIONS`).
- `tests/unit/test_catalog_ingest.py`: all three tests (their rules survive under the names in
  § Tests, against the new operations).
- `migrations/schema.sql:160-162`: the `[spec] vocabulary undecided` comment on
  `ingest_files.state` — decided above; Design 3 replaces it with the CHECK line.
- Nothing in `errors.py`, `models.py` or `ports.py` is removed.

### Data flow

```mermaid
stateDiagram-v2
    [*] --> PREPARING: begin_ingest (D3)
    PREPARING --> UPLOADING: open — lease live
    UPLOADING --> UPLOADING: require(UPLOADING) · part_received · completed · linked · renew
    UPLOADING --> VERIFYING: verify — lease live, every file COMPLETE
    VERIFYING --> COMMITTING: begin_commit — lease live, digest equal
    COMMITTING --> COMMITTED: commit — lease ignored (storage leads)
    PREPARING --> ABORTED: abort / expire — lease ignored
    UPLOADING --> ABORTED: abort / expire — lease ignored
    VERIFYING --> ABORTED: abort / expire — lease ignored
    PREPARING --> FAILED: fail
    UPLOADING --> FAILED: fail
    VERIFYING --> FAILED: fail
    COMMITTING --> FAILED: fail — driver saw the failure before the rename
    COMMITTED --> [*]
    ABORTED --> [*]
    FAILED --> [*]
    note right of COMMITTING
        No abort, no expire, no sweep.
        A crashed driver here is the
        reconciler's (P3) — see Open question 1.
    end note
    note left of UPLOADING
        renew (heartbeat or any accepted part)
        moves expires_at only; etag is
        bumped by state edges alone.
    end note
```

### Rejected alternatives

- **Keep a public `transition(target)` and let routes pick targets** — two paths to the same edge
  with different lease rules (the bug this design removes); the named operations are the table.
- **A `MISMATCHED` file state** — it would record garbage on disk as a ledger fact; discarding
  the bytes and returning to PENDING keeps two states and one authority.
- **A fourth terminal `EXPIRED`** — a migration, two partial-index rewrites and a new error row
  for information the `ingest.expired` audit event already carries.

### Open questions

1. **A session whose driver crashed in COMMITTING holds the dataset lock until P3's reconciler
   exists.** *Recommended:* accept for P2 and record it in the roadmap write-back; the window is
   one request, the client's `:commit` retry with the same `Idempotency-Key` recovers the
   post-rename case (step 6 retry is silent, step 7 then runs) only if the retry is allowed to
   re-enter COMMITTING — so also allow Design 3/4 a **`COMMITTING → COMMITTING` re-entry when the
   caller presents the current etag** (the stale driver is fenced by the bump). If the owner
   wants no P2 gap at all, the alternative is a sweep that consults storage (`final/COMMITTED`
   present → complete step 7; absent → `fail`), which is reconciler work pulled forward.
2. **Multipart in P2, or whole-file only?** The domain supports both through `PART_BYTES`.
   *Recommended:* multipart at 64 MiB, because milestone 8's gate is literally "without
   re-sending completed parts" and a 9 GiB restart-from-zero fails the spirit of it; Design 2
   owns the part assembly. If deferred, set `PART_BYTES = DEFAULT_MAX_FILE_BYTES` and nothing else
   here changes.
3. **Where the metadata document is submitted.** `api.html:127` puts a "metadata draft" in the
   create body; the DDL has no column and the session no field. *Recommended:* the document is
   submitted with `:commit`, when `committed_by`/`committed_at` are known and it is final — no
   draft column, no draft-mutation route, and the create body's draft becomes optional and
   ignored (write-back to §3). The alternative is a `metadata_draft jsonb` column on
   `ingest_sessions` owned by Design 3.
4. **Absolute TTL.** `api.html:240` says `INGEST_SESSION_EXPIRED` covers "idle or absolute TTL";
   layer-raw §4 has only the renewable 2 h. *Recommended:* no absolute cap — a heartbeating
   client is alive by definition and force-abort covers the pathological case; drop "or
   absolute" from the §7 row at write-back rather than add a second expiry to the lease.

### Tests

`tests/unit/test_catalog_ingest.py` (rewritten; `pytest.mark.unit`, a `_session(state, *, expires_in)` helper):

| Test | Asserts |
|---|---|
| `test_every_operation_from_every_state_matches_the_transition_table` | parametrized over 7 states × {`open`, `verify`, `begin_commit`, `commit`, `abort`, `fail`}: success iff the target is in `TRANSITIONS[state]`, etag `+1` on success, `IllegalIngestTransition` otherwise |
| `test_a_committing_session_refuses_abort_and_expire` | `abort()` and `expire(now)` from COMMITTING raise `IllegalIngestTransition` |
| `test_abort_and_fail_ignore_a_lapsed_lease` | lapsed UPLOADING → `abort()` and `fail()` succeed |
| `test_commit_ignores_a_lapsed_lease` | lapsed COMMITTING → `commit()` is COMMITTED |
| `test_forward_edges_refuse_a_lapsed_lease` | lapsed PREPARING/UPLOADING/VERIFYING → `open`/`verify`/`begin_commit` raise `IngestSessionExpired` |
| `test_terminal_sessions_refuse_with_the_transition_error_even_when_lapsed` | lapsed COMMITTED → every op raises `IllegalIngestTransition` |
| `test_renew_moves_the_expiry_and_leaves_the_etag` | `expires_at == now + LEASE_TTL`, etag unchanged, state unchanged |
| `test_renew_refuses_at_the_expiry_instant_and_after_and_when_terminal` | `now == expires_at` refused; terminal refused |
| `test_require_refuses_another_state_and_a_lapsed_lease` | VERIFYING + `require(UPLOADING)` → `IllegalIngestTransition`; lapsed → `IngestSessionExpired` |
| `test_expire_aborts_a_lapsed_session_and_refuses_a_live_one` | lapsed → ABORTED; live → `ValueError` |
| `test_verify_refuses_while_any_file_is_pending` | `ManifestMismatch.context["incomplete"]` lists exactly the pending paths |
| `test_verify_refuses_an_empty_ledger` | `ValueError` |
| `test_begin_commit_refuses_a_different_manifest_digest` | `ManifestMismatch`, state unchanged |
| `test_part_received_records_the_part_and_is_idempotent` | `{1}` then `{1}` again; `received` true at the last part |
| `test_part_received_refuses_a_part_outside_the_plan_a_hardlink_file_and_a_complete_file` | `ValueError` for 0 and `part_count + 1`; `IllegalIngestTransition` for the other two |
| `test_completed_refuses_before_every_part_has_arrived` | `IllegalIngestTransition` |
| `test_completed_marks_a_matching_observation_complete` | state COMPLETE, parts kept |
| `test_completed_refuses_a_size_or_digest_mismatch_with_the_observation_in_context` | both fields in `context`; file unchanged |
| `test_linked_completes_a_hardlink_file_and_refuses_an_upload_file` | COMPLETE with empty parts; `IllegalIngestTransition` for UPLOAD |
| `test_a_zero_byte_file_is_one_part_that_completes_on_the_empty_digest` | `part_count == 1`; `completed(0, sha256(b""))` |
| `test_upload_plan_links_only_entries_the_parent_holds_identically` | same → HARDLINK; size change → UPLOAD; media-type change → HARDLINK; new → UPLOAD; zero-byte unchanged → HARDLINK |
| `test_upload_plan_uploads_everything_without_a_parent_or_under_another_hash_algorithm` | all UPLOAD in both cases |
| `test_upload_plan_part_counts_follow_the_part_size` | 9 GiB at 64 MiB → 144; 64 MiB → 1; 64 MiB + 1 → 2; 0 → 1; HARDLINK → 0 |
| `test_revision_record_takes_every_column_from_the_session_and_manifest` | all nine fields equal their named sources |
| `test_revision_record_refuses_a_foreign_manifest_or_a_session_not_committing` | `ValueError` |
| `test_revision_committed_event_carries_the_revision_identity` | kind, subject, five payload keys, id and created_at as passed |

`tests/unit/test_catalog_properties.py` (appended, `hypothesis`, `_property` settings):

| Test | Asserts |
|---|---|
| `test_ingest_operations_never_leave_the_transition_table` | random operation sequences from PREPARING: every successful state change is an edge of `TRANSITIONS`, etag increases by one per state change and never otherwise, no operation succeeds from a terminal state |
| `test_ingest_file_parts_are_a_subset_of_the_plan_and_complete_only_when_full` | random part orders and duplicates: `completed_parts ⊆ 1..part_count`; `received` iff full; `completed` refused before |
| `test_upload_plan_is_one_entry_per_file_in_manifest_order_and_links_only_identical_entries` | generated manifest/parent pairs with random overlap |
| `test_upload_plan_part_counts_cover_every_byte_exactly_once` | `(part_count - 1) * part_bytes < max(size, 1) <= part_count * part_bytes` |
| `test_validate_manifest_refuses_every_non_nfc_path` | generated paths with an NFD-decomposable character → `PATH_NOT_NFC` |

### Receipts

`uv run python` against `c5e35c7` (script in the session scratchpad):

- Transition matrix, live lease — rows PREPARING/UPLOADING/VERIFYING allow exactly {next, ABORTED,
  FAILED}; COMMITTING allows {COMMITTED, FAILED}; the three terminals allow nothing
  (`ILLEGAL_INGEST_TRANSITION` throughout). Expired lease — every non-terminal row is
  `INGEST_SESSION_EXPIRED` for every target, terminals unchanged.
- `heartbeat(now=expires_at)` → `INGEST_SESSION_EXPIRED` (boundary is refused).
  `transition` then `heartbeat` → etag 1 → 3, expiry `now + 2:00:00`.
- `compute_upload_plan` against a parent: unchanged → `hardlink parent_path=<same path>`; size
  10 → 11 with the same digest → `upload`; media type changed only → `hardlink`; new path →
  `upload`; zero-byte unchanged → `hardlink`; no parent → `{UPLOAD}` only.
- `validate_manifest([NFC, NFD])` → `PATH_NOT_NFC` with `context={"path": …}` (the NFD entry is
  refused before the collision check); a lone NFD path → `PATH_NOT_NFC`.
- `validate_manifest([ManifestEntry("payload/z", 0, sha)])` → 1 file, `total_bytes 0`.
- Not run: anything against PostgreSQL (Design 3's proof); `hardlink_from_parent` idempotency
  under a repeated `os.link` (Design 2's).

## Design 2 — The RawStore port and PosixRawStore's streaming, document and commit contract

Designed against `main` at `c5e35c7`, inside `pkg/rawstore`'s import contract (no sibling
package, no framework) and `pkg/catalog`'s (the port never imports `rawstore`). Design 1's
requirements (a)–(e) on this task are taken as binding. Claims marked **proved** were run against
a scratch root on this machine (macOS, APFS, euid 501); see § Receipts. One of them overturns the
documented commit order: **a directory whose mode is `0o555` cannot be renamed into another parent
by a non-root user** (`EACCES`, **proved** here; Linux `rename(2)` documents the same — write
permission on the moved directory is needed to update its `..` entry). `layer-raw.html:285-287`
seals "dirs 0555" at step 5 and renames at step 6; executed literally against the envelope root,
step 6 fails. The design below seals the envelope's *contents* before the rename and its root
after.

### Target design

**Module layout.** No new modules. `pkg/catalog/ports.py` (`RawStore` rewritten),
`pkg/rawstore/store.py` (signatures below), `pkg/rawstore/commit.py` (`commit_envelope` gains the
root seal), `pkg/rawstore/__init__.py` (exports `PartLengthMismatch`),
`service/api/repository.py:99-101` (typed against the port).

**The port** — `pkg/catalog/ports.py`. It declares everything the service tier asks of the raw
filesystem, P1's control-plane documents included, so one type serves both consumers; the
docstring's rule "the catalog hands it paths from `paths` and never composes its own" becomes true
for every method (`create_staging` takes the path from `paths.staging_dir` instead of composing
`root/.staging/{hex}` a second time). `root` is a read-only property returning `pathlib.Path`
(**proved**: `mypy --strict` and `ty` both accept `PosixRawStore.root: Path` against it, and
`app.py:374`'s `root.exists()` keeps type-checking).

```python
class RawStore(Protocol):
    """Everything the service asks of the raw filesystem: one root, private envelopes, durable
    parts and links, documents, publication by rename, sealing, write-once tags."""

    @property
    def root(self) -> Path:
        """The data root ``.staging/`` and ``organization/`` sit under; every other path is derived from it by :mod:`paths`."""

    def initialize(self) -> None:
        """Create ``.staging/`` and ``organization/`` if missing and prove they share a filesystem (``CrossDeviceCommitError`` otherwise)."""

    def create_staging(self, staging: PurePosixPath) -> None:
        """Claim ``staging`` (from :func:`paths.staging_dir`) as a fresh private envelope with an empty ``payload/``; a second claim fails."""

    def write_part(
        self, staging_payload: PurePosixPath, rel_path: str, chunks: Iterable[bytes], *, offset: int, length: int
    ) -> str:
        """Stream exactly ``length`` bytes into ``[offset, offset + length)`` of a payload file, hashing in flight; return the range's SHA-256 once it and the names leading to it are durable."""

    def finish_file(self, staging_payload: PurePosixPath, rel_path: str) -> tuple[int, str]:
        """Report a payload file as it is on disk: its size and the SHA-256 of one sequential read."""

    def discard_file(self, staging_payload: PurePosixPath, rel_path: str) -> None:
        """Remove a payload file the ledger no longer vouches for; a missing file is success."""

    def hardlink_from_parent(
        self, parent_payload: PurePosixPath, staging_payload: PurePosixPath, rel_path: str
    ) -> None:
        """Make ``rel_path`` in the envelope the parent's inode (or a byte-identical copy); success when it already is, replacing anything else there."""

    def read_document(self, path: PurePosixPath) -> bytes:
        """Return a stored document's bytes; ``FileNotFoundError`` when storage does not hold it."""

    def write_document(self, staging: PurePosixPath, name: str, payload: bytes) -> None:
        """Durably place ``payload`` at ``staging/name`` (one path component, read-only), replacing an earlier attempt's bytes."""

    def atomic_replace(self, path: PurePosixPath, payload: bytes) -> None:
        """Replace ``path``'s content in one step, durable on return; for pointers and derived aids that move."""

    def seal(self, revision_dir: PurePosixPath) -> None:
        """Make everything below ``revision_dir`` read-only (files ``0o444``, directories ``0o555``); the root itself is untouched so it can still be renamed."""

    def commit_envelope(self, staging: PurePosixPath, final: PurePosixPath) -> None:
        """Publish a ``COMMITTED`` envelope at ``final`` by one rename after fsyncing it, then seal ``final`` itself; a completed commit may be retried silently."""

    def write_tag_once(self, tag_file: PurePosixPath, payload: bytes) -> None:
        """Unchanged (P1)."""

    def write_generation(self, entity_dir: PurePosixPath, generation: int, payload: bytes) -> Path:
        """Unchanged (P1)."""
```

**`PosixRawStore` — changed and added methods** (`pkg/rawstore/store.py`; unchanged:
`__init__`, `initialize`, `write_tag_once`, `write_generation`, `atomic_replace`):

```python
class PartLengthMismatch(ValueError):
    """The stream delivered a different number of bytes than the part was planned to hold."""

class PosixRawStore:
    def create_staging(self, staging: PurePosixPath) -> None:
        # ValueError unless staging.parent == root/.staging; mkdir(0o700) without exist_ok (FileExistsError
        # is the second claim); payload/ 0o700; fsync_dir(.staging), fsync_dir(staging), fsync_dir(payload)

    def write_part(
        self, staging_payload: PurePosixPath, rel_path: str, chunks: Iterable[bytes], *, offset: int, length: int
    ) -> str:
        # target = staging_payload / _safe_relative(rel_path); _make_private_dirs(staging_payload, target.parent)
        # fd = os.open(target, O_WRONLY | O_CREAT, 0o600)          -- no O_EXCL, no O_TRUNC
        # for chunk in chunks: refuse if written + len > length (PartLengthMismatch); _pwrite_all(fd, chunk, offset + written); digest.update(chunk)
        # refuse if written != length (PartLengthMismatch); os.fsync(fd); close; fsync every directory from target.parent up to staging_payload
        # return digest.hexdigest()

    def finish_file(self, staging_payload: PurePosixPath, rel_path: str) -> tuple[int, str]:
        # open O_RDONLY (FileNotFoundError propagates); read in 1 MiB blocks into sha256; return (fstat.st_size, hexdigest)

    def discard_file(self, staging_payload: PurePosixPath, rel_path: str) -> None:
        # target.unlink(missing_ok=True); fsync_dir(target.parent) when it exists

    def hardlink_from_parent(self, parent_payload, staging_payload, rel_path) -> None:
        # _make_private_dirs; if target exists: return when os.path.samefile(source, target) else target.unlink()
        # os.link, or _copy_exclusive when hardlink_fallback_copy; fsync_dir(target.parent)

    def read_document(self, path: PurePosixPath) -> bytes:
        # Path(path).read_bytes()

    def write_document(self, staging: PurePosixPath, name: str, payload: bytes) -> None:
        # ValueError unless name is one component, not "", ".", "..", "payload"; self.atomic_replace(staging / name, payload, mode=0o444)

    def seal(self, revision_dir: PurePosixPath) -> None:
        # as today minus the final root.chmod(0o555)

def _make_private_dirs(base: Path, directory: Path) -> None:
    # mkdir each missing component below base with mode 0o700 (today's mkdir(parents=True) yields 0o755 under umask 022, proved)

def _pwrite_all(descriptor: int, payload: bytes, offset: int) -> None:
    # os.pwrite loop across short writes, the positional twin of _write_all
```

`commit.commit_envelope` (module function) gains one step after `fsync_dir(final.parent)`:
`os.chmod(final, 0o555)` then `fsync_dir(final)`; its retry branch (staging gone, `final/COMMITTED`
present) applies the same two calls before returning, so a crash between the parent fsync and the
root seal is repaired by the retry. Everything else in `commit.py` is unchanged.

**Typed consumers.** `HierarchyRepository.__init__(self, raw_store: RawStore, …)`
(`repository.py:101`) and the ingest facade Design 4 introduces; `app.py:224` keeps constructing
`PosixRawStore(settings.data_root)`. `RawStore` therefore has two consumers and `PosixRawStore`
exactly one implementation of each port method; `PosixRawStore.write_once` and `staging_root`
leave the public surface (§ Deletions).

**`write_part` input contract.**

- *Type.* `Iterable[bytes]`, consumed once, in order, on the worker thread `asyncify` runs the
  call on. A list still works; a generator is what P2 passes (**proved** the loop only iterates).
- *Chunk ownership.* A chunk is fully written (`_pwrite_all`) and folded into the digest before the
  next is requested; the store keeps no reference to it, so the producer may recycle its buffer
  once `__next__` is called again. Chunk size is the producer's; the store's memory bound is one
  chunk.
- *Back-pressure.* Pull-based: the store never reads ahead, so a slow disk stalls the producer's
  `__next__` and a slow client stalls the store's write loop. Nothing is queued in the store.
- *Length.* The range is fixed by the plan: `offset = (part - 1) * PART_BYTES`, `length = PART_BYTES`
  for every part but the last and `size - offset` for the last (so `offset = 0, length = size` is
  the single-part and the whole-file case — both of Design 1's Open question 2 options are one
  call). A stream that ends short or runs long raises `PartLengthMismatch` before any success is
  reported; whatever landed in the range stays and is overwritten by the re-send.
- *Mid-stream failure.* An exception from the iterator (client disconnect) propagates unchanged
  after the descriptor is closed. On disk: the file exists at mode `0o600` with a partially written
  range (**proved**: 6 bytes left of a stream that raised after two chunks). Nothing is unlinked —
  under multipart, other parts of the same file may be complete. The ledger (Design 1) does not
  record the part, so the client re-sends it and `write_part` overwrites the same range
  (**proved** with `os.pwrite`: out-of-order parts assemble correctly and a re-sent part replaces
  only its own bytes). This is Design 1's requirement (b) — "replace stale bytes" — realised as a
  range overwrite rather than unlink-then-`O_EXCL`, which cannot coexist with out-of-order parts
  into one file. Today's `O_EXCL` refusal of the reopen (**proved**: `FileExistsError` on retry)
  is exactly the behaviour that made resume impossible, and it goes.
- *Per-part durability.* Before returning, `write_part` fsyncs the file and every directory from
  the file's parent up to `staging_payload` inclusive, so a part the ledger records survives a
  crash together with the names that reach it (≤ 9 directory fsyncs per 64 MiB part at the 8-level
  nesting limit). Today's `write_part` fsyncs the file only and relies on `fsync_tree` at commit;
  that is not enough for a ledger that says "durably in the envelope" mid-session.
- *Single-part observation.* For `part_count == 1` the returned digest with `length` is the
  whole-file `(observed_size, observed_sha256)` Design 1 requires at the single-part write, because
  within one envelope every write to a path derives its range from the same plan, so a payload
  file never holds bytes beyond its manifest size. Multipart files get their observation from
  `finish_file` at `:complete` (one sequential read; 9 GiB is read once and written once).

**The commit sequence** — the six on-disk steps between `begin_commit` and the PostgreSQL
transaction, with the state a crash after each leaves, named against `layer-raw.html` §5's table:

1. `write_document(staging, "manifest.json", …)`, then `write_document(staging, "metadata.json", …)`
   — each a temp-file write, fsync, rename over any earlier attempt's file, fsync of the envelope
   root. *Crash:* row "4–5" — a complete-looking envelope under `.staging/`, invisible to readers;
   the session expires and the sweeper (P3) deletes it, or a COMMITTING re-entry rewrites the
   documents (replace semantics are what make the retry possible).
2. `seal(staging)` — payload files and the two documents `0o444`, every directory below the root
   `0o555`; the root stays `0o700`. *Crash:* row "4–5". The root staying writable is what lets the
   retry of step 1 succeed (**proved**: `atomic_replace` inside a `0o555` root → `PermissionError`).
3. `write_document(staging, "COMMITTED", …)` — the marker means "documents and seal are complete";
   it is written last for that reason. *Crash:* row "4–5" ("complete-looking envelope").
4. `commit_envelope` part one: `fsync_tree(staging)` — files, then directories deepest-first, then
   the root (**proved** it opens a sealed tree). *Crash:* row "4–5"; no rename has been attempted
   (**proved**: `os.fsync` raising → zero renames).
5. `commit_envelope` part two: `os.rename(staging, final)`. *Crash* before the parent fsync: the
   rename is in the page cache — after recovery either row "4–5" or row "6", both named states;
   `EXDEV` here becomes `CrossDeviceCommitError` (**proved**). *Crash* in the rename itself: row
   "4–5", staging intact, `final` absent (**proved**: `EIO` after 7 fsyncs).
6. `commit_envelope` part three: `fsync_dir(final.parent)`, then `os.chmod(final, 0o555)` and
   `fsync_dir(final)`. *Crash* after the parent fsync: row "6" — orphan commit, published, no row;
   the root may still be `0o700`. *Crash* after the chmod: row "6" with a sealed root.

*Retry.* A second `commit_envelope(staging, final)` finds `staging` gone and `final/COMMITTED`
present, reseals the root and returns silently (**proved** the silence; the reseal is the addition),
after which step 7 (Design 3's transaction) runs — row "7", complete. Any other pre-existing `final`
is `FileExistsError`; a missing staging is `FileNotFoundError`; a staging without `COMMITTED` is
`ValueError`; a cross-device pair is `CrossDeviceCommitError` before any fsync. Step 7 never runs
before step 6 returns: storage leads.

**Hardlink-then-seal.** Links are made at `:verify` (Design 1's route table), before any seal.
`os.link` needs write and search permission on the *staging* directory only: a `0o444` file in a
`0o555` parent revision links into a `0o700` envelope without touching the parent (**proved**:
`nlink` 2, `samefile`). `seal` then chmods the shared inode to `0o444` — a no-op for a linked file,
the real seal for a copied fallback (`0o600` → `0o444`) — and a write through the link is
`PermissionError` (**proved**). Idempotency: `os.link` onto an existing name is `EEXIST` whether
or not it is the same inode (**proved**, both cases), so `hardlink_from_parent` checks `samefile`
first: same inode → success; anything else → unlink and link again (the ledger has not recorded
`linked()`, so what is there is a crashed attempt's). Design 1 (d) is met.

**Parent-manifest read-back.** `read_document(PurePosixPath(parent.revision_path) / "manifest.json")`
returns the bytes; Design 5 decodes them and rebuilds the `Manifest` through `validate_manifest`
(Design 1 (e)), and `compute_upload_plan` runs on that. `parent.revision_path` comes from
`dataset_revisions` via Design 3's parent resolution. A `FileNotFoundError` here means storage and
catalog disagree about a committed revision; it propagates — Design 4 renders it as a server error
and the reconciler (P3) owns the repair.

**`CrossDeviceCommitError` surfacing.** Both sites stay. `initialize` (run from
`HierarchyRepository.__init__`, `repository.py:124`, so a bad layout fails app construction)
compares `st_dev` of `.staging` and `organization` (**proved** against two real device boundaries,
`/dev` and `/System/Volumes/VM`). `commit_envelope` compares `staging` with `final.parent` and
translates a rename `EXDEV`; that catches what startup cannot — a dataset directory that is its own
mount point under `organization/`.

**Sync or async.** The store stays synchronous and every service-tier call is
`await asyncify(store.method)(...)`, the rule `API_DESIGN.md` § "Design 1" set and
`test_execution_model.py` pins (no `cancellable=` anywhere; an abandoned write must run to its
fsync). An async surface would put each `os.write`/`os.fsync` either on the loop or on its own
thread hop; one hop per part is the right granularity. The request stream reaches the worker
thread through Design 4's bridge (`asyncer.syncify`, present in the pinned 0.0.18 and documented
for exactly "inside some function passed to `asyncify()`"), never through the store.

**Drift 9 write-back.** The code, `paths.staging_dir` (`paths.py:390`) and layer-raw's own tree
(`:131`) agree; the two prose lines are wrong. `design/layer-raw.html:129`
`{ingest_id}/` → `{ingest_id hex}/                            one per open ingest session (32 lowercase hex digits, no hyphens — the path form of §2)`;
`:406` "never descends into `orgs/`" → "never descends into `organization/`". Also written back
from this design: `:285` "5. Seal: chmod payload files 0444, dirs 0555." → "5. Seal the envelope's
contents: files 0444, directories below the envelope root 0555. The root keeps its write bit —
`rename(2)` must update its `..` entry."; `:286-287` gains "then chmod the published root 0555 and
fsync it". Drift 5 (§7 `O_EXCL` vs replace) needs no code change here and stays with the plan's
write-back.

### Explicit contracts

| Method | Invariant | Error behaviour | Durability on return |
|---|---|---|---|
| `root` | `.staging/` and `organization/` are direct children; nothing links or renames across roots | — | — |
| `initialize` | idempotent; both roots exist on one device | `CrossDeviceCommitError(EXDEV)` | directories exist (not fsynced; a crash before the first ingest recreates them) |
| `create_staging` | `staging.parent == root/.staging`; envelope and `payload/` are `0o700`; one claim per name | `ValueError` (wrong parent), `FileExistsError` (second claim) | `.staging`, envelope and `payload/` entries fsynced |
| `write_part` | writes only `[offset, offset+length)`; hashes exactly the bytes written; created directories are `0o700`; never truncates | `ValueError` (unsafe path, before any open), `PartLengthMismatch` (short/long), the iterator's own exception; `OSError` unchanged | file data and every directory entry from the file up to `staging_payload` fsynced; on any raise nothing is promised |
| `finish_file` | reads what is on disk, nothing cached | `FileNotFoundError`, `ValueError` (path) | — (read) |
| `discard_file` | after it returns the path does not exist | `ValueError` (path) | removal fsynced |
| `hardlink_from_parent` | target is the parent's inode, or a byte-identical `0o600` copy when linking fails and `hardlink_fallback_copy`; parent never modified; same inode already there → no-op | `ValueError` (path), `FileNotFoundError` (source), `OSError` from `os.link` when the fallback is off | new entry fsynced |
| `read_document` | returns bytes as stored | `FileNotFoundError` | — |
| `write_document` | `name` is one component; file is `0o444`; old bytes or new, never a mix | `ValueError` (name), `PermissionError` if the root is sealed (never, by the sequence) | file and envelope-root entry fsynced |
| `atomic_replace` | as today | as today | as today |
| `seal` | every file below the root `0o444`, every directory below it `0o555`, root untouched; idempotent | `FileNotFoundError` | mode bits not fsynced (re-applied by the commit's `fsync_tree`) |
| `commit_envelope` | after return `final` holds everything `staging` held, `staging` is gone, `final` is `0o555`; on raise `final` absent and `staging` untouched; retry silent | the four refusals, in that order; `OSError` from the rename unchanged | whole tree, `final.parent` entry, `final` inode |
| `write_tag_once`, `write_generation` | unchanged | unchanged | unchanged |

**Lifecycle assumptions.** One driver per envelope at a time, fenced by Design 3's etag on state
edges and by `(file_id, state = 'PENDING')` on parts; parallel `write_part` calls for *different*
parts of one file are safe (disjoint ranges, page-aligned at 64 MiB; NFS close-to-open suffices
because nobody reads until `finish_file` opens the file after every writer closed). The store is
never a lock. Nothing is read from `.staging/` by any reader. The envelope root is `0o700` until
publication, so the `0o700` intermediate directories are defence in depth, not the boundary.

**Requirements on the other designs.**

- **Design 3 (persistence).** Provide the parent's `revision_path` alongside `parent_revision_id`
  at create, and the target `revision_path` (`paths.revision_dir`) at commit; nothing else about
  disk is persisted. The COMMITTING re-entry Design 1's Open question 1 recommends is safe against
  these mechanics: every step before the rename is replace-idempotent and the rename's retry is
  silent. See Open question 1 for what the retry needs after the rename.
- **Design 4 (HTTP).** (a) Hand `write_part` an `Iterable[bytes]` whose `__next__` blocks on the
  worker thread until a chunk is available, yields non-empty chunks until the body is exhausted,
  and raises on client disconnect (never ends silently early); the recommended bridge is a
  generator calling `syncify(receive)()` per chunk inside the `asyncify`'d call. (b) Derive
  `offset`/`length` from the plan as stated above; refuse a `Content-Length` that disagrees with
  `length` before opening the stream. (c) Call `finish_file` at `:complete` for `part_count > 1`,
  use `write_part`'s return for `part_count == 1`, and `discard_file` on `ManifestMismatch`.
  (d) Map `PartLengthMismatch` and a disconnect to error rows of its choosing; the store raises
  no `DomainError`. (e) The upload route is `async def` (it awaits the store) and its `write_part`
  call must appear in `test_execution_model.py`'s off-loop tripwire. Per-request memory is one
  chunk.
- **Design 5 (documents).** Call `write_document(staging, name, payload)` with `name` in
  `{"manifest.json", "metadata.json", "COMMITTED"}` in the sequence's order; `atomic_replace(index_path, payload)`
  for `INDEX.json` if P2 writes it; `read_document` for the parent manifest. Byte payloads only.
  If Open question 1 resolves to read-back, `COMMITTED` must carry `committed_by`, `committed_at`,
  `manifest_sha256`, `metadata_sha256`, `file_count`, `total_bytes`.
- **Design 6 (sweep).** No store call in P2; staging deletion is P3's.
- **Design 7 (tests).** Arrange the tests in § Tests; the crash helper lives in
  `tests/unit/support.py` beside `memory_stores`.

### Deletions

- `pkg/rawstore/store.py`: `PosixRawStore.staging_root` (no caller outside the class; the path
  comes from `paths.staging_dir`); `write_once` leaves the public surface as `_write_once`
  (only `write_tag_once` calls it); `write_part`'s `chunks: list[bytes]` signature; `seal`'s
  `root.chmod(0o555)`; the class docstring's claim that every payload name "is written at most
  once" (the ledger, not `O_EXCL`, is the authority for parts).
- `pkg/catalog/ports.py`: `RawStore.create_staging(ingest_id)` (replaced by the path form).
- `service/api/repository.py:101`: the `PosixRawStore` annotation and, if it becomes unused, its
  import.
- `design/layer-raw.html:285` "dirs 0555" as the pre-rename seal of the root (write-back above).
- Tests: none; `tests/unit/test_rawstore_generation.py` stays as is.

### Data flow

```mermaid
sequenceDiagram
    participant F as ingest facade (async)
    participant T as worker thread (asyncify)
    participant S as PosixRawStore
    participant E as .staging/{hex}
    participant P as …/raw/revision/

    Note over F,E: uploads, one asyncify hop per part
    F->>T: asyncify(write_part)(payload, rel, chunks, offset, length)
    T->>S: write_part
    S->>E: pwrite range · fsync(file) · fsync(dirs up to payload/)
    S-->>F: sha256 of the range
    Note over F,E: :verify — links before any seal
    F->>T: asyncify(hardlink_from_parent)
    T->>E: samefile? no-op : unlink+link · fsync(dir)
    Note over F,P: :commit — begin_commit (etag CAS, Design 3) then the six steps
    F->>T: asyncify(write_document) ×2
    T->>E: manifest.json, metadata.json (replace, 0o444, fsync file+root)
    F->>T: asyncify(seal)
    T->>E: files 0o444 · dirs below root 0o555 · root stays 0o700
    F->>T: asyncify(write_document)
    T->>E: COMMITTED (replace, fsync)
    F->>T: asyncify(commit_envelope)
    rect rgb(235,235,235)
        Note right of T: durability boundary
        T->>E: fsync_tree (files, dirs deepest-first, root)
        T->>P: rename(staging → final)
        T->>P: fsync(final.parent) ◀ durability point
        T->>P: chmod(final, 0o555) · fsync(final)
    end
    S-->>F: return
    Note over F: step 7 — ONE PG transaction (Design 3)
    Note over F,P: retry after a crash past the rename
    F->>T: asyncify(commit_envelope)
    T->>P: staging gone ∧ final/COMMITTED → reseal root, return
```

### Rejected alternatives

- **Parts as separate files assembled at `:complete`** — 50% more I/O and a transient second copy
  of the largest file; the range write gives the same resume semantics in one write pass.
- **An async `RawStore` (`write_part(AsyncIterator[bytes])`)** — every syscall would run on the
  loop or cost a thread hop per chunk; the tier's rule already puts one hop around the whole call.
- **Unlink-then-`O_EXCL` per part (today's whole-file semantics, per part)** — cannot coexist with
  out-of-order parts into one file, and Design 1 already made the ledger, not `EEXIST`, the
  authority.

### Open questions

1. **What the post-rename retry builds the revision row from.** After a crash between step 6 and
   step 7 the published documents carry the crashed attempt's `committed_at` (Design 1 takes it at
   `begin_commit`; a re-entry takes a new one), while the retry's `RevisionRecord` would carry a
   different instant. *Recommended:* the retry reads them back — `read_document(final / "COMMITTED")`
   and `read_document(final / "metadata.json")` (for `metadata_sha256`) — and builds the record
   from storage, which is exactly what §5 row 6 says the reconciler does ("imports the row from
   `COMMITTED`"); it needs no migration and no domain field, and the P3 reconciler reuses the
   same read. The alternative is Design 3 persisting the commit instant on `ingest_sessions` at
   the COMMITTING edge (a `0009` column, and a `committed_at` on Design 1's `IngestSession`) so
   every retry produces byte-identical documents; that is cleaner for the row but costs two
   owners a change each.
2. **Multipart at 64 MiB or whole-file only (Design 1's Open question 2, mechanics side).**
   `write_part` expresses both; the mechanics cost of multipart is `finish_file`'s one sequential
   read per multipart file and `PART_BYTES`-aligned range arithmetic in Design 4. *Recommended:*
   multipart — a 9 GiB restart from zero fails milestone 8's gate in spirit, and range writes make
   resume a one-line overwrite rather than a second code path.

### Tests

Helper, `tests/unit/support.py`:
`crash_on(monkeypatch, name: str, *, call: int = 1, errno_: int = errno.EIO) -> list[str]` —
patches `os.<name>` (`rename`, `fsync`, `link`, `pwrite`) so its `call`-th invocation raises
`OSError(errno_)`, records every call's first argument, and is the injection the crash-matrix gate
reuses for "kill after step *n*"; `fsync_log(monkeypatch) -> list[Path]` — records the path behind
every `os.fsync` by pairing it with the `os.open` that produced the descriptor, so ordering
assertions read as paths.

`tests/unit/test_rawstore_commit.py` (`pytest.mark.unit`, `tmp_path`):

| Test | Asserts |
|---|---|
| `test_fsync_dir_flushes_a_directory_descriptor_and_refuses_a_file` | one fsync on a directory fd; `NotADirectoryError` for a file |
| `test_fsync_tree_flushes_files_then_directories_deepest_first_then_the_root` | `fsync_log` order over a 3-level tree |
| `test_fsync_tree_opens_a_sealed_tree` | no error over `0o444`/`0o555` |
| `test_assert_same_filesystem_creates_both_roots_and_accepts_one_device` | directories exist, no raise |
| `test_assert_same_filesystem_refuses_two_devices` | `Path.stat` patched for one root → `CrossDeviceCommitError` with `errno.EXDEV` |
| `test_commit_envelope_refuses_an_existing_final_that_is_not_a_completed_retry` | `FileExistsError`; staging untouched; zero fsyncs |
| `test_commit_envelope_refuses_a_missing_staging_directory` | `FileNotFoundError` |
| `test_commit_envelope_refuses_an_envelope_without_the_committed_marker` | `ValueError`; zero renames |
| `test_commit_envelope_refuses_a_cross_device_pair_before_any_fsync` | `CrossDeviceCommitError`; zero fsyncs |
| `test_commit_envelope_translates_exdev_from_the_rename` | `crash_on("rename", errno_=EXDEV)` → `CrossDeviceCommitError`; staging intact |
| `test_commit_envelope_fsyncs_the_whole_tree_before_the_rename_and_the_parent_after` | `fsync_log`: every file and directory precedes the rename; `final.parent` and `final` follow it |
| `test_commit_envelope_publishes_and_seals_the_root` | `final` is a dir at `0o555`, staging gone |
| `test_commit_envelope_retry_after_the_rename_is_silent_and_reseals_the_root` | root chmod'ed back to `0o700`, second call returns, root `0o555` |
| `test_a_crash_in_the_tree_fsync_attempts_no_rename` | `crash_on("fsync")` → zero renames, staging intact |
| `test_a_crash_in_the_rename_leaves_staging_intact_and_final_absent` | `crash_on("rename")` → both hold |
| `test_a_crash_in_the_parent_fsync_leaves_the_envelope_published_and_the_retry_silent` | `crash_on("fsync", call=<after rename>)` → `final` exists; second call silent |

`tests/unit/test_rawstore_store.py`:

| Test | Asserts |
|---|---|
| `test_initialize_creates_the_skeleton_and_refuses_a_cross_device_layout` | dirs exist; patched `st_dev` → `CrossDeviceCommitError` |
| `test_create_staging_claims_a_private_envelope_once` | `0o700` root and payload; `.staging`, envelope, payload in `fsync_log`; second call `FileExistsError`; a path outside `.staging` → `ValueError` |
| `test_write_part_pulls_one_chunk_at_a_time_and_reports_the_digest_of_the_bytes_written` | a spying generator sees `__next__` only after the previous chunk is on disk; digest equals `sha256(b"".join(chunks))` |
| `test_write_part_places_parts_at_their_offsets_in_any_order` | parts 3, 1, 2 → file equals the concatenation |
| `test_write_part_overwrites_a_resent_part_s_range_only` | a partial then a full part 2; parts 1 and 3 untouched |
| `test_write_part_refuses_a_short_or_long_stream` | `PartLengthMismatch` both ways; no digest returned |
| `test_write_part_propagates_a_mid_stream_exception_and_leaves_the_range_for_the_resend` | `ConnectionResetError` propagates; file exists `0o600`; a re-send succeeds |
| `test_write_part_fsyncs_the_file_and_every_directory_up_to_the_payload_root` | `fsync_log` holds the file and each ancestor through `payload/`; created dirs are `0o700` |
| `test_write_part_refuses_an_unsafe_path_before_touching_the_disk` | `ValueError`; nothing created |
| `test_a_single_part_write_is_the_whole_file_observation` | `offset=0, length=size` digest equals `finish_file`'s |
| `test_finish_file_reports_size_and_digest_and_refuses_a_missing_file` | `(st_size, sha256)`; `FileNotFoundError` |
| `test_discard_file_removes_the_file_and_tolerates_a_missing_one` | gone; second call returns |
| `test_hardlink_from_parent_links_the_inode_and_is_idempotent` | `nlink == 2`, `samefile`; second call no error, `nlink` still 2 |
| `test_hardlink_from_parent_replaces_a_foreign_file_at_the_target` | different inode there → afterwards `samefile` |
| `test_hardlink_from_parent_copies_when_linking_fails_and_the_copy_is_enabled` | `crash_on("link", errno_=EPERM)` → bytes equal, `nlink == 1`, `0o600` |
| `test_hardlink_from_parent_raises_when_linking_fails_and_the_copy_is_disabled` | `OSError(EPERM)`; target absent |
| `test_hardlink_from_parent_links_a_sealed_parent_file_into_a_private_envelope` | `0o444` in `0o555` → linked; parent modes unchanged |
| `test_seal_makes_files_read_only_and_directories_below_the_root_traversal_only` | `0o444`/`0o555`; root mode unchanged; write → `PermissionError`; idempotent |
| `test_seal_refuses_a_missing_directory` | `FileNotFoundError` |
| `test_seal_after_hardlink_leaves_the_shared_inode_read_only_for_both_revisions` | parent and staging paths both `0o444`, `nlink == 2` |
| `test_write_document_replaces_at_the_envelope_root_and_refuses_a_nested_or_reserved_name` | second write wins; `0o444`; `a/b`, `..`, `payload` → `ValueError` |
| `test_read_document_returns_the_bytes_and_refuses_a_missing_file` | equality; `FileNotFoundError` |
| `test_atomic_replace_leaves_the_old_bytes_when_the_write_fails` | `crash_on("fsync")` → old bytes, no temp file left |
| `test_safe_relative_refuses_escapes_and_strips_a_leading_payload_component` | parametrized: `../x`, `/abs`, `""`, `.`, `a/./b`, `a//b`, `payload` → `ValueError`; `payload/a` → `a`; `a/b` → `a/b` |

`tests/unit/test_execution_model.py` (Design 4 adds, Design 7 places):
`test_the_upload_route_s_write_part_executes_off_the_event_loop_thread` — same pattern as the
`readyz` tripwire, `ran_on_the_event_loop == [False]`.

### Receipts

`uv run python scratchpad/d2_proofs.py` at `c5e35c7` (script in the session scratchpad), salient
lines:

- `os.link` onto an existing same-inode link → `FileExistsError EEXIST`, `samefile True`,
  `nlink 2`; onto a foreign inode → `FileExistsError EEXIST`, `samefile False`.
- `write_part` with a generator raising after two chunks → `ConnectionResetError` propagates;
  `a/b.bin` left, size 6, mode `0o600`; retry → `FileExistsError`.
- Parent file `0o444` in `0o555` dirs linked into a `0o700` envelope → `nlink 2`, `samefile True`;
  `hardlink_from_parent` twice → `FileExistsError`; after `seal`: file `0o444`, parent `0o444`,
  dirs `0o555`, root `0o555`; write through the link → `PermissionError`. Intermediate directory
  created by `mkdir(parents=True)` was `0o755` (umask `0o22`).
- `os.rename` of the `0o555` envelope root into `raw/revision/` → **`EACCES` on darwin**;
  `atomic_replace` inside the `0o555` root → `PermissionError`.
- `commit_envelope` with `os.rename` → `EIO`: raised after 7 fsyncs, staging intact, final absent;
  with `EXDEV`: `CrossDeviceCommitError EXDEV`; with `os.fsync` → `EIO`: zero renames; real
  commit: final present, staging gone, root `0o700` (today's code does not reseal); second call
  silent.
- `assert_same_filesystem(scratch, /dev)` → `CrossDeviceCommitError EXDEV`
  (`st_dev` 18446744072009856479 vs 16777234); `/System/Volumes/VM` → `EXDEV` (16777233);
  `/` → same device as the scratchpad.
- `os.pwrite` parts 3, 1, 2 (4-byte parts, 3-byte last) → `b"AAAABBBBCCC"`, size 11; re-send of
  part 2 → `b"AAAAbbbbCCC"`.
- `hardlink_from_parent` with `os.link` → `EPERM`: copied, `nlink 1`, `0o600`; with
  `hardlink_fallback_copy=False`: `EPERM` propagates, target absent.
- `fsync_tree` over the sealed published tree: ok.
- `mypy --strict` and `ty check` on a scratch `Protocol` with `@property root -> Path` satisfied by
  `self.root = Path(root)` and a consumer typed against the protocol: both clean.
- `asyncer` 0.0.18 exports `syncify`; its docstring: "expected to be used from a worker thread.
  For example inside some function passed to `asyncify()`".
- Not run: Linux (the `EACCES` on rename is taken from `rename(2)`'s documented `EACCES` case and
  the darwin receipt); NFS; a real `EXDEV` from `os.rename` (only the injected one).

## Design 3 — Ingest persistence: the port and its PostgreSQL implementation

Designed against `main` at `c5e35c7`, with Designs 1 and 2 as binding inputs. Every claim marked
**proved** was run against a disposable `postgres:16` migrated to `0008` (podman; § Receipts). One
of them settles the arbiter question the DDL leaves open: **without a row lock, two allocators
computing the same `max + 1` are decided by whichever unique index PostgreSQL checks first, which
is index-OID order — `one_open_ingest_per_dataset` (OID 16539, from `0001`) before
`one_claim_per_revision_number` (16934, from `0008`)**. That order is an artefact of migration
history and would invert under a dump/restore that recreates indexes by name, so the design does
not make either index the arbiter. The arbiter is a row lock on `datasets`; the indexes are
backstops.

### Target design

**Port convention: extend the tier-owned `HierarchyStore`/`HierarchyWriter` in
`service/api/stores/ports.py`; delete `pkg/catalog/ports.py::Metastore`.** Reasons, in order of
weight. (1) The commit transaction spans `dataset_revisions` — already the hierarchy store's table
(`revision_ref` `:1290`, the `release` join `:1274`) — plus `ingest_sessions`, `audit_events`,
`outbox_events` and `idempotency_records`; the writer that inserts the revision must be the one
that `claim`s and `remember`s, and a second store with its own `transaction()` would have to share
the idempotency ledger, the revisions and the datasets with the in-memory twin — three shared
structures with no PostgreSQL analogue beyond "the pool" — and would give the tier two transaction
types that can never be combined. (2) Every route is tested over `TestClient` with
`memory_stores()`; the ingest routes need the same twin, and the twin's test-only
`register_revision` (`hierarchy.py:700`) becomes the real `insert_revision`. (3) `Metastore` is a
consumer-owned port with no consumer and no implementation (`grep -rn Metastore src tests` → its
definition only); its `begin_ingest` docstring (Design 1's replacement text) moves to
`HierarchyWriter.begin_ingest` unchanged, `record_revision`'s atomicity sentence becomes the
commit-transaction contract below, and `resolve_tag` is `HierarchyStore.release`. The class name
`HierarchyStore` is kept; its docstring's first line widens to "The hierarchy's durable state and
the ingest workflow that extends it". The port stays a `typing.Protocol` satisfied structurally by
one in-memory and one Postgres adapter in `stores/hierarchy.py`, exported through
`stores/__init__.py` only.

**Module layout.**

| Module | Change |
|---|---|
| `stores/ports.py` | `HierarchyWriter` +8 methods, `HierarchyStore` +6 reads (below); `Replay.kind` gains `"ingest_session"`, `"revision"` |
| `stores/hierarchy.py` | both adapters implement the additions; `InMemoryHierarchyStore` gains `_sessions`, `_files`, `_audit`, `_outbox` dicts and `_revisions` is re-keyed `dict[UUID, RevisionRecord]`; `_TransactionBuffer` gains the same; `register_revision` deleted |
| `stores/rows.py` | `ingest_session(row) -> IngestSession`, `ingest_file(row) -> LedgerEntry`, `revision_record(row) -> RevisionRecord` |
| `service/api/records.py` | `AuditEvent`, `LedgerEntry` (`@dataclass(slots=True)`, stdlib fields only, as the module requires) |
| `pkg/catalog/ports.py` | `Metastore` deleted |
| `migrations/versions/0009_ingest_ledger.py`, `migrations/schema.sql` | the DDL below; stamp moves |

**The port additions** (`stores/ports.py`; `IngestSession`, `IngestFile`, `RevisionRecord`,
`OutboxEvent`, `LEASE_TTL` from `huron.pkg.catalog`):

```python
@dataclass(slots=True)
class AuditEvent:
    """One append-only audit row: who did what to which subject, and when."""
    id: UUID; kind: str; actor: str; subject_kind: str; subject_id: UUID | None
    payload: dict[str, object]; created_at: datetime

@dataclass(slots=True)
class LedgerEntry:
    """One ingest file together with the session whose ledger it belongs to."""
    ingest_id: UUID
    file: IngestFile

class Replay:
    kind: Literal["organization", "project", "dataset", "release", "ingest_session", "revision"]

class HierarchyWriter(Protocol):          # additions; every existing method unchanged
    async def begin_ingest(
        self, dataset_id: UUID, manifest_sha256: str, *,
        created_by: str, parent_revision_id: UUID | None, files: Sequence[IngestFile],
    ) -> IngestSession:
        """Open a session in PREPARING and reserve max(revision_number) + 1 under the dataset's row lock; Design 1's docstring."""
    async def update_ingest_session(self, session: IngestSession, *, expected_etag: int) -> None:
        """Persist one state edge: state and etag land only when the stored etag equals ``expected_etag``."""
    async def renew_ingest_session(self, session: IngestSession) -> None:
        """Move ``expires_at`` forward to the session's lease, never backward, without touching the etag."""
    async def expire_ingest_session(self, session: IngestSession, *, expected_etag: int, now: datetime) -> None:
        """Persist an ``expire`` edge: the etag CAS plus a fence that the stored lease is still lapsed at ``now``."""
    async def update_ingest_file(self, ingest_id: UUID, file: IngestFile, *, expected_parts: frozenset[int]) -> None:
        """Persist one ledger step for a PENDING file whose stored parts still equal ``expected_parts``."""
    async def insert_revision(self, record: RevisionRecord) -> None:
        """Insert the row a COMMITTING session publishes; refuses a manifest the dataset already holds."""
    async def insert_audit_event(self, event: AuditEvent) -> None:
        """Append one audit row."""
    async def insert_outbox_event(self, event: OutboxEvent) -> None:
        """Append one outbox row, unprocessed."""

class HierarchyStore(Protocol):           # additions; none takes Visibility - the caller authorises on the dataset the read names
    async def ingest_session(self, session_id: UUID) -> IngestSession:
        """Return one session by id; ``ResourceNotFound`` otherwise."""
    async def ingest_files(self, session_id: UUID) -> tuple[IngestFile, ...]:
        """Return a session's ledger in manifest order (by ``path``)."""
    async def ingest_file(self, file_id: UUID) -> LedgerEntry:
        """Return one ledger entry and its session id; ``ResourceNotFound`` otherwise."""
    async def revision(self, revision_id: UUID) -> RevisionRecord:
        """Return one revision row in any state; ``ResourceNotFound`` otherwise."""
    async def latest_committed_revision(self, dataset_id: UUID) -> RevisionRecord | None:
        """Return the dataset's highest-numbered revision in state COMMITTED - the hardlink parent - or None."""
    async def lapsed_ingest_sessions(self, now: datetime, *, limit: int) -> tuple[IngestSession, ...]:
        """Return up to ``limit`` sessions in PREPARING/UPLOADING/VERIFYING whose lease lapsed at or before ``now``, oldest first; never COMMITTING."""
```

**SQL-level semantics.** All statements run on the transaction's connection; `$n` parameters with
explicit casts; decoding in `rows.py`. `TERMINALS` is `('COMMITTED','ABORTED','FAILED')`.

| Method | Statements, in order | Refusal → error |
|---|---|---|
| `begin_ingest` | 1 `SELECT id FROM datasets WHERE id = $1 FOR UPDATE` · 2 `SELECT id, state, expires_at FROM ingest_sessions WHERE dataset_id = $1 AND state NOT IN TERMINALS` · 3 `SELECT id FROM dataset_revisions WHERE dataset_id = $1 AND manifest_sha256 = $2` · 4 `SELECT id FROM dataset_revisions WHERE dataset_id = $1 AND state = 'COMMITTED' ORDER BY revision_number DESC LIMIT 1` · 5 `SELECT coalesce(max(revision_number), 0) + 1 FROM dataset_revisions WHERE dataset_id = $1` · 6 `INSERT INTO ingest_sessions (id, dataset_id, revision_id, revision_number, manifest_sha256, state, etag, expires_at, created_by, created_at, updated_at, parent_revision_id) VALUES (uuid7(), $1, uuid7(), <5>, $2, 'PREPARING', 1, $now + LEASE_TTL, $3, $now, $now, $4)` · 7 `INSERT INTO ingest_files (file_id, ingest_id, path, size, expected_sha256, action, part_count) SELECT * FROM unnest($1::uuid[], $2::uuid[], $3::text[], $4::bigint[], $5::text[], $6::text[], $7::integer[])` | 1 no row → `ResourceNotFound`; 2 a row → `DatasetLocked(context={"session_id","state","expires_at"})`; 3 a row → `DuplicateContent(context={"revision_id"})`; 4 result ≠ `parent_revision_id` → `DatasetLocked(context={"reason":"parent_superseded","latest_revision_id"})`; 6 `UniqueViolation` `one_open_ingest_per_dataset` → `DatasetLocked` (backstop, unreachable under 1), `one_claim_per_revision_number` → propagates (an invariant broken by a writer outside this adapter); `ingest_sessions_parent_revision_fk` (`23503`) → propagates (the caller passed a revision of another dataset: a bug, not a client condition) |
| `update_ingest_session` | `UPDATE ingest_sessions SET state = $2, etag = $3, updated_at = $4 WHERE id = $1 AND etag = $5` (`$3 = session.etag`, `$5 = expected_etag`) | zero rows → `PreconditionFailed`; `ingest_sessions_revision_guard` (`P0001`) when `state = 'COMMITTED'` and no matching revision row → propagates (statement order below makes it unreachable) |
| `renew_ingest_session` | `UPDATE ingest_sessions SET expires_at = GREATEST(expires_at, $2), updated_at = $3 WHERE id = $1 AND state NOT IN TERMINALS` | zero rows → `IngestSessionExpired` (the session became terminal under the caller) |
| `expire_ingest_session` | `UPDATE ingest_sessions SET state = 'ABORTED', etag = $2, updated_at = $3 WHERE id = $1 AND etag = $4 AND state IN ('PREPARING','UPLOADING','VERIFYING') AND expires_at <= $3` | zero rows → `PreconditionFailed` (renewed, already flipped, or COMMITTING); the sweep skips the row |
| `update_ingest_file` | `UPDATE ingest_files SET state = $3, completed_parts = $4::jsonb WHERE file_id = $1 AND ingest_id = $2 AND state = 'PENDING' AND completed_parts = $5::jsonb` (`$4`, `$5` are sorted JSON arrays, so equality is set equality) | zero rows → `PreconditionFailed`; the caller re-reads and re-applies the domain step, which is idempotent |
| `insert_revision` | `INSERT INTO dataset_revisions (id, dataset_id, revision_number, manifest_sha256, metadata_sha256, revision_path, file_count, total_bytes, committed_by, committed_at) VALUES (…)` — `state` takes its DDL default | `dataset_revisions_dataset_id_manifest_sha256_key` → `DuplicateContent`; `…_revision_number_key`, `…_revision_path_key` → propagate (unreachable under the allocator) |
| `insert_audit_event`, `insert_outbox_event` | one `INSERT` each; `payload` as `$n::jsonb` | format/shape CHECKs propagate (a caller bug) |
| `ingest_session`, `ingest_file`, `revision` | `SELECT … WHERE id = $1` on the pool | no row → `ResourceNotFound` |
| `ingest_files` | `SELECT … FROM ingest_files WHERE ingest_id = $1 ORDER BY path COLLATE "C"` | — |
| `latest_committed_revision` | statement 4 above, on the pool, selecting every column | — |
| `lapsed_ingest_sessions` | `SELECT … FROM ingest_sessions WHERE state IN ('PREPARING','UPLOADING','VERIFYING') AND expires_at <= $1 ORDER BY expires_at, id LIMIT $2` | — |

**The allocator and the race.** Statement 1 is the arbiter: two `begin_ingest` calls on one
dataset serialise on the `datasets` row lock; the second blocks until the first's transaction
commits, then runs statement 2 on a fresh READ COMMITTED snapshot, sees the PREPARING row and
raises `DatasetLocked` — **proved**: two concurrent transactions, exactly one `won`, the other
`locked` with the holder's state `PREPARING`, one open row afterwards, no `UniqueViolation`
raised. "Committed" in `max(committed) + 1` means **a `dataset_revisions` row exists in any
state**: a revision that retention later marks `EXPIRED` or `PURGED` keeps its number and
`UNIQUE (dataset_id, revision_number)` is total, so the pool of numbers only ever grows by one per
commit. The parent for hardlinks (statement 4) is a different question — the highest revision
whose bytes are on disk — and must equal the caller's `parent_revision_id` because the plan was
computed against it; a mismatch means another session committed between the caller's parent read
and this call (**proved** the refusal for `None` against a committed latest). Gap-free numbering
follows: an `ABORTED`/`FAILED` session leaves no revision row, so the next allocation recomputes
the same number, and `one_claim_per_revision_number` admits it because the dead row is outside the
index predicate — **proved**: abort then retry re-takes `1` with the dead row kept `ABORTED`, and
100 sequential begin→commit cycles with a `FAILED` attempt before every tenth number `1..100`
exactly, leaving 100 `COMMITTED` and 10 `FAILED` session rows.

**The expired-session rule.** An expired-but-unflipped session **still holds the dataset lock**;
`begin_ingest` never flips it and raises `DatasetLocked` with the holder's `expires_at` in
`context` so the client can see it has lapsed (**proved**: a lapsed `COMMITTING` row refuses the
next `begin_ingest`). The flip is performed by exactly two actors: the owner or a project admin
through `abort` (any time; Design 1 made `abort` lease-agnostic) and the sweep (Design 6) through
`lapsed_ingest_sessions` → `session.expire(now)` → `expire_ingest_session`. Not the allocator,
because the `ingest.expired` audit row would then be written by a request of a different
principal on a session it does not own, the allocator would inherit the sweep's bound and loop,
and two writers of one edge under replicas is one too many. `COMMITTING` is never listed and never
matched by the fence (**proved**: 0 rows at `now + 9 days`); a crashed driver there is Design 1's
Open question 1. Cost: a dataset stays locked for up to `LEASE_TTL` plus one sweep period after a
client vanishes; the owner can `abort` sooner.

**Etag and the other fences.** State edges are compare-and-swap on `etag` and write the value's
own `etag` (the domain bumped it by one), the house pattern of `update_organization`
(**proved**: a stale expected etag → 0 rows; the edge with the current one → `etag` 2, 3, …).
`renew` has no etag predicate; `GREATEST` makes concurrent renewals commutative and an older
instant never moves the lease backward (**proved**). The sweep's fence is `expires_at <= now` in
addition to the etag, because `renew` does not move the etag (**proved**: a session renewed to
15:30 is untouched by a sweep at 15:00 and flipped by one at 15:30, etag 3; renew on an `ABORTED`
row → 0 rows). Per-file writes fence on `(file_id, ingest_id, state = 'PENDING', completed_parts =
expected)` and never on the session etag, so parallel parts of different files never serialise and
parallel parts of one file cannot lose an update (**proved**: two writers from the same `[]`, the
first `UPDATE 1`, the second `UPDATE 0`). The store is edge-agnostic: it does not know
`TRANSITIONS`; the `COMMITTING → COMMITTING` re-entry Design 1 recommends is a domain value with
`etag + 1` presented against the current etag, and this port persists it like any other edge.

**`ingest_files` rows.** One row per `IngestFile`, inserted with the session; vocabulary
`state IN ('PENDING','COMPLETE')` (CHECK, `0009`); `part_count` action-tied (CHECK, `0009`);
`completed_parts` the sorted JSON array of the domain's set (`[]` for HARDLINK forever). A
mismatch is never a row state: the caller persists the file back to `PENDING` with `[]` through
`update_ingest_file` with the parts it read.

**The commit transaction** — one `transaction()` block, opened only after `commit_envelope` has
returned (Design 2 step 6, the durability point); no file I/O and no hashing inside it:

1. `claim(IdempotencyClaim)` → a `Replay(kind="revision")` short-circuits; a digest mismatch is
   `IdempotencyKeyReused`.
2. `insert_revision(record)` — the `dataset_revisions` row, `state` defaulting to `COMMITTED`.
3. `update_ingest_session(session.commit(), expected_etag=…)` — `state = 'COMMITTED'`; the guard
   fires here and finds step 2's row `FOR KEY SHARE`.
4. `insert_audit_event(AuditEvent(kind="revision.committed", subject_kind="revision", subject_id=record.id, …))`.
5. `insert_outbox_event(revision_committed(record, …))`.
6. `remember(claim, Replay("revision", record.id))`.

**Proved**: with 2 and 3 swapped the guard raises `P0001` ("ingest session … claims revision …,
which is not revision … of dataset …"), the transaction rolls back and the session is still
`COMMITTING` at its old etag; in the order above the session ends `COMMITTED` and `revision_ref`
resolves the row. **Transaction across file I/O.** This write follows `layer-raw.html` §3, not
`HierarchyRepository`'s hold-across-the-document invariant (`repository.py:81-84`). The two
coexist because they answer opposite authority questions: a hierarchy generation file is derived
from its row (row first; a failed document write rolls the row back, nothing durable is orphaned),
whereas a revision envelope *is* the revision ("storage leads; the catalog follows") and the row
records what is already on disk. Holding a transaction — and the `datasets` or session row locks
— across a 9 GiB `fsync_tree` would also pin a pool connection for minutes.

**`DUPLICATE_CONTENT`.** Refused twice: at `begin_ingest` statement 3 (**proved**, the explicit
read under the lock, so the client learns before uploading) and at `insert_revision` by
`dataset_revisions_dataset_id_manifest_sha256_key` (**proved**: `23505`, that constraint name),
which under the lock is unreachable and is mapped anyway because it is the same fact. The
constraint is total, so a purged revision's manifest can never be re-ingested (Open question 1).

**Migration `0009_ingest_ledger`** — needed. Candidates: `ingest_files.state` CHECK — **yes**
(Design 1 decided the vocabulary; every other state column has one); `part_count` — **yes**
(Design 1 (a), action-tied CHECK); `parent_revision_id` — **yes**, as a composite FK
`(parent_revision_id, dataset_id) → dataset_revisions (id, dataset_id)` on the house precedent
`releases_revision_dataset_fk`, so a parent of another dataset is refused declaratively
(**proved**: `23503 ingest_sessions_parent_revision_fk`; NULL passes under `MATCH SIMPLE`);
`ingest_sessions (dataset_id)` index — **yes**: the two partial unique indexes cannot serve a
predicate-free lookup, so the `datasets` FK check and any per-dataset listing sequential-scan the
table (**proved** with `enable_seqscan = off`: `Seq Scan … cost=10000000000` before, `Index Scan
using ingest_sessions_dataset` after); an index on the new FK column — **yes**, `0008:178-188`'s
rule; an observed-digest column — **no** (Design 1: compared and discarded); `metadata_sha256` —
**no column change**, it is `RevisionRecord.metadata_sha256` from Design 5's document;
`created_by` — **already present** (`0001:126`); a commit-instant column (Design 2 Open question 1)
— **no**: the retry after a crash between the rename and step 7 must describe what is on disk,
and only `final/COMMITTED` knows that; a persisted instant would make the row agree with a
document the client may resubmit differently. Raw-SQL style of `0008`:

```sql
-- upgrade()
-- The parent a session's upload plan was computed against: the dataset's
-- highest COMMITTED revision at reservation time, whose payload the
-- HARDLINK entries link from. The composite key, as for releases, keeps
-- the citation inside the session's own dataset.
ALTER TABLE ingest_sessions ADD COLUMN parent_revision_id uuid;
ALTER TABLE ingest_sessions
    ADD CONSTRAINT ingest_sessions_parent_revision_fk
        FOREIGN KEY (parent_revision_id, dataset_id) REFERENCES dataset_revisions (id, dataset_id)
        ON DELETE NO ACTION ON UPDATE NO ACTION;
CREATE INDEX ingest_sessions_parent_revision ON ingest_sessions (parent_revision_id, dataset_id);

-- The two partial unique indexes lead with dataset_id but carry a predicate,
-- so neither serves the datasets foreign-key check or a per-dataset listing.
CREATE INDEX ingest_sessions_dataset ON ingest_sessions (dataset_id);

-- A file's progress is a ledger of parts; the plan fixes how many. A
-- hardlinked file has no parts and no state beyond linked or not.
ALTER TABLE ingest_files ADD COLUMN part_count integer NOT NULL;
ALTER TABLE ingest_files
    ADD CONSTRAINT ingest_files_part_count_matches_action
        CHECK ((action = 'hardlink' AND part_count = 0) OR (action = 'upload' AND part_count >= 1));
ALTER TABLE ingest_files
    ADD CONSTRAINT ingest_files_state_vocabulary
        CHECK (state IN ('PENDING','COMPLETE'));

-- downgrade()
ALTER TABLE ingest_files DROP CONSTRAINT ingest_files_state_vocabulary;
ALTER TABLE ingest_files DROP CONSTRAINT ingest_files_part_count_matches_action;
ALTER TABLE ingest_files DROP COLUMN part_count;
DROP INDEX ingest_sessions_dataset;
DROP INDEX ingest_sessions_parent_revision;
ALTER TABLE ingest_sessions DROP CONSTRAINT ingest_sessions_parent_revision_fk;
ALTER TABLE ingest_sessions DROP COLUMN parent_revision_id;
```

`ADD COLUMN … NOT NULL` without a default is deliberate: `ingest_files` has no writer at `0008`,
so it is empty in every deployment, and a row of unknown origin is not ours to backfill. Every
CHECK was exercised (**proved**: `23514 ingest_files_part_count_matches_action` for
`hardlink/1` and `upload/0`, `23514 ingest_files_state_vocabulary` for `MISMATCHED`) and the
downgrade leaves no `parent_revision_id`/`part_count` column (**proved**). `schema.sql`: the
`Reflects:` line becomes `0009_ingest_ledger`; `ingest_sessions` gains
`parent_revision_id uuid,  -- NULL for a first revision` and the annotations
`-- [db] FOREIGN KEY (parent_revision_id, dataset_id) REFERENCES dataset_revisions (id, dataset_id) ingest_sessions_parent_revision_fk: the plan's parent is a revision of this dataset`,
`-- [db] index ingest_sessions_parent_revision (parent_revision_id, dataset_id)`,
`-- [db] index ingest_sessions_dataset (dataset_id)`; `ingest_files.state`'s `[spec]` block
(`:160-162`) becomes `-- [db] ingest_files_state_vocabulary CHECK IN ('PENDING','COMPLETE'): PENDING until every part is in the envelope and proven`,
plus `part_count integer NOT NULL,  -- [db] ingest_files_part_count_matches_action CHECK: 0 iff hardlink, >= 1 iff upload`;
`dataset_revisions`'s `[spec] linear, gap-free` block (`:87-89`) becomes
`-- [app] service.api.stores.hierarchy begin_ingest: linear and gap-free - max(revision_number) + 1 over every row, taken under SELECT ... FOR UPDATE on the datasets row`.
`scripts/check_schema_map.py` needs no change; `make lint` passes once the stamp moves.

### Explicit contracts

**Invariants the store holds.** At most one `ingest_sessions` row per dataset outside `TERMINALS`
(row lock + `one_open_ingest_per_dataset`); `revision_number` of a new session equals
`max(revision_number) + 1` over the dataset's `dataset_revisions` rows at the instant the lock is
held; a `COMMITTED` session's `(revision_id, dataset_id, revision_number, manifest_sha256)` names
an existing revision row (guard); `parent_revision_id` is NULL or a revision of the same dataset
(composite FK); a file row is `COMPLETE` only by a write that fenced on `PENDING`; `expires_at`
never decreases. **Error behaviour** is the table above; the store raises only
`ResourceNotFound`, `DatasetLocked`, `DuplicateContent`, `PreconditionFailed`,
`IngestSessionExpired`, `IdempotencyKeyReused` — no new error code. **Isolation.** READ COMMITTED
(the pool default); correctness rests on the `datasets` row lock and on each statement after it
taking a fresh snapshot, never on repeatable reads. Only `begin_ingest` takes the dataset lock;
the commit transaction needs none, because the session it flips is the dataset's only open one
and its revision row cannot collide. **Lifecycle.** A session row is never deleted by this tier;
a dead row is the record of the attempt. The in-memory twin serialises every transaction on its
`asyncio.Lock`, so the race is trivially serial there; each SQL predicate has a one-line dict
equivalent (open-session scan, manifest scan, `max` over the revisions dict, etag compare, parts
compare, `expires_at` compare) so the contract scenarios hold on both.

**Requirements on the other designs.**

- **Design 4 (HTTP and the facade).** (a) `POST /ingest-sessions` performs exactly one store
  transaction — `claim` → `begin_ingest` → `insert_audit_event(ingest.started)` →
  `remember(Replay("ingest_session", id))` — then `create_staging` outside any transaction, then a
  second transaction for the `open` edge; if `create_staging` raises, persist `session.fail()`
  (the number is freed) before surfacing the error. A dataset created at intake is the hierarchy
  writer's own transaction under its own idempotency claim; the two writes are never one
  transaction (S7a: the dataset is kept, empty, if the ingest dies). (b) On
  `DatasetLocked(reason="parent_superseded")` the facade may re-plan once — re-read
  `latest_committed_revision`, re-read its manifest, recompute — before surfacing it. (c) Upload
  routes hold no transaction across `write_part`; the ledger write is one `update_ingest_file`
  after the bytes are durable, retried after a re-read on `PreconditionFailed`. (d) `:commit`,
  before `begin_commit`: if the session is already `COMMITTED`, return `revision(lease.revision_id)`
  — this is what makes a replayed commit return the same revision whether or not the key survives;
  then the `begin_commit` edge in its own transaction; then Design 2's six steps; then, if
  `final/COMMITTED` was present before the steps (a re-entry past the rename), build the record by
  Design 2's read-back; then the six-statement transaction above. Any failure before the rename →
  the `fail` edge; between the rename and the transaction → nothing, the client retries. (e) Audit
  kinds this tier writes, all `subject_kind = "ingest_session"` except the last:
  `ingest.started`, `ingest.aborted`, `ingest.force_aborted`, `ingest.failed`, `ingest.expired`,
  and `revision.committed` (`subject_kind = "revision"`); `actor` is the principal subject, or
  `"system:sweep"` for expiry. (f) `ApiStores`/`ApiRuntime` gain nothing: the facade Design 4
  introduces takes the same `HierarchyStore`.
- **Design 5 (documents).** Supply `metadata_sha256` and the target `revision_path`
  (`paths.revision_dir`) on the `RevisionRecord`; the answer to Design 2's Open question 1 is
  read-back, so `COMMITTED` must carry `committed_by`, `committed_at`, `manifest_sha256`,
  `metadata_sha256`, `file_count`, `total_bytes`. The parent's `revision_path` for
  `read_document` comes from `latest_committed_revision` at create and `revision(parent_revision_id)`
  at `:verify`.
- **Design 6 (sweep).** One pass is `lapsed_ingest_sessions(now, limit=…)`, then per session one
  transaction: `session.expire(now)` → `expire_ingest_session(expired, expected_etag=…, now=now)` →
  `insert_audit_event(ingest.expired)`; `PreconditionFailed` is skipped silently (another replica
  or a renewal got there first). The sweep touches no other table and no file; it never sees
  `COMMITTING`.
- **Design 7 (tests).** Arrange § Tests; `_HIERARCHY_TABLES` in `test_hierarchy_store.py` gains
  `ingest_files`, `ingest_sessions`, `audit_events`, `outbox_events`.

### Deletions

- `src/huron/pkg/catalog/ports.py`: `class Metastore` in full (`:131-186`); its `IngestLease`,
  `RevisionRecord`, `OutboxEvent`, `RevisionRef` imports stay if `RawStore` or `Clock` use them,
  otherwise go with it.
- `src/huron/service/api/stores/hierarchy.py`: `InMemoryHierarchyStore.register_revision`
  (`:700-720`) and its 20 call sites in `tests/` (each becomes
  `async with store.transaction() as w: await w.insert_revision(record)`); `_revisions` keyed by
  `(dataset_id, number)` holding `RevisionRef` (becomes `dict[UUID, RevisionRecord]`;
  `revision_ref` derives the ref).
- `tests/hierarchy_contract.py`: the `seed_revision: Callable[[RevisionRef], Awaitable[None]]`
  parameter on all nine scenarios and every `del seed_revision`; `tests/contract/test_hierarchy_store.py`:
  `_insert_revision` (`:184-206`) — both backends now seed through the port.
- `migrations/schema.sql:87-89` and `:160-162`: the two `[spec]` blocks (replaced above).
- Nothing in `errors.py`, `models.py`, `rows.py` or the routes.

### Data flow

```mermaid
sequenceDiagram
    participant A as begin_ingest (tx A)
    participant DB as PostgreSQL
    participant B as begin_ingest (tx B)
    A->>DB: SELECT datasets … FOR UPDATE
    B->>DB: SELECT datasets … FOR UPDATE
    Note over B,DB: blocks on A's row lock
    A->>DB: open session? none · manifest held? no · parent = latest? yes
    A->>DB: max(revision_number)+1 → N
    A->>DB: INSERT ingest_sessions (PREPARING, N) · INSERT ingest_files
    A->>DB: COMMIT
    Note over B,DB: lock granted; next statement takes a fresh snapshot
    B->>DB: open session? → A's PREPARING row
    B-->>B: DatasetLocked(context={session_id, state, expires_at})
    B->>DB: ROLLBACK
```

```mermaid
sequenceDiagram
    participant F as facade
    participant DB as PostgreSQL
    participant S as PosixRawStore (asyncify)
    F->>DB: tx: UPDATE … COMMITTING, etag=$e+1 WHERE etag=$e
    Note over F,S: no transaction open
    F->>S: write_document ×2 · seal · write_document(COMMITTED) · commit_envelope
    S-->>F: rename durable (durability point)
    F->>DB: BEGIN
    F->>DB: claim → replay? · INSERT dataset_revisions
    F->>DB: UPDATE ingest_sessions COMMITTED WHERE etag = current
    Note right of DB: ingest_sessions_revision_guard: FOR KEY SHARE on the row just inserted
    F->>DB: INSERT audit_events · INSERT outbox_events · remember
    F->>DB: COMMIT
```

### Rejected alternatives

- **A separate `IngestStore` port and `stores/ingest.py`** — clean on paper, but the commit
  transaction needs `claim`/`remember` and the revision insert in one writer, so the in-memory
  twin would have to share three structures with the hierarchy twin and the tier would carry two
  transaction types that can never be combined.
- **Let the unique indexes arbitrate the race without a row lock** — works (proved), but which
  index names the error is index-OID order, an accident of migration history; the row lock makes
  the refusal deterministic and lets the error carry the holder.
- **The allocator flips a lapsed session lazily** — a second writer of the same edge, an audit
  row written by a stranger's request, and the sweep's bound smuggled into every create.

### Open questions

1. **A purged revision's manifest can never be re-ingested** — `UNIQUE (dataset_id,
   manifest_sha256)` is total and `max` counts every row. *Recommended:* keep both for P2 (no
   purge exists; the retention phase can narrow the index to `WHERE state = 'COMMITTED'` if
   re-ingest after purge is wanted, and the allocator is unaffected either way).
2. **Whether `:commit` keeps `Idempotency-Key` given the state-based replay in (d).** The key adds
   only the digest-mismatch refusal on the first attempt. *Recommended:* keep it — convention 4
   and `api.html` require it on creating POSTs, and the check costs one row.

### Tests

`tests/hierarchy_contract.py` (both backends, appended to `_SCENARIOS`):

| Scenario | Asserts |
|---|---|
| `scenario_10_begin_ingest_reserves_and_locks` | first session numbers `1`, `PREPARING`, etag `1`, `expires_at = now + LEASE_TTL`, files `PENDING` with the plan's `part_count`; a second call → `DatasetLocked` with `session_id`/`state`/`expires_at` in `context`; still locked after the clock passes `expires_at`; unknown dataset → `ResourceNotFound`; a manifest already committed → `DuplicateContent`; a stale parent → `DatasetLocked(reason=parent_superseded)` |
| `scenario_11_a_dead_session_frees_its_number_and_a_commit_spends_it` | abort → retry numbers `1`, dead row kept; commit `1` → next is `2`; `FAILED` from `COMMITTING` → next re-takes the number |
| `scenario_12_state_edges_cas_on_etag_and_renew_does_not` | stale `expected_etag` → `PreconditionFailed`, row unchanged; renew moves `expires_at`, etag unchanged; an older instant does not move it back; renew on a terminal → `IngestSessionExpired` |
| `scenario_13_file_ledger_updates_fence_on_pending_and_parts` | update with the stored parts → `COMPLETE`; with stale `expected_parts` → `PreconditionFailed`; a `COMPLETE` file refuses; `ingest_file` returns the entry with its `ingest_id` |
| `scenario_14_the_commit_transaction_is_atomic_and_replays` | steps 1-6 commit together; a raise after `insert_revision` leaves no revision, no outbox row, session `COMMITTING`; the same claim replays `Replay("revision", id)`; `revision`, `latest_committed_revision` and `revision_ref` read it; a second `insert_revision` with the same manifest → `DuplicateContent` |
| `scenario_15_expiry_flips_lapsed_sessions_only` | `lapsed_ingest_sessions` lists lapsed `PREPARING`/`UPLOADING`/`VERIFYING`, never `COMMITTING`, oldest first, bounded by `limit`; `expire_ingest_session` on a renewed row → `PreconditionFailed`; after the flip `begin_ingest` succeeds with the same number |
| `scenario_16_a_hundred_sequential_ingests_number_gap_free` | 100 begin→commit cycles with a `FAILED` attempt before every tenth → revision numbers `1..100`, 100 `COMMITTED` + 10 `FAILED` sessions |

`tests/contract/test_hierarchy_store.py` (Postgres only):
`test_two_concurrent_begin_ingest_calls_serialize_on_the_dataset_row` — `asyncio.gather` of two
transactions; exactly one `IngestSession`, one `DatasetLocked`, one open row.

`tests/contract/test_catalog_store.py` (raw SQL pins for `0009`, beside the existing
`0008` pins): `_assert_ingest_files_state_vocabulary` (`MISMATCHED` → `CheckViolationError`
naming `ingest_files_state_vocabulary`), `_assert_ingest_files_part_count_matches_action`
(`hardlink/1`, `upload/0` refused; `hardlink/0`, `upload/1` accepted),
`_assert_a_parent_revision_belongs_to_the_sessions_dataset` (`ForeignKeyViolationError` naming
`ingest_sessions_parent_revision_fk`; NULL accepted), `_assert_ingest_sessions_dataset_index_serves_a_bare_dataset_lookup`
(`EXPLAIN` under `enable_seqscan = off` names `ingest_sessions_dataset`), and `_assert_round_trip`
extended so the `0009` → `0008` downgrade drops both columns and re-upgrade restores them. The
existing guard-order pin (`_assert_trigger_rejects_a_committed_session_naming_no_revision`) and
the two index pins stay as they are. `scripts/check_schema_map.py`'s unit test is unchanged; the
gate's `make lint` proves the stamp.

### Receipts

Container: `podman run -d --name huron-d3-pg -e POSTGRES_… -p 127.0.0.1:55432:5432 postgres:16`
(podman 5.4.1, arm64); `pg_isready` accepting; `HURON_DATABASE_URL=… uv run alembic upgrade head`
→ `0001` … `0008`; scripts `d3_proofs.py` and `d3_sweep.py` in the session scratchpad; `podman rm
-f huron-d3-pg` → removed, `podman ps -a` shows none. Salient output:

- `pg_index` OID order on `ingest_sessions`: pkey 16528, `revision_id_key` 16530,
  `one_open_ingest_per_dataset` 16539, `one_claim_per_revision_number` 16934.
- Race under `SELECT … FOR UPDATE`: `['locked', 'won']`, loser saw holder state `PREPARING`; open
  rows after: 1, number 1. Race with no lock and no check: `('unique', '23505',
  'one_open_ingest_per_dataset')` and `('won', 1)`.
- Abort then retry: stale etag CAS → `None`; open → etag 2; abort → 3; retry number 1; dead row
  `ABORTED`.
- Flip before insert: `P0001 RaiseError ingest session … claims revision …, which is not
  revision …`; session afterwards `COMMITTING`, etag 4; right order → `COMMITTED`, etag 5.
- Duplicate at begin: `DuplicateContent` carrying the committed revision id; at insert: `23505
  dataset_revisions_dataset_id_manifest_sha256_key`. Stale parent (`None` vs latest) refused.
- Gap-free: numbers `== range(1, 101)`; `{'c': 100, 'f': 10}`.
- Lapsed `COMMITTING` still locks the next `begin_ingest`. Renew to 15:30 (`GREATEST`); sweep at
  15:00 flipped 0, at 15:30 flipped one (etag 3); `GREATEST` with an earlier instant keeps 15:30;
  renew on `ABORTED` → no row; sweep at +9 days over a `COMMITTING` row → 0. (A first run of the
  sweep case used a sweep instant after the renewed expiry and flipped the row — the fence was
  right, the expectation was not; the re-run above is the receipt.)
- `0009`: plan before, `enable_seqscan = off`: `Seq Scan on ingest_sessions (cost=10000000000…`;
  after: `Index Scan using ingest_sessions_dataset`. Cross-dataset parent: `23503
  ingest_sessions_parent_revision_fk`; NULL parent `UPDATE 1`. CHECKs: `23514
  ingest_files_part_count_matches_action` ×2, `23514 ingest_files_state_vocabulary`. Parts CAS:
  `UPDATE 1`, `UPDATE 0`. After downgrade: no `parent_revision_id`/`part_count` column. The
  applied variant added `part_count` nullable, backfilled by `action`, then `SET NOT NULL`; the
  shipped form is the direct `NOT NULL` add, which differs only on a non-empty table.
- Not run: the migration as an Alembic revision file (the DDL was applied directly); the in-memory
  twin (nothing to prove against PostgreSQL); `FOR UPDATE SKIP LOCKED` (not used — the etag CAS
  makes double sweeps harmless without it).

## Design 4 — The /ingest-sessions HTTP surface

Designed against `main` at `c5e35c7` with Designs 1–3 binding. Pins: `fastapi` 0.141.1,
`starlette` 1.6.0, `asyncer` 0.0.18, `httpx` 0.28.1 (`uv.lock`). Claims marked **proved** were run
(§ Receipts). Two facts found on the way shape the wire: (1) `ingest_files` carries no
`media_type` (`schema.sql:153-164`) while `Manifest.sha256` covers it, so the session's ledger
cannot rebuild the `Manifest` a commit needs — the envelope must carry `manifest.json` from the
moment it is created; (2) the code's action-route convention is a slash sub-resource
(`…/service-accounts/{id}/disable`, `/users/{id}/disable` — live route table, § Receipts), not
`design/api.html`'s `:verb`, and the design follows the code.

### Target design

**Module layout.**

| Module | Change |
|---|---|
| `routes/v1/endpoints/ingest_sessions.py` | new: four routers (`dataset_ingest_sessions`, `project_ingest_sessions`, `router`, `transfer`), nine path operations |
| `routes/v1/schema/ingest_sessions.py` | new: the request bodies and views below |
| `routes/v1/__init__.py` | includes the four routers after `datasets.router` |
| `service/api/ingest.py` | new: `IngestService` (the facade), `SessionLedger` |
| `authorization/guards.py` | + `IngestDrive`, `UploadTarget`, `dataset_raw_writer`, `project_intake`, `session_owner`, `session_overseer`, `upload_owner`; − `LayerWrite`, `dataset_layer_writer` |
| `authorization/__init__.py` | exports follow |
| `runtime.py` | `ApiRuntime` + `ingest: IngestService`; `Ingest = Annotated[IngestService, Depends(api_ingest)]`; `ApiStores` unchanged (D3 (f)) |
| `app.py` | lifespan builds `clock = SystemClock()`, hands it to `_postgres_stores(pool, clock)` and to `IngestService(raw_store, wired.hierarchy, clock=clock)`; the one `PosixRawStore` instance is shared with `HierarchyRepository` |
| `stores/hierarchy.py`, `stores/__init__.py` | `_SystemClock` → `SystemClock`, exported |
| `problems.py` | seventh handler: `ClientDisconnect` → `problem(400, "BAD_REQUEST", …)` (`BAD_REQUEST` is already a wire code via `FRAMEWORK_STATUSES`, no new §7 row) |
| `routes/v1/endpoints/datasets.py`, `schema/datasets.py` | the write-intent stub and its view deleted (§ Deletions) |

**Route table.** Prefix `/api/v1`; the credential requirement and `AUTHENTICATED_ERRORS`
(401/403/422/500) come from the v1 router. "Ops" is the domain/store sequence the facade runs;
every route is `async def`; every blocking call is `await asyncify(...)`. `E` abbreviates the
error-code list that follows the table.

| # | Method, path | Body / headers | Guard | Ops (in order) | Success |
|---|---|---|---|---|---|
| 1 | `POST /datasets/{dataset_id}/ingest-sessions` | `CreateIngestSession`; `Idempotency-Key` | `dataset_raw_writer` | `validate_manifest` → refuse `entry_layer != raw` → parent = `latest_committed_revision` + parent `manifest.json` read-back → `compute_upload_plan` → **tx A** `claim` → `begin_ingest` → `insert_audit_event(ingest.started)` → `remember(Replay("ingest_session", id))` → `create_staging` → `write_document(staging, "manifest.json")` → **tx B** `update_ingest_session(session.open(now), expected_etag=1)` | 201 `IngestSessionView` (state UPLOADING), `ETag` |
| 2 | `POST /projects/{project_id}/ingest-sessions` | `CreateIngestSessionInProject`; `Idempotency-Key` | `project_intake` | `repository.create_dataset(project_id, …, entry_layer="raw", claim=IdempotencyClaim(key=f"{key}/dataset"))` (its own tx — D3 (a)) → then exactly route 1's ops on the created dataset | 201 as route 1 |
| 3 | `GET /ingest-sessions/{session_id}` | — | `session_overseer` | `ingest_session` + `ingest_files` | 200 `IngestSessionView`, `ETag` |
| 4 | `POST /ingest-sessions/{session_id}/heartbeat` | — | `session_owner` | `session.renew(now)` → `renew_ingest_session` | 200 `IngestSessionView`, `ETag` |
| 5 | `PUT /transfer/uploads/{file_id}/parts/{part}` | raw body; `Content-Length` (required) | `upload_owner` | `session.require(UPLOADING, now)` → refuse HARDLINK / COMPLETE / `part ∉ 1..part_count` → derive `offset`, `length` → refuse `Content-Length != length` → `write_part(payload, path, chunks, offset, length)` → `file.part_received(part)` → if `part_count == 1`: `file.completed(length, digest)` (on `ManifestMismatch`: `discard_file`, re-raise) → `update_ingest_file` (re-read + re-apply on `PreconditionFailed`) → `session.renew(now)` → `renew_ingest_session` | 200 `IngestFileView` |
| 6 | `POST /transfer/uploads/{file_id}/complete` | — | `upload_owner` | `session.require(UPLOADING, now)` → refuse unless `file.received` → `finish_file` → `file.completed(size, digest)` (on `ManifestMismatch`: `discard_file`, persist `replace(file, completed_parts=frozenset())`, re-raise) → `update_ingest_file` → `renew` | 200 `IngestFileView` |
| 7 | `POST /ingest-sessions/{session_id}/verify` | — | `session_owner` | `session.require(UPLOADING, now)` → parent = `revision(parent_revision_id)` once → per PENDING HARDLINK file: `hardlink_from_parent` → `file.linked()` → `update_ingest_file` → `session.verify(files, now)` → `update_ingest_session(expected_etag)` | 200 `IngestSessionView` (VERIFYING), `ETag` |
| 8 | `POST /ingest-sessions/{session_id}/commit` | `CommitIngestSession`; `If-Match`; `Idempotency-Key` | `session_owner` | the commit flow below | 201 `RevisionView` (Design 5) |
| 9 | `POST /ingest-sessions/{session_id}/abort` | — | `session_overseer` | **tx** `update_ingest_session(session.abort(), expected_etag)` → `insert_audit_event(ingest.aborted \| ingest.force_aborted)` | 200 `IngestSessionView` (ABORTED), `ETag` |

**Error codes by route** (status · code · condition). Codes common to a guard are listed once.

- *Guards.* `dataset_raw_writer`: 404 `NOT_FOUND` dataset absent/invisible → 403
  `LAYER_WRITE_FORBIDDEN` `ensure_layer_writable(RAW, kind)` (service accounts) → 403 `FORBIDDEN`
  no `data.write@raw` binding. `project_intake`: 404 project → 403 `LAYER_WRITE_FORBIDDEN` → 403
  `FORBIDDEN` (`data.write@raw` at the project scope) → 403 `FORBIDDEN` (`dataset.create`); the
  order puts the kind rule before `dataset.create` so a service account never mints a dataset it
  cannot fill. `session_owner`/`session_overseer`/`upload_owner`: 404 `NOT_FOUND` session or file
  absent, or its dataset invisible → 403 `FORBIDDEN` not the owner (owner routes), or neither owner
  nor `project.update` at the dataset's scope (overseer routes) → 403 `FORBIDDEN` owner whose
  `data.write@raw` was revoked (owner and upload routes only; an owner may always `GET` and abort).
- *Routes 1–2.* 400 `EMPTY_REVISION`, `PATH_OUTSIDE_PAYLOAD`, `PATH_NOT_NFC`, `PATH_TOO_LONG`,
  `PATH_TRAVERSAL`, `PATH_CONTROL_CHARS`, `PATH_SEPARATOR`, `PATH_RULE_VIOLATION` (the manifest
  path rules, from `validate_manifest`); 409 `PATH_COLLISION`; 413 `FILE_TOO_LARGE`,
  `TOO_MANY_FILES`, `REVISION_TOO_LARGE`; 409 `LAYER_WORKFLOW_VIOLATION` dataset's `entry_layer`
  is not `raw` (route 1 only); 409 `DATASET_LOCKED` another non-terminal session (context: holder
  `session_id`, `state`, `expires_at`) or `parent_superseded` after one re-plan (D3 (b)); 409
  `DUPLICATE_CONTENT` the dataset already holds this manifest identity; 409
  `IDEMPOTENCY_KEY_REUSED` same key, different manifest; route 2 also 409 `SLUG_EXISTS` and 400
  `PATH_RULE_VIOLATION` from `create_dataset`. A negative size or a malformed digest is 422
  `REQUEST_INVALID` from the body model (`ge=0`, `pattern=^[0-9a-f]{64}$`), never a `ValueError`
  from the domain.
- *Route 4.* 409 `INGEST_SESSION_EXPIRED` lease lapsed, or terminal (domain or store).
- *Route 5.* 422 `REQUEST_INVALID` missing/non-integer `Content-Length` (a chunked body is
  refused: the part's length must be known before the first byte); 409 `INGEST_SESSION_EXPIRED`;
  409 `ILLEGAL_INGEST_TRANSITION` session not UPLOADING, file is HARDLINK, or file COMPLETE; 404
  `NOT_FOUND` `part` outside `1..part_count`; 400 `MANIFEST_MISMATCH` `Content-Length != length`
  (before the stream opens; context `path`, `part`, `expected_length`, `content_length`),
  `PartLengthMismatch` mid-stream (short or long body; same context with `observed_length`), or —
  single-part files only — the whole-file observation differs from the manifest (D1's context);
  400 `BAD_REQUEST` client disconnected mid-body (`ClientDisconnect`; the ledger is untouched, the
  range stays for the re-send); 412 `PRECONDITION_FAILED` never (the ledger retry absorbs it).
  All refusals except the two mid-stream ones happen before the first chunk is pulled.
- *Route 6.* 409 `INGEST_SESSION_EXPIRED`; 409 `ILLEGAL_INGEST_TRANSITION` not UPLOADING, file
  not fully received, HARDLINK, or already COMPLETE; 400 `MANIFEST_MISMATCH` observation differs
  (the file is discarded and back to PENDING with no parts).
- *Route 7.* 409 `INGEST_SESSION_EXPIRED`; 409 `ILLEGAL_INGEST_TRANSITION` not UPLOADING; 400
  `MANIFEST_MISMATCH` `{"incomplete": [paths]}`; 412 `PRECONDITION_FAILED` the session moved under
  the caller (an admin abort raced; `GET` and retry).
- *Route 8.* 412 `PRECONDITION_FAILED` `If-Match` ≠ `etag` (after the COMMITTED short-circuit);
  422 `REQUEST_INVALID` malformed `If-Match`; 409 `INGEST_SESSION_EXPIRED` lapsed at
  `begin_commit`; 409 `ILLEGAL_INGEST_TRANSITION` not VERIFYING or COMMITTING; 400
  `MANIFEST_MISMATCH` body `manifest_sha256` ≠ session's; Design 5's metadata-document refusal
  (recommended 409 `CONTRACT_MISMATCH`; D5 decides and owns the row flip); 409
  `IDEMPOTENCY_KEY_REUSED` same key, different `(manifest_sha256, content_identity(metadata))`;
  409 `DUPLICATE_CONTENT` from `insert_revision` (unreachable under the allocator, mapped anyway);
  500 `INTERNAL_ERROR` storage and catalog disagree (envelope `manifest.json` ≠
  `session.manifest_sha256`; parent manifest missing) — the reconciler's, not the client's.
- *Route 9.* 409 `ILLEGAL_INGEST_TRANSITION` COMMITTING or terminal; 412 `PRECONDITION_FAILED`
  raced.

Reconciliation: every code above is a `DomainError` class in `pkg/catalog/errors.py`,
`layers.py` or `service/api/errors.py`, or a framework status name, so `wire_error_codes()` and
`test_error_contract.py`'s bijection are unchanged; no new row.

**Schema twin** (`routes/v1/schema/ingest_sessions.py`):

```python
class ManifestFile(BaseModel):
    """One declared file: the manifest entry as the client states it."""
    path: str
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: str = "application/octet-stream"

class CreateIngestSession(BaseModel):
    """Body of ``POST /datasets/{dataset_id}/ingest-sessions``: the files the revision will hold."""
    files: list[ManifestFile]                    # emptiness is the domain's EMPTY_REVISION, not min_length

class NewDataset(BaseModel):
    """The dataset an intake creates before opening its first session; its entry layer is raw by definition."""
    slug: str
    title: str = Field(min_length=1)
    description: str = ""
    profile_name: str
    profile_version: str

class CreateIngestSessionInProject(BaseModel):
    """Body of ``POST /projects/{project_id}/ingest-sessions``: a dataset to create and the files to ingest."""
    dataset: NewDataset
    files: list[ManifestFile]

class CommitIngestSession(BaseModel):
    """Body of ``…/commit``: the declared identity, restated, and the final descriptive metadata document."""
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    metadata: dict[str, object]                  # metadata-v1; Design 5 validates and builds metadata.json

class IngestFileView(BaseModel):
    """One planned file and its progress: the plan (action, part_count) and the ledger (state, parts)."""
    model_config = ConfigDict(from_attributes=True)
    file_id: UUID; path: str; size: int; expected_sha256: str
    action: UploadAction; part_count: int; state: FileState
    completed_parts: list[int]                   # sorted; the resume set is 1..part_count minus this

class IngestSessionView(BaseModel):
    """A session and its ledger; ``etag`` is what ``If-Match`` carries back on commit."""
    model_config = ConfigDict(from_attributes=True)
    id: UUID; dataset_id: UUID; revision_id: UUID; revision_number: int
    state: IngestState; etag: int; expires_at: datetime
    created_by: str; parent_revision_id: UUID | None; manifest_sha256: str
    part_bytes: int                              # PART_BYTES, so the client derives offsets the way the server does
    files: list[IngestFileView]
```

`IngestSessionView.model_validate(ledger)` reads `SessionLedger` (flattened `lease` fields as
properties on it). Every session-view response sets `ETag: "{etag}"` through a `response:
Response` parameter, so `If-Match` round-trips in the form `expected_version()` accepts.

**The facade** (`service/api/ingest.py`), typed against the port (D2's second consumer):

```python
@dataclass(frozen=True, slots=True)
class SessionLedger:
    """One session as last read, with its files in manifest order."""
    session: IngestSession
    files: tuple[IngestFile, ...]
    # id, dataset_id, revision_id, revision_number, state, etag, expires_at, created_by,
    # parent_revision_id, manifest_sha256, part_bytes: read-only properties over `session`

class IngestService:
    """The raw-ingest workflow: sessions, parts, verification and the commit that publishes a revision.

    The opposite discipline from HierarchyRepository: no store transaction is ever held across
    file I/O or hashing; storage leads and the catalog records what is already on disk.
    """
    def __init__(self, raw_store: RawStore, hierarchy: HierarchyStore, *, clock: Clock) -> None: ...
    async def create(self, dataset: Dataset, *, files: Sequence[ManifestEntry], created_by: str, claim: IdempotencyClaim) -> SessionLedger: ...
    async def ledger(self, session_id: UUID) -> SessionLedger: ...
    async def entry(self, file_id: UUID) -> tuple[SessionLedger, IngestFile]: ...
    async def heartbeat(self, session: IngestSession) -> SessionLedger: ...
    async def receive_part(self, ledger: SessionLedger, file: IngestFile, part: int, chunks: Iterable[bytes], *, content_length: int) -> IngestFile: ...
    async def complete_file(self, ledger: SessionLedger, file: IngestFile) -> IngestFile: ...
    async def verify(self, ledger: SessionLedger) -> SessionLedger: ...
    async def commit(self, ledger: SessionLedger, *, expected_etag: int, manifest_sha256: str, metadata: Mapping[str, object], committed_by: str, claim: IdempotencyClaim) -> RevisionRecord: ...
    async def abort(self, ledger: SessionLedger, *, actor: str, forced: bool) -> SessionLedger: ...
```

`PART_BYTES` is read from the module global (`from huron.pkg.catalog import PART_BYTES`) at each
use, so tests patch `huron.service.api.ingest.PART_BYTES` the way `test_execution_model.py`
patches `login.verify_password`. Paths come from `paths.staging_dir(root, ingest_id)` and
`paths.revision_dir(root, organization, project, dataset, number, revision_id)`, with the
organization and project read at `Visibility.ALL` as `create_release` does.

**Guards** (`authorization/guards.py`):

```python
@dataclass(frozen=True, slots=True)
class IngestDrive:
    """Proof that the caller may act on one session: the ledger as read, and whether the caller owns it."""
    principal: Principal
    ledger: SessionLedger
    owner: bool

@dataclass(frozen=True, slots=True)
class UploadTarget:
    """Proof that the caller owns the session one planned file belongs to."""
    principal: Principal
    ledger: SessionLedger
    file: IngestFile

async def _raw_write(cache, repository, principal, scope: Scope) -> None:
    ensure_layer_writable(Layer.RAW, principal.kind)                      # LAYER_WRITE_FORBIDDEN
    capability, layer = required_capability(LayerAction.WRITE, Layer.RAW)
    await check(cache, repository, principal, capability, scope, layer=layer)   # FORBIDDEN

async def dataset_raw_writer(dataset_id: UUID, principal: CurrentPrincipal, repository: Repository, cache: BindingCache, visibility: CurrentVisibility) -> Principal
    # dataset_scope → _raw_write
async def project_intake(project_id: UUID, ...) -> Principal
    # project_scope → _raw_write → check("dataset.create")
async def session_overseer(session_id: UUID, principal, repository, ingest: Ingest, cache, visibility) -> IngestDrive
    # ledger = await ingest.ledger(session_id); scope = dataset_scope(…, ledger.dataset_id, visibility)
    # owner = ledger.created_by == principal.subject; if not owner: check("project.update", scope)
async def session_owner(...) -> IngestDrive
    # session_overseer's resolution, then Forbidden unless owner, then _raw_write
async def upload_owner(file_id: UUID, ...) -> UploadTarget
    # ledger, file = await ingest.entry(file_id); then session_owner's checks
```

**Intake authorization matrix** (the rows are what the guards above produce; `dev` = a human
bound `developer`, `pa` = `project_admin`, `sa` = an organization service account):

| Caller | Route 1 (existing raw dataset) | Route 2 (create at intake) | Why |
|---|---|---|---|
| `dev` at project/org | 201 | 201 | `developer` holds `dataset.create` and `data.write@{raw,bronze}` (`roles.py:198-206`) |
| `pa` | 403 `FORBIDDEN` | 403 `FORBIDDEN` | `project_admin` has `dataset.create` but no `data.write` (`roles.py:226`) — may administer and force-abort, not upload |
| `sa` | 403 `LAYER_WRITE_FORBIDDEN` | 403 `LAYER_WRITE_FORBIDDEN` | `ensure_layer_writable` (`layers.py:225-229`); `SERVICE_ACCOUNT_LAYERS = {silver, gold}` |
| anyone, invisible dataset/project | 404 | 404 | `dataset_scope`/`project_scope` before any binding |
| anyone, dataset with `entry_layer ∈ {bronze, silver}` | 409 `LAYER_WORKFLOW_VIOLATION` | — (route 2 fixes `raw`) | a raw revision of a dataset that declares it has none |

The `ensure_layer_writable` consequence is **not changed here**: an organization service
account cannot open a raw ingest session, and milestone 8's parenthetical ("or an organization
service account, whose dataset-CRUD authority is intrinsic") is true only of the dataset half —
which the existing `POST /projects/{id}/datasets` already grants it. See Open question 1 for the
write-back and the alternative.

**Upload transport: decided.** `PUT /transfer/uploads/{file_id}/parts/{part}` as `api.html:130`
lists it, with parts fixed by the plan at `PART_BYTES = 64 MiB` (D1 OQ2 / D2 OQ2 taken; no
wire-level reason against it was found — one `PUT` per part is exactly the unit a client retries).
Semantics:

- *Range.* `offset = (part - 1) * PART_BYTES`; `length = PART_BYTES` for `part < part_count`,
  `size - offset` for the last; a zero-byte file is one part of length 0 (`Content-Length: 0`,
  `write_part` sees no chunk and returns `sha256(b"")`). `Content-Length` is compared with
  `length` before the stream is opened (D2 (b)); a chunked body has no `Content-Length` and is
  422 by the header's requiredness — **proved** the header is bound before the first chunk.
- *Resumability.* `completed_parts` in `IngestFileView` is the authority; the client re-sends
  `1..part_count − completed_parts` of every file whose `state` is PENDING after any interruption,
  in any order and in parallel across parts and files (the ledger fences per file, D3; the store
  writes disjoint ranges, D2). A re-sent completed part is accepted and overwrites its own range
  (`part_received` is idempotent). Nothing is ever re-sent for a COMPLETE file, and a HARDLINK
  file never receives bytes. Milestone 8's "resumes without re-sending completed parts" is this
  rule at part granularity and the P2 gate's "only incomplete files" is it at file granularity.
- *The bridge.* The route is `async def`; `write_part` runs under `await asyncify(...)` and pulls
  the body through a generator that calls `syncify(request.stream().__aiter__().__anext__)()` per
  chunk on the worker thread (`asyncer` 0.0.18; **proved** it refuses to run on the loop thread
  with `NoEventLoopError`, so the bridge cannot be misplaced silently). Empty chunks are skipped;
  `StopAsyncIteration` ends the iterator; `ClientDisconnect` propagates through `asyncify` into
  the route (**proved**). A body that ends short without a disconnect message ends the iterator
  and is caught by `PartLengthMismatch` (**proved**), so "never ends silently early" holds at the
  route: no short stream is ever reported as success.
- *Memory bound.* Two chunks — the one the ASGI server just handed over and the one the store is
  writing — independent of body size: **proved** peak 2.01 MiB for both 8 MiB and 64 MiB bodies
  in 1 MiB chunks. FastAPI does not read the body eagerly when no `Body` parameter is declared
  (**proved**: a 32 MiB body streamed with an 11 KB peak).
- *Execution-model rule.* Every ingest operation is `async def` (each awaits the store);
  `write_part`, `finish_file`, `discard_file`, `hardlink_from_parent`, `create_staging`,
  `write_document`, `read_document`, `seal` and `commit_envelope` are the nine `asyncify` sites in
  the facade; `test_execution_model.py`'s tripwire gains `write_part` (D2 (e)) and the table gains
  nine handler names and loses `create_write_intent` (60 operations).

**`/commit`, end to end** (`IngestService.commit`; the store sequence is D3's, the disk sequence
D2's):

1. `session.state is COMMITTED` → `return revision(lease.revision_id)` — before `If-Match` and
   before the claim, so a retry whose key lapsed and whose etag is stale still returns the
   revision (D3 (d)). Rendered 201, as `create_dataset`'s replay is.
2. `expected_version(if_match) != session.etag` → `PreconditionFailed`.
3. `now = clock.now()`; read back `staging/manifest.json` → `validate_manifest` (D5's decoder);
   `manifest.sha256 != session.manifest_sha256` → `RuntimeError` (500: storage disagrees with the
   catalog). Build Design 5's `metadata.json` document from `body.metadata`, `manifest`, the
   hierarchy names, `committed_by`, `now` — its refusal is raised here, before any edge.
4. `committing = session.begin_commit(manifest_sha256=body.manifest_sha256, now=now)` —
   VERIFYING → COMMITTING, or the COMMITTING → COMMITTING re-entry against the current etag (Open
   question 3); one transaction: `update_ingest_session(committing, expected_etag=session.etag)`.
5. `published = read_document(final / "COMMITTED")` or `None`. If `None`: D2's six steps —
   `write_document` ×2 (manifest.json again, identical bytes; metadata.json), `seal`,
   `write_document(COMMITTED)`, `commit_envelope` — then `record = revision_record(committing,
   manifest, metadata_sha256=…, revision_path=str(final), committed_by, committed_at=now)`. If
   present (a retry past the rename): `record` is built by Design 5's read-back of `COMMITTED` and
   `metadata.json` (D2 OQ1 as D3 resolved it). On any exception: if `final/COMMITTED` is still
   absent, persist `committing.fail()` + `ingest.failed` in one transaction and re-raise; if it
   is present, re-raise leaving COMMITTING for the client's retry (D3 (d)).
6. The six-statement transaction: `claim` (a `Replay("revision", id)` → `return revision(id)`;
   a digest mismatch → `IdempotencyKeyReused`) → `insert_revision` → `update_ingest_session(
   committing.commit(), expected_etag=committing.etag)` → `insert_audit_event(revision.committed)`
   → `insert_outbox_event(revision_committed(record, event_id=uuid7(), created_at=now))` →
   `remember`.
7. 201 `RevisionView.model_validate(record)`.

`Idempotency-Key` stays on `/commit` (D3 OQ2 taken): its claim digest is
`request_sha256("revision", str(session_id), manifest_sha256, content_identity(metadata))`, so a
retry that changed the metadata is refused rather than silently publishing the first document's
digest under the second body. Cost accepted: that refusal lands after the file steps (the claim
is inside the final transaction by D3's order), and the replaced documents are rewritten by the
corrected retry.

**Route 2's two claims.** One `Idempotency-Key` header, two idempotent writes: the dataset is
created under `IdempotencyClaim(principal, key=f"{key}/dataset", request_sha256("dataset", …))`
and the session under `IdempotencyClaim(principal, key, request_sha256("ingest_session",
str(dataset.id), manifest.sha256))`. The derived key is deterministic, so a retry after a failure
between the two writes replays the dataset creation (returns the kept, empty dataset — S7a) and
then opens the session; a retry with a different manifest replays the dataset and is refused at
the session claim. Two claims cannot share one `(principal, key)`: the second would see the
first's digest and raise `IdempotencyKeyReused`.

**Facade decision.** A sibling service, not new methods on `HierarchyRepository`.
`API_DESIGN.md` § "Design 3" concluded that `repository.py` is only `HierarchyRepository` and its
private helpers, that the decomposition's invariant is import direction (records ← ports ←
adapters ← the service, with only `app.py`, `runtime.py`, `authorization` and the routes
importing the service), and that `HierarchyRepository`'s stated invariant is "a write is one
store transaction … the row first, then its durable document, both before the transaction
commits" (`repository.py:79-93`). D3 decided the revision commit follows the opposite discipline
(`layer-raw` §3: no transaction across file I/O). Putting both under one class makes its
docstring false for half its methods and grows a 1,217-line module by the largest workflow in
the tier; `IngestService` sits beside it under the same import rules (`pyproject.toml:233-254`
gains `huron.service.api.ingest` in the stores contract's `source_modules`), takes the same
`HierarchyStore` (D3 (f): no new store, `ApiStores` unchanged) and the same `RawStore` instance,
and is reached the same way (`runtime.Ingest`). Dataset creation at intake stays on
`HierarchyRepository` — it is a hierarchy write with the hierarchy's discipline.

**§7 disposition column — definition and write-back (Drift 8).** Sentence to insert above the
table at `design/api.html:213`: *"`live` means at least one shipped path operation can answer with
the code; `reserved` means the code is part of the contract but no shipped route raises it yet."*
Mechanically, `test_error_contract.py` asserts the necessary condition: a `live` row's class has
at least one `raise` site under `src/huron` (an `ast` walk over `Raise` nodes naming the class)
and a `reserved` row's has none (§ Tests). Rows to flip `reserved` → `live`: `MANIFEST_MISMATCH`
(routes 5, 6, 7, 8), `INGEST_SESSION_EXPIRED` (4, 5, 6, 7, 8), `DATASET_LOCKED` (1, 2),
`DUPLICATE_CONTENT` (1, 2, 8). Meaning cells: `INGEST_SESSION_EXPIRED` → "ingest session passed
its idle TTL, or is terminal and cannot be renewed (§3 ingest)" (D1 OQ4: "or absolute" dropped).
No other row changes; `ILLEGAL_INGEST_TRANSITION` becomes truthfully `live`. `CONTRACT_MISMATCH`
flips only if Design 5 chooses it for the metadata document.

**§3 write-back.** The `POST /ingest-sessions` row becomes two rows —
`POST /datasets/{id}/ingest-sessions` "body: manifest → session with `UploadPlan` (files: `upload |
hardlink`, `part_count`, `part_bytes`); locks the dataset; `Idempotency-Key`" and
`POST /projects/{id}/ingest-sessions` "creates the dataset (raw entry) under `dataset.create` +
`data.write@raw`, then as above"; the metadata draft leaves the create body (D1 OQ3);
`:heartbeat`/`:verify`/`:commit`/`:abort`/`:complete` become `/heartbeat` … `/complete` (the
code's action-suffix form); the parts row gains "`Content-Length` must equal the part's planned
length; parts are 64 MiB; `completed_parts` in `GET` is the resume set"; the commit row's body
becomes `{manifest_sha256, metadata}`.

**The write-intent stub: deleted.** `POST /datasets/{id}/layers/{layer}/write-intents` persists
nothing and mints nothing (Current State); its docstring's consumer — "the ingest/commit
machinery … hang their work off this authorization" — is this design, and it hangs off the guard
directly, per request, so a revoked binding takes effect on the next part rather than surviving
in an unexpiring intent. `design/api.html` never lists the route. Its only other value, pinning
the human/service-account layer rule over HTTP, is kept by `list_layers`'s `caller_may.write`
(the same `decide` call, already asserted at `test_api_catalog_hierarchy.py:880-896`) and by the
new 403s on routes 1–2.

### Explicit contracts

**Invariants the surface holds.**

- A response body is never built from state the domain lacks: views render `SessionLedger`
  (`IngestSession` + `IngestFile`s) and `RevisionRecord` only; `part_bytes` is the one echoed
  constant.
- `ETag` is `session.etag`; `If-Match` is accepted on `/commit` only, in the three forms
  `expected_version()` parses; a stale etag is 412 unless the session is already COMMITTED.
- Every check that can refuse an upload runs before the first chunk is pulled, except the two
  mid-stream conditions (short/long body, disconnect); a refused or interrupted part leaves the
  ledger unchanged and the envelope's range in place for the re-send.
- No store transaction is open while `write_part`, `finish_file`, `hardlink_from_parent`, any
  `write_document`, `seal` or `commit_envelope` runs (D3); the hierarchy's own writes keep their
  own discipline.
- The owner drives; `project.update` at the dataset's scope may read and abort; nobody else sees
  more than 404/403.
- Audit rows: `ingest.started` (route 1/2, tx A), `ingest.aborted` (owner) / `ingest.force_aborted`
  (admin), `ingest.failed` (create's staging failure; commit's pre-rename failure),
  `revision.committed` (`subject_kind = "revision"`); `actor = principal.subject`. `ingest.expired`
  is Design 6's.

**Lifecycle.** `IngestService` is built once in the lifespan, after `HierarchyRepository` (which
runs `raw_store.initialize()`), over the same `PosixRawStore` instance; it holds no state beyond
its three collaborators. A staging envelope is never deleted by this tier (P3's sweeper).

**Requirements on the other designs.**

- **Design 5 (documents and the read side).** (a) `RevisionView` in `routes/v1/schema/revisions.py`
  with `model_config = ConfigDict(from_attributes=True)` and at least `id`, `dataset_id`,
  `number`, `manifest_sha256`, `metadata_sha256`, `file_count`, `total_bytes`, `committed_by`,
  `committed_at`; **not** `revision_path` (a filesystem location is not wire contract). Route 8
  imports it; the plan orders D5's schema module before route 8. (b) Three pure functions the
  facade calls: `manifest_bytes(manifest) -> bytes` (canonical `Manifest.as_dict()`; written at
  create and again at commit step 1), `decode_manifest(payload: bytes) -> Manifest` (through
  `validate_manifest`, used for the parent at create/verify and for the session's own envelope at
  commit), and `metadata_document(metadata: Mapping[str, object], *, manifest, organization,
  project, dataset, committed_by, committed_at) -> tuple[bytes, str]` returning the canonical bytes
  and their `content_identity`; it raises one named `DomainError` for an invalid document — this
  design recommends `CONTRACT_MISMATCH` (409) and D5 flips its §7 row. (c) `committed_bytes(record)`
  and `revision_from_storage(committed: bytes, metadata: bytes, session) -> RevisionRecord` for
  the read-back retry. (d) The download routes are D5's; the `data.read@raw` check they need is the
  `_raw_write` shape with `LayerAction.READ`.
- **Design 6 (sweep).** `create_app` may grow a `clock: Clock | None` parameter if the sweep's
  tests need to drive time through the app; this design's tests do not (they seed a lapsed
  `expires_at` on the in-memory store). The `SystemClock` instance in the lifespan is the one to
  share. `ingest.expired` is the sweep's audit kind; the sweep never touches a route.
- **Design 7 (suites).** The tests in § Tests are `unit` over `TestClient` + `memory_stores()`;
  the racing-`begin_ingest` proof is D3's contract test; the crash matrix uses D2's `crash_on`
  against `IngestService.commit` through the route; the 9 GiB clause is exercised at
  `PART_BYTES` patched small, and the real constant only in the acceptance suite.

### Deletions

- `src/huron/service/api/routes/v1/endpoints/datasets.py`: `create_write_intent` (`:436-471`),
  the imports `LayerWrite`, `dataset_layer_writer`, `WriteIntent`, and the module docstring's
  write-intent sentence (`:6-8`).
- `src/huron/service/api/routes/v1/schema/datasets.py`: `WriteIntent` (`:124-131`).
- `src/huron/service/api/authorization/guards.py`: `LayerWrite` (`:225-236`),
  `dataset_layer_writer` (`:239-279`); `authorization/__init__.py`: their two exports.
- `src/huron/service/api/stores/hierarchy.py`: the name `_SystemClock` (becomes `SystemClock`).
- `src/huron/service/api/problems.py:98` "six handlers" and `tests/unit/test_error_contract.py:5`
  "all six" (seven).
- `tests/unit/test_api_catalog_hierarchy.py:899-925` (the write-intent test);
  `tests/unit/test_api_rbac.py:122-137, 171-176` (the four write-intent probes — replaced by the
  route-1 assertions in § Tests); `tests/unit/test_execution_model.py:74`
  (`"create_write_intent": True`).
- `design/api.html:130-132`'s `:verb` spellings and `:127`'s "metadata draft" (write-back above).
- Nothing in `errors.py`, `records.py`, `repository.py` or `runtime.py`'s existing members.

### Data flow

```mermaid
sequenceDiagram
    participant C as Client
    participant R as PUT …/parts/{n} (async def, loop thread)
    participant G as upload_owner
    participant W as worker thread (asyncify)
    participant S as PosixRawStore
    participant DB as HierarchyStore
    C->>R: PUT body, Content-Length
    R->>G: file_id → ledger, file · owner ∧ data.write@raw
    G-->>R: UploadTarget (or 404 / 403)
    R->>R: require(UPLOADING) · action/state/part checks · offset,length · Content-Length == length
    R->>W: asyncify(write_part)(payload, path, chunks, offset, length)
    loop one chunk at a time (bound: 2 chunks)
        W->>R: syncify(stream.__anext__)()  — anyio.from_thread.run on the loop
        R-->>W: chunk (ClientDisconnect → raises on W → propagates to R → 400)
        W->>S: pwrite + sha256
    end
    S-->>R: digest (PartLengthMismatch → 400 MANIFEST_MISMATCH, ledger untouched)
    R->>R: file.part_received(n) [· completed(length, digest) if part_count == 1]
    R->>DB: update_ingest_file(expected_parts = stored)
    DB-->>R: ok, or PreconditionFailed → re-read, re-apply, retry
    R->>DB: renew_ingest_session(session.renew(now))
    R-->>C: 200 IngestFileView
```

```mermaid
sequenceDiagram
    participant C as Client
    participant R as POST …/commit
    participant F as IngestService.commit
    participant DB as HierarchyStore
    participant S as PosixRawStore (asyncify)
    C->>R: {manifest_sha256, metadata} · If-Match · Idempotency-Key
    R->>F: session_owner → ledger
    F->>DB: COMMITTED already? → revision(revision_id) → 201
    F->>F: If-Match == etag? (412) · read back staging/manifest.json · build metadata.json (D5)
    F->>DB: tx: update_ingest_session(begin_commit → COMMITTING, expected_etag)
    F->>S: final/COMMITTED present?
    alt absent — first attempt or retry before the rename
        F->>S: write_document ×2 · seal · write_document(COMMITTED) · commit_envelope
        Note over S: rename → fsync(parent) — durability point
        F->>F: record = revision_record(committing, manifest, …, committed_at = now)
    else present — retry after the rename
        F->>S: read_document(COMMITTED), read_document(metadata.json)
        F->>F: record = revision_from_storage(…)
    end
    Note over F,S: any raise with COMMITTED absent → tx: fail + ingest.failed; present → leave COMMITTING
    F->>DB: tx: claim (replay → revision) · insert_revision · update(commit, expected_etag) · audit · outbox · remember
    F-->>R: RevisionRecord
    R-->>C: 201 RevisionView
```

### Rejected alternatives

- **One `POST /ingest-sessions` with a discriminated body (`dataset_id` | `project_id + dataset`)**
  — the guard would have to declare the body model to authorise before the route runs, coupling
  `authorization` to a schema module (inverting the routes → authorization import direction);
  two parent-scoped creating routes are the tier's own template (`project_datasets` + `router`).
- **A per-file streamed `PUT` (whole file, one part)** — makes a 9 GiB interruption a restart from
  zero and, with `O_EXCL` gone, buys nothing the range write does not; the design's range
  arithmetic is the same code path with `part_count == 1`.
- **Keep the write-intent stub as a "pre-flight" for clients** — `GET /datasets/{id}/layers`
  already answers "may I write raw?" and an unpersisted intent is a promise the ingest routes do
  not honour.

### Open questions

1. **Service accounts and `raw`.** Milestone 8 (`roadmap.html:559-566`) reads as if an
   organization service account can drive intake; `ensure_layer_writable` and
   `SERVICE_ACCOUNT_LAYERS` (`roles.py:41-44`, pinned by `test_api_rbac.py:171-176`) say raw and
   bronze are the human contribution surface. *Recommended:* keep the rule — the RBAC boundary is
   deliberate and tested, `/ingest-sessions` is raw-only by definition, and a feed's real intake
   is a `silver`/`bronze`-entry dataset the existing create route already lets it mint — and
   write back milestone 8's parenthetical to "humans with `dataset.create` and `data.write@raw`;
   an organization service account may mint the dataset but cannot upload to `raw`". The
   alternative is widening `SERVICE_ACCOUNT_LAYERS` to include `raw` (a one-set change plus two
   test flips), which is an RBAC policy decision this design should not make.
2. **The derived dataset claim key (`f"{key}/dataset"`) on route 2.** *Recommended:* take it —
   it is the only way one client key makes both writes idempotent under the store's
   `(principal, key)` ledger without a resolve-by-slug heuristic. The alternative is no claim on
   the dataset half: a retry after a failure between the writes then gets `SLUG_EXISTS` and must
   switch to route 1 with the kept dataset's id — honest but a worse client story.
3. **COMMITTING → COMMITTING re-entry (adopting D1 Open question 1).** Routes 8's step 4 needs
   `begin_commit` to accept COMMITTING as a source (same digest check, `etag + 1`) so a retry
   after a crash past the rename can re-fence and run step 5's read-back branch. *Recommended:*
   adopt it as a one-line addition to D1's `TRANSITIONS` (`COMMITTING: {COMMITTING, COMMITTED,
   FAILED}`) carried by the plan; D2 and D3 already assume it. Without it a crash in that window
   holds the dataset lock until P3's reconciler, which D1 OQ1 named as the fallback.

### Tests

`tests/unit/test_api_ingest_sessions.py` (`pytest.mark.unit`; `client`/`stores` fixtures as
`test_api_catalog_hierarchy.py:71-89`; helpers `_developer_dataset(client) -> (project_id,
dataset_id)` binding `bob` as `developer`, `_manifest(*files)`, `_session(client, dataset_id,
files, subject="bob")`, `_put_part(client, file_id, part, payload)`, `_commit(client, session_id,
etag, metadata)`; multipart tests `monkeypatch.setattr(ingest_module, "PART_BYTES", 4)`; lapsed
sessions are seeded by rewriting `expires_at` on the in-memory store's row):

| Test | Asserts |
|---|---|
| `test_create_returns_the_plan_and_locks_the_dataset` | 201; `state == "UPLOADING"`, `etag == 2`, `part_bytes == PART_BYTES`, one `IngestFileView` per file with `action`, `part_count`, `state == "PENDING"`, `completed_parts == []`; `ETag: "2"`; a second create on the dataset → 409 `DATASET_LOCKED` with the holder in `context` (the racing-sessions gate, serial in memory) |
| `test_create_replays_under_the_same_key_and_refuses_a_changed_manifest` | same key + same body → 201 same `id`; same key + different file → 409 `IDEMPOTENCY_KEY_REUSED` |
| `test_create_refuses_a_manifest_the_dataset_already_holds` | after a commit, the same files → 409 `DUPLICATE_CONTENT` |
| `test_create_refuses_every_manifest_rule_with_its_documented_code` | parametrized over `[]` → `EMPTY_REVISION`; `x` → `PATH_OUTSIDE_PAYLOAD`; NFD → `PATH_NOT_NFC`; 1025-byte path → `PATH_TOO_LONG`; `payload/a/../b` → `PATH_TRAVERSAL`; `payload/a\x01` → `PATH_CONTROL_CHARS`; `payload/a\\b` → `PATH_SEPARATOR`; `payload/A` + `payload/a` → `PATH_COLLISION`; oversize → `FILE_TOO_LARGE`; 10,001 files → `TOO_MANY_FILES`; > 1 TiB → `REVISION_TOO_LARGE`; the rule's status and code from `context`/body |
| `test_create_refuses_a_dataset_whose_entry_layer_is_not_raw` | `entry_layer: "bronze"` dataset → 409 `LAYER_WORKFLOW_VIOLATION` |
| `test_create_in_project_mints_the_dataset_then_opens_the_session` | 201; the dataset exists with `entry_layer == "raw"` and `slug`; a retry with the same key → same session; the same key with another manifest → 409 `IDEMPOTENCY_KEY_REUSED` and no second dataset |
| `test_intake_authorization_matrix` | parametrized: developer 201/201; project_admin 403 `FORBIDDEN`/403 `FORBIDDEN`; service account (API key) 403 `LAYER_WRITE_FORBIDDEN` on both; unbound user 403; invisible dataset/project 404 |
| `test_get_shows_progress_and_the_etag` | 200 body equals the create view; `ETag` header; a non-owner without `project.update` → 403; a project admin → 200; unknown id → 404 |
| `test_heartbeat_moves_the_lease_and_not_the_etag` | `expires_at` later, `etag` unchanged; lapsed → 409 `INGEST_SESSION_EXPIRED`; aborted → 409 `INGEST_SESSION_EXPIRED` |
| `test_a_single_part_upload_completes_the_file` | `PUT` part 1 with matching bytes → 200 `state == "COMPLETE"`, `completed_parts == [1]`; the session's `expires_at` moved |
| `test_a_multipart_upload_resumes_without_resending_completed_parts` | 3 parts (size 10, `PART_BYTES` 4): parts 3 and 1 → `[1, 3]`; `GET` shows PENDING; part 2 → `[1, 2, 3]`; `/complete` → COMPLETE; a re-sent part 2 after completion → 409 `ILLEGAL_INGEST_TRANSITION` |
| `test_an_upload_refuses_a_content_length_that_disagrees_with_the_plan_before_reading` | `Content-Length` off by one → 400 `MANIFEST_MISMATCH` with `expected_length`; ledger unchanged; a missing header → 422 |
| `test_a_short_body_is_a_manifest_mismatch_and_leaves_the_part_pending` | generator body ending early → 400 `MANIFEST_MISMATCH` (`observed_length`); `completed_parts` unchanged; the re-send succeeds |
| `test_a_mismatched_single_part_file_is_discarded_and_back_to_pending` | wrong bytes → 400 `MANIFEST_MISMATCH` with `observed_sha256`; the payload file is absent on disk; the correct re-send → COMPLETE |
| `test_a_mismatched_multipart_file_is_discarded_at_complete` | parts assembled from wrong bytes → `/complete` 400; `completed_parts == []`; file absent; full re-send then `/complete` → COMPLETE |
| `test_upload_refusals_happen_before_the_body_is_read` | part 0 and `part_count + 1` → 404; a HARDLINK file → 409 `ILLEGAL_INGEST_TRANSITION`; a VERIFYING session → 409; a lapsed session → 409 `INGEST_SESSION_EXPIRED`; another user → 403; a revoked developer → 403 — each with a body-tracking generator that was never iterated |
| `test_a_client_disconnect_mid_part_answers_400_and_keeps_the_ledger` | a raw ASGI drive with `http.disconnect` after one chunk → 400 `BAD_REQUEST`; `completed_parts` unchanged |
| `test_verify_links_parent_files_and_moves_to_verifying` | second session against a committed parent with one unchanged file: plan `hardlink`/`part_count 0`; `/verify` with the upload file COMPLETE → 200 VERIFYING, HARDLINK file COMPLETE, `nlink == 2` on disk; a retry of `/verify` after an injected `os.link` failure (`crash_on`) links the remainder |
| `test_verify_refuses_while_a_file_is_pending` | 400 `MANIFEST_MISMATCH` with `context["incomplete"] == [path]`; state unchanged |
| `test_commit_publishes_the_revision_and_its_events` | 201 `RevisionView` (`number == 1`, `manifest_sha256`, `metadata_sha256`, `file_count`, `total_bytes`, `committed_by == "bob"`); on disk `…/raw/revision/000001--{hex}/{COMMITTED,manifest.json,metadata.json,payload/…}`, staging gone, root `0o555`; store: session COMMITTED, one `revision.committed` audit row and one outbox row, `GET /datasets/{id}/releases` can tag revision 1 |
| `test_commit_requires_the_current_etag_and_the_declared_digest` | stale `If-Match` → 412; malformed → 422; another `manifest_sha256` → 400 `MANIFEST_MISMATCH`; from UPLOADING → 409 `ILLEGAL_INGEST_TRANSITION`; lapsed VERIFYING → 409 `INGEST_SESSION_EXPIRED` |
| `test_a_replayed_commit_returns_the_same_revision` | second `/commit` with the same key, stale `If-Match` → 201 same `id`; a different `metadata` with the same key on a not-yet-committed retry → 409 `IDEMPOTENCY_KEY_REUSED` |
| `test_a_commit_retry_after_a_crash_past_the_rename_completes_the_catalog` | `crash_on("fsync", call=<the parent fsync>)` → 500; session COMMITTING; retry with the new etag → 201; the record's `committed_at` equals `COMMITTED`'s; one revision row |
| `test_a_commit_failure_before_the_rename_fails_the_session` | `crash_on("rename")` → 500; session FAILED; `ingest.failed` audited; a new session re-takes number 1 |
| `test_abort_releases_the_lock_for_the_owner_and_a_project_admin` | owner → 200 ABORTED + `ingest.aborted`; a new session → 201 number 1; admin on another's session → 200 + `ingest.force_aborted`; a developer who is not the owner → 403; from COMMITTING (seeded) → 409 `ILLEGAL_INGEST_TRANSITION`; from ABORTED → 409 |
| `test_every_session_route_hides_an_invisible_dataset` | a `restricted`-classified project's session → 404 on routes 3–9 for a user outside it |

`tests/unit/test_api_rbac.py` (the four write-intent probes become): `bob` → route 1 201;
`alice` (org admin, no write) → 403 `FORBIDDEN`; the service account → 403
`LAYER_WRITE_FORBIDDEN`, while `list_layers` still reports `caller_may.write` true for `silver`
and `gold` only.

`tests/unit/test_execution_model.py`: `EXPECTED_COROUTINE_FUNCTION` gains
`create_dataset_ingest_session`, `create_project_ingest_session`, `get_ingest_session`,
`heartbeat_ingest_session`, `upload_part`, `complete_upload`, `verify_ingest_session`,
`commit_ingest_session`, `abort_ingest_session` and loses `create_write_intent` (60);
`test_the_upload_route_s_write_part_executes_off_the_event_loop_thread` (D2's name) patches
`PosixRawStore.write_part` with a tracking wrapper, drives one `PUT`, asserts
`ran_on_the_event_loop == [False]`; `test_the_commit_route_s_envelope_publication_executes_off_the_event_loop_thread`
does the same for `commit_envelope`.

`tests/unit/test_error_contract.py`: `test_live_rows_have_a_raise_site_and_reserved_rows_have_none`
— `ast` walk of `src/huron` collecting the names in every `Raise` node's call; every `live` row
whose code is a `DomainError` class name has one, every `reserved` row has none.

### Receipts

`uv run python scratchpad/d4_stream_proofs.py` and a follow-up driver at `c5e35c7` (FastAPI
0.141.1, Starlette 1.6.0, asyncer 0.0.18 — printed by the script):

- A `PUT` handler with no `Body` parameter, `request.stream().__aiter__().__anext__` wrapped in
  `syncify` inside an `asyncify`'d consumer: 32 MiB in 1 MiB pre-allocated chunks → `written
  33554432`, consumer-side `tracemalloc` peak **11,472 B**; `content_length` logged before the
  first chunk. With chunks allocated lazily in `receive()` (`os.urandom`): 8 × 1 MiB → peak
  **2.01 MiB**, 64 × 1 MiB → peak **2.01 MiB** (bound = two chunks, not the body).
- `http.disconnect` after two chunks with `Content-Length` 8 MiB → `ClientDisconnect` raised in
  the consumer thread and propagated out of the ASGI call (`consumer_raised ClientDisconnect`).
- `more_body=False` after 2 MiB of a declared 8 MiB → the iterator ended, consumer reported
  `written 2097152` — the length check (`PartLengthMismatch`) is what refuses it.
- `TestClient`: 3 MiB bytes body and a generator body both 200 with the right digest; `httpx`
  `ASGITransport`: 200. `syncify(...)()` on the loop thread → `NoEventLoopError`.
- Live route table from `create_app(...)` with `memory_stores()`: 52 operations; action routes are
  `…/service-accounts/{principal_id}/disable`, `/users/{principal_id}/disable`; no ingest or
  transfer path; `/api/v1` prefix confirmed absent on `/healthz`, `/readyz`, `/login`.
- `grep`: `ingest_files` columns in `schema.sql:153-164` — no `media_type`; `raise` sites for the
  §7 reserved rows under `src/huron` — none (only `AmendmentFieldForbidden`, a `live` row, has
  two); `BAD_REQUEST` documented once in `design/api.html`.
- Not run: the guards against a real `RoleBindingAuthorizer` decision (read from
  `decisions.py:151-192`, `roles.py:198-230`); anything against PostgreSQL; a real server's
  behaviour on a truncated `Content-Length` body (uvicorn/h11 surfaces it as `http.disconnect`
  by protocol, taken from the ASGI spec, not proved here); FastAPI's handling of a body-declaring
  dependency (not needed after the two-route decision).

## Design 5 — Revision documents on disk and download capabilities

Designed against `main` at `c5e35c7` with Designs 1–4 binding (pins: `fastapi` 0.141.1,
`starlette` 1.6.0, `jsonschema` 4.26.0, `rfc8785` 0.1.4). Claims marked **proved** were run
(§ Receipts). Three of them shape what follows: (1) the stored JCS bytes of a document hash to its
`content_identity` — `sha256(canonical_bytes(doc)) == content_identity(doc)` — so a reader
rehashes stored bytes directly, as `layer-raw.html:208` promises; (2) `metadata-v1.json`'s
`format: date-time` assertion is **silently unenforced** in this environment (no
`rfc3339-validator` is installed, so `FormatChecker` skips it) while `format: uuid` is enforced —
`committed_at` is therefore server-generated by construction, never trusted to the schema; (3) the
filesystem serves an NFD spelling of an NFC path (APFS normalises) and `FileResponse` raises after
the handler returned when its file is missing — so the download route's path rule and its stat
are the route's own, run before any response object exists.

`CLAUDE.md` § Code Design is applied as follows: the four documents are structural value objects
(frozen, slotted) whose only constructors are creational classmethods that validate (`compose`,
`decode`, `of`, `including`), so an instance always conforms to its schema and the canonical bytes
and identity are properties of it, never recomputed by a caller; the behavioural seam is one
service class (`RevisionService`) the routes call; nothing wraps `FileResponse`.

### Target design

**Module layout.**

| Module | Change |
|---|---|
| `pkg/catalog/documents.py` | new: `manifest_bytes`, `decode_manifest`, `MetadataDocument`, `CommitRecord`, `RevisionIndex`, `IndexEntry`, `revision_from_storage`; the two instant helpers (`Z`-suffixed render, tz-aware parse) |
| `pkg/catalog/__init__.py` | re-exports the seven names above |
| `schema/documents/committed-v1.json`, `schema/documents/revision-index-v1.json` | new; `manifest-v1.json` and `metadata-v1.json` unchanged |
| `service/api/revisions.py` | new: `RevisionService`, `PayloadFile` — the read side |
| `service/api/runtime.py`, `app.py` | `ApiRuntime.revisions: RevisionService`; `Revisions = Annotated[RevisionService, Depends(api_revisions)]`; lifespan builds `RevisionService(raw_store, wired.hierarchy)` over the shared `PosixRawStore` |
| `authorization/guards.py`, `authorization/__init__.py` | + `RevisionRead`, `revision_raw_reader` |
| `routes/v1/schema/revisions.py` | new: `MetadataSubmission`, `RevisionView` (Design 4's route 8 imports `RevisionView`; its `CommitIngestSession.metadata` becomes `MetadataSubmission`) |
| `routes/v1/endpoints/revisions.py`, `routes/v1/__init__.py` | new router `/revisions`, three path operations, included after `datasets.router` |
| `problems.py` | `FRAMEWORK_STATUSES = (400, 404, 405, 416)` — `FileResponse` answers an unsatisfiable `Range` itself (below) |
| `pyproject.toml` | `huron.service.api.revisions` joins the stores-contract `source_modules` beside Design 4's `huron.service.api.ingest` |

`huron.schema` gains its first two callers in `src/` (`pyproject.toml:193-194` already says
"catalog validates against it"): `decode_manifest` and `MetadataDocument.compose`/`decode`.
Without the P5 registry, P2 validates against the packaged platform-scope documents by file name —
`manifest-v1.json`, `metadata-v1.json`, `committed-v1.json`, `revision-index-v1.json` — and the
document's own `schema` member is "the exact schema reference it validated against"
(`layer-raw.html:201`); there is no organization or project enrichment to compose, so no `allOf`.

**The four documents.** Every one is written as `canonical_bytes(doc)` (RFC 8785; convention 9)
and decoded by a classmethod that refuses bytes which are not their own canonical form
(`canonical_bytes(json.loads(payload)) != payload` → `ValueError`), so a hand-edited or
pretty-printed file is detected at first read rather than silently re-identified.

| Document | `$id` | Members and their source at intake | Write primitive (Design 2) and step |
|---|---|---|---|
| `manifest.json` | `urn:huron:manifest:1` (existing) | `Manifest.as_dict()` — `schema` const, `hash_algorithm` `"sha256"`, `files[{path, size, sha256, media_type}]` in path order, from the `Manifest` `validate_manifest` built at create | `write_document(staging, "manifest.json", manifest_bytes(m))` at create (Design 4 route 1) and again at commit **step 1** with identical bytes; `sha256(bytes) == m.sha256 == session.manifest_sha256` |
| `metadata.json` | `urn:huron:metadata:1` (existing) | the table below | `write_document(staging, "metadata.json", doc.canonical)` at **step 1**, after the manifest; `metadata_sha256 = doc.sha256` |
| `COMMITTED` | `urn:huron:committed:1` (new) | `CommitRecord.of(record)`: every `RevisionRecord` field except `revision_path` | `write_document(staging, "COMMITTED", CommitRecord.of(record).canonical)` at **step 3**, after `seal` (step 2), before `commit_envelope` (steps 4–6) |
| `INDEX.json` | `urn:huron:revision-index:1` (new) | `RevisionIndex.decode(existing) or .empty(dataset_id)`, then `.including(record)` | `atomic_replace(PurePosixPath(record.revision_path).parent / "INDEX.json", index.canonical)` at **step 8**, after the PostgreSQL transaction, best-effort — Open question 1 |

Sealing's place is Design 2's and taken as given: contents at step 2 (so the three documents and
the payload are `0o444` before the marker says the envelope is complete), root after the rename.

**`metadata-v1` required members, sourced.** The submission is the client's half; everything
else is the server's. A submission member the server owns is refused at the wire (422, the body
model forbids it) and, independently, by `compose` (`ValueError`, a caller bug).

| Member | Required | Source |
|---|---|---|
| `schema` | yes | constant `urn:huron:metadata:1` |
| `organization`, `project`, `dataset` | yes | `{id: str(uuid), slug}` from the three hierarchy records the facade reads at `Visibility.ALL` for the path (`create_release`'s pattern, `repository.py:625-629`); the records satisfy `paths.Slugged` |
| `revision_number` | yes | `session.lease.revision_number` |
| `title` | yes | submission (`minLength 1` is the schema's) |
| `creators` | yes | submission (`minItems 1` is the schema's) |
| `committed_by` | yes | the principal driving `/commit`, `actor.subject` — the same value `revision_record` receives |
| `committed_at` | yes | the one `Clock.now()` taken at `begin_commit`, rendered `isoformat()` with `+00:00` → `Z` — the same instant `revision_record` and `COMMITTED` carry |
| `data_classification` | yes | **Open question 3** — recommended `project.data_classification` (server-sourced); alternative: a submission member |
| `manifest_sha256` | yes | `manifest.sha256` of the envelope's `manifest.json` read back at commit (equal to `session.manifest_sha256` by Design 4 step 3) |
| `description`, `tags`, `source`, `coverage`, `extensions` | no | submission, present only when sent (`exclude_none`); `extensions` is stored verbatim — unknown namespaces are preserved, not rejected (`layer-raw.html:202`) |

No required member is unsourceable. `format: date-time` being unenforced (Open question 4) does
not weaken this: the server writes the instant.

**Schema fragments** (Draft 2020-12, `additionalProperties: false`, all listed members required).

```json
{ "$id": "urn:huron:committed:1",
  "required": ["schema", "revision_id", "dataset_id", "revision_number", "manifest_sha256",
               "metadata_sha256", "file_count", "total_bytes", "committed_by", "committed_at"],
  "properties": {
    "schema": {"const": "urn:huron:committed:1"},
    "revision_id": {"type": "string", "format": "uuid"},
    "dataset_id": {"type": "string", "format": "uuid"},
    "revision_number": {"type": "integer", "minimum": 1, "maximum": 999999},
    "manifest_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    "metadata_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    "file_count": {"type": "integer", "minimum": 1, "maximum": 10000},
    "total_bytes": {"type": "integer", "minimum": 0, "maximum": 9007199254740991},
    "committed_by": {"type": "string", "minLength": 1},
    "committed_at": {"type": "string", "format": "date-time"} } }
```

```json
{ "$id": "urn:huron:revision-index:1",
  "required": ["schema", "dataset_id", "revisions"],
  "properties": {
    "schema": {"const": "urn:huron:revision-index:1"},
    "dataset_id": {"type": "string", "format": "uuid"},
    "revisions": {"type": "array", "items": {"type": "object", "additionalProperties": false,
      "required": ["number", "revision_id", "directory", "manifest_sha256", "metadata_sha256",
                   "file_count", "total_bytes", "committed_at"],
      "properties": {
        "number": {"type": "integer", "minimum": 1, "maximum": 999999},
        "revision_id": {"type": "string", "format": "uuid"},
        "directory": {"type": "string", "pattern": "^[0-9]{6}--[0-9a-f]{32}$"},
        "manifest_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "metadata_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "file_count": {"type": "integer", "minimum": 1},
        "total_bytes": {"type": "integer", "minimum": 0},
        "committed_at": {"type": "string", "format": "date-time"} } } } } }
```

`COMMITTED` deliberately omits `revision_path`: a document must not name its own location —
`parse_revision_dir` recovers it from the prefix (`layer-raw.html:181-183`), and a tree moved to
another root stays valid. `INDEX.json` carries no timestamp: the same set of revisions gives the
same bytes, so the reconciler detects staleness by comparing `sha256(INDEX.json)` with a rebuild
rather than by clock. `directory` is the revision directory's basename, which is what a reader
listing `raw/revision/` joins on.

**`pkg/catalog/documents.py`** — signatures with one-line intents (`JsonValue` from
`manifest.py`; `Slugged` from `paths.py`; `RevisionRecord` from `models.py`; `IngestSession` from
`ingest.py`; `ContractMismatch` from `errors.py`; `validate` from `huron.schema`):

```python
METADATA_SCHEMA, COMMITTED_SCHEMA, INDEX_SCHEMA = "urn:huron:metadata:1", "urn:huron:committed:1", "urn:huron:revision-index:1"
SERVER_METADATA_MEMBERS: frozenset[str]   # schema, organization, project, dataset, revision_number, committed_by, committed_at, manifest_sha256, data_classification

def manifest_bytes(manifest: Manifest) -> bytes:
    """The ``manifest.json`` document: canonical bytes of ``as_dict()``, whose SHA-256 is ``manifest.sha256``."""

def decode_manifest(payload: bytes) -> Manifest:
    """Rebuild a manifest from stored bytes through manifest-v1 and ``validate_manifest``; refuses bytes that are not their own canonical form."""
    # json.loads → ValueError if canonical_bytes(doc) != payload → validate("manifest-v1.json", doc) (jsonschema.ValidationError → ValueError)
    # → validate_manifest([ManifestEntry(**f) for f in doc["files"]]) (the nine path codes propagate as PathRuleViolation)

@dataclass(frozen=True, slots=True)
class MetadataDocument:
    """One revision's descriptive snapshot, exactly as ``metadata.json`` holds it; always conforms to metadata-v1."""
    _document: Mapping[str, JsonValue]      # validated; exposed only as copies and properties

    @classmethod
    def compose(cls, submission: Mapping[str, JsonValue], *, manifest: Manifest, organization: Slugged, project: Slugged,
                dataset: Slugged, revision_number: int, committed_by: str, committed_at: datetime, data_classification: str) -> MetadataDocument:
        """Assemble the client's descriptive members under the server's identity, provenance and digest members."""
        # ValueError: submission ∩ SERVER_METADATA_MEMBERS ≠ ∅, or committed_at is naive
        # ContractMismatch(context={"schema": METADATA_SCHEMA, "path": err.json_path, "message": err.message}): validate("metadata-v1.json") failed
    @classmethod
    def decode(cls, payload: bytes) -> MetadataDocument:
        """Rebuild from stored bytes; ``ValueError`` for a non-canonical or non-conforming document (storage, not a client, is wrong)."""
    def as_dict(self) -> dict[str, JsonValue]: ...          # a fresh copy
    @property
    def canonical(self) -> bytes: ...                        # canonical_bytes(self._document)
    @property
    def sha256(self) -> str: ...                             # content_identity(...) — the metadata_sha256 column
    @property
    def manifest_sha256(self) -> str: ...
    @property
    def committed_by(self) -> str: ...
    @property
    def committed_at(self) -> datetime: ...                  # tz-aware UTC

@dataclass(frozen=True, slots=True)
class CommitRecord:
    """The ``COMMITTED`` marker: the reconciler's reconstruction record — a revision record minus its location."""
    revision_id: UUID; dataset_id: UUID; revision_number: int
    manifest_sha256: str; metadata_sha256: str; file_count: int; total_bytes: int
    committed_by: str; committed_at: datetime

    @classmethod
    def of(cls, record: RevisionRecord) -> CommitRecord:
        """Take every field of the record but ``revision_path``."""
    @classmethod
    def decode(cls, payload: bytes) -> CommitRecord:
        """Rebuild from stored bytes through committed-v1; ``ValueError`` when non-canonical or non-conforming."""
    def as_dict(self) -> dict[str, JsonValue]: ...
    @property
    def canonical(self) -> bytes: ...
    def revision_record(self, *, revision_path: str) -> RevisionRecord:
        """The row this marker reconstructs, at the directory it was read from."""

@dataclass(frozen=True, slots=True)
class IndexEntry:
    number: int; revision_id: UUID; directory: str; manifest_sha256: str; metadata_sha256: str
    file_count: int; total_bytes: int; committed_at: datetime

@dataclass(frozen=True, slots=True)
class RevisionIndex:
    """The derived navigation aid beside a dataset's revision directories: one entry per committed revision, ascending by number."""
    dataset_id: UUID
    entries: tuple[IndexEntry, ...]

    @classmethod
    def empty(cls, dataset_id: UUID) -> RevisionIndex: ...
    @classmethod
    def decode(cls, payload: bytes) -> RevisionIndex:
        """Rebuild through revision-index-v1; ``ValueError`` when non-canonical, non-conforming, unsorted or with a repeated number."""
    def including(self, record: RevisionRecord) -> RevisionIndex:
        """Return the index with ``record``'s entry added or replaced at its number; ``ValueError`` for another dataset's record."""
    def as_dict(self) -> dict[str, JsonValue]: ...
    @property
    def canonical(self) -> bytes: ...

def revision_from_storage(committed: bytes, metadata: bytes, *, session: IngestSession, revision_path: str) -> RevisionRecord:
    """Rebuild the row a published envelope describes, after proving the envelope agrees with itself and with the session."""
    # record = CommitRecord.decode(committed); doc = MetadataDocument.decode(metadata)
    # ValueError unless: doc.sha256 == record.metadata_sha256; record.manifest_sha256 == doc.manifest_sha256 == session.manifest_sha256;
    #   (record.revision_id, record.dataset_id, record.revision_number) == (lease.revision_id, lease.dataset_id, lease.revision_number);
    #   record.committed_by == doc.committed_by and record.committed_at == doc.committed_at
    # return record.revision_record(revision_path=revision_path)
```

**Design 4's five named callables, mapped.** `manifest_bytes` and `decode_manifest` are the
module functions above. `metadata_document(metadata, *, manifest, organization, project,
dataset, committed_by, committed_at)` is `MetadataDocument.compose(...)` — it returns the
document, and the facade takes `.canonical` and `.sha256` from it instead of a `(bytes, str)`
tuple. `committed_bytes(record)` is `CommitRecord.of(record).canonical`.
`revision_from_storage(committed, metadata, session)` gains the keyword `revision_path=` (the
facade already holds `final`; the marker does not carry it). The one named `DomainError` is
`ContractMismatch` (`errors.py:244`, `CONTRACT_MISMATCH` 409), raised in exactly one place —
`MetadataDocument.compose` — so the §7 row flips `reserved` → `live` (below).

**`RevisionView` and `MetadataSubmission`** (`routes/v1/schema/revisions.py`):

```python
class MetadataSubmission(BaseModel):
    """The committer's half of ``metadata.json``: description, never identity or provenance."""
    model_config = ConfigDict(extra="forbid")               # a client-supplied committed_by is 422 REQUEST_INVALID
    title: str
    creators: list[str]
    description: str | None = None
    tags: list[str] | None = None
    source: dict[str, object] | None = None
    coverage: dict[str, object] | None = None
    extensions: dict[str, object] | None = None
    # the facade passes model_dump(exclude_none=True) to MetadataDocument.compose; value rules
    # (minLength, minItems, uniqueItems) are the schema's, so they refuse as CONTRACT_MISMATCH

class RevisionView(BaseModel):
    """A committed revision as the catalog records it; the storage location is not wire contract."""
    model_config = ConfigDict(from_attributes=True)
    id: UUID; dataset_id: UUID; number: int
    manifest_sha256: str; metadata_sha256: str
    file_count: int; total_bytes: int
    committed_by: str; committed_at: datetime
```

Types are Pydantic's, values are the schema's — one authority for content rules, so P5's
effective schema replaces `metadata-v1.json` without touching the wire model.

**`RevisionService`** (`service/api/revisions.py`), typed against the port; the read side
consults storage on every request and caches nothing:

```python
@dataclass(frozen=True, slots=True)
class PayloadFile:
    """One payload file as the manifest lists it and as storage holds it."""
    entry: ManifestEntry
    location: Path
    stat: os.stat_result

class RevisionService:
    """The read side of a committed revision: its record, its stored manifest, its payload files."""
    def __init__(self, raw_store: RawStore, hierarchy: HierarchyStore) -> None: ...
    async def revision(self, revision_id: UUID, visibility: Visibility) -> RevisionRecord:
        # hierarchy.revision(revision_id) (Design 3) → hierarchy.dataset(record.dataset_id, visibility): ResourceNotFound either way
    async def manifest_file(self, record: RevisionRecord) -> tuple[Path, os.stat_result]:
        # location = Path(record.revision_path) / "manifest.json"; stat = await asyncify(os.stat)(location); FileNotFoundError propagates
    async def payload_file(self, record: RevisionRecord, path: str) -> PayloadFile:
        # validate_manifest_path(path) — before any storage access (PATH_* 400)
        # manifest = decode_manifest(await asyncify(raw_store.read_document)(PurePosixPath(record.revision_path) / "manifest.json"))
        # manifest.sha256 != record.manifest_sha256 → RuntimeError (storage and catalog disagree)
        # entry = the one whose .path == path → ResourceNotFound("no such file in revision") otherwise
        # location = Path(record.revision_path) / entry.path — composed from the validated entry, never from the request string
        # stat = await asyncify(os.stat)(location); stat.st_size != entry.size → RuntimeError; FileNotFoundError propagates
```

**Guard** (`authorization/guards.py`; `Revisions` imported from `..runtime` as `Repository` is):

```python
@dataclass(frozen=True, slots=True)
class RevisionRead:
    """Proof that the caller may read one revision's raw bytes: the principal and the record as resolved."""
    principal: Principal
    record: RevisionRecord

async def revision_raw_reader(revision_id: UUID, principal: CurrentPrincipal, revisions: Revisions,
                              repository: Repository, cache: BindingCache, visibility: CurrentVisibility) -> RevisionRead:
    record = await revisions.revision(revision_id, visibility)                 # 404 absent or invisible, before any binding is read
    scope = await dataset_scope(repository, record.dataset_id, visibility)
    capability, layer = required_capability(LayerAction.READ, Layer.RAW)       # ("data.read", "raw")
    await check(cache, repository, principal, capability, scope, layer=layer)   # 403 FORBIDDEN
    return RevisionRead(principal, record)
```

There is no read-side kind rule (`ensure_layer_writable` is write-only, `layers.py:206`): a
service account is refused by its synthesised bindings (`SERVICE_ACCOUNT_CAPABILITIES` holds no
`data.read`, `roles.py:49`), which is `FORBIDDEN`, not `LAYER_WRITE_FORBIDDEN`.

**The download capability, defined.** `design/api.html:135` names `dataset.read_raw`, which
does not exist; the layer model's capability is `data.read` with layer `raw`
(`required_capability(LayerAction.READ, Layer.RAW)`, `layers.py:168-183`). `layer-raw.html:121`
gave up presigned downloads, so no token is minted: **the authorised response is the capability**.
Its name is `data.read@raw` at the revision's dataset scope; the re-check is per request —
every `GET …/files/{path}` and every `Range` re-request of the same file runs the guard against
the request's own binding read (`BindingCache` is request-scoped), so a revoked binding takes
effect on the next request exactly as Design 4 made a revoked `data.write@raw` take effect on the
next part; the TTL is the response — nothing outlives the connection that carries the bytes.
Whether this belongs in milestone 8's "Adds" is Open question 2.

**Route table.** Prefix `/api/v1/revisions`, tags `["revisions"]`; credential and
`AUTHENTICATED_ERRORS` from the v1 router; every route `async def`; every stat and document read
is `await asyncify(...)`. R1 is not one of the scope's two download routes: it costs one path
operation on an existing read and makes the resource a 201 returns addressable; the plan may
drop it without affecting R2/R3.

| # | Method, path | Guard | Calls (in order) | Success | Errors (status · code · condition) |
|---|---|---|---|---|---|
| R1 | `GET /revisions/{revision_id}` | credential + visibility | `revisions.revision(id, visibility)` | 200 `RevisionView` | 404 `NOT_FOUND` absent or dataset invisible |
| R2 | `GET /revisions/{revision_id}/manifest` | `revision_raw_reader` | `revisions.manifest_file(record)` → `FileResponse(location, media_type="application/json", stat_result=stat, headers={"ETag": f'"{record.manifest_sha256}"'})` | 200 the stored JCS bytes; 206 on `Range` | 404 `NOT_FOUND`; 403 `FORBIDDEN` no `data.read@raw`; 416 `REQUESTED_RANGE_NOT_SATISFIABLE`; 500 `INTERNAL_ERROR` `manifest.json` missing (storage/catalog disagreement — the reconciler's) |
| R3 | `GET /revisions/{revision_id}/files/{path:path}` | `revision_raw_reader` | `revisions.payload_file(record, path)` → `FileResponse(location, media_type=entry.media_type, filename=PurePosixPath(entry.path).name, stat_result=stat, headers={"ETag": f'"{entry.sha256}"'})` | 200 the bytes, `Content-Length` = `entry.size`, `Content-Disposition: attachment; filename*=utf-8''…` for non-ASCII names; 206 on `Range` | 400 `PATH_OUTSIDE_PAYLOAD`/`PATH_NOT_NFC`/`PATH_TOO_LONG`/`PATH_TRAVERSAL`/`PATH_CONTROL_CHARS`/`PATH_SEPARATOR` (`validate_manifest_path`, before any storage access); 404 `NOT_FOUND` revision absent/invisible, or `path` not a manifest entry (a stray file on disk is still 404 — the manifest is the authority); 403 `FORBIDDEN`; 416; 500 `INTERNAL_ERROR` listed file missing, `st_size ≠ size`, or manifest identity ≠ row |

`path` is the manifest path verbatim (`payload/…`, NFC), so one string names one entry and the
manifest's own rules are the URL's. The proxy/client normalises a literal `..` before the route
sees it (**proved**: httpx sends `secret.txt`, refused as `PATH_OUTSIDE_PAYLOAD`); a percent-encoded
`%2E%2E` reaches the route as `payload/../x` and is `PATH_TRAVERSAL` (**proved**); an NFD spelling is
`PATH_NOT_NFC` although the filesystem would serve it (**proved** the filesystem does).

**Streaming response type: `FileResponse`.** It reads in 64 KiB chunks off the event loop
(`anyio` thread), sends `Content-Length` and `Last-Modified` from the stat passed in, honours
single and multiple `Range`s with `If-Range` against the `ETag`, and quotes a non-ASCII
`filename` as RFC 5987 (**proved** all of: a sealed `0o444` file in `0o555` directories → 200;
`bytes=1-3` → 206 `Content-Range: bytes 1-3/5`; `bytes=99-` → 416 `Content-Range: bytes */5`;
`caf%C3%A9.txt` in `filename*`). The `ETag` is the content digest from the manifest, a strong
validator a client can verify after the download, rather than Starlette's mtime/size hash (its
`setdefault` yields to the header passed in). `stat_result` is passed so a missing or short file
is the route's error before a response exists (**proved**: without it `FileResponse` raises
`RuntimeError` at send time, after the handler returned). Range support is kept because the P2
gate's 9 GiB download is what a client resumes; its cost is one wire status: an unsatisfiable
range is answered by the response object itself — 416, empty body, `Content-Range: bytes */{size}`,
not a problem document — so `FRAMEWORK_STATUSES` gains 416 and `design/api.html` §7 gains the row
`REQUESTED_RANGE_NOT_SATISFIABLE · 416 · live · a Range header names bytes outside the file;
answered by the file response with an empty body and Content-Range, not a problem document`.
`StreamingResponse` is excluded: it would reimplement all of the above.

**`CONTRACT_MISMATCH`: decided — taken.** `MetadataDocument.compose` raises `ContractMismatch`
(409) with `context={"schema", "path", "message"}` from the first `jsonschema` violation, raised at
Design 4's step 3, before any state edge. §7 consequence: the row at `design/api.html:248` flips
`reserved` → `live`; its meaning cell gains "— in P2 the registered contract is the packaged
`metadata-v1.json`". Design 4's `ast` raise-site check finds the one raise in
`pkg/catalog/documents.py`. `layer-raw.html:192`'s "a client-supplied value is a 400" for
`committed_by`/`committed_at` becomes "is 422 `REQUEST_INVALID`: the body model has no such
member" — shape refusals are the tier's 422, content refusals the schema's 409.

### Explicit contracts

**Document invariants** (each pinned in § Tests):

| Document / class | Invariant | Error behaviour | Lifecycle |
|---|---|---|---|
| `manifest_bytes` / `decode_manifest` | `sha256(manifest_bytes(m)) == m.sha256`; `decode_manifest(manifest_bytes(m)).sha256 == m.sha256`; decoded paths are NFC and digests lower-case (through `validate_manifest`) | `ValueError` non-canonical or off-schema bytes; `PathRuleViolation` from `validate_manifest` | written at create and rewritten identically at commit step 1; read at create/verify (parent), at commit (own envelope), at every R3 |
| `MetadataDocument` | an instance conforms to metadata-v1; `sha256 == sha256(canonical)`; `committed_at` tz-aware and rendered with `Z`; the submission never carries a server member | `compose`: `ValueError` (server member in submission, naive instant — caller bugs), `ContractMismatch` (content); `decode`: `ValueError` | composed once per `/commit` attempt before any edge; written at step 1; read back by the post-rename retry and by P3's reconciler |
| `CommitRecord` | `of(r).revision_record(revision_path=r.revision_path) == r`; `as_dict()` keys are exactly committed-v1's required set | `decode`: `ValueError` | written at step 3, last before the rename, because its presence means "documents and seal are complete" (Design 2); read by the retry (`revision_from_storage`) and by the reconciler |
| `RevisionIndex` | entries ascending and unique by `number`; the same entry set gives identical bytes; `including` never drops an entry | `ValueError` | best-effort at step 8 (Open question 1); regenerated by P3 |
| `revision_from_storage` | returns a record only when marker, metadata and session agree on identity, digests, committer and instant | `ValueError` — Design 4 renders it as its 500 (storage disagrees with the catalog) | the post-rename retry only in P2 |

**Read-side invariants.** Only manifest entries are served: the request string is used for
lookup, the served location is composed from the validated entry; every R2/R3 request re-runs
`data.read@raw` at the dataset scope; nothing under `.staging/` is ever reachable (a record's
`revision_path` is always a published directory); `Content-Length` equals the manifest size or
the request is a 500, never a short body reported as success; the read side never writes.

**Lifecycle.** `RevisionService` is built once in the lifespan over the shared `PosixRawStore`
and `HierarchyStore`, after `HierarchyRepository` (which runs `initialize()`); it holds no state.
Documents are values; none is cached between requests.

**Requirements on the other designs.** Flagged **(new)** where an earlier design did not
anticipate it — the plan must carry these.

- **Design 2 (raw store).** None beyond what it offered: `write_document` ×3 in the stated order,
  `atomic_replace` for `INDEX.json`, `read_document` for the parent and own manifest. `COMMITTED`
  now has JSON content; `commit_envelope` keeps testing only its presence.
- **Design 3 (persistence).** None beyond `revision(id)`, `latest_committed_revision`, and the
  existing `HierarchyStore.dataset(id, visibility)` the read side uses for 404-before-403.
- **Design 4 (HTTP and the facade).** (a) **(new)** `CommitIngestSession.metadata` is
  `MetadataSubmission` (typed, `extra="forbid"`), not `dict[str, object]`; the claim digest's
  `content_identity(metadata)` is computed over `model_dump(exclude_none=True)`. (b) **(new)**
  `record = revision_record(committing, manifest, metadata_sha256=doc.sha256, revision_path=str(final), committed_by, committed_at=now)`
  is built **before** disk step 3 — `COMMITTED` is `CommitRecord.of(record).canonical` — not
  after `commit_envelope` as step 5's prose orders it; `revision_record` refuses a session not in
  COMMITTING, which step 4 already guarantees. (c) Step 3 reads the organization, project and
  dataset at `Visibility.ALL` (it already does for the path) and passes them plus
  `project.data_classification` (Open question 3) to `compose`. (d) `metadata_document` and
  `committed_bytes` are the classmethods mapped above; `revision_from_storage` takes
  `revision_path=` **(new)**. (e) `ValueError` from `decode_manifest`, `revision_from_storage` or
  a document `decode` is the same class of failure as the manifest-identity mismatch in step 3 —
  500, the reconciler's — and, with `final/COMMITTED` absent, still persists `fail()`. (f) If Open
  question 1 resolves to A: after the six-statement transaction commits, step 8 —
  `read_document(index_path)` (`FileNotFoundError` → `RevisionIndex.empty`) → `.including(record)`
  → `atomic_replace(index_path, canonical)` — inside a `try` that logs and swallows every
  exception; the 201 never depends on it. (g) `ApiRuntime.revisions` and the lifespan wiring;
  `test_execution_model.py`'s table gains `get_revision`, `get_revision_manifest`,
  `get_revision_file` (63 operations). (h) Design 4's Tests: `test_commit_publishes_the_revision_and_its_events`
  asserts the three documents through `decode_manifest`, `MetadataDocument.decode` and
  `CommitRecord.decode`, not by string inspection.
- **Design 6 (sweep).** None.
- **Design 7 (suites).** Arrange § Tests as `unit` over `TestClient` + `memory_stores()` +
  `tmp_path`; the P2 gate's "ingests and downloads byte-identically" is Design 4's upload helpers
  composed with R3 in `test_api_revisions.py`; the 9 GiB download uses the same sparse-file
  technique as the upload (a `FileResponse` never holds more than 64 KiB), in the acceptance
  suite only. `_HIERARCHY_TABLES` is unchanged. The two new schema modules follow
  `test_schema_snapshot_provenance.py`'s pattern.

### Deletions

- Code: **none**. `records.jsonable` stays (it renders tier records; the catalog cannot import
  it, so `documents.py` carries its own two-line instant render/parse under the same `Z` rule).
- `pkg/catalog/models.py:57` `RevisionRecord` docstring "as the metastore records it" → "as the
  catalog records it" (Design 3 deletes `Metastore`).
- `design/api.html:135`: `dataset.read_raw` → `data.read@raw`; "issues a short-lived download
  capability; re-authorized per file" → "authorised per request against `data.read@raw`; the
  response is the capability, nothing is minted"; `:134` unchanged. §7: `CONTRACT_MISMATCH`
  `reserved` → `live` (+ meaning suffix); new `REQUESTED_RANGE_NOT_SATISFIABLE` row.
- `design/layer-raw.html:192` "a client-supplied value is a 400" → "is 422 `REQUEST_INVALID`";
  `:311` "digests, counts, committer, timestamp in one small JSON" → "… one small JCS document,
  `urn:huron:committed:1`"; `:141` "regenerated on commit" → per Open question 1's answer.
- `design/roadmap.html:559-566` milestone 8 "Adds": per Open question 2's answer.

### Data flow

```mermaid
sequenceDiagram
    participant C as Client
    participant F as IngestService.commit (D4)
    participant D as pkg/catalog/documents
    participant S as PosixRawStore (asyncify)
    participant DB as HierarchyStore
    participant R as GET /revisions/{id}/files/{path}

    Note over F,S: create — the envelope carries the manifest from the start
    F->>S: write_document(staging, "manifest.json", manifest_bytes(m))
    Note over C,DB: /commit — before any edge
    C->>F: {manifest_sha256, metadata: MetadataSubmission}
    F->>S: read_document(staging/manifest.json)
    F->>D: decode_manifest → m (sha256 == session's, else 500)
    F->>D: MetadataDocument.compose(submission, m, org, project, dataset, n, by, now, classification)
    D-->>F: doc (or 409 CONTRACT_MISMATCH)
    F->>DB: tx: begin_commit → COMMITTING
    F->>D: record = revision_record(…, metadata_sha256 = doc.sha256, revision_path = final)
    alt final/COMMITTED absent
        F->>S: 1 write_document(manifest.json) · write_document(metadata.json, doc.canonical)
        F->>S: 2 seal(staging)
        F->>S: 3 write_document("COMMITTED", CommitRecord.of(record).canonical)
        F->>S: 4–6 commit_envelope — rename, durability point
    else retry past the rename
        F->>S: read_document(final/COMMITTED) · read_document(final/metadata.json)
        F->>D: revision_from_storage(committed, metadata, session, revision_path = final)
        D-->>F: record (agreement proved) or ValueError → 500
    end
    F->>DB: 7 tx: claim · insert_revision · COMMITTED · audit · outbox · remember
    F->>S: 8 best-effort: read INDEX.json → including(record) → atomic_replace (OQ1)
    F-->>C: 201 RevisionView
    Note over C,R: download — re-authorised per request
    C->>R: GET …/files/payload/é/café.txt (+ Range)
    R->>DB: revision(id) · dataset(visibility) · data.read@raw at the dataset scope
    R->>R: validate_manifest_path(path) — PATH_* before storage
    R->>S: read_document(final/manifest.json) → decode_manifest → entry
    R->>R: stat(final/entry.path) == entry.size, else 500
    R-->>C: FileResponse: 200/206, ETag "<sha256>", filename*=utf-8''…
```

### Rejected alternatives

- **Minted signed download URLs (`/transfer/downloads/{token}`, own TTL)** — `layer-raw.html:121`
  gave presigned downloads up; a token outlives a revoked binding and needs a signing key, while a
  per-request check is stronger and the request already carries the credential.
- **Serving `GET …/manifest` from the catalog row by regenerating the JSON** — the stored bytes
  are the identity; regenerated bytes can drift from what was hashed.
- **Mirroring every schema constraint into `MetadataSubmission` (`min_length`, `min_length=1`,
  unique tags)** — two authorities for one rule, and `CONTRACT_MISMATCH` would have a raise site
  with no reachable path; the schema is what P5's registry replaces.

### Open questions

1. **`INDEX.json` ownership (Drift 4).** *Option A — P2 writes it best-effort at step 8, P3's
   reconciler owns regeneration.* P2: one `read_document` + `atomic_replace` per commit, swallowed
   on failure; a torn or stale index is a named reconciler finding, never a client error; the
   content schema (`revision-index-v1`) and `RevisionIndex` exist either way. P3: "stale
   `INDEX.json` → regenerate" (`layer-raw.html:413`) becomes a rebuild from `COMMITTED` markers
   compared by digest, and needs a directory-listing primitive on the port that P2 does not add.
   *Option B — P2 writes nothing; P3 creates and regenerates.* P2: nothing beside the revision
   directories, and the P2 row's "`INDEX.json`" deliverable is written back to P3. P3: the same
   rebuild, plus first creation; a dataset committed under P2 has no index until the reconciler
   runs once. *Recommended: A* — it is the grill's recommendation, the cost is two calls that
   cannot fail the commit, and it makes `layer-raw.html:141`'s "regenerated on commit" true for
   the common case while leaving the authority where §9 puts it.
2. **Download capabilities in milestone 8's "Adds" (Drift 4).** *Option A — add R2 and R3 (and
   R1) explicitly*, with the capability defined as per-request `data.read@raw` authorisation.
   P2: three read routes, one guard, one service class, and the P2 gate's "downloads
   byte-identically" is provable over HTTP in the unit suite; `design/api.html:135` is written
   back. P3: nothing. *Option B — defer downloads to a later milestone.* P2: the gate's download
   clause can only be proved by reading the sealed tree in a test, and a client that committed a
   revision has no way to get its bytes back through the API. *Recommended: A* — the grill's
   recommendation; the P2 row already lists download capabilities as a deliverable and the
   routes are small.
3. **`data_classification`'s source.** *Option A — server-sourced from
   `project.data_classification`* (recommended): the project's classification governs discovery
   today (`records.py:59`), `design/api.html:136` says reclassification is "separately
   permissioned" (an amend privilege), so a committer should not set it; `compose` takes it as a
   keyword. *Option B — a `MetadataSubmission` member*: the client states it, the schema requires
   it non-empty, and a revision may disagree with its project. If B, `data_classification` moves
   from `SERVER_METADATA_MEMBERS` into the wire model and out of `compose`'s keywords.
4. **`format: date-time` is a no-op in this environment** (**proved**: `"yesterday"` and a naive
   isoformat both accepted; `uuid` is enforced). P2 does not depend on it (the server writes the
   instant), but `metadata-v1`, `committed-v1` and `revision-index-v1` all assert it and P3's
   reconciler will re-validate stored documents. *Recommended:* add `rfc3339-validator` (the
   `jsonschema[format-nongpl]` extra) to the runtime dependencies in the same change, and pin it
   with one test that a malformed instant is refused. Alternative: leave the assertion documentary
   and note it in `schema/__init__.py`'s docstring.

### Tests

`tests/unit/test_catalog_documents.py` (`pytest.mark.unit`; helpers `_manifest(*entries)`,
`_record(**overrides)`, `_submission(**overrides)`; `NFC = normalize("NFC", "payload/é/café.txt")`,
`DEEP = "payload/d1/…/d8/leaf.bin"`, a zero-byte entry with `sha256(b"")`):

| Test | Asserts |
|---|---|
| `test_manifest_bytes_are_canonical_and_hash_to_the_manifest_identity` | `manifest_bytes(m) == canonical_bytes(m.as_dict())`; `sha256(bytes) == m.sha256`; `é` is raw UTF-8 in the bytes |
| `test_decode_manifest_round_trips_nfc_zero_byte_and_eight_level_entries_with_the_same_identity` | `decode_manifest(manifest_bytes(m)) == m`; `.sha256` equal; the three entries intact |
| `test_decode_manifest_refuses_an_nfd_path_a_pretty_printed_document_and_a_foreign_schema` | NFD → `PathRuleViolation` `PATH_NOT_NFC`; `json.dumps(indent=2)` bytes → `ValueError`; `schema: "x"` → `ValueError` |
| `test_metadata_compose_places_every_server_member_and_keeps_the_submission_s` | all eleven required members present with their named sources; `tags`/`extensions` verbatim; absent optionals absent |
| `test_metadata_compose_refuses_a_submission_naming_a_server_member_or_a_naive_instant` | `committed_by` in the submission → `ValueError`; naive `committed_at` → `ValueError` |
| `test_metadata_compose_refuses_schema_violations_as_contract_mismatch_naming_the_path` | parametrized `title ""`, `creators []`, duplicate `tags`, `data_classification ""`, unknown key → `ContractMismatch`, `context["path"]` names the member |
| `test_metadata_document_round_trips_and_renders_the_instant_with_a_z_suffix` | `decode(doc.canonical).sha256 == doc.sha256`; `"Z"` in canonical, `"+00:00"` absent; `committed_at` tz-aware equal |
| `test_metadata_decode_refuses_non_canonical_or_non_conforming_bytes` | `ValueError` both |
| `test_commit_record_carries_every_record_field_but_the_path_and_rebuilds_the_record` | `as_dict()` keys == committed-v1 `required`; `decode(of(r).canonical).revision_record(revision_path=r.revision_path) == r` |
| `test_commit_record_decode_refuses_an_extra_member_a_missing_member_and_pretty_bytes` | `ValueError` ×3 |
| `test_revision_from_storage_rebuilds_the_record_only_when_the_envelope_agrees_with_the_session` | happy path `== revision_record(...)`; each of metadata digest, manifest digest, revision id, number, committer, instant disagreeing → `ValueError` |
| `test_revision_index_includes_replaces_sorts_and_refuses_another_dataset` | `including` twice at one number keeps one entry; numbers ascending; foreign `dataset_id` → `ValueError` |
| `test_revision_index_round_trips_and_the_same_set_gives_identical_bytes` | `decode(canonical)` equal; two build orders → equal bytes; unsorted or repeated bytes → `ValueError` |

`tests/unit/test_schema_committed.py` and `tests/unit/test_schema_revision_index.py` (the
`test_schema_snapshot_provenance.py` pattern): `test_the_schema_itself_is_valid`,
`test_every_required_member_is_required` (parametrized removal → refused),
`test_unknown_members_are_refused`, `test_digests_and_ids_must_be_well_formed` (upper-case digest,
non-uuid → refused), and for the index `test_the_directory_name_must_be_a_revision_directory`.

`tests/unit/test_api_revisions.py` (`client`/`stores` fixtures as `test_api_catalog_hierarchy.py:71-89`,
`tmp_path` data root; helpers reuse Design 4's `_developer_dataset`, `_session`, `_put_part`,
`_commit`, plus `_committed(client, files) -> (dataset_id, revision_id)` and `_reader(client,
subject)` binding a role that holds `data.read@raw`):

| Test | Asserts |
|---|---|
| `test_get_revision_returns_the_view_and_hides_an_invisible_one` | 200 with the nine `RevisionView` members and no `revision_path`; a restricted project's revision → 404 for an outsider; unknown id → 404 |
| `test_manifest_download_streams_the_stored_bytes_with_the_identity_as_etag` | body equals the file under `revision_path`; `sha256(body) == manifest_sha256`; `ETag == '"<manifest_sha256>"'`; `Content-Type: application/json` |
| `test_file_download_round_trips_nfc_zero_byte_and_eight_level_files_byte_identically` | three files uploaded through Design 4's routes, downloaded through R3: bytes equal; `Content-Length` = size (0 for the empty file); `Content-Disposition` carries `filename*=utf-8''caf%C3%A9.txt`; `ETag == '"<sha256>"'`; `Content-Type` = `media_type` |
| `test_file_download_reads_a_sealed_payload` | after commit the file is `0o444` in `0o555` directories under a `0o555` root → 200 |
| `test_file_download_refuses_traversal_and_non_nfc_spellings_before_touching_storage` | `payload/%2E%2E/x` → 400 `PATH_TRAVERSAL`; NFD spelling → 400 `PATH_NOT_NFC`; `x` → 400 `PATH_OUTSIDE_PAYLOAD`; a `read_document` spy is never called |
| `test_file_download_404s_a_path_the_manifest_does_not_list_even_if_it_exists_on_disk` | a stray file placed under `payload/` → 404 `NOT_FOUND` |
| `test_download_authorization_requires_data_read_on_raw_and_hides_invisible_datasets` | reader → 200; org admin without a data role → 403 `FORBIDDEN`; service account → 403 `FORBIDDEN`; unbound user → 403; outsider on a restricted project → 404 — on R2 and R3; R1 needs only visibility |
| `test_download_is_re_authorized_on_every_request` | 200, revoke the binding, 403 on the next `GET` of the same file |
| `test_range_requests_are_served_and_an_unsatisfiable_one_is_416` | `bytes=1-3` → 206, `Content-Range: bytes 1-3/{size}`, three bytes; `bytes=99999-` → 416 with `Content-Range: bytes */{size}` |
| `test_a_listed_file_missing_or_short_on_disk_is_a_server_error` | unlink (after `chmod`) → 500 `INTERNAL_ERROR`; truncate → 500; manifest row digest patched → 500 |
| `test_commit_writes_the_three_documents_and_they_agree` | `decode_manifest(manifest.json).sha256 == view.manifest_sha256`; `MetadataDocument.decode(metadata.json).sha256 == view.metadata_sha256` with `committed_by == "bob"` and the schema's eleven members; `CommitRecord.decode(COMMITTED).revision_record(revision_path=…)` equals the store's row; all three `0o444` |
| `test_commit_refuses_a_metadata_submission_the_schema_rejects_before_any_edge` | `creators: []` → 409 `CONTRACT_MISMATCH`, `context["path"] == "$.creators"`, session still VERIFYING at the same etag; `committed_by` in the body → 422 `REQUEST_INVALID` |
| `test_metadata_carries_the_project_s_classification_and_the_hierarchy_refs` | `data_classification == project's`; `organization/project/dataset` `{id, slug}` equal the records (Open question 3 = A) |
| `test_a_commit_writes_the_index_and_a_second_commit_extends_it` | `INDEX.json` beside the directory decodes to one entry, then two, ascending, `directory` equals each basename; an injected `atomic_replace` failure leaves the 201 intact (Open question 1 = A) |
| `test_a_commit_retry_past_the_rename_rebuilds_the_record_from_the_marker` | extends Design 4's crash test: the retried 201's `metadata_sha256`, `committed_at` and `committed_by` equal `COMMITTED`'s, not the retry's instant |

`tests/unit/test_execution_model.py`: `EXPECTED_COROUTINE_FUNCTION` gains the three handlers;
`test_the_file_download_s_stat_executes_off_the_event_loop_thread` patches `os.stat` through
`RevisionService` with the `readyz` tracking pattern. `tests/unit/test_error_contract.py`:
`CONTRACT_MISMATCH` is `live` with its raise site under `pkg/catalog/documents.py`; the 416 row
round-trips through `wire_error_codes()`.

### Receipts

`uv run python scratchpad/d5_proofs.py` at `c5e35c7` (fastapi 0.141.1, starlette 1.6.0,
jsonschema 4.26.0, rfc8785 0.1.4; script in the session scratchpad), salient lines:

- Manifest with `payload/é/café.txt` (NFC), a zero-byte entry and an 8-level path:
  `canonical_bytes` holds raw UTF-8 (`"é".encode() in payload` True, no `é`); `json.loads` →
  `validate_manifest` → `.sha256` equal (`8d309578…`); `sha256(stored bytes) == identity` True;
  the NFD twin → `PATH_NOT_NFC` with the path in `context`; `validate("manifest-v1.json",
  as_dict())` passes and refuses `path: "x"` at `$.files[0].path`.
- `metadata-v1`: `{}` yields exactly the eleven required-property errors; a full minimal
  document passes; refused — non-uuid `id`, one-character slug, extra top-level key, empty
  `creators`, upper-case digest; **accepted** — `committed_at: "yesterday"` and a naive
  isoformat (`format: date-time` unenforced; `rfc3339` absent from `pyproject.toml`/`uv.lock`);
  `extensions` round-trips through JCS; `isoformat().replace("+00:00","Z")` →
  `2026-09-04T12:00:00Z`; `fromisoformat` of it is tz-aware UTC.
- `FileResponse` under `TestClient` from a `0o444` file in `0o555` directories: 200 `b"hello"`,
  `content-disposition: attachment; filename*=utf-8''caf%C3%A9.txt`, `accept-ranges: bytes`;
  zero-byte file 200 with `content-length: 0`; `Range: bytes=1-3` → 206 `b"ell"`,
  `content-range: bytes 1-3/5`; `bytes=99-` → 416 `bytes */5`; a literal `..` is normalised by
  httpx before the route (it saw `secret.txt`); `%2E%2E` reaches the route as `payload/../secret.txt`;
  the NFD URL of the NFC file → 200 from the filesystem; a missing file → `RuntimeError` raised
  inside `FileResponse.__call__` after the handler returned. `set_stat_headers` uses `setdefault`
  for `etag`, `content-length`, `last-modified` (`responses.py:336-338`).
- `HTTPStatus(416).name == "REQUESTED_RANGE_NOT_SATISFIABLE"`; `FRAMEWORK_STATUSES` is
  `(400, 404, 405)` today (`problems.py:40`).
- Not run: the guard against a real `RoleBindingAuthorizer`; anything against PostgreSQL; a
  multi-range request; NFS; the reconciler's rebuild (P3).

## Design 6 — Expiry sweep and lease reaping

Scope: milestone 8's "expiry sweep" (`roadmap.html:558`) — the actor that flips an abandoned
session so `one_open_ingest_per_dataset` releases and the next `begin_ingest` on that dataset
succeeds. The rule (which rows, which fence, which audit kind) is Design 3's and is taken as
given; the domain edge (`expire`, landing in `ABORTED`, never from `COMMITTING`) is Design 1's.
This design owns the runner: where it lives, how it is scheduled and clocked, its bound, its
lifecycle, and its tests. Designs 1–5 are binding inputs. CLAUDE.md § Code Design: the pass is
behaviour and belongs to the object that already owns every other state edge (`IngestService`);
the runner is a lifecycle object owning one task, entered and left with the lifespan.

### Target design

**Placement: a lifespan-owned `asyncio.Task` in every API replica.** The pass is one indexed
`SELECT` and, per lapsed row, one two-statement transaction — work the API process already has
the pool, the clock and the facade for. `architecture.html:163` runs the API at "≥2, stateless"
replicas and `docker-compose.yml:110` at one; the design below is correct at any count (§ multi-
replica). Three placements were on the table; the other two are rejected below.

**This is not `architecture.html`'s `sweeper` service.** That row (`:192-194`) is a 15-minute
CronJob that "deletes expired staging directories on NFS" with a fraction guard and dry-run and
writes to "NFS staging only" — `layer-raw.html` §9's sweeper, P3's deliverable
(`roadmap.html:347`). The P2 sweep writes PostgreSQL rows and never opens a file; the two share
a trigger (a lapsed lease) and nothing else. To keep the names apart the P2 object is the
**expiry sweep**; "sweeper" stays P3's.

**Module layout.**

| Module | Change |
|---|---|
| `service/api/ingest.py` | `IngestService` + `expire_lapsed(*, limit) -> ExpiryReport` (the pass); `ExpiryReport`; `SWEEP_ACTOR = "system:sweep"` — requirement on Design 4, § Explicit contracts |
| `service/api/expiry.py` | new: `ExpirySweep` — the loop and the task it owns |
| `service/api/settings.py` | `ingest_sweep_interval_seconds`, `ingest_sweep_limit` |
| `service/api/app.py` | the lifespan wraps `yield` in `async with ExpirySweep(...)` after the runtime is published and `_bootstrap` ran |
| `runtime.py`, `create_app`'s signature | unchanged — no `clock` parameter (the tests below never drive time through the app; Design 4's `ApiRuntime.ingest` is all the loop needs) |

**The pass** (`service/api/ingest.py`, on Design 4's facade; `PreconditionFailed` from
`huron.pkg.catalog`, `AuditEvent` from `stores`):

```python
SWEEP_ACTOR = "system:sweep"                  # Design 3 (e): the actor of every ingest.expired row

@dataclass(frozen=True, slots=True)
class ExpiryReport:
    """What one sweep pass did; ``listed == expired + skipped`` always holds."""
    listed: int
    expired: int
    skipped: int

class IngestService:
    async def expire_lapsed(self, *, limit: int) -> ExpiryReport:
        """Flip up to ``limit`` lapsed PREPARING/UPLOADING/VERIFYING sessions to ABORTED, oldest first, one transaction each."""
        now = self._clock.now()
        lapsed = await self._hierarchy.lapsed_ingest_sessions(now, limit=limit)
        expired = skipped = 0
        for session in lapsed:
            aborted = session.expire(now=now)
            try:
                async with self._hierarchy.transaction() as writer:
                    await writer.expire_ingest_session(aborted, expected_etag=session.etag, now=now)
                    await writer.insert_audit_event(self._audit(
                        "ingest.expired", actor=SWEEP_ACTOR, session=session, now=now,
                        payload={"state": session.state.value, "expires_at": session.lease.expires_at,
                                 "dataset_id": session.lease.dataset_id},
                    ))
            except PreconditionFailed:
                skipped += 1
            else:
                expired += 1
        return ExpiryReport(listed=len(lapsed), expired=expired, skipped=skipped)
```

`now` is read **once per pass** so the list predicate, the fence, `session.expire`'s guard and
the audit row's `created_at` judge the same instant; a row the list called lapsed can never be
called live by the same pass. `_audit` is the helper Design 4's `abort` uses for `ingest.aborted`
(`AuditEvent(id=uuid7(), kind, actor, subject_kind="ingest_session", subject_id=session.id,
payload, created_at=now)`); payload datetimes and UUIDs go through `jsonable()` (Convention 9).

**The runner** (`service/api/expiry.py`; `logger = logging.getLogger(__name__)` as
`problems.py:31`):

```python
class ExpirySweep:
    """Owns this process's one background task reaping lapsed ingest leases.

    Entered by the lifespan once the runtime is published; leaving it cancels and awaits
    the task, so no pass outlives the pool it runs on.
    """

    def __init__(self, ingest: IngestService, *, interval_seconds: float, limit: int) -> None: ...

    async def run(self) -> None:
        """Sweep immediately, then every ``interval_seconds``, forever.

        A failing pass is logged with its traceback and the next pass runs on schedule;
        only cancellation ends the loop.
        """
        while True:
            try:
                report = await self._ingest.expire_lapsed(limit=self._limit)
            except Exception:
                logger.exception("ingest expiry sweep failed; the next pass runs on schedule")
            else:
                if report.expired or report.skipped:
                    logger.info("ingest expiry sweep: expired %d, skipped %d, listed %d",
                                report.expired, report.skipped, report.listed)
            await asyncio.sleep(self._interval_seconds)

    async def __aenter__(self) -> Self:
        """Start the task, named ``ingest-expiry-sweep`` so it is identifiable in a dump."""
        self._task = asyncio.create_task(self.run(), name="ingest-expiry-sweep")
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Cancel the task and await it; ``CancelledError`` is the expected outcome and is swallowed here only."""
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
```

`except Exception` does not catch `asyncio.CancelledError` (a `BaseException`), which is what
lets `__aexit__` end the loop. An empty pass logs nothing: at a 60 s cadence per replica an
"expired 0" line would be noise; a pass that did anything, or failed, is one line.

**Settings** (`settings.py`, house style: `Field` bounds as `ClassificationValue` uses, a `#:`
comment naming the intent, `HURON_*` env names):

```python
#: Seconds between two passes of this replica's ingest expiry sweep. A lapsed
#: session holds its dataset lock for at most LEASE_TTL plus this.
ingest_sweep_interval_seconds: float = Field(default=60.0, gt=0)
#: Lapsed sessions one pass flips at most; a backlog drains oldest first.
ingest_sweep_limit: int = Field(default=100, ge=1)
```

`HURON_INGEST_SWEEP_INTERVAL_SECONDS`, `HURON_INGEST_SWEEP_LIMIT`. Seconds as a float rather
than a `timedelta`, because pydantic-settings will not parse a bare `"90"` from the environment
into a `timedelta` (**proved**: only ISO 8601 `PT1M` is accepted) and `READINESS_TIMEOUT_SECONDS`
(`app.py:403`) already sets the tier's unit. No new validator beside
`_refuse_unsafe_authentication`: both bounds are single-field.

**Wiring** (`app.py` lifespan, after Design 4's additions):

```python
            app.state.runtime = ApiRuntime(..., ingest=ingest, ...)
            await _bootstrap(repository, settings)
            async with ExpirySweep(
                ingest,
                interval_seconds=settings.ingest_sweep_interval_seconds,
                limit=settings.ingest_sweep_limit,
            ):
                yield
        finally:
            if pool is not None:
                await pool.close()
```

Startup order: pool → stores → repository → facade → runtime published → bootstrap grant → task
created → `yield` (Starlette reports `startup.complete`). The task's first pass runs at the
loop's next tick, which is before the first request is served (**proved** under `TestClient`:
zero passes at `yield`, one by the time the first request's handler ran). Shutdown order: the
`async with` sits inside the `try`, so the task is cancelled and awaited **before** the `finally`
closes the pool; a pass cancelled mid-transaction leaves `asyncpg`'s `transaction()` context by
exception and rolls back on a still-open connection. `/readyz` does not consult the sweep: a
replica whose sweep is failing still serves requests correctly, another replica's sweep covers
the same rows, and taking the replica out of rotation would remove a working request path to
fix a background one.

**The contract, one sentence each.**

- *Input.* The rows `lapsed_ingest_sessions(now, limit)` returns: `state IN ('PREPARING',
  'UPLOADING','VERIFYING') AND expires_at <= now`, ordered `expires_at, id`, at most `limit`,
  with `now` read once per pass from the injected `Clock`.
- *Effect.* For each row, in its own transaction, `session.expire(now)` persisted by
  `expire_ingest_session(aborted, expected_etag=session.etag, now=now)` — the row lands in
  `ABORTED`, leaves `one_open_ingest_per_dataset`'s predicate, and the dataset's next
  `begin_ingest` re-takes the same revision number (Design 3, **proved** there).
- *Audit.* One `ingest.expired` row per flip — `actor = "system:sweep"`, `subject_kind =
  "ingest_session"`, `subject_id = session.id`, `created_at = now`, payload `{state,
  expires_at, dataset_id}` — in the flip's transaction, so neither exists without the other.
- *Bound.* At most `ingest_sweep_limit` flips per pass and one pass per
  `ingest_sweep_interval_seconds` per replica; because at most one session per dataset is open,
  a backlog is bounded by the dataset count and drains oldest first.
- *P3 boundary.* The P2 sweep changes `ingest_sessions` rows and never touches the filesystem;
  P3's sweeper deletes `.staging/{ingest_id}` for sessions that are terminal — which this
  sweep's flips make them — and never changes a session row.

**Multi-replica failure mode.** Every replica runs its own loop against the same table with no
coordination. Correctness rests on Design 3's fence: `WHERE id = $1 AND etag = $4 AND state IN
(…) AND expires_at <= $3` lets exactly one writer flip a row; every other replica — and a
client's concurrent `abort` or `renew` — gets zero rows → `PreconditionFailed` → `skipped`. The
only failure mode is **duplicated work**: N `SELECT`s per interval and up to N−1 skipped
transactions per lapsed row, each bounded by `limit`. Two costs are named and accepted: a replica
whose clock runs ahead by δ flips a lease δ early (the same δ makes its `renew` δ generous; clock
discipline is the deployment's, not this tier's); with zero replicas up nothing sweeps, which
matters to nobody because nothing can `begin_ingest` either, and the owner's `abort` releases
the lock the moment a replica returns. `PreconditionFailed` is not logged per row — under N
replicas it is the expected outcome N−1 times — only counted.

**What the sweep does not do.** It never selects, matches or flips `COMMITTING` (Design 1's Open
question 1 stands: a driver crashed there holds the lock until the reconciler). It never calls
the raw store — no `discard`, no staging deletion (Design 2 § Explicit contracts: "No store call
in P2; staging deletion is P3's"); the `.staging/{ingest_id}` directory of an expired session
stays on disk for P3's sweeper, which is why that sweeper's "terminal or expired" predicate
(`layer-raw.html:404-405`) is satisfiable at all. It writes no outbox event: expiry is an audit
fact, not something a projection consumes (`revision.committed` is the only P2 outbox kind,
Design 1). It never touches a route, `ApiRuntime` or `/readyz`.

### Explicit contracts

**Invariants.** `listed == expired + skipped`. A row is flipped only if it was lapsed at both the
list and the write, judged at one `now`. A `COMMITTING` row is never listed and cannot match the
fence. The flip and its audit row commit together. A second pass over the same rows expires
nothing (idempotent). Concurrent passes from any number of replicas are safe without a lock.
The pass holds no transaction across the list; each row's transaction is two statements. No
filesystem call, so nothing here needs `asyncify` and `test_execution_model.py` is untouched.

**Error behaviour.** `PreconditionFailed` from one row → counted, the pass continues. Any other
exception — a store outage (`asyncpg.PostgresError`, `OSError`), a `ValueError` from
`session.expire` (a live row listed as lapsed: a store bug, since the predicate and the guard are
the same comparison) — propagates out of `expire_lapsed`: rows flipped before it stay flipped,
the failing row's transaction rolled back, the rest of the list untouched until the next pass.
`run()` logs it with `logger.exception` and sleeps the interval; it never re-raises and never
retries early, so a wedged database is one log line per interval per replica, not a hot loop.
Cancellation is never caught by the pass or the loop.

**Lifecycle.** Created in the lifespan after `app.state.runtime` is published and `_bootstrap`
ran; first pass immediately; cancelled and awaited on lifespan exit before the pool closes; a pass
in flight is cancelled at its next `await` and its transaction rolls back — no drain, because the
CAS makes the next replica's or the next start's pass finish the job. The task is the only
background task the tier owns; its name is `ingest-expiry-sweep`.

**Requirements on the other designs.** The plan must carry all of these.

- **Design 4 (facade) — unanticipated.** (a) `IngestService.expire_lapsed`, `ExpiryReport` and
  `SWEEP_ACTOR` live in `service/api/ingest.py` beside the other state edges; the audit-row
  helper `abort` uses is shared with the pass. (b) The lifespan change above; `create_app` gains
  no parameter. (c) `runtime.py` is unchanged beyond Design 4's own `ingest` member.
- **Design 3 (store) — unanticipated, two items.** (a) Migration `0009` adds `CREATE INDEX
  ingest_sessions_lapsing ON ingest_sessions (expires_at) WHERE state IN
  ('PREPARING','UPLOADING','VERIFYING')` with its `DROP INDEX` in `downgrade()` and the
  `schema.sql` line `-- [db] index ingest_sessions_lapsing (expires_at) WHERE state IN (…)`.
  Reason: `lapsed_ingest_sessions`' predicate is served by neither of `0009`'s indexes nor the
  two partial unique ones (`0001:131` leads with `dataset_id`); session rows are never deleted
  (Design 3 § Lifecycle), so without it every pass on every replica is a sequential scan over
  every session ever opened. The open subset is at most one row per dataset, so the partial
  index is tiny. Not provable here (no PostgreSQL); the plan should prove it the way Design 3's
  receipts did (`enable_seqscan = off`, `EXPLAIN`). (b) `InMemoryHierarchyStore(*, clock: Clock
  | None = None)`, defaulting to `SystemClock()`, so `begin_ingest` derives `expires_at` from an
  injectable clock — today only `PostgresHierarchyStore` takes one (`hierarchy.py:1111`). Every
  test below seeds a lapsed lease by advancing one `FakeClock` shared by the store and the
  facade; nothing sleeps.
- **Design 7 (suites).** Arrange § Tests: the pass and runner tests are `unit` and async
  (`asyncio_mode = "auto"`, `pyproject.toml:148`), no `TestClient`; the lifespan test is `unit`
  over `TestClient` + `memory_stores()`; `support.memory_stores` gains `clock: Clock | None =
  None` threaded to the hierarchy store; the settings tests join `test_api_settings.py`.
- **Documentation write-back (plan milestone).** `layer-raw.html:270-271` "a crashed client
  releases the dataset lock within the TTL" → "within the TTL plus one sweep interval";
  `architecture.html:163-165`'s API row gains "reaps lapsed ingest leases" under Responsibility
  and keeps "PostgreSQL" under Writes-to; `docs/getting-started/local-development.md`'s
  environment table gains the two settings.

### Deletions

None in code: nothing exists to remove — no sweep, no ingest setting, no background task.
`pkg/catalog/ports.py:29-39`'s `Clock` stays as it is; its "injected so lease arithmetic is
testable" is exactly what this design relies on.

### Data flow

```mermaid
sequenceDiagram
    participant L as ExpirySweep.run (replica A)
    participant F as IngestService.expire_lapsed
    participant DB as PostgreSQL
    participant R as client renew / replica B
    L->>F: expire_lapsed(limit)
    F->>F: now = clock.now()
    F->>DB: SELECT … WHERE state IN (open) AND expires_at <= now ORDER BY expires_at, id LIMIT limit
    DB-->>F: [s1 (etag 3), s2 (etag 1)]
    F->>F: s1.expire(now) → ABORTED, etag 4
    F->>DB: BEGIN · UPDATE … ABORTED, etag=4 WHERE id=s1 AND etag=3 AND state IN (open) AND expires_at <= now
    DB-->>F: 1 row
    F->>DB: INSERT audit_events (ingest.expired, system:sweep, s1) · COMMIT
    R->>DB: renew s2: SET expires_at = GREATEST(expires_at, now'+ttl) WHERE state NOT IN terminals
    DB-->>R: 1 row (lease moved forward; etag unchanged)
    F->>F: s2.expire(now) → ABORTED, etag 2
    F->>DB: BEGIN · UPDATE … WHERE id=s2 AND etag=1 AND … AND expires_at <= now
    DB-->>F: 0 rows (fence: lease no longer lapsed)
    F->>DB: ROLLBACK
    F-->>L: ExpiryReport(listed=2, expired=1, skipped=1)
    L->>L: log "expired 1, skipped 1" · sleep(interval)
    Note over DB,R: Replica B's pass over the same list: s1 → 0 rows (etag moved), skipped; s2 → 0 rows, skipped.
```

### Rejected alternatives

- **A `lakectl sweep` command or a CronJob deployable** — a new image, schedule and deployable
  for one `SELECT` and one `UPDATE`; `lakectl` does not exist (Emptiness 6) and the API process
  already holds the pool, the clock and the facade.
- **Lazy flip in `begin_ingest`** — ruled out by Design 3: an audit row written by a stranger's
  request, the sweep's bound smuggled into every create, two writers of one edge.
- **Leader election (`pg_try_advisory_lock`) so one replica sweeps** — saves N−1 cheap `SELECT`s
  per interval and adds a failure mode (a lock held by a wedged replica stops every sweep); the
  CAS already makes concurrent passes harmless.
- **Driving the loop in tests by patching `asyncio.sleep`** — the pass is the unit and is called
  directly; the loop is driven with `interval_seconds=0`, where `sleep(0)` is one cooperative
  tick, so a test advances it with `await asyncio.sleep(0)` and never waits on the wall clock.

### Open questions

1. **The default interval: 60 s or `layer-raw` §9's 15 min?** *Recommended: 60 s.* The cost
   of a longer interval is dataset lock time (TTL + interval); the cost of a shorter one is one
   indexed `SELECT` per replica per interval, which at 60 s is noise. §9's 15 min belongs to the
   deletion sweeper, whose pass walks NFS and carries a fraction guard — a different cost profile.
2. **Should a deployment be able to turn one replica's sweep off** (say `0` meaning disabled) to
   designate a single sweeper? *Recommended: no.* `gt=0` keeps one deployment shape; nothing in
   `docker-compose.yml` or `architecture.html` wants a designated replica, and the CAS is what
   makes designation unnecessary. Revisit only if the duplicated `SELECT`s ever show in a plan.

### Tests

`tests/unit/test_api_ingest_expiry.py` — the pass. Fixture: one `FakeClock` (settable `now`)
shared by `InMemoryHierarchyStore(clock=…)` and `IngestService(…, clock=…)`; a dataset and a
session opened through the store's `begin_ingest` (`expires_at = T0 + LEASE_TTL`), then the
clock moved.

| Test | Asserts |
|---|---|
| `test_expire_lapsed_flips_a_lapsed_session_and_frees_its_dataset` | clock at `T0 + LEASE_TTL` → `ExpiryReport(1, 1, 0)`; the row reads `ABORTED` with `etag + 1`; `begin_ingest` on the dataset succeeds and re-takes the same revision number |
| `test_expire_lapsed_leaves_a_live_session_untouched` | clock at `T0 + LEASE_TTL − 1 s` → `(0, 0, 0)`; the row is byte-identical; `begin_ingest` → `DatasetLocked` |
| `test_expire_lapsed_never_touches_a_lapsed_committing_session` | a `COMMITTING` row, clock at `T0 + 9 days` → `(0, 0, 0)`; still `COMMITTING`; `begin_ingest` → `DatasetLocked` |
| `test_a_renewal_between_listing_and_flip_beats_the_sweep` | a delegating store double whose `lapsed_ingest_sessions` renews the listed session before returning → `(1, 0, 1)`; the row is `UPLOADING` with the renewed lease and the original etag; no audit row |
| `test_expire_lapsed_flips_at_most_limit_sessions_oldest_first` | three datasets lapsed at `T0`, `T0 + 1 min`, `T0 + 2 min`, `limit=2` → `(2, 2, 0)` flipping the two oldest; a second pass → `(1, 1, 0)` |
| `test_expire_lapsed_audits_each_flip_as_the_sweep` | one `audit_events` row per flip: `kind == "ingest.expired"`, `actor == "system:sweep"`, `subject_kind == "ingest_session"`, `subject_id == session.id`, `created_at == clock.now()`, payload `{"state", "expires_at", "dataset_id"}` |
| `test_a_flip_and_its_audit_row_commit_together` | a store double whose `insert_audit_event` raises → the exception propagates, the row is still `UPLOADING`, no audit row |
| `test_a_second_pass_over_the_same_rows_expires_nothing` | pass, pass → second report `(0, 0, 0)` and exactly one audit row |

`tests/unit/test_api_expiry.py` — the runner, with a recording double for `expire_lapsed`
(`calls`, optional `raise_on`), `interval_seconds=0`, driven by `await asyncio.sleep(0)`.

| Test | Asserts |
|---|---|
| `test_the_sweep_runs_a_pass_as_soon_as_it_starts` | after `__aenter__` and one tick, `calls == 1` with `limit` forwarded |
| `test_a_failing_pass_is_logged_and_the_next_pass_runs` | `raise_on=1`; after six ticks `calls >= 2`; `caplog` holds one `ERROR` record with the traceback from `huron.service.api.expiry` |
| `test_leaving_the_context_cancels_and_awaits_the_task` | after `__aexit__`, no task named `ingest-expiry-sweep` in `asyncio.all_tasks()`; `calls` is unchanged over three further ticks |
| `test_cancellation_during_a_pass_does_not_wait_for_it` | a double whose pass awaits an hour; `__aexit__` returns within the same tick; the task reports `cancelled()` |

`tests/unit/test_api_app.py`:

| Test | Asserts |
|---|---|
| `test_the_lifespan_sweeps_lapsed_sessions_before_serving_the_first_request` | `memory_stores(clock=FakeClock(now − 3 h))` seeded with one open session; `create_app(settings, stores=…)`; the first request `GET /api/v1/ingest-sessions/{id}` reads `ABORTED`; the store holds one `ingest.expired` row |

`tests/unit/test_api_settings.py`:

| Test | Asserts |
|---|---|
| `test_defaults_construct_a_working_development_configuration` (extended) | `ingest_sweep_interval_seconds == 60.0`, `ingest_sweep_limit == 100` |
| `test_sweep_interval_must_be_positive` | `0` and `-5` → `ValidationError` "greater than 0" |
| `test_sweep_limit_must_be_at_least_one` | `0` → `ValidationError` "greater than or equal to 1" |

Store-level coverage of the list, the bound and the fence on both backends is Design 3's
`scenario_15_expiry_flips_lapsed_sessions_only`; the tests above do not repeat it.

### Receipts

- Scratchpad `d6_sweep_proof.py` (`PYTHONASYNCIODEBUG=1 uv run python -W always …`): a FastAPI
  lifespan publishing `app.state.runtime` then `async with ExpirySweep(...)` around `yield`,
  under `TestClient`. **P1** passes at `yield`: 0; passes seen by the first request's handler:
  1 — the task starts after the runtime and its first pass precedes the first request. **P2**
  at lifespan exit `task.done() == cancelled() == True`, the loop's `finally` ran, zero
  warnings recorded (no "Task was destroyed but it is pending"). **P3** (`asyncio.run(...,
  debug=True)`, `interval_seconds=0`, pass 1 raises): six cooperative ticks → 6 passes, the
  traceback logged once by `logger.exception`; after `__aexit__` three more ticks add no pass.
  **P4** a pass that awaits an hour, cancelled at the next tick: `cancelled() == True`, the
  `finally` ran, `__aexit__` returned without waiting.
- Same script, settings: a `timedelta` field refuses the env string `"90"` and `"0"`/`"-5"` with
  "day identifier in duration not correctly formatted" and accepts only `PT1M`; the float shape
  `Field(default=60.0, gt=0)` accepts `90`, `0.5`, refuses `0`, `-5` ("greater than 0") and
  `abc`; `Field(default=100, ge=1)` refuses `0`, accepts `1`, `500`.
- Inspection: `Containerfile:30` runs `uvicorn … main:app` with no `--workers`, so one process per
  container; `architecture.html:163` API "≥2, stateless"; `docker-compose.yml:110-130` one `api`
  service; `Makefile:50` `--reload` for development. No index serves `expires_at` in
  `0001`–`0008` (`grep -n expires_at migrations/`) nor in Design 3's `0009` (`ingest_sessions_dataset`,
  `ingest_sessions_parent_revision` only). `InMemoryHierarchyStore` takes no clock;
  `PostgresHierarchyStore(pool, *, clock=None)` does (`hierarchy.py:1111-1120`).
- Not run: anything against PostgreSQL (the partial index's plan); the sweep against the real
  `IngestService` (Design 4's class does not exist yet); the multi-replica race itself (its
  arbiter is Design 3's fence, proved there).

## Design 7 — Test strategy for the P2 gate

Arranges the tests Designs 1–6 named into suites, fixtures and CI so that every clause of the P2
gate (`roadmap.html:341-347`) and milestone 8's gate (`:567-569`) is proven by a named test, and
adds the four tests no design named (file-level resume, the HTTP crash matrix, dedup 1-of-500, the
full-size 9 GiB round trip). Nothing below re-decides a design; where two designs collided the
resolution is in § Collisions and the plan carries it. Suite semantics are
`docs/getting-started/testing.md`'s: `unit` needs nothing external, `contract` needs a container
runtime through testcontainers, `integration` the Compose stack, `acceptance` a phase gate end to
end. Every marker is registered (`pyproject.toml:150-155`, receipt: `pytest --markers`); today
`unit` collects 674, `contract` 10, `integration` and `acceptance` 0 (receipts).

### Gate coverage table

"Needs" is the infrastructure beyond `uv sync`: **none**, **runtime** (a container runtime for
testcontainers' `postgres:16`), or **disk** (≥ 10 GiB free, no services).

| # | Clause | Suite | Fixtures | Module · test | Asserts | Needs |
|---|---|---|---|---|---|---|
| P1 | Round trip: a tree with NFC/NFD pairs ingests and downloads byte-identically | `unit` | `client`, `stores`, `tmp_path`, `IngestClient` | `test_api_revisions.py` · D5 `test_file_download_round_trips_nfc_zero_byte_and_eight_level_files_byte_identically` (the NFC half: `payload/é/café.txt` up through routes 1/5/6/7/8, down through R3, bytes equal, `filename*=utf-8''caf%C3%A9.txt`); D5 `test_file_download_refuses_traversal_and_non_nfc_spellings_before_touching_storage` and D4 `test_create_refuses_every_manifest_rule_with_its_documented_code` (the NFD half: the decomposed spelling of the same name is `PATH_NOT_NFC` at intake and at download) | the NFC spelling is stored and served byte-identically; the NFD spelling of the same name never reaches storage | none |
| P2 | … a zero-byte file | `unit` | as P1 | same D5 R3 test (`Content-Length: 0`, `ETag` = `sha256(b"")`); D1 `test_catalog_ingest.py::test_a_zero_byte_file_is_one_part_that_completes_on_the_empty_digest`; D5 `test_catalog_documents.py::test_decode_manifest_round_trips_nfc_zero_byte_and_eight_level_entries_with_the_same_identity` | one part, completes on the empty digest, downloads as zero bytes | none |
| P3 | … 8-level nesting | `unit` | as P1 | same D5 R3 test (`payload/d1/…/d8/leaf.bin`); same D5 document test; D2 `test_rawstore_store.py::test_write_part_fsyncs_the_file_and_every_directory_up_to_the_payload_root` | the eight directories are created `0o700`, fsynced, sealed `0o555`, and the leaf downloads byte-identically | none |
| P4 | … a 9 GiB file | `acceptance` | `client`, `stores`, `tmp_path`, `IngestClient`, `sparse_file`, `zeros_sha256`; real `PART_BYTES` | `tests/acceptance/test_raw_ingest_gate.py::test_a_nine_gib_file_round_trips_byte_identically_after_an_interrupted_upload_resumes` (§ Techniques); unit twins at `PART_BYTES` patched small: D1 `test_upload_plan_part_counts_follow_the_part_size` (9 GiB at 64 MiB → 144) and D4 `test_a_multipart_upload_resumes_without_resending_completed_parts` | 144 parts, `finish_file` digest equals the declared digest, R3 streams 9 GiB back with `sha256(body)` equal and `Content-Length == 9 · 2³⁰` | disk |
| P5 | Crash matrix: kill after every protocol step | `unit` | `client`, `stores`, `IngestClient`, `crash_on`, `fsync_log`, `monkeypatch` | `tests/unit/test_api_ingest_crash_matrix.py::test_a_crash_after_each_commit_step_leaves_the_named_state_and_the_retry_converges` (parametrized over the eight rows of § Techniques) and `test_a_session_left_committing_before_the_rename_completes_on_the_next_commit`; primitive level: D2's six crash tests in `test_rawstore_commit.py` / `test_rawstore_store.py` | after each injected fault: on-disk state is the `layer-raw.html` §5 row named for that step, the session row is what D4's rule prescribes, and the retry or a new session converges to exactly one revision | none |
| P6 | staging crashes invisible | `unit` | as P5 | matrix rows 1–5 (`final` absent, `GET /revisions/{id}` for the would-be revision 404, `latest_committed_revision` unchanged); D2 `test_a_crash_in_the_tree_fsync_attempts_no_rename`, `test_a_crash_in_the_rename_leaves_staging_intact_and_final_absent` | nothing under `raw/revision/` changes before the rename returns | none |
| P7 | … and swept | — | — | **excluded** (§ Excluded clauses) | — | — |
| P8 | post-rename crash imported as an orphan | — | — | **excluded** | — | — |
| P9 | … with no duplicate on retry | `unit` | as P5 | matrix row 6 (parent-fsync fault → 500, retry → 201, one revision row, one envelope directory); D2 `test_commit_envelope_retry_after_the_rename_is_silent_and_reseals_the_root`; D5 `test_a_commit_retry_past_the_rename_rebuilds_the_record_from_the_marker` | the retry publishes nothing new and takes its instants from `COMMITTED` | none |
| P10 | Resume re-sends only incomplete files | `unit` | `client`, `stores`, `IngestClient` ×2 | `test_api_ingest_sessions.py::test_a_new_client_resumes_from_the_session_view_and_re_sends_only_pending_files` (added here; § Techniques) | a second client reading `GET` sends parts only for `PENDING` files; a PUT to the `COMPLETE` file is 409 `ILLEGAL_INGEST_TRANSITION` with the body never iterated | none |
| P11 | Two racing `BeginIngest` calls: exactly one wins | `contract` | `PostgresContainer`, `_migrate`, `_wait_until_a_backend_blocks_on` | D3 `test_hierarchy_store.py::test_two_concurrent_begin_ingest_calls_serialize_on_the_dataset_row` | one `IngestSession`, one `DatasetLocked` with the winner in `context`, one open row in `ingest_sessions` | runtime |
| P12 | 100 sequential ingests number 1..100 gap-free | `contract` + `unit` | `_INGEST_SCENARIOS`, `FakeClock` | D3 `hierarchy_contract.py::scenario_16_a_hundred_sequential_ingests_number_gap_free`, run by `test_hierarchy_store.py::test_the_postgres_hierarchy_store_against_a_migrated_database` and by `test_hierarchy_store_memory.py::test_a_hundred_sequential_ingests_number_gap_free` | revision numbers `1..100`, 100 `COMMITTED` + 10 `FAILED` sessions, on both backends | runtime / none |
| P13 | Replayed commit returns the same revision | `unit` + `contract` | `IngestClient`; `_INGEST_SCENARIOS` | D4 `test_a_replayed_commit_returns_the_same_revision`; D3 `scenario_14_the_commit_transaction_is_atomic_and_replays` | same key → 201 with the same `id` even under a stale `If-Match`; `Replay("revision", id)` on both backends | none / runtime |
| P14 | Dedup: 1 changed file of 500 uploads exactly 1; the other 499 hardlink | `unit` | `client`, `stores`, `tmp_path`, `IngestClient` | `tests/unit/test_api_ingest_dedup.py::test_one_changed_file_of_five_hundred_uploads_one_and_links_the_rest` (added here; § Techniques); the 1-file twin is D4 `test_verify_links_parent_files_and_moves_to_verifying` | plan: 499 `hardlink`/`part_count 0`, 1 `upload`; PUTs issued == 1; after commit 499 paths have `st_nlink == 2` and `samefile` with the parent, 1 has `st_nlink == 1` | none |
| P15 | the new revision is independently complete | `unit` | as P14 | `test_api_ingest_dedup.py::test_the_linked_revision_survives_the_parent_s_names_being_removed` | after unlinking every parent payload name, all 500 files download byte-identically through R3 and the 499 read `st_nlink == 1`; every file `0o444`, every directory `0o555` | none |
| P16 | Every path-rejection rule produces its documented error code | `unit` | `client`, `stores` | D4 `test_create_refuses_every_manifest_rule_with_its_documented_code` (`PATH_OUTSIDE_PAYLOAD`, `PATH_NOT_NFC`, `PATH_TOO_LONG`, `PATH_TRAVERSAL`, `PATH_CONTROL_CHARS`, `PATH_SEPARATOR`, `PATH_COLLISION` over route 1); D5 `test_file_download_refuses_traversal_and_non_nfc_spellings_before_touching_storage` (the six 400s over R3, before storage); D1 `test_catalog_properties.py::test_validate_manifest_refuses_every_non_nfc_path` | the 7 manifest rows of `api.html` §7 `:219-229` each produce their code over HTTP; the 8th row, `PATH_RULE_VIOLATION`, has no manifest-path raise site (`manifest.py:224-235` always names a specific code) and is already pinned on the wire by `test_api_problems.py` | none |
| M1 | An interrupted multi-GB upload resumes without re-sending completed parts | `acceptance` | as P4 | the P4 acceptance test: the first client stops after part 50 of 144; a second `IngestClient` resumes from `GET` | parts 1–50 are never re-sent (the helper's `put_count` is 144 across both clients); `completed_parts == [1..144]` before `/complete` | disk |
| M2 | two sessions racing one dataset serialize on the lock | `unit` | `client`, `stores` | D4 `test_create_returns_the_plan_and_locks_the_dataset` | the second create → 409 `DATASET_LOCKED` with `session_id`, `state`, `expires_at` of the holder (the PostgreSQL arbiter is P11) | none |
| M3 | a committed revision appears in the catalog | `unit` | `client`, `stores`, `IngestClient` | D4 `test_commit_publishes_the_revision_and_its_events`; D5 `test_get_revision_returns_the_view_and_hides_an_invisible_one` | the store holds the `COMMITTED` session and the revision row; `GET /revisions/{id}` returns the nine-member view; releases can tag it | none |
| M4 | … the search projection | — | — | **excluded** | — | — |
| M5 | … and the audit stream | `unit` | as M3 | D4 `test_commit_publishes_the_revision_and_its_events` | exactly one `revision.committed` audit row and one outbox row (the outbox row is P2's half of M4) | none |

**Excluded clauses.**

- **P7 "staging crashes … swept."** The staging sweeper is P3 (`roadmap.html` P3 row; `layer-raw.html`
  §9); Design 6 states "No store call in P2; staging deletion is P3's" (§ Design 6 › Explicit
  contracts). P2 proves the precondition — a staging crash leaves the envelope invisible under
  `.staging/` (P6) and the session expires (D6's tests) — and nothing deletes it.
- **P8 "post-rename crash imported as an orphan."** Importing a `COMMITTED` marker into
  `dataset_revisions` is the reconciler (P3, `layer-raw.html:296-299`). P2 proves the retry half
  (P9); the orphan that is never retried stays an orphan until P3.
- **M4 "… appears in the search projection."** The outbox consumer and the LanceDB tables are P4.
  P2 proves the outbox row exists and carries the revision identity (M5; D1
  `test_revision_committed_event_carries_the_revision_identity`).
- **`layer-raw.html` §5 step 8's "retried by the reconciler."** Matrix row 8 proves the
  best-effort write and that its failure leaves the 201 intact (D5's test); regeneration is P3.

Drift 1 ("implemented and unit-tested") becomes true through D1's 25 + 5 property tests and D2's
40 tests; no gate clause maps to it, and the roadmap write-back is the plan's.

### Techniques

**The 9 GiB file.** One test, `acceptance` only. Source: `sparse_file(tmp_path / "nine.bin",
9 * 2**30)` — `f.seek(size - 1); f.write(b"\0")` — costs 16 KiB of disk (receipt: apparent
9,663,676,416 bytes, 32 blocks) and reads as zeros; `zeros_sha256(9 * 2**30)` hashes it once in
64 MiB chunks (receipt: 7.33 s on this machine). The manifest declares `size = 9 · 2³⁰` and that
digest (under `DEFAULT_MAX_FILE_BYTES = 10 GiB`, `manifest.py:32`). The client streams each part
from the sparse file as a generator body with `Content-Length = PART_BYTES` (route 5 requires it)
— 144 parts at the real `PART_BYTES` (`compute_upload_plan`: ⌈9 · 2³⁰ / 2²⁶⌉ = 144). The
**server writes 9 GiB of real bytes** — `os.pwrite` of zeros allocates, and the store cannot know
they were holes — so the run needs ≥ 10 GiB free; it could not be rehearsed here (receipt: 5.8 GiB
free). Interruption (M1): the first `IngestClient` stops after part 50; a second one `GET`s the
session and sends parts 51–144 only; `put_count` summed over both clients is 144. Then
`/complete` (route 6 re-hashes 9 GiB — one more ~10 s), `/verify`, `/commit`, and R3 streamed with
`client.stream("GET", …)` hashed in 64 MiB chunks, never materialised. Budget: hashing ×4 (client
source, `write_part`, `finish_file`, download) ≈ 40 s plus 9 GiB written and read at runner disk
speed → 3–6 minutes; `timeout-minutes: 30` on the job. The `unit` suite exercises the same
code path at `PART_BYTES` patched to 4 with a 10-byte file (D4's multipart tests) and the plan
arithmetic at true size (D1's `144`); nothing in `unit` touches a large file.

**The crash matrix** — over HTTP through `IngestClient.commit`, one parametrized test, one row per
on-disk step of Design 2's sequence plus Design 3's transaction and Design 5's index. Injection is
D2's `crash_on(monkeypatch, name, *, call, errno_)`; because `crash_on` and `fsync_log` both patch
`os.fsync`, fsync-indexed rows first run a **rehearsal commit** under `fsync_log` in a sibling
dataset (same manifest, same tree shape), take `L = fsync_log(...)`, and compute
`call_of(path) = L.index(path) + 1` inside a fresh `monkeypatch.context()`. `write_document`
replaces through `os.replace` (`store.py:299`), so document rows target `"replace"`, not
`"rename"`; the one `os.rename` in the path is the envelope publication (`commit.py:152`).
"DB after" is D4's rule (§ Design 4 › Tests, the two crash tests): an `OSError` with `final`
absent → `session.fail()`, `ingest.failed` audited, the number freed; with `final` present →
stays `COMMITTING`, 500, retry converges.

| Row | Step (D2 §"The commit sequence" / layer-raw §5) | `crash_on` target | On disk afterwards | Session row | Retry expectation |
|---|---|---|---|---|---|
| 1 | documents: `manifest.json` replace | `("replace", call=1)` | staging intact; create-time `manifest.json` bytes intact; no `metadata.json`; `final` absent (§5 row 4–5) | `FAILED`, etag +1, `ingest.failed` | new session re-takes the same number; `GET /revisions/{id}` 404 |
| 2 | documents: `metadata.json` replace | `("replace", call=2)` | `manifest.json` rewritten identically; no `metadata.json`; `final` absent | `FAILED` | as row 1 |
| 3 | `seal` | `("chmod", call=1)` | both documents present; payload modes unchanged (`0o600`); `final` absent | `FAILED` | as row 1 |
| 4 | `COMMITTED` replace | `("replace", call=3)` | contents sealed (`0o444`/`0o555`), root `0o700`, no marker; `final` absent | `FAILED` | as row 1 |
| 5 | `fsync_tree` | `("fsync", call=call_of(first payload path after L.index(staging/"COMMITTED")))` | marker present; `final` absent; no rename attempted (`final.parent` unchanged) | `FAILED` | as row 1 |
| 6 | `os.rename(staging, final)` | `("rename", call=1)` | staging intact and complete; `final` absent | `FAILED` (D4's `crash_on("rename")` test, folded here) | as row 1 |
| 7 | parent fsync after the rename | `("fsync", call=call_of(final.parent))` | `final` published with `COMMITTED`; staging gone; root may still be `0o700` (§5 row 6) | `COMMITTING`, 500 | `/commit` with the new etag → 201; one revision row; `committed_at` equals `COMMITTED`'s (D4's post-rename test, folded here; D5 extends) |
| 8 | PostgreSQL transaction (D3 step 7) | `monkeypatch` the in-memory writer's `insert_outbox_event` to raise once | `final` published, root `0o555` | `COMMITTING`, 500; no revision row, no audit row (the in-memory transaction rolls back — D3 `scenario_14` proves the same on PostgreSQL) | retry → 201, exactly one revision, one outbox row |
| 9 | `INDEX.json` best-effort (D5 step 8) | D5's injected `atomic_replace` failure | revision published; `INDEX.json` absent or previous | `COMMITTED`, 201 already returned | D5 `test_a_commit_writes_the_index_and_a_second_commit_extends_it`; regeneration is P3 |

A process **kill** runs no handler, so a killed pre-rename commit leaves `COMMITTING` with staging
intact — the state rows 1–6 never produce. `test_a_session_left_committing_before_the_rename_completes_on_the_next_commit`
seeds it the way D4 seeds lapsed rows: drive to `VERIFYING` through the client, rewrite the
in-memory row to `COMMITTING` with etag +1 (D1 Open question 1 / D4 Open question 3's re-entry),
then `/commit` with that etag → 201, documents rewritten (D2's replace semantics), one revision.
Row 7 already *is* the post-rename kill state (no flip happens). Storage state under a fault and
under a kill is identical at each row because the injection sits on the same `os` call.

**Dedup 1-of-500.** Revision 1: 500 one-part files `payload/f/{i:04d}.bin` with distinct 32-byte
content, uploaded by `IngestClient.upload_revision(files)` (create → 500 PUTs → verify → commit).
Revision 2: the same manifest with file 250's bytes changed. Assertions, in order: the create view
has 499 entries `action == "hardlink"`, `part_count == 0` and one `upload`; `upload()` issues
exactly one PUT (`put_count == 1`); `/verify` → 500 `COMPLETE`; after commit, for the 499:
`os.stat(new).st_nlink == 2` and `os.path.samefile(old, new)`; for file 250: `st_nlink == 1` and
new bytes; every payload file `S_IMODE == 0o444`, every directory below the root `0o555`, both
roots `0o555` (D2 `test_seal_after_hardlink_leaves_the_shared_inode_read_only_for_both_revisions`
at the primitive level). Independence (P15): `os.chmod` the parent envelope's directories `0o755`
and `os.unlink` each of its 500 payload names; then every one of the 500 new paths downloads
byte-identically through R3 and the 499 read `st_nlink == 1`. Budget ≤ 10 s in `unit` (500
`write_part` calls each fsync a file and two directories; receipt: hardlinks and `0o444` behave as
asserted on this filesystem).

**Racing `begin_ingest`** (contract, PostgreSQL only). D3's arbiter is statement 1 of
`begin_ingest`, `SELECT id FROM datasets WHERE id = $1 FOR UPDATE` (§ Design 3 › Target design).
The house pattern is `test_concurrent_identical_claims_serialize_on_the_row`
(`test_hierarchy_store.py:542-608`): the first transaction holds its row lock open until a third
connection sees the second backend `wait_event_type = 'Lock'` in `pg_stat_activity`, then
commits. Generalise `_wait_until_a_backend_blocks_staking_the_claim` (`:510-540`) to
`_wait_until_a_backend_blocks_on(pool, *, query_fragment: str, timeout: float = 5.0)`; the
existing caller passes `"INSERT INTO idempotency_records"`, the new test passes
`"FROM datasets WHERE id = $1 FOR UPDATE"`. First attempt: `async with store.transaction() as w:
session = await w.begin_ingest(...)`, set an `asyncio.Event`, await the wait helper, exit (commit).
Second attempt: await the event, `begin_ingest` → blocks on the row lock → after the commit,
statement 2 sees the open row → `DatasetLocked`; the coroutine returns the exception. Assert one
session, one `DatasetLocked` whose `context["session_id"]` is the winner's, and
`SELECT count(*) FROM ingest_sessions WHERE dataset_id = $1` = 1 through the pool. Deterministic:
the second call is proven blocked before the first commits, so no timing assumption is made.

**Resume — "only incomplete files re-sent."** Two upload files A (one part) and B (three parts at
`PART_BYTES = 4`). Client 1 sends A and B's part 1, then is discarded. Client 2 — a fresh
`IngestClient` for the same subject — calls `GET`, receives `A: COMPLETE, [1]` and `B: PENDING,
[1]`, and `upload()` sends only B's parts 2 and 3 (`put_count == 2`), then `/complete` → all
`COMPLETE`, `/verify` → 200. A deliberate PUT of A's part 1 afterwards is 409
`ILLEGAL_INGEST_TRANSITION` and its body generator is never iterated (D4's body-tracking pattern).
Part-level resume is D4's multipart test; full size is M1.

### Fixtures

All shared objects and where they live; each names the fixture it extends or replaces.

| Object | Module | Signature | Extends / replaces |
|---|---|---|---|
| `memory_stores` | `tests/unit/support.py` | `def memory_stores(*, clock: Clock \| None = None) -> ApiStores` — threads `clock` to `InMemoryHierarchyStore(clock=clock)` (D6 back-contract on D3) | extends `support.py:15` |
| `FakeClock` | `tests/unit/support.py` | `@dataclass(slots=True) class FakeClock:` `_now: datetime`; `now() -> datetime`; `advance(delta: timedelta) -> None`; `set(instant: datetime) -> None` | replaces `_FakeClock` at `tests/unit/test_hierarchy_store_memory.py:54` and `tests/contract/test_hierarchy_store.py:102` (both deleted) |
| `crash_on` | `tests/unit/support.py` | `def crash_on(monkeypatch: MonkeyPatch, name: str, *, call: int = 1, errno_: int = errno.EIO) -> list[object]` (D2; `name` is any `os` attribute — `replace`, `rename`, `fsync`, `link`, `pwrite`, `chmod`) | new |
| `fsync_log` | `tests/unit/support.py` | `def fsync_log(monkeypatch: MonkeyPatch) -> list[Path]` (D2) | new |
| `IngestClient` | `tests/ingest_client.py` (top level, beside `hierarchy_contract.py`, so `unit` and `acceptance` share it) | `class IngestClient:` `__init__(self, client: TestClient, *, subject: str = "bob")`; `developer_dataset() -> tuple[str, str]`; `create(dataset_id: str, files: Sequence[ManifestFile], *, key: str \| None = None) -> Response`; `put_part(file_id: str, part: int, body: bytes \| Iterable[bytes], *, content_length: int \| None = None) -> Response`; `upload(session: Mapping[str, Any], source: Callable[[str], BinaryIO]) -> int` (sends every missing part of every `PENDING` upload file, returns PUTs issued); `complete(file_id)`, `verify(session_id) -> Response`, `commit(session_id, etag: int, metadata: Mapping[str, Any], *, key=None) -> Response`, `abort(session_id)`, `get(session_id)`, `download(revision_id, path) -> Response` (streamed); `upload_revision(dataset_id, files) -> dict` (create → upload → verify → commit); `put_count: int`. Module functions `manifest_file(path: str, data: bytes) -> ManifestFile`, `declared_file(path: str, size: int, sha256: str) -> ManifestFile`, `sparse_file(path: Path, size: int) -> Path`, `zeros_sha256(size: int) -> str` | replaces D4's private `_developer_dataset`, `_manifest`, `_session`, `_put_part`, `_commit` and D5's `_committed`, `_reader` (§ Collisions 2) |
| `client`, `stores` | each API test module | as `tests/unit/test_api_catalog_hierarchy.py:71-89`: `stores() -> ApiStores` and `client(tmp_path, stores) -> Iterator[TestClient]` entering `TestClient` as a context manager | house pattern (no `conftest.py` exists; none is added) |
| `_INGEST_SCENARIOS` | `tests/contract/test_hierarchy_store.py` | `tuple[Callable[[HierarchyStore, FakeClock], Awaitable[None]], ...]` of D3's `scenario_10`–`scenario_16`, run by `_assert_every_scenario` after `_SCENARIOS`, `_reset_hierarchy_tables` between each; the in-memory twin is seven `async def test_…` functions in `test_hierarchy_store_memory.py`, one per scenario, each `InMemoryHierarchyStore(clock=FakeClock(...))` | extends `_SCENARIOS` (`:222-232`) without changing the nine two-argument scenarios |
| `_HIERARCHY_TABLES` | `tests/contract/test_hierarchy_store.py:71-78` | gains `ingest_files`, `ingest_sessions`, `audit_events`, `outbox_events` (D3) | extends |
| `_wait_until_a_backend_blocks_on` | `tests/contract/test_hierarchy_store.py` | `async def _wait_until_a_backend_blocks_on(pool: asyncpg.Pool, *, query_fragment: str, timeout: float = 5.0) -> None` | replaces `_wait_until_a_backend_blocks_staking_the_claim` (`:510`) |
| `PostgresContainer` + `_migrate` | `tests/contract/test_hierarchy_store.py:84-95` | unchanged; D3's race test and the `0009` pins in `test_catalog_store.py` use them as the existing tests do | unchanged |
| `_property` | `tests/unit/test_catalog_properties.py:48` | `settings(deadline=None, max_examples=200)` — D1's five property tests use it unchanged (hypothesis 6.165.10, receipt) | unchanged |
| `PART_BYTES` patch | multipart `unit` tests | `monkeypatch.setattr(huron.pkg.catalog.ingest, "PART_BYTES", 4)`; effective only under § Collisions 4 | D4 |

### Suite placement and CI

| Marker | Where it runs | Command | Change |
|---|---|---|---|
| `unit` | `ci.yml` job `unit` | `uv run pytest --cov=src/huron --cov-report=term-missing` | none to the job; gains D1–D6's tests plus the matrix, dedup, resume modules |
| `contract` | `ci.yml` job `contract` | `uv run pytest -m contract` | none to the job; gains one container start (D3's race test, ~10 s) and the `_INGEST_SCENARIOS` loop inside the existing container |
| `integration` | `ci.yml` job `integration` | unchanged; still collects nothing | none — no P2 clause needs the Compose stack |
| `acceptance` | **new** `.github/workflows/acceptance.yml` | `on: {schedule: [{cron: "0 3 * * *"}], workflow_dispatch: {}}`; one job `acceptance` on `ubuntu-latest`, `timeout-minutes: 30`; steps: checkout, `astral-sh/setup-uv` (same pinned SHA as `ci.yml`), `uv sync --all-groups`, `df -h .` (the disk receipt in the log), `uv run pytest -m acceptance --no-header -q` | `ci.yml` itself is unchanged (Open question 1) |

- **`pyproject.toml`.** No marker change: all four are registered (`:150-155`) and `-m acceptance`
  on the command line overrides `addopts`' `-m unit` (receipt: `--co -m acceptance` collects
  nothing without error). No `[tool.coverage.run]` exists and none is added; the acceptance job
  runs without `--cov`. **Coverage ratchet:** the plan's last milestone re-measures and raises
  `fail_under` (`:263`, today 89) to the measured value rounded down, per the comment at
  `:260-262`; with every touched file at 100 % and ~150 new unit tests it should land ≥ 90 — the
  plan sets the number from the measurement, not from this design.
- **`radon` / `complexipy`.** No threshold moves. The ceilings every P2 function must stay under
  are the gate's as configured: cyclomatic grade B (CC ≤ 10, `radon cc --min C` prints nothing),
  cognitive complexity ≤ 15 (`complexipy`), and maintainability rank A (MI ≥ 20, `radon mi
  --min B` prints nothing). Neither tool has a per-file ceiling and none is proposed. Two
  consequences: (a) route 5's operation list (§ Design 4 › Target design: session fence, three
  refusals, `Content-Length` check, `write_part`, `part_received`, the single-part `completed`
  branch with `discard_file`, the ledger CAS retry, `renew`) is more than ten decision points, so
  `IngestService.upload_part` must be three functions — a pre-read refusal that returns the target
  (file, offset, length) or raises, the stream observation, and the ledger update with its
  retry — with the route handler doing nothing but dependency resolution and delegation; (b)
  `stores/hierarchy.py` is the module nearest the MI floor (receipt: A, 30.06 at 1,523 lines) and
  D3 adds the ingest methods to it — the plan measures `radon mi -s` after D3's milestone (Open
  question 5).
- **Baseline.** `radon cc src/huron --min C` on `main` today prints four C-grade items
  (`ApiSettings`, `ApiSettings.refuse_unsafe_combinations`, `Binding.covers`,
  `parse_revision_dir`) and exits 0; `make lint` passes because radon's exit status ignores
  findings, while `.claude/commands/implement-markdown.md:59` demands empty output (Open
  question 3).
- **`Makefile`.** One target added for symmetry with `test`: `test-acceptance: uv run pytest -m
  acceptance`. `lint` unchanged.
- **Hypothesis.** No profile is registered anywhere (receipt: no `register_profile`); D1's
  properties run under `_property` on every `unit` run.
- **Roadmap write-back (plan milestone).** The P2 row's tag flips from `partial` only with the
  acceptance run's receipt (the workflow's URL) recorded in `design/roadmap.html`; the `unit` and
  `contract` jobs prove the other 19 mapped clauses on every push.

### Collisions resolved

1. **`FakeClock`.** Two private copies exist (`test_hierarchy_store_memory.py:54`,
   `test_hierarchy_store.py:102`) and D6 names a third. One public `FakeClock` in
   `tests/unit/support.py`; both privates deleted; the contract module imports it (it already
   imports `tests.hierarchy_contract`). D3's and D6's text stand; the plan deletes the copies.
2. **D4's private helpers reused by D5.** D5 "reuses Design 4's `_developer_dataset`, `_session`,
   `_put_part`, `_commit`" — private functions imported across test modules. Both yield to
   `tests/ingest_client.py::IngestClient`; the matrix, dedup, resume and acceptance modules use
   it too. D4's and D5's assertions are unchanged.
3. **D4's two commit-crash tests vs the matrix.**
   `test_a_commit_failure_before_the_rename_fails_the_session` and
   `test_a_commit_retry_after_a_crash_past_the_rename_completes_the_catalog` become rows 6 and 7
   of `test_api_ingest_crash_matrix.py`; D4 yields the two names, their assertions survive
   verbatim. D5's `test_a_commit_retry_past_the_rename_rebuilds_the_record_from_the_marker`
   "extends Design 4's crash test" → extends row 7.
4. **The `PART_BYTES` patch.** D4 patches `ingest_module.PART_BYTES`; D1's `compute_upload_plan(…,
   part_bytes: int = PART_BYTES)` binds its default at import, so the patch is a no-op unless the
   service reads the module attribute at call time. D4 yields: `IngestService` calls
   `compute_upload_plan(manifest, parent, part_bytes=ingest.PART_BYTES)` and derives route 5's
   `offset`/`length` and the view's `part_bytes` from the same read. D1 is unchanged.
5. **D3's scenarios "appended to `_SCENARIOS`."** The runner calls `scenario(store,
   seed_revision)` (`:257`); scenarios 10, 12 and 15 advance time. They go in a second tuple
   `_INGEST_SCENARIOS` with signature `(store, clock)` and their own loop; the nine two-argument
   scenarios are untouched. D3 yields the placement, not the scenarios.
6. **`_HIERARCHY_TABLES`.** D3 says +4 tables; D5 says "unchanged". D3 wins — D5's statement was
   about its own tests, which are `unit`.
7. **`crash_on`'s example list.** D2 lists `rename`, `fsync`, `link`, `pwrite`; the document
   writes go through `os.replace`. The helper is generic over `os.<name>`; the matrix passes
   `"replace"` and `"chmod"`. No design changes.
8. **`create_app(clock=)`.** D4 says it *may* grow one for D6; D6's lifespan test back-dates the
   store's clock instead. `create_app` is unchanged.
9. **Gaps filled, not collisions.** No design named a file-level resume test (P10), the HTTP
   crash matrix as a matrix (P5), the 500-file dedup (P14/P15) or the full-size round trip
   (P4/M1); the four modules above are this design's additions.

### Open questions

1. **Does the owner want a nightly full-size 9 GiB job at all?** Options: (A) the separate
   `acceptance.yml` on a nightly schedule plus manual dispatch — *recommended*: 3–6 minutes and
   10 GiB of runner disk per run, invisible to PR feedback, and a permanent receipt for the
   roadmap; (B) an `acceptance` job in `ci.yml` on every push to `main` — the same cost on every
   merge, for a clause whose code path `unit` already exercises at small `PART_BYTES`; (C) no CI
   job, run manually once for the P2 write-back — cheapest, but the roadmap's `done` tag would rest
   on a receipt nothing re-checks.
2. **What "full stack" means for P2's acceptance test.** (A) in-process `TestClient` +
   `memory_stores()` + the real `PosixRawStore` — *recommended*: the P2 clauses are storage and
   protocol semantics, all of which this proves, and the PostgreSQL half is the `contract` suite;
   (B) `httpx` against the Compose stack — adds `docker compose up` and a volume for 9 GiB to CI
   and proves composition, which no P2 clause asks for; belongs to `integration` when a clause
   needs it.
3. **The four pre-existing radon C-grade items.** The gate text (`implement-markdown.md:59`) makes
   them a baseline failure for every P2 task, though `make lint` passes. (A) the plan's first
   milestone reduces the four to B by extracting predicates — *recommended*: an hour of work that
   removes a standing ambiguity between the gate as written and as run; (B) the owner records the
   four as accepted baseline for the verifier — cheaper now, re-litigated on every run.
4. **Dedup 500 in `unit`.** The budget above is ≤ 10 s; if the runner measures more, (A) keep it
   in `unit` at 500 — *recommended*: it is the gate's number and the only suite that runs on every
   PR; (B) move it to `acceptance`; (C) shrink the count — rejected: it would no longer be the
   clause.
5. **`stores/hierarchy.py`'s maintainability rank.** If `radon mi -s` after D3's milestone reads
   below 25, (A) the ingest methods move to `stores/ingest.py` behind the same port —
   *recommended*: keeps rank A with margin and is the file split the module's size already
   invites; (B) leave it and accept a later forced split when it crosses 20.

### Receipts

- Sparse file (scratchpad, APFS `/System/Volumes/Data`): `f.seek(9*2**30-1); f.write(b"\0")` →
  `st_size 9663676416`, `st_blocks*512 = 16384`; `du -h` 16K, `ls -l` 9.7G. Full SHA-256 in
  64 MiB chunks: **7.33 s**. `chmod 0o444` then `os.link` → `st_nlink 2`, link mode `0o444`,
  append → `PermissionError` errno 13. `df`: 5.8 GiB free — the 9 GiB real write was not
  rehearsed.
- `uv run pytest --co -q -m contract` → `10/684 collected`; `-m acceptance` and `-m integration`
  → `no tests collected (684 deselected)`, exit without error; `-m unit` → `674/684`.
  `pytest --markers` lists `unit`, `contract`, `integration`, `acceptance`. `tests/integration/`
  and `tests/acceptance/` hold one 1-line `__init__.py` each; no `tests/conftest.py` exists.
- `hypothesis 6.165.10`; default profile `max_examples=100, deadline=200ms`; the repo's
  `_property = settings(deadline=None, max_examples=200)` (`test_catalog_properties.py:48`); no
  `register_profile` anywhere under `tests/`.
- `uv run pytest --cov=src/huron --cov-report=term-missing --co -q` → `FAIL Required test coverage
  of 89.0% not reached. Total coverage: 53.48%` (collect-only; confirms the command shape and that
  `fail_under` is read from `[tool.coverage.report]`; no `[tool.coverage.run]` section).
- `uv run radon cc src/huron --min C` → four C-grade items, exit 0; `uv run complexipy src/huron
  --max-complexity-allowed 15` → "All functions are within the allowed complexity"; `radon mi -s`
  lowest: `stores/hierarchy.py` A (30.06), `repository.py` A (35.25).
- Inspection: `store.py:299` `os.replace` (documents), `commit.py:152` `os.rename` (envelope),
  `store.py:136` `os.link`; `manifest.py:32-34` limits 10 GiB / 10,000 / 1 TiB;
  `manifest.py:224-235` every manifest-path raise names a specific code; `api.html:218-229` eight
  `PATH_*` rows; `test_hierarchy_store.py:257` `await scenario(store, seed_revision)`, `:510-540`
  the `pg_stat_activity` wait helper, `:542-608` the race pattern; `ci.yml` four jobs, no
  acceptance job, no other workflow file.
- Not verified: the runner's free disk (GitHub advertises ~14 GB on `ubuntu-latest`; the workflow's
  `df -h` step records it), the dedup-500 wall clock and the 9 GiB job's wall clock (the routes do
  not exist), and whether `pg_stat_activity.query` renders asyncpg's `FOR UPDATE` statement with
  the `$1` placeholder verbatim (the existing helper relies on the same rendering for its
  `INSERT`).
