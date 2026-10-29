# Phase 000: canonical agent tooling and lifecycle

Status: VERIFIED tooling slice — independent review attempt 2 PASS, as supplied by
the parent/user. Product planning and MVP implementation are separate and not verified.

## Context and outcome

This slice is TOOLING AND PLANS only. The user assigned AGENTS.md, opencode.json,
.agents/**, skills-lock.json, .gitignore and docs/agents/**. The worker was explicitly
told not to launch nested agents; the parent commissions independent review.

Initial `git status --short` showed extensive pre-existing dirty work: migrated
.claude/.opencode assets, modified AGENTS/config, deleted CLAUDE/root legacy plans
and minihuron files, modified CONTEXT/design/backend/testing/frontend docs and web
API files, untracked design/raw-first.md and catalog/interface, plus untracked
.agents README/commands/package/plugin/tests/workflow assets. The exact initial
status is in this worker transcript. Treat all of it as user/parent work. This
worker owns only the allowed tooling paths listed above and this ignored record;
no reset/revert/stash/commit/branch/push, service operation or global skill edit.

Desired lifecycle: evidence-based design → bounded prototype → self-contained
phase plan → serial implementation/independent review/fix (maximum three reviews).
Main sessions delegate research/planning/prototypes/coding/checks/review; workers
never delegate. Local plans/evidence stay ignored; durable architecture belongs
in design/, terms in CONTEXT.md. Product design/legacy relocation is a later slice.

## Prototype evidence and concrete interface

The bounded tooling experiment was actual runtime/config/CLI inspection, not a
Raw product prototype. Baseline on Node 22.23.2: `.agents/` `npm run check` passed;
`npm test` passed all 10 existing plugin tests. Those tests exercise real SDK
requests against a simulated HTTP boundary and make no model calls.

Existing plugin dispatch is sufficient:

```ts
implementation_start({
  role: "implementation", // planning/prototype/code writer; fix for corrections
  title: "one bounded slice",
  prompt: "complete assignment with exact scope, gate and progress contract"
});
implementation_status({ sessionID: "returned-direct-child-id" });
// verification role: read-only discovery, baseline or independent reviewer
```

Preserve direct-child status, asynchronous polling, serial exclusion, indeterminate
dispatch recovery and Astra Low enforcement. No new dispatch role or concurrency
bypass is needed. The runtime may only perform concurrent read-only discovery if
it actually supports safe tracked dispatch; this plugin serializes all children.

Official schema was fetched from https://opencode.ai/config.json before config
edits. Actual `opencode debug config` revealed inherited architectural-review and
execute_plan commands. The tested project-only hook removes those entries from
resolved config, preserving unrelated commands and all home files:

```ts
config: async (config) => {
  delete config.command?.["architectural-review"];
  delete config.command?.["execute_plan"];
}
```

Installed Playwright probe, cwd `web/`:
`npx --no-install playwright --version` → Version 1.62.1;
`npx --no-install playwright cli --help` → exit 0 with named session commands.
Read official installed SKILL.md plus all nine linked reference files. Adapted
local guidance removes global install/broad shutdown/skip/credential-storage
examples, adds owned sessions/ignored artifacts/QA contract and records provenance.
No browser or service was started; this proves CLI availability, not UI behavior.

## Scope, interfaces and deletions

- Rewrite AGENTS.md concisely, preserving current-versus-target distinctions and
  actual Compose/ports; product implementation/import cutover remains planned.
- Configure canonical four commands, default orchestrator, prompts and deny-first
  project skill allowlist. Preserve Astra Low and reviewer edit/no-delegation denies.
- Retain technical skills: oop-design, fastapi, postgresql-table-design,
  svelte-code-writer, svelte-core-bestpractices, tailwind-design-system.
- Add local playwright-cli, design-plan, implementation-plan, implement-markdown;
  rewrite prototype for the local lifecycle. Remove unavailable Svelte agent mention.
- Remove all other local skill files: ask-matt, claude-handoff, code-review,
  codebase-design, diagnosing-bugs, domain-modeling, git-guardrails-claude-code,
  grill-me, grill-with-docs, grilling, handoff, implement, implement-spec,
  improve-codebase-architecture, loop-me, migrate-to-shoehorn, oop-encapsulation,
  research, resolving-merge-conflicts, retro, scaffold-exercises,
  setup-matt-pocock-skills, setup-pre-commit, setup-ts-deep-modules, tdd, teach,
  to-questionnaire, to-spec, to-tickets, triage, wait-what, wayfinder, wizard,
  writing-beats, writing-for-agents, writing-fragments, writing-shape.
  writing-for-agents and SKILL-MECHANICS were read before retirement.
- Remove prototype's obsolete LOGIC/UI/agent assets, architectural-review command,
  docs/agents issue-tracker and triage-labels; prune obsolete lock entries.
- Add reusable design/prototype/phase/assignment templates, orchestration and
  applicable verification contracts; rewrite implement-markdown; update domain docs.
- Add asset registration/reference checks and safe actual resolved-config validation.
- Add anchored /roadmap/ and browser artifact ignores. No compatibility exceptions.

## Skills

This tooling assignment used built-in customize-opencode, official schema and the
local writing-for-agents guidance before its requested retirement. It does not
change/review product Core, HTTP, PostgreSQL or Svelte component code. Future phase
assignments resolve all area skills from AGENTS.md and canonical local files.

## Acceptance and exact applicable gate

All commands run with Node 22.23.2 first on PATH:
`PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH`.

| Cwd | Command | Observed result |
| --- | --- | --- |
| .agents | npm run check | PASS: TypeScript and 11-skill/four-command/template/reference consistency |
| .agents | npm test | PASS: 15 tests, no failures/skips; preserves existing 10 plugin cases |
| .agents | node scripts/check-resolved.mjs | PASS: actual commands/prompts/default, all three Astra Low agents, bounded permissions, 11 canonical local skill locations |
| root | git diff --check | PASS |
| root | git check-ignore -v roadmap/plans/000-agent-tooling.md web/.playwright-cli/qa.png .playwright-cli/qa.png | PASS: anchored rules apply |
| root | git ls-files roadmap | Empty: no tracked roadmap files |
| root | make docs | PASS: strict Zensical build, no issues |

The asset scanner also covers untracked canonical Markdown whitespace and local
links. Two pre-existing Tailwind relative links were discovered and corrected.
Resolved-config diagnostics are captured privately and removed by the checker;
only safe summaries are printed. Large `opencode debug skill` piped output was
truncated by CLI exit; regular-file capture resolved it without changing config.

No application Python/frontend/e2e suites apply to this tooling-only change. No
live model child was launched (explicit no-nesting scope); parent review remains
required. No docs baseline was captured before documentation edits; final strict
build is self-check evidence, not an independent baseline receipt.

## Blockers, readiness and handoff

No unresolved implementation self-check blocker. Parent must independently review
the owned changes and rerun the complete applicable gate above. This record is
ignored and no tracked asset/test relies on its existence in a fresh checkout.

Quit and restart OpenCode to activate new default, commands, prompts, skills,
permissions and plugin config hook. The current worker retains its loaded tools.
Do not claim Raw MVP implementation from this tooling slice. Durable design,
glossary, legacy relocation and subsequent product plans remain the next owner's
assignment. All unrelated dirty files and global skills were preserved.

## Independent review attempt 1 — fix attempt 1

Finding (medium): AGENTS' database target was vague and the mandatory retained
FastAPI skill (lines 19/273) and other-tools reference (lines 66–70) recommended
SQLModel over SQLAlchemy and sharing database/validation models, contradicting
the agreed schema/runtime/domain/transport split.

Initial fix state: `git status --short` captured in the fix transcript before
edits. Extensive tracked modifications/deletions and untracked assets matched the
ongoing tooling/product work described above. AGENTS.md was already modified;
both FastAPI files were initially clean. All pre-existing changes are user/parent
work. This fix owns only incremental edits to AGENTS.md, the FastAPI SKILL.md,
its references/other-tools.md, and this ignored execution ledger. No delegation.

Correction: AGENTS and both FastAPI guidance entry points now specify SQLAlchemy
Core `Table`/`MetaData` definitions plus Alembic migrations, direct asyncpg runtime
queries/transactions, domain-owned `interface/` values, and separately owned
application Pydantic HTTP transport models with explicit mapping. The local skill
explicitly overrides the upstream recommendation; no SQLModel ORM or SQLAlchemy
sessions are prescribed. Package/schema moves remain planned until implemented
and verified, and the current `metastore` runtime/import graph stays enforced.
No product implementation, permissions, allowed-skill logic, thresholds or tests
were changed.

Complete fix self-check evidence (all commands exited 0; terminal output retained
in the fix transcript). Every shell used
`PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH`; `node --version` confirmed
`v22.23.2`:

| Cwd | Command | Observed result |
| --- | --- | --- |
| .agents | npm run check | PASS: TypeScript; 11 canonical skills, four commands, templates and local references |
| .agents | npm test | PASS: 15 tests; 0 failures, skips or cancellations |
| .agents | node scripts/check-resolved.mjs | PASS: safe summaries confirm lifecycle/default, three Astra Low agents, bounded permissions and 11 canonical local skill paths |
| root | git diff --check | PASS |
| root | make docs | PASS: strict Zensical build, no issues |
| root | git check-ignore -v roadmap/plans/000-agent-tooling.md web/.playwright-cli/qa.png .playwright-cli/qa.png | PASS: .gitignore lines 40, 44 and 43 respectively |
| root | git ls-files roadmap | Empty: no tracked roadmap files |
| web | npx --no-install playwright --version | PASS: Version 1.62.1 |
| web | npx --no-install playwright cli --help | PASS: CLI help includes named-session usage |

No browsers/services or product tests were needed or run for this guidance-only
fix. These are fix-author self-checks, not an independent PASS. The single finding
is addressed for parent re-review; no independent re-review verdict is claimed.

## Independent review attempt 2 — parent receipt

Parent/user supplied final reviewer ID `ses_ef721b6d3ffelqKW9KthXauH9B` and verdict
**PASS** for attempt 2: 15 tooling tests, strict docs, resolved configuration and
ignore checks passed. This entry records that supplied independent receipt; the
planning writer did not rerun it as an independent reviewer or invent timestamps.
Review count: 2 of maximum 3. The earlier pending statements above describe prior
attempt state and are superseded by this receipt. The current planning/documentation
slice awaits its own independent review; no Raw MVP execution has begun.
