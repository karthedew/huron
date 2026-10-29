# Phase checker-input-boundary: local checker authored-input boundary correction

Status: ready — independent maximum plan review 3 of 3 PASS (subject bytes efe06ee9…; R3-F1 and O1–O4 low, recorded below); parent recorded blockers 2 and 3 on 2026-10-07; Slices A–D run only under the orchestrator's exclusive admission (no concurrent workflow); no checker, test, inventory or receipt change is authorized outside those slices.

Lifecycle note: `roadmap/check_docs.py` accepts only the lifecycle words draft, blocked,
ready, implementing and verified in a plan status line, so the requested state
"READY FOR INDEPENDENT REVIEW — not READY" is carried after `draft —`. The parent changes
it to `ready — …` only after an independent maximum review of this file passes with no
execution blocker, and to `implementing`/`verified` only from slice evidence.

## Authority and enrollment authorization

- **Current authority:** `roadmap/planning-pause-2026-10-06.md` ("Current authority"):
  the production-code pause is lifted; normal reviewed-plan readiness, scoped exclusive
  maximum implementation, complete applicable gates and independent qualification still
  apply. No deploy/promotion, data deletion or sudo.
- **Parent technical authorization:** `roadmap/planning-review-2026-10-06.md` lines 31–37,
  verbatim:

```text
Parent approves enrollment of ONLY the exact retained 1,140 vendor Markdown and
44 report attachment identities/hashes and lock/receipt bindings verified in that
input proof, with its non-hostile local-classification limitations. This is technical
authorization for a future prerequisite-checker correction, not a PASS, production
authorization, permission to rewrite artifacts, or permission to enroll new runs.
The future exclusive maximum writer must recheck every binding against this proof
and stop on drift. Preserve original 63 assertions/harness and all authored coverage.
```

- **Exact enrollment scope (made concrete; nothing else may be enrolled):**
  - Binding source: `roadmap/checks/3818200d-review-input-proof.json`, pinned here at
    SHA-256 `f4a580659daa5dae6fab3899e3fda48ffe3aa4a372766a974b98fc617ddc585c`. The proof
    is a mutable ignored file; any other bytes are drift and STOP the work.
  - 1,140 vendor Markdown identities: 570 under `roadmap/prototypes/starlight/node_modules/`
    and 570 under `roadmap/prototypes/starlight/clean-reproduction/node_modules/` (proof
    `vendors[].files`), each bound to its project lock, its nearest owning installed
    package (431 per tree) and its reviewed `npm ci` install receipt.
  - 44 report attachments named `error-context.md` in seven report roots under
    `roadmap/prototypes/starlight/evidence/`: `e2e-root` 3, `e2e-root-wide-corrected` 1,
    `e2e-root-full` 12, `e2e-root-qualified-matrix` 8, `e2e-root-full-corrected` 8,
    `e2e-root-final` 6, `e2e-subbase-final` 6 (proof `reports[].files`), each bound to its
    sibling Playwright JSON report `<root>.json`.
  - The binding values are listed in "Binding table" under Interfaces item 5.
- **Limitations (copy into every receipt):** the proof's own limit is "Read-only retained
  lock/cache/archive/package/report agreement; no registry authenticity or hostile-writer
  origin proof." Hashes prove equality to a reviewed local snapshot under a non-hostile
  local-classification assumption; they do not prove authorship, registry authenticity,
  generator correctness or semantic truth. A lock's tarball integrity is not an unpacked
  file hash. Reports and receipts are mutable unsigned local files. This authorization
  is not a PASS, not production authorization, not permission to rewrite, normalize,
  move or delete any artifact, and not permission to enroll new runs or roots. The
  code writer rechecks every binding before editing and stops on drift. The original
  63-case harness and all authored coverage are preserved.
- **Reviewed contract:** `roadmap/checker-input-boundary-plan.md`, SHA-256
  `d2f71de5f1909322ff994e49124432f9cbad3239f3b583c40454adf89d27927d`, maximum review 2 of 3
  (dispatch `3818200d-e18f-4145-b5d7-2122de0151fe`): F1–F3 resolved, no new plan-contract
  defect. This file is its self-contained execution form. The contract stays
  byte-identical and gains no pointer. Every detail added here (exact paths, diagnostics,
  gating, generator, tests, tools, labels) is a **plan resolution** for independent
  review; none relaxes a contract invariant. If a reviewer finds a conflict, the
  contract wins and the conflict is a plan defect.

## Context and outcome

**Defect.** `roadmap/check_docs.py` (SHA-256
`e74d7708b2d5468c48a76829d4fb066d87a4814fc5707d1abbeb9ef873f8a77e`) builds its whitespace
inputs at line 49 as `sorted({*paths, *ROOT.glob("roadmap/**/*.md"), *ROOT.glob("roadmap/*.py")})`.
The glob ignores Git ignore rules and has no authored/vendor/generated boundary, so the
retained Starlight npm installs and Playwright error-context reports are scanned as if
they were authored text. `python roadmap/check_docs.py` therefore exits 1 with exactly
2,330 `trailing whitespace` lines (details under Prototype evidence E1).

**Consequence.** Every complete gate that includes the root checker fails: SDK isolation
review 1 (complete FAIL solely on this gate), checker-contract review 2 (complete FAIL
solely on this defect) and every later plan/prototype review. The original harness
`roadmap/checks/test_check_docs.py` (SHA-256
`4cb36369770aee10d54d8a49edd00e68f21641359a68281d48e45f13335eb149`) asserts an exit-0,
empty-stderr, `PASS: ` whole-tree baseline at lines 149–151 before its 63 CLI cases
(19 accepted + 44 rejected). Rejected cases include the empty status (`Status: ` with a
trailing space) whose exact expected output is the fixture's trailing-whitespace line
followed by the lifecycle error. Today the harness fails at line 150 before case 1. That
is the known owned defect, not permission to accept a bad baseline; the earlier 63-case
PASS predates these artifacts.

**Unchanged checks.** Tracked live-doc link/fragment scope (lines 13–14 and 28–47),
the untracked-text whitespace scan (55–68), the tracked dependency on ignored plans
(70–80), phase cross-references and skills (102–119), phase structure, status and
markers (121–148), the success line (150) and the exit rule (151). Roadmap Markdown is
not link-checked today and must not become link-checked.

**Outcome.** After the correction, `python roadmap/check_docs.py` exits 0 on the retained
tree and prints the existing PASS line unchanged. Only the 1,184 exact enrolled identities
whose every identity and provenance check passes leave the whitespace input set. All
other Markdown stays checked, including new narratives anywhere, `fixtures/`, `src/`,
`.work/`, `.test-work/`, other `clean-reproduction/` paths, Starlight and SDK narratives,
all 151 SDK Markdown files, plans, receipts and the four Markdown file links. The original
63 cases pass unchanged, and a new suite proves the fail-closed boundary.

**Durable decisions (from the reviewed contract).**
- Default authored discovery plus exact reviewed identities. No runtime relocation or
  migration of retained artifacts.
- Rejected: blanket `node_modules`/`evidence`/`runs`/cache/prototype directory ignores,
  authored allowlists, filtered diagnostics, automatic hash regeneration, and a general
  artifact registry or framework.
- One small versioned JSON inventory, Python standard library only, no persistence
  service. The CLI stays `python roadmap/check_docs.py`: read-only, deterministic, exit 1
  on any error, existing `PASS: ` line only on complete success, and no `--rebaseline`,
  optional-validation, fetch or bypass mode.
- Version 1 covers only the retained snapshot: two installed roots and seven report roots.
  A Starlight fresh-run/output protocol is separate and blocks only Starlight final
  qualification. SDK text needs no exception and stays checked.

**Review history and dispositions.**

| Event | Identity | Result |
| --- | --- | --- |
| Contract planning attempt 1 | child `ses_ef0f3e0ffffe95afJSfTpSFKK7`, dispatch `857c6ad8-e3c4-4e40-9e14-5dd709dc4840` | preparatory draft; review count 0 |
| Maximum review 1 | `ses_ef0ed9dadffeHFMdl0i6eVUDrv`, dispatch `b5243808-f6a6-422d-ae17-88646ef51398` | FAIL. F1 blocking: global symlink rejection would lose coverage. F2 high: unbounded future qualification loop. F3 medium: undefined original-prefix binding |
| Planning fix 1 | `ses_ef0e0497effeAJC8bCE8Ds9cC7`, dispatch `a6a26983-02e5-4cdf-9370-b7169072a2b9` | F1: discovery separated from classification security, with no directory-link traversal and file links checked through lexical paths. F2: retained snapshot only, plus a separate blocking fresh-run protocol. F3: origin derived from the hashed report, with component agreement |
| Maximum review 2 | `ses_ef0d73ae6ffeShc645txcgdzV5`, dispatch `3818200d-e18f-4145-b5d7-2122de0151fe`, terminal 03:10:36Z | F1–F3 resolved, no new contract defect; complete verdict FAIL only from the known checker/harness defect |
| Parent approval | `roadmap/planning-review-2026-10-06.md:31-37` | bounded enrollment authorization (above) |
| Read-only discovery (Claude Code) | verification/discovery worker, 2026-10-06 04:35–05:00Z | no drift; placement, mapping and seven clarifications needed (resolved below) |
| This execution plan: reviews 1–2 and fixes 1–2 | see Execution ledger | review 1 FAIL (F1, F2 medium; F3–F9 low); review 2 FAIL (R2-F1 medium; R2-F2, R2-F3 low); every finding dispositioned in the ledger |

**Discovery clarifications resolved by this plan.**
1. Install-receipt cwd is bound by components to the origin derived from the hashed
   reports, never resolved on the host.
2. The proof is pinned by SHA-256.
3. Import side effects and bytecode: add a narrow `main()`; the new suite sets
   `sys.dont_write_bytecode`.
4. Gate logs go to unique per-invocation directories.
5. Discovery fixtures are minimal synthetic `git init` repositories under the system
   temporary directory, not 1.55 GB repository copies.
6. The harness depends on live plan 001, which requires quiescence.
7. Tool timeout is 600000 ms.

## Prototype evidence

**Question.** Can an exact, fail-closed v1 classification remove all 2,330 findings
without hiding authored text? Do the retained bindings still equal the approved proof?

**E1 — defect reproduction** (read-only discovery, 2026-10-06 about 04:43Z, CPython 3.14.0,
proven nonwriting by `find -newer` and an unchanged index):
`cd /home/karl/repo/huron && python roadmap/check_docs.py` exits 1 in 2.89 s with empty
stderr and 2,330 stdout lines, all `<path>:<line>: trailing whitespace`:

| Population | Lines | Files |
| --- | ---: | ---: |
| `roadmap/prototypes/starlight/node_modules` | 1,035 | 43 |
| `roadmap/prototypes/starlight/clean-reproduction/node_modules` | 1,035 | 43 |
| Playwright `error-context.md` reports | 260 | 43 of 44 |
| Anything else | 0 | 0 |

The stdout SHA-256 is `6d2d1d1c95a106327fe1269065e37ee1c6c5c0fedc20338e34c3ea193b8f50c4`,
byte-identical (`cmp`) to `roadmap/checks/3818200d-review-checker.log` and
`roadmap/checks/b5243808-review1-check-docs.log`. All 260 report lines are Playwright
gutter renderings of blank source lines inside "# Test source". The authored
`e2e/docs.spec.ts` has no offending line.

**E2 — binding drift check** (same discovery):
- 1,140/1,140 vendor and 44/44 report identities match the proof.
- Also matching: two locks, two install receipts, seven report receipts
  (config/attachment/disk agreement), 862 package-to-lock bindings and 431/431 retained
  archives with 570 Markdown members.
- 0 drifted, 0 missing, 0 extra.
- The vendor trees are byte-identical (4,594,997 Markdown bytes each). They contain no
  `.MD`/`.markdown`/`.mdx` files and no Markdown or directory links.
- For all 1,140 files, the nearest `package.json` is the nearest lock key.

**E3 — read-only simulation of this plan's v1 rules** (this planning turn, 2026-10-06
about 14:07Z, `python -I -B`, CPython 3.14.0). The simulation script lives only in the
planning scratch directory and is not persistent; its normative parts appear in
Interfaces and the appendix tool `recheck_bindings.py`. Results:
- **Projected inventory:** 228,680 bytes, 5,972 lines, no trailing whitespace, SHA-256
  `3536bb8e6f6bc3d7d33d63e21bbf5bdc97f7487bbf1b076c5b6eb19f7fd93b57`. Strict re-parse
  passed with 0 path-grammar failures, 0 overlaps, and roots equal to the reviewed set.
- **Discovery:** 4,560 Markdown paths, equal to the CPython 3.14 glob population, with
  0 discovery errors. The four Markdown file links were found. Directory links were
  never traversed: 194 SDK and 4 Starlight.
- **Classification:** 1,184/1,184 with 0 errors, from one origin
  `/home/karl/repo/huron/roadmap/prototypes/starlight`. Eligible attachments equalled
  enrollment per root (3/1/12/8/8/6/6), with no duplicate path across all attachment
  records. Package metadata matched for 862 bindings. 482 intermediate-directory checks
  (241 per tree, over 27 distinct directories per tree) found no nearer package.
- **Remaining population:** 0 unknown inputs in enrolled roots. 3,376 Markdown files
  remain authored, with 0 trailing-whitespace lines.
- **Archives:** 431/431 with 570 members.
- **Cost and writes:** under 1 s; no repository writes (`find -newer` empty).

**E4 — gate-tool probes** (this planning turn):
- The appendix recheck tool (`recheck_bindings.py`) exits 0 on the live tree in 1.8 s,
  with 0 errors and `inventory_file: absent`.
- On a scratch copy holding only the proof and the two locks, its `--write-inventory`
  mode created a 5,972-line inventory with SHA-256 `3536bb8e…` and refused a second
  write. That copy deliberately lacked the live artifacts, so its recheck failed.
- The appendix manifest tool (`manifest.py`) captured 77,101 entries (63,598 files, 13,041
  directories, 446 links, 16 missing tracked deletions; 553 Git-visible paths). Its
  compare mode flagged undeclared change kinds and removals on synthetic edits.
- A synthetic fixture repository (`git init -q`, `.gitignore` = `/roadmap/`,
  `roadmap/README.md`, eleven synthetic plans for phases 000–010) ran a copy of the
  current checker and printed the exact PASS line. Adding one dirty
  `roadmap/notes/new.md` produced exactly `roadmap/notes/new.md:1: trailing whitespace`.

**E5 — independent review-2 receipts** (under `roadmap/checks/`, summarized; read-only):

| Receipt | SHA-256 prefix | Summary |
| --- | --- | --- |
| `3818200d-review-gates.json` | `e7ef303c` | `git status --short --untracked-files=all` exit 0 (55 lines); `git diff --check` exit 0; `UV_CACHE_DIR=/tmp/opencode/huron-effort-uv-cache make docs` exit 0, "No issues found"; checker exit 1 (2,330 lines, 2.528 s); harness exit 1 (2.711 s, AssertionError line 150); `git check-ignore -v` exit 0 (12 lines); `git ls-files roadmap` exit 0, empty |
| `3818200d-review-input-proof.json` | `f4a58065` | `errors: []`. Vendors: 2 × 570 files, 431/431 packages, lock `5857165d…` × 2. Receipts: primary `901b574d…`, clean `ed99415a…`. 7 reports / 44 attachments; 431 archives / 570 members. 151 SDK Markdown; 194 SDK + 4 Starlight directory links; 4 Markdown file links; 47 owned hashes |
| `3818200d-review-text-contracts.json` | `d4aab28b` | `errors: []`; `diagnostics_not_in_verified_exact_sets: []`; `original63_byte_identical: true`; 63 declared (19/44), 0 executed; 3,375 ordinary Markdown with 0 whitespace errors; 151 SDK Markdown still checked; Python 3.14.0; uv 0.12.19 |
| `3818200d-review-preservation.json` | `82609128` | 77,078 entries, 553 Git-visible, 51 tracked dirty, 4 untracked; HEAD/index/status/visible equal; `changed_entries: []`; 4.89 min |
| `3818200d-review-processes-corrected.json` | `98bee6c4` | no residual relevant processes; the strict docs build ran; no npm/SDK builds, services or browsers; 22 outputs ignored |
| `3818200d-review-before.json`, `-after.json` | `07af8daa`, `d15f9b18` | 77,078 entries each (63,575 files, 13,041 directories, 446 links, 16 missing) |

**E6 — planning-fix probes** (planning fix attempt 1, 2026-10-06 about 18:40Z, `python -I -B`,
CPython 3.14.0, uid 1000, ext4 scratch fixtures outside the repository, removed after use):
- Interfaces item 3 as reviewed (`a6f336f3…`), run verbatim: a mode-000 file returned
  `unreadable`, but a file below a mode-000 directory raised an uncaught `PermissionError`
  (EACCES), and a grammar-valid 256-character component raised an uncaught `OSError`
  (ENAMETOOLONG). The corrected item 3 helpers return `unreadable` and
  `inaccessible ENAMETOOLONG`. A directory and a FIFO return `not a regular file` without
  being opened. `os.path.lexists` returns false below a mode-000 directory, so rule 1
  now uses the component walk instead.
- Item 4 discovery on the new case shapes: a mode-000 `.md` file gives D3, a mode-000
  directory gives D1 and a FIFO named `.md` gives D2. A directory named `readme.md`
  and a report root replaced by a regular file give no discovery line.
- `json.loads` parsed 5,000 nested arrays and a 2,000-level chain of nested `suites`.
  A recursive suite walk raised `RecursionError` on that chain, and parsing 100,000
  nested arrays raised `RecursionError`. Hence the shared parse rule and the iterative
  walk in item 6.
- The seven report receipts, read once with hashes equal to the proof, hold 323
  attachment records. 132 have a `path` (44 each `error-context`, `screenshot`, `trace`);
  all are canonical absolute under the item 3 grammar, with no duplicate. The other 191
  (`network-and-console` 160, `injected-index-failure` 31) have no `path` key; each
  carries an inline `body`. The stricter P3 rule therefore changes nothing on the
  retained tree. `find -newer` showed no repository write.
  - Correction (fix attempt 2, R2-F2): this bullet first said the 191 records had no
    `body` either. The fix-1 probe counted `body` only on records that have a `path`.
    Independent plan review 2 read the seven receipts (hashes equal to the proof) and
    found an inline `body` on all 191. No rule reads `body`, so classification is
    unaffected.

**E7 — planning-fix-2 probes** (planning fix attempt 2, 2026-10-06 about 19:36–19:42Z,
`python -I -B`, CPython 3.14.0, scratch only; `find -newer` showed no repository write):
- Interfaces item 3's `relative_parts`, run verbatim, rejects
  `roadmap/prototypes/starlight/.test-work` (leading-dot component) and its would-be
  receipt `roadmap/prototypes/starlight/.test-work.json`. It accepts every other root
  named in I10.
- Overlap by components with the item 9 fixture roots: of the I10 roots placed as the
  `e2e-subbase-final` report root, only `roadmap/prototypes/starlight/evidence`
  (ancestor of the remaining `…/evidence/e2e-root-final`) and
  `roadmap/prototypes/starlight/clean-reproduction/node_modules` (equal to the clean
  vendor root) overlap a remaining root. `roadmap/prototypes/starlight/evidence/e2e-root`
  as the clean vendor root overlaps nothing.
- From the pinned proof alone: each file's owner is the deepest of the proof's 431
  archive packages that contains it, which reproduces 431 owners per tree. That gives
  241 intermediate-directory checks per tree over 27 distinct directories, 482 in all,
  equal to the E3 count.
- The gate-wrapper blocks as reviewed (`cf832c68…`), copied verbatim into a scratch
  repository, kept going after a failure and exited 0:
  - With the invocation directory already present, `mkdir` failed. The extraction then
    wrote into it when it was empty, or raised `FileExistsError` when it held an
    earlier invocation's tools. Either way the gate ran next and overwrote that
    directory's `g0-python.out`.
  - A failed extraction (a tool body edited so its digest no longer matched) also let
    the gate run.
- The corrected creation block (under "Gate wrapper and tool extraction"), run the same
  way, exited 1 before any gate in all three cases and left the existing directories
  byte-identical. In a fresh directory it still extracted the three tools with their
  pinned digests. The re-entry check still continued in its own directory and stopped
  for a missing one.

**Limitations.** E3, E4, E6 and E7 are planning probes, not implementation or
qualification. The simulation is not the checker, and the receipts are mutable ignored
files. No install, browser or network was used. The non-hostile assumption holds
throughout. Counts are evidence, not global thresholds.

**Conclusion.** The v1 rules can be met on the retained snapshot with zero residual
authored findings. Implementation may proceed after independent review of this plan.

## Exact scope and ownership

Owned code-slice paths (only the exclusive maximum code worker in Slice B or D writes them):

| Path | Action | Label | State at planning |
| --- | --- | --- | --- |
| `roadmap/check_docs.py` | modify: constants, discovery/classification helpers, narrow `main()`, whitespace input set | `tool:roadmap-checker` write | `e74d7708…` |
| `roadmap/checks/test_check_docs.py` | keep byte-identical; run only | `tool:roadmap-checker` read | `4cb36369…` |
| `roadmap/checks/test_check_docs_discovery.py` | create: new discovery/classification suite (the contract's choice; the original harness stays byte-identical) | `tool:roadmap-checker` write | NOT PRESENT |
| `roadmap/checks/starlight-markdown-inputs.v1.json` | create once, with exclusive create, through the appendix generator only; never edited or regenerated | `tool:roadmap-checker` write (enrollment/provenance data) | NOT PRESENT; must equal `3536bb8e…` |
| `roadmap/checks/checker-input-boundary-receipt.md` | create (writer); fix workers append dated sections only | `tool:roadmap-checker` write | NOT PRESENT |
| `roadmap/checks/recovery/` | untouched | `tool:roadmap-checker` read | retained fixture |

The contract names the inventory path exactly (`roadmap/checker-input-boundary-plan.md`
line 119), so no alternative path is chosen. The parent extends the exact boundary of
`tool:roadmap-checker` to name the new suite and the receipt. It also removes
`roadmap/check_docs.py` from `plan:docs-design` in the OpenCode-era
`roadmap/resource-ledger.md`. The parent owns those records; workers never edit them.

Run outputs. They are unique per invocation, never shared, and never deleted by
another invocation.

| Output | Producer | Label |
| --- | --- | --- |
| `roadmap/checks/chk-<role>-a<attempt>-<UTC>/` | baseline, writer, fix and review workers | `checks:roadmap` write |
| `roadmap/plans/check-docs-*.md` transient fixture (created and removed by the original harness) | every harness run | `checks:roadmap` write |
| `${TMPDIR:-/tmp}/huron-checker-discovery-*/` (`tempfile.mkdtemp`, removed only by the run that created it) | new suite | `checks:roadmap` write |
| `site/`, docs cache, `UV_CACHE_DIR=/tmp/opencode/huron-effort-uv-cache` | `make docs` | `build:docs` write (the OpenCode-era ledger names this cache `cache:uv`) |
| `.venv/` | `make docs` (docs-group sync) | `env:python` write |
| session notes and progress log | each worker | `scratch:<name>` write |

Per-invocation directory details:
- `<role>` is `baseline`, `writer`, `fix` or `review`; `<UTC>` is `date -u +%Y%m%dT%H%M%SZ`.
- Create the directory with plain `mkdir` (no `-p`). If it exists, pick a new timestamp;
  never reuse another invocation's directory. The creation block exits the tool call
  when `mkdir` fails, before any extraction or gate can write. An invocation re-enters
  only its own directory, in every later tool call (prologue and re-entry check under
  the gate set).
- Allowed contents: logs (`.cmd`/`.out`/`.err`/`.json`), manifests, Appendix tools and
  `progress.log`. The writer also saves `check_docs.py.orig`.
- No Markdown file may be placed in this directory.

Read-only inputs:
- `source:repo`: tracked files and the dirty user work.
- `plan:checker-inputs`: this file and the contract.
- `plan:raw-phases`: plans 000–010. Live `roadmap/plans/001-decisions-prototypes.md` is
  the harness source, and every plan is a checker input.
- `prototype:starlight` (`roadmap/prototypes/starlight/`) and `prototype:sdk-isolation`
  (`roadmap/prototypes/sdk-isolation/`): all retained artifacts, receipts, links and caches.
  These are the orchestrator dictionary's `prototype:<name>` labels, where `<name>` is the
  directory name under `roadmap/prototypes/`.
  - The OpenCode-era `roadmap/resource-ledger.md` (line 24) names the same SDK boundary
    `prototype:sdk`, as it names the uv cache `cache:uv` (see `build:docs` above).
  - Labels are exact and aliases are never inferred, so this plan always writes
    `prototype:sdk-isolation`. Until the parent reconciles the ledger (blocker 2), a claim
    under either spelling conflicts with a claim under the other.
- `tool:roadmap-checker`: the proof and the `3818200d-*`/`b5243808-*` receipts.

**Admission.**
- Slices B and D are actual code: exclusive against ALL workers, reviews and checks
  in both admission orders, which is equivalent to `*:write`.
- Slices A and C are non-code, but they write `checks:roadmap` (a transient file in
  `roadmap/plans/` plus reading ALL roadmap Markdown), `build:docs` and `env:python`.
- None of A–D may overlap any roadmap Markdown writer, a `plan:raw-phases`,
  `prototype:starlight`, `prototype:sdk-isolation` or `source:repo` writer, another
  `checks:roadmap`/`build:docs`/`env:python` claimant, or the subject writer.
- On this host the parent guarantees this by running no other workflow concurrently.
  Claims are cooperative coordination, not a sandbox.

**Exclusions.**
- No deletions, moves, renames, compatibility shims, producer edits, dependency
  changes, root/CI configuration, `.gitignore` or tracked-file changes.
- No edits to Starlight/SDK artifacts, the proof or other receipts, the contract,
  other plans or `roadmap/resource-ledger.md`.
- No installs other than the docs-group sync performed by `make docs`. No services,
  browsers, network fetches, or fresh Starlight/SDK runs.
- The existing explicit historical canonical/legacy task-heading support stays
  untouched.
- Tests create and remove only their own uniquely created fixtures. Unknown
  pre-existing files at owned paths block the work rather than inviting cleanup.

**Dirty-tree ownership.**
- State at planning: `git --no-optional-locks status --porcelain=v1 -uall` showed 55
  entries (51 tracked modified/deleted; 4 untracked: `design/raw-first.md` and three
  files under `src/huron/core/catalog/interface/`). All are pre-existing user or
  prior-planning work.
- HEAD `2b2e9c0c9d6b9beafef2e11b840f28535502aa6b`; raw index SHA-256
  `a966503715762ae180e3a8b1d9634fd1f9fd0e8a6f945d4bffc75aed062dc706`; status SHA-256
  `f3f774478e5a4680e68c74f89586a8143822230116c2dc6e877f838ea4c35cf0`. `git ls-files roadmap`
  was empty and `git diff --check` exited 0.
- Preserve all of it. Never commit, branch, stash, reset, clean, checkout or push, and
  never use sudo.
- Never touch foreign services, containers or processes: Ethereum lighthouse/reth
  (including ports 9000/8545), kind clusters, marimohub pgvector/registry containers,
  VirtualBox VMs and the user's opencode process.
- `roadmap/__pycache__` and `roadmap/checks/__pycache__` were absent at planning and
  must stay absent.

## Interfaces and implementation examples

Code below is illustrative unless marked normative. Normative items are binding
contracts that the tests and review check. "Existing" means today's checker.

### 1. CLI contract (normative, unchanged)

`cd /home/karl/repo/huron && python roadmap/check_docs.py`.
- It is read-only and deterministic and adds no arguments or modes.
- On complete success it prints exactly this line and exits 0:
  `PASS: local documentation links/fragments, no tracked ignored-plan links, owned/untracked text whitespace, 000–010 phase cross-references/skills and 10 product phase structures`
- Otherwise it prints one diagnostic per line and exits 1.
- Stderr stays empty and no traceback appears for any input/provenance condition named
  here. That includes every operating-system error while reading a classified path
  (item 3) and malformed or deeply nested JSON (items 5 and 6).

### 2. Module structure (normative shape)

Move today's module-level procedural statements, unchanged and in order, into
`def main() -> None:` and end the file with `if __name__ == "__main__": main()`.
Importing the module then runs no Git command, prints nothing and raises nothing.
`ROOT`, `anchors()`, `TASK_HEADINGS` and `count_task_headings()` stay module-level and
byte-identical in body. The only semantic change inside `main()` is the whitespace input
set at the old line 49, plus one inserted `errors.extend(...)`. The receipt includes
`diff -u -w` of the saved original against the new file (gate G13).

```python
ROOT = Path(__file__).resolve().parents[1]
STARLIGHT = "roadmap/prototypes/starlight"
INVENTORY = "roadmap/checks/starlight-markdown-inputs.v1.json"
REVIEWED_VENDORS = {  # vendor root -> its reviewed install receipt
    f"{STARLIGHT}/node_modules": f"{STARLIGHT}/evidence/commands/final-ci.json",
    f"{STARLIGHT}/clean-reproduction/node_modules": f"{STARLIGHT}/evidence/clean-reproduction-commands.json",
}
REVIEWED_REPORTS = frozenset(f"{STARLIGHT}/evidence/{name}" for name in (
    "e2e-root", "e2e-root-wide-corrected", "e2e-root-full", "e2e-root-qualified-matrix",
    "e2e-root-full-corrected", "e2e-root-final", "e2e-subbase-final",
))


def main():
    """Run every documentation check, print diagnostics and exit 1 on any finding."""
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    ...  # existing statements through the link loop, unchanged
    discovered, discovery_errors = discover_roadmap_markdown(ROOT)
    classified, identity_errors = verified_starlight_markdown(ROOT, ROOT / INVENTORY, discovered)
    errors.extend(sorted(set(discovery_errors + identity_errors)))
    for path in sorted({*paths, *(set(discovered) - classified), *ROOT.glob("roadmap/*.py")}):
        ...  # existing whitespace loop body, unchanged
    ...  # existing untracked, dependency, phase and PASS/exit statements, unchanged


if __name__ == "__main__":
    main()
```

The existing loop body handles every discovered regular file or valid file link, and
both are read through their lexical path. Diagnostic order is unchanged: link errors,
then the new sorted block, then whitespace, untracked, dependency and phase errors. The
63 cases see no new lines because the real tree yields none.

### 3. Path grammar and safe reads (normative behavior)

```python
COMPONENT = re.compile(r"[A-Za-z0-9_@+-][A-Za-z0-9._@+-]*")
SHA256 = re.compile(r"[0-9a-f]{64}")


def relative_parts(value):
    """Return the components of a canonical relative POSIX path, or None."""
    if not isinstance(value, str):
        return None
    parts = value.split("/")
    return tuple(parts) if all(COMPONENT.fullmatch(part) for part in parts) else None


def absolute_parts(value):
    """Return the components of a canonical absolute POSIX path, or None."""
    if not isinstance(value, str) or not value.startswith("/"):
        return None
    return relative_parts(value[1:])


def os_error_reason(error):
    """Return the fixed diagnostic reason for an operating-system error, never its message.

    FileNotFoundError and NotADirectoryError give "missing", PermissionError (EACCES or
    EPERM) gives "unreadable", and any other OSError gives "inaccessible <errno name>",
    for example "inaccessible ENAMETOOLONG".
    """
    if isinstance(error, (FileNotFoundError, NotADirectoryError)):
        return "missing"
    if isinstance(error, PermissionError):
        return "unreadable"
    return "inaccessible " + errno.errorcode.get(error.errno, "EUNKNOWN")


def lstat_components(root, relative):
    """Return (lstat result, None) for root/relative reached without any symlink component.

    Every component is examined with os.lstat. Otherwise returns (None, reason) where
    reason is "missing", "symlink component <prefix>", "unreadable" (for example below a
    directory without search permission) or "inaccessible <errno name>".
    """
    current = root
    parts = relative.split("/")
    for index, part in enumerate(parts):
        current = current / part
        try:
            info = os.lstat(current)
        except OSError as error:
            return None, os_error_reason(error)
        if stat.S_ISLNK(info.st_mode):
            return None, "symlink component " + "/".join(parts[: index + 1])
    return info, None


def read_regular(root, relative):
    """Read a regular file reached from root without any symlink component.

    Returns (bytes, None) on success, else (None, reason) where reason is one of
    "missing", "symlink component <prefix>", "not a regular file", "unreadable" or
    "inaccessible <errno name>". A file that is not regular is never opened.
    """
    info, reason = lstat_components(root, relative)
    if reason:
        return None, reason
    if not stat.S_ISREG(info.st_mode):
        return None, "not a regular file"
    try:
        descriptor = os.open(root / relative, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as error:
        return None, os_error_reason(error)
    with os.fdopen(descriptor, "rb") as handle:
        try:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                return None, "not a regular file"
            return handle.read(), None
        except OSError as error:
            return None, os_error_reason(error)


def directory_problem(root, relative):
    """Return None when root/relative is a directory reached without symlinks, else the reason."""
    info, reason = lstat_components(root, relative)
    if reason:
        return reason
    return None if stat.S_ISDIR(info.st_mode) else "not a directory"
```

The grammar rejects, before any filesystem access:
- absolute, empty, `.` and `..` components, and leading-dot names;
- `//`, a trailing `/` and a leading `./`;
- backslash, NUL, glob characters, `%`-encoded aliases, spaces and non-ASCII.

All 1,184 enrolled paths, all lock keys used and the real origin satisfy it (E3). Roots
use `directory_problem`: the same component walk, with `not a directory` for any other
final type.

Classification reaches the filesystem only through these helpers. The one exception is
rule 5's V3 `lexists` probes, which run only after the file's own walk succeeded, so every
directory they pass through is searchable. The reasons map to the item 7 templates:
- `missing` is A1 and `symlink component <prefix>` is A2.
- `not a regular file` and `not a directory` are A3.
- `unreadable` is A4, including a target below a directory without search permission.
- `inaccessible <errno name>` is A6, such as an over-long name (E6).

None of them is a traceback. `<errno name>` is the symbolic name from `errno.errorcode`,
which is deterministic; the exception message is never printed.

### 4. Discovery (normative behavior)

```python
def discover_roadmap_markdown(root):
    """Return lexical Markdown inputs under roadmap/ and sorted discovery diagnostics.

    Walks real directories only, never through a directory link. Markdown file links
    are inputs only when they resolve to a readable regular file inside roadmap/.
    """
    roadmap = Path(os.path.realpath(root / "roadmap"))
    found, errors, pending = [], [], [root / "roadmap"]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name)
        except OSError:
            errors.append(f"{directory.relative_to(root)}: unreadable directory")
            continue
        for entry in entries:
            path = Path(entry.path)
            if entry.is_symlink():
                if entry.name.endswith(".md"):
                    problem = markdown_link_problem(path, roadmap)
                    if problem:
                        errors.append(f"{path.relative_to(root)}: {problem}")
                    else:
                        found.append(path)
                continue  # other links: never traversed, never reported
            if entry.is_dir(follow_symlinks=False):
                pending.append(path)
            elif entry.name.endswith(".md"):
                if not entry.is_file(follow_symlinks=False):
                    errors.append(f"{path.relative_to(root)}: Markdown input is not a regular file")
                elif not os.access(path, os.R_OK):
                    errors.append(f"{path.relative_to(root)}: unreadable Markdown input")
                else:
                    found.append(path)
    return sorted(found), sorted(errors)


def markdown_link_problem(path, roadmap):
    """Return why a Markdown file link cannot be an input, or None when it can."""
    try:
        info = os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return "broken Markdown link"
    except PermissionError:
        return "unreadable Markdown input"
    except OSError as exc:
        return "cyclic Markdown link" if exc.errno == errno.ELOOP else "broken Markdown link"
    if not Path(os.path.realpath(path)).is_relative_to(roadmap):
        return "Markdown link escapes roadmap"
    if not stat.S_ISREG(info.st_mode):
        return "Markdown link target is not a regular file"
    if not os.access(path, os.R_OK):
        return "unreadable Markdown input"
    return None
```

The `.md` suffix match stays case-sensitive, as the old glob was. Hidden directories are
walked. The four retained `.test-work/content-*/fixtures/docs/history.md` links remain
inputs through their own lexical paths, and their diagnostics are never deduplicated
with the target's. The 194 SDK directory links (62 venv `lib64` and 132 uv-cache) and
the four `.test-work/content-*/src/content/docs/escape` directory links are neither
traversed nor reported. Non-Markdown links, such as `node_modules/.bin/*`, are outside
this boundary. This is not a new global filesystem security policy.

### 5. Inventory v1 (normative)

Document shape (exact key sets; no other keys):

```json
{
 "version": 1,
 "vendors": [{"root": "...", "lock": {"path": "...", "sha256": "..."}, "install": {"path": "...", "sha256": "..."}, "files": [{"path": "...", "sha256": "...", "package": "..."}]}],
 "reports": [{"root": "...", "receipt": {"path": "...", "sha256": "..."}, "files": [{"path": "...", "sha256": "..."}]}]
}
```

Rules:
- Strict UTF-8 JSON. Duplicate keys are rejected through `object_pairs_hook`, and `NaN`
  and `Infinity` through `parse_constant`. A `RecursionError` from nesting beyond the
  parser's limit is N2 too, never a traceback (E6).
- `version` is the integer 1, never a bool or string. `vendors` and `reports` are
  arrays of objects, and every `files` array is non-empty.
- Every `sha256` is 64 lowercase hex characters.
- Every `root`, `path` and `package` satisfies the grammar.
- Vendor rules:
  - `root` is a key of `REVIEWED_VENDORS`.
  - `lock.path` is `<root parent>/package-lock.json`.
  - `install.path` is `REVIEWED_VENDORS[root]`.
  - File paths are relative to `root` and end in `.md`.
  - `package` is a lock key relative to the root's parent and starts with the component
    `node_modules`.
- Report rules: `root` is in `REVIEWED_REPORTS`, `receipt.path` is `<root>.json`, and each
  file path has exactly two components, the second being `error-context.md`.
- No two roots may be equal or ancestor/descendant by components, and no repo-relative
  file path may appear twice.
- Diagnostic precedence. It decides which N lines validation prints, never whether the
  document fails, because any N line classifies nothing (item 6 rule 2):
  - A value of the wrong JSON type gets only N4. The grammar applies only to strings.
  - A string that fails the grammar gets only its N6 line. N7 and N9 examine only
    grammar-valid values, N10 compares only grammar-valid roots, and N11 counts only
    files whose `root` and `path` are both grammar-valid.
  - Reviewed bindings exist only for an entry whose `root` is a grammar-valid member of
    its section's reviewed set. For any other entry (its `root` is missing, not a
    string, noncanonical or unreviewed: N4, N6 or N8), the `lock`, `install` and
    `receipt` paths are not compared and give no N9. Every other rule still applies to
    that entry's values, including N10 for a grammar-valid root.
- The whole document is validated before any referenced path is touched.
- The set of roots may be a subset of the reviewed nine (fixtures use four). The real
  inventory contains all nine, which the G11 projection equality proves. The two vendor
  install receipts have different shapes (an object and an array), so validation
  accepts both.

Real excerpt from the projection (first vendor root and first report entry):

```json
{
 "version": 1,
 "vendors": [
  {
   "root": "roadmap/prototypes/starlight/clean-reproduction/node_modules",
   "lock": {
    "path": "roadmap/prototypes/starlight/clean-reproduction/package-lock.json",
    "sha256": "5857165d1169f134499883b793799a084fd9b64ca6f173bef48201943e91fd70"
   },
   "install": {
    "path": "roadmap/prototypes/starlight/evidence/clean-reproduction-commands.json",
    "sha256": "ed99415aae3184644a1b8975014b6230d41b18f0d2d39b484c0e10609b00cc5c"
   },
   "files": [
    {
     "path": "@astrojs/check/README.md",
     "sha256": "53c44275e5892a08e404a59c40191901f793180461420e06705aad58ebc96d08",
     "package": "node_modules/@astrojs/check"
    }
   ]
  }
 ],
 "reports": [
  {
   "root": "roadmap/prototypes/starlight/evidence/e2e-root",
   "receipt": {
    "path": "roadmap/prototypes/starlight/evidence/e2e-root.json",
    "sha256": "320394b56e7406e628e546c2aa4537eefae966d97fe1da005c58393d943b051f"
   },
   "files": [
    {
     "path": "docs-A-delayed-search-inde-5476a-ading-and-then-real-results-wide-light/error-context.md",
     "sha256": "aa3eb0badc79197b13ce7c701e8e85351dee87ee796adfdaac3024258caa590f"
    }
   ]
  }
 ]
}
```

(The real file contains 570 entries in each vendor `files` array and 7 report roots.
The excerpt is trimmed; it is not valid enrollment.)

Binding table (normative; every value is rechecked by G11 before and after editing):

| Binding | Repo-relative path | SHA-256 / value |
| --- | --- | --- |
| Approved proof | `roadmap/checks/3818200d-review-input-proof.json` | `f4a580659daa5dae6fab3899e3fda48ffe3aa4a372766a974b98fc617ddc585c` |
| Lock, primary | `roadmap/prototypes/starlight/package-lock.json` | `5857165d1169f134499883b793799a084fd9b64ca6f173bef48201943e91fd70` |
| Lock, clean | `roadmap/prototypes/starlight/clean-reproduction/package-lock.json` | `5857165d1169f134499883b793799a084fd9b64ca6f173bef48201943e91fd70` |
| Install receipt, primary (object shape) | `roadmap/prototypes/starlight/evidence/commands/final-ci.json` | `901b574d9ace13c0562653de31082e4e39c2cc3cd8e4e461081a6b9768ce5590` |
| Install receipt, clean (array shape) | `roadmap/prototypes/starlight/evidence/clean-reproduction-commands.json` | `ed99415aae3184644a1b8975014b6230d41b18f0d2d39b484c0e10609b00cc5c` |
| Report `e2e-root` (3) | `roadmap/prototypes/starlight/evidence/e2e-root.json` | `320394b56e7406e628e546c2aa4537eefae966d97fe1da005c58393d943b051f` |
| Report `e2e-root-wide-corrected` (1) | `…/evidence/e2e-root-wide-corrected.json` | `c8a16ff77b7647f699420ef41d185d43d2d963a147ebe187f4a130bb70071947` |
| Report `e2e-root-full` (12) | `…/evidence/e2e-root-full.json` | `7dddec8a4474311adc9d33cc36d400ea16da11b0b8d3d5c6a52f138f09e547e4` |
| Report `e2e-root-qualified-matrix` (8) | `…/evidence/e2e-root-qualified-matrix.json` | `2fcec0b3544a3853188445180db29230bde0e3c0c2321e24f58eb42daab6743e` |
| Report `e2e-root-full-corrected` (8) | `…/evidence/e2e-root-full-corrected.json` | `35f0261e86cd2de3f3b6a9d0a85bbf9a6397d565f76b9daf4e462ae32141e9ca` |
| Report `e2e-root-final` (6) | `…/evidence/e2e-root-final.json` | `baa8446d5a4632051f2761fad67f35a3f663db5c3c57c966d0b40dbca8ffcd6b` |
| Report `e2e-subbase-final` (6) | `…/evidence/e2e-subbase-final.json` | `634b9b78aeeb59935dc88125496a94330788169a5763bd67484fe99fbaf023d8` |
| Origin O (from every report `config.configFile`) | — | `/home/karl/repo/huron/roadmap/prototypes/starlight` (never resolved on the host) |
| Primary `npm ci` | final-ci.json | `["npm","ci"]`, cwd = O, exit 0, signal/error null, Node v22.23.2, started 2026-10-06T01:33:01.659Z |
| Clean `npm ci` | clean-reproduction-commands.json | exactly one `["npm","ci"]` record, cwd = O/`clean-reproduction`, exit 0 |
| Inventory to create | `roadmap/checks/starlight-markdown-inputs.v1.json` | `3536bb8e6f6bc3d7d33d63e21bbf5bdc97f7487bbf1b076c5b6eb19f7fd93b57` (228,680 bytes) |
| Checker before edit | `roadmap/check_docs.py` | `e74d7708b2d5468c48a76829d4fb066d87a4814fc5707d1abbeb9ef873f8a77e` |
| Original harness (unchanged) | `roadmap/checks/test_check_docs.py` | `4cb36369770aee10d54d8a49edd00e68f21641359a68281d48e45f13335eb149` |
| Contract (unchanged) | `roadmap/checker-input-boundary-plan.md` | `d2f71de5f1909322ff994e49124432f9cbad3239f3b583c40454adf89d27927d` |
| Baseline checker stdout | equal to `roadmap/checks/3818200d-review-checker.log` | `6d2d1d1c95a106327fe1269065e37ee1c6c5c0fedc20338e34c3ea193b8f50c4` |

### 6. Classification and gating (normative)

`verified_starlight_markdown(root, inventory, discovered) -> tuple[set[Path], list[str]]`
returns the verified enrolled paths (always a subset of `discovered`) and diagnostics.
The contract's two-argument signature was a suggestion. The plan passes `discovered`
so that unknown-input detection reuses the one discovery definition.

**Shared parse rule.** Locks, install receipts, reports and `package.json` files are
parsed from their exact bytes with plain `json.loads`. Any `ValueError` (including
invalid UTF-8) or `RecursionError` is that file's V1, V2, P1 or V4 diagnostic, never a
traceback. Unlike the inventory, these third-party and generator files are not checked
for duplicate keys or `NaN`. Suite trees are walked iteratively with an explicit stack,
never recursively, because a parseable 2,000-level chain overflows a recursive walk (E6).

Rules, in order:

1. **Inventory presence.** The inventory is read with `read_regular` (item 3).
   - Only the reason `missing` means absent. Then, if `lstat_components(root, STARLIGHT)`
     reports anything other than `missing` (the subject exists, or is unreadable,
     inaccessible or behind a symlink component), report N1 and classify nothing.
     Otherwise report nothing and classify nothing. Authored-only discovery and all
     existing checks still run.
   - Any other reason is reported for INV with its template (A2, A3, A4 or A6) and
     classifies nothing.
2. **Present inventory.**
   - Check N2–N11 in one validation pass over the bytes read in rule 1.
   - Any error classifies nothing.
3. **Reports.** For each report, in order:
   - Run the receipt checks A1–A6, then P1, then P2, stopping at the first failure.
   - P1 requires all of (an absent optional key counts as an empty array):
     - The receipt parses to an object whose `config` is an object and whose `suites`
       is an array.
     - Every suite is an object whose optional `suites` and `specs` are arrays.
     - Every spec is an object whose optional `tests` is an array, and every test is an
       object whose optional `results` is an array.
     - Every result is an object whose optional `attachments` is an array, and every
       attachment record is an object.
   - P2 requires all of:
     - `configFile` canonical absolute, ending in `playwright.config.ts`; its parent is O.
     - `rootDir` = O + `e2e`.
     - A non-empty `projects` array whose elements are objects.
     - Every `outputDir` = O + R, where R is the root's components relative to
       `STARLIGHT`, such as `evidence/e2e-root-final`.
   - If valid reports yield more than one distinct O, report N12 and classify nothing
     anywhere.
   - If no valid report yields O while vendors are listed, report N13; vendors stay
     unclassified.
   - When O is unknown (N12 or N13), vendor roots are not examined further.
   - A report root whose receipt failed A1–A6, P1 or P2 is not examined further.
4. **Per report root.**
   - The root directory passes A1–A4 and A6 (`directory_problem`).
   - The attachment graph is walked iteratively through suites → specs → tests →
     results → attachments, plus nested suites.
   - P3 is reported for every record that breaks one of these rules:
     - A record named `error-context` has `contentType` exactly `text/markdown` and a
       canonical absolute `path` whose components are O + R + (one test-output
       directory, `error-context.md`).
     - A record of any other name has no `path` key, or a canonical absolute `path` at
       any location. So a noncanonical alias of an eligible attachment is P3 under any
       name. Records without `path` stay valid; 191 real records have none (E6).
   - Count the canonical absolute `path` of every record, of any name. A path under
     O + R that occurs more than once gives P4. P3 rejects every noncanonical `path`, so
     equal locations have equal spellings and this count finds every duplicate.
   - Eligible set E = {`<dir>/error-context.md`} from the valid `error-context` records.
     E minus the enrolled files gives P5.
   - Any root-level error leaves the whole root unclassified, and its files are not
     examined further (no per-file lines).
   - Per file, stopping at the first failure: P6 if the file is not in E, then A1–A6.
     Paths compare by components; there is no prefix-string or suffix search, and O is
     never resolved on the host.
5. **Per vendor root.**
   - The root directory passes A1–A4 and A6 (`directory_problem`).
   - The lock passes A1–A6 and V1: it parses to an object whose `packages` is an object.
   - The install receipt passes A1–A6 and V2. V2 accepts an object or an array of
     command records with exactly one `command == ["npm", "ci"]`. No record may run npm
     ci with extra arguments, so `--ignore-scripts` is rejected. The single record must
     have integer `exit` equal to 0 (bool rejected), `signal`/`error` absent or null,
     `inBandFailure` absent or false, and canonical absolute `cwd` components equal to O
     plus the project directory's components relative to `STARLIGHT`: none for the
     primary root, `clean-reproduction` for the clean root. A receipt that does not
     parse is V2.
   - Any failure leaves the whole root unclassified, and its files are not examined
     further (no per-file lines).
   - Per file, in this order, stopping at the first failure:
     - A1–A6.
     - V3: `package` components are a proper prefix of `node_modules/<path>`, and
       `package` is a lock key. No intermediate prefix between `package` and the file is
       a lock key, and no intermediate directory has a `package.json` entry
       (`lexists`).
     - `<project>/<package>/package.json` passes A1–A4, A6 and V4 (it parses to a JSON
       object).
     - V5. Let `entry` be `packages[package]`, and let the expected name be exactly
       `entry.get("name") or package.rsplit("node_modules/", 1)[1]`. That is the lock
       entry's `name` when present and non-empty, otherwise the text after the key's
       last `node_modules/`. This is the rule of the E3 simulation and the appendix
       recheck tool, which passed for all 862 real bindings (E3, E4). `package.json`
       `name` equals the expected name, and its `version` equals `entry`'s `version`.
       An `entry` that is not an object fails V5.
   - Package results are computed once per package and shared by its files.
6. **Unknown inputs.** With a valid document, every discovered path under any
   inventory root that is not enrolled for that root gets U1. It also stays an
   ordinary whitespace input.
7. **Verdict.** A file is removed from the authored set only when every check above
   passes for it and its root. Links never acquire an exemption. Non-Markdown is
   never enrolled. Exit 1 follows from any diagnostic through the existing
   `raise SystemExit(bool(errors))`.

Orchestration outline (illustrative):

```python
def verified_starlight_markdown(root, inventory, discovered):
    """Return enrolled Markdown whose every identity and provenance check passed.

    Args:
        root: Repository root.
        inventory: Location of the reviewed v1 inventory.
        discovered: Lexical Markdown inputs from discover_roadmap_markdown.

    Returns:
        The verified subset of discovered paths and the diagnostics.
    """
    name = inventory.relative_to(root).as_posix()
    data, reason = read_regular(root, name)
    if reason == "missing":  # absence is allowed only while the subject is wholly absent
        _, subject = lstat_components(root, STARLIGHT)
        return set(), [] if subject == "missing" else [f"{name}: missing inventory for present {STARLIGHT}"]
    if reason:
        return set(), [f"{name}: {reason}"]
    document, errors = parse_inventory(name, data)  # N2-N11, no filesystem access
    if document is None:
        return set(), errors
    origin, report_roots, errors = check_reports(root, name, document["reports"], errors)  # A, P1-P2, N12-N13
    verified = set()
    for report in report_roots:  # only reports whose receipt checks passed
        verified |= verified_report_files(root, report, origin, errors)  # A root, P3-P6, A1-A6
    for vendor in document["vendors"]:
        verified |= verified_vendor_files(root, vendor, origin, errors)  # A, V1-V5
    errors += unknown_inputs(root, document, discovered)  # U1
    return verified & set(discovered), errors
```

### 7. Diagnostics (normative)

Each new line has the form `<subject>: <reason>`. The subject is a repo-relative POSIX
path, and no exception text is included. INV stands for
`roadmap/checks/starlight-markdown-inputs.v1.json`. A pointer is `$`, `$.version`,
`$.vendors[0]`, `$.vendors[0].files[12].package` or `$.reports[3].receipt.sha256`.

| ID | Line | Condition |
| --- | --- | --- |
| D1 | `<dir>: unreadable directory` | scandir fails |
| D2 | `<path>: Markdown input is not a regular file` | non-link, non-directory `.md` that is not regular |
| D3 | `<path>: unreadable Markdown input` | `.md` file or link target not readable |
| D4 | `<path>: broken Markdown link` | link target missing |
| D5 | `<path>: cyclic Markdown link` | ELOOP |
| D6 | `<path>: Markdown link escapes roadmap` | realpath outside realpath(roadmap) |
| D7 | `<path>: Markdown link target is not a regular file` | contained non-regular target |
| N1 | `INV: missing inventory for present roadmap/prototypes/starlight` | rule 1 |
| N2 | `INV: invalid JSON` | syntax, non-UTF-8, NaN/Infinity, or a `RecursionError` from nesting |
| N3 | `INV: duplicate JSON key "<key>"` | key rendered with `json.dumps` |
| N4 | `INV: invalid schema at <pointer>` | version, unknown/missing key, type, empty `files` |
| N5 | `INV: invalid sha256 at <pointer>` | not 64 lowercase hex |
| N6 | `INV: noncanonical path at <pointer>` | grammar failure of a string; no other N line for that value (item 5 precedence) |
| N7 | `INV: non-Markdown input at <pointer>` | vendor file not `.md`; report file not `<dir>/error-context.md` |
| N8 | `INV: unreviewed root <root>` | grammar-valid root outside its reviewed set |
| N9 | `INV: unreviewed binding at <pointer>` | lock/install/receipt path of a grammar-valid reviewed root, or a `package` prefix, not as reviewed |
| N10 | `INV: overlapping roots <a> and <b>` | equal or nested grammar-valid roots (`a` sorts first) |
| N11 | `INV: duplicate path <repo-relative path>` | file listed twice |
| N12 | `INV: report origins disagree` | more than one O |
| N13 | `INV: no report origin` | vendors listed and no valid report |
| A1 | `<path>: missing` | absent component (`ENOENT` or `ENOTDIR`) |
| A2 | `<path>: symlink component <prefix>` | any symlink from repo root down |
| A3 | `<path>: not a regular file` / `<root>: not a directory` | wrong final type; a file that is not regular is never opened |
| A4 | `<path>: unreadable` | `PermissionError` (EACCES or EPERM) from a component `lstat` or the `open`, including a target below a directory without search permission |
| A5 | `<path>: sha256 mismatch` | bytes differ from enrollment |
| A6 | `<path>: inaccessible <errno name>` | any other `OSError` from a component `lstat`, the `open`, `fstat` or `read`; the name comes from `errno.errorcode`, such as `ENAMETOOLONG` |
| V1 | `<lock>: invalid package lock` | does not parse (shared rule), or no `packages` object |
| V2 | `<receipt>: not an ordinary successful npm ci` | rule 5, including a receipt that does not parse |
| V3 | `<file>: owning package <package> is not the nearest installed package` | rule 5 |
| V4 | `<package.json>: invalid package metadata` | does not parse, or not a JSON object |
| V5 | `<package.json>: name/version does not match lock` | rule 5 |
| P1 | `<receipt>: invalid report` | does not parse, or breaks the rule 3 P1 types |
| P2 | `<receipt>: inconsistent Playwright config` | rule 3 |
| P3 | `<receipt>: invalid attachment <json path>` | rule 4: an invalid `error-context` record, or a noncanonical `path` on a record of any name |
| P4 | `<receipt>: duplicate attachment <json path>` | rule 4, once per duplicated path |
| P5 | `<receipt>: unenrolled error-context attachment <dir>/error-context.md` | rule 4 |
| P6 | `<file>: not an error-context attachment of <receipt>` | rule 4 |
| U1 | `<path>: unknown Markdown input in enrolled root <root>` | rule 6 |

`<json path>` is `json.dumps(record.get("path"))` for the offending record, with the
default `ensure_ascii=True`. That is a quoted JSON string, `null` when the key is absent,
or the JSON rendering of any other value. For P4 it is the duplicated canonical path,
which every duplicate spells identically. It is never a JSONPath pointer. Before this
plan's review 1, P3 read `invalid error-context attachment`; it was reworded because P3
now covers records of any name (ledger, F8).

The new block is emitted as `sorted(set(lines))`. Whitespace diagnostics keep their
existing form, `<path>:<line>: trailing whitespace`. A writer who finds a template
insufficient adds a template for an uncovered condition and records it in the receipt
for review. An existing template is never reworded silently.

### 8. Inventory generation (normative)

Create the inventory exactly once, in Slice B, with the appendix tool. It projects
the pinned proof and the hashed locks, refuses any projection other than SHA-256
`3536bb8e…`, and creates the file exclusively:

```sh
cd /home/karl/repo/huron
python -I -B "$INV/recheck_bindings.py" /home/karl/repo/huron "$INV/b3-inventory-write-result.json" --write-inventory
```

The projection keeps the proof's file keys. Vendor `root` gains `/node_modules`.
`package` is the nearest `node_modules/…` lock key owning `node_modules/<path>`. Install
receipt hashes come from proof `summary`, and report receipts are `<root>.json`. Roots
and files are sorted, and serialization is `json.dumps(document, indent=1,
ensure_ascii=True) + "\n"` in ASCII. Hand edits, re-serialization and regeneration of
an existing file are prohibited. If any projection, proof or lock differs, STOP; the
correction never re-baselines.

### 9. New suite `roadmap/checks/test_check_docs_discovery.py` (normative contract)

**Running.** Use plain Python with the standard library only:
`python roadmap/checks/test_check_docs_discovery.py` from the repository root, like the
original harness. The first line is `fixture base: <absolute path>`. Each case prints
`'<ID> <name>': ok`, and the run ends with `OK: <N> discovery/classification cases`.
The first failing assertion stops the run with a traceback and exit 1.

**Setup assertions.** At start the suite asserts:
- `os.geteuid() != 0`, so the permission cases are deterministic. Root fails; it is not
  skipped.
- The temporary base lies outside the repository, and its components satisfy the
  path grammar, so the real-origin variant of C01 is well defined.
- `roadmap/check_docs.py` is the checker under test.

**Test style.**
- Each CLI case asserts the exact `(returncode, stdout, stderr)` triple. Stderr is always
  empty.
- Each negative case also asserts that the fixture's no-follow fingerprint (types,
  modes, sizes, SHA-256 values, link targets; `.git/` excluded) is unchanged.
- The fingerprint never opens a file that is not regular, so FIFO cases cannot block it.
- Permission cases (D13, D14, C36–C42) take the fingerprint before `chmod`. They
  restore the original modes in a `finally` block, fingerprint again after the
  restore, and assert that the two are equal.
- Docstrings and test names describe behavior. They never mention plans, phases or
  reviews (`docs/getting-started/docstrings.md`, `docs/getting-started/testing.md`).
- The suite reuses the original harness's conventions (exact CLI outcomes, real
  filesystem, fingerprints) without importing or modifying it.

Fixture repository builder (illustrative; E4 verified the synthetic-plan approach):

```python
REPO = Path(__file__).resolve().parents[2]
CHECKER = REPO / "roadmap/check_docs.py"
GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
PLAN_LINES = [  # one synthetic plan per phase 000-010, valid for every structure rule
    "# Phase {n:03}: disposable fixture",
    "",
    "Status: draft — disposable checker fixture",
    "",
    "## Context and outcome",
    "No product scope; review evidence only.",
    "## Prototype evidence",
    "## Exact scope and ownership",
    "## Interfaces and implementation examples",
    "## Per-subject serial task slices",
    "## Skills",
    "## Acceptance and complete applicable gates",
    "make docs and git diff --check.",
    "## Blockers and readiness",
    "## Execution ledger",
    "## Escalation / final receipt",
]


def fixture_repository(base):
    """Create a disposable repository whose roadmap mirrors the real ignore rule."""
    root = Path(tempfile.mkdtemp(prefix="repo-", dir=base))
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, env=GIT_ENV)
    (root / ".gitignore").write_text("/roadmap/\n")
    plans = root / "roadmap/plans"
    plans.mkdir(parents=True)
    (root / "roadmap/README.md").write_text("# Disposable roadmap\n")
    for n in range(11):
        (plans / f"{n:03}-fixture.md").write_text("\n".join(PLAN_LINES).format(n=n) + "\n")
    shutil.copyfile(CHECKER, root / "roadmap/check_docs.py")
    return root


def run_checker(root):
    """Run the copied checker through its public CLI with a bounded wait."""
    return subprocess.run([sys.executable, "roadmap/check_docs.py"], cwd=root,
                          capture_output=True, text=True, timeout=30, env=GIT_ENV)


def import_real_checker():
    """Import the live checker without running it or writing bytecode."""
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("huron_roadmap_check_docs", CHECKER)
    module = importlib.util.module_from_spec(spec)
    with contextlib.redirect_stdout(io.StringIO()) as output:
        spec.loader.exec_module(module)
    assert output.getvalue() == "", output.getvalue()
    return module
```

**Starlight fixture subject.** Built under the reviewed root names with O =
`<suite temp>/absent-origin/huron/roadmap/prototypes/starlight`. O is never created,
and the suite asserts its absence before and after. The fixture contains:
- `package-lock.json` in both project directories (identical bytes). Its `packages`
  object holds `node_modules/alpha` 1.0.0, `node_modules/@scope/beta` 2.0.0 and
  `node_modules/alpha/node_modules/gamma` 3.0.0.
- Matching `package.json` files in both `node_modules` trees.
- `alpha/README.md` (dirty), `alpha/docs/guide.md` (clean), `@scope/beta/readme.md`
  (clean) and `alpha/node_modules/gamma/CHANGELOG.md` (dirty).
- A `node_modules/.bin/alpha` link to `../alpha/cli.js`.
- `evidence/commands/final-ci.json`: an object with `cwd` = O.
- `evidence/clean-reproduction-commands.json`: an array holding one `npm ci` record at
  O/`clean-reproduction` and one `npm run build` record.
- Two report roots, `evidence/e2e-root-final` (one dirty and one clean
  `error-context.md`, plus a screenshot record and a `network-and-console` record
  without `path` that carries an inline `body`, like the real records in E6) and
  `evidence/e2e-subbase-final` (one dirty attachment). Their sibling `.json` reports
  use a nested suite tree.
- Authored `evidence/README.md`, `evidence.md` and `fixtures/docs/history.md`.
- The fixture inventory, which the suite computes from these fixture bytes. That is
  test data, not enrollment.

Required cases (each variant is its own counted case). In the rows, S stands for
`roadmap/prototypes/starlight` and INV for the inventory path. Expected stdout is exact:
- "exactly" lists every line;
- "plus the whitespace lines of X" adds X's existing `trailing whitespace` lines, which
  follow the sorted new block in the checker's existing order;
- "classified" means no line for those files, so the fixture's dirty enrolled bytes
  produce none.

Every failing case or variant exits 1 with empty stderr. A passing one exits 0 with
exactly the PASS line and empty stderr.

| ID | Behavior |
| --- | --- |
| D01 | Authored-only fixture with Starlight and inventory absent passes with the PASS line |
| D02 | Dirty new Markdown outside any root fails with only its whitespace lines (no registration) |
| D03 | Contained Markdown link to a dirty target reports the target and the link's lexical path |
| D04 | Contained clean Markdown link passes |
| D05 | Broken Markdown link → D4 |
| D06 | Escaping Markdown link to a clean outside file → D6 |
| D07 | Self-loop and two-link cycle → D5 per link |
| D08 | Markdown link to a directory inside roadmap → D7 |
| D09 | Directory link to an outside directory holding dirty Markdown is neither traversed nor reported |
| D10 | Directory link to an inside directory holding dirty Markdown reports only the real path, once |
| D11 | Valid and broken non-Markdown links are silent |
| D12 | FIFO named `x.md` → D2 |
| D13 | Mode-000 Markdown file → D3 (permissions restored before cleanup) |
| D14 | Mode-000 directory → D1 (permissions restored before cleanup) |
| D15 | Two consecutive runs on a multi-diagnostic fixture give identical results and leave the fixture unchanged |
| C01 | Valid enrollment passes although enrolled files contain trailing whitespace; a variant using the fixture's real absolute origin also passes |
| C02 | Relocated origin passes without O existing (asserted before and after) |
| C03 | Missing inventory with a present subject → N1 plus every enrolled dirty file's whitespace lines |
| C04 | Missing inventory with a present but clean subject → N1 only |
| C05 | Inventory present, subject absent → A1 for each report receipt plus N13; exit 1 |
| C06 | New clean narratives and an unregistered new report outside enrolled roots (`evidence/new-run/notes.md`, `evidence/README.md`, `evidence/e2e-new/<dir>/error-context.md` with its `.json`) pass; dirty variants report only their whitespace |
| C07 | Dirty `fixtures/`, `.test-work/`-style and `evidence.md` text stays checked |
| C08 | Altered enrolled vendor bytes → A5 plus that file's whitespace lines |
| C09 | Altered enrolled report bytes → A5 plus whitespace |
| C10 | Missing enrolled vendor file → A1 |
| C11 | Unknown clean Markdown in a vendor root → U1 only |
| C12 | Unknown dirty Markdown in a vendor root → U1 plus whitespace |
| C13 | Unknown clean and dirty Markdown in a report root → U1 (plus whitespace) |
| C14 | Altered lock → A5; that root's dirty files are exposed |
| C15 | Missing lock → A1 |
| C16 | Altered install receipt → A5 |
| C17 | Hash-consistent non-ordinary receipts → V2 each: extra `--ignore-scripts`, exit 1, bool exit, signal, error, `inBandFailure` true, foreign cwd, zero and two npm ci records |
| C18 | Missing `package.json` → A1 on that path |
| C19 | `package.json` version differs → V5; invalid JSON → V4; a hash-consistent lock whose `node_modules/alpha` entry is a string → V5 |
| C20 | `package` not nearest (parent for nested file; intermediate `package.json`; key absent from lock) → V3 |
| C21 | Altered report receipt → A5; missing receipt → A1 |
| C22 | Report omits an enrolled attachment → P6 |
| C23 | Wrong `contentType` → P3 |
| C24 | Foreign attachment prefix → P3 |
| C25 | Same R/P suffix under another prefix → P3 |
| C26 | Noncanonical attachment paths (`..`, `.`, `//`, `%2e%2e`, trailing `/`) → P3. Variant: the same spellings on the screenshot record (any name), including the alias `<O>/<R>/<dir>/./error-context.md` of an eligible attachment, plus a relative and a non-string screenshot `path` → P3 |
| C27 | Duplicate attachment record, including a non-error-context duplicate → P4 |
| C28 | Inconsistent config: relative `configFile`, other basename, `rootDir` mismatch, one `outputDir` mismatch, empty `projects` → P2 |
| C29 | Two reports with different origins → N12; nothing classified |
| C30 | Eligible attachment not enrolled → P5 |
| C31 | Missing enrolled root directory → A1 |
| C32 | Enrolled clean `S/node_modules/@scope/beta/readme.md` replaced by an empty directory → exactly `S/node_modules/@scope/beta/readme.md: not a regular file` (A3) |
| C33 | Enrolled clean `S/node_modules/alpha/docs/guide.md` replaced by a FIFO → exactly D2 and A3 for that path; the FIFO is never opened, so the run ends within its timeout |
| C34 | Report root `S/evidence/e2e-subbase-final` replaced by a regular file → exactly `S/evidence/e2e-subbase-final: not a directory` (A3) |
| C35 | Inventory replaced by an empty directory → `INV: not a regular file` (A3) plus the whitespace lines of every enrolled dirty file; nothing classified |
| C36 | Mode-000 enrolled dirty `S/node_modules/alpha/README.md` → exactly A4 and D3 for that path |
| C37 | Mode-000 primary lock `S/package-lock.json` → A4 for it plus the whitespace lines of the primary root's dirty files; the clean root and both report roots stay classified |
| C38 | Mode-000 install receipt `S/evidence/commands/final-ci.json` → A4 for it plus the whitespace lines of the primary root's dirty files |
| C39 | Mode-000 report receipt `S/evidence/e2e-root-final.json` → A4 for it plus that root's dirty attachment lines; `e2e-subbase-final` still yields O, so both vendor roots stay classified |
| C40 | Mode-000 `S/node_modules/alpha/package.json` → one A4 line for it plus the whitespace lines of `S/node_modules/alpha/README.md`; `gamma` and `@scope/beta` stay classified |
| C41 | Mode-000 inventory → `INV: unreadable` (A4) plus the whitespace lines of every enrolled dirty file; nothing classified |
| C42 | Mode-000 directory `S/node_modules/alpha/docs` → exactly A4 for `S/node_modules/alpha/docs/guide.md` and D1 for the directory. Variant: mode-000 `roadmap/checks` → `INV: unreadable` (A4, not N1) and D1 `roadmap/checks: unreadable directory`, plus the whitespace lines of every enrolled dirty file |
| C43 | Inventory enrolls an extra primary file `alpha/<253 "a" characters>.md`, a grammar-valid 256-character name → exactly `S/node_modules/alpha/<that name>: inaccessible ENAMETOOLONG` (A6; Linux `NAME_MAX` is 255) |
| C44 | Hash-consistent primary lock variants → V1 plus the whitespace lines of the primary root's dirty files: non-JSON text, invalid UTF-8 (`\x80`), a JSON array, an object without `packages`, `packages` as an array, 100,000 nested arrays |
| C45 | Hash-consistent `S/evidence/e2e-root-final.json` variants → P1 plus that root's dirty attachment lines: non-JSON, a JSON array, no `config`, `config` as an array, `suites` as an object, a nested `suites` string, `specs`/`tests`/`results` not arrays, `attachments` as an object, a string attachment record, 100,000 nested arrays under `suites`. Positive variant: an added 2,000-level chain of nested empty suites still classifies and the run passes |
| I01 | Invalid JSON syntax, non-UTF-8 bytes and 100,000 nested arrays → N2 |
| I02 | `NaN`/`Infinity` → N2 |
| I03 | Duplicate keys at top level and in a file object → N3 |
| I04 | `version` 2, `"1"`, `true` → N4 |
| I05 | Unknown key at top, vendor, binding and file level → N4 |
| I06 | Missing keys, wrong types, empty `files` → N4 |
| I07 | Uppercase, 63-character and non-hex hashes → N5 |
| I08 | Absolute, empty, `.`, `..`, `a//b`, trailing `/`, leading `./`, backslash, NUL, `*`, `?`, `[`, `%2e%2e`, space and non-ASCII paths → N6. Root variant: the `e2e-subbase-final` report entry's `root` becomes `S/.test-work`, whose leading-dot component fails the grammar → exactly `INV: noncanonical path at <pointer to that root>`, with no N8, N9 or N10 line (item 5 precedence), plus the whitespace lines of every dirty fixture file, because nothing is classified |
| I09 | Vendor `package.json` enrolled; report file with 1 or 3 components or another name → N7 |
| I10 | Grammar-valid roots outside their section's reviewed set → N8, with the exact lines under "I10 root variants" below: `roadmap/plans`, `roadmap/prototypes/sdk-isolation`, `S/fixtures`, `S/evidence`, `S/src`, `roadmap/checks/recovery`, a report root in the vendor section and a vendor root in the report section |
| I11 | Lock not `<project>/package-lock.json`, swapped install receipts, receipt not `<root>.json`, `package` without `node_modules` prefix → N9 |
| I12 | Duplicated root → N10: a second entry repeats an entry's `root` and bindings but lists files the original does not, so no N9 or N11 line appears |
| I13 | Same file listed twice → N11 |
| I14 | Attempts to classify a plan, an evidence narrative, fixtures, `evidence.md`, an SDK narrative and the recovery README with correct hashes are rejected, and those files stay checked |
| L01 | Enrolled vendor file replaced by a link to an identical copy → A2; the link stays checked through its lexical path |
| L02 | Package directory replaced by a directory link → A2; nothing beneath it is discovered |
| L03 | Vendor root is a directory link → A2 |
| L04 | Symlinked lock, install receipt, report receipt or `package.json` → A2 each |
| L05 | Symlinked inventory → A2; nothing classified |
| L06 | Report root is a directory link → A2 |
| R01 | Importing the live checker runs nothing and writes no bytecode |
| R02 | Live discovery: no errors, all four `.test-work` Markdown file links present, no discovered path with a symlinked directory component, none under any real directory link (counts printed; 194 SDK + 4 Starlight at planning) |
| R03 | Live classification: no errors; verified equals every enrolled path of the live inventory; the four file links are unclassified; verified is a subset of discovered |

**I10 root variants.** Each variant changes only one entry's `root`. That entry's other
values and every other entry stay as in the valid fixture. By item 5 precedence the
changed entry's bindings are not compared, so no N9 line appears. Each variant exits 1
with exactly the lines below (S expanded) plus the whitespace lines of every dirty
fixture file, because nothing is classified:
- `roadmap/plans`, `roadmap/prototypes/sdk-isolation`, `S/fixtures`, `S/src` and
  `roadmap/checks/recovery`, each as the `e2e-subbase-final` report root: only
  `INV: unreviewed root <root>`.
- `S/evidence` as that report root: `INV: unreviewed root S/evidence` and
  `INV: overlapping roots S/evidence and S/evidence/e2e-root-final` (N10, because the
  remaining report root lies below it; E7).
- Report root in the vendor section: `S/evidence/e2e-root`, reviewed for reports and
  unused by the fixture, as the clean vendor root: only
  `INV: unreviewed root S/evidence/e2e-root`.
- Vendor root in the report section: `S/clean-reproduction/node_modules` as the
  `e2e-subbase-final` report root: `INV: unreviewed root S/clean-reproduction/node_modules`
  and `INV: overlapping roots S/clean-reproduction/node_modules and S/clean-reproduction/node_modules`
  (N10, because it equals the clean vendor root; E7).

`S/.test-work` is not an I10 variant: its leading-dot component fails the grammar, so it
is the I08 root variant (N6), never N8. The grammar likewise rejects every root or file
path below `.test-work`, so none of its Markdown can be enrolled.

Template coverage: every item 7 template has at least one required case.

| Family | Template → cases |
| --- | --- |
| D | D1 → D14, C42; D2 → D12, C33; D3 → D13, C36; D4 → D05; D5 → D07; D6 → D06; D7 → D08 |
| N | N1 → C03, C04; N2 → I01, I02; N3 → I03; N4 → I04–I06; N5 → I07; N6 → I08 (including its `.test-work` root variant); N7 → I09; N8 → I10; N9 → I11; N10 → I10, I12; N11 → I13; N12 → C29; N13 → C05 |
| A | A1 → C05, C10, C15, C18, C21, C31; A2 → L01–L06; A3 → C32–C35; A4 → C36–C42; A5 → C08, C09, C14, C16, C21; A6 → C43 |
| V | V1 → C44; V2 → C17; V3 → C20; V4 → C19; V5 → C19 |
| P, U | P1 → C45; P2 → C28; P3 → C23–C26; P4 → C27; P5 → C30; P6 → C22; U1 → C11–C13 |

The R cases are read-only against the live tree. Every other case uses its own
disposable repository under the suite's `mkdtemp` base. In a `finally` block, the suite
restores the permissions it changed and removes only that base.

### 10. Prohibitions (normative)

The correction must not introduce:
- directory-wide exclusions, or classification by name, glob or prefix;
- deletion, normalization or relocation of reports, receipts or dependency bytes;
- automatic or conditional inventory regeneration, or optional validation;
- network access or installs;
- diagnostic filtering;
- changes to any other input population or check, or to the PASS line.

## Per-subject serial task slices

Every slice runs from `/home/karl/repo/huron` with `python` = `/usr/bin/python` →
`/usr/local/bin/python3.14` (CPython 3.14.0). Each slice records role, attempt, invocation
directory, start/end UTC and its progress log. All four slices are pending.

### Slice A — defect baseline and binding recheck (preflight; pending)

- **Who and claims:** `verification`/`discovery`, profile maximum (this host configures
  max). Read claims: `source:repo`, `tool:roadmap-checker`, `plan:checker-inputs`,
  `plan:raw-phases`, `prototype:starlight`, `prototype:sdk-isolation`. Write claims:
  `checks:roadmap`, `build:docs`, `env:python`, `scratch:<name>`. No other workflow runs.
- **Objective:** reproduce the defect on the untouched tree, prove zero binding drift,
  and record versions and state. Nothing is edited.
- **Steps:**
  1. In the first tool call, run the prologue with
     `INV=roadmap/checks/chk-baseline-a1-<UTC>`, then the creation block (`mkdir` and
     tool extraction, once). These are under "Gate wrapper and tool extraction". Every
     later tool call starts with the prologue and the re-entry check, reusing the same
     literal `$INV`.
  2. Run G0–G3, G5–G9 (G9 on `roadmap/check_docs.py` only), G11, G12 and G14, plus a
     single G10 capture. Immediately before G5, run the parent-added gate
     `gate g5-docs-offline env UV_OFFLINE=1 UV_CACHE_DIR=/tmp/opencode/huron-effort-uv-cache make docs`
     (exit 0 and "No issues found"; anything else is BLOCKED, never PASS). It evaluates the
     execution-time condition "`make docs` works offline" after the reboot removed the old
     cache directory (Execution ledger, "Parent host-change record (2026-10-08)").
  3. Report G4 as NOT PRESENT; never create the suite.
- **Acceptance:**
  - G2 exits 1 with stdout `cmp`-identical to `roadmap/checks/3818200d-review-checker.log`.
  - G3 exits 1 at line 150 before case 1.
  - G11 exits 0 with `inventory_file: absent` and projection `3536bb8e…`.
  - G5–G8 pass.
- **STOP conditions:** any other population or diff, drift, a different Python minor
  version, or an unexpected owned path.
- **Deletions:** none.

### Slice B — implementation (actual code; pending)

- **Who and claims:** `implementation`/`code`, profile maximum, exclusive against ALL
  work. Claims are recorded as write `tool:roadmap-checker`, `checks:roadmap`,
  `build:docs`, `env:python`, `scratch:<name>` and read `source:repo`,
  `plan:checker-inputs`, `plan:raw-phases`, `prototype:starlight`,
  `prototype:sdk-isolation` (equivalent to `*:write`).
- **Inputs:** this plan, the contract and the Slice A record.
- **Outputs:**
  - Modified: `roadmap/check_docs.py`.
  - Created (three files): `roadmap/checks/test_check_docs_discovery.py`,
    `roadmap/checks/starlight-markdown-inputs.v1.json` and
    `roadmap/checks/checker-input-boundary-receipt.md`.
  - Unchanged: `roadmap/checks/test_check_docs.py` (run only; G12 proves byte identity).
  - Run outputs in the single invocation directory `roadmap/checks/chk-writer-a1-<UTC>/`.
- **Step 1, pre-edit:**
  - In the first tool call, run the prologue with `INV=roadmap/checks/chk-writer-a1-<UTC>`
    and the creation block (`mkdir` and tool extraction, once). Every later tool call
    starts with the prologue and the re-entry check.
  - `cp -p roadmap/check_docs.py "$INV/check_docs.py.orig"` and verify `e74d7708…`.
  - Verify that the three new owned paths are absent: `ls -d --
    roadmap/checks/test_check_docs_discovery.py
    roadmap/checks/starlight-markdown-inputs.v1.json
    roadmap/checks/checker-input-boundary-receipt.md` exits 2 with empty stdout and one
    "No such file or directory" line per path on stderr. Any existing entry, including a
    dangling link (which `ls -d` lists), is an owned path existing before creation: STOP.
  - Run G10 capture `manifest-before.json`, then rerun the Slice A gate set.
  - STOP on any deviation or drift.
- **Step 2:** implement Interfaces items 1–7 in `roadmap/check_docs.py`, including item
  5's inventory validation (N2–N11). Item 8 is step 3, item 9 is step 4, and item 10
  binds every step.
- **Step 3:** create the inventory (item 8) and confirm `inventory_file: equal`.
- **Step 4:** write the suite (item 9) with every required case.
- **Step 5:** iterate until G2 and G4 pass. Then run the complete final gate G0–G14
  with G10 compare `--changed roadmap/check_docs.py --added
  roadmap/checks/test_check_docs_discovery.py --added
  roadmap/checks/starlight-markdown-inputs.v1.json`. The receipt is still absent.
- **Step 6:**
  - Create the receipt (exclusive create), with the contents under Escalation.
  - Then, in the same `$INV`, run the post-receipt gates with the IDs
    `post-receipt-g2-checker` (G2), `post-receipt-g7-ignore` (G7) and
    `post-receipt-g9-receipt` (G9 on the receipt only).
  - They pass with G2 exit 0 and exactly the PASS line, every G7 line at
    `.gitignore:40:/roadmap/`, and G9 `OK: 1 files clean`.
  - The receipt names these logs in advance, because it cannot contain their results.
- **Acceptance:** every criterion under Acceptance.
- **Skills:** listed under Skills.
- **Deletions:** none.

### Slice C — independent maximum qualification (pending; review 1 of at most 3)

- **Who and claims:** a fresh `verification`/`review` worker, profile maximum. It
  starts only after Slice B is terminal and its processes are stopped. Read claims:
  `tool:roadmap-checker` (the subject label), `source:repo`, `plan:checker-inputs`,
  `plan:raw-phases`, `prototype:starlight`, `prototype:sdk-isolation`. Write claims:
  `checks:roadmap`, `build:docs`, `env:python`, `scratch:<name>`.
- **Edits:** none, including through the shell, beyond its own invocation directory and
  normal gate outputs.
- **Invocation:** one `$INV` (`roadmap/checks/chk-review-a<N>-<UTC>/`) through the
  prologue, the creation block (first tool call only) and the re-entry check.
- **Objective:**
  - Independently inspect this plan, the contract and the diff (G13 using the writer's
    `check_docs.py.orig`; verify `e74d7708…`).
  - Check the inventory equality (G11) and harness byte identity (G12).
  - Check suite coverage against the required case table, and every diagnostic template.
  - Rerun ALL gates G0–G14 with its own G10 before/after manifests (no declared
    changes).
- **Output:** a `verdict.json` (PASS/FAIL/BLOCKED with findings by file/symbol) plus logs
  in `roadmap/checks/chk-review-a<N>-<UTC>/`, and the final response. The verdict
  includes the original-63 comparison (G12 harness identity and the G3 counts) and the
  artifact population and byte equality (G10). Review 3
  classifies each remaining issue as a fixable defect or a plan defect.

### Slice D — fix and requalification (conditional; pending)

- **Trigger:** a Slice C FAIL before review 3.
- **Who:** an `implementation`/`code` fix worker with the same claims and exclusivity as
  Slice B, in `roadmap/checks/chk-fix-a<N>-<UTC>/`.
- **Work, in order:**
  1. Run the prologue and creation block for its own single `$INV`
     (`roadmap/checks/chk-fix-a<N>-<UTC>/`), as in Slice B step 1. Take the G10
     before-capture `manifest-before.json` before any edit.
  2. Address every finding.
  3. Rerun the complete final gate G0–G14, ending with the G10 after-capture and
     compare. The compare declares exactly the owned files this fix changed
     (`--changed`) or created (`--added`).
  4. Append a dated "Fix attempt N" section to the receipt, preferably after the G10
     after-capture. If the append happens before that capture, the compare must also
     declare `--changed roadmap/checks/checker-input-boundary-receipt.md`.
  5. Earlier receipt sections stay byte-identical. Before appending, record the
     receipt's byte size and SHA-256 in `$INV/receipt-before.json`. After appending, the
     first that-many bytes (`head -c <size>`) must hash to the recorded value.
  6. Then run the post-append gates in the same `$INV`, with the Slice B step 6 IDs and
     pass criteria: `post-receipt-g2-checker`, `post-receipt-g7-ignore` and
     `post-receipt-g9-receipt`. The appended section names these logs in advance.
- **Next:** a fresh Slice C follows. After review 3 fails, stop: record all reports,
  ownership and remaining defects, and route plan or contract defects to
  `/implementation-plan` or `/design-plan`.

## Skills

- `.agents/skills/implementation-plan/SKILL.md`: this plan and its independent review.
- `.agents/skills/implement-markdown/SKILL.md`, with `.agents/commands/implement-markdown.md`
  and `.agents/workflows/implement-markdown.md`: execution of slices A–D.
- `.agents/skills/design-plan/SKILL.md`: only if a reviewer reports a contract-level
  (design) defect.
- Also read `.agents/workflows/orchestration.md`, `.agents/workflows/verification.md`,
  `.agents/templates/phase-plan.md`, `.agents/templates/assignment.md`,
  `docs/getting-started/testing.md` and `docs/getting-started/docstrings.md`.
- Docstrings are Google style with a summary line and, where applicable, Args, Returns
  and Raises. Test docstrings state the behavior as a fact. Neither code nor tests
  reference plans, phases or reviews.
- Not applicable, because there is no Core/domain, API, database, Svelte, Tailwind,
  browser or OpenCode-configuration change: `oop-design`, `fastapi`,
  `postgresql-table-design`, `svelte-code-writer`, `svelte-core-bestpractices`,
  `tailwind-design-system`, `playwright-cli` and `customize-opencode`.

## Acceptance and complete applicable gates

**Acceptance criteria.**
1. The original harness is byte-identical (`4cb36369…`). It passes 63 cases, 19
   accepted and 44 rejected, with every original name, input, exact
   exit/stdout/stderr expectation, the exit-0 baseline prerequisite and its
   preservation checks. The empty-status trailing-whitespace diagnostic remains.
2. The checker exits 0 on the retained tree with the exact PASS line and empty stderr.
3. Exactly the 1,184 enrolled identities are classified (R03). Every other discovered
   Markdown file remains a whitespace input (R02), including the four Markdown file
   links, all SDK Markdown, plans and receipts.
4. The inventory equals the appendix generator's projection (`3536bb8e…`). It was
   created once, never edited or regenerated.
5. Every required case D01–D15, C01–C45, I01–I14, L01–L06 and R01–R03 passes with exact
   outputs, no writes and no traceback, and every item 7 template has a case.
6. Retained artifacts, reports, receipts, dependency bytes, plans, Git-visible files,
   HEAD, index and status are unchanged except for the declared owned outputs (G10).
   No `__pycache__`, leftover fixture or residual process remains.
7. Strict docs, diff check, ignore checks, an empty `git ls-files roadmap` and the
   new-text scans all pass.
8. The receipt contains every required item, and its post-receipt checks pass.

**Gate set.** Run from `/home/karl/repo/huron`.
- Interpreter: `python` = CPython 3.14.0. Tools run with `python -I -B`.
- Tool timeout is 600000 ms for G3 and G4. Run each of them in its own tool call; use
  a background run with polling if needed, and never abandon or kill a running harness.
- Report every exit separately. Each command is logged by `gate` into `$INV`.
- `$WRITER_INV` is the writer's invocation directory, as named in the receipt.
- Git status and diff run with `--no-optional-locks`, so they cannot refresh the index
  that G10 preserves. Their output is identical to the contract's plain commands.

| ID | Command | Baseline (A, B step 1) | Final (B, C, D) |
| --- | --- | --- | --- |
| G0 | `python -c 'import sys; print(sys.version)'`; `readlink -f "$(command -v python)"`; `uv --version`; `git --version`; `make --version`; `.venv/bin/python --version` | 3.14.0, `/usr/local/bin/python3.14`, uv 0.12.19, git 2.53.0, GNU Make 4.4.1, `.venv` 3.12.4 (git and Make re-pinned by the parent after the 2026-10-07 host upgrade; see the Execution ledger row "Parent host-change record (2026-10-08)"); a minor-version change is BLOCKED | same |
| G1 | `git --no-optional-locks status --short --untracked-files=all` | exit 0; record lines and SHA-256 (55 entries at planning) | exit 0, byte-identical to this invocation's first G1 capture |
| G2 | `python roadmap/check_docs.py` | exit 1; 2,330 lines; stdout `cmp`-identical to `roadmap/checks/3818200d-review-checker.log`; empty stderr | exit 0; stdout is exactly the PASS line plus newline; empty stderr |
| G3 | `python roadmap/checks/test_check_docs.py` | exit 1; stderr AssertionError at line 150; stdout only the 5 `Preserved` lines | exit 0; 63 case lines, 5 `Preserved` lines, then `OK: 19 accepted + 44 rejected = 63 CLI cases; baseline exit 0`; empty stderr; no `roadmap/plans/check-docs-*.md` left |
| G4 | `python roadmap/checks/test_check_docs_discovery.py` | NOT PRESENT (never created in baseline) | exit 0; empty stderr; every required ID printed; last line `OK: <N> discovery/classification cases` with N at least the number of required cases and variants; its temporary base removed |
| G5 | `UV_CACHE_DIR=/tmp/opencode/huron-effort-uv-cache make docs` (recipe `uv run --group docs zensical build --strict`) | exit 0; "No issues found" | same; missing cache/network → BLOCKED, not PASS |
| G6 | `git --no-optional-locks diff --check` | exit 0, empty | same |
| G7 | `git check-ignore -v roadmap/check_docs.py roadmap/checks/test_check_docs.py roadmap/checks/test_check_docs_discovery.py roadmap/checks/starlight-markdown-inputs.v1.json roadmap/checks/checker-input-boundary-receipt.md roadmap/plans/checker-input-boundary.md "$INV"` | exit 0; every line `.gitignore:40:/roadmap/` plus a tab and the path; absent paths are still matched | same; all owned paths exist |
| G8 | `git ls-files roadmap` | exit 0, empty | same |
| G9 | `python -I -B "$INV/text_scan.py" roadmap/check_docs.py roadmap/checks/test_check_docs_discovery.py roadmap/checks/starlight-markdown-inputs.v1.json` (receipt added post-receipt) | `roadmap/check_docs.py` only | exit 0, `OK: 3 files clean` (receipt: `OK: 1 files clean`) |
| G10 | `python -I -B "$INV/manifest.py" capture /home/karl/repo/huron "$INV/manifest-before.json" --exclude "$INV"`; after the gates `capture … manifest-after.json`, then `compare … "$INV/manifest-compare.json"` with declared changes | capture only | exit 0. Writer: declared checker change plus suite and inventory additions. Fixer: exactly the owned files it changed or created, plus the receipt when appended before the after-capture (Slice D). Reviewer: nothing declared. HEAD, index, status and visible set equal |
| G11 | `python -I -B "$INV/recheck_bindings.py" /home/karl/repo/huron "$INV/g11-recheck-result.json"` | exit 0; `inventory_file: absent`; counts 1,140/44/862/431/570 | exit 0; `inventory_file: equal` |
| G12 | `sha256sum roadmap/checks/test_check_docs.py roadmap/checker-input-boundary-plan.md roadmap/checks/3818200d-review-input-proof.json` | `4cb36369…`, `d2f71de5…`, `f4a58065…` | same three values; the same command with `roadmap/check_docs.py roadmap/checks/test_check_docs_discovery.py roadmap/checks/starlight-markdown-inputs.v1.json` appended records the new hashes (inventory `3536bb8e…`) |
| G13 | `sha256sum "$WRITER_INV/check_docs.py.orig"` = `e74d7708…`; `diff -u -w "$WRITER_INV/check_docs.py.orig" roadmap/check_docs.py` | n/a | reviewed: only the planned structure, helpers and line-49 change |
| G14 | `pgrep -af '^([^ ]*/)?python[0-9.]*( [^ ]*)* [^ ]*check_docs'` (anchored at the interpreter, so a shell whose own command line mentions the checker cannot self-match); `ls -d roadmap/__pycache__ roadmap/checks/__pycache__`; `ls -d roadmap/plans/check-docs-*.md`; own `huron-checker-discovery-*` base | pgrep exit 1 with no output; all `ls` report "No such file" | same |

Gate wrapper and tool extraction (copy the blocks exactly; `$INV` is the invocation
directory). One invocation uses exactly one `$INV` for all of its gates, logs, manifests
and progress lines. Claude Code Bash calls keep no shell variables or functions, and the
working directory resets between calls. Therefore:
- Choose the name once, immediately before creation: `<UTC>` is the output of
  `date -u +%Y%m%dT%H%M%SZ`. Record the full literal name in the worker's notes and as the
  first line of `$INV/progress.log`. Later calls reuse that literal and never call `date`
  for it.
- Every tool call, the first included, starts with the prologue.
- The first tool call alone then runs the creation block, without `-p`, never repeated.
  Its two guards exit that tool call with status 1 before any gate runs:
  - If `mkdir` fails (normally because the name already exists, for example a recorded
    literal reused by a re-dispatched session), nothing was written. The worker records
    the message and starts again with a new first tool call and a new `<UTC>`. A second
    `mkdir` failure is a STOP.
  - If the extraction fails, STOP and escalate. The partly filled directory is
    preserved and never reused.
- Every later tool call runs the re-entry check right after the prologue. If it fails,
  STOP; never create a replacement directory for a running invocation.
- Gate IDs are unique within an invocation. A deliberate rerun uses a suffixed ID such as
  `g2-checker-r2`, so no log is overwritten.

Prologue (every tool call):

```sh
cd /home/karl/repo/huron
INV="roadmap/checks/chk-<role>-a<attempt>-<UTC>"
gate() {
  id=$1; shift
  printf '%s\n' "$*" >"$INV/$id.cmd"
  started=$(date -u +%FT%T.%3NZ)
  "$@" >"$INV/$id.out" 2>"$INV/$id.err"
  code=$?
  printf '{"id": "%s", "exit": %d, "started": "%s", "finished": "%s", "cwd": "%s"}\n' \
    "$id" "$code" "$started" "$(date -u +%FT%T.%3NZ)" "$PWD" >"$INV/$id.json"
}
```

Creation block (first tool call only, right after the prologue):

```sh
mkdir "$INV" || { echo "STOP: cannot create $INV (it may exist); choose a new <UTC>"; exit 1; }
python -I -B - roadmap/plans/checker-input-boundary.md "$INV" <<'EOF' || { echo "STOP: tool extraction failed in $INV"; exit 1; }
import hashlib, re, sys
from pathlib import Path
plan, target = Path(sys.argv[1]).read_text(), Path(sys.argv[2])
pattern = r"^#### Tool file `([a-z_]+\.py)` SHA-256 `([0-9a-f]{64})`\n\n```python\n(.*?)^```$"
tools = re.findall(pattern, plan, re.M | re.S)
assert [name for name, _, _ in tools] == ["recheck_bindings.py", "manifest.py", "text_scan.py"], tools
for name, digest, body in tools:
    assert hashlib.sha256(body.encode()).hexdigest() == digest, name
    with open(target / name, "x", encoding="utf-8") as handle:
        handle.write(body)
    print(name, digest)
EOF
```

Re-entry check (every later tool call, right after the prologue), followed by gate calls
such as the last two lines. In the first tool call, gate calls follow the creation block.

```sh
test -d "$INV" && test -f "$INV/recheck_bindings.py" && test -f "$INV/manifest.py" && test -f "$INV/text_scan.py" || { echo "STOP: $INV is not this invocation's directory"; exit 1; }
gate g2-checker python roadmap/check_docs.py
gate g5-docs env UV_CACHE_DIR=/tmp/opencode/huron-effort-uv-cache make docs
```

**Not applicable.** This boundary is local, ignored tooling only (contract lines 385–389).
- `make lint` (scoped to `src`), the pytest unit/contract/integration/acceptance suites,
  the frontend gate and the `.agents` npm gate do not apply.
- The configured 96.01% coverage floor, import, complexity and duplication ratchets stay
  unchanged.
- The Starlight build/browser and SDK fresh runs are separate subjects.

**Testing standard** (verbatim from `.agents/workflows/verification.md`):

```text
Before adding tests, find existing public-behavior coverage, parametrization,
scoped conftest/fixtures and helpers; reuse or extend them. Discover fixtures with
pytest `--fixtures`/`--fixtures-per-test` when unclear. Test changed contracts,
happy/error paths, boundaries, permissions, retries, concurrency and recovery as
applicable. Assert observable outcomes rather than private call sequences. Control
time/randomness, isolate mutable state, and mock only external I/O. Real filesystem
and PostgreSQL contracts prove durability/locking that fakes cannot. Frontend pure
behavior/API seams use Vitest; cross-route interactions use Playwright. Delete
obsolete owned tests instead of skipping them. Comments/docstrings/test names
describe enduring behavior, not plan phases. No suppressions, exclusions, skips,
xfails, weakened assertions, thresholds or contracts to manufacture a pass.
```

**Progress contract** (verbatim from `.agents/workflows/orchestration.md`):

```text
Every implementation, fix, and verification subagent must send a brief progress update at least every 15 minutes of elapsed time while its assignment remains active, including during validation. Send blockers, repeated failures, and suspected hangs immediately rather than waiting for the next interval. These are progress messages, not final implementation reports or verification verdicts. Keep each update to 2-4 short lines containing the phase/task, agent role and attempt number, elapsed time, concrete progress since the previous update, current operation or command, and the next step or blocker. If nothing has advanced, say so and identify the last observed activity; do not substitute 'still working' for evidence. Parent polls asynchronously at least once per minute.
```

**Host limitation (accepted by the user 2026-10-06).** Workers cannot send mid-run
messages. The user watches live progress in the workflow view, and the orchestrator
reports at workflow boundaries; runs are resumable by run ID. Each worker therefore
appends a timestamped progress line (phase/task, role and attempt, elapsed time,
concrete progress, current command, next step or blocker) to `$INV/progress.log` at
least every 15 minutes, including during validation. Blockers, repeated failures and
suspected hangs are recorded immediately and returned in the final response.

## Blockers and readiness

| # | Blocker | Owner | Next action |
| --- | --- | --- | --- |
| 1 | Independent maximum review 3 of this file, the last of at most three (review 1 FAIL, F1–F9 dispositioned by fix attempt 1; review 2 FAIL, R2-F1–R2-F3 dispositioned by fix attempt 2) | parent | Dispatch `verification`/`review`, profile maximum. Read claims: `plan:checker-inputs`, `tool:roadmap-checker`, `source:repo`, `plan:raw-phases`, `prototype:starlight`, `prototype:sdk-isolation`; `checks:roadmap` read for one checker run. There is no fourth plan review: after a FAIL the parent records the reports and remaining defects and decides the route |
| 2 | Canonical dictionary entries | parent | Record the `tool:roadmap-checker` extension (new suite, inventory, receipt) and the `checks:roadmap` invocation-directory and temp-prefix outputs. Record the label mapping: the OpenCode-era `prototype:sdk` (`roadmap/resource-ledger.md` line 24) is `prototype:sdk-isolation` (`roadmap/prototypes/sdk-isolation/`), and `cache:uv` is the uv cache within `build:docs`. Reconcile `roadmap/resource-ledger.md` |
| 3 | Exclusive admission and quiescence | parent | No concurrent workflow during A–D. No roadmap Markdown, plan 000–010, Starlight, SDK or `source:repo` writer, so the live plan-001 harness markers stay intact |

**Resolved:** the bounded enrollment authorization (parent approval), host tools present
(verified at planning), the proof pin, the gate tools (tested), and placement and
mapping (this file).

**Execution-time conditions (STOP if false):** Slice A baseline equals E1 and E2. Python
is 3.14.x. `make docs` works offline (Slice A gate `g5-docs-offline`; the original cache
directory was removed by the 2026-10-07 reboot, see the Execution ledger). Plan 001 still contains
exactly one `## Serial task slices` line, one status line, `## Skills`, `make docs` and
`.agents/skills/design-plan/SKILL.md`.

**Readiness:** NOT READY until blocker 1 passes and blockers 2–3 are recorded. Then the
parent sets the lifecycle to `ready — …` and dispatches Slice A.

## Follow-on work (out of scope)

- **SDK independent review 2:** after this correction is independently qualified, a
  separate maximum review reruns the SDK full applicable gate: fresh runs with new IDs,
  `check_artifacts.py`, strict docs, the corrected root checker, diff, status, ignore
  and `git ls-files roadmap`, plus the review-1 supplemental checks. This correction
  cannot convert SDK review 1's FAIL.
- **Artifact-layout rule (E1):** version 1 covers only the retained snapshot. New npm
  installs, Python environments or test reports under `roadmap/` (P5 web-session probes,
  fresh Starlight runs, environment-heavy probes) would immediately reintroduce
  findings. A layout rule must be designed and reviewed before P5 or any fresh Starlight
  run. Options: keep dependencies, caches and reports outside the scanned roadmap tree,
  recorded in evidence, or adopt a reviewed producer protocol. It must not become a
  repeated enrollment loop.
- **Starlight fresh-run/output protocol:** this blocks only Starlight final
  qualification (`scripts/reproduce.mjs` refuses an existing `clean-reproduction`). It is
  defined separately with unique fresh output locations and provenance validation.
- **Resource-ledger and durable-record reconciliations:** owned by the parent.

## Execution ledger

**Runtime facts.**
- Host: Claude Code. The OpenCode `implementation_start`/`implementation_status` tools
  do not exist here.
- Worker: a Claude Code workflow subagent. Configured model `claude-opus-5-5`, configured
  effort max; provider effort acceptance not proven.
- Progress-delivery limitation accepted by the user 2026-10-06: workers cannot send
  mid-run messages, the user watches live progress in the workflow view, the
  orchestrator reports at workflow boundaries, and runs are resumable by run ID.
- The orchestrator admits code work exclusively by running no other workflow
  concurrently.
- Loaded schema and restart: this plan and its slices change no agent tooling, plugin,
  prompt, skill or schema, so no OpenCode quit/restart is required. The loaded host
  schema above stays in force.

**History.**

| Entry | Detail |
| --- | --- |
| Contract planning and reviews | see the Context and outcome table (review 2 of 3 on the contract, no contract defect) |
| This execution plan, attempt 1 | Role `implementation`, activity `planning`, Claude Code workflow subagent. Orchestrator-recorded wave-1 track A run `wf_b9a96f3d-d8a`, task `w1yab60ju` (not independently verified by the worker). Started 2026-10-06T13:49:00Z |
| Claims (attempt 1) | write `plan:checker-inputs` (only creating this file) and `scratch:chk`; read `tool:roadmap-checker`, `source:repo`, `plan:raw-phases`, `checks:roadmap` (one checker run) |
| Owned diff (attempt 1) | this file only. The contract stays at `d2f71de5…` with no pointer. No nested agents |
| Planning probes (attempt 1) | E3/E4 read-only; outputs in the session scratch directory only |
| Self-checks (attempt 1) | listed under Escalation. Results are in the worker's final structured report and scratch logs. The single real checker run (exit 1, the known 2,330 lines byte-identical to the review logs, no line from this file) covered bytes `8a0695bc…`. One later edit (the G14 process pattern and this row) was validated by a nonwriting replica of the checker's plan rules and a text scan, not by a second run. The plan review reruns the checker |
| Independent plan review 1 | Role `verification`, activity `review`, Claude Code workflow subagent independent of the writer. Window 2026-10-06T14:36:28Z to about 15:00Z, subject bytes `a6f336f3…`. FAIL: F1 and F2 medium, F3–F9 low. No enrollment, binding, contract-hash or claim-upgrade defect. The known checker exit 1 is the subject, not a plan defect. Its single checker run was byte-identical to the review logs and wrote nothing |
| Planning fix attempt 1 | Role `fix`, activity `planning`, Claude Code workflow subagent. A first session started 2026-10-06T15:01:09Z and stopped after reading inputs without writing; this file stayed `a6f336f3…`. The re-dispatched session started 18:31:27Z and applied every finding (dispositions below) |
| Claims (fix attempt 1) | write `plan:checker-inputs` (only this file) and `scratch:chk`; read `tool:roadmap-checker`, `source:repo`, `checks:roadmap` (one checker run). E6 also read the seven hashed report receipts once, without writing, after checking their hashes against the proof. Under this plan's mapping those bytes belong to `prototype:starlight`, which the dispatch did not list; no writer of it was active (the fixer was the wave's only roadmap writer) |
| Owned diff (fix attempt 1) | this file only. The contract stays at `d2f71de5…` with no pointer. The appendix tool bodies and hashes are unchanged. No nested agents |
| Self-checks (fix attempt 1) | listed under Escalation; results are in the worker's final structured report. The single real checker run covered this file's final fix-attempt-1 bytes |
| Independent plan review 2 | Role `verification`, activity `review`, Claude Code workflow subagent independent of the writer and fixer. Started 2026-10-06T19:01:37Z, terminal 19:25:19Z by its progress log; subject bytes `cf832c68…`. FAIL: R2-F1 medium, R2-F2 and R2-F3 low. It confirmed F1–F9 resolved and found no enrollment, binding, contract-hash, original-63 or claim-wording defect. Its single checker run was byte-identical to the review logs and wrote nothing |
| Planning fix attempt 2 | Role `fix`, activity `planning`, Claude Code workflow subagent. Started 2026-10-06T19:26:12Z from bytes `cf832c68…` (equal to the review-2 snapshot) and applied every finding (dispositions below) |
| Claims (fix attempt 2) | write `plan:checker-inputs` (only this file) and `scratch:chk`; read `tool:roadmap-checker`, `source:repo`, `checks:roadmap` (one checker run). E7 read only the pinned proof (hash-checked), review 2's scratch results and a scratch copy of this file; it read no `prototype:starlight` bytes directly |
| Owned diff (fix attempt 2) | this file only. The contract stays at `d2f71de5…` with no pointer. The appendix tool bodies and hashes are unchanged (E7 extracted all three with their pinned digests). No nested agents |
| Self-checks (fix attempt 2) | listed under Escalation; results are in the worker's final structured report and scratch logs. The E7 wrapper test was repeated on this file's final fix-attempt-2 bytes, and the single real checker run covered the same bytes |
| Review count | 3 of at most 3 for this file (review 1 FAIL, fix attempt 1 applied; review 2 FAIL, fix attempt 2 applied; review 3 PASS). No further plan review is permitted; later changes go through Slice D fixes or a parent-recorded route |
| Independent plan review 3 | Role `verification`, activity `review`, Claude Code workflow subagent independent of the writer and both fixers. Started 2026-10-06T19:50Z by its progress log; subject bytes `efe06ee9…` (2,158 lines). PASS. R2-F1–R2-F3 verified resolved with its own code; enrollment, bindings, inventory projection `3536bb8e…`, original 63 cases and claim wording correct. New findings, all low and non-blocking: R3-F1 (on git 2.43.0 `git --no-optional-locks diff` can still refresh `.git/index` when a tracked file has changed stat data but unchanged content), O1 (report-root walk after N12 unspecified; C29 output identical either way), O2 (progress-log location: scratch or `$INV`, both permitted), O3 (final G7 covers the owned paths that exist at that step), O4 (`def main() -> None:` vs illustrative `def main():`, either satisfies G13) |
| Parent readiness record (2026-10-07) | Blocker 2 recorded in `roadmap/resource-ledger.md` section 'Claude Code session dictionary (2026-10-07)': `tool:roadmap-checker` extended to `roadmap/checks/test_check_docs_discovery.py`, `roadmap/checks/starlight-markdown-inputs.v1.json` and `roadmap/checks/checker-input-boundary-receipt.md`; `checks:roadmap` covers `roadmap/checks/chk-*` invocation directories and the `${TMPDIR:-/tmp}/huron-checker-discovery-*` fixture prefix; OpenCode-era `prototype:sdk` = `prototype:sdk-isolation`; `cache:uv` is the uv cache inside `build:docs`. Blocker 3: the orchestrator admits Slices A–D with no other workflow running. R3-F1 disposition: parent probe 2026-10-07 found no stat-dirty tracked entry (`git --no-optional-locks diff-files --name-only` equals the 51 content-modified tracked paths; raw index SHA-256 unchanged `a9665037…`), and no tracked file is written during A–D, so no refresh is expected; if G10 nevertheless reports an index-only difference, the worker STOPs and reports to the parent (never treats it as PASS). O1–O4 need no change. Status set to `ready — …` by the parent; this file's bytes after this record are no longer `efe06ee9…` |
| Parent host-change record (2026-10-08) | After readiness and before Slice A, the host rebooted (2026-10-07 13:46Z) and came back upgraded to Ubuntu 26.04.1 LTS. Observed by the parent on 2026-10-08: `python` still resolves to `/usr/local/bin/python3.14` (3.14.0); uv 0.12.19 and `.venv` 3.12.4 are unchanged; git is now 2.53.0 (was 2.43.0) and GNU Make 4.4.1 (was 4.3). G0 is re-pinned to these values; any other version change is still BLOCKED. Coreutils are now uutils 0.10.0. The parent probed the forms these gates rely on and found them equal to the GNU behaviour: `ls -d` on missing paths exits 2 with one "No such file or directory" line per path, `date -u +%FT%T.%3NZ` works, and the `sha256sum` and `stat -c` formats match. `cmp` (GNU diffutils 3.12) and `pgrep` (procps-ng 4.0.4) are unchanged in kind. The /tmp cleanup at boot removed the docs uv cache `/tmp/opencode/huron-effort-uv-cache` (28K, metadata only). G5 runs unchanged at the same path, where uv recreates the directory. Slice A adds gate `g5-docs-offline` (Slice A step 2) for the condition "`make docs` works offline". R3-F1 named git 2.43.0. The same `--no-optional-locks` rule and the G10 index STOP apply on git 2.53.0. Repository fingerprints are unchanged: HEAD `2b2e9c0`, porcelain SHA-256 `f3f77447…` (55 entries), index `a9665037…`, diff `8fc596fb…`. After this edit the parent's checker rerun stays `cmp`-identical to `roadmap/checks/3818200d-review-checker.log` |
| Slices A–D | pending. The parent adds one row per child (activity, claims, start, last progress, terminal evidence, verdict) only between slices, never during a `checks:roadmap` run. Each edit keeps a single valid status line |

**Plan review 1 dispositions (planning fix attempt 1).** Every finding was accepted; none
was weakened or disputed.

| Finding | Correction |
| --- | --- |
| F1 (medium): `read_regular` let a `PermissionError` from a component `lstat` escape | Interfaces item 3 now defines `os_error_reason`, `lstat_components`, `read_regular` and `directory_problem`. EACCES or EPERM from any component `lstat` or the `open` is A4 `unreadable`. Any other `OSError`, such as ENAMETOOLONG (E6), is the new A6 `inaccessible <errno name>`. Stderr stays empty. Rule 1 uses the same walk for inventory and subject presence, so an unreadable inventory is A4, not N1. Item 1 names these conditions. Parsing and the suite walk got the same treatment: the shared parse rule, an iterative walk, N2 for `RecursionError`, and object `projects` elements in P2 |
| F2 (medium): no case for A3, A4, V1 or P1 | Added C32–C35 for A3 (directory and FIFO vendor paths, report root as a file, inventory as a directory). Added C36–C42 for A4 (mode-000 enrolled file, lock, install receipt, report receipt, `package.json` and inventory; an enrolled file and the inventory below mode-000 directories). Added C43 for A6, C44 for V1 and C45 for P1. Each states its exact lines; failing variants exit 1, the C45 positive variant passes, and stderr stays empty. Permission cases fingerprint before `chmod` and after restoring modes. P1 and the per-file stop rule are now precise, so the triples are exact. A coverage table maps every item 7 template to cases, and acceptance criterion 5 lists C01–C45 |
| F3 (low): Slice B miscounted owned paths and omitted item 5 | Slice B names the three new paths and checks their absence with `ls -d`. Its outputs list one modified file, three created files and the unchanged harness. Step 2 covers items 1–7, including item 5 (N2–N11) |
| F4 (low): the wrapper could not span Bash calls | The wrapper is split into a prologue for every tool call, a once-only creation block and a re-entry check. One invocation uses exactly one `$INV`, and gate IDs are never reused. Slices A–D cite the blocks, and a failed re-entry is a STOP |
| F5 (low): Slice D lacked post-append checks | Slice D orders its work, with the G10 before-capture ahead of any edit. It records the receipt's size and hash before appending, then proves earlier sections unchanged. It runs `post-receipt-g2-checker`, `post-receipt-g7-ignore` and `post-receipt-g9-receipt`. It declares the receipt `--changed` when the append precedes the G10 after-capture. Slice B step 6 uses the same IDs and pass criteria |
| F6 (low): `prototype:sdk` is not the dictionary label | Every claim reads `prototype:sdk-isolation` (`roadmap/prototypes/sdk-isolation/`). Read-only inputs and blocker 2 record the OpenCode-era `prototype:sdk` alias next to `cache:uv`. Until reconciled, either spelling conflicts with the other |
| F7 (low): `<json path>` and V5 were ambiguous | `<json path>` is `json.dumps(record.get("path"))`: `null` when absent, and for P4 the duplicated canonical path. V5 uses exactly `entry.get("name") or package.rsplit("node_modules/", 1)[1]`, the rule E3 and the recheck tool verified on 862 bindings. A lock entry that is not an object fails V5 (C19 variant) |
| F8 (low): a noncanonical alias escaped P3 and P4 | P3 also covers a noncanonical `path` on a record of any name. Its template now reads `invalid attachment`, since P3 is no longer limited to `error-context`. Records without `path` stay valid, and P4's count is then complete. E6 found 0 noncanonical among the 132 real paths, so the retained tree is unaffected; a real-tree violation is a STOP. C26 gains a variant, and the fixture gains a record without `path` |
| F9 (low): no restart statement | Runtime facts state that no tooling, plugin, prompt, skill or schema changes, so no quit/restart is required |

**Plan review 2 dispositions (planning fix attempt 2).** Every finding was accepted; none
was weakened or disputed. One optional suggestion in R2-F1 was applied in a different
form, with the evidence given in its row.

| Finding | Correction |
| --- | --- |
| R2-F1 (medium): I10 required N8 for the root `roadmap/prototypes/starlight/.test-work`, whose leading-dot component fails the item 3 grammar, so only N6 was possible | The `.test-work` root is now the I08 root variant, with the exact line `INV: noncanonical path at <pointer to that root>` and no N8, N9 or N10 line (E7 reran `relative_parts` verbatim). I10 keeps only grammar-valid roots: `roadmap/plans`, `roadmap/prototypes/sdk-isolation`, Starlight `fixtures`, `evidence` and `src`, `roadmap/checks/recovery`, a report root in the vendor section and a vendor root in the report section. A new "I10 root variants" paragraph gives each variant's construction and exact lines. Item 5 gains a diagnostic-precedence rule: a wrong type is N4 only, a grammar failure is N6 only, and bindings are compared only for a grammar-valid reviewed root. Without it N9 was implementation-defined for these variants: `REVIEWED_VENDORS[root]` does not exist for an unreviewed vendor root, and nothing said whether the `<root parent>` and `<root>.json` rules apply to a noncanonical root. Item 7's N6, N9 and N10 conditions say the same, and their templates are unchanged. The optional suggestion (replace the root and its `<root>.json` receipt so that no N9, N10 or N11 line appears) became "replace only the root". Under the precedence rule an unreviewed root's receipt is never compared, and `roadmap/prototypes/starlight/.test-work.json` would itself fail the grammar (E7). Two variants cannot avoid N10, so their exact lines include it: `evidence` is an ancestor of the remaining report root, and a vendor root placed in the report section equals the clean vendor root (E7). I12 now says its second entry repeats the root and bindings but lists other files, so it gives N10 without N9 or N11. Coverage: N6 → I08 and N8 → I10 stay; N10 → I10, I12 |
| R2-F2 (low): E6 said the 191 records without `path` have no `body`; E3 called 482 checks "intermediate directories" | E6 now says the 191 records "have no `path` key; each carries an inline `body`". Its correction note names the cause: the fix-1 probe counted `body` only on records with a `path`, and review 2's verifier found `body` on all 191. E3 now says "482 intermediate-directory checks (241 per tree, over 27 distinct directories per tree)". E7 recomputed 241 checks per tree over 27 distinct directories from the pinned proof alone. The fixture's `network-and-console` record now carries an inline `body`, like the real shape. No rule reads `body` |
| R2-F3 (low): the creation block kept going after a failed `mkdir` | The creation block now ends the tool call with status 1, before any gate, when `mkdir` fails and when the extraction fails: each command carries a guard that prints a `STOP:` line and runs `exit 1`. The wrapper prose says what follows. A failed `mkdir` wrote nothing, so the worker restarts with a new `<UTC>` in a new first tool call; a second failure is a STOP. A failed extraction is a STOP, and its directory is preserved and never reused. The escalation list names both. E7 reproduced the old behavior in scratch (overwritten log, gate after a failed extraction, exit 0) and showed the corrected block exiting 1 with the existing directories byte-identical |

## Escalation / final receipt

**STOP and escalate** (preserve everything, report the last known state and ask the
parent for an exact corrective assignment) on any of these conditions:
- binding drift or a proof, lock or projection mismatch;
- a baseline population other than E1;
- plan-001 harness markers changed;
- an owned path existing before creation;
- an interrupted harness or a leftover `check-docs-*.md`. Never delete it; the parent
  preserves it as in `roadmap/checks/recovery/`;
- a preservation mismatch;
- a Python minor-version change, or missing docs cache/network;
- unreadable or nonregular retained Markdown;
- any classification diagnostic on the retained tree under the planned rules, such as
  a real attachment record with a noncanonical `path`. That is a plan defect; never
  relax a rule to make G2 pass;
- a failed re-entry check (the recorded `$INV` is missing or lacks its tools), a failed
  creation-block extraction, or a second failed creation-block `mkdir`;
- any need to touch an artifact, receipt, dependency, configuration or tracked file.

Never reset, clean, stash, restore, re-baseline or overwrite. Recovery needs human
authorization and process reconciliation.

**Writer receipt** `roadmap/checks/checker-input-boundary-receipt.md`. It is
whitespace-clean, contains no Markdown links (paths go in code spans), and includes:
1. The invocation directory, role, attempt, UTC start/end and runtime facts.
2. Pre-edit HEAD, index, status, checker/harness/contract/proof SHA-256 values and the
   Slice A cross-check.
3. Baseline G0–G12 exits and log paths.
4. The binding recheck result.
5. Changed and created files with before/after SHA-256, and the location of the
   `diff -u -w` log.
6. The inventory SHA-256 and per-root counts.
7. Final G0–G14 exits and counts (63 = 19 + 44; suite N), with logs.
8. The preservation compare result.
9. The names of the post-receipt logs.
10. Limitations and open issues.
11. The handoff to independent review.

**Reviewer outputs:** `roadmap/checks/chk-review-a<N>-<UTC>/verdict.json` with the
verdict, findings, gate exits and log paths, and no Markdown. On PASS, the parent records
the ledger rows, sets the lifecycle to `verified — …` and schedules SDK review 2.

**Handoff:** after blocker 1 passes, run `/implement-markdown roadmap/plans/checker-input-boundary.md`
semantics on this host through Claude Code workflows: A, then B, then C, then D when
needed, with at most three reviews.

**Planning self-check gate (this file only).** cwd `/home/karl/repo/huron`:
- `git diff --check` exits 0.
- A trailing-whitespace and tab scan of this file is clean.
- `sha256sum roadmap/checker-input-boundary-plan.md` equals `d2f71de5…`.
- `git check-ignore -v roadmap/plans/checker-input-boundary.md` reports
  `.gitignore:40:/roadmap/`.
- `git ls-files roadmap` is empty.
- One `python roadmap/check_docs.py` run, with stdout/stderr redirected to the planning
  scratch directory, must be byte-identical to the discovery log of 2,330 lines. That
  proves this file adds no plan-structure, cross-reference, skill-path or whitespace
  diagnostic. The harness is not run in planning.

## Appendix — gate tools (verbatim; tested read-only on 2026-10-06)

Extract the tools only with the creation block above. Each body must hash to the stated
SHA-256. The tools read the repository and write only their own result or manifest
files. The single exception is `--write-inventory`, used once in Slice B step 3.

The tools are gate instruments, not the checker. An unexpected condition, such as an
unreadable path below a directory without search permission, ends a tool with a
traceback and a nonzero exit. The gate records that as a failure and the worker STOPs.
Interfaces item 1's no-traceback contract binds only `roadmap/check_docs.py`, so the
tested tool bytes stay pinned unchanged.

#### Tool file `recheck_bindings.py` SHA-256 `d186c3d4f1b968128071f99899b8d7c3caac8f93120141e6840b4ade5f72de53`

```python
"""Recheck every approved enrollment binding against the pinned proof; exit 1 on drift.

Usage: python -I -B recheck_bindings.py <repo> <result.json> [--write-inventory]
Without the flag the repository is only read and <result.json> is exclusively created.
--write-inventory (implementation slice only) first exclusively creates the v1 inventory
from the pinned proof and hashed locks, and refuses unless the projection matches the
reviewed SHA-256; it never overwrites an existing inventory.
"""

import base64
import collections
import hashlib
import io
import json
import os
import re
import stat
import sys
import tarfile
from pathlib import Path

STARLIGHT = "roadmap/prototypes/starlight"
INVENTORY = "roadmap/checks/starlight-markdown-inputs.v1.json"
PROOF = "roadmap/checks/3818200d-review-input-proof.json"
PROOF_SHA256 = "f4a580659daa5dae6fab3899e3fda48ffe3aa4a372766a974b98fc617ddc585c"
INVENTORY_SHA256 = "3536bb8e6f6bc3d7d33d63e21bbf5bdc97f7487bbf1b076c5b6eb19f7fd93b57"
INSTALL_RECEIPTS = {
    f"{STARLIGHT}/node_modules": f"{STARLIGHT}/evidence/commands/final-ci.json",
    f"{STARLIGHT}/clean-reproduction/node_modules": f"{STARLIGHT}/evidence/clean-reproduction-commands.json",
}
COMPONENT = re.compile(r"[A-Za-z0-9_@+-][A-Za-z0-9._@+-]*")


def nearest_lock_package(packages, relative):
    """Return the nearest lock key owning node_modules/<relative>, or None."""
    parts = ("node_modules", *relative.split("/"))
    for cut in range(len(parts) - 1, 0, -1):
        key = "/".join(parts[:cut])
        if key.startswith("node_modules/") and key in packages:
            return key
    return None


def build_inventory(repo):
    """Project the approved proof and hashed locks into canonical v1 inventory bytes."""
    proof_bytes = (repo / PROOF).read_bytes()
    if hashlib.sha256(proof_bytes).hexdigest() != PROOF_SHA256:
        raise SystemExit("STOP: approved proof bytes drifted")
    proof = json.loads(proof_bytes)
    summary = proof["summary"]
    install = {
        f"{STARLIGHT}/node_modules": summary["primary_receipt_sha256"],
        f"{STARLIGHT}/clean-reproduction/node_modules": summary["clean_receipt_sha256"],
    }
    vendors = []
    for vendor in proof["vendors"]:
        project = vendor["root"]
        root = f"{project}/node_modules"
        lock_path = f"{project}/package-lock.json"
        lock_bytes = (repo / lock_path).read_bytes()
        if hashlib.sha256(lock_bytes).hexdigest() != vendor["lock_sha256"]:
            raise SystemExit(f"STOP: {lock_path} drifted from the approved proof")
        packages = json.loads(lock_bytes)["packages"]
        files = []
        for relative, digest in sorted(vendor["files"].items()):
            owner = nearest_lock_package(packages, relative)
            if owner is None:
                raise SystemExit(f"STOP: no owning lock package for {root}/{relative}")
            files.append({"path": relative, "sha256": digest, "package": owner})
        vendors.append({
            "root": root,
            "lock": {"path": lock_path, "sha256": vendor["lock_sha256"]},
            "install": {"path": INSTALL_RECEIPTS[root], "sha256": install[root]},
            "files": files,
        })
    reports = []
    for report in proof["reports"]:
        root = f"{STARLIGHT}/evidence/{report['name']}"
        reports.append({
            "root": root,
            "receipt": {"path": f"{root}.json", "sha256": report["sha256"]},
            "files": [{"path": p, "sha256": d} for p, d in sorted(report["files"].items())],
        })
    document = {
        "version": 1,
        "vendors": sorted(vendors, key=lambda item: item["root"]),
        "reports": sorted(reports, key=lambda item: item["root"]),
    }
    return (json.dumps(document, indent=1, ensure_ascii=True) + "\n").encode("ascii")


def parts_of(value, absolute=False):
    """Return canonical path components (relative, or absolute when asked), else None."""
    if not isinstance(value, str) or (absolute and not value.startswith("/")):
        return None
    parts = (value[1:] if absolute else value).split("/")
    return tuple(parts) if all(COMPONENT.fullmatch(part) for part in parts) else None


def read_regular(repo, relative):
    """Return (bytes, None) for a regular file reached without symlinks, else (None, reason)."""
    current = repo
    for index, part in enumerate(relative.split("/")):
        current = current / part
        try:
            info = os.lstat(current)
        except (FileNotFoundError, NotADirectoryError):
            return None, "missing"
        if stat.S_ISLNK(info.st_mode):
            return None, "symlink component " + "/".join(relative.split("/")[: index + 1])
    if not stat.S_ISREG(info.st_mode):
        return None, "not a regular file"
    try:
        with open(os.open(current, os.O_RDONLY | os.O_NOFOLLOW), "rb") as handle:
            return handle.read(), None
    except PermissionError:
        return None, "unreadable"


def attachments(suites):
    """Yield every attachment record of a Playwright JSON report suite tree."""
    for suite in suites:
        for spec in suite.get("specs", []):
            for test in spec.get("tests", []):
                for result in test.get("results", []):
                    yield from result.get("attachments", [])
        yield from attachments(suite.get("suites", []))


def markdown_under(repo, root):
    """Return Markdown paths below root (relative to it), never following directory links."""
    found = set()
    for directory, _, names in os.walk(repo / root, followlinks=False):
        for name in names:
            if name.endswith(".md"):
                found.add(os.path.relpath(os.path.join(directory, name), repo / root).replace(os.sep, "/"))
    return found


def main():
    write = "--write-inventory" in sys.argv[1:]
    repo, out = (Path(a) for a in sys.argv[1:] if a != "--write-inventory")
    repo = repo.resolve()
    if out.resolve().is_relative_to(repo / "roadmap" / "prototypes"):
        raise SystemExit("result must not be written inside retained artifacts")
    errors = []
    data = build_inventory(repo)
    digest = hashlib.sha256(data).hexdigest()
    if digest != INVENTORY_SHA256:
        errors.append(f"projected inventory sha256 {digest} != {INVENTORY_SHA256}")
        if write:
            raise SystemExit("STOP: projection differs from the reviewed SHA-256; inventory not written")
    if write:
        try:
            with open(repo / INVENTORY, "xb") as handle:
                handle.write(data)
        except FileExistsError:
            raise SystemExit(f"STOP: {INVENTORY} already exists; it is never overwritten") from None
    live, problem = read_regular(repo, INVENTORY)
    inventory_state = "absent" if problem == "missing" else ("equal" if live == data else f"DIFFERENT ({problem})")
    if inventory_state.startswith("DIFFERENT"):
        errors.append(f"{INVENTORY}: live bytes differ from projection")
    document = json.loads(data)
    counts = collections.Counter()
    origins = set()
    for report in document["reports"]:
        receipt, problem = read_regular(repo, report["receipt"]["path"])
        if problem or hashlib.sha256(receipt).hexdigest() != report["receipt"]["sha256"]:
            errors.append(f"{report['receipt']['path']}: {problem or 'sha256 drift'}")
            continue
        parsed = json.loads(receipt)
        config = parsed["config"]
        config_file = parts_of(config.get("configFile"), absolute=True)
        relative_root = parts_of(report["root"])[3:]
        if config_file is None or config_file[-1] != "playwright.config.ts":
            errors.append(f"{report['receipt']['path']}: config file")
            continue
        origin = config_file[:-1]
        output = origin + relative_root
        projects = config.get("projects") or []
        if (parts_of(config.get("rootDir"), absolute=True) != origin + ("e2e",) or not projects
                or any(parts_of(p.get("outputDir"), absolute=True) != output for p in projects)):
            errors.append(f"{report['receipt']['path']}: config agreement")
            continue
        origins.add(origin)
        records = list(attachments(parsed["suites"]))
        seen = collections.Counter(parts_of(r.get("path"), absolute=True) for r in records)
        eligible = set()
        for record in records:
            if record.get("name") != "error-context":
                continue
            parts = parts_of(record.get("path"), absolute=True)
            if (record.get("contentType") != "text/markdown" or parts is None or seen[parts] != 1
                    or parts[: len(output)] != output or len(parts) != len(output) + 2
                    or parts[-1] != "error-context.md"):
                errors.append(f"{report['receipt']['path']}: attachment {record.get('path')!r}")
                continue
            eligible.add("/".join(parts[len(output):]))
        enrolled = {item["path"] for item in report["files"]}
        if eligible != enrolled or markdown_under(repo, report["root"]) != enrolled:
            errors.append(f"{report['root']}: graph/disk/enrollment sets differ")
        for item in report["files"]:
            path = f"{report['root']}/{item['path']}"
            body, problem = read_regular(repo, path)
            if problem or hashlib.sha256(body).hexdigest() != item["sha256"]:
                errors.append(f"{path}: {problem or 'sha256 drift'}")
            else:
                counts["report_files"] += 1
    if len(origins) != 1:
        errors.append(f"report origins: {sorted(origins)}")
    origin = next(iter(origins)) if len(origins) == 1 else None
    trees = {}
    for vendor in document["vendors"]:
        project = vendor["root"].rsplit("/", 1)[0]
        packages = json.loads((repo / vendor["lock"]["path"]).read_bytes())["packages"]
        receipt, problem = read_regular(repo, vendor["install"]["path"])
        if problem or hashlib.sha256(receipt).hexdigest() != vendor["install"]["sha256"]:
            errors.append(f"{vendor['install']['path']}: {problem or 'sha256 drift'}")
        else:
            parsed = json.loads(receipt)
            entries = [parsed] if isinstance(parsed, dict) else parsed
            installs = [e for e in entries if e.get("command") == ["npm", "ci"]]
            expected_cwd = None if origin is None else origin + parts_of(project)[3:]
            if not (len(installs) == 1 and type(installs[0].get("exit")) is int and installs[0]["exit"] == 0
                    and installs[0].get("signal") is None and installs[0].get("error") is None
                    and installs[0].get("inBandFailure", False) is False
                    and parts_of(installs[0].get("cwd"), absolute=True) == expected_cwd):
                errors.append(f"{vendor['install']['path']}: not an ordinary successful npm ci at origin")
        enrolled = {item["path"] for item in vendor["files"]}
        if markdown_under(repo, vendor["root"]) != enrolled:
            errors.append(f"{vendor['root']}: disk/enrollment sets differ")
        checked = {}
        current = {}
        for item in vendor["files"]:
            path = f"{vendor['root']}/{item['path']}"
            body, problem = read_regular(repo, path)
            if problem or hashlib.sha256(body).hexdigest() != item["sha256"]:
                errors.append(f"{path}: {problem or 'sha256 drift'}")
                continue
            current[item["path"]] = item["sha256"]
            package = item["package"]
            file_parts = ("node_modules", *item["path"].split("/"))
            between = ["/".join(file_parts[:cut]) for cut in range(len(package.split("/")) + 1, len(file_parts))]
            if any(key in packages or os.path.lexists(repo / project / key / "package.json") for key in between):
                errors.append(f"{path}: nearer package than {package}")
            if package not in checked:
                meta, problem = read_regular(repo, f"{project}/{package}/package.json")
                entry = packages.get(package, {})
                name = entry.get("name") or package.rsplit("node_modules/", 1)[1]
                metadata = json.loads(meta) if problem is None else {}
                checked[package] = (problem is None and metadata.get("name") == name
                                    and metadata.get("version") == entry.get("version"))
                if not checked[package]:
                    errors.append(f"{project}/{package}/package.json: {problem or 'name/version differs from lock'}")
            counts["vendor_files"] += 1
        counts["packages"] += sum(checked.values())
        trees[vendor["root"]] = current
    identical = len(trees) == 2 and len({json.dumps(t, sort_keys=True) for t in trees.values()}) == 1
    if not identical:
        errors.append("vendor trees differ")
    proof = json.loads((repo / PROOF).read_bytes())
    primary = next(v for v in document["vendors"] if v["root"] == f"{STARLIGHT}/node_modules")
    inside = collections.defaultdict(list)
    for item in primary["files"]:
        inside[item["package"]].append(("/".join(item["path"].split("/")[len(item["package"].split("/")) - 1:]), item["sha256"]))
    lock = json.loads((repo / STARLIGHT / "package-lock.json").read_bytes())["packages"]
    for record in proof["archives"]:
        algorithm, encoded = record["integrity"].split("-", 1)
        hexdigest = base64.b64decode(encoded).hex()
        cache = f"{STARLIGHT}/.npm-cache/_cacache/content-v2/{algorithm}/{hexdigest[:2]}/{hexdigest[2:4]}/{hexdigest[4:]}"
        body, problem = read_regular(repo, cache)
        good = (problem is None and hashlib.new(algorithm, body).hexdigest() == hexdigest
                and hashlib.sha256(body).hexdigest() == record["archive_sha256"]
                and lock.get(record["package"], {}).get("integrity") == record["integrity"])
        matched = 0
        if good:
            with tarfile.open(fileobj=io.BytesIO(body), mode="r:*") as archive:
                members = {m.name.removeprefix("./"): m for m in archive.getmembers()}
                for name, sha in inside.get(record["package"], []):
                    member = members.get(f"{record['prefix']}/{name}")
                    if member is not None and member.isreg() and hashlib.sha256(archive.extractfile(member).read()).hexdigest() == sha:
                        matched += 1
        if not good or matched != record["matched"]:
            errors.append(f"archive {record['package']}: drift")
        else:
            counts["archives"] += 1
            counts["archive_members"] += matched
    result = {"proof_sha256": PROOF_SHA256, "inventory_projection_sha256": digest, "inventory_file": inventory_state,
              "origin": "/" + "/".join(origin) if origin else None, "counts": dict(counts),
              "vendor_trees_identical": identical, "errors": errors}
    with open(out, "x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=1, sort_keys=True)
        handle.write("\n")
    print(json.dumps({k: (v if k != "errors" else len(v)) for k, v in result.items()}, sort_keys=True))
    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    main()
```

#### Tool file `manifest.py` SHA-256 `ea782d556778c3736380c45d972a7074cdd89f8fee9bedc600045c1327a0d10d`

```python
"""Capture or compare preservation manifests of Git-visible paths and the roadmap tree.

Usage:
  python -I -B manifest.py capture <repo> <out.json> [--exclude REL ...]
  python -I -B manifest.py compare <before.json> <after.json> <result.json> [--changed REL ...] [--added REL ...]
Capture never follows directory links and never writes inside the repository except
the exclusive-create output file. Compare exits 1 on any removal, on any change or
addition not declared with --changed/--added, and on any HEAD/index/status/visible drift.
"""

import hashlib
import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path


def git(repo, *args):
    """Run a read-only Git command without optional index locks."""
    return subprocess.check_output(["git", "--no-optional-locks", *args], cwd=repo)


def entry(path):
    """Describe one path without following a final symlink."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return {"type": "missing"}
    mode = stat.S_IMODE(info.st_mode)
    if stat.S_ISLNK(info.st_mode):
        return {"type": "link", "target": os.readlink(path)}
    if stat.S_ISDIR(info.st_mode):
        return {"type": "dir", "mode": mode}
    if stat.S_ISREG(info.st_mode):
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
        return {"type": "file", "mode": mode, "size": info.st_size, "sha256": digest.hexdigest()}
    return {"type": "other", "mode": mode}


def capture(repo, out, excludes):
    repo = repo.resolve()
    excluded = [tuple(Path(e).parts) for e in excludes]

    def kept(relative):
        parts = Path(relative).parts
        return not any(parts[: len(e)] == e for e in excluded)

    started = time.time()
    visible = sorted(set(filter(None, git(repo, "ls-files", "-z", "--cached", "--others",
                                          "--exclude-standard").decode().split("\0"))))
    entries = {name: entry(repo / name) for name in visible if kept(name)}
    for directory, dirnames, filenames in os.walk(repo / "roadmap", followlinks=False):
        for name in sorted(dirnames + filenames):
            relative = os.path.relpath(os.path.join(directory, name), repo).replace(os.sep, "/")
            if kept(relative):
                entries[relative] = entry(repo / relative)
        dirnames[:] = [d for d in dirnames if kept(os.path.relpath(os.path.join(directory, d), repo))]
    index = repo / git(repo, "rev-parse", "--git-path", "index").decode().strip()
    status = git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    record = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "head": git(repo, "rev-parse", "HEAD").decode().strip(),
        "index_sha256": hashlib.sha256(index.read_bytes()).hexdigest(),
        "status_sha256": hashlib.sha256(status).hexdigest(),
        "status_entries": len([s for s in status.split(b"\0") if s]),
        "visible": visible,
        "excluded": sorted(excludes),
        "entries": dict(sorted(entries.items())),
        "seconds": round(time.time() - started, 3),
    }
    with open(out, "x", encoding="utf-8") as handle:
        json.dump(record, handle, indent=0, sort_keys=True)
        handle.write("\n")
    kinds = {}
    for value in entries.values():
        kinds[value["type"]] = kinds.get(value["type"], 0) + 1
    print(json.dumps({"entries": len(entries), "kinds": kinds, "visible": len(visible),
                      "head": record["head"], "index_sha256": record["index_sha256"],
                      "status_sha256": record["status_sha256"], "seconds": record["seconds"]}))


def compare(before_path, after_path, out, may_change, may_add):
    before = json.loads(Path(before_path).read_text())
    after = json.loads(Path(after_path).read_text())
    changed = sorted(k for k in before["entries"].keys() & after["entries"].keys()
                     if before["entries"][k] != after["entries"][k])
    added = sorted(after["entries"].keys() - before["entries"].keys())
    removed = sorted(before["entries"].keys() - after["entries"].keys())
    scalars = {k: before[k] == after[k] for k in ("head", "index_sha256", "status_sha256", "visible", "excluded")}
    unexpected = ([p for p in changed if p not in may_change] + [p for p in added if p not in may_add]
                  + removed)
    result = {"changed": changed, "added": added, "removed": removed, "equal": scalars,
              "declared_changed": sorted(may_change), "declared_added": sorted(may_add),
              "unexpected": unexpected,
              "entries_before": len(before["entries"]), "entries_after": len(after["entries"])}
    with open(out, "x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=1, sort_keys=True)
        handle.write("\n")
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if not unexpected and all(scalars.values()) else 1)


def main():
    command, *args = sys.argv[1:]
    flags = {"--exclude": [], "--changed": [], "--added": []}
    positional = []
    while args:
        item = args.pop(0)
        if item in flags:
            flags[item].append(args.pop(0))
        else:
            positional.append(item)
    if command == "capture":
        repo, out = positional
        capture(Path(repo), out, flags["--exclude"])
    elif command == "compare":
        before, after, out = positional
        compare(before, after, out, set(flags["--changed"]), set(flags["--added"]))
    else:
        raise SystemExit(f"unknown command {command}")


main()
```

#### Tool file `text_scan.py` SHA-256 `9ca51bbd31ed222c83d699e7cefbd3b1b227abac22156e0f8f2169c506baef77`

```python
"""Scan new or changed authored text without writing; exit 1 on any finding.

Usage: python -I -B text_scan.py <file> [<file> ...]
Findings: undecodable UTF-8, carriage returns, tabs, trailing whitespace, missing final
newline and (Markdown only) any Markdown or HTML link target.
"""

import re
import sys
from pathlib import Path

LINK = re.compile(r"!?\[[^\]\n]*\]\([^)\n]*\)|^\[[^\]]+\]:\s*\S+|(?:href|src)=[\"']", re.M)
findings = []
for name in sys.argv[1:]:
    data = Path(name).read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        findings.append(f"{name}: not UTF-8")
        continue
    if "\r" in text:
        findings.append(f"{name}: carriage return")
    if not text.endswith("\n"):
        findings.append(f"{name}: missing final newline")
    for number, line in enumerate(text.split("\n"), 1):
        if "\t" in line:
            findings.append(f"{name}:{number}: tab")
        if line.rstrip() != line:
            findings.append(f"{name}:{number}: trailing whitespace")
    if name.endswith(".md"):
        for match in LINK.finditer(text):
            findings.append(f"{name}:{text.count(chr(10), 0, match.start()) + 1}: link target {match.group()!r}")
print("\n".join(findings) if findings else f"OK: {len(sys.argv) - 1} files clean")
raise SystemExit(1 if findings else 0)
```
