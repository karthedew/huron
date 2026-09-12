---
description: Execute a clean-sweep architectural review through serial review and synthesis agents
agent: build
---

Using the `codebase-design` skill, perform a clean-sweep architectural review of the target codebase.

Unlike `/design-plan`, this command runs no documentation grill of its own. `codebase-design` expects the project's documented intent to have been checked first, so where a review conclusion rests on a claim made by the project's own documentation rather than on the code, the reviewing subagent must say so and mark the claim unverified — or check it directly. Do not treat a design document as evidence that the code does what it says.

## Inputs

- Target path: `$1`
- Review output file: `${2:-architectural_review.md}`
- Primary architectural goal: `${3:-Improve composability by identifying common abstractions, duplicated concepts, and domain boundaries that should be moved into core/shared modules.}`
- Escalation context (optional): `${4:-}` — when this command is run because `/implement-markdown` escalated, pass the path to that plan's `## Escalation` section here so discovery starts from the known failure instead of re-deriving it.
- Token budget per subagent: 30k–50k tokens

## Clean-sweep rule

This is a clean-sweep architectural review. Do not preserve backwards compatibility unless the review plan explicitly says to preserve it.

Favor removing:

- obsolete paths
- compatibility shims
- legacy behavior
- duplicate abstractions
- stale types
- unused helpers
- transitional code
- unnecessary indirection

The desired design should be simple, cohesive, direct, idiomatic, readable, and maintainable. Prefer clear domain boundaries over cleverness. Prefer deletion over accommodation. Prefer explicit contracts over implicit behavior. Prefer well-named functions and types over comments explaining confusing code.

Do not recommend TODOs, temporary names, debug statements, commented-out code, speculative abstractions, or partial migrations.

Comments should be rare and should explain non-obvious intent, invariants, security boundaries, lifecycle assumptions, or subtle tradeoffs. Do not recommend comments that reference this review plan, phases, markdown tasks, or implementation checklist items.

## Required orchestration

Maintain a visible progress ledger in the response while working. The ledger must track:

- Current phase/task name
- Review attempt number
- Verification attempt number
- Verification status
- Remaining phases/tasks

Use `${2:-architectural_review.md}` to determine phase boundaries. If the file does not yet exist, create it during the discovery phase. If the markdown does not clearly define phases after discovery, derive a sensible sequence and record that sequence in the file before starting task reviews.

## Phase 0: discovery and codebase map

Send exactly one discovery subagent.

The discovery subagent must use the `codebase-design` skill and must inspect the full target path before writing conclusions.

The discovery subagent must not perform architectural analysis beyond what is needed to create the review plan.

The discovery subagent must:

1. If `${4:-}` is set, read that escalation report first and treat the failure it describes as the primary lead for this review — do not re-derive what it already established.
2. Inspect `$1`.
3. Identify major packages, modules, classes, protocols, services, data flows, and domain boundaries.
4. Create UML class diagrams or equivalent Mermaid diagrams showing the current structure.
5. Create or replace `${2:-architectural_review.md}`.
6. Write a structured review plan into `${2:-architectural_review.md}`.
7. Divide the review into phases/tasks small enough that each can be completed by one subagent within a 30k–50k token budget.
8. If a topic is too large for one subagent, split it into smaller review tasks.
9. Include acceptance criteria for each phase/task.
10. Include likely files or directories to inspect for each phase/task.
11. Include a final synthesis task.

The discovery output should be factual and structural. It should identify what needs review, not complete the review.

## Serial review loop

After Phase 0 is complete, complete every phase/task in `${2:-architectural_review.md}` using a strict serial loop.

For each phase/task:

1. Choose exactly one incomplete phase/task from `${2:-architectural_review.md}`.
2. Send exactly one review subagent for that phase/task.
3. Wait for that subagent to finish before starting the next one.
4. Verify that the subagent updated `${2:-architectural_review.md}`.
5. Update the visible progress ledger.
6. Continue until every phase/task is complete.

Do not run review subagents in parallel.

## Review subagent assignment template

Each review subagent must receive the following self-contained assignment format:

```text
## Assignment

Target path:
`$1`

Review output file:
`${2:-architectural_review.md}`

Phase/task name:
[PHASE_OR_TASK_NAME]

Scope:
[PASTE_OR_SUMMARIZE_THE_EXACT_SCOPE_FROM_THE_MARKDOWN]

Acceptance criteria:
[PASTE_OR_SUMMARIZE_ACCEPTANCE_CRITERIA_FROM_THE_MARKDOWN]

Relevant files/directories:
[PASTE_OR_SUMMARIZE_RELEVANT_FILES_FROM_THE_MARKDOWN]

Clean-sweep rule:
Do not preserve backwards compatibility unless this phase/task explicitly requires it.

Token budget:
30k–50k tokens.

Instructions:
- Use the `codebase-design` skill.
- Where a claim about runtime behavior can be cheaply tested, test it and record the receipt rather than reasoning about it.
- Load the area skills that AGENTS.md's "Skills by area" table assigns to every code area the scope touches: `oop-design` for `src/huron/pkg` and `src/huron/core`, `fastapi` for `src/huron/applications/api`, `postgresql-table-design` for PostgreSQL adapters, `migrations/`, and any DDL, index, constraint, or trigger work, and the Svelte and Tailwind skills for `web/`. Read each `SKILL.md` before applying it.
- Read the review output file before starting.
- Inspect the relevant code before making recommendations.
- Produce senior-level, idiomatic, minimal, cohesive architectural recommendations.
- Identify obsolete code that should be removed.
- Append or update only this assigned section in the review output file.
- If the scope cannot fit within the token budget, stop and update the review output file with a recommended task split.
```
