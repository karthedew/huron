# Medium workflow migration: restart and independent review required

Date: 2026-11-09. Status: **implementation self-check, not independent PASS**.
No product completion or production qualification is claimed.

## Ownership and activation boundary

Implementation/code attempt1, child `ses_e408c796effeI227CS8VizNTvj`, dispatch
`2944a623-0fb7-424c-936a-b841133f94de`, parent `ses_e40c78b7fffeLwxNhxaPBLlHq5`.
Envelope time: 08:36:21.734Z; first measured worker timestamp: 08:36:37Z.
Configured profile is **maximum**, model `openai/gpt-6-astra`, variant/effort **max**.
Provider effort acceptance is **not-proven**. Medium is future configuration after restart,
not an observed change to this worker or the serving runtime.

Claims were `*:write` (whole worktree/all outputs serially) and `build:agent-tools:write`
(`.agents` check/test outputs). These coordinate exclusion, not authority over all files/services.
The supplied scope explicitly assigned B1 stale skill-policy checks/tests, B2 source/spelling
registration, and B3 roadmap-ignore remediation. Existing dirty hunks and unknown data were retained.
The worker did not delegate, run a real dispatch experiment, resume/replay, change the live journal
or locks, start a server/service/container, install/download packages, upgrade dependencies, edit
product source/tests, or commit/branch/push. Existing test helpers used isolated fake HTTP and
private temporary worktrees; they never dispatched a child to the serving OpenCode instance.

Required contracts, all four canonical lifecycle skills/templates, customize-opencode,
writing-for-agents and its SKILL-MECHANICS.md were read before edits. The public configuration
schema accepts explicit `skills.paths`; fresh installed OpenCode 1.18.35 checks confirmed directory
scanning and portable `~/` expansion with external scans disabled. An optional upstream tagged
source URL returned 404; no implementation assumption depends on it.

ASD was denied by the serving skill policy. Its source was registered and its spelling corrected
for the next startup, without direct-reading its instructions. Discovery of name/location is not
skill loading or language qualification. That qualification remains pending after restart.

## Exact edited files

No file was deleted by this worker. These 29 files are the complete edit boundary:

```text
opencode.json
.gitignore
AGENTS.md
IMPLEMENTATION_PLAN_LATEST.md
HANDOFF_MEDIUM_WORKFLOW.md
.agents/plugins/dispatch-state.ts
.agents/plugins/implementation.ts
.agents/scripts/check-assets.mjs
.agents/scripts/check-resolved.mjs
.agents/tests/dispatch-state.test.js
.agents/tests/implementation.test.js
.agents/tests/assets.test.js
.agents/tests/launcher.test.js
.agents/README.md
.agents/commands/implement-markdown.md
.agents/prompts/orchestrator.md
.agents/prompts/implementer.md
.agents/prompts/reviewer.md
.agents/workflows/orchestration.md
.agents/workflows/verification.md
.agents/workflows/implement-markdown.md
.agents/templates/assignment.md
.agents/templates/design-plan.md
.agents/templates/prototype.md
.agents/templates/phase-plan.md
.agents/skills/design-plan/SKILL.md
.agents/skills/prototype/SKILL.md
.agents/skills/implementation-plan/SKILL.md
.agents/skills/implement-markdown/SKILL.md
```

Only this handoff is newly created. The latest plan was already untracked; its prospective policy
and appended §15 changed, not §§11–14 or historical profiles. Existing dirty tooling changes were
extended, not replaced. The user writing-for-agents allow remains. The only replaced allow name
is the authorized `asd=ste100` typo. Other user configuration and permissions remain unchanged.
The staged runtime-artifact deletions, dirty `.agents/.gitignore`, `.opencode/README.md`, and
existing `.opencode` deletions were present before this worker and remain untouched.

## Implemented contracts and tests

- Seven fixed Astra agents: three Low agents, two new Medium counterparts, two unchanged Max
  effort counterparts. Shared prompts/permissions stay equal per worker role; Task and nested
  dispatch remain denied. Primary and commands remain Low.
- Three-way profile selection and chat.params enforcement. SDK promptAsync remains native and
  asynchronous with parentID and navigable child/dispatch IDs; no invented variant request field.
- New classified omission defaults Medium; legacy-exclusive omission defaults Maximum. Explicit
  Medium/Max may be legacy-exclusive. Low code/legacy-exclusive refuses before API/journal effects.
  Missing, disabled or mismatched selected capability refuses without fallback.
- V1 ledger container unchanged; v1 absence stays not-recorded/configured null. Mixed v1 and v2
  Low/Medium/Max history is preserved across append, recreation, and uncertain stages. No live
  migration/backfill. Older readers reject Medium, so mixed launchers are prohibited.
- Existing four test files/helpers were extended for all profiles/roles, classification defaults,
  strict capability selection, native IDs, uncertain create/prompt/save, cross-profile exclusion,
  claim conflicts/read sharing, and source/permission policy. Existing corruption, symlink,
  cross-process locking, privacy, progress, terminal-evidence and no-replay coverage remains.
- Approved skill paths are exactly `.agents/skills`, `~/.agents/skills/writing-for-agents`, and
  `.claude/skills/asd-ste100`. No broad home registration or vendor copies. Deny-by-default and
  external-scan suppression remain; missing approved sources fail with supply/restart guidance.
- `/roadmap/` is ignored only through the root ignore addition; no data moved or deleted.
- Prospective instructions use ordinary Medium code/fix/review and explicit Maximum final
  COMPLETE qualification. Explicit Maximum prerequisite probes/reviews remain. The latest-plan
  §15 supersedes only the assigned prospective architecture workflow/availability clauses;
  historical design documents remain byte-identical.
- Approved setup is documented, not executed: existing-lockfile npm ci, installed Playwright CLI's
  matching Chromium only, no broad npx fetch/upgrade/image pull, and assigned isolated cached
  containers with --pull=never. The unavailable Svelte autofixer has no installation exception.

## Baseline and self-check evidence

Independent baseline child `ses_e409cc5aaffeoZkOUKvxHtBStE`, dispatch
`ba770f66-97ed-4883-bc4e-361cb6ddf7cd`, ended BLOCKED at 08:33:58Z, observed 08:34:30.887Z.
It found no owned residual process. Node 26.10.0, npm 11.19.1 and OpenCode 1.18.35 were recaptured
unchanged here. Baseline check exit1 was stale skill policy after successful TypeScript; tests
were 108 total, 103 passing, five stale-policy failures. Resolved checker exit1 demanded denial
of the user-approved writing skill. Roadmap paths were unignored, with no tracked roadmap data.
These failures were owned and fixed, not waived. Root whitespace remains separately attributed.

Outputs are retained in this child session's terminal evidence, with safe summaries below.
There is no separate raw provider/config log. The resolved checker retains its existing private
temporary capture/cleanup behavior; the additional root CLI projections captured raw output in
anonymous memory file descriptors and printed only known fields, never skills' instruction bodies.

| Cwd | Exact command | Outcome |
| --- | --- | --- |
| `.agents/` | `npm run check` | Exit0; strict TypeScript and asset checks pass: 11 canonical skills, two explicit sources, seven agents, four commands |
| `.agents/` | `npm test` | Exit0; 120 tests, 120 pass, 0 fail/cancelled/skipped/todo; Node test duration 2913.884884 ms |
| `.agents/` | `OPENCODE_DISABLE_EXTERNAL_SKILLS=1 node scripts/check-resolved.mjs` | Exit0; canonical dispatcher/commands/prompts, all seven profiles/permissions, three registry variants, 13 approved skill locations |
| Root | `sh .agents/scripts/opencode-project.sh debug config` | Exit0 through memory-only projection; default orchestrator, canonical lifecycle, exact three source paths; implementation command Low |
| Root | `sh .agents/scripts/opencode-project.sh debug agent markdown-orchestrator` | Exit0; Astra low/low, primary |
| Root | `sh .agents/scripts/opencode-project.sh debug agent markdown-implementer` | Exit0; Astra low/low, subagent |
| Root | `sh .agents/scripts/opencode-project.sh debug agent markdown-reviewer` | Exit0; Astra low/low, subagent |
| Root | `sh .agents/scripts/opencode-project.sh debug agent markdown-implementer-medium` | Exit0; Astra medium/medium, subagent |
| Root | `sh .agents/scripts/opencode-project.sh debug agent markdown-reviewer-medium` | Exit0; Astra medium/medium, subagent |
| Root | `sh .agents/scripts/opencode-project.sh debug agent markdown-implementer-max` | Exit0; Astra max/max, subagent |
| Root | `sh .agents/scripts/opencode-project.sh debug agent markdown-reviewer-max` | Exit0; Astra max/max, subagent |
| Root | `sh .agents/scripts/opencode-project.sh models openai --verbose` | Exit0; projected Astra low→low, medium→medium, max→max only; provider acceptance not-proven |
| Root | `sh .agents/scripts/opencode-project.sh debug skill` | Exit0; 13 names/locations only, canonical lifecycle plus exact approved writing/ASD sources under suppressed external scans |
| Root | `git check-ignore -v roadmap/ roadmap/plans/probe.md .agents/.test-build/implementation.js .agents/.dispatch-state/ledger.json .agents/.dispatch-state/admission.lock .agents/.dispatch-archive/recovery/ledger.json` | Exit0; root `/roadmap/` and existing `.agents` output/journal/archive rules |
| Root | `git ls-files -- roadmap` | Exit0; empty |
| Root | `git diff --cached --check` | Exit0; no diagnostics |
| Root | `git diff --check -- .agents opencode.json .gitignore AGENTS.md` | Exit0; scoped tracked tooling/instruction changes clean |

The final root whitespace, new-text, link and residual-process checks are recorded below.
No product Python/frontend/site suite applies: this assignment changed only
tooling and agent instructions, not product code/tests, site input, visible UI or generated API data.
The root offline Python invocation below is the assigned link checker, not product qualification.

## Protected history

Verified again at 08:50:01Z with git rev-parse/hash-object; migration staged/unstaged diffs empty:

| Item | Unchanged value |
| --- | --- |
| HEAD | `0dcdf1ff6a8689f704a73a0758a886c18b5d3584` |
| Historical IMPLEMENTATION_PLAN.md blob | `862e1bafc54c5ca88b0351ff7ee723662a1ac7f8` |
| migrations/versions/0003_uploads.py blob | `83757f7e73640356639ae07c45d7885660b9a6e3` |
| HANDOFF_M11_PLAN.md blob | `83e6e675f2434297b6b6fc3470ee7ff1f4a4ef88` |
| design/m11-production-architecture.md blob | `c4fdc32f3bbfb8363a2a36f8fe167b061d78c02a` |
| design/m11-review-evidence.md blob | `0eea7b44ad42f17d28cbfb1ab7285b244cb749ac` |
| design/m11-prototype-evidence.md blob | `d7453cc440b649bcce33a44caa089c6b245b9ced` |

The initial latest-plan hash was `c71f24d2c53ac9b4ac95cdd49d69197822d8bd54`.
An optional `git cat-file -e` check for that hash exited1: hash-object had not stored the untracked
blob. No Git object was written to manufacture a baseline. Preservation of §§11–14 is supported
by the original full read and the scoped patch record, not a claimed unavailable blob comparison.

## Required next session

1. Parent records this worker's terminal response and checks owned residual processes. No further
   dispatch in the current serving session. Do not alter the journal or steal a lock.
2. Quiesce existing workers/invocations. Quit and restart the existing OpenCode process from the
   repository root through `sh .agents/scripts/opencode-project.sh`, retaining its intended launch
   arguments. No second server, Task bypass, manual resume or prompt replay.
3. Inspect actual loaded launch schema for all three profiles, fixed agent/effort settings,
   skill availability and canonical source paths. Fresh CLI success above does not prove activation.
   Load writing-for-agents and permitted ASD instructions for the affected instruction/language review.
4. Arrange a fresh independent **verification/review/maximum** with the complete assignment,
   exact ownership plus build-output claims, preserved dirty baseline and all applicable gates.
   This migration has no independent verdict yet. Findings need an explicitly owned future fix,
   not this stopped worker's self-resume or a silent fourth review.
5. Retain [latest-plan §15](IMPLEMENTATION_PLAN_LATEST.md#15-prospective-tooling-and-setup-amendment-2026-11-09)
   and the unchanged historical receipts. The legacy `.claude/commands/implement-markdown.md`
   is not the resolved OpenCode entrypoint and remains an out-of-scope residual, not a fallback.
   Other recorded product/workflow gate drift and M11 prerequisites remain; this tooling change
   does not authorize P00, product implementation, installs, service starts or production enablement.

## Final self-check closure

At 08:53:32Z the complete assigned gate had returned. The final receipt edits are checked again
with the same root whitespace/new-text/link commands before terminal return.

| Cwd | Exact command | Outcome |
| --- | --- | --- |
| Root | `git diff --check` | Exit2, only pre-existing `web/src/lib/api/openapi.ts:170` trailing whitespace; not changed or relabeled green |
| Root | `git diff --cached --check` | Exit0, no diagnostics |
| Root | `git diff --check -- .agents opencode.json .gitignore AGENTS.md` | Exit0, no diagnostics; pre-existing clean tooling hunks retained |
| Root | `git diff --no-index --check /dev/null IMPLEMENTATION_PLAN_LATEST.md` | Exit1 for additions, no whitespace diagnostics |
| Root | `git diff --no-index --check /dev/null HANDOFF_MEDIUM_WORKFLOW.md` | Exit1 for additions, no whitespace diagnostics |
| Root | `uv run --offline --no-sync python scripts/check_links.py HANDOFF_M11_PLAN.md IMPLEMENTATION_PLAN_LATEST.md design/m11-production-architecture.md design/m11-review-evidence.md design/m11-prototype-evidence.md HANDOFF_MEDIUM_WORKFLOW.md` | Exit0, no diagnostics; file links, not anchor validation |
| Root | `git status --short`; `git diff --numstat -- .agents opencode.json .gitignore AGENTS.md`; `git diff --cached --stat` | Exit0; original dirt preserved plus the declared edits; staged deletions unchanged |
| Root | `ps -C node,npm,tsc,opencode,python3,python,sh -o pid,ppid,stat,etimes,comm` | Exit0; final serial observation 08:53:48Z shows no npm, tsc, Node test, fresh CLI or link-check process remaining |

The first process snapshot overlapped the already-running link gate and showed its Python process;
the serial 08:53:48Z snapshot confirmed it had exited. Only the pre-existing serving OpenCode
PID 2413678 and older environment Python/shell PIDs 3160819/3160827/3160829/3160830 matched that
projection. None was started, stopped or altered by this worker. Synchronous check subprocesses
all returned; no owned residual process was found. This is not authority to stop unrelated processes.

No new gate failure was observed. Ancillary failures were the optional upstream source HTTP404
and unavailable initial untracked Git object, both described above; neither replaced or waived a gate.
The source/runtime/self-check pass is complete. **Independent review, ASD language qualification,
and serving-runtime activation remain pending.** The worker stops here; the parent must restart
before further dispatch. No independent PASS or product completion is claimed.

## Parent terminal receipt

At 2026-11-09T08:57:40.863Z, the parent observed the writer idle with a completed
terminal response, completedAt 08:56:59.429Z. The response reports completed self-checks,
not an independent verdict. Its final process observation at 08:56:22Z found no owned
validation process remaining. The parent read this handoff and dispatched no further worker.
The recorded dispatch remains maximum with configured effort max; provider acceptance is
not-proven. Independent review attempt1 is pending after the required quit/restart.

## R1 language fix and self-check (2026-11-09)

This receipt records fix attempt1, not independent acceptance. The parent must restart before independent Maximum review2.
The original receipt above remains unchanged. Its Git blob before this append was `45847c2f9da74ed8fdda1945f92e3e0b9d343875`.

The supplied review1 receipt reports FAIL for structural language in new migration prose.
Reviewer `ses_e3f39e631ffepzYigMV38AvSLA` used dispatch `4bf80469-f0b4-4c56-a0de-a5794b32c5bf`.
The parent observed its completed terminal response at `2026-11-09T14:56:34.056Z`.
That reviewer independently passed the functional tooling gates and all 120 tests.
It reported no owned residual validation process.

This fix uses role fix, activity code, and configured profile medium with effort medium.
The model is `openai/gpt-6-astra`. Provider effort acceptance remains not-proven.
Dispatch: `909cd7b2-dcc9-4ab3-9ba9-ec6c5b4bf0c0`. Child: `ses_e3f2aba90ffekEEu28lrSzr5NF`.
Claims remain `*:write` and `build:agent-tools:write`. These claims coordinate exclusion, not edit authority.

### Changes and semantic checks

The fix splits compound sentences and removes semicolons from owned prospective prose.
It also separates multi-step instructions and long paragraphs.
Tool and error descriptions retain their conditions and evidence limits.
Two existing launcher assertions now match the revised diagnostic punctuation.
The fix adds no runtime branch, permission, dependency, profile default, or migration rule.

The self-check compared these retained contracts against the actual code and existing public-behavior tests:

- Classified omission selects Medium. Legacy-exclusive omission selects Maximum.
- Explicit Medium or Maximum may remain legacy-exclusive. Low refuses code and legacy-exclusive before journal/API effects.
- Explicit Maximum assignments remain Maximum. Final complete qualification requires verification/review/maximum.
- Capability refusal has no fallback. Configured effort does not prove provider effort.
- Claims, exclusion, privacy, historical records, recovery, and restart conditions remain unchanged.
- Setup remains bounded to the approved locked dependencies and matching Chromium. This assignment performs no setup.

Exact edited files for this fix:

```text
AGENTS.md
IMPLEMENTATION_PLAN_LATEST.md
HANDOFF_MEDIUM_WORKFLOW.md
opencode.json
.agents/README.md
.agents/commands/implement-markdown.md
.agents/plugins/implementation.ts
.agents/prompts/implementer.md
.agents/prompts/orchestrator.md
.agents/prompts/reviewer.md
.agents/scripts/check-assets.mjs
.agents/scripts/check-resolved.mjs
.agents/skills/design-plan/SKILL.md
.agents/skills/implement-markdown/SKILL.md
.agents/skills/implementation-plan/SKILL.md
.agents/skills/prototype/SKILL.md
.agents/templates/assignment.md
.agents/templates/design-plan.md
.agents/templates/phase-plan.md
.agents/templates/prototype.md
.agents/tests/launcher.test.js
.agents/workflows/implement-markdown.md
.agents/workflows/orchestration.md
.agents/workflows/verification.md
```

The other five files in the migration boundary remain untouched by this fix.
The worker deleted no file. Existing staged deletions and unrelated dirty work remain owned by others.

### Reproducible language checks and attribution

The isolated helper is `/tmp/opencode/r1-language.py`. Run `python3 /tmp/opencode/r1-language.py` from the repository root.
It invokes `python3 .claude/skills/asd-ste100/scripts/ste-lint.py --json` with each selected sentence or description on stdin.
It uses no baseline increase, disabled rule, or linter change.
Its JSON records contain the source path, source line, exact text, diagnostics, and exit status.

For tracked prose, selection starts from changed paragraphs in `git diff -U0 HEAD`.
The helper excludes complete sentences that remain identical to HEAD after whitespace normalization.
It selects changed tool/error strings without treating JavaScript or TypeScript punctuation as English.
For the untracked latest plan, explicit markers select only migration policy passages.
Only writer-profile cells qualify from the two existing execution rows.
The original latest-plan blob remains unavailable. This method does not claim an unavailable preservation comparison.

The worker reviewed paragraph structure, instruction length, conditions, and modality manually alongside the mechanical screen.
The linter applies a 25-word cap. Manual review also applies the 20-word instruction cap.
The check does not certify the official lexical dictionary.
Existing technical identifiers and diagnostic field names retain their meanings.

Historical receipt language remains an explicit exception to this fix's edit scope.
The original handoff, latest-plan sections 11–14, and other protected history retain their original text.
This preserves evidence rather than silently rewriting past claims.
Pre-existing sentences in the surrounding tooling documents also remain outside this migration-language fix.
Whole-file screens can therefore fail. Those failures do not qualify as corrected new prose.
The prior review's whole-file count included that historical and pre-existing debt.

### Functional checks and preservation

Versions: Node `26.10.0`, npm `11.19.1`, OpenCode `1.18.35`, Python `3.12.4`.
From `.agents/`, all three commands returned exit 0:

- `npm run check` passed strict TypeScript and asset checks.
- `npm test` passed 120 tests, with zero failures, cancellations, skips, or todo entries.
- `OPENCODE_DISABLE_EXTERNAL_SKILLS=1 node scripts/check-resolved.mjs` passed all resolved checks.

The root helper `python3 /tmp/opencode/r1-cli.py` ran the following fresh CLI commands.
Each returned exit 0. Raw configuration stayed in anonymous memory descriptors.
Only known profile, model, command, and skill-location fields appeared in output.

- `sh .agents/scripts/opencode-project.sh --version`
- `sh .agents/scripts/opencode-project.sh debug config`
- `sh .agents/scripts/opencode-project.sh debug agent markdown-orchestrator`
- `sh .agents/scripts/opencode-project.sh debug agent markdown-implementer`
- `sh .agents/scripts/opencode-project.sh debug agent markdown-reviewer`
- `sh .agents/scripts/opencode-project.sh debug agent markdown-implementer-medium`
- `sh .agents/scripts/opencode-project.sh debug agent markdown-reviewer-medium`
- `sh .agents/scripts/opencode-project.sh debug agent markdown-implementer-max`
- `sh .agents/scripts/opencode-project.sh debug agent markdown-reviewer-max`
- `sh .agents/scripts/opencode-project.sh models openai --verbose`
- `sh .agents/scripts/opencode-project.sh debug skill`

The fresh CLI results showed the seven configured agents and low/medium/max registry mappings.
They showed the three approved source directories and all 13 required skill locations.
Fresh CLI success does not activate the serving process or prove provider effort acceptance.

At `15:11:18Z`, HEAD and all six protected blobs matched the values in the original receipt.
The staged deletion summary remained unchanged. Root ignore checks returned exit 0 for all six assigned paths.
The command `git ls-files -- roadmap` returned exit 0 with no tracked files.
Root whitespace and link outcomes:

- `git diff --check`: exit 2, solely existing `web/src/lib/api/openapi.ts:170` trailing whitespace.
- `git diff --cached --check`: exit 0.
- `git diff --check -- .agents opencode.json .gitignore AGENTS.md`: exit 0.
- `git diff --no-index --check /dev/null IMPLEMENTATION_PLAN_LATEST.md`: exit 1 for additions, without diagnostics.
- `git diff --no-index --check /dev/null HANDOFF_MEDIUM_WORKFLOW.md`: exit 1 for additions, without diagnostics.
- `uv run --offline --no-sync python scripts/check_links.py HANDOFF_M11_PLAN.md IMPLEMENTATION_PLAN_LATEST.md design/m11-production-architecture.md design/m11-review-evidence.md design/m11-prototype-evidence.md HANDOFF_MEDIUM_WORKFLOW.md`: exit 0.

The full historical screen `python3 /tmp/opencode/r1-language.py --whole` returned exit 1 with 1,056 hard candidates.
Its 1,190 total candidates include protected history and pre-existing debt across 19 documents.
Those counts precede this final receipt addition. They are not a migration-defect count or a passing gate.
The targeted screen returned exit 0 with zero hard findings before this receipt's final checks.
The terminal response records the final count and residual-process observation after all edits.

Product Python, frontend, site, and browser suites do not apply to these tooling-language changes.
The worker ran no service, container, setup, real dispatch experiment, or P00 task.
Two context-mismatched patches made no changes before corrected patches succeeded.
An initial diagnostic pipe had a Python syntax error. The corrected pipeline reran the complete language selection.

The writer stops after self-check. The parent must reconcile terminal workers and owned processes.
Then quit and restart through `sh .agents/scripts/opencode-project.sh` before further dispatch.
Independent Maximum review2 must inspect the result and rerun all applicable gates.
This receipt grants no independent PASS, product completion, or production qualification.

## Normal-startup correction blocker (2026-11-10)

Status: **BLOCKED before policy implementation**. This receipt is a worker self-check, not independent qualification.
The user accepts the Review1 language corrections. That acceptance is not an independent PASS.
The supplied Review2 receipt reports a terminal BLOCKED result before gates, solely for the missing serving suppression flag.
Review2 child `ses_e3c501563ffeCEeL1rrua6JPlj` reported no owned validation process.

This worker uses role fix, activity code, profile medium, and configured effort medium.
The configured model is `openai/gpt-6-astra`. Provider acceptance remains not-proven.
Dispatch: `5ab77e97-83d1-4886-9e84-454103e91d59`. Child: `ses_e3c4715eeffegoVCanBuaMDMfu`.
Claims are `*:write` and `build:agent-tools:write`.
The worker did not delegate, resume a child, edit the journal, or start a service.
It performed no setup, download, dependency upgrade, commit, or product edit.

### Runtime evidence and decision boundary

Normal OpenCode startup succeeds, but canonical skill resolution is nondeterministic.
The installed binary is `/home/karl/.opencode/bin/opencode`, version `1.18.35`.
Its embedded skill loader collects external and explicit paths into one set.
It then parses that set with `concurrency:"unbounded"`.
Each completed parse assigns `j.skills[z.data.name]`, replacing any previous entry with that name.
Explicit path order therefore does not establish deterministic precedence.

The worker inspected this installed code with these commands:

```sh
strings /home/karl/.opencode/bin/opencode | rg -n -C 8 'Duplicate skill|skill\.ts|OPENCODE_DISABLE_EXTERNAL_SKILLS'
strings /home/karl/.opencode/bin/opencode | rg -o '.{400}disableExternalSkills.{1800}'
strings /home/karl/.opencode/bin/opencode | rg -o '.{500}(duplicate skill|Duplicate skill|\.claude.{0,80}\.agents|\*\*/SKILL.md).{1500}'
strings /home/karl/.opencode/bin/opencode | rg -o 'var uA=A.fnUntraced.{0,18000}'
```

All commands returned exit 0. These inspect executable code, not provider configuration.
The final extraction contains discovery, concurrent parsing, and name-based lookup together.

Twelve serial `opencode debug skill` calls each returned exit 0 and 59 skills.
The worker removed these variables from each subprocess environment:

- `OPENCODE_DISABLE_EXTERNAL_SKILLS`
- `OPENCODE_DISABLE_CLAUDE_CODE_SKILLS`
- `OPENCODE_DISABLE_CLAUDE_CODE`

Run 3 resolved `prototype` to `/home/karl/.agents/skills/prototype/SKILL.md`.
The other eleven runs resolved it to the repository source.
The other three lifecycle names resolved to repository sources in all twelve runs.
One earlier normal scan also returned 59 skills and four canonical lifecycle locations.
These observations demonstrate the collision. They do not prove that later scans will succeed.

Raw CLI output stayed in anonymous memory descriptors.
The worker printed only names, locations, selected configuration fields, and command exits.
External discovery included unrelated skills such as `graphify` and `research`.
Existing wildcard skill denial still prevents their use by workflow agents.
Discovery alone does not satisfy the requested permission contract.

The worker found no supported per-name source selector in the installed loader or loaded configuration guidance.
Changing path order cannot fix the observed race.
A narrow checker could detect a losing scan, but cannot guarantee the serving process selects the same source.
The worker therefore stopped before changing policy, configuration, or tests.
It did not impose suppression, rename public commands, or change external skills.
The requested correction remains unimplemented, rather than partially represented as complete.

The parent must decide how to obtain deterministic resolution with external scans enabled.
A runtime fix or an explicitly approved naming change needs a new assignment.
This receipt does not authorize either action.

### Affected policy and existing coverage

The prospective correction spans these existing files:

- `opencode.json`: wildcard skill denial.
- `.agents/scripts/opencode-project.sh`: mandatory suppression export.
- `.agents/scripts/check-resolved.mjs`: flag prerequisite, exact source policy, and global skill denial assertions.
- `.agents/scripts/check-assets.mjs`: exact source registration and skill allowlist assertions.
- `.agents/tests/launcher.test.js`: flag enforcement and resolved-source fixtures.
- `.agents/tests/assets.test.js`: registration and permission behavior.
- `.agents/README.md`: launcher, suppression, source, and verification instructions.
- `.agents/workflows/orchestration.md`: launcher requirement after quiescence.
- `.agents/workflows/verification.md`: flagged checker and launcher requirement.
- `AGENTS.md`: mandatory launcher reference.
- `IMPLEMENTATION_PLAN_LATEST.md` section 15: prospective suppression and restart policy.

The worker inspected `.opencode/README.md`. It contains no active launcher or suppression requirement.
Existing tests already cover CLI stubs, source mismatches, argument forwarding, permissions, profiles, admission, and recovery.
No test contract changed, so the worker added no tests.
Seven agents, profile defaults, Maximum qualification, and delegation denials remain unchanged.
Historical receipts remain intact, including their obsolete launcher instructions as historical evidence.

### Baseline checks and preservation

Versions: Node `26.10.0`, npm `11.19.1`, OpenCode `1.18.35`.
Commands below ran from `.agents/` unless the row specifies the repository root.

| Command | Result |
| --- | --- |
| `npm run check` | Exit 0. Strict TypeScript and asset checks passed. |
| `npm test` | Exit 0. All 120 tests passed. No failures, cancellations, skips, or todo entries. |
| `env -u OPENCODE_DISABLE_EXTERNAL_SKILLS -u OPENCODE_DISABLE_CLAUDE_CODE_SKILLS -u OPENCODE_DISABLE_CLAUDE_CODE node scripts/check-resolved.mjs` | Exit 1. Existing flag prerequisite rejected normal startup before CLI inspection. |
| Root: `opencode debug config` | Exit 0. Safe projection checked the canonical commands and default orchestrator. |
| Root: `opencode debug agent NAME` for all seven workflow agents | Each returned exit 0. Low, Medium, and Max settings matched their configured agents. |
| Root: `opencode models openai --verbose` | Exit 0. Registry mappings include low, medium, and max with matching reasoning effort. |
| Root: `opencode debug skill`, twelve serial calls | Each returned exit 0. One call selected the noncanonical home prototype. |
| Root: `git diff --check` | Exit 2. Only existing `web/src/lib/api/openapi.ts:170` trailing whitespace. |
| Root: `git diff --cached --check` | Exit 0. |
| Root: `git diff --check -- .agents opencode.json .gitignore AGENTS.md` | Exit 0. |
| Root: `git ls-files -- roadmap` | Exit 0 with no output. |

The root CLI projections used the same three-variable removal shown above.
They invoked `opencode` directly, without the launcher.
The seven agent names were `markdown-orchestrator`, `markdown-implementer`, `markdown-reviewer`,
`markdown-implementer-medium`, `markdown-reviewer-medium`, `markdown-implementer-max`, and `markdown-reviewer-max`.
Worker delegation and Task remained denied. Reviewers retained edit denial.
The CLI results do not prove serving activation or provider effort acceptance.

The root ignore check returned exit 0 for all six paths:

```sh
git check-ignore -v roadmap/ roadmap/plans/probe.md .agents/.test-build/implementation.js .agents/.dispatch-state/ledger.json .agents/.dispatch-state/admission.lock .agents/.dispatch-archive/recovery/ledger.json
```

`git rev-parse HEAD` and `git hash-object` checked every value in the protected-history table above.
The three staged runtime-artifact deletions remain unchanged: 500 removed lines across three files.
The handoff blob before this append was `3a472099c3d94349bf63f3888a7a795c2d079560`.
This append is the only source-file change by this worker.
Normal tests generated only their assigned ignored artifacts.
Product Python, frontend, browser, and site gates do not apply to this evidence-only append.

### Required next action

The parent must reconcile this terminal blocker and owned processes before further work.
The worker stops without further dispatch or manual resume.
After an approved tooling correction, quiesce workers and restart with normal `opencode` from the repository root.
Keep the intended serving arguments. Do not start a competing server.
The user rejects a launcher or suppression flag as a qualification prerequisite.
Independent Maximum qualification remains required after the fixed runtime loads.
Restart alone does not fix the observed skill collision.

### Final evidence checks

The assigned offline link check returned exit 0 without diagnostics:

```sh
uv run --offline --no-sync python scripts/check_links.py HANDOFF_M11_PLAN.md IMPLEMENTATION_PLAN_LATEST.md design/m11-production-architecture.md design/m11-review-evidence.md design/m11-prototype-evidence.md HANDOFF_MEDIUM_WORKFLOW.md
```

Both new-text checks returned exit 1 for additions, without whitespace diagnostics:

```sh
git diff --no-index --check /dev/null HANDOFF_MEDIUM_WORKFLOW.md
git diff --no-index --check /dev/null IMPLEMENTATION_PLAN_LATEST.md
```

The ASD screen selected only this appended section from `git diff --no-index` output.
It passed that text to `python3 .claude/skills/asd-ste100/scripts/ste-lint.py --json` through stdin.
The first screen reported four synonym findings. The worker fixed them.
The repeated screen returned exit 0 with no findings, without baselines or disabled rules.
Manual review also checked instruction length, paragraph structure, and modality.
This screen does not certify the official lexical dictionary or rewrite historical prose.

At `2026-11-10T04:36:04Z`, the residual-process projection returned exit 0:

```sh
ps -C node,npm,tsc,opencode,python3,python,sh -o pid,ppid,stat,etimes,comm
```

It showed no owned validation process. All synchronous checks returned before that observation.
The remaining OpenCode PID was `2655255`, with elapsed time 977 seconds.
Other listed Python and shell processes also preceded this assignment.
The worker did not start or stop those processes.
The same observation showed unchanged staged deletions and the original dirty-tree inventory.
Earlier progress messages estimated elapsed time too high. The measured interval was about five minutes after dispatch at this observation.
This timing correction changes no runtime evidence or verdict.

## Namespaced lifecycle and normal startup correction (2026-11-10)

Status: implementation self-check, not independent PASS. The user accepts Review1 prose corrections, not independent qualification.
This section supersedes prospective launcher and scan-suppression requirements in earlier receipts. Historical evidence above remains unchanged.

The parent authorized four internal skill names with the `huron-` prefix.
Public commands remain `/design-plan`, `/prototype`, `/implementation-plan`, and `/implement-markdown`.
The fix uses activity code, role fix, profile medium, and configured effort medium.
The configured model is `openai/gpt-6-astra`. Provider acceptance remains not-proven.
Dispatch: `40769be9-6eb4-468d-9410-4cbabc7ec011`. Child: `ses_e3c40764affecapZy6xkTdTOOi`.
Claims are `*:write` and `build:agent-tools:write`. These claims coordinate exclusion, not permission.

### Exact changes

The four skill moves preserve their bodies and change only their frontmatter names:

| Old directory under `.agents/skills/` | New directory |
| --- | --- |
| `design-plan` | `huron-design-plan` |
| `prototype` | `huron-prototype` |
| `implementation-plan` | `huron-implementation-plan` |
| `implement-markdown` | `huron-implement-markdown` |

Each directory contains `SKILL.md`. No old generic skill alias remains in the repository lifecycle sources.
External generic skills remain discoverable but do not gain permission.

Other edited files:

```text
opencode.json
AGENTS.md
IMPLEMENTATION_PLAN_LATEST.md
HANDOFF_MEDIUM_WORKFLOW.md
.agents/README.md
.agents/commands/design-plan.md
.agents/commands/prototype.md
.agents/commands/implementation-plan.md
.agents/commands/implement-markdown.md
.agents/scripts/check-assets.mjs
.agents/scripts/check-resolved.mjs
.agents/scripts/opencode-project.sh
.agents/tests/assets.test.js
.agents/tests/launcher.test.js
.agents/workflows/orchestration.md
.agents/workflows/verification.md
```

The optional shell script only forwards arguments, exit status, signals, and the existing environment.
Normal startup uses `opencode` from the repository root. No launcher or suppression flag is required.
The checker sets no suppression flags. It permits unrelated discovered skills and checks all thirteen approved skill sources.
The seven area skills and two additional approved sources retain their registrations and permissions.
The four namespaced lifecycle skills replace the four generic allow rules. All other permission boundaries remain unchanged.

Existing parametrized CLI fixtures cover normal startup, unrelated external skills, and each missing, duplicate, or noncanonical lifecycle source.
They also reject permission grants for each old generic alias.
The fixtures assert that all three suppression variables remain absent in checker subprocesses.
The obsolete suppression-prerequisite test was removed, not skipped.
Forwarding tests now require environment preservation instead of suppression.

No dispatcher code, profile default, admission rule, progress rule, recovery rule, or journal format changed.
No global skill, product file, dependency, service, container, or journal was modified.
The worker performed no delegation, real dispatch experiment, setup, download, commit, resume, or cleanup of unknown data.

### Gates and evidence

Versions: Node `26.10.0`, npm `11.19.1`, OpenCode `1.18.35`.
Terminal tool records contain command outputs. Raw provider configuration and skill bodies were not printed.

From `.agents/`:

```sh
npm run check
npm test
env -u OPENCODE_DISABLE_EXTERNAL_SKILLS -u OPENCODE_DISABLE_CLAUDE_CODE_SKILLS -u OPENCODE_DISABLE_CLAUDE_CODE node scripts/check-resolved.mjs
```

All three commands returned exit 0. The tests reported 129 passing, zero failing, zero cancelled, zero skipped, and zero todo.
The checker invoked these normal CLI commands from the repository root:

- `opencode debug config`: canonical dispatcher, commands, prompts, and explicit source registrations.
- `opencode debug agent NAME`: all seven workflow agents, with exact profiles and retained permission boundaries.
- `opencode models openai --verbose`: low, medium, and max registry mappings.
- `opencode debug skill`: all thirteen approved sources, including the four namespaced lifecycle sources.

Each CLI invocation returned exit 0. The checker prints safe summaries only and removes its private diagnostic capture.
Twelve additional serial `opencode debug skill` scans each returned exit 0 and sixty skills.
All twelve selected the four canonical namespaced sources.
Each scan also discovered `graphify`, `research`, and external `prototype`.
These scans removed the same three variables and used anonymous memory descriptors for safe name/location projections.
Repeated scans are observed evidence, not proof against future same-name external copies.

Root `git diff --check` returned exit 2 solely for existing `web/src/lib/api/openapi.ts:170` trailing whitespace.
The cached check and scoped `.agents opencode.json AGENTS.md` check returned exit 0.
The six-path `git check-ignore -v` command from the preceding receipt returned exit 0.
`git ls-files -- roadmap` returned exit 0 with no output.
The protected-history hashes above matched exactly, including HEAD, the old plan, migration 0003, and all four protected documents.
The staged deletions remain three files and 500 lines. Initial product changes remain untouched.

The asset gate checks moved skill links, frontmatter, command references, templates, and the exact allowlist.
Product, frontend, browser, and site gates do not apply to this tooling-only correction.
The assigned offline links, new-text whitespace, structural language, and final process checks complete this receipt below.

### Required activation

1. Record this worker's terminal response.
2. Reconcile children and owned processes.
3. Quiesce all invocations.
4. Quit and restart normal `opencode` from the repository root with the intended serving arguments.
5. Inspect the loaded schema, seven agents, and four canonical namespaced skills.
6. Arrange independent verification/review with explicit maximum profile and the complete applicable gate.

Do not start a competing server or dispatch through the stale runtime.
Fresh CLI evidence does not activate the serving process. This worker stops after self-check.

### Final limitation and preservation checks

The complete tooling gate passed again after the final code changes: 129 tests, no failures or skips.
The required six-document offline link command returned exit 1 for five historical links:

```text
HANDOFF_M11_PLAN.md: .agents/skills/implementation-plan/SKILL.md
HANDOFF_M11_PLAN.md: .agents/skills/design-plan/SKILL.md
design/m11-review-evidence.md: ../.agents/skills/design-plan/SKILL.md
design/m11-review-evidence.md: ../.agents/skills/prototype/SKILL.md
design/m11-review-evidence.md: ../.agents/skills/implementation-plan/SKILL.md
```

Those documents have protected historical hashes. The assignment also prohibits old generic aliases.
The worker preserved both constraints and reported the conflict to the parent immediately.
The parent must reconcile these historical references before complete qualification.
The worker did not rewrite receipts, restore aliases, or weaken the link checker.
This is a new link-gate failure caused by the authorized moves, not an infrastructure failure or a passing gate.
The tooling implementation is complete, but full acceptance remains BLOCKED by this conflict and pending independent review.

The new-text checks covered this handoff, the latest plan, and each of the four moved skill files.
Each returned exit 1 for additions, with no whitespace diagnostics.
The final scoped and cached whitespace checks returned exit 0.
The initial dirty product inventory and staged deletions remain unchanged.

The structural language helper is `/tmp/opencode/normal-startup-language.py`, outside the repository.
It checks the new policy paragraphs and this appended receipt with the canonical ASD linter.
An initial run found one semicolon in the touched README context. The worker split that sentence and repeated the check.
The repeated check returned exit 0 with zero hard findings, without baselines or disabled rules.
Passive-voice advisories remain for status descriptions. Manual inspection checked short instructions, paragraph structure, and preserved modality.
This is not official dictionary certification or independent language review.

At `2026-11-10T04:43:43Z`, the final serial process projection returned exit 0 and showed no owned validation process.
The projection was `ps -C node,npm,tsc,opencode,python3,python,sh -o pid,ppid,stat,etimes,comm`.
All synchronous checks returned before that observation. Existing OpenCode PID `2655255` and older Python/shell processes remained untouched.
