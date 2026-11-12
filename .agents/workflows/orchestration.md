# Orchestration contract

Main sessions coordinate scope, decisions, ownership, dispatch, progress and
synthesis. Delegate nearly all research, planning, prototype work, coding, baseline
checks and independent review. Workers do not delegate. Explicit user scope can
assign a worker-only turn; such a turn performs its own assignment and self-checks
without spawning nested agents or claiming independent verification.

## OpenCode readiness and dispatch

The default primary and lifecycle commands remain Low `markdown-orchestrator`.
All seven workflow agents use `openai/gpt-6-astra`. Never substitute models.
`preparatory` selects Low, `medium` selects Medium, and `maximum` selects Max,
with variant and reasoning effort `low`, `medium`, and `max` respectively.

Each role's counterparts share the same prompt and permissions. Ordinary code,
fixes and reviews use explicit medium. An explicit maximum assignment stays Max.
Final complete qualification explicitly uses verification/review/maximum.
Preparatory and Medium reviews are not final complete qualification.

For a new classified request, omitted profile defaults to medium.
When a request supplies neither activity nor claims, an omitted profile defaults to maximum for legacy-exclusive. Explicit
medium or maximum may be legacy-exclusive. The dispatcher rejects Low for code and legacy-exclusive
before journal or API effects.

Reject an unavailable selected capability.
Never silently substitute another capability. Never claim prompt wording changed provider effort.

Check actual tool availability before dispatch: the local plugin exposes
`implementation_start(role, title, prompt, activity?, claims?, profile?)` and
`implementation_status(sessionID?)`. Quit and restart OpenCode after plugin, prompt
or skill changes; the loaded schema and effort enforcement remain unchanged until restart.
If launch/status is missing, stop delegation and report the need to restart or use
an explicitly agreed runtime. Prompts cannot expose tools. Other hosts must inspect
their actual native asynchronous schemas and record supported model settings;
do not invent tool aliases or assume OpenCode tools exist there.

Role controls agent permissions; activity controls scheduling, not edit authority:

| Assignment | Role | Activity | Agent |
| --- | --- | --- | --- |
| Read-only discovery or baseline | `verification` | `discovery` | `markdown-reviewer` |
| Independent review | `verification` | `review` | `markdown-reviewer` |
| Planning/document synthesis | `implementation` or `fix` | `planning` | `markdown-implementer` |
| Isolated ignored throwaway experiment | `implementation` or `fix` | `prototype` | `markdown-implementer` |
| Actual source/config/tooling/test implementation or fix | `implementation` or `fix` | `code` | `markdown-implementer` |

The table names the Low counterparts. Medium selects the `-medium` suffix and
maximum selects `-max`. Actual code uses Medium or explicitly assigned Max. Record
requested/recorded profile and configured effort separately from observed model.
Receipt/status `providerAcceptance: not-proven` is not a provider effort measurement.
Final complete qualification uses `markdown-reviewer-max`, even when read-only.

Use a complete [assignment](../templates/assignment.md) each time. Reviewer edit
and delegation tools are denied. Shell checks retain existing permissions: this
is **not an OS-level read-only sandbox**; the assignment must prohibit edits via
shell too, except normal ignored check artifacts. Do not widen permissions to
make a check work.

## Admission, recovery and polling

Actual code is exclusive against ALL workers, reviewers and competing checks in
both admission orders. Non-code activities may overlap only when all exact claims
are nonconflicting. Same-subject writer → review → fix remains terminally sequenced.
Prototype activity permits only owned ignored throwaway paths and isolated resources;
live source/config/service mutation is code, even if called an experiment.

Every new dispatch supplies both activity and 1–32 unique claims of the form
`{ resource: 'plan:dispatch', mode: 'read' | 'write' }`. Names match
`^(\*|[a-z][a-z0-9:._-]{0,95})$`. The parent maintains one canonical resource dictionary
mapping labels to exact files, services, browser profiles, ports and check outputs.
Same labels (or `*`) conflict if either side writes; read/read may share. Prefixes,
paths and aliases are NOT inferred. Subject reviewers use their writer's label.
Every `.agents` npm-test invocation claims `build:agent-tools:write`; ignored output
still mutates shared state. Uncertain independence requires `*:write` or code.
Omitting BOTH fields preserves `legacy-exclusive` for every role; partial/invalid
classification rejects. Claims are cooperative coordination, not a sandbox.

Use one coordinating parent and the existing local server; all workflow starts go
through this plugin. Never bypass with Task, a second server, manual child resumes
or outside edits/checks racing admitted work. Workers cannot escalate classification
or resume themselves. Stop and reconcile with the parent if scope needs to change.

The private worktree `.agents/.dispatch-state/` journal and exclusive-create lock
coordinate all parents/instances. Admission reconciles current/recorded parents,
recorded children and additional `session.list` discoveries. Enumeration is not
proof of arbitrary unregistered history. Unknown active children, missing recorded
children, API errors, corrupt state and incomplete creation block all starts.
Dispatch uncertainty blocks until actual terminal evidence; no automatic create or
prompt replay. Completed records remain so resumed turns regain original claims.
Do not delete journal data or steal locks by age/PID. Stale lock/incomplete create
maintenance requires explicit human authorization, stopped invocation/process evidence
and child reconciliation; there is no force-unlock/recovery tool. Quiescent ordinary
plugin recreation reads durable claims automatically. This is local coordination,
not a multi-host scheduler or guaranteed NFS/power-loss protocol.

New dispatch records/envelopes are v2 with required profile, inside the v1 ledger
container. Valid old v1 records remain unchanged, report `not-recorded`/configured
null and never gain invented Max provenance. Quiesce and restart before v2 writes:
v1-only readers cannot read v2, and older two-profile readers reject Medium v2 records.
Do not mix launchers. New Medium records require all these conditions:

- All workers are terminal.
- The parent reconciled owned processes.
- OpenCode quit/restarted from the repository root with normal `opencode`.

Reads never apply new-request defaults to history. No destructive migration, backfill
or silent rollback. A tooling writer stops after its self-check. Independent Maximum
qualification follows the parent's restart, not another dispatch in the stale runtime.

Record the returned session ID immediately, then poll at least once per minute
using bounded waits. Relay progress promptly and at least every 15 minutes; keep
the parent turn active rather than blocking on Task. Maintain task, role/attempt,
model settings, start/last-update time, current command, verdict and remaining work.

After an interrupted launch, omit `sessionID` to discover direct children and
inspect the existing session. Idle alone, API errors, timeout, missing final text
and ambiguous dispatch are indeterminate. Terminal response evidence is necessary
but errors/final text are not automatically PASS. Inspect surviving processes
before replacement; never delete/abort a healthy child to evade admission.
An overdue update requires reporting the last observed activity and checking
liveness; if unavailable, say unknown, not working or stuck.

Status/list expose only the caller's direct children and validated ownership or
`unknown`. Progress is the latest meaningful assistant text from 100 messages,
bounded to 4,000 characters with message ID, original timestamp and truncation flag;
recentTools is at most 20 safe name/status/ID/timing projections. Earlier progress
survives empty/user turns but is NEVER terminal evidence. Existing text/tools are
actual-last-assistant projections. Terminal requires idle + completed assistant +
stop/error, not busy/retry/tool-calls/length/user turns. Errors are not PASS. Tool
titles, input/output, reasoning and raw retry/error data are omitted. Assistant text
is sensitive: never put credentials in progress; arbitrary secret redaction is not
promised. Record observedAt and progress age, not fabricated freshness.

## Progress contract (paste verbatim into every assignment, including resumes)

Every implementation, fix, and verification subagent must send a brief progress update at least every 15 minutes of elapsed time while its assignment remains active, including during validation. Send blockers, repeated failures, and suspected hangs immediately rather than waiting for the next interval. These are progress messages, not final implementation reports or verification verdicts. Keep each update to 2-4 short lines containing the phase/task, agent role and attempt number, elapsed time, concrete progress since the previous update, current operation or command, and the next step or blocker. If nothing has advanced, say so and identify the last observed activity; do not substitute 'still working' for evidence. Parent polls asynchronously at least once per minute.

Confirm intermediate progress can actually be observed before launch. If the
runtime cannot deliver it, disclose the limitation and obtain an explicit
checkpoint/resume alternative. Do not cancel healthy validation just for updates.
