# Phase: fixed Astra preparatory and maximum profiles

Status: blocked — source checkpoint qualified and committed; serving activation through canonical-skill launcher pending

## Context and outcome

Current `.agents/plugins/implementation.ts` exposes start/status, uses the original
SDK injected by plugin 1.17.18, and selects only two fixed Low child agents.
`configuredAgent`, `chat.params`, registration checks and returned launch effort all
force Low. `opencode.json` has three Astra Low agents, including the orchestrator.
The accepted concurrency implementation classifies activity/claims, serializes all
actual code against all workers/checks, reconciles durable records and preserves
indeterminate outcomes. Preserve those semantics exactly.

Outcome: one optional `profile: 'preparatory' | 'maximum'` argument. Omission means
maximum. Actual code implementation/fix always uses maximum; explicit preparatory
code and unclassified legacy requests reject. Preparation may explicitly use Low.
Final complete qualification is explicitly role verification/activity review/profile
maximum, not an ordinary preparatory review. No arbitrary model selector or new
scheduler. Model stays exactly `openai/gpt-6-astra`.

The current launcher cannot create a Max child. The user-authorized bootstrap is
parent-owned live edits only after independent plan/probe review; no Low actual-code
child is authorized. Subsequent actual-code children/fixes and complete qualification
must use the restarted maximum launcher. Existing Low receipts remain Low or unknown,
never relabeled. This tooling phase does not alter scientific domain contracts.

## Prototype evidence

Question: does fixed-agent selection avoid an unnecessary SDK migration? Installed
SDK 1.17.18 `SessionPromptAsyncData.body` includes agent/model/parts, not variant;
PluginInput.client uses this original SDK. Official schema permits agent variant and
options. The isolated probe typechecks the actual payload with locked TypeScript,
then uses the real SDK against injected HTTP for three roles × two profiles. Generated
enum schema and deliberate capability failures are exercised, plus v1 absence
projection. Reproduce from root on Node 22.23.2:

```sh
/home/karl/.nvm/versions/node/v22.23.2/bin/node --test roadmap/prototypes/effort-profile/probe.mjs
```

Six probe tests must pass; no model/server calls, production import, build output or
runtime state mutation. Mock fixtures prove API feasibility, not real registration,
provider Max acceptance, production durability or scheduler behavior. Historical
preservation is only a projection experiment; production tests must use real journal
files and existing lock/subprocess coverage. Never import prototype code into production.
Writer observed 6 passed, 0 failed, 0 skipped, exit 0 (about 0.52 seconds including
the no-emit typecheck); independent reproduction is pending.
Parent's prior discovery reports actual CLI 1.18.34 registration
`variants.max.reasoningEffort === 'max'` and untouched 55-test baseline passing, but
registration is not paid Max dispatch. Recheck it safely during the live full gate.

## Exact scope and ownership

Initial tree is extensively dirty: tooling lifecycle/concurrency work, removed legacy
assets, application/design/docs changes and untracked catalog interface scaffolding.
Preserve all baseline work. Writer inspected `git status --short`/`git diff --stat`
before adding only these ignored planning/probe files. No runtime journal inspection
or mutation was needed. Before bootstrap capture fresh status plus owned-file hashes
and compare against that pre-edit state, not repository HEAD alone.

Exact future live edit allowlist (no wildcard authorization):

| File | Symbols / purpose |
| --- | --- |
| `opencode.json` | Add markdown-implementer-max and markdown-reviewer-max; remove command description's blanket Low claim; retain original three Low settings, prompt paths and permissions |
| `.agents/plugins/dispatch-state.ts` | Profile type; normalizeDispatch; discriminated DispatchRecord v1/v2; validateRecords only; preserve claimsConflict and all journal locking/fsync/recovery algorithms |
| `.agents/plugins/implementation.ts` | Fixed agent/effort mapping, configuredAgent, chat.params, start schema/execute/metadata/receipts/envelope, ownership/status projection |
| `.agents/tests/implementation.test.js` | Existing setup/classified/terminal helpers and public start/status/hook scenarios |
| `.agents/tests/dispatch-state.test.js` | Existing setup/real-journal scenarios and profile/version matrix |
| `.agents/tests/assets.test.js` | Existing registrationIssues/dispatchIssues mutation tests |
| `.agents/scripts/check-assets.mjs` | registrationIssues/dispatchIssues: exact five-agent settings, counterpart prompt/permission parity and truthful profile contracts |
| `.agents/scripts/check-resolved.mjs` | Resolve five agents, compare full counterpart permission rules and prompts, safely assert registered variants and print only allowlisted registration fields |
| `.agents/README.md` | Tool signature, profile policy, version/receipt limits, restart instructions |
| `.agents/workflows/orchestration.md` | Profile dispatch table, default, code/final qualification rules |
| `.agents/workflows/implement-markdown.md` | Explicit maximum actual code/fix and final complete review |
| `.agents/workflows/verification.md` | Complete qualification explicitly maximum; distinguish configured from observed |
| `.agents/prompts/orchestrator.md` | Explicit profile choice and Max-only code/final qualification |
| `.agents/prompts/implementer.md` | Honor recorded profile; stop if Low assigned actual code |
| `.agents/prompts/reviewer.md` | Do not claim complete qualification from preparatory review |
| `.agents/templates/assignment.md` | Requested/recorded profile, configured effort, observed model, acceptance-not-proven fields |
| `.agents/templates/phase-plan.md` | Model/profile ledger and final complete qualification requirement only; do not rename headings |
| `.agents/templates/design-plan.md` | Preparation vs future maximum implementation planning |
| `.agents/templates/prototype.md` | Explicit preparatory/maximum evidence and limits |
| `.agents/skills/design-plan/SKILL.md` | Explicit preparatory planning/review option, code remains maximum |
| `.agents/skills/prototype/SKILL.md` | Profile choice never authorizes live Low code |
| `.agents/skills/implementation-plan/SKILL.md` | Resolve profile, maximum code/final gate in phase contracts |
| `.agents/skills/implement-markdown/SKILL.md` | Maximum code/fix and final complete qualification |
| `.agents/commands/implement-markdown.md` | State maximum code/final complete qualification |
| `AGENTS.md` | One lifecycle policy statement matching profiles, no unrelated edits |

No new live files, dependencies or abstractions required. No file deletions. Replace
obsolete blanket-Low assertions/descriptions with exact per-agent checks; do not
remove existing scheduling/privacy/permission/recovery tests. No edits to package or
lock files, global configuration, `.agents/.dispatch-state/`, source applications,
design/site docs, Starlight migration, local docs checker or unrelated phase plans.
Explicit compatibility exception: read/preserve historically valid v1 records only;
no behavioral shim for old Low callers (omitted profile now maximum).

Canonical resource dictionary for future dispatches:

- `source:repo`: read-only entire existing repository source/config/docs for context.
- `source:effort-profile`: precisely the live edit allowlist above, writer write/reviewer read.
- `plan:effort-profile`: this plan and `roadmap/effort-profile-design.md`.
- `prototype:effort-profile`: `roadmap/prototypes/effort-profile/` only.
- `build:agent-tools`: `.agents/.test-build/` plus invocation-owned existing agent-test
  temporary worktrees under `/tmp/opencode/dispatch-test-*`, `journal-test-*`,
  `symlink-test-*`, `symlink-target-*`; include write on every npm-test/resolved rerun.
- `build:docs`: `site/` and `.cache/` generated by the existing strict docs build.
- `cache:uv`: the resolved uv cache used by `make docs`; parent must establish its
  exact path before dispatch (or set an owned isolated UV_CACHE_DIR in assignment).
- `env:python`: root `.venv/` if the locked uv docs invocation synchronizes it;
  parent must include write ownership or establish that no synchronization occurs.

Actual code is globally exclusive regardless of labels. Reviews follow writers
terminally, never race checks; non-code overlap requires nonconflicting complete
claims. Claims are cooperative coordination, not a sandbox. Parent owns resource
reconciliation, no manual resumes or automatic replay. Current planning worker may
write only ignored plan/prototype paths, not this future live allowlist.

## Interfaces and implementation examples

### Input normalization and fixed mapping

Extend generated args with
`profile: tool.schema.enum(['preparatory', 'maximum']).optional()`.
`normalizeDispatch(unknown)` additionally allowlists profile and returns a required
profile on every new request. Only absent/undefined defaults; null, empty, aliases,
whitespace, objects and unknown keys reject. Keep existing role/activity/claims
validation unchanged. Run normalization before `DispatchJournal.at`, capability
reads, reservation or create. If normalized activity is code OR legacy-exclusive,
preparatory rejects (legacy activity is normalized internally, not a new input enum).

| Role | Preparatory | Maximum |
| --- | --- | --- |
| implementation / fix | markdown-implementer / low | markdown-implementer-max / max |
| verification | markdown-reviewer / low | markdown-reviewer-max / max |

Use a small fixed map in implementation.ts, not a new module/class. Include the
orchestrator as fixed Low in chat.params. No user-supplied agent/model/effort fields.
New agent config mirrors existing counterpart mode/prompt/permissions exactly:

```json
{"mode":"subagent","model":"openai/gpt-6-astra","variant":"max",
 "options":{"reasoningEffort":"max"},
 "prompt":"{file:./.agents/prompts/implementer.md}",
 "permission":{"task":"deny","implementation_start":"deny"}}
```

Reviewer Max instead shares reviewer prompt and adds the existing `edit: deny`.
Do not widen any rule or change canonical skill allowlist. Exact five known names
only; unknown markdown names must not acquire an implicit effort policy.

### Capability and payload

`configuredAgent(role, profile)` uses existing injected client and request timeout,
checks selected agent identity/model/subagent mode/variant/options effort and actual
registered Astra selected variant mapping before reservation/create. Require
`variants[effort].reasoningEffort === effort` and disabled absent or false. Missing,
disabled, malformed or mismatched values fail closed with safe diagnostics, no fallback.
Original SDK Agent/Model declarations omit variant/variants: treat API values as
unknown and narrow object/string/boolean fields locally; do not use `any`, unchecked
casts, a v2 client, guessed server URL or untyped prompt variant injection. If the
actual endpoint lacks capability fields, stop for design reconciliation, not bypass.

```ts
// Proposed payload; original SDK supports these exact fields.
await client.session.promptAsync({ ...request(), path: { id: record.childID },
  body: { agent, model: { providerID: 'openai', modelID: 'gpt-6-astra' },
    parts: [{ type: 'text', text: envelope }, { type: 'text', text: normalized.prompt }] }
});
```

chat.params rejects a wrong model/provider for each of the five fixed names and
sets exactly that name's effort (`low` or `max`), overriding an incoming downgrade
or upgrade. Unrelated agents remain unchanged. Runtime registration preflight must
not claim successful provider acceptance. Keep all safeRead redaction and timeouts.

### Record schema, historical preservation and uncertainty

Keep ledger container `{version:1, worktree, records}`. Use discriminated records:

```ts
type Profile = 'preparatory' | 'maximum';
// Base is the existing identity/classification/time/state fields, unchanged.
type DispatchRecord = (Base & { version: 1; profile?: never })
  | (Base & { version: 2; profile: Profile });
```

New reservations ALWAYS version 2 with normalized required profile. Envelope marker
is `HURON_DISPATCH_V2` and contains that record in dispatching state. It is context,
never authority for reconstructing ownership. Record version 1 must have no profile
key; accept only previously valid v1 shapes and original activity/claims. Historical
v1 code records stay valid without profile. Record v2 requires profile; reject missing,
invalid, extra keys and preparatory code/legacy. Unknown ledger/record versions or
corrupt artifacts reject without repair/deletion. Separate new-request defaulting
from persisted validation; never run a historical record through profile-defaulting.

Reads/status do not write anything. Appending v2 may serialize the existing ledger
under its original admission lock; existing v1 record field values/absence must be
deep-equal before/after (no synthetic profile, model or effort). Do not demand entire
ledger byte equality when appending; rejection/status paths must preserve bytes.
No runtime migration command. Old readers reject v2, so quiesce all invocations and
restart before first v2 dispatch; no mixed old/new launcher operation or silent rollback.

Keep creating → dispatching → submitted persistence timing, identity checks, locks,
fsync, conflict logic and terminal evidence unchanged. Persist profile in creating
before remote create; retain it through lost create response, lost prompt response,
save-after-I/O failure and ordinary recreation. Return selection even for ambiguous
creation/dispatch; it describes requested/configured execution, not completed work.
Never replay/create replacement automatically; parent reconciles existing children,
owned processes and journal uncertainty with explicit human maintenance authorization.

### Safe receipts/status

Replace ambiguous launch `reasoningEffort` reporting with nested
`configured: {profile, agent, model: 'openai/gpt-6-astra', reasoningEffort: 'low'|'max'}`.
Both successful and indeterminate launch receipts include configured plus
`providerAcceptance: 'not-proven'`, dispatch ID and known child ID; retain existing
activity/claims/state on success. Metadata adds profile (safe fixed value), not prompts.
No successful receipt until submitted is persisted.

Ownership projections keep dispatchID/activity/claims/state and add
`profile: 'preparatory'|'maximum'|'not-recorded'`, plus configured object for v2 or
null for v1. This is the immutable recorded selection, not a fresh configuration
attestation; derive the fixed agent/effort from validated role/profile. Unknown
ownership remains literal `unknown`, never reconstructed from envelope, name or
current config. List/status remain direct-child-only.

Keep snapshot's existing `model` as observed assistant provider/model, separate from
configured; absent assistant evidence remains absent. Add `providerAcceptance:
'not-proven'` to status: assistant model identity/terminal stop is not evidence of
reasoning effort. Do not invent observed effort or expose options/config/provider
objects. Existing progress/tool bounds/redaction and terminal rules are unchanged.
Operator smoke receipts may describe accepted completed Max-configured dispatch;
never claim measurable internal reasoning intensity without provider evidence.

## Serial task slices

1. **Prerequisites / baseline (pending).** Parent obtains independent plan/probe
   review using verification/review/preparatory (current Low tool), exact plan/probe
   read claims and no live writes. Complete missing full baseline commands below
   before live edits; prior agent-only baseline is useful evidence, not docs PASS.
   Record Node/CLI versions and safe model-registration projection. Resolve output
   claims and ownership before dispatch. Max bootstrap impossibility is an explicit
   parent exception, not authorization for a Low code child.
2. **Narrow coherent bootstrap (pending).** Parent, after all workers terminal and
   authorized reconciliation, exclusively edits only the live allowlist. Implement
   profile normalization/fixed config/record validation/receipts/tests/contracts as
   one coherent slice; no promotion of probe implementation. Run every static and
   deterministic applicable gate below. Objective: all acceptance except restarted
   real dispatch, with no scheduling/permission regression. No Low code children.
3. **Restart and actual Max dispatch smoke (pending).** Preserve private journal;
   quiesce parent invocations/children/processes, quit and restart OpenCode once.
   Confirm actual loaded start schema includes profile; safe resolved checks must
   show five configured agents and real max mapping. Parent uses existing tool,
   not direct SDK/second server, for verification/review/maximum smoke with a tiny
   read-only assignment and source read claim. Record returned configured selection,
   child/dispatch ID, observed Astra model and terminal evidence. Max provider error
   blocks; no fallback or automatic replay. Smoke is not full qualification.
4. **Independent complete qualification (pending, review 1 of at most 3).** After
   bootstrap/smoke terminally complete, dispatch fresh verification/review with
   explicit maximum, source:effort-profile and plan/prototype read plus all complete
   output write claims. Independently inspect actual changes and rerun every gate,
   preserving all configured thresholds. On findings, a maximum fix/code worker
   follows terminally, reruns full gate, then a fresh maximum reviewer (max 3 total).
   If launcher is broken before Max can run, stop for parent reconciliation; never
   delegate a Low fix. Final receipt requires acceptance and full green review.

Each writer/reviewer reads this entire plan; paste the canonical testing and 15-minute
progress contracts verbatim into its assignment. Poll each admitted child at least
once per minute, report blockers immediately and progress at least every 15 minutes
including validation. Self-check is not independent review. No commits/branches/pushes,
permissions changes, journal cleanup, automatic resume/reset/revert/clean/stash.

## Skills

Read full local lifecycle skills for synthesis/execution/review as applicable:
`.agents/skills/design-plan/SKILL.md`, `.agents/skills/prototype/SKILL.md`,
`.agents/skills/implementation-plan/SKILL.md`,
`.agents/skills/implement-markdown/SKILL.md`; corresponding commands, workflows and
templates. Load built-in `customize-opencode`, consult official schema and installed
SDK/plugin 1.17.18 declarations. Read AGENTS.md, .agents README and verification
contract, testing/docstring conventions. No Core/API/database/Svelte/Tailwind/browser
changes, so those area skills and app suites do not apply. No new dependencies.

## Acceptance and complete applicable gates

Reuse existing Node test helpers: implementation.test.js setup/classified/terminal
and real SDK mocked HTTP; dispatch-state.test.js setup/real filesystem/subprocess
lock checks; assets.test.js registration mutation tests. Do not import prototype
helpers. Python fixtures are irrelevant to this Node-only boundary.

| Acceptance matrix | Required observable evidence |
| --- | --- |
| Three roles × both profiles; omitted profile | Exact fixed payload/receipt mapping; omission including legacy is Max |
| Invalid profile and Low code/legacy | Generated schema and direct execute reject; zero API calls, no reservation/lock/ledger mutation |
| Capabilities | Wrong/missing selected agent, model/provider, mode, variant, effort or registered mapping; disabled/malformed variant; HTTP/JSON/transport error all reject before create/reservation without secrets |
| Hook/config | Five fixed efforts, no model substitution, unrelated agents untouched; new prompt and full permission parity, reviewer edit/nested launch remain denied |
| Durable profile | v2 required profile at creating/dispatching/submitted, recreation, lost create/prompt response and post-I/O persistence failure |
| Historical | Existing valid v1 read/status/append remain unmodified in value/absence; not-recorded/null projections; invalid versions/profile keys/missing v2 profile fail without destructive repair |
| Ownership/uncertainty | Unknown children not upgraded from envelope; direct-only list/status; lost create returns configured selection with no invented child ID; no replay/fallback |
| Scheduling | Existing symmetric code/legacy exclusion, non-code exact claims, multi-parent reconciliation, resumed claims, missing child/outages, lock ownership/subprocess crash tests remain passing across profiles |
| Privacy/progress | Existing window/bounds/terminal separation pass; configured vs observed model distinction; no claimed provider effort proof, titles/options/raw diagnostics leakage |
| Operational | Restarted actual schema, safely registered max mapping, one terminal Max-configured real-tool smoke and subsequent full independent maximum review |

Full future baseline/implementation/fix/independent-review gate (cwd explicit):

```sh
# cwd: /home/karl/repo/huron/.agents
PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH npm run check
PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH npm test
PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH node scripts/check-resolved.mjs
# cwd: /home/karl/repo/huron
git diff --check
python roadmap/check_docs.py
make docs
git check-ignore -v roadmap/plans/astra-effort-profiles.md roadmap/effort-profile-design.md roadmap/prototypes/effort-profile
git ls-files roadmap
/home/karl/.nvm/versions/node/v22.23.2/bin/node --test roadmap/prototypes/effort-profile/probe.mjs
```

Preserve locked dependencies and existing check flags/thresholds; no suppressions,
skips, xfails, exclusion changes or weaker tests. All commands exit 0; `git ls-files`
must print nothing, all owned paths ignored. Check owned untracked text/links too.
Safe resolved checker must project only Astra model ID/variant names/effort mapping,
five known agents, permission/parity pass indicators and canonical skill locations.
If CLI `opencode models openai --verbose` is used to obtain actual registration,
capture it privately in invocation-owned `.agents/.test-build` scratch with mode 0600,
parse only selected Astra entry and withhold raw output/errors, like current debug
handling. No model calls in these CLI checks. Test wrong/missing max mapping; no
hardcoded success from the project config. Actual dispatch smoke is separate after
restart and needs provider availability/quota. Its errors are blockers, not skips.

The root docs gate is required by this assignment even though no docs-site changes
are authorized. Current Makefile uses `uv run --group docs zensical build --strict`.
Baseline failure in checker/docs infrastructure must be precisely reported and
reconciled by parent, not fixed outside scope or treated as PASS. The local checker
recognizes `## Serial task slices`; use that heading here, leave template heading
normalization/Starlight work separate. Application Python lint/unit/contract/
integration/acceptance and frontend gates do not apply to this tooling-only slice.

Planning worker's bounded gate is only root diff check, ignore/untracked-roadmap
checks, isolated probe including owned links/whitespace/headings. No shared outputs
or full tooling gate execution is claimed by that worker.

## Blockers and readiness

Pending independent plan/probe review prevents ready status. Parent must complete
full baseline (including docs) and exact uv cache output ownership before bootstrap.
The present loaded Low tool cannot authorize a Max code child: only the explicitly
authorized exclusive parent bootstrap resolves that dependency. Post-bootstrap
restart/actual schema/registration/smoke are mandatory downstream acceptance, not
evidence already obtained. If endpoint capability shape cannot be safely narrowed
as designed, return to plan/probe rather than changing SDK, permissions or models.

After independent review and baseline, parent may mark ready and invoke
`/implement-markdown roadmap/plans/astra-effort-profiles.md` subject to the bootstrap
exception above. This worker's READY FOR REVIEW does not mark implementation ready.

## Execution ledger

Latest source checkpoint: maximum review 3 `ses_ef39a4415ffeYxgbAgyAK8cuxX`
qualified tree `028edc75f61292d3887be71f59f95f7e37625b40` after the supported
external-skill launch contract fixed the observed collision. Independent gates:
86 tests, 20 launcher regressions, three canonical inventories, safe resolved
checks, strict assets/typecheck/docs all green. Parent local commit
`2b2e9c0c9d6b9beafef2e11b840f28535502aa6b` matches that exact tree. Serving process
must now restart via `sh .agents/scripts/opencode-project.sh` and be verified;
fresh CLI success does not activate the current session. No open source finding
or additional source review required for this checkpoint. Earlier failures remain
historical receipts, not current uncorrected defects.

Subsequent regression evidence: staged-checkpoint review 2
`ses_ef55a982dffeoK5dFUYwiFsgmA` observed one failing safe-resolved gate in an exact
export: prototype selected a noncanonical skill, followed by an unchanged passing
rerun. This is not retry-until-green acceptance. The prior Max review PASS below
remains a historical observation; complete tooling/checkpoint qualification is now
blocked on reliable canonical skill discovery. Source/index are preserved. Read-only
root-cause discovery `ses_ef54d50ffffezcQ6dgASvNLs89` is assigned; no global assets
or checker assertions may be removed to hide this finding.

Final parent acceptance, 2026-10-05: actual maximum smoke
`ses_ef569164effe3rHjAx7BYPTG11` / `cb1b5eaf-755f-45e5-b487-0845ea1ad8b5`
returned terminal PASS. Fresh complete maximum reviewer
`ses_ef5681593ffe1n0p1ZrXj9xg1u` / `7ab26b3d-fd59-4540-a7db-644760d30b60`
returned PASS on implementation review 1, terminal observed 05:52:28 UTC. All gates
were independently rerun: 66 tooling tests, 8 probe tests, strict docs/type/assets,
safe five-agent/registered-Max checks, links/whitespace/ignore checks, no failures
or skips. Reviewer additionally verified 1,215 permission-normalization outcomes.
No open findings. Configured maximum/max and observed Astra model are separate
from unproven internal provider effort. Historical pending statements below are
earlier receipts, not the current verdict. No further tooling restart is required.

Parent acceptance: review 1 `ses_ef5865f75ffee7YdYyZmAn0ou3` found F1 only;
ignored-probe fix `ses_ef581dde0ffeMwuNAZAl0Y4Jwr` corrected it. Independent
preparatory review 2 `ses_ef57e602affeWD5gkbfOi58iU4` returned PASS, with all
complete baseline gates green (55 live tooling tests, 8 probe tests), terminal
observed 2026-10-05 05:23 UTC. All children are terminal. Parent now owns exclusive
bootstrap edits to the exact allowlist; no Low actual-code child is launched.
Fresh pre-edit status and SHA-256 of all 25 owned live files are captured in the
parent tool transcript. No runtime journal/lock maintenance or mutation is assigned.
Restart, real Max smoke and independent Max qualification remain pending.

| Event | Evidence / status |
| --- | --- |
| Prior preparatory discovery | ses_ef5b3f3d9ffeR5DL19194wlcH1 terminal per parent: registered max, CLI 1.18.34, Node 22.23.2, agent check/test/resolved green (55 tests), diff check green; no paid Max proof |
| Planning/API writer attempt 1 | ses_ef590afc4ffei81X14yro6LxWV; dispatch 2946e4e3-dea7-4f44-b79a-21675e8a88d8; started 2026-10-05T05:00:29.576Z; implementation/planning, source:repo read, plan/prototype:effort-profile write; current Low preparation only |
| Self-check | Root probe: exit 0, 6 passed/0 failed/0 skipped, about 0.52s; diff check exit 0; check-ignore exit 0, all three owned paths matched .gitignore:40; git ls-files roadmap exit 0, empty; independent review pending |
| Plan review | Pending; maximum three subject reviews |
| Complete baseline/bootstrap/restart/smoke/Max qualification | Pending; no implementation claim |

Parent appends each actual child ID, role/activity/profile/claims, configured effort,
observed model, start/last-progress/observedAt timestamps, progress age, current
command, actual-last-response terminal evidence, review count/findings and owned diff.
Record missing historical profile as NOT RECORDED, never infer maximum from current
agent config. Do not put credentials in ledger/progress/tool titles. No journal edits.

## Escalation / final receipt

### Parent bootstrap self-check — restart and Max qualification pending

All delegated workers were terminal before exclusive parent edits began. The main
session implemented precisely the 25-file live allowlist above; no new live files,
deletions, dependencies, permissions widening, application changes or runtime journal
maintenance. No actual-code subagent was launched at Low. The caller-visible profile
field remains unavailable in this running session until restart.

Delivered in the staged bootstrap: fixed Low/Max agents; default-Max profile
normalization and code/legacy downgrade rejection before side effects; selected
agent/mode/variant/model/effort and registered capability checks; exact fixed-effort
hook; required-profile v2 reservations/envelopes within the v1 ledger; untouched v1
historical values; safe configured ownership/uncertainty receipts separate from
observed model and providerAcceptance not-proven. Claim/lock/recovery algorithms
were not changed. Tests cover all existing safety behaviors plus the new profiles.

An intermediate safe-resolved check failed because inherited same-action external
directory allow rules appear in different discovery order across CLI invocations.
Safe diagnostics confirmed equal prompts, identical 113-rule multisets and only
order differences. The checker now normalizes ONLY contiguous same-permission,
same-action groups (commuting rules); it preserves every rule and action boundary.
Regression tests reject reordered deny boundaries, missing/additional/changed rules
and changed permissions. No permission itself was changed to satisfy the checker.

Final code self-check, cwd `.agents`, with
`PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH` on each command:

- `npm run check`: exit 0, strict TypeScript and canonical asset/text checks.
- `npm test`: exit 0, **66 tests**, 48 top-level, zero failures/skips/cancellations/todo;
  final code-test run duration about 7.30 seconds. Original 55-test behaviors retained.
- `node scripts/check-resolved.mjs`: exit 0; all five fixed agents resolve, canonical
  prompt/permission parity, all 11 local skills; registered low→low and max→max.

Root gates also passed: `git diff --check`; `python roadmap/check_docs.py`;
`UV_CACHE_DIR=/tmp/opencode/huron-effort-uv-cache make docs` (strict, no issues);
explicit ignore checks for this plan/design/prototype; `git ls-files roadmap`
(empty); exact Node prototype command above (8 passed, zero failures/skips).
Receipts are parent self-checks, not independent complete qualification. Post-receipt
reruns remain in the main tool transcript. No provider inference at Max is claimed.

Next: quit/restart with no live children, inspect actual `profile` schema, dispatch
the planned tiny maximum verification smoke, then a fresh independent maximum
review of the full bootstrap and all gates. Implementation review count is still
zero; the two reviews above were preparatory plan/probe reviews only. Preserve
runtime state; do not use manual SDK dispatch, a second server or Low fallback.

Return exact changed files, no deletions beyond replaced obsolete assertions, every
command/cwd/exit/count, baseline attribution, safe registration/smoke evidence and
ownership preservation. Distinguish configured max, observed Astra identity and
provider acceptance/internal effort not proven. Independent complete Max review is
mandatory; incomplete gates or restart evidence mean BLOCKED, never completion.
On failure preserve all data and route only owned findings to parent; no automatic
rollback of accepted concurrency work or unknown files. This ignored phase document
and prototype are not shipped features and must never become tracked dependencies.

## Preparatory F1 fix receipt (attempt 1)

Review 1 (`ses_ef5865f75ffee7YdYyZmAn0ou3`) reported F1: the owned-document
probe required draft status permanently, contradicting the future lifecycle gate.
Fix worker `ses_ef581dde0ffeMwuNAZAl0Y4Jwr`, dispatch
`218c43dd-621b-4c15-aa6c-b38685208b6e`, is bounded fix/prototype, current Low
preparation only. It changed only `roadmap/prototypes/effort-profile/probe.mjs`
and appended this receipt. The actual plan status remains draft; no live source,
configuration, tests, checker, profile policy or runtime journal was edited.

The probe now requires exactly one explicit lifecycle status using the grammar in
`roadmap/check_docs.py:111–119`: case-sensitive `Status:` label, case-insensitive
draft/blocked/ready/implementing/verified value, optional spaced em/en/hyphen-dash
rationale. Two additional tests cover all five states, lower/upper/title case,
all three rationale separators, tab/no-space label boundaries, and 17 missing,
malformed or duplicate declaration cases. Existing six tests and unrelated
assertions remain. The current expected probe total is **8**, superseding the
six-test count recorded in the original prototype evidence above. Syntax acceptance
does not certify readiness or authorize a lifecycle transition.

Self-check on 2026-10-05, all commands exit 0:

| Cwd | Exact command | Outcome |
| --- | --- | --- |
| root | `git diff --check` | Clean |
| root | `python roadmap/check_docs.py` | Documentation/link/phase checks pass |
| root | `UV_CACHE_DIR=/tmp/opencode/huron-effort-uv-cache make docs` | Strict build, no issues |
| root | `git check-ignore -v roadmap/plans/astra-effort-profiles.md roadmap/effort-profile-design.md roadmap/prototypes/effort-profile` | All three match `.gitignore:40` |
| root | `git ls-files roadmap` | Empty |
| root | `/home/karl/.nvm/versions/node/v22.23.2/bin/node --test roadmap/prototypes/effort-profile/probe.mjs` | 8 passed, 0 failed, 0 skipped |
| `.agents` | `PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH npm run check` | Typecheck/assets pass; 11 skills/four commands |
| `.agents` | `PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH npm test` | 55 passed, 0 failed, 0 skipped |
| `.agents` | `PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH node scripts/check-resolved.mjs` | Existing three Astra Low agents and 11 canonical skills resolve |

Shared check writes were limited to declared normal build/docs/cache/environment
artifacts. Initial tracked/untracked dirty work was captured and preserved. No
baseline failures or missing infrastructure were observed in this rerun. Parent's
review-1 baseline receipt was 55 live tests/6 probe tests green; F1 was a lifecycle
contract defect, not an existing draft-state command failure. This is a fix
self-check, not independent PASS or Max/provider acceptance evidence. Independent
preparatory review 2 remains pending; no ready transition or promotion is claimed.
