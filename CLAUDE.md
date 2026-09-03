# CLAUDE.md

Huron is a datalake for scientific projects. `design/` is the authoritative architecture record; `design/roadmap.html` is the living, cross-phase roadmap.

## Development lifecycle: design → implement → review

Non-trivial work in this repo goes through three Claude Code slash commands, defined in `.claude/commands/` and backed by skills in `.claude/skills/`. Don't hand-implement a multi-file change without going through this loop.

1. `/design-plan <target-path> [design-file] [plan-file] [design-goal] [roadmap-file] [escalation-context]`
   - Planning only — never edits application code.
   - Uses the `codebase-design` and `grill-with-docs` skills.
   - Produces/updates `DESIGN.md` (current state, roadmap drift, target design, rejected alternatives) and `IMPLEMENTATION_PLAN.md` (milestone-by-milestone, mechanically verifiable tasks) for the phase currently being worked on.
   - Reconciles `design/roadmap.html` — the living, cross-phase roadmap — against what the codebase actually does, so documentation doesn't drift from reality.
   - Defaults: `design-file=DESIGN.md`, `plan-file=IMPLEMENTATION_PLAN.md`, `roadmap-file=design/roadmap.html`.

2. `/implement-markdown <plan-file> [impl-model] [verify-model] [escalation-command]`
   - Implements an `IMPLEMENTATION_PLAN.md` produced by `/design-plan`, one phase/task at a time, through a strict implement → verify serial loop.
   - Every attempt runs the full Python validation gate (ruff, pydoclint, ty, mypy, lint-imports, pytest with coverage, radon, complexipy, pyscn) — no suppressed lints, no partial runs.
   - Capped at 3 verification attempts per phase/task.
   - On the 3rd failure: reverts/isolates the broken state, appends a `## Escalation` section to the plan (what was tried, what failed, the open design questions), and instructs the user to run `/architectural-review` against the affected area, seeded with that escalation report.
   - Defaults: `impl-model=anthropic/claude-sonnet-5`, `verify-model=anthropic/claude-opus-5`, `escalation-command=/architectural-review`.

3. `/architectural-review <target-path> [review-file] [review-goal] [escalation-context]`
   - Clean-sweep structural review only — no implementation.
   - Uses the `codebase-design` skill.
   - Produces `architectural_review.md`: a phased review plan, per-phase findings, and a final synthesis.
   - Can be seeded with an `/implement-markdown` escalation report so discovery starts from the known failure instead of re-deriving it.

### The loop

```text
/design-plan  ──►  /implement-markdown  ──► success: next phase ──► back to /design-plan
                          │
                          └─ 3x verification failure
                                   │
                                   ▼
                          /architectural-review
                                   │
                                   ▼
                    /design-plan (re-seeded with escalation
                     report + architectural review findings)
```

### Conventions shared across all three commands

- Clean-sweep by default: no backwards-compatibility shims, no TODOs, no speculative abstractions, no suppressed lints — unless the design or plan explicitly requires otherwise for this change.
- No comment, docstring, test name, or user-facing string may reference the plan, phases, or checklist mechanics. Comments explain enduring code intent, not orchestration history.
- Every module, class, function and method carries a Google-style docstring whose `Args`/`Returns`/`Yields`/`Raises` match the signature — enforced by ruff's `D` rules and `pydoclint` in the gate; tests carry a one-line summary of what they prove. The standard is `docs/getting-started/docstrings.md`.
- Subagents run serially, never in parallel, within each command.
- Commands and skills live in `.claude/commands/` and `.claude/skills/<name>/SKILL.md` respectively, both committed to the repo so the workflow travels with it.

### Skills

- `.claude/skills/fastapi/` — the official FastAPI skill, vendored from the upstream FastAPI repo (`fastapi/.agents/skills/fastapi/`). Load it whenever working on the FastAPI service tier (`src/huron/service`) — endpoints, routers, dependencies, Pydantic models, responses, streaming — whether designing, implementing, or reviewing.
- `.claude/skills/postgresql-table-design/` — PostgreSQL schema-design skill, vendored from the wshobson/agents plugin collection (`plugins/database-design/skills/postgresql/`). Load it whenever designing, updating, or reviewing the PostgreSQL schema — `src/huron/schema`, `migrations/`, or any DDL, index, constraint, or trigger work.
- `.claude/skills/codebase-design/` and `.claude/skills/grill-with-docs/` back the lifecycle commands above (both are still TODO scaffolds pending their real methodology).
