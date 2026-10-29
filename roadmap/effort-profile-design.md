# Design and local roadmap: fixed Astra effort profiles

## Goal, scope and authority

Allow cheap preparation without authorizing Low actual-code children. All actual-code
implementation/fix children and final complete qualification use Astra maximum effort.
Add one `profile: preparatory | maximum` selector, not a model picker or scheduler.
This ignored document and the [phase plan](plans/astra-effort-profiles.md) are proposals,
not shipped behavior. The worker owns only these documents and
`roadmap/prototypes/effort-profile/`. Live source/config/tests/docs, runtime journal,
services and shared caches are untouched. Claims are cooperative, not a sandbox.

## Verified current state

Inspected on 2026-10-05 (no live server/model calls):

| Claim | Evidence | Classification |
| --- | --- | --- |
| Three agents force Low | `opencode.json` agents; `implementation.ts` configuredAgent/chat.params/start receipt; check-assets/check-resolved assertions | Implemented |
| Activity/claims scheduling is independent of model settings | `dispatch-state.ts` normalizeDispatch/claimsConflict and real filesystem tests; implementation reconciliation tests | Implemented |
| Original injected SDK accepts `agent`, not typed prompt `variant` | PluginInput.client imports original SDK; SDK 1.17.18 SessionPromptAsyncData body lines 2329–2343 | Implemented |
| Agent and model API types lag current fields | Original Agent lacks variant; original model types lack variants; runtime extension must be narrowed from unknown | Verified type limitation |
| Current schema supports agent variant/options | Official configuration schema AgentConfig; official agents documentation | Supported configuration surface, not paid execution proof |
| Registered Astra `max` maps to `reasoningEffort: max` | Parent-supplied independent discovery ses_ef5b3f3d9ffeR5DL19194wlcH1 reports CLI 1.18.34 registration | External receipt; not independently re-observed by this isolated probe |
| Full untouched agent baseline passed 55 tests | Same discovery receipt: Node 22.23.2 check/test/safe resolved checks and diff check | Prior independent baseline, not this worker's rerun |

Initial `git status --short` and `git diff --stat` captured in this worker's tool
evidence: broad existing tracked modifications/deletions (242 tracked paths in the
stat), untracked `.agents` tooling and catalog interface scaffolding. None is owned
for edits here. The new owned document/prototype paths were absent when inspected.
Do not reset any of that work or touch `.agents/.dispatch-state/`.

## Target and alternatives

Fixed mapping: preparatory selects the existing implementer/reviewer Low agents;
maximum selects new `markdown-implementer-max` / `markdown-reviewer-max` agents.
The existing orchestrator stays Low. The new agents reuse counterpart prompts and
exact permissions; only name, description, variant and effort differ. Omission
defaults to maximum, including legacy-exclusive calls. Explicit preparatory code
or legacy-exclusive requests reject before journal reservation or remote create.
Preparatory is allowed only for explicitly classified non-code work.

The plugin owns input normalization, capability checks, payload/receipts and exact
chat.params enforcement. The existing journal owns historical identity, admission
and durability. New v2 records require profile; historical valid v1 records retain
their original representation and are projected as `not-recorded`, never Max.
No automatic conversion, historical replay, delete, lock theft or model fallback.
Final complete qualification explicitly requests verification/review/maximum;
there is no heuristic interpretation of assignment prose or additional selector.

Rejected: untyped prompt variant injection (unnecessary API mismatch), SDK v2
migration (unrelated scope), arbitrary effort/model options (bypass surface), changing
all existing agents to Max (eliminates preparation), defaulting omitted profile to
Low (legacy bypass), retroactively normalizing old records to Max (false evidence).

## Phase sequence

One coherent live tooling slice after independent design/probe/plan review:
parent-owned narrow bootstrap, static/deterministic full gate, quiescent quit/restart,
actual loaded-schema and Max smoke evidence, then independent Max complete review.
The current launcher forces Low, so no Low code child is permitted to bootstrap it.
Future code/fix dispatches are exclusive against all work; preparation/review are
terminally ordered for their subject. Exact claims, files and gates are in the plan.
No service, application or documentation-site implementation is included.

## Prototype questions and evidence

Question: can the installed original SDK carry fixed Low/Max agent selection without
a prompt variant field, and can a minimal fail-closed profile contract be expressed
using the installed generated tool schema? Hypothesis: yes; no dependency migration.

Owned non-production inputs: `probe-api.mjs` and `probe.mjs` under
`roadmap/prototypes/effort-profile/`. In-memory synthetic fixtures only; injected
mock HTTP is the sole SDK I/O boundary. No listener, live server, child, model call,
production import, build output, credentials or mutable global state. TypeScript is
invoked with `--noEmit`; installed node_modules are read only.

Reproduce from repository root, Node 22.23.2, SDK/plugin 1.17.18:

```sh
/home/karl/.nvm/versions/node/v22.23.2/bin/node --test roadmap/prototypes/effort-profile/probe.mjs
```

Acceptance: six tests cover actual SDK serialization for three roles × two profiles,
typed payload acceptance, generated enum rejection, code/legacy downgrade refusal,
malformed configured-agent/capability refusal, historical absence projection, and
owned links/whitespace/plan headings. The capability fixtures deliberately model
`variants.max.reasoningEffort === 'max'`; missing/wrong/disabled mappings fail.

Observed writer self-check: the command above exited 0, **6 passed / 0 failed /
0 skipped**, about 0.52 seconds total (including the no-emit typed API check).
Root `git diff --check` exited 0; `git check-ignore -v` reported `.gitignore:40`
for both documents and the prototype directory; `git ls-files roadmap` exited 0
with empty output. These are isolated self-check results, not independent review.

Concrete typed request (illustration, not production implementation):

```ts
await client.session.promptAsync({
  path: { id: "synthetic-child" }, query: { directory: "/isolated/probe" },
  body: { agent: "markdown-implementer-max",
    model: { providerID: "openai", modelID: "gpt-6-astra" },
    parts: [{ type: "text", text: "Synthetic API probe" }] },
  throwOnError: true,
});
```

This proves transport shape/type feasibility and the proposed small decision rule,
NOT running-server registration, actual provider acceptance of Max, delivered
reasoning intensity, production validation, scheduler correctness, fsync/locking or
crash recovery. Historical preservation here is a frozen-object projection concept,
not a substitute for production real-journal tests. No prototype imports in production.

## Decisions and blockers

Use fixed agents and v2 records with explicit read-preservation of valid v1 records.
Keep ledger container version 1; document the mixed record versions and require
quiescence/restart (old readers will fail closed on v2). Do not edit old runtime data.
Runtime capability failure is blocking, never grounds to substitute `high`, another
model, SDK, permission set or server. Parent owns operational reconciliation.

Independent review is pending. Full production execution remains gated on reviewed
plan, complete baseline, authorized parent bootstrap and restart; actual Max provider
dispatch cannot be proven by the current Low tools or this mock probe.

## Review and next step

This writer self-check is not independent review. Parent dispatches read-only review
of both owned documents/probe after writer termination, then records findings and
at most three reviews in the phase ledger. Cleanup belongs only to the explicit
prototype owner; preserve unknown data. No automatic promotion, commits or issues.
The Starlight/docs checker heading mismatch is separate: this plan intentionally
uses `## Serial task slices`, which the existing local checker accepts; neither
checker nor template is edited by this planning slice.

References inspected: [official schema](https://opencode.ai/config.json),
[agents](https://opencode.ai/docs/agents/) and
[plugins](https://opencode.ai/docs/plugins/).
