# Design and local roadmap: activity-aware dispatch

## Goal, scope and authority

User priority: more independent subagents, but actual code implementation/fix is
EXCLUSIVE: no other worker, reviewer or competing validation while code changes.
Planning, discovery, isolated throwaway prototypes and reviews may overlap only
when their declared read/write resources do not conflict. A review never races its
subject writer. These decisions are user-owned, not suggestions to relax safety.

This is planning/prototype writer attempt 1, not implementation or independent
review. Current runtime still serializes every child. Do not use the future schema,
Task, nested workers, a second server or prompt wording to bypass that guard.
Only new ignored dispatch-specific files are owned. Initial `git status --short`
showed extensive pre-existing tracked edits/deletions and untracked assets,
including all `.agents` plugin/tests/prompts/workflows, `opencode.json`, AGENTS and
product/docs work. `git ls-files roadmap` was empty. All that work is preserved;
the earlier Starlight planning files remain somebody else's pending review.

No application/domain changes, permissions/model changes, paid model calls, live
plugin/config edits, global edits, commits, branches, cleanup or promotion.

## Verified current state

| Claim | Evidence | Classification |
| --- | --- | --- |
| Roles conflate planning/prototypes with code | `.agents/plugins/implementation.ts` `implementation_start`; `.agents/README.md` polling table | Implemented |
| All children block another start until terminal | start loop over `session.children`; in-memory `launching` set | Implemented |
| Reload retains child discovery but not in-flight launch mutex | closure-local Set; existing recreation test checks a created child, not two plugin instances before creation | Implemented limitation |
| Status loses earlier progress during empty/latest tool or user turns | `snapshot` only reads `messages.data.at(-1)` | Implemented limitation |
| Astra Low, direct-child polling, nested denial and errors-not-PASS | plugin plus 11 dispatch tests; 4 asset tests | Implemented, untouched baseline still assigned to reviewer |
| SDK supports custom session metadata | Installed SDK `Session`, `SessionCreateData`, `SessionPromptAsyncData` have no such field | Unsupported; do not invent |
| Activity-aware concurrency | Isolated probe only | Planned, not available in loaded tools |

Read all four commands, four full lifecycle skills, four templates, AGENTS,
tooling guide, three workflows, testing/docstring/domain guidance, actual plugin,
all 15 tests, asset/resolution scripts and installed SDK/plugin declarations.
Built-in customize-opencode loaded. Official schema and plugin/server docs fetched:

- <https://opencode.ai/config.json>
- <https://opencode.ai/docs/plugins/>
- <https://opencode.ai/docs/server/>

Installed `@opencode-ai/plugin` and SDK are 1.17.18. The plugin's injected client
is v1; `session.create({query, body:{parentID,title}, throwOnError:true})`,
`session.promptAsync({path:{id},query,body:{agent,model,parts},throwOnError:true})`,
`session.children`, `session.messages`, `session.status`, `session.list` are real
APIs. `ToolContext.metadata` is tool display data, not a durable ownership store.
`PluginInput.worktree` provides the lock root. No config schema change is needed.

## Target and alternatives

Keep `implementation_start` and existing role routing. Add explicit `activity`
and `claims`, independent of role. Supported explicit activities: `code`,
`discovery`, `planning`, `prototype`, `review`. `code` includes actual product,
tooling, configuration or test implementation/fixes. A prototype is non-code for
scheduling only if throwaway, isolated, unpromoted and not modifying live sources
or shared services. Shared build artifacts count as write resources even for
read-only reviewers. Uncertain classification means exclusive, never inferred
from title/prompt. Old callers omitting both new fields retain exclusive behavior
for all roles, including verification. Explicit bad/partial inputs fail validation.

### Resource claims

`claims: Array<{resource: string, mode: 'read'|'write'}>` (1–32 unique entries).
Resource names are exact canonical labels, regex
`^(\*|[a-z][a-z0-9:._-]{0,95})$`; no glob/path resolution or filesystem enforcement
is claimed. `*` is workspace-wide. Equal labels (or either wildcard) conflict if
either claim writes. Read/read is allowed. Code/legacy-exclusive conflicts with
every active child, independent of labels. Parent owns one resource dictionary
mapping labels to concrete files, directories, service instances, check outputs,
browser profiles/ports and processes. Uncertain mapping must use `*:write`.
Aliases or labels for overlapping parent/child directories are prohibited by the
assignment contract; the plugin cannot detect false declarations.

Examples: two planning writers can share `repo-context:read`, while claiming
`plan:dispatch:write` and `plan:starlight:write`. A dispatch-plan reviewer claims
`plan:dispatch:read` and is blocked by that plan writer. Two reviewers running
`npm test` in `.agents` both need `build:agent-tools:write` and cannot overlap.
An isolated experiment owns `prototype:dispatch:write`; any shared service it
mutates is an additional write claim. No browser names alone prove independence.

### Durable ownership and atomic admission

Use one real-filesystem admission lock and journal at canonical
`<worktree>/.agents/.dispatch-state/`, ignored in the future implementation.
This is a managed-worktree coordination boundary, not a distributed scheduler or
security sandbox. One existing local OpenCode server; no remote/NFS lock guarantee.
All workflow dispatches in the worktree share it, across plugin instances and
parents. No memory-only authoritative lock/ownership and no lock TTL/stealing.

Acquire `admission.lock` with exclusive create (`open('wx',0600)`). Contention
returns bounded `admission-busy`; caller polls/retries, not an indefinite wait.
Hold through reconciliation, durable reservation, creation, prompt dispatch and
durable submitted transition; release only the lock this invocation created.
Realpath the worktree, reject symlinked state components, store no prompt/secrets.
Validate every persisted record strictly, reject unexpected versions, duplicates,
workspace mismatch or invalid state; never reset corrupt data to an empty ledger.
Use private atomic temp-write + file fsync + rename + directory fsync for journal
updates. Process/host failure leaving a lock, temp artifact, malformed journal or
unfinished reservation is an explicit block, never an automatic cleanup cue.

Versioned records retain dispatch ID, canonical worktree, parent/child IDs,
role/activity/claims, created timestamp and state (`creating`, `dispatching`,
`submitted`). Journal identity survives plugin recreation. Before remote create,
persist `creating` without child ID. After create, persist child ID and
`dispatching`; publish child identity using current context metadata, then send
prompt. Persist `submitted` only after HTTP acknowledgement. Missing/uncertain
create response leaves a durable unknown reservation and blocks every new start.
Missing/uncertain prompt acknowledgement leaves a known child but blocks all new
starts until terminal evidence reconciles it. Never replay creation or prompt
automatically. Lost final journal update is uncertainty, not submitted.

Journal is authoritative; prepend a strictly generated `HURON_DISPATCH_V1` JSON
envelope as the initial text part for audit/cross-check, not a writable session
metadata field. Assignment is the next text part. Unknown children/envelopes are
not reconstructed optimistically into parallel-safe ownership. Missing journal
with active children blocks, even if their text looks like a valid envelope.

Reconcile journal children by actual ID, and enumerate direct children of current
and recorded parents (including completed records' parents). `session.list` is an
extra discovery source for unknown child sessions, not proof of globally complete
history: v1 does not expose a paging contract. Unknown active/indeterminate child
in these sources blocks all starts, even if the proposed work is independent.
Do not discard terminal records: a resumed user turn makes a child active again
with its original claims. Do not cache terminal status as permanent completion.
API errors and missing/deleted recorded children block; absence is not completion.

Assumption/boundary: all concurrent work uses this admission path; parent never
resumes an old child, launches through another host/server, or edits/runs competing
checks outside declared coordination. Manual child resumes cannot be made atomic
with dispatch by this plugin; prohibit them while other workers are active, inspect
newly observed resumes and stop new dispatch. It is not an OS sandbox. These are
explicit limitations, not permission to ignore unexpected sessions. One existing
server and one coordinating main session are required at first rollout.

Stale lock or unresolved create requires human-authorized maintenance after proving
the original invocation/server and owned processes have stopped and reconciling
children. No automatic recovery/delete/abort or force-unlock tool in this slice.
Retain the evidence; do not treat age/PID absence alone as safe. Ordinary recreation
with submitted records needs no manual intervention. Terminal errors remain visible
and are never PASS; parent inspects residual processes before any replacement.

### Monitoring

Preserve terminal detection from the actual latest response and observed status:
idle + completed assistant + (`finish === 'stop'` or assistant error). Empty history,
user turn, tool-calls, length, busy, retry or API failure are not success. Completion
is not a review verdict. Old meaningful text is never terminal evidence.

Add `progress:{messageID,createdAt,text,truncated}|null` from the latest nonblank
assistant text in the last 100 messages, max 4,000 characters; `recentTools` from
those messages, max 20, with message/part ID, tool name, state and timestamps only.
Keep existing `text`/`tools` as actual-last-assistant projections for old monitors;
omit raw tool titles going forward because titles can embed arguments/secrets.
Do not return reasoning, raw input/output, tool metadata, error data or user text.
Assistant progress is still project-sensitive: no generic filter can guarantee
redaction of arbitrary secrets volunteered in text. Assignments forbid credentials
in progress. Return safe error names/status type, retry timing/count, not raw retry
messages. Include `observedAt`, `windowMessages:100`, truncation/age information,
durable activity/claims/dispatch state for authorized direct children. Listing
without ID remains direct-child only, now with safe ownership summaries; avoid
exposing other parents' IDs/claims in admission errors.

### Alternatives rejected

- Role-only parallel verification: still confuses planning and code and misses
  shared build outputs.
- Memory Set or global Symbol alone: races/recreation lose admission ownership.
- Envelope alone: no atomic reservation before `session.create`, cannot safely
  distinguish an unknown asynchronous dispatch.
- Arbitrary path globs: false precision without canonicalization, symlink and
  service-resource semantics; explicit labels are smaller and honest.
- Automatic stale-lock leases/abort/retry: risks double writers after slow I/O.
- New scheduler service/database/provider/model or broader permissions: unnecessary.

## Phase sequence

One exclusive tooling implementation slice followed by fresh read-only review,
at most three reviews; no live change in this assignment. Implement durable
admission/activity classification/progress and tests together, reconcile all
blanket-serial documentation, run complete tooling/docs gate, then require a quit
and restart. See the [self-contained phase](plans/dispatch-concurrency.md).
Only explicit compatibility: omitted classification stays exclusive and old status
fields remain actual-last-message fields (titles removed for confidentiality).

## Prototype questions

Can real SDK payloads and real local filesystem admission support safe independent
non-code overlap across recreation while preserving exclusive code, uncertainty
and direct-child progress? The [evidence](prototypes/dispatch-concurrency/evidence.md)
and isolated `probe.mjs` answer bounded state-model/adapter questions, not live
OpenCode durability, hidden session completeness, sandbox enforcement or production
correctness. No source promotion; reimplement using the phase contract and tests.

## Decisions and blockers

User owns exclusive-code and independent-non-code policy. Recommended exact-label
claims plus durable filesystem journal/lock satisfy the bounded local use case.
Parent/reviewer must independently review the design/prototype and run untouched
live tooling baseline before authorizing implementation. No model/config/permission
changes proposed. Rollout requires quiescent workers and a full OpenCode restart;
running tools do not change when docs/files change. Any demand for automatic recovery,
multiple coordinating servers or verified filesystem write confinement is a new
design slice, not an implicit extension here.

## Review and next step

READY-FOR-REVIEW means writer handoff only. Independent review not yet performed.
Parent should dispatch a fresh read-only reviewer through the currently serial
runtime after this worker is terminal. Reviewer owns untouched live tooling baseline
and independent prototype/planning gate reruns; maximum three reviews. If accepted
and baseline green, authorize `/implement-markdown roadmap/plans/dispatch-concurrency.md`.
No target concurrency is presently claimed available.
