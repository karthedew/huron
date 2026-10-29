# Phase dispatch-concurrency: durable activity-aware dispatch

Status: verified — independent implementation review attempt 2 PASS;
activation requires quitting and restarting OpenCode. Current runtime remains serial.

## Context and outcome

### Final orchestrator acceptance — 2026-10-05

T1 is independently verified, not merely self-checked. Fix worker
`ses_ef5dddd86ffeHLMBPxd2ZlxgVl` (about 03:36–03:40 UTC) corrected R1 and
reproduced all 18 confidentiality failure cases before its green run. Fresh reviewer
`ses_ef5d8c796ffewBKlmQUCaDfRYs` (about 03:41–03:44 UTC) returned PASS on
implementation review 2 of 3, with R1 resolved and no remaining findings.

The reviewer independently inspected all 25 assigned paths and reran every gate:
all exit 0; 55 tests (37 top-level), no failures/skips/cancellations/todo;
strict TypeScript/assets, strict documentation build, safe resolved agent/config
checks, ignored artifacts and whitespace/link checks passed. Node 22.23.2 and
npm 10.9.8. No live-model concurrency smoke or product MVP acceptance was claimed.

All dispatched workers have returned terminal responses. Preserve the extensive
pre-existing tree and all review receipts below. No commits or sudo were used.
Next action is a user-controlled OpenCode quit/restart; inspect the actual loaded
activity/claims schema afterward before dispatching concurrent independent work.
Historical pending statuses below record earlier stages, not the current verdict.

Current `.agents/plugins/implementation.ts` exposes
`implementation_start(role,title,prompt)` and `implementation_status(sessionID?)`.
Role is implementation/fix/verification; planning and code both use implementation.
All nonterminal direct children block starts; a closure-local Set prevents only
same-instance concurrent start races. The snapshot only shows latest-message text
and tools. Eleven dispatch tests and four asset tests exist (15 total).

User decision: actual code implementation/fix is EXCLUSIVE against all workers,
reviews and competing checks. Independent non-code discovery/planning/isolated
throwaway prototypes/reviews may overlap with no read/write resource conflicts.
Review never races its subject writer. Keep Astra Low, no nested delegation, no
Task/second server, direct-child-only visibility, errors-not-PASS, minute polling,
15-minute progress and maximum three reviews. Prompt text is not permission.

This file is a self-contained future tooling phase. No live changes are authorized
by the planning assignment. Runtime remains blanket-serial until implementation,
independent verification and quitting/restarting OpenCode. No broader permissions,
new models or agents. One coordinating main session and one existing local server
are rollout prerequisites; all workflow starts go through the plugin. Parent/manual
resumes and outside edits/checks must not race admitted work. This is cooperative
coordination, not an OS sandbox or distributed multi-host scheduler.

## Prototype evidence

From root `/home/karl/repo/huron`:

```sh
/home/karl/.nvm/versions/node/v22.23.2/bin/node --test roadmap/prototypes/dispatch-concurrency/probe.mjs
```

Writer observed 10 passing scenarios (0 fail/skip), after fixing an isolated ESM-only
SDK import. Installed SDK/plugin 1.17.18 and Node v22.23.2. Probe uses real SDK at a
simulated HTTP external boundary, real filesystem exclusive-create/fsync/rename,
fresh directories and a separate Node lock-holder process; no model/server calls.
It covers non-code overlap, code/legacy exclusion in both orders, resource conflicts,
two-instance race, recreation, unknown children, create/dispatch/status uncertainty,
latest-response terminal rules, resumed user turns, bounded cross-message progress,
direct-child isolation, nested denial, malformed claims and corrupt journal.

Limitations: not live server durability/compaction/enumeration completeness, all
production schema validation or symlink hardening, agent compliance, permissions,
power-loss portability or surviving-process detection. Product must independently
implement the following contract and test real filesystem behavior; do not import
prototype code or make tracked tests depend on ignored roadmap files. Preserve
existing model/permissions/asset tests. Essential SDK examples appear below.

## Exact scope and ownership

Future exclusive writer owns only these changes, preserving all pre-existing dirty
work within and outside them (baseline first, no wholesale replacements):

| Path | Exact symbols/sections to change |
| --- | --- |
| `.agents/plugins/implementation.ts` | replace closure `launching` authority and serial child loop; `implementation_start` schema/execute, `snapshot`, status list projection; preserve config/chat.params hooks |
| `.agents/plugins/dispatch-state.ts` (new) | `DispatchClaim`, `DispatchRecord`, `normalizeDispatch`, `claimsConflict`, `DispatchJournal.withAdmission`, `readRecords`, `saveRecords`; strict validation and real filesystem ownership only |
| `.agents/tests/implementation.test.js` | extend `setup` HTTP fixture for unique child IDs/per-child histories, list and multiple parents/instances, temp worktree; existing 11 behaviors and new matrix |
| `.agents/tests/dispatch-state.test.js` (new) | public normalization/conflict/journal behavior and real filesystem/subprocess crash/locking tests |
| `.agents/tests/assets.test.js` | retain all four tests; add registration/document contract assertions through existing helpers |
| `.agents/scripts/check-assets.mjs` | focused activity/claims/progress/reference consistency checks, no ignored-plan dependency |
| `.agents/.gitignore` | add `.dispatch-state/` only |
| `.agents/README.md` | Polling/API, recovery, validation and restart documentation |
| `.agents/prompts/orchestrator.md` | activity/claims, resource dictionary, exclusive code, overlap eligibility, monitoring |
| `.agents/prompts/implementer.md`, `.agents/prompts/reviewer.md` | enforce declared ownership, no classification escalation/resume, shared check-output claims |
| `.agents/workflows/orchestration.md` | replace role-conflated table/blanket serialization with role+activity table and admission/recovery rules; keep verbatim progress contract |
| `.agents/workflows/implement-markdown.md` | keep serial writer→subject review→fix dependency; allow unrelated non-code scopes only after claims/gates resolved |
| `.agents/workflows/verification.md` | require check artifact/service claims and concurrent-monitor evidence, unchanged gate thresholds |
| `.agents/commands/implement-markdown.md` | replace unconditional serial-delegation wording with exclusive-code/conflict-aware policy |
| `.agents/templates/assignment.md` | activity, canonical resource dictionary/claims, subject ownership and progress fields |
| `.agents/templates/design-plan.md`, `.agents/templates/prototype.md`, `.agents/templates/phase-plan.md` | add classification/resource/check-output/recovery requirements; clarify per-subject serial review |
| `.agents/skills/design-plan/SKILL.md`, `.agents/skills/prototype/SKILL.md`, `.agents/skills/implementation-plan/SKILL.md`, `.agents/skills/implement-markdown/SKILL.md` | role/activity examples, isolated prototype conditions, per-subject sequencing (not blanket serialization) |
| `.agents/skills/playwright-cli/references/session-management.md` | lines 22–23: browser names do not authorize overlap; require dispatched claims/service ownership rather than claiming blanket-serial contract |
| `AGENTS.md` | Lifecycle and delegation paragraph: exclusive actual-code policy, non-code claim checks, actual loaded runtime/restart qualification |

No `opencode.json`, permissions, provider/model, package dependencies/versions,
application, web, domain, public design or legacy roadmap edits. No files deleted.
Existing four lifecycle command bodies except implement-markdown need no changes:
they defer to workflows and do not assert serialization. Existing check-resolved
script remains unchanged and required. No home/global assets or unknown data cleanup.

Explicit compatibility exceptions: callers omitting BOTH new arguments are
`legacy-exclusive` regardless of role; keep old status `text` and `tools` as actual
last-message projections, removing tool titles to avoid argument leakage. New callers
use explicit classification; unknown fields/activity/partial claims reject rather
than silently downgrade. No other shim or role inference from assignment prose.

Obsolete behavior: unconditional exclusion of correctly classified independent
non-code children and memory-only admission ownership. Replace assertions requiring
that exclusion with the stronger conflict/code/unknown-state matrix. Do not delete
the safety behind existing serial-race, reload, idle, retry or error tests.

## Interfaces and implementation examples

Future tool schema (NOT AVAILABLE IN THE CURRENT LOADED RUNTIME):

```ts
type Role = 'implementation' | 'fix' | 'verification';
type Activity = 'code' | 'discovery' | 'planning' | 'prototype' | 'review';
type DispatchClaim = { resource: string; mode: 'read' | 'write' };
// Existing required role/title/prompt unchanged. New args optional only as a pair.
implementation_start({ role, title, prompt,
  activity?: Activity, claims?: DispatchClaim[] });
implementation_status({ sessionID?: string });
```

Use `tool.schema` (Zod exposed by installed plugin) and explicit execute-time
normalization for semantic validation and direct execute test coverage. Trim title
and reject blank prompt/title. Explicit claims length 1–32, unique canonical names,
regex `^(\*|[a-z][a-z0-9:._-]{0,95})$`, modes read/write; reject unknown object keys.
Omitted activity+claims → internal `legacy-exclusive`, claims `*:write`.
Reject one without the other, duplicate labels, unknown enums or invalid names.
Discovery/review require verification role; code/planning/prototype require
implementation or fix. Verification may have write claims for ignored build outputs,
but is still forbidden to edit source. Role controls agent permissions, activity
controls scheduling; neither grants permission to violate the assignment.

Examples of future normalized calls:

```js
{ role: 'implementation', activity: 'planning', title: 'Dispatch plan', prompt,
  claims: [{ resource: 'repo-context', mode: 'read' },
           { resource: 'plan:dispatch', mode: 'write' }] }
{ role: 'verification', activity: 'review', title: 'Other plan review', prompt,
  claims: [{ resource: 'repo-context', mode: 'read' },
           { resource: 'plan:other', mode: 'read' }] }
{ role: 'fix', activity: 'code', title: 'Fix plugin', prompt,
  claims: [{ resource: 'agent-tools', mode: 'write' }] } // exclusive with ALL
```

Parent maintains one dictionary mapping exact labels to actual file/service/artifact
ownership. `plan:dispatch` and `plan:other` must be disjoint; subject review uses the
same label as its writer. Shared `build:agent-tools` is write for every npm-test run.
Path globs, prefix relationships or aliases are NOT enforced by labels; never say
they are. If independence cannot be established, claim `*:write` or use `code`.
Code is exclusive even if its claims happen to be disjoint/read-only. Prototype
classification requires only owned ignored throwaway paths and isolated resources;
live config/code/service mutation is code, not prototype.

### Journal and admission algorithm

Create `DispatchJournal` under `realpath(worktree)/.agents/.dispatch-state`, private
0700 directories/0600 files. Reject symlinked state roots/components/files, wrong
worktree/version and invalid journal shape; never follow caller-supplied paths.
State consists of versioned ledger and `admission.lock`; temp files have invocation
unique names and are not cleanup targets of other invocations. Persist lock owner
token and start timestamp; token, not age or PID, identifies the releasable lock.

Record: `{version:1,dispatchID,worktree,parentID,childID?,role,activity,claims,
createdAt,state:'creating'|'dispatching'|'submitted'}`. ID generated locally before
reservation; valid canonical UUID or equivalently validated collision-resistant ID,
not interpolated user path. Strictly validate every record and allowed field/state
combination; duplicate dispatch/child IDs block. Store no prompt, tool data or secrets.
Keep completed records for resumed-turn reconciliation, no automatic garbage collection.

1. Validate arguments/caller (`markdown-orchestrator` only), canonical root and model
   settings before side effects. Preserve current configured agent/provider checks
   and Astra Low chat.params enforcement; no model substitution.
2. Atomically acquire worktree-wide lock via `open('wx')`. EEXIST returns a safe
   admission-busy error immediately. No queue/lease/force unlock. Recheck current
   state under lock. Use bounded SDK requests (`signal: AbortSignal.timeout(30000)`
   supported by installed RequestOptions extending Config/RequestInit) so ordinary network hangs return
   uncertainty, while progress polling is never held hostage to a child finishing.
3. Read journal; reconcile current and every recorded parent's `session.children`,
   plus `session.list` as an additional unknown-child discovery source. Fetch status
   and actual messages for all recorded child IDs, even if not listed as active.
   Missing/deleted recorded child/API failure/corruption blocks. List has no v1
   pagination contract, so never claim it proves arbitrary unregistered history.
4. Unknown active/indeterminate child blocks ALL starts. Unknown terminal child
   need not block, but error outcome requires parent process inspection. Incomplete
   create reservation blocks ALL starts. Dispatching record blocks ALL starts unless
   child is now terminal. Submitted known nonterminal holds its immutable claims;
   only non-conflicting classified non-code may overlap. Resumed terminal children
   reacquire original claims automatically on observation; never permanently mark done.
5. Persist reservation BEFORE create with fsync(file), atomic rename, fsync(directory).
   Crash artifacts/invalid records fail closed. Create child using injected client;
   persist childID+dispatching BEFORE prompt. Publish ID to `context.metadata`.
6. Prepend generated envelope text and assignment as separate text parts; on prompt
   acknowledgement persist submitted. Envelope includes exact record classification
   and identity, no assignment copies/secrets. It is audit, not authority. A missing
   journal cannot be silently rebuilt from untrusted text. No invented API metadata.
7. Ambiguous create returns dispatch ID and `creation-indeterminate` (child may be
   unknown); ambiguous prompt returns known session ID and `dispatch-indeterminate`.
   Save failure after remote I/O is uncertainty too. Never retry remote create/prompt
   automatically. Release only current token's lock in normal finally; failure to
   release remains blocked. No automatic deletion/reset of unknown records/artifacts.

Real SDK payloads (v1 installed declarations inspected):

```ts
const session = await client.session.create({ query: { directory },
  body: { parentID: context.sessionID, title: args.title }, throwOnError: true });
await client.session.promptAsync({ path: { id: session.data.id },
  query: { directory }, throwOnError: true,
  body: { agent, model: { providerID: 'openai', modelID: 'gpt-6-astra' },
    parts: [{ type: 'text', text: envelope }, { type: 'text', text: args.prompt }] } });
```

Successful result extends current fields with dispatchID/activity/claims. Rejected
admission creates zero sessions. Journal lives outside git but is runtime data,
not disposable build output. Stale lock/incomplete create maintenance requires
explicit human authorization, evidence the old invocation and processes stopped,
and child reconciliation. No automatic TTL, PID-based stealing, abort/delete or
recovery tool in this phase. Quiescent regular plugin recreation is automatic:
read journal and live children, do not depend on a closure Set.

### Snapshot contract

Retain actual-last-response terminal logic separately from progress extraction:
idle AND completed assistant AND stop/error. User/no response/tool-calls/length/
busy/retry is not terminal. Error is a name, not PASS; no raw error data. Parent
must inspect residual processes before replacement, including after terminal errors.
Existing `text`/`tools` continue to reflect only actual last assistant, without tool
titles/inputs/output/reasoning. Add latest meaningful `progress` from last 100 messages
(4,000 chars maximum, timestamp/message ID/truncated flag) and `recentTools` (20
maximum, message/part IDs, name/status/start/end only). Include observedAt/window
and explicit null when none found; do not fabricate freshness. Empty tool/user turn
retains earlier progress but cannot inherit terminal truth. Read-only list and status
are limited to caller's direct children; add validated ownership/state summary or
`unknown`. Do not leak other parents' identities/claims in admission errors.
Assistant text remains sensitive; never promise arbitrary secret redaction. Assignments
must forbid credentials in progress. Raw tool titles and retry messages are omitted
because they can contain secrets. Return retry type/count/next timestamp only.

## Serial task slices

### T1 — one exclusive implementation and independent review (pending)

Input: this full phase, independently accepted design/prototype, green untouched
tooling/docs baseline, initial ownership receipt. Objective/output: complete
activity-aware plugin plus documentation and regression coverage in exact owned
paths above. Implement journal + plugin + tests first, reconcile docs/prompts/templates
and asset checks in the same slice; no half-cutover usable state. Remove only obsolete
blanket exclusion assertions, retaining safety cases below. No concurrent worker or
reviewer during actual implementation/fixes, even if claims differ.

Use current serial dispatch for this rollout. Writer runs the full gate below;
fresh independent reviewer reruns it and inspects all acceptance. Review/fix max
three reviews; same subject sequence is always writer terminal → review terminal →
fix terminal → fresh review. Independent unrelated non-code concurrency is a future
runtime feature, not authority for overlapping this cutover. Findings route back to
owned fix or design, never auto-reset unknown work or manufacture PASS.

## Skills

Required for writer and reviewer: built-in `customize-opencode` (official schema
<https://opencode.ai/config.json>, plugin and server docs, installed 1.17.18 APIs),
`.agents/skills/implement-markdown/SKILL.md` and
`.agents/skills/implementation-plan/SKILL.md`. Read changed lifecycle skills fully:
`.agents/skills/design-plan/SKILL.md`, `.agents/skills/prototype/SKILL.md`.
For the browser-reference wording only, read
`.agents/skills/playwright-cli/SKILL.md` and its session-management reference; no
browser operation/UI analysis is assigned. Read AGENTS, tooling guide, all three
workflows and four templates. No Core/API/SQL/Svelte/Tailwind code changes, so those
area gates/skills are not applicable. No external/global skill copies.

## Acceptance and complete applicable gates

### Existing 15-test inventory and migration

1. Launch role/model: retain all three roles; extend to explicit activities, generated
   envelope + unchanged assignment and old-call exclusive default.
2. Poll text/tools privacy: retain observable last-message fields; remove title
   expectation in favor of no-title/no-secret assertion, add cross-message fields.
3. Idle/intermediate turns: retain all finishes/status assertions and exclusion for
   exclusive/unknown; independent known claims are not blanket rejected.
4. Dispatch uncertainty: retain discoverability/no duplicate; add recreation and
   independent-request blocking, create and journal-save uncertainty.
5. Serial launch/recreation: replace blanket serial name/assertion with exclusive-code
   and conflict exclusion across simultaneous instances/processes and reload.
6. Status error/unrelated isolation: retain, include journal/list/children errors.
7. Completed child vs resumed user: retain and reconcile original durable claims.
8. Retry/aborted response: retain visible error/retry but never verdict; redact raw data.
9. Bad model/config: retain zero-created-child assertion before reservation dispatch.
10. Nested/Astra Low only workflow: retain unchanged safety assertions.
11. Retired commands: preserve exact unrelated-command preservation.
12–15. Four asset tests: preserve local-only skills, references, command/agent registration,
   lock inventory and reviewer/worker permission protections; add new policy checks.

Extend existing `setup` rather than cloning live fixture setup. Per-child state and
unique IDs correct current fixture's one-child assumptions. Add parameterized activity
and claim-mode cases. Tests of public tool behavior must include all successful/error
outcomes, validated enums/partial/empty/glob/duplicate claims, conflict examples,
unknown legacy child, multiple parents, cross-instance simultaneous starts, after-create
lost response, after-prompt lost acknowledgement, no automatic retry, malformed/unknown
version journal, missing child, symlink path, crash-held lock and safe recovery refusal.
Real temp filesystem + subprocess proves lock ownership; deterministic barriers, not
sleeps, order races. Explicitly test active unknown other-parent child discovery and
recorded-parent direct enumeration. Test last-100/4,000-char/20-tool bounds, timestamps,
null/no-progress, resumed user, busy/retry, privacy and direct-child lists. No new test
depends on roadmap. Prototype never substitutes for live implementation tests.

Testing contract for every assignment: Before adding tests, find existing public-behavior
coverage, parametrization, scoped conftest/fixtures and helpers; reuse or extend them.
Discover fixtures with pytest `--fixtures`/`--fixtures-per-test` when unclear. Test changed
contracts, happy/error paths, boundaries, permissions, retries, concurrency and recovery
as applicable. Assert observable outcomes rather than private call sequences. Control
time/randomness, isolate mutable state, and mock only external I/O. Real filesystem and
PostgreSQL contracts prove durability/locking that fakes cannot. Frontend pure behavior/API
seams use Vitest; cross-route interactions use Playwright. Delete obsolete owned tests
instead of skipping them. Comments/docstrings/test names describe enduring behavior,
not plan phases. No suppressions, exclusions, skips, xfails, weakened assertions,
thresholds or contracts to manufacture a pass. Here Node fixture coverage is known;
pytest/PostgreSQL/frontend tools are not applicable to this tooling-only boundary.

### Complete future gate — baseline, writer, fixes and independent reviewers

Cwd `/home/karl/repo/huron`:

```sh
git diff --check
python roadmap/check_docs.py
make docs
git check-ignore -v roadmap/dispatch-concurrency-design.md roadmap/prototypes/dispatch-concurrency roadmap/plans/dispatch-concurrency.md
git ls-files roadmap
```

Cwd `/home/karl/repo/huron/.agents` (separate exact commands):

```sh
PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH node --version
PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH npm --version
PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH npm run check
PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH npm test
PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH node scripts/check-resolved.mjs
```

Post-implementation root also run `git check-ignore -v .agents/.dispatch-state/ledger.json`
and require the new ignore rule (not an untouched baseline requirement). Supported
engine range is `^22.22.2 || ^24.15.0 || >=26.0.0`; use v22.23.2 here. Locked deps already
present; if absent, stop/report and request authorized `npm ci --ignore-scripts` in
`.agents`, not global installs. `make docs` executes `uv run --group docs zensical
build --strict`; inspect baseline output and preserve dirty public docs. It is required
by this tooling phase even though planning-only gate does not run it.

Safe resolved inspection is EXACTLY `node scripts/check-resolved.mjs`: inspected script
runs `opencode debug config`, `opencode debug agent markdown-orchestrator`, corresponding
implementer/reviewer and `opencode debug skill` into private 0600 scratch, projects safe
assertions/summaries and removes only its own diagnostics. It has 60-second command
timeouts and makes no child/model calls. Do not dump raw config/provider credentials
or raw debug output. Preserve all existing model/permission/skill checks.

Pass criteria: every applicable command exit 0, no weakened thresholds/skip/xfail,
strict docs clean, all original safety behaviors plus new matrix green, no tracked
roadmap files, artifacts ignored, new text whitespace/local links checked, exact owned
diff reviewed. `git diff --check` omits ignored/new text: run root
`/home/karl/.nvm/versions/node/v22.23.2/bin/node roadmap/prototypes/dispatch-concurrency/check-owned.mjs`
for these planning files; future public asset whitespace/links use `npm run check`
and `python roadmap/check_docs.py` plus inspection of all new TS/test text. Baseline
failures/missing infrastructure are BLOCKED, not PASS; reviewer records exact commands,
versions, exit/output and old vs new failure attribution. Do not repair unowned defects.
No full Python/application/frontend gates apply; no paid live agent smoke is required
or authorized. Independent reviewer must rerun the complete gate, not copy receipts.

Progress contract (include verbatim in every assignment):

Every implementation, fix, and verification subagent must send a brief progress update at least every 15 minutes of elapsed time while its assignment remains active, including during validation. Send blockers, repeated failures, and suspected hangs immediately rather than waiting for the next interval. These are progress messages, not final implementation reports or verification verdicts. Keep each update to 2-4 short lines containing the phase/task, agent role and attempt number, elapsed time, concrete progress since the previous update, current operation or command, and the next step or blocker. If nothing has advanced, say so and identify the last observed activity; do not substitute 'still working' for evidence. Parent polls asynchronously at least once per minute.

## Blockers and readiness

Independent design/prototype review and untouched live tooling/docs baseline passed
in reviewer session `ses_ef6041902ffeLjT19n0Ss57Ppy` on 2026-10-05. The user's request
authorizes the exclusive implementation slice. No unresolved product/API choice is deferred
to a writer: exact labels, filesystem journal, conservative defaults and manual-only
ambiguous-state recovery are deliberate bounded decisions. If reviewer finds SDK/FS
assumptions invalid, return to design/prototype, not a silent implementation change.
Future API is unavailable until completed implementation and OpenCode quit/restart.
Any old active/unclassified children or indeterminate dispatch must settle before
rollout; never delete sessions or journal to evade exclusion.

## Execution ledger

| Task / role / attempt | Model | Child / times | Evidence / verdict | Review count / remaining |
| --- | --- | --- | --- | --- |
| Design + prototype + phase writer / implementation / 1 | inherited Astra Low | parent records actual child ID and polling times | own ignored dispatch paths only; self-check receipt in prototype evidence; READY-FOR-REVIEW only | 0; independent review/baseline pending |
| Independent plan/prototype review + live untouched baseline | Astra Low required | pending parent dispatch | pending | review 1 pending |
| T1 exclusive implementation | Astra Low required | pending authorization | pending | full gate pending |
| T1 independent review | Astra Low required | pending | pending | max 3 |

### Orchestrator receipt — 2026-10-05

- Planning/prototype writer `ses_ef612e9b4ffeiUD19aiGTiknzC`: launched about
  02:38 UTC, terminal observed 02:53 UTC; Astra Low; ten prototype tests passed.
- Independent design/prototype reviewer and untouched-baseline worker
  `ses_ef6041902ffeLjT19n0Ss57Ppy`: launched about 02:54 UTC, terminal observed
  02:59 UTC; Astra Low; review attempt 1 PASS, no findings.
- Reviewer independently reran all root/agent/prototype gates listed above:
  all exit 0, ten prototype tests and all fifteen existing tooling tests passed,
  no skips/cancellations. Node 22.23.2, npm 10.9.8, safe resolved checks passed.
- These receipts accept the plan and baseline only. Implementation review count
  remains zero; current runtime is still serial. Existing dirty work is preserved.
- The parent authorizes T1 under the user's explicit concurrency-change request;
  no additional permission request is required. Restart remains necessary after
  independently verified implementation.

### T1 independent review attempt 1 — FAIL

- Implementer `ses_ef5fe47f6ffeW99WQVa50taWmW` launched about 03:00 UTC;
  terminal observed 03:28 UTC. Self-check: 36 tests and complete gates green.
- Reviewer `ses_ef5e4658bffefLNgFfXlY9TKrY` launched about 03:28 UTC;
  terminal observed 03:34 UTC. Independently reran the full gate, all exit 0,
  36 tests passed, no skips. Verdict FAIL on privacy acceptance, not command failure.
- R1 HIGH: raw SDK exceptions escape launch preflight (`configuredAgent`) and
  polling/list (`snapshot`, `implementation_status.execute`). Reviewer reproduced
  synthetic private details escaping children/messages/status/agent/provider HTTP
  failures, including `Error.message` and `Error.cause.body`.
- Correction: fixed safe errors without original causes at these read/preflight
  boundaries; retain fail-closed zero-create preflight and remote-write uncertainty
  semantics. Test returned and thrown diagnostics for JSON/plain-text/transport
  failures at all five boundaries. No other review findings reported.
- Parent authorizes the bounded R1 fix. Review count: 1 of at most 3. Do not roll
  out or claim acceptance until independent re-review. Runtime remains serial.

### T1 exclusive implementer receipt — attempt 1, 2026-10-05

Writer self-check only, READY-FOR-INDEPENDENT-REVIEW, not independent PASS. Parent
retains the actual child ID and dispatch time. Work started after the recorded
02:59 UTC baseline; progress observed/reported through 03:19 UTC and full gate
completed subsequently. No children launched, no live model smoke, services, sudo,
commits, branches, permission/model/dependency changes or prototype promotion.
The loaded parent runtime remains serial; quit/restart is required after acceptance.

**Before/after ownership:** Initial `git status --short` and `git diff --stat` were
captured before editing in this worker's tool transcript: 242 tracked files changed,
1,451 insertions, 16,297 deletions, plus pre-existing untracked `.agents` assets,
`design/raw-first.md` and `src/huron/core/catalog/interface/`. All those unrelated
changes/deletions were preserved. Initial owned file contents were read in full.
AGENTS and prototype SKILL already had extensive tracked edits; the other existing
owned assets were untracked. Changes below are incremental against those initial
contents, not ownership claims over their whole Git diff. Only the two named new
files were created; no files were deleted. No product/Starlight/public design edits.

| Owned path | Incremental result |
| --- | --- |
| `.agents/plugins/implementation.ts` | Replaced closure-only blanket guard with durable admission, explicit classification, bounded requests/reconciliation, generated envelope and safe cross-message progress; retained model/config hooks |
| `.agents/plugins/dispatch-state.ts` | New production normalization/conflict rules and strict private filesystem journal/owner-token lock, independent of prototype code |
| `.agents/tests/implementation.test.js` | Extended existing SDK HTTP fixture with fresh worktrees/unique children/per-child histories/parents/failure hooks; preserved 11 safety tests and added contract matrix |
| `.agents/tests/dispatch-state.test.js` | New normalization and real filesystem/subprocess locking, corruption, symlink, mode and ownership tests |
| `.agents/tests/assets.test.js` | Preserved all four original tests; added dispatch documentation/registration regression |
| `.agents/scripts/check-assets.mjs` | Added activity/claims/recovery/progress consistency, canonical plugin registration and TS/JS/MJS whitespace checks |
| `.agents/.gitignore` | Added only `.dispatch-state/` |
| `.agents/README.md` | API, classification/claims, bounded safe progress, durable recovery, validation limits and prominent restart documentation |
| `.agents/prompts/orchestrator.md` | Explicit activity/claims dictionary, code exclusion, monitoring/recovery and restart |
| `.agents/prompts/implementer.md` | Declared ownership, no escalation/resume, isolated prototypes, output claims and progress confidentiality |
| `.agents/prompts/reviewer.md` | Same-subject sequencing, read-only limits, output claims and progress confidentiality |
| `.agents/workflows/orchestration.md` | Role/activity table, exact-label admission, durable recovery, bounded monitoring; verbatim progress contract preserved |
| `.agents/workflows/implement-markdown.md` | Exclusive code and per-subject writer/review/fix sequencing; only unrelated non-code scopes may overlap |
| `.agents/workflows/verification.md` | Complete subject/check-output/service claims and per-child monitoring evidence; thresholds unchanged |
| `.agents/commands/implement-markdown.md` | Conflict-aware asynchronous delegation and restart qualification |
| `.agents/templates/assignment.md` | Classification/resource dictionary/subject claims/progress/recovery fields |
| `.agents/templates/design-plan.md` | Classification/claims/check-output/recovery/restart requirements |
| `.agents/templates/prototype.md` | Isolated ignored prototype condition, classification/claims and serial subject review |
| `.agents/templates/phase-plan.md` | Classification/claims/check-output/recovery/monitoring and per-subject sequencing |
| `.agents/skills/design-plan/SKILL.md` | Role/activity examples and nonconflicting non-code policy |
| `.agents/skills/prototype/SKILL.md` | Isolated prototype versus exclusive live-code distinction and resource/recovery rules |
| `.agents/skills/implementation-plan/SKILL.md` | Role/activity examples, exact claims and phase/review coordination |
| `.agents/skills/implement-markdown/SKILL.md` | Exclusive code, per-subject sequencing, claims and restart/recovery |
| `.agents/skills/playwright-cli/references/session-management.md` | Browser names alone do not authorize overlap; dispatched claims and service/output ownership required |
| `AGENTS.md` | Only Lifecycle/delegation paragraph incrementally changed to exclusive-code/non-code-claims and actual-loaded-runtime qualification |

**Acceptance evidence:** Final Node run: 36 tests passed, 0 failed/cancelled/skipped/
todo (8,304.318463 ms). Original 15 safety behaviors retained; obsolete blanket guard
expectation replaced by stricter both-order code/legacy exclusion and cross-instance
admission. Tests cover all explicit activities/role compatibility, exact-label modes,
wildcard and no-prefix semantics, claim/name/count validation, durable recreation,
create/prompt lost acknowledgements and post-I/O save failure without replay,
cross-parent enumeration/privacy, missing child and API failures, resumed original
claims, missing-journal unknown ownership, and terminal dispatch reconciliation.
Progress tests exercise 100-message/4,000-character/20-tool bounds, timestamps/null,
empty and user turns, retry data and secret title/input/output/reasoning omission.
Real filesystem/subprocess tests exercise private permissions, persisted records,
strict corruption/version/worktree/state/duplicate validation, symlink rejection,
owner-token mismatch, deterministic IPC-handshaked lock contention and crash-held
lock refusal. Tests use fresh owned temporary worktrees under `/tmp/opencode/`;
no unknown state is cleaned. Fixture-only ledger deletion simulates loss, not recovery.

**Exact complete gate (all final exits 0):**

| Cwd | Command | Observed result |
| --- | --- | --- |
| root | `git diff --check` | No output |
| root | `python roadmap/check_docs.py` | PASS: local documentation links/fragments, no tracked ignored-plan links, owned/untracked text whitespace, 000–010 phase cross-references/skills and 10 product phase structures |
| root | `make docs` | `uv run --group docs zensical build --strict`; No issues found; build 0.21s |
| root | `git check-ignore -v roadmap/dispatch-concurrency-design.md roadmap/prototypes/dispatch-concurrency roadmap/plans/dispatch-concurrency.md` | All three matched `.gitignore:40:/roadmap/` |
| root | `git ls-files roadmap` | Empty |
| root | `git check-ignore -v .agents/.dispatch-state/ledger.json` | `.agents/.gitignore:4:.dispatch-state/` |
| root | `/home/karl/.nvm/versions/node/v22.23.2/bin/node roadmap/prototypes/dispatch-concurrency/check-owned.mjs` | Owned planning text: 5 files, whitespace/links/skills/phase sections OK |
| `.agents` | `PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH node --version` | v22.23.2 |
| `.agents` | `PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH npm --version` | 10.9.8 |
| `.agents` | `PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH npm run check` | Strict TypeScript clean; 11 canonical skills, four commands, templates/local references and new text checks OK |
| `.agents` | `PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH npm test` | 36/36 passed, no skips/cancellations/todo |
| `.agents` | `PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH node scripts/check-resolved.mjs` | Canonical lifecycle/default, retired commands absent, all three Astra Low prompts/permissions and 11 canonical local skills OK; no raw configs exposed |

Earlier writer-only feedback: first npm test exited 2 because TypeScript 6 did not
implicitly load already-installed Node declarations. Added an explicit node types
reference, no package/config or suppression change; rerun passed original 15 tests.
Expanded run passed 32 tests. First new asset check exited 1 on missing literal
activity wording in verification guidance; wording corrected, final check green.
These were implementation feedback failures, not baseline defects. No remaining
gate failure or missing infrastructure was observed; no thresholds were weakened.
Final self-inspection additionally tightened non-string persisted state rejection,
canonical lock timestamp validation and contradictory parent enumeration handling.
The added enumeration regression and persisted-state counterexample passed; the
complete gate was rerun after those final code edits. This remains self-inspection,
not an independent review verdict.

Limits: real SDK 1.17.18 at a simulated external HTTP boundary, not live server/model
durability/compaction or enumeration completeness. Local filesystem locks are not a
distributed/NFS scheduler or sandbox; resource labels require truthful coordination.
Parent/manual resumes and outside checks must not race admitted work. Assistant text
cannot promise arbitrary secret redaction. Power-loss portability and residual-process
detection remain explicit limits. Application/Core/DB/Svelte/browser gates do not apply.
Next: parent dispatches a fresh read-only independent T1 reviewer to inspect actual
changes and independently rerun the full gate; this self-check does not consume a
review attempt or establish independent PASS.

Parent records start/last-progress/current command, IDs, outcomes, findings, owned diff
and remaining work at dispatch; placeholders here are pending execution, not fabricated
evidence. See prototype evidence for actual writer commands and final planning gate.

## Escalation / final receipt

On FAIL/BLOCKED preserve all unknown and incomplete work. Fix owned findings serially,
fresh reviewer each time; stop after third failed review. No commits/branches/pushes,
issues, permission escalation, destructive cleanup or prototype promotion. Final
implementation receipt must list exact changed files/deletions, acceptance evidence,
full gate outcomes, baseline attribution, outstanding limits and required restart.
After acceptance parent may invoke
`/implement-markdown roadmap/plans/dispatch-concurrency.md`; not before review/baseline.
Independent PASS and implementation completion are not claimed by this planning handoff.

### T1 R1 fix self-check — attempt 1, 2026-10-05

READY-FOR-INDEPENDENT-REVIEW-2 only; this is not independent PASS. Review count
remains 1 of at most 3. Parent retains actual fix child ID/times. Loaded runtime
remains old serial schema; no rollout until fresh review and quit/restart.

**Finding and reproduction:** Reviewer `ses_ef5e4658bffefLNgFfXlY9TKrY` reported
R1 HIGH despite all 36 existing tests and full gates passing: raw SDK exceptions
escaped `configuredAgent` (original lines 69, 75, called at 151), `snapshot`
(13–16) and status execute (192–202). Failures on `/session/parent/children`,
`/session/child/message`, `/session/status`, `/agent`, `/config/providers` exposed
synthetic private details in `Error.message` and `Error.cause.body`, with JSON503
and plaintext503 responses. Reconcile already sanitized; no other findings or plan
defect were reported. Consulted official `https://opencode.ai/docs/sdk/` and installed
1.17.18 `dist/error-interceptor.js` and `dist/gen/client/client.gen.js`: HTTP bodies
are wrapped with message/cause, whereas fetch exceptions escape directly.

Extended the existing SDK HTTP fixture, not a cloned harness. Before the production
fix, `.agents` command `PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH npm test`
exited 1: all original 36 tests passed; all 18 new subtests failed the synthetic-secret
absence assertion (55 tests total, 36 pass, 19 fail including their parent test;
0 skipped/cancelled/todo, 5508.054462 ms). This intentional red reproduction confirms
the existing privacy defect, not a new baseline/infrastructure problem.

**Exact incremental ownership:** Initial `git status --short` (exit 0) captured
the extensive pre-existing tracked modifications/deletions and untracked assets.
Both target code/test files were already untracked T1 work. Preserved all prior T1
and unrelated contents; changed only:

- `.agents/plugins/implementation.ts`: added `safeRead` and applied it only to the
  five SDK read boundaries. Each rejection becomes a fixed boundary-specific Error
  with no original cause. Deliberate validation, direct-child restriction, admission,
  journal and post-write uncertainty/no-replay handling are unchanged.
- `.agents/tests/implementation.test.js`: extended `setup` failPath responses with
  JSON503/plaintext503/transport exceptions; added 18 parameterized subtests covering
  all five endpoints plus both children list/poll entry points. Inspect settled
  results with non-enumerable error fields and nested causes so returned or thrown
  diagnostics cannot conceal the synthetic marker. Require rejection, fixed message,
  absent cause, no additional POST/child and no preflight reservation. Strengthened
  existing model/config tests to retain deliberate validation messages.
- `roadmap/plans/dispatch-concurrency.md`: appended this ignored receipt only.

No dispatch-state changes, deletions, dependency/model/permission/config changes,
services, delegation, sudo, commits, branches, pushes or user-data cleanup. Examined
the full plugin and original tests plus every incremental hunk; new TS/test whitespace
is included in the existing asset gate. No threshold/assertion was weakened.

**Complete final gate:** All commands below exited 0. Root means
`/home/karl/repo/huron`; agents means `/home/karl/repo/huron/.agents`.

| Cwd | Exact command | Output/result |
| --- | --- | --- |
| root | `git diff --check` | No output |
| root | `python roadmap/check_docs.py` | PASS: local documentation links/fragments, no tracked ignored-plan links, owned/untracked text whitespace, 000–010 phase cross-references/skills and 10 product phase structures |
| root | `make docs` | `uv run --group docs zensical build --strict`; No issues found; build 0.30s |
| root | `git check-ignore -v roadmap/dispatch-concurrency-design.md roadmap/prototypes/dispatch-concurrency roadmap/plans/dispatch-concurrency.md` | All three match `.gitignore:40:/roadmap/` |
| root | `git ls-files roadmap` | Empty |
| root | `git check-ignore -v .agents/.dispatch-state/ledger.json` | `.agents/.gitignore:4:.dispatch-state/` |
| root | `/home/karl/.nvm/versions/node/v22.23.2/bin/node roadmap/prototypes/dispatch-concurrency/check-owned.mjs` | Owned planning text: 5 files, whitespace/links/skills/phase sections OK |
| agents | `PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH node --version` | v22.23.2 |
| agents | `PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH npm --version` | 10.9.8 |
| agents | `PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH npm run check` | Strict TypeScript clean; Agent assets: 11 canonical skills, four commands, templates and local references OK |
| agents | `PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH npm test` | 55/55 pass (37 top-level including 18 nested cases), 0 fail/cancelled/skipped/todo; 5513.190943 ms |
| agents | `PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH node scripts/check-resolved.mjs` | Canonical lifecycle/default and retired commands absent; all three workflow Astra Low prompts/permissions OK; all 11 skills canonical |

R1 is addressed by writer self-check evidence; independent review2 remains required.
No raw provider/debug configuration was printed. Real SDK with simulated external HTTP
and fresh filesystem fixtures, not live model/server acceptance. Existing filesystem,
concurrency, permissions, recovery and uncertainty regressions all remain passing.
Application/Core/API/DB/frontend gates do not apply. No missing infrastructure or
remaining self-check failure observed; assistant progress text is still sensitive,
and this fix does not promise arbitrary text redaction or change enumeration limits.
