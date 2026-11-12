# Repository agent assets

[AGENTS.md](../AGENTS.md) is the sole repository instruction file. This directory
contains the canonical skills, command prompts, shared workflows and agent tooling.

OpenCode's root [configuration](../opencode.json) explicitly registers `commands/`,
`plugins/implementation.ts` and `skills/`; it does not depend on automatic discovery
of a tool-specific project directory. Command metadata belongs in that configuration;
the command Markdown files contain prompt bodies.

Do not keep legacy dispatcher plugins or lifecycle commands under `.opencode/`.
OpenCode discovers both singular and plural plugin and command directories there.
Those definitions can override the explicit registrations on every restart.
The asset and resolved-config checks reject these legacy entrypoints.
Keep backups outside OpenCode's discovery directories.

`/implement-markdown PLAN.md` reads [the shared workflow](workflows/implement-markdown.md).
It uses seven fixed `markdown-*` agents on Astra:

- Low serves explicit preparation.
- Medium serves ordinary code/fixes/reviews.
- Max serves explicitly selected assignments and final complete qualification.

The default primary remains Low
`markdown-orchestrator`. The lifecycle is `/design-plan` → `/prototype` →
`/implementation-plan` → `/implement-markdown`; all four commands load canonical
local skills. Read [orchestration](workflows/orchestration.md) and
[verification](workflows/verification.md) before dispatch. Reusable
[templates](templates/) define assignments, evidence and self-contained phases.

Local roadmaps, prototypes, plans and evidence live under ignored `/roadmap/`,
with phase plans in `/roadmap/plans/`. No tracked asset or test requires an ignored
plan to exist in a fresh checkout. Durable decisions stay in `design/` and terms
in `CONTEXT.md`. Legacy plan relocation requires its own assigned slice.

## Canonical skills and permissions

Retained capability skills: `oop-design`, `fastapi`, `postgresql-table-design`,
`svelte-code-writer`, `svelte-core-bestpractices`, `tailwind-design-system`, and
`playwright-cli`. Lifecycle skills: `huron-design-plan`, `huron-prototype`,
`huron-implementation-plan`, `huron-implement-markdown`. These eleven use `.agents/skills`.
The four public slash commands keep their unprefixed names. No generic lifecycle skill aliases remain.
Two additional approved sources are explicitly registered, without vendor copies:

- `writing-for-agents`: `~/.agents/skills/writing-for-agents/SKILL.md` (including
  its skill-mechanics reference before skill edits).
- `asd-ste100`: `.claude/skills/asd-ste100/SKILL.md`.

The portable `~/` path resolves at startup to that workstation's home directory.
Missing sources are actionable blockers. Supply the approved source. Restart OpenCode.
Do not widen explicit source registrations or use a permissive fallback. Playwright's adapted official
1.62.1 source and references are documented in its
[provenance](skills/playwright-cli/PROVENANCE.md).

`permission.skill` defaults to deny, allowing only these thirteen skills and built-in
`customize-opencode`. Skill permissions match names, not paths: verify resolved
locations after reload and use the canonical files explicitly. Global copies stay
untouched. The old issue/spec/ticket lifecycle is retired. `skills-lock.json` retains
only the still-applicable upstream Tailwind entry; locally authored/adapted assets
are maintained here, not attributed to obsolete installer hashes.

Normal startup retains external skill discovery. Discovery does not grant permission to load a skill.
Unrelated external skills do not fail the checker. The required skills must still resolve to their approved sources.

The plugin's config hook suppresses inherited `architectural-review` and
`execute_plan` commands for this project; use the local design/revision and
implementation lifecycle instead. It preserves unrelated global commands and
never edits global configuration or skills.

## Setup

Use a Node version satisfying `package.json`'s engine range (required by the locked
tool dependencies). Run `npm ci --ignore-scripts` from `.agents/`.
With cached packages, use `npm ci --offline --ignore-scripts --no-audit --no-fund`.
An installation under `.opencode/` does not supply the canonical tooling's dependencies.
After workers and owned processes are quiescent, quit and restart OpenCode from the repository root:

```sh
opencode
```

No launcher or external-scan suppression flag is required.
The optional `scripts/opencode-project.sh` only forwards arguments, exit status and signals.
The Huron lifecycle namespace avoids collisions with generic external lifecycle names.
Same-name copies can still collide, so check required source locations after restart.
Keep existing serving arguments when restarting an owned `serve` or `web` process.
Do not start a competing server. Fresh CLI checks do not activate an existing serving process.

Configuration and the local plugin are loaded at startup. The OpenAI provider must already have
access to `gpt-6-astra`; this project does not install credentials or substitute
another model. Inspect configuration from the repository root with
`opencode debug agent markdown-orchestrator`
and the corresponding implementer/reviewer names.

## Dispatch and polling — restart required

**Quit and restart OpenCode to load the profile-aware schema. Running sessions
retain their previous schema and effort enforcement.** Roll out only after existing workers and owned
processes are quiescent, with one coordinating parent and one existing local server.

- `implementation_start(role, title, prompt, activity?, claims?, profile?)` creates one child of the current
  orchestrator and submits the complete assignment asynchronously. Roles are
  `implementation`, `fix`, and `verification`. Planning/prototype writes use
  `implementation`; read-only discovery and baselines use `verification` as well
  as independent reviews. Record its `sessionID` and `dispatchID` immediately.
  Explicit activity is `code`, `planning`, `prototype`, `discovery`, or `review`;
  discovery/review require verification, the other activities implementation/fix.
  Actual code is exclusive against every worker/check in either order. Non-code
  overlaps only with nonconflicting claims. Omit both fields for `legacy-exclusive`;
  partial/invalid arguments reject, never infer activity from assignment prose.
- `profile` is `preparatory` (Low), `medium` (Medium), or `maximum` (Max).
  New classified requests without a profile default to medium.
  When a request supplies neither activity nor claims, its omitted profile stays maximum for legacy-exclusive.
  Explicit medium or maximum may be legacy-exclusive. Exclusion stays the same.
  Actual code and legacy-exclusive reject preparatory before journal/API effects.

  Final complete qualification must explicitly request maximum with verification/review.
  The fixed Medium/Max implementer/reviewer agents share their counterparts' exact prompts
  and permissions. Capability checks refuse absent/disabled/mismatched registered
  variants before reservation. There is no fallback or arbitrary model selector.

  The installed SDK's `promptAsync` has no typed variant field. Dispatch uses the
  fixed agent. The `chat.params` hook enforces that agent's exact reasoning effort.
  Native OpenCode children retain parentID, asynchronous submission and navigable IDs.
- Receipts contain `configured` profile/agent/model/effort and
  `providerAcceptance: 'not-proven'`, including uncertain dispatch outcomes. Status
  keeps observed assistant model separate; model identity does not prove reasoning
  effort. Historical v1 records report profile `not-recorded` and configured `null`.
- Claims are 1–32 unique `{resource, mode: 'read' | 'write'}` entries, names matching
  `^(\*|[a-z][a-z0-9:._-]{0,95})$`. Parent owns an exact resource dictionary mapping
  labels to file/service/artifact ownership. Equal labels or wildcard conflict when
  either writes; no path globs/prefix semantics/alias detection. Claim shared check
  output (e.g. `build:agent-tools:write`) too. Uncertain scope uses `*:write` or code.
  Claims are cooperative coordination, not a sandbox or edit permission.
- `implementation_status(sessionID)` returns observed session state, recent
  assistant text, tool names/status/timestamps, and terminal-response evidence.
  `progress` retains latest meaningful text in the last 100 messages, at most 4,000
  characters with message ID/timestamp/truncation; `recentTools` retains at most 20
  name/status/ID/timing projections. `observedAt` is polling time, not progress time.
  Existing `text`/`tools` project the actual last assistant only. Earlier progress
  never establishes terminal truth. No tool titles, inputs/outputs, reasoning or raw
  retry/error data are returned. Assistant text remains sensitive: do not include
  credentials; arbitrary secret redaction is not guaranteed.
- Omit `sessionID` to discover children after an interrupted launch. Polling is
  restricted to the caller's direct children, with validated ownership or `unknown`.
  The SDK uses the current server
  client and workspace, not a guessed localhost port or a second server.
- Poll at least once per minute with bounded waits, and relay a brief update to
  the user at least every 15 minutes. Polling tools are not an autonomous timer:
  the orchestrator must keep polling rather than finish its turn or block on Task.
- `idle` alone is not completion. Missing response evidence and ambiguous dispatch
  remain indeterminate. Unknown or uncertain ownership blocks every new launch;
  submitted nonterminal classified work retains its claims, including after reload.
  Errors and final responses are not automatic PASS verdicts. The orchestrator
  must inspect results and any surviving processes before replacement after errors.
- Verification agents cannot use the edit tool or launch nested tasks. Shell
  checks retain existing permissions; this is not an OS-level read-only sandbox.

The plugin does not abort, delete, or restart sessions, weaken permissions, or
change validation gates. If a child is indeterminate, inspect it in OpenCode and
resolve its state explicitly; do not delete it to evade admission. Prototype activity
is only for owned ignored throwaway experiments with isolated resources. Live code,
config or service mutation requires exclusive code. Reviewers stay read-only except
normal ignored check outputs. Workers may not escalate classification or resume;
parents must not manually resume or run outside checks racing admitted work.

## Durable state and recovery

`.agents/.dispatch-state/` is private runtime data, not disposable build output.
Never commit this directory, `.agents/.dispatch-archive/`, or `.agents/.test-build/`.
The asset check rejects tracked copies, even when ignore rules cover their paths.
An authorized recovery may preserve a copied journal under `.agents/.dispatch-archive/`.
Do not replace a journal's worktree or session identities to make it pass validation.
The ledger container stays v1. New records/envelopes are v2 and require a profile;
valid historical v1 records remain unchanged and must not acquire invented profiles.
Reads never migrate state. Appending under admission preserves old record values.
V1-only readers reject v2. Older two-profile readers also reject Medium v2 records.
Before any new Medium record or further dispatch:

1. Quiesce all invocations.
2. Reconcile owned processes.
3. Quit/restart OpenCode.

Do not mix launchers. Do not erase the journal. Do not backfill history.
This workflow prohibits silent rollback. New-request defaults never apply to reads.

After tooling edits, the writer stops at self-check. The parent restarts before the
independent Maximum qualification. The current serving session does not change effort.
The journal validates version/worktree/records, persists reservations before remote
create, then dispatching before prompt and submitted after acknowledgement. File and
directory fsync plus atomic rename persist records; an exclusive-create lock with
an owner token spans admission. Symlinks, unsafe modes, corrupt/unknown artifacts,
missing recorded children and uncertain API responses fail closed. Locks are never
stolen by age/PID; requests have 30-second abort signals, not replay logic.

`creation-indeterminate` returns the dispatch ID; `dispatch-indeterminate` also
returns known child ID. Never retry remote create/prompt automatically. Reconcile
existing children/processes first. Ordinary plugin recreation reads durable records,
including completed ones: resumed turns regain original claims. Additional session
listing helps find unknown children but proves no globally complete history.
Stale locks/incomplete creation require explicit human-authorized maintenance after
proving stopped invocations/processes and reconciling children. No force unlock,
automatic garbage collection, abort/delete or recovery tool is provided. Cross-parent
admission errors reveal no other parent's identity/claims; polling remains direct-only.

## Validation

From `.agents/`:

```sh
npm run check
npm test
```

Tests use the real SDK against a simulated HTTP boundary; they make no model calls.
The test command compiles the plugin with the locked TypeScript compiler before
running the existing Node tests, so it does not depend on native TypeScript loading.
They prove fixed-profile dispatch payloads, downgrade rejection, historical record
preservation, progress bounds/privacy, model enforcement, exclusive
code and conflict admission, durable uncertainty and parent isolation. Real filesystem
and subprocess tests prove local lock ownership/recreation and crash-lock refusal,
not live server completeness, worker compliance or power-loss portability. Asset checks cover
command/skill/template references, the exact approved skill sources and the allowlist.
A live model run is a
separate smoke test and consumes provider quota.

After changing registration, inspect the resolved commands and workflow agents with
`opencode debug config` and `opencode debug agent markdown-orchestrator`.
Keep any credential-bearing provider configuration out of shared diagnostic output.
Use the safe checker below.

From `.agents/`:

```sh
node scripts/check-resolved.mjs
```

This checks the single canonical dispatcher, resolved commands, workflow agents and canonical skill locations
while printing only safe summaries. Run it without external-scan suppression flags.
The checker does not set suppression flags. It permits unrelated discovered skills without granting skill permissions.
It invokes fresh installed OpenCode CLI processes and makes no child/model calls.
Success proves their inventory, not the active serving process or its cached skills.
Always quit and restart normal OpenCode after config, plugin, prompt or skill changes.
The running session keeps the previously loaded tools and permissions.
The legacy `.claude/commands/implement-markdown.md` is not the resolved OpenCode
entrypoint. It remains outside this migration. Do not re-enable it as a dispatch bypass.

References: [configuration schema](https://opencode.ai/config.json),
[plugins](https://opencode.ai/docs/plugins/), and
[asynchronous prompts and session status](https://opencode.ai/docs/server/).
