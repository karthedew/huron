# Repository readiness: inherited repair and current gates

Date: 2026-11-10. Status: **BLOCKED: review3 ended with APIError and no final verdict; inherited read-close defect remains**.
This is a bounded readiness effort, not a P phase or a production qualification.
The parent records the terminal review verdict. A writer's self-check cannot establish readiness.

## Context and entry boundary

The repository contains inherited, unaccepted M11.5e repair work and separate agent-tooling changes.
The historical [M plan](IMPLEMENTATION_PLAN.md) remains unchanged.
The [production plan](IMPLEMENTATION_PLAN_LATEST.md) keeps its phase IDs, technical design and historical receipts.
Do not resume the old M sequence. Do not count this effort as P implementation progress.

The initial P00 discovery is a historical diagnostic. It exposed missing docs dependencies, ambiguous
umask ownership, duplicate repair documentation, generated whitespace and nested npm resolution drift.
Restored docs dependencies then exposed two links to the removed `adm apply-acl` command.
These are readiness findings, not evidence that P00 or P01 acceptance is complete.
P01 still owns its own phase acceptance, even when readiness checks inspect the same inherited repair work.
Future P entry requires the parent's recorded readiness verdict and all prerequisites of the selected P phase.

No prototype is required for these bounded corrections. Actual CLI registration, repair operations,
generated schemas, subprocess tests and full gates supply the evidence instead.
Earlier publication prototypes remain limited experiments. They do not qualify the current product.

## Contract and ownership

Fix workers use code activity, medium Astra, with serial `*:write`. Explicit maximum assignments remain maximum.
The claim covers this worktree and check outputs, but only the private resources below.
It coordinates work, not edit authority. No worker delegates, escalates scope or resumes itself.
The parent reconciles new blockers and dispatches any further code changes separately.

The current fix owns these increments only:

- `docs/concepts/access-and-roles.md`: obsolete ACL guidance and its directly related text and links.
- `docs/concepts/raw-ingest.md`: obsolete ACL guidance and links. Preserve the inherited 206-byte naming hunk.
- `REPOSITORY_READINESS.md`: this bounded contract, ledger and evidence summary.
- `IMPLEMENTATION_PLAN_LATEST.md`: a dated separation note and future-entry prerequisite only.

Preserve the first readiness writer's four corrections:

1. Restore the existing locked docs packages, without dependency or lockfile changes.
2. Select the invoking npm through `node "$npm_execpath"` in nested web/docs scripts.
   Retain all seven subprocess cases in `web/scripts/npm-scripts.test.mjs`.
3. Assign the inherited umask bundle explicitly to P01 without behavior changes.
4. Reduce `FailureReason` to a one-sentence description, regenerate OpenAPI and web types,
   and retain the direct API snapshot regression. `RepairFailureOut` remains authoritative.

The previous setup used top-level npm 11.19.1 with the existing lockfile in `web/docs-site`.
Its command was `npm ci --no-audit --no-fund --prefer-offline`. No additional setup is expected.
Nested scripts must not resolve the unrelated npm 2.15.12 on PATH. No global npm changes are authorized.

Readiness review must inspect the inherited repair ownership, not merely these four corrections.
Its inventory includes storage repair/parity/errors/ports/exports, POSIX primitives, placement pruning,
lake repair planning/lookups/lifecycle, API repair/routes/schema/runtime, and their existing tests.
It also includes the two repair import contracts, naming/upload tests, raw-ingest naming text,
API error/schema consumers, and `tests/conftest.py` temporary-mode and fixed-umask fixtures.
The umask bundle includes `SERVICE_UMASK/build_runtime` and lifespan coverage.
The P01 clause enumerates those paths. Unrelated hunks remain outside readiness edit authority.

The user's historical repair resolution remains binding:

- `MemoryStorage` stays a full adapter. Both adapters must pass the complete error matrix.
- Preserve the 253 shared cases, method variants and pair coverage. Compare exact errors and paths.
- Metadata or temporary-file failures name that actual file, in the specified API path form.
- `RepairFailureOut` Field descriptions are the sole detailed failure contract.
- Repair remains database-planned, with no filesystem walk, and exactly three failure reasons.
- Preserve no-follow containment and the retained reference branch. No containment hole was found historically.

No product runtime, fixture, agent-tooling, skill, journal or lock changes belong to this continuation.
No compatibility path, new command, migration, source behavior or product-design change is authorized.
Do not weaken tests, thresholds, assertions, source scope, link checks or complexity limits.
Do not commit, branch, push, reset, revert, stash, pull images or delete unknown data.

Preservation constants:

- HEAD: `0dcdf1ff6a8689f704a73a0758a886c18b5d3584`.
- Reference `m11.5-escalated`: `04958ad538eac69f16a6abdd3925350781e4d718`.
- Historical plan blob: `862e1bafc54c5ca88b0351ff7ee723662a1ac7f8`.
- Migration `0003_uploads.py` blob: `83757f7e73640356639ae07c45d7885660b9a6e3`.

## Current behavior and limits

Grants govern API access. Directory modes and `share_group` govern filesystem read access.
Grant changes do not apply ACLs or change directory permissions. Huron uses no ACLs.
The installed CLI supports `adm check` and `adm provision-orgs`.
It does not yet support `adm repair`, `adm provision-catalogs` or `adm apply-acl`.
Do not replace a broken link with one of those nonexistent commands.

Current API repair plans directories from rows and rereads row existence or metadata before each step.
It can create missing directories, correct permitted mode changes, try the catalog group, and restore metadata.
It does not recursively change groups or repair file modes. Storage administrators handle group/setgid obstructions.
The captured plan's share group can become stale. P19 owns stronger current-group/version ordering.
This known limitation remains explicit, not silently fixed or waived by readiness.

The existing CLI integration skip remains a P33 release limitation. Mountless API integration is not ingestion evidence.
P33 still owns real tusd/nginx/CLI workflows and skip removal. Missing offline assets remain blockers at their named gates.
P37 retains ONTAP, fencing and workload evidence. Readiness establishes none of those production properties.
Broader stale ingest/operator prose remains P36-owned. This effort repairs only the assigned ACL guidance.

## Skills and working rules

Read AGENTS.md, the full production plan, the orchestration/verification/implement-markdown workflows,
the assignment template, domain guidance and the historical repair resolution before work.
Use these canonical sources:

- `.claude/skills/asd-ste100/SKILL.md` for language.
- `.agents/skills/huron-implementation-plan/SKILL.md` and `.agents/templates/phase-plan.md` for this record.
- `.agents/skills/playwright-cli/SKILL.md` for browser QA.
- The canonical web skills in `.agents/skills` for any affected web component or style analysis.
- `oop-design`, `fastapi` and `postgresql-table-design` from `.agents/skills` for independent repair review.

Reuse existing public-behavior coverage and fixtures. Add tests only for an uncovered changed contract.
Do not introduce skips, xfails, exclusions or suppressions. Real filesystem and PostgreSQL tests remain mandatory.
Send progress at least every 15 minutes, including validation. Report blockers and suspected hangs immediately.
Each update names readiness, role/attempt, elapsed time, concrete results, current command and next action.
The parent polls at least once per minute. Idle alone is not terminal evidence.

## Exact resources and gate environment

Root: `/home/karl/repo/huron-tusd`. Web: root plus `/web`. Docs: root plus `/web/docs-site`.
All subprocesses inherit `UV_OFFLINE=1` and `UV_NO_SYNC=1`.
Use `HURON_TEST_DATABASE_URL=postgresql://huron_p00@127.0.0.1:25432/postgres` only.
Ordinary fixtures may create and remove only their new disposable databases on this assigned server.
Preserve the interrupted prior run's database `huron_test_bdfdfe352c31`. Do not drop it.

The only assigned container is `huron-p00-20261110t045227-pg`, ID
`83336a4ac0a5ee998b86f586d6b446f11ebe767ee81ae67af359b4d30db96eaf`.
Its label is `huron.assignment=p00-20261110t045227`, volume `huron-p00-20261110t045227-pgdata`.
Its cached image is `sha256:88a36c64c1003dad93f56daa12d1f8916ec66d1fa3e5fb1fb0ae7cb77efd56d1`.
Verify identity before start/use/stop. Do not remove its container or volume.
Do not use testcontainers, dev.env, developer databases or retained prototype container `ca0aac2e123e`.

Assigned harness variables:

```text
HURON_E2E_IDP_PORT=28199
HURON_E2E_PROXY_PORT=28197
HURON_E2E_API_PORT=28198
HURON_E2E_WEB_PORT=24173
HURON_DEMO_WEB_PORT=25173
```

Check port ownership before startup. Developer ports 8080, 5173, 2718 and 8082 are not assigned.
Use only gate-owned harness/browser processes. Reconcile and stop owned processes and PostgreSQL after checks.
Matching cached Chromium is available. No package-fetch fallback, browser upgrade or autofixer installation is permitted.

## Acceptance and full applicable gates

Ready requires complete passing current gates and preservation evidence.
It also requires independent maximum review of the repaired readiness boundary and inherited repair ownership.
Independent review must rerun these gates. No self-check, historical green count or missing asset can substitute for that review.
No P phase becomes complete through this readiness verdict. No production qualification is implied.

G0, root:

```sh
git diff --check
git diff --cached --check
git diff --no-index --check /dev/null REPOSITORY_READINESS.md
git diff --no-index --check /dev/null IMPLEMENTATION_PLAN_LATEST.md
git diff --no-index --check /dev/null src/huron/core/storage/repair.py
git diff --no-index --check /dev/null web/scripts/npm-scripts.test.mjs
uv run --offline --no-sync python scripts/check_links.py REPOSITORY_READINESS.md HANDOFF_M11_PLAN.md IMPLEMENTATION_PLAN_LATEST.md design/m11-production-architecture.md design/m11-review-evidence.md design/m11-prototype-evidence.md HANDOFF_MEDIUM_WORKFLOW.md
```

Check each additional owned untracked text file separately if the inventory changes.
The no-index check may exit 1 for additions without whitespace diagnostics. Other checks must exit 0.

GP, root: `UV_OFFLINE=1 UV_NO_SYNC=1 make gate`. All actual constituents must pass:

```text
uv run ruff check src tests scripts/cli_reference.py scripts/ste_check.py
uv run ruff format --check src tests scripts/cli_reference.py scripts/ste_check.py
uv run mypy
uv run mypy scripts/cli_reference.py scripts/ste_check.py
uv run ty check
uv run ty check scripts/cli_reference.py scripts/ste_check.py
uv run lint-imports
uv run python scripts/cli_reference.py --check
uv run python scripts/ste_check.py
uv run pytest -m "not integration" --cov=src/huron --cov-report=term-missing
uv run radon cc src --min C
uv run radon mi src --min B
uv run complexipy src --max-complexity-allowed 15
uv run python scripts/check_schema_map.py
```

Preserve the 90% coverage floor and all import/source/complexity limits. Radon must print nothing.
Record exact uncovered lines and all counts. Allow more than 133 seconds for GP, without competing retries.

GC and GA, root:

```sh
uv run --offline --no-sync pytest -m contract
uv run --offline --no-sync pytest -m integration
uv run --offline --no-sync pytest tests/unit/api/test_openapi_snapshot.py tests/unit/test_error_contract.py
```

No snapshot regeneration is expected. Record the existing integration skip without calling it release evidence.

GW, web:

```sh
npm run check
npm test
npm run lint
npm run build
npm run test:e2e
node --test scripts/npm-scripts.test.mjs
```

Check must report zero errors and warnings. Every command must exit 0.

GD, root:

```sh
UV_OFFLINE=1 UV_NO_SYNC=1 make docs-check
uv run --offline --no-sync python scripts/ste_check.py
uv run --offline --no-sync python scripts/cli_reference.py --check
```

Also run web `npm run docs:build` and docs `npm test`. Retain strict rendered link/anchor checks.
Capture both changed concept pages at 390×844, 816×900 and 1440×900, light and dark.
Inspect every capture, wrapping, links, keyboard focus and forced colors on the owned harness.
Keep screenshots ignored. Record the prior API description's visual applicability separately.
Investigate the reported stock Swagger focus limitation without automatically redesigning Swagger.
The unavailable Svelte autofixer stays not run. No Svelte change is expected.

Generic workflow drift remains explicit: `make docs` is a no-op, and strict pytest markers exclude `-m unit`.
No `make test-acceptance` target exists yet. The exact commands above govern this readiness assignment.
Agent-tooling gates are not applicable because no tooling change is assigned.

## Execution ledger

No independent readiness review ran before fix attempt 2. Review1 subsequently returned FAIL, as recorded below.
The parent owns terminal observations, any later review verdict and future P admission.

| Event | Evidence and disposition |
| --- | --- |
| Initial P00 discovery | Maximum discovery child `ses_e3c2f1fa5ffeAQiv3XEiq3Oyux`, terminal BLOCKED. The production plan preserves its full historical receipt. Not implementation progress. |
| Readiness fix attempt 1, previously called P00 remediation | Medium/code, child `ses_e3bfe3984ffeQjv8Nxk6aMAchI`, dispatch `66662fd7-9215-4cc4-af6c-61272294fef8`. Completed 06:05:29.802Z, observed 06:06:08.935Z. Terminal BLOCKED, self-check only. |
| Attempt 1 changes | Four corrections above. Seven existing files and one new test. Its receipt reports 940 other files preserved. No umask behavior change. |
| Attempt 1 checks | GP 2,202 passed, 99.98% coverage. Contract 59, GA 4, web 1,645, docs tests 12, npm regression 7 passed. Check/lint/build passed. Docs build and e2e failed on the two removed ACL anchors. These are leads, not qualification. |
| Attempt 1 visual finding | Concise API description rendered without overflow. Stock Swagger schema button lacked visible focus. Requires attribution, not an automatic product change. |
| Readiness fix attempt 2 | Medium/code, serial `*:write`, child `ses_e3bee1d1cffeVLvNoe7NgQs2AN`, dispatch `38d622ee-4861-439f-ad37-619ea5647737`, created 06:07:48.945Z. Configured Astra/medium, provider acceptance not-proven. |
| Attempt 2 preflight | Captured 948 initial file hashes. Preserved refs and historical plan/migration blobs matched. Assigned PostgreSQL was stopped with PID 0. Assigned ports were free. |

Attempt 1 evidence: `/tmp/opencode/p00-remediation-20261110/SELF-CHECK.md`, `increment.diff`, and `preservation.json`.
Attempt 2 evidence: `/tmp/opencode/repo-readiness-20261110-fix2`, with initial/final hashes, incremental diff, command receipts and browser evidence.
The parent reports that the current schema and skills were loaded after restart. This continuation changes no agent tooling.

## Remaining blockers and handoff

- Current writer: terminal self-check below. No independent acceptance claimed.
- Parent: reconcile any new product, tooling or e2e blocker before another code assignment.
- Independent maximum reviewer: inspect and rerun the entire readiness boundary, including inherited repair ownership.
- Parent: record terminal review acceptance before future P entry. P01 retains its separate acceptance obligation.
- Production owners: retain P19 ordering, P33 integration, P36 broader documentation and external qualification obligations.

No unilateral waiver of missing tests or assets is permitted. Preserve failed evidence and unknown data.

## Fix attempt 2 self-check receipt

These results are writer evidence only. No independent review ran, and no P acceptance changed.
The current increment changes the two assigned concept guides, adds this record, and adds the separation note to the production plan.
The inherited 206-byte naming hunk and all first-writer corrections remain unchanged.
No new test was necessary: existing rendered-link checks, CLI reference checks and public behavior suites cover the corrected documentation boundary.

All commands used the directories and environment above. Logs and matching JSON receipts are in the attempt 2 evidence directory.

| Gate | Outcome | Log basename |
| --- | --- | --- |
| GP `make gate` | Exit 0, 2,202 passed, 2 deselected, 99.98% coverage, 10 import contracts kept | `gp` |
| Explicit radon CC and MI checks | Exit 0, both outputs empty | `radon-cc`, `radon-mi` |
| GC contract | Exit 0, 59 passed, 2,145 deselected | `gc-contract` |
| GC integration | Exit 0, 1 passed, 1 existing skip, 2,202 deselected | `gc-integration` |
| GA snapshot/error contract | Exit 0, 4 passed | `ga` |
| Focused containment/repair/race suites | Exit 0, 650 passed | `repair-focused` |
| GW check | Exit 0, zero errors and warnings | `gw-check` |
| GW unit tests | Exit 0, 130 files and 1,645 tests passed | `gw-test` |
| GW lint and build | Both exit 0 | `gw-lint`, `gw-build` |
| GW e2e | Exit 0, 245 passed, no retries or new skips | `gw-e2e` |
| Nested npm regression | Exit 0, 7 passed | `npm-regression` |
| GD root links, STE and CLI reference | All exit 0, zero hard language findings | `gd-root`, `gd-ste`, `gd-cli` |
| GD strict site build | Exit 0, 50 pages, all rendered links resolve | `gd-build` |
| GD docs tests | Exit 0, 12 passed | `gd-test` |
| Seven retained prototype hashes | All match the prior receipt | `retained` |

GP ran for 133.80 seconds without interruption. Coverage includes 9,649 statements with two misses in unchanged CLI `identifiers.py:76–77`.
No source statement changed in this continuation. Complexity limits and the 90% coverage floor remain unchanged.
STE reports 21 advisory findings, not hard failures. Astro retains its existing smartypants, empty i18n/404 and missing sitemap-site warnings.
Those warnings do not replace or disable the strict rendered-link check.

Browser session `readiness-fix2` used the owned harness at `http://localhost:24173`.
The writer inspected 38 concept-page images: section, full-page and focus captures at each viewport/theme, plus two forced-color captures.
Both themes rendered correctly. All 12 page-width measurements equaled their viewport widths.
The changed text and commands wrap, and the focused `huron adm check` links have visible, unclipped outlines.
Both links navigated to the actual CLI check heading. Forced-color controls, text and links remain visible.
The full-page images supplement the readable section captures. Existing wide tables/code retain their local scrolling.
Console inspection reported no errors or warnings. No Svelte source changed. The unavailable autofixer was not run or installed.

The first QA script waited for a theme selector hidden at the mobile viewport and timed out.
The corrected script used the actual automatic color-scheme behavior and completed all captures.
Playwright CLI returned exit 0 even for that initial diagnostic, so the receipt uses the inspected result, not exit status alone.

The API description still renders the concise sentence. A separate check reproduced the reported Swagger focus limitation.
Both `FailureReason` and unchanged `CollectionOut` buttons match `:focus-visible` but have `outline-style: none` and no shadow.
The loaded stylesheet is stock `swagger-ui-dist@5` from jsDelivr, not changed Huron styles.
The additional screenshot confirms the absent indicator. This is an inherited renderer finding for parent disposition, not passed focus QA or a new docs regression.
No API operation was executed through Swagger, and no renderer change was made.

The owned QA supervisor and its three children received SIGTERM after browser closure.
The assigned PostgreSQL server had no other client backends before stop.
It retained only the default databases and the explicitly preserved `huron_test_bdfdfe352c31` database.
The container stopped with PID 0 and exit 0. Its volume remains. The retained prototype container remains stopped with PID 0.
Final G0 root/cached whitespace and seven-document link checks passed.
The four separate owned untracked-text checks each returned 1 for additions, without whitespace diagnostics.
The final inventory preserves 945 initial files byte-for-byte. Only the three owned existing files changed, and this readiness record is new.
Staged changes, refs, the historical plan and migration blobs, and all seven retained prototype hashes match.
The browser, supervisor and three recorded children are absent. All six assigned ports are free.
IdP and web children exited 0. The API wrapper exited 143 after the owned SIGTERM.
Screenshot hashes and exact incremental hunks are in `screenshots.json` and `increment.diff` beside the terminal self-check.

## Parent receipt: independent maximum review1

Review1 returned **FAIL** for one fixable inherited repair defect. All assigned automated gates passed.
No P phase is accepted or admitted by these results.

- Reviewer: `ses_e3bd9b479ffe6lgZpQnIxS1W6h`, dispatch `d21b7948-2995-4d1b-bcc9-87d1bbd7e75f`.
- Role/activity/profile: verification/review/maximum, serial `*:write`.
- Configured model/effort: `openai/gpt-6-astra` / `max`. Provider acceptance remains not-proven.
- Terminal completion: 2026-11-10T06:54:04.023Z. Parent observation: 06:54:45.755Z.
- Evidence: `/tmp/opencode/repo-readiness-review1-20261110/`.
- Review count: one of at most three. A correction must finish before a fresh review2.

### R1-1: preserve the actual temporary-file error path

`PosixStorage.write_bytes` preserves the temporary-file location for `PartBlocked` only.
Other errors from the `.huron-part` file pass through `_parent` as errors on the requested target.
The reviewer injected EIO on `os.stat` of `metadata.json.huron-part` in a real temporary lake.
Both `Repairer` and the HTTP repair route incorrectly reported `metadata.json` in the path and detail.
Original metadata bytes remained intact. The rooted-organization case reproduced the same attribution defect.

Locations: `core/storage/posix.py:162–174,267–287`, `pkg/fs/posix.py:242–244,349–353`,
and the coverage gap in `tests/unit/storage/test_repair.py:223–284`.
See `part-error-reproduction.log` and `part-error-api-reproduction.log`.
The parent assigns the correction to the readiness storage/repair owner, not a future P phase.
Preserve the actual file for ordinary temporary-file errors and add direct filesystem/API regressions.
Keep parent-permission precedence, the full shared adapter matrix, exact details and three failure reasons.

### Independent checks and disposition

The reviewer inspected all 41 inherited product paths and the readiness increments.
It confirmed the four initial corrections, obsolete ACL guidance replacement and preserved umask behavior.
GP passed 2,202 tests with 99.98% coverage. Contract passed 59, GA passed 4 and focused repair passed 650.
Web check reported zero errors and warnings. Web unit tests passed 1,645, e2e passed 245, npm regressions passed 7.
Docs tests passed 12. The strict build rendered 50 pages with valid links. G0 and the seven-document link check passed.
Integration retained one pass and the existing P33-owned skip. Full command logs remain in the review evidence directory.

The reviewer inspected 67 images, including both changed concept pages at all required sizes and themes.
It verified wrapping, focus, forced colors and all 61 main-page links and anchors.
It independently attributed the missing Swagger focus outline to unchanged stock renderer CSS.
The parent records that issue for separate API-documentation accessibility maintenance.
It is not a readiness prose regression or a passed focus check, and does not block this bounded readiness scope.

All 949 captured file hashes and 98 status entries were unchanged during review.
Protected references, blobs and seven prototype hashes matched. No source edits or setup occurred.
The reviewer stopped its browser and harness. Assigned ports were free and PostgreSQL was stopped with PID 0.
The container, volume and `huron_test_bdfdfe352c31` remain preserved. Developer services were untouched.

## Fix attempt 3 self-check receipt

This is writer evidence, not independent acceptance. Review1 remains FAIL, one of at most three reviews.
No P phase started or became accepted. The parent must reconcile this terminal result before dispatching review2.

- Worker: `ses_e3bc1aebdffeYdb2x7eZt08a0C`, dispatch `ebf99c23-3123-48a7-9b50-ab11052264d7`.
- Role/activity/profile: fix/code/medium, serial `*:write`. Configured model: `openai/gpt-6-astra`. Provider acceptance remains not-proven.
- Evidence: `/tmp/opencode/repo-readiness-fix3-20261110/`. Each gate has a full log and a JSON command receipt.

### Owned correction

The parent explicitly assigned this source correction after R1-1. This supersedes the earlier prose-only edit boundary for this attempt only.

| File | Increment |
| --- | --- |
| `src/huron/pkg/fs/posix.py` | Add generic `FileError` and preserve the known part-file origin during inspection and I/O. Separate part removal, creation and descriptor writes. |
| `src/huron/core/storage/posix.py` | Map `FileError` through the storage-owned, constructed part path before generic target mapping. |
| `tests/support/disk.py` | Add one reusable, single-fault filesystem injector for the direct regressions. |
| `tests/unit/pkg/test_posix.py` | Add 16 cases for inspection, removal, creation, descriptor operations, and target/rename boundaries. |
| `tests/unit/storage/test_repair.py` | Add 24 cases for exact error paths, rooted conversion, byte preservation and successful retry. Correct the existing fsync expectation to name the part file. |
| `tests/unit/api/test_repair.py` | Add four HTTP cases for EIO and EACCES with default and rooted organizations. |
| `REPOSITORY_READINESS.md` | Append this self-check only. Preserve the parent's failed review receipt. |

The generic filesystem package carries filesystem information only. Storage constructs the LakePath from its own part name, never from an arbitrary system exception filename.
The tests deliberately supply an unrelated absolute exception filename. Exact returned paths and details still name the actual part file.
Part inspection, descriptor chmod/write/fsync/close, and non-permission creation/removal errors retain that origin.
Creation and unlink permission failures retain the established parent-access mapping. Target inspection and rename failures retain target mapping.
Symbolic-link and directory classifications remain unchanged. No-follow traversal and cleanup checks remain in place.
No new domain reason or error code was added. The three repair reasons and all shared matrix rows remain unchanged.
MemoryStorage needs no change: its existing modeled states and their precedence still pass the full shared specification.

### Regression and gate evidence

The first regression run exposed ten wrong-path failures and two incomplete rooted test setups.
The rooted setup needed contributor access and a collection-enabled namespace. Both setup defects were corrected without changing existing fixtures.
`regression-baseline-final.log` then records 28 wrong-path failures against the captured initial implementations.
That control loaded the initial module text in an isolated Python process. It did not revert or edit the working tree.
The same regressions pass with the correction. Original metadata bytes remain intact, and storage retries restore the requested bytes.

| Gate | Result | Log basename |
| --- | --- | --- |
| GP full `make gate` | Exit 0, 2,246 passed, 2 deselected, 99.98% coverage | `gp` |
| Radon CC and MI | Both exit 0 with empty output | `radon-cc`, `radon-mi` |
| GC contract | Exit 0, 59 passed | `gc-contract` |
| GC integration | Exit 0, 1 passed, 1 inherited CLI skip | `gc-integration` |
| GA snapshot/error contract | Exit 0, 4 passed | `ga` |
| Focused repair/containment/races plus POSIX primitives | Exit 0, 760 passed | `focused-final` |
| GW check | Exit 0, zero errors and warnings | `gw-check` |
| GW unit tests | Exit 0, 130 files, 1,645 passed | `gw-test` |
| GW lint/build | Both exit 0 | `gw-lint`, `gw-build` |
| GW e2e | Exit 0, 245 passed | `gw-e2e` |
| Nested npm regression | Exit 0, 7 passed | `npm-regression` |
| GD root/STE/CLI reference | All exit 0 | `gd-root`, `gd-ste`, `gd-cli` |
| GD strict site build | Exit 0, 50 pages, rendered links resolve | `gd-build` |
| GD docs tests | Exit 0, 12 passed | `gd-test` |
| G0 root/cached/seven-document links | All exit 0 | `g0-diff`, `g0-cached`, `g0-links` |
| Six separate untracked-text checks | Exit 1 for additions, no whitespace diagnostics | `g0-untracked-0` through `g0-untracked-5` |

GP completed in 135.60 seconds. Both touched source files have 100% line coverage: 239 filesystem statements and 223 storage statements.
Overall coverage includes 9,676 statements. Only unchanged CLI `identifiers.py:76–77` remain uncovered. Thresholds and exclusions are unchanged.
The initial local evidence helper failed on import because it lacked a main guard. The corrected helper completed all final checks.
Existing Astro smartypants, empty i18n/404 and missing sitemap-site warnings remain. No strict link check was disabled.

This correction changes no visible page, layout, generated API contract or concept guide. New visual captures are not applicable.
The prior independent docs QA remains applicable to those unchanged pages. The stock Swagger focus limitation remains separate maintenance, not passed focus QA.
The unavailable Svelte autofixer was not run or installed. P19, P33 and P36 limitations remain unchanged.

### Preservation and resources

The initial inventory captured 949 text files. Only the seven listed files changed, with no new repository file.
Initial/final snapshots and `increment.diff` retain exact hunks. Staged changes, references and protected blobs remain unchanged.
All seven retained prototype artifact hashes match. No setup, tool configuration, migration, commit or history change occurred.
The assigned PostgreSQL server retained only its default databases and `huron_test_bdfdfe352c31` before shutdown, with no other client backends.
Container `83336a4ac0a5ee998b86f586d6b446f11ebe767ee81ae67af359b4d30db96eaf` stopped with PID 0 and exit 0. Its volume remains.
The retained prototype container `ca0aac2e123e` remains stopped with PID 0. All assigned ports are free after the harness completed.
Developer services remain untouched. No independent PASS or permission to resume follows from this self-check.

## Parent receipt: independent maximum review2

Review2 returned **FAIL**. R1-1 is independently closed. R2-1 is a fixable error-precedence defect.
Review count is two of at most three. No P phase was admitted or accepted.

- Reviewer: `ses_e3bb17606ffeUTY72EnNsFdE6T`, dispatch `76fa8694-4044-492a-afb3-c96cf5dda8f9`.
- Role/activity/profile: verification/review/maximum, serial `*:write`.
- Configured model/effort: `openai/gpt-6-astra` / `max`. Provider acceptance remains not-proven.
- Terminal completion: 2026-11-10T07:33:23.877Z. Parent observation: 07:34:07.016Z.
- Evidence: `/tmp/opencode/repo-readiness-review2-20261110/`, including `gate-receipts.json`.

R1-1 passed four HTTP cases and an independent 36-case filesystem check covering part-file operations and target boundaries.
Rooted paths, exact details, byte preservation, retry and untrusted error filenames were checked.

R2-1 occurs when cleanup fails while a primary exception is active.
At `pkg/fs/posix.py:256–261`, part cleanup can replace a write or rename error.
At lines 360–368, descriptor close can replace a write or fsync error.
Rename ENOSPC followed by cleanup EIO reports the part file's EIO through HTTP, hiding the target's ENOSPC.
Rename plus cleanup-stat failure and fsync plus close failure also reproduced.
Metadata bytes remained intact and retry succeeded. No data loss was observed.
The baseline already masked primary errors. Fix3 additionally changed the secondary failure's reported path.

The parent assigns the readiness storage owner to preserve primary errno, message, origin and causal identity.
Secondary cleanup diagnostics must remain available without replacing the primary public failure.
Combined-failure tests must cover cleanup stat/unlink and descriptor close, HTTP details, byte preservation and retry.
All existing single-fault mappings and parent-permission precedence must remain.
See `cleanup-precedence.log`, `compound-http.log` and `compound-baseline-control.log` for independent counterexamples.

All full gates passed: GP 2,246 tests and 99.98% coverage, contract 59, GA 4, focused 760,
web unit 1,645, e2e 245, npm regression 7, docs tests 12, and the strict 50-page docs build.
G0, links and all static gates passed. Integration retained one pass and the declared P33 CLI skip.
All 22 inherited changed/new source files had complete coverage, which does not prove combined-error coverage.

All 949 file hashes and 99 status entries remained unchanged. Protected references and prototype hashes matched.
PostgreSQL was stopped with PID 0. The preserved database, container and volume remain.
Assigned ports were free and no gate-owned processes remained. Unrelated desktop Chrome was identified and left untouched.
Concept pages were unchanged since review1, and all 67 retained screenshot hashes matched.
The independently attributed Swagger limitation remains separate nonblocking maintenance, not passed focus QA.

## Fix attempt 4 self-check receipt

This is writer evidence only. Review1 and review2 remain **FAIL / FAIL**, two of at most three reviews.
R1-1 remains independently closed by review2. Only the parent can dispatch the final allowed review3.
No P phase started or became accepted. This receipt does not resume the historical M sequence.

- Worker: `ses_e3b9d7f75ffeq96mezZwk5WEpw`, dispatch `98e2e301-5381-4611-950a-f04fab93a1a1`.
- Role/activity/profile: fix/code/maximum, serial `*:write`.
- Configured model/effort: `openai/gpt-6-astra` / `max`. Provider acceptance remains not-proven.
- Evidence: `/tmp/opencode/repo-readiness-fix4-20261110/`. Logs have matching JSON command receipts.

### Narrow correction for R2-1

The parent explicitly assigned this correction under the user's readiness authorization.
This scope supersedes the earlier prose-only boundary for this attempt, without changing any P contract.

| File | Increment |
| --- | --- |
| `src/huron/pkg/fs/posix.py` | Preserve primary errors during part removal and descriptor closure. Retain ordinary secondary errors as exception notes. |
| `tests/support/disk.py` | Extend the existing filesystem injector to return exact exceptions. Add shared combined-failure cases and diagnostic inspection helpers. |
| `tests/unit/pkg/test_posix.py` | Add 146 cases for error identity, cleanup diagnostics, cancellation, descriptor ownership, obstruction safety, empty writes and retry. |
| `tests/unit/storage/test_repair.py` | Add 124 cases for exact storage causes, paths, details, rooted conversion, parent closure, old bytes and retry. |
| `tests/unit/api/test_repair.py` | Add 120 combined-failure HTTP cases. Reuse the rooted setup and strengthen the four existing R1 cases with retry assertions. |
| `REPOSITORY_READINESS.md` | Append this scope and self-check. Preserve both failed review receipts and the existing status. |

The primary exception keeps its errno, message and explicit cause chain. Existing `FileError` wrapping retains the original exception object.
Secondary `OSError` diagnostics remain in exception notes, including multiple close/removal failures. Notes do not change `str(error)` or the public failure schema.
Cleanup does not suppress cancellation, `KeyboardInterrupt`, `SystemExit` or `GeneratorExit`.
An active interruption survives ordinary cleanup errors. A new interruption during cleanup propagates instead of being hidden.

The final parent descriptor also closes during a failed rename. Its close therefore needs the same precedence rule.
`open_beneath` now transfers ownership to the new descriptor before closing the previous one.
A failed close is never retried, because the descriptor can already belong to another resource.
Tests force descriptor reuse and prove that the replacement stays open while the owned descriptor closes.
Sole close errors still propagate. A close failure after successful rename does not undo the completed replacement.

Storage constructs paths as before. No system exception filename selects a lake path.
All R1 single-fault mappings, parent-access precedence and the existing fsync assertion remain.
The shared matrix still contains 253 rows, 16 method variants and 125 arrangeable pairs.
No storage mapping, MemoryStorage, API reason, error code, dependency, umask or runtime change was necessary.
No generated contract, concept guide, latest plan or tooling file changed.

### Reproduction and acceptance evidence

The five named review2 logs were read before editing. They contain results and inline-command tracebacks, but no saved reproduction commands or scripts.
This evidence gap was reported. Equivalent public-behavior controls are saved as `reproduce.py`, with exact commands in their JSON receipts.
Before correction, both storage and HTTP controls reported secondary EIO instead of primary rename ENOSPC.
Both preserved old bytes and succeeded on retry. The corrected controls pass, including cleanup-stat and fsync-close cases.

`baseline.py` loads captured initial module text in an isolated process. It never rewrites or reverts working files.
The R2 control produced 344 expected failures against the fix4 initial implementations.
The separate R1 control produced 28 expected wrong-path failures against the preserved pre-fix3 implementations.
The current R1 selection passes all 28 cases. These controls distinguish both defects from test-only assertions that always pass.

The first expanded focused run passed 1,139 cases and failed one descriptor-reuse fixture assertion.
The fixture incorrectly assumed which free descriptor the kernel would allocate.
It now uses `dup2` to force the required reuse, without weakening the lifetime assertion.
Final focused validation passes 1,150 cases, including 390 added cases and all 760 initial cases.

| Gate | Outcome | Log basename |
| --- | --- | --- |
| GP full `make gate` | Exit 0, 2,636 passed, 2 deselected, 99.98% coverage | `gp` |
| Explicit radon CC and MI | Both exit 0, both outputs empty | `radon-cc`, `radon-mi` |
| GC contract | Exit 0, 59 passed | `gc-contract` |
| GC integration | Exit 0, 1 passed, 1 inherited CLI skip | `gc-integration` |
| GA snapshot/error contract | Exit 0, 4 passed | `ga` |
| Focused filesystem/repair/containment/race suites | Exit 0, 1,150 passed | `focused-final` |
| R1 current public assertions | Exit 0, 28 passed | `r1-fixed` |
| R2 current storage and HTTP controls | Both exit 0 | `r2-storage-fixed`, `r2-http-fixed` |
| GW check | Exit 0, zero errors and warnings | `gw-check` |
| GW unit tests | Exit 0, 130 files and 1,645 tests passed | `gw-test` |
| GW lint and build | Both exit 0 | `gw-lint`, `gw-build` |
| GW e2e | Exit 0, 245 passed | `gw-e2e` |
| Nested npm regression | Exit 0, 7 passed | `npm-regression` |
| GD root links, STE and CLI reference | All exit 0 | `gd-root`, `gd-ste`, `gd-cli` |
| GD strict site build | Exit 0, 50 pages, rendered links resolve | `gd-build` |
| GD docs tests | Exit 0, 12 passed | `gd-test` |

GP completed in 159.83 seconds. Its 10 import contracts and all static checks passed without threshold changes.
The changed filesystem module has 254 covered statements and no misses. The unchanged storage adapter has all 223 statements covered.
Overall coverage includes 9,691 statements. Only unchanged CLI `identifiers.py:76–77` remain uncovered.
`coverage-and-matrix.json` records coverage, matrix counts and installed Python package versions.
STE has no hard findings and 21 advisories. Existing Astro warnings remain, with strict rendered links and anchors checked.

This correction changes no visible page, layout or rendered contract. New visual captures are not applicable.
The prior independent 67-capture concept-page QA remains applicable to the unchanged pages.
The stock Swagger focus limitation remains separate nonblocking maintenance, not passed focus QA.
The unavailable Svelte autofixer was not run or installed. P19 ordering, P33 ingestion and P36 broader prose remain future obligations.

### Preservation and resources

The initial snapshot contains 949 file hashes and their text. Intermediate snapshots preserve every unowned file, staged change, reference and protected blob.
The six listed files are the complete increment. No repository file was added or deleted.
All seven retained prototype hashes match. No setup, installation, migration, tooling, history or reference-branch change occurred.

The assigned PostgreSQL container briefly rejected connections during startup, then its separate readiness check passed.
Before shutdown, it held only the default databases and preserved `huron_test_bdfdfe352c31`, with no other client backend.
Container `83336a4ac0a5ee998b86f586d6b446f11ebe767ee81ae67af359b4d30db96eaf` stopped with PID 0 and exit 0.
Its volume remains. Retained prototype container `ca0aac2e123e` remains stopped with PID 0.
All six assigned ports are free. No gate-owned harness or cached-browser process remains.
Developer services and desktop Chrome were not changed.

Final G0 root/cached whitespace checks and the seven-document link check each returned 0.
The six separate untracked-text checks each returned 1 for additions, without whitespace diagnostics.
The final inventory preserves 943 initial files byte-for-byte. Only the six listed files changed.
Status entries, staged changes, references, protected blobs and all seven retained prototype hashes match the initial snapshot.
Exact incremental hunks, final hashes and command receipts remain in the evidence directory.
These results require parent reconciliation and independent review3. They do not establish independent acceptance or permission to resume.

## Parent receipt: interrupted review3 and recovery discovery

Review3 did not return a final verdict. Its actual last assistant response was empty and ended with `APIError`.
Do not promote its earlier progress into PASS or a completed FAIL. Review history is FAIL / FAIL / interrupted review3.
Readiness remains BLOCKED, and no P phase is admitted or accepted.

- Review3 child: `ses_e3b7e91d7ffeweh1J84j3eWqV4`, dispatch `8a077bab-aa70-4849-88fb-7b2c62b8d887`.
- Completed assistant timestamp: 2026-11-10T08:29:15.365Z. Parent observed the terminal APIError at 13:58:58.161Z.
- Review3 evidence: `/tmp/opencode/repo-readiness-review3-20261110/`.
- Recovery discovery child: `ses_e3a3d09acffefpxA79ZhxLAbDw`, dispatch `ff8fa082-1c20-482b-bf59-1458d8c66d93`.
- Recovery completed at 14:11:15.811Z and was observed at 14:11:34.069Z.
- Both assignments selected maximum Astra, effort max. Provider acceptance remains not-proven.
- Recovery was read-only discovery, not review4, gate reruns or a substitute acceptance verdict.

The recovery inspected 48 retained command receipts with exact commands, cwd, exits, logs and PID records.
There were 32 exit0 receipts and 16 exit1 receipts. Thirteen exit1 receipts were clean no-index addition checks.
The other three were failing diagnostic assertions: `http-current`, `http-confirmed` and `read-close-identity`.
Inline reproduction commands are preserved inside JSON receipts and were inspected without execution during recovery.

### Retained results, not new recovery gate runs

The complete GP run passed 2,636 tests with 99.98% coverage and all static constituents.
Contract passed 59, GA passed 4 and focused repair/filesystem suites passed 1,150.
Integration retained one pass and the P33-owned CLI skip. Web check had zero errors and warnings.
Web unit tests passed 1,645, e2e passed 245 and npm regressions passed 7.
Docs tests passed 12. The strict docs build rendered 50 pages with valid links.
G0 and the seven-document links passed. Both radon outputs were empty.
All 67 retained screenshots matched, and 441 web/docs files were unchanged since review1.
These results cannot override the diagnostic defect or missing terminal review verdict.

### Remaining read-close defect

`src/huron/core/storage/posix.py:67–78`, `PosixStorage.read_bytes`, closes its descriptor unconditionally in `finally`.
A close error can replace an active read error or interruption. `_parent` then maps the secondary `OSError`.
Repair reads existing metadata through `core/storage/directories.py:72–82` and reports the resulting error through `core/storage/repair.py:157–159`.

Retained HTTP controls injected read EIO followed by close ENOSPC in default and rooted organizations.
Both reported the metadata path but the secondary close detail, rather than the primary read detail.
Direct controls also showed masking of `CancelledError`, `KeyboardInterrupt`, `SystemExit` and `GeneratorExit`.
The primary object was absent from the explicit cause chain. This does not assert that implicit exception context was absent.
Metadata bytes and inode remained intact, and retry succeeded. No data loss or descriptor leak was observed in those controls.

The method is identical in HEAD, pre-fix3, pre-fix4, fix4-final and review3-initial snapshots.
Its extracted SHA-256 is `cea837b56b6beaa67e813f63217e325adb4fcceef0fdfab83ad5a3c6583b879f`.
This is a fixable inherited implementation/test defect, not a fix4 regression or a production-plan design defect.
See `http-confirmed.log`, `http-read-baseline-confirmed.log`, `read-close-diagnostic.log` and `read-close-identity.log` with their JSON commands.

A separately authorized correction must preserve primary read errno, message, path and causal identity.
Ordinary close failures must remain secondary diagnostics. Active interruptions must survive ordinary cleanup failures.
New cleanup interruptions and sole close failures must still propagate. Tests need direct storage and default/rooted HTTP coverage,
byte/inode preservation, retry and descriptor ownership. This recovery made no such correction.

### Recovery preservation and shutdown

At 14:05:01Z, all 949 file hashes and 99 status entries matched review3-initial and fix4-final snapshots exactly.
Working/staged diffs, references, protected blobs and seven retained prototype hashes matched. No ownership was reassigned.
All 48 recorded command PIDs were absent. No gate-owned harness/browser residual was identified.

The interrupted reviewer had left the assigned PostgreSQL container running.
Recovery verified its exact identity and read-only database/activity inventory twice, with no other client backend.
It stopped only that container at 14:05:02.069489782Z, leaving PID0 and exit0.
The container, volume, default databases and `huron_test_bdfdfe352c31` remain preserved.
All six assigned ports were free. Developer services, unrelated browsers and the retained prototype were untouched.

Review3 lacked final preservation, shutdown and process-reconciliation receipts as well as its terminal report.
Recovery supplies current preservation/resource evidence, not a retroactive review verdict.
Any further correction and qualification require explicit bounded authorization and review-count reconciliation.
There is no automatic child resume, prompt replay, count reset or fourth review.
