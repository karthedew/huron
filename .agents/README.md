# Repository agent assets

[AGENTS.md](../AGENTS.md) is the sole repository instruction file. This directory
contains the canonical skills, command prompts, shared workflows and agent tooling.

OpenCode's root [configuration](../opencode.json) explicitly registers `commands/`,
`plugins/implementation.ts` and `skills/`; it does not depend on automatic discovery
of a tool-specific project directory. Command metadata belongs in that configuration;
the command Markdown files contain prompt bodies.

`/implement-markdown PLAN.md` reads [the shared workflow](workflows/implement-markdown.md).
It uses fixed `markdown-*` agents on Astra: Low for explicit preparation, Max for
actual code and final complete qualification. The default primary remains Low
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
`playwright-cli`. Lifecycle skills: `design-plan`, `prototype`,
`implementation-plan`, `implement-markdown`. Read the actual local files; no home
copy or node_modules symlink is a project dependency. Playwright's adapted official
1.62.1 source and references are documented in its
[provenance](skills/playwright-cli/PROVENANCE.md).

`permission.skill` defaults to deny, allowing only this local set and built-in
`customize-opencode`. Skill permissions match names, not paths: verify resolved
locations after reload and use the canonical files explicitly. Global copies stay
untouched. The old issue/spec/ticket lifecycle is retired. `skills-lock.json` retains
only the still-applicable upstream Tailwind entry; locally authored/adapted assets
are maintained here, not attributed to obsolete installer hashes.

The plugin's config hook suppresses inherited `architectural-review` and
`execute_plan` commands for this project; use the local design/revision and
implementation lifecycle instead. It preserves unrelated global commands and
never edits global configuration or skills.

## Setup

Use a Node version satisfying `package.json`'s engine range (required by the locked
tool dependencies). Run `npm ci --ignore-scripts` from `.agents/`. After workers and
owned processes are quiescent, quit and restart OpenCode **from the repository root
through the project launcher**:

```sh
sh .agents/scripts/opencode-project.sh
```

The launcher exports the supported `OPENCODE_DISABLE_EXTERNAL_SKILLS=1` before
`exec opencode "$@"`, forwarding arguments, exit status and signals without a wrapper
process. No executable-bit change is needed. In OpenCode 1.18.34, discovered skill
files are parsed concurrently and same-name resolution is not reliable precedence:
a home `prototype` can replace the canonical project skill even with `skills.paths`
configured. The flag disables automatic external `.agents`/`.claude` scans at home
and project scopes; the explicit `.agents/skills` registration still loads all 11
canonical skills. Global assets remain untouched. This addresses the current
external home-skill collision, not all possible duplicates: normal OpenCode skill
directories and additional configured skill paths can still introduce collisions.

**The flag must apply to the serving OpenCode process.** If using `serve` or `web`,
start that process through the launcher with its existing arguments after quiescing
and stopping the old owned instance; do not start a competing server. Attaching a
flagged client to an unflagged server does not change the server environment or its
cached skills. Installing the launcher or checking a fresh CLI does not activate
the fix in an already running session; serving-runtime activation remains pending
until quit/restart through the launcher and verification after restart.

Configuration and the local plugin are loaded at startup. The OpenAI provider must already have
access to `gpt-6-astra`; this project does not install credentials or substitute
another model. Inspect configuration from the repository root with
`sh .agents/scripts/opencode-project.sh debug agent markdown-orchestrator`
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
- `profile` is `preparatory` (Low) or `maximum` (Max); omission conservatively means
  maximum. Actual code and legacy-exclusive requests reject preparatory profiles.
  Final complete qualification must explicitly request maximum with verification/review.
  The fixed Max implementer/reviewer agents share their counterparts' exact prompts
  and permissions. Capability checks refuse absent/disabled/mismatched registered
  variants before reservation; there is no Low fallback or arbitrary model selector.
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
The ledger container stays v1. New records/envelopes are v2 and require a profile;
valid historical v1 records remain unchanged and must not acquire invented profiles.
Reads never migrate state. Appending under admission preserves old record values.
Old readers reject v2, so quiesce all invocations and restart before the first new
dispatch; do not mix old/new launchers, erase the journal or silently roll back.
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
not live server completeness, worker compliance or power-loss portability. Asset checks validate
command/skill/template references, local-only skill inventory and the allowlist.
A live model run is a
separate smoke test and consumes provider quota.

After changing registration, inspect the resolved commands and workflow agents with
the project launcher and `debug config` / `debug agent markdown-orchestrator` arguments.
Keep any credential-bearing provider configuration out of shared diagnostic output;
prefer the safe checker below.

From `.agents/`:

```sh
OPENCODE_DISABLE_EXTERNAL_SKILLS=1 node scripts/check-resolved.mjs
```

This checks actual resolved config, workflow agents and canonical skill locations
while printing only safe summaries. It rejects a missing or different flag before
any CLI invocation rather than silently setting it. It invokes fresh installed
OpenCode CLI processes and makes no child/model calls; success proves their
environment and inventory, not the active serving process or its cached skills.
Always quit and restart OpenCode through the launcher after config, plugin, prompt
or skill changes; the running session keeps the previously loaded tools and permissions.

References: [configuration schema](https://opencode.ai/config.json),
[plugins](https://opencode.ai/docs/plugins/), and
[asynchronous prompts and session status](https://opencode.ai/docs/server/).
