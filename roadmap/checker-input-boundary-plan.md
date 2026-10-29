# Local checker authored-input boundary correction

Status: blocked — review1 FAIL; planning fix awaits maximum review2 and exact enrollment authorization.

## Context and outcome

This is a bounded prerequisite-tooling plan, not production implementation authority.
The user permits planning, checking, isolated experiments and prerequisite corrections,
but requires a pause before production application, migration, deployment or live docs
implementation. Fresh deployment and explicit stale-base conflict/no silent merge are
approved product planning policies; neither authorizes deletion. The checker contract
below is still proposed. No production policy is changed by it.

Current `roadmap/check_docs.py` line 49 unions every `roadmap/**/*.md` into its
whitespace inputs. Git ignore rules do not constrain that glob. Roadmap Markdown is
not universally link-checked: preserve the existing separate live-doc link scope,
tracked ignored-plan dependency prohibition, untracked text scan, phase structure,
status, skills and cross-references. Do not quietly invent universal roadmap links.

Independent SDK review 1 (`ses_ef11f098cffeC9UE2g5LgejBOW`, maximum) reports two
fresh green packaging runs, strict docs green, unchanged source/index/553 Git-visible
paths, and checker exit 1 with exactly **2,330 trailing-whitespace lines: 2,070 vendor,
260 Playwright error contexts, zero SDK**. Full SDK qualification remains FAIL solely
on that required gate; packaging success is not full qualification. This planning
turn did not rerun root checker/docs/regressions or SDK experiments.

`checks/test_check_docs.py:149–151` requires an exit-0 whole-tree baseline before its
63 cases. Keep that prerequisite and all original exact exit/stdout/stderr assertions:
19 accepted + 44 rejected, including empty status's whitespace diagnostic. The current
artifact-triggered failure blocks the matrix before case 1; it is a known owned defect,
not permission to accept a bad baseline. Earlier 63-case PASS predates these artifacts.

## Prototype evidence

No new experiment is necessary to establish the discovery defect. Read-only inspection
of checker/harness, Starlight evidence, `scripts/summarize.mjs`, `scripts/e2e.mjs`,
`playwright.config.ts`, `scripts/package-proof.mjs`, SDK evidence and
`check_artifacts.py` supplies the tooling probe. These scripts were not executed.

Read-only `rg --files --hidden --no-ignore -g '*.md' roadmap` enumeration counted
4,554 Markdown paths before this new plan. Starlight has 4,371; SDK has 151 (three
top-level narratives, 148 under runs); other subjects total 32. Counts are discovery
evidence, not hard-coded global acceptance thresholds. Symlink following is not
qualified by this enumeration. Review1 corrected its omission of four Markdown
file links: Starlight has 4,375 paths, including 3,048 in `.test-work/`; the 4,559
whole-roadmap count then included this plan. These are historical counts, not a
global ratchet. Do not traverse directory links; retain contained Markdown file-link
whitespace coverage under invariant 3. The table below records regular files only.

Exact Starlight population, relative to `roadmap/prototypes/starlight/`:

| Location | Markdown count | Proposed treatment |
| --- | ---: | --- |
| `node_modules/` | 570 | Enroll exact verified installed files, never directory exclusion |
| `clean-reproduction/node_modules/` | 570 | Same rule, independent install identities |
| `evidence/` | 46 | Only 44 exact report attachments eligible; two narratives stay authored |
| `evidence.md` | 1 | Authored |
| `fixtures/` | 14 | Authored/copied; never exempt |
| `src/` | 14 | Retain existing whitespace checks, even generated content |
| `.work/` | 70 | Retain existing checks |
| `.test-work/` | 3,044 | Retain existing checks, including negative-test fixtures |
| other `clean-reproduction/` paths | 42 | Retain existing checks |

The seven exact report roots are `evidence/e2e-root` (3 attachments),
`evidence/e2e-root-wide-corrected` (1), `evidence/e2e-root-full` (12),
`evidence/e2e-root-qualified-matrix` (8), `evidence/e2e-root-full-corrected` (8),
`evidence/e2e-root-final` (6), and `evidence/e2e-subbase-final` (6).
Each has a sibling `.json` report. Exact files are its
`suites → specs → tests → results → attachments` records named `error-context`,
with `contentType: text/markdown`, terminating in `error-context.md`, inside that
specific output directory. Initial enrollment must verify equality with all 44
on-disk paths, not just select records with whitespace findings. No failed report
or historical receipt may be removed, normalized or rewritten.

The two vendor trees each contain 570 Markdown files, not 1,035 files: the reported
2,070 count is offending lines, not file count. Enroll all eligible Markdown in those
installs, not only failing lines. Review1 verified both 570-file sets byte-identical,
431 owning packages matching the lock, and all 570 members matching retained archives
whose 431 SHA-512 integrities match the lock. Its first archive probe assumed a
`package/` prefix; corrected inspection accounted for 13 `@types` archive prefixes,
without changing artifacts. This supports non-hostile local classification, NOT
authenticated registry origin. Exact enrollment still requires parent authorization.

Read-only review1 evidence is under `roadmap/checks/`:
`b5243808-review1-input-inspection.json`,
`b5243808-review1-cached-archive-inspection.json`,
`b5243808-review1-cached-archive-corrected-inspection.json`,
`b5243808-review1-preservation.json`, `b5243808-review1-gate-checker.json`,
`b5243808-review1-gate-original63.json` and
`b5243808-review1-text-and-matrix-inspection.json`, with before/after records.
They establish all seven attachment sets (44 total), 47 matching authored inventory
hashes, 151 SDK Markdown paths still checked, 76,912 preserved entries and no residual
processes. Review1 reproduced the same 2,330 findings and pre-case-1 harness failure;
strict docs passed. None of those historical failures is rewritten by this prose fix.

Starlight's 47-entry `evidence/owned-files.json` identifies authored/copied inputs,
but misses future narratives and is not a fail-closed discovery boundary.
`summarize.mjs:11–13` classifies error strings by substrings; that proves neither
file identity nor origin. SDK RECORD, source/run/driver hashes and retained complete
inventories are useful packaging evidence, not an authorization to exempt SDK text.
All SDK Markdown remains checked; no SDK classifier or producer mutation is proposed.
Other producers have not been provenance-qualified; they remain checked by default.

## Exact scope and ownership

This planning dispatch owns ONLY this new ignored file. Initial status was 51 dirty
tracked paths and four untracked paths, all pre-existing/unknown ownership. Initial
`git diff --check` exited 0; `git ls-files roadmap` was empty. Preserve all of it.

Proposed future exclusive maximum code slice allowlist (not permission in this turn):

- Change `roadmap/check_docs.py`: whitespace input discovery at line 49; add bounded
  no-follow discovery and explicit inventory validation helpers. Preserve other loops,
  diagnostics and success prefix. No command mode that bypasses existing checks.
- Keep `roadmap/checks/test_check_docs.py` original 63 cases/assertions unchanged.
  Only append invocation of new discovery tests after successful existing matrix if
  needed; prefer leave file byte-identical and run new suite separately.
- Add `roadmap/checks/test_check_docs_discovery.py`: disposable filesystem/CLI cases.
- Add `roadmap/checks/starlight-markdown-inputs.v1.json`: exact reviewed enrollment.
- Add `roadmap/checks/checker-input-boundary-receipt.md`: command, enrollment and
  preservation evidence, no replacement of old receipts.

No deletions, moves, compatibility shims, producer edits, dependency changes, root
config edits or tracked changes. Old canonical/legacy task heading support is the
existing explicit historical compatibility exception, untouched here. All Starlight
and SDK artifacts are read-only. Tests may create and remove only their own uniquely
created fixtures; unknown pre-existing files block rather than invite cleanup.

Parent must reconcile new code/output ownership before dispatch. Use code activity,
maximum profile and exclusive `*:write` with the file allowlist above; actual code
excludes every worker/check. Final review is terminally after writer, maximum,
verification/review, with read claims on code/source/prototypes/plans and write claims
for unique test outputs, `build:docs` (root `site/`), `cache:uv`
(`/tmp/opencode/huron-effort-uv-cache`) and `env:python` (root `.venv`). Parent records
the exact resource dictionary, including new fixture/output paths. Claims coordinate,
not sandbox. No services, browser, npm install, SDK fresh runs or agent-config changes
are needed. No runtime restart is needed for this plain Python checker; no plugin is
changed. Parent owns uncertain-session/process reconciliation; no manual resume/replay.

## Interfaces and implementation examples

Choose **default authored discovery plus exact reviewed identities**, not runtime
relocation. Moving old artifacts would invalidate absolute report paths, historical
receipts and preservation evidence, and requires broader producer/layout authority.
Future explicit runtime separation may be separately planned, but does not solve
today's retained artifacts without migration. Reject blanket `node_modules`, `evidence`,
`runs`, cache or prototype directory ignores, authored allowlists, filtered diagnostics,
automatic hash regeneration and a general artifact registry/framework.

Use one small versioned JSON document, no new dependency or persistence service.
Illustrative shape (hash tokens below must become real 64-lowercase-hex values;
the example is not valid enrollment):

```json
{
  "version": 1,
  "vendors": [{
    "root": "roadmap/prototypes/starlight/node_modules",
    "lock": {"path": "roadmap/prototypes/starlight/package-lock.json", "sha256": "LOCK_SHA256"},
    "install": {"path": "roadmap/prototypes/starlight/evidence/commands/final-ci.json", "sha256": "901b574d9ace13c0562653de31082e4e39c2cc3cd8e4e461081a6b9768ce5590"},
    "files": [{"path": "PACKAGE/README.md", "sha256": "FILE_SHA256", "package": "node_modules/PACKAGE"}]
  }],
  "reports": [{
    "root": "roadmap/prototypes/starlight/evidence/e2e-root-final",
    "receipt": {"path": "roadmap/prototypes/starlight/evidence/e2e-root-final.json", "sha256": "REPORT_SHA256"},
    "files": [{"path": "EXACT_TEST_OUTPUT/error-context.md", "sha256": "FILE_SHA256"}]
  }]
}
```

The primary receipt above is resolved: ordinary `["npm", "ci"]`, correct Starlight
cwd, exit 0, null signal/error, Node 22.23.2, started `2026-10-06T01:33:01.659Z`.
Clean reproduction uses the existing `evidence/clean-reproduction-commands.json`;
validate its successful ordinary npm-ci entry and exact clean cwd. Hash each complete
receipt, not a normalized projection. Other example hash tokens remain illustrative;
do not create enrollment JSON in this planning turn or accept `--ignore-scripts` as
successful installation. Lock SHA-256 reported by inspected evidence is
`5857165d1169f134499883b793799a084fd9b64ca6f173bef48201943e91fd70`.

Suggested pure helper boundaries, not a framework or existing implementation:

```python
def discover_roadmap_markdown(root: Path) -> tuple[list[Path], list[str]]: ...
def verified_starlight_markdown(root: Path, inventory: Path) -> tuple[set[Path], list[str]]: ...
# Keep all other input populations unchanged.
# authored = discovered_markdown - verified_exact_files
# errors.extend(discovery_errors + identity_errors)
# Never remove a file from authored unless every identity/provenance check succeeds.
```

CLI remains `python roadmap/check_docs.py`: read-only, deterministic diagnostics,
exit 1 on any input/provenance/ordinary validation error; exit 0 and existing `PASS:`
prefix only on complete success. No `--rebaseline`, optional validation or fetch mode.
Helpers can be imported without executing the CLI by narrowly adding `main()` if
needed; do not refactor unrelated validation rules. New tests exercise public CLI
in disposable repository copies plus small real-filesystem helper fixtures.

Representation and invariants:

1. Strict schema/version, unknown keys rejected; arrays retain duplicate visibility.
   Reject duplicate JSON keys, duplicate paths, overlapping roots and duplicate
   classification across sections. Root paths are repo-relative canonical POSIX,
   file paths root-relative; reject absolute, empty, `.`/`..`, backslash, NUL, glob,
   encoded escape aliases and noncanonical spellings. Validate before resolving.
2. This correction covers ONLY the retained snapshot: the two exact installed roots
   and seven exact report roots listed above, not future Starlight producers/runs.
   Names alone confer no exception. Eligible report
   files have exactly one test-output directory plus `error-context.md`, and must
   appear exactly once in the hashed report attachment graph. Prefix binding is
   derived from that same hashed report, not an omitted inventory field: parse
   `config.configFile` as canonical absolute POSIX and require basename
   `playwright.config.ts`; its parent is origin O. Require `config.rootDir == O/e2e`
   and every `config.projects[].outputDir == O/R`, where R is the enrolled root
   relative to `roadmap/prototypes/starlight` (e.g. `evidence/e2e-root-final`).
   Require each eligible absolute attachment to be exactly `O/R/P`, where P is
   its enrolled two-component relative path; reject duplicates across the entire
   attachment graph. Compare path components, not string prefixes or suffix search.
   Reject noncanonical/traversal/encoded aliases before mapping. Map P to the current
   checkout's enrolled root only after all fields agree. Do not resolve O on the
   current host: unchanged reports must work in a relocated checkout without the
   old checkout existing. A foreign attachment prefix or inconsistent output root
   fails; there is no hardcoded `/home/karl` binding. No authored fixture/evidence
   narrative, plan, source, recovery or SDK path can be classified through these rules.
3. Separate discovery from classification security. Walk real directories only;
   never descend through directory symlinks and do not emit blanket errors for
   unrelated runtime links. Preserve all 194 SDK directory links (62 venv `lib64`,
   132 uv-cache) and four retained Starlight negative-test directory links without
   traversal, deletion or classification. Non-Markdown executable links stay outside
   this Markdown boundary. For ordinary discovered `.md` file links, resolve strictly
   to a readable regular file contained in the current roadmap root, then whitespace
   check through the original lexical path (never deduplicate away its diagnostic).
   Broken/cyclic/nonregular/unreadable or escaping Markdown file links fail clearly;
   do not silently omit them. The four existing
   `.test-work/content-*/fixtures/docs/history.md` links remain checked and retained.
   This is not a new global filesystem
   security policy. Independently reject ANY symlink component at inventory, lock,
   receipt, package-metadata and classified-file boundaries, with strict containment
   and missing/nonregular/unreadable checks. A link cannot acquire an exemption even
   if it points at an enrolled file. Inventory cannot exempt non-Markdown files.
4. For each vendor file validate hash, nearest owning installed package metadata,
   exact package key/version against the hashed lock, and reviewed install receipt.
   For each report validate report hash, attachment membership and exact byte hash.
   Require registered root's discovered Markdown set equals its enrolled file set.
   Unknown Markdown in such roots produces an explicit unknown-input error even if
   whitespace-clean and still receives normal whitespace checks. Changed enrolled
   bytes produce integrity errors, not a fallback exemption. Missing inputs fail.
5. Outside enrolled roots, every new Markdown path is authored by default without
   registration. Thus new narratives anywhere, including new evidence directories,
   receive whitespace checks. New author text inside a registered artifact root
   fails unknown-input classification; do not enroll it merely to obtain green.
6. Hashes prove equality to a reviewed local snapshot, not authorship, registry
   authenticity, correct generator behavior or semantic truth. A lock's tarball
   integrity is not an unpacked-file hash. Initial reviewer must inspect file/package
   mapping and independently compare the two existing install trees; any mismatch
   needs explanation, not rebaseline. Reports plus generator configuration support
   retrospective classification but are not signed origin proofs. If stronger origin
   evidence is required or available receipts cannot support classification, stop for
   parent-approved isolated package/archive verification; do not install during this
   correction or pretend hashes alone settle provenance. No hostile-writer guarantee.
7. Version 1 is a finite retained-snapshot correction, not a reusable Starlight
   qualification protocol or automatically generated baseline. Checker review reruns
   the unchanged checker/matrix/docs gate plus new discovery tests against retained
   artifacts; it must NOT require fresh Starlight installs/builds/browser runs.
   SDK review separately reruns its unchanged full applicable gate, including fresh
   SDK runs and the corrected root checker; SDK text needs no enrollment exception.
   Starlight final qualification is separately BLOCKED on a reviewed fresh-run/output
   protocol: `scripts/reproduce.mjs` refuses existing `clean-reproduction`, and a new
   install root is not one of these two enrolled roots. Do not solve that by deleting
   old evidence, inventing a third root here or a repeated code/review enrollment loop.
   New unenrolled artifacts remain ordinary checked text; no future gate is waived.
8. Fresh tracked checkout has neither this ignored checker nor local plans; tracked
   CI/docs must not require them. With local checker/plans restored but no Starlight
   subject, inventory absence is allowed only when that subject is entirely absent;
   authored-only discovery still runs all existing phase requirements. If the subject
   exists, missing inventory is an explicit failure, even if its artifacts happen to
   have clean whitespace. An inventory referencing missing roots/receipts fails;
   no optional missing entries or silent skipping. Copying local tooling without its
   required plans still fails existing requirements, not a false fresh-checkout PASS.

## Per-subject serial task slices

1. **Plan review/enrollment readiness, pending:** maximum independent review2 checks
   the F1–F3 revisions and resolved local proof receipts with parent.
   The code baseline worker inventories exact 1,140 vendor + 44 report paths/hashes
   read-only and records equality/provenance limitations. Missing new inventory is
   expected absent infrastructure to create, not baseline PASS. Parent approves exact
   enrollment identities before they can become exceptions. No layout migration.
2. **Baseline then correction, pending:** newly dispatched exclusive maximum writer
   captures preservation and reruns complete baseline before editing. Known checker
   exit 1 and matrix pre-case failure reproduce the defect; unrelated failures stop
   for reconciliation. Add the bounded inventory, discovery and tests only; no edits
   to artifact bytes or original63 expectations. Run full final gate with artifacts
   retained and receipt all results.
3. **Independent qualification, pending:** after writer terminal, maximum reviewer
   independently checks enrollment and original63 preservation, then reruns all gates.
   Maximum three reviews, serial fix/review for findings. SDK review2 remains a separate
   parent dispatch rerunning its own full applicable gate; this tooling PASS cannot
    retroactively convert SDK review1 FAIL or resolve Starlight search/table findings.

Separate future Starlight prerequisite (NOT a task or acceptance gate in this slice):
parent commissions a bounded protocol plan before Starlight final review. It must
reserve unique fresh install/report/output locations before invocation, preserve all
old artifacts and all authored Markdown coverage, and define package-lock/archive,
receipt, prefix and attachment provenance validation for review-owned normal outputs.
After independent protocol approval and any separately authorized exclusive code
change, the Starlight reviewer can produce and validate those fresh outputs under
declared output claims without modifying checker code/enrollment for each review.
Define a finite writer-terminal → reviewer-full-gate sequence and failure retention;
do not build a general registry or approve an unbounded producer policy here.

## Skills

This plan and its review require `.agents/skills/design-plan/SKILL.md` and
`.agents/skills/implementation-plan/SKILL.md`, read in full, plus orchestration,
verification and design/phase/assignment templates. Future execution additionally
reads `.agents/skills/implement-markdown/SKILL.md` and its command. Read testing and
docstring conventions. No Core/domain, API, database, Svelte, Tailwind, browser or
OpenCode-config implementation is in scope; their specialized gates do not apply.

## Acceptance and complete applicable gates

Reuse existing real-plan fixture conventions, `fingerprint`, `preservation_state`
and exact CLI outcome style; do not replace the original matrix with helper tests.
New deterministic filesystem/CLI cases must prove:

- All 63 original names, inputs, expectations, baseline prerequisite and preservation
  checks remain intact and pass (19/44). The empty-status whitespace error remains.
- Valid exact vendor/report identities with trailing whitespace pass discovery;
  clean/dirty new authored Markdown outside enrollment is checked without registration.
- Dirty fixtures, copied content, top-level/evidence narratives, root plans and SDK
  narratives still fail; attempts to classify those paths are rejected even with hashes.
- Unknown clean and dirty Markdown under either vendor or enrolled report root fails;
  altered enrolled bytes, altered lock/receipt, missing file/package metadata/receipt/
  root, wrong lock package/version, report not listing attachment and wrong MIME fail.
- Unregistered new report is not exempt; dirty content fails. Future Starlight output
  support requires the separate protocol, not an enrollment loop in this acceptance.
  A clean new narrative is still checked, not required to be globally registered.
- Duplicate JSON key/path, overlapping root, unknown version/key, invalid hash, absolute/
  traversal/encoded escape, symlink classified file/directory/ancestor/receipt/lock/
  inventory/package metadata and missing inventory
  with present subject all fail clearly, without writes or uncaught traceback.
- Real retained-link regressions: all 194 SDK and four negative-test directory links
  produce no blanket errors and are never traversed; all four Markdown file links
  are whitespace inputs. In disposable matching fixtures, dirty target bytes must
  report the link's lexical path; contained clean targets pass, broken/escaping/cyclic
  Markdown links fail. Do not mutate retained fixtures to test these cases.
- Relocate a disposable checkout while retaining report bytes and original absolute
  origins: correct mapping passes without accessing the old origin. Foreign prefix,
  inconsistent config/rootDir/project outputDir, traversal, duplicate attachment and
  arbitrary matching suffix all fail. These are fixture tests, not fresh Starlight runs.
- Inventory absent with wholly absent Starlight is valid discovery (other checks still
  run); inventory present with missing referenced artifacts fails. No network/install.
- Repeated checker execution leaves inventory, source, plans, reports and artifacts
  byte-identical. Sorting and exact diagnostics are deterministic. Preserve failed test
  fixtures only when ownership is uncertain; no automatic restore/reset on mismatch.

Commands below all use cwd `/home/karl/repo/huron`. Future baseline and independent
final review must run them, with tool timeout **at least 300000 ms** for the original
matrix (historically 135.875 seconds), and separately report each exit:

```sh
git status --short --untracked-files=all
python roadmap/check_docs.py
python roadmap/checks/test_check_docs.py
python roadmap/checks/test_check_docs_discovery.py
UV_CACHE_DIR=/tmp/opencode/huron-effort-uv-cache make docs
git diff --check
git check-ignore -v roadmap/check_docs.py roadmap/checks/test_check_docs.py roadmap/checks/test_check_docs_discovery.py roadmap/checks/starlight-markdown-inputs.v1.json roadmap/checks/checker-input-boundary-receipt.md
git ls-files roadmap
```

Baseline: new suite/inventory/receipt absent must be reported NOT PRESENT, not passed;
run existing checker/matrix/docs, inspect ignore rule for planned paths. Known root
checker exit 1 with 2,330 lines and harness exit 1 before63 are defect reproduction,
never a green baseline. Any different population requires reconciliation. Final: every
command exit 0, original63 complete plus all new tests complete, docs strict `No issues
found`, whitespace zero, all five paths ignored, no tracked roadmap paths. Root docs
recipe is `uv run --group docs zensical build --strict`, not a Starlight build.

Also run nonwriting whitespace and local-link/fragment checks on every new/changed
authored text; `git diff` omits ignored files. Capture before/after HEAD, exact index,
Git-visible path/mode/content/deletion manifest, dirty inventory, all real plans and
all Starlight/SDK artifact paths/hashes/symlink targets. Only allowlisted checker/test/
inventory/receipt outputs may differ. Include original63 cases/expectations comparison
and original artifact population/byte equality in the reviewer receipt. No filters,
waivers, skips, xfails, weakened assertions, threshold changes or automatic rebaseline.
Application coverage floor 96.01%, import/complexity/duplication ratchets remain
unchanged; application/backend/frontend/agent suites are not applicable to this local
tooling-only boundary. Missing tools/cache authority/docs dependencies are BLOCKED.

## Blockers and readiness

- Parent: review/approve proposed discovery contract and exact resource mapping, then
  authorize an exclusive maximum code assignment; planning profile cannot implement.
- Enrollment owner/reviewer: use the resolved primary/clean receipts and review1
  package/archive/attachment proof to prepare exact identities for parent approval.
  No enrollment JSON exists yet; proof readiness is not enrollment authorization.
- Reviewer: determine whether retrospective local receipt/dual-install evidence is
  sufficient for non-hostile authored-input classification. Escalate any unproven
  origin, package mismatch, symlink collision or missing historical input; never
  silently expand policy to SDK/other producers or manufacture replacement evidence.
- Parent: separate BLOCKING fresh-run/output-protocol prerequisite before Starlight
  final qualification, as outlined above. This does not block bounded checker review
  or unchanged SDK review after this correction qualifies. Starlight search-error
  and table findings remain separate. No MVP readiness or production approval follows.

## Execution ledger

Planning attempt1: child `ses_ef0f3e0ffffe95afJSfTpSFKK7`, dispatch
`857c6ad8-e3c4-4e40-9e14-5dd709dc4840`, implementation/planning, recorded preparatory
profile (configured Low selection); provider acceptance not-proven. No provider effort
observation is claimed. Only `plan:checker-inputs` writes this file; source/docs-design/
raw-phases/Starlight/SDK claims are read-only. No nested agents or manual resumes.
That original planning turn had review count zero; its self-check was not independent
review or complete qualification.

Maximum independent plan review1: `ses_ef0ed9dadffeHFMdl0i6eVUDrv`, dispatch
`b5243808-f6a6-422d-ae17-88646ef51398`, terminal FAIL. Findings: F1 blocking global
symlink rejection/coverage loss; F2 high unbounded future qualification loop; F3 medium
undefined original-prefix binding. Original63 harness SHA-256 remains
`4cb36369770aee10d54d8a49edd00e68f21641359a68281d48e45f13335eb149`.

Planning fix attempt1: `ses_ef0e0497effeAJC8bCE8Ds9cC7`, dispatch
`a6a26983-02e5-4cdf-9370-b7169072a2b9`, fix/planning, preparatory (configured Low;
provider acceptance not-proven). Only `plan:checker-inputs` writes this file; source,
docs-design, Starlight, SDK and checks-roadmap are read-only. F1 is revised in
discovery/classification and regression contracts; F2 chooses the parent's retained
snapshot scope plus separate blocking future protocol; F3 derives prefix binding
from the hashed report with agreement checks. Dispositions await maximum review2
(review count 1 of at most 3); no implementation-readiness claim follows from prose.
Concurrent product-plan ownership is excluded: this fix does not read/edit those
plans or run global checker/docs/harness. Only bounded nonwriting self-checks apply.
Fix self-check: root status before/after shows the same 51 tracked dirty paths and
four untracked paths; `git diff --check` exits 0 before/after. Nonwriting
`python -I -B` validates this file's whitespace/final newline, JSON/Python example
syntax and explicit local evidence/skill references (no Markdown link/fragment
targets present); exit 0. `git check-ignore -v roadmap/checker-input-boundary-plan.md`
exits 0 at `.gitignore:40:/roadmap/`; `git ls-files roadmap` exits 0 with empty output.
The three planned discovery/inventory/receipt outputs remain absent, not passed.
These self-checks do not rerun or supersede the maximum review1 artifact preservation
manifest or global gates; full checks await separately dispatched maximum review.

Every future assignment must preserve the 15-minute progress contract, including
validation: brief task/role/attempt, elapsed time, concrete evidence/current command,
next action/blocker; report blockers/hangs immediately. Parent polls at least once
per minute and records terminal evidence, not idle alone.

## Escalation / final receipt

Planning-only gate: before/after root status and diff check; nonwriting new-plan text
and local-reference validation; `git check-ignore -v roadmap/checker-input-boundary-plan.md`;
`git ls-files roadmap` empty. Full-root failure is carried from independent receipt,
not rerun or relabeled PASS. Future rollback means stop, preserve owned diff/artifacts,
report last known state and ask parent for an exact corrective assignment; never reset,
clean, stash, overwrite a report or restore unknown bytes automatically.

Handoff: review this plan independently at maximum, separate contract findings from
the known current checker defect. Only after blockers close may parent dispatch
`/implement-markdown roadmap/checker-input-boundary-plan.md` as prerequisite tooling.
Production application/migration/deployment/live docs work remains paused.
