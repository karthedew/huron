---
description: Grill the documentation, map and design the codebase, and produce a verifiable IMPLEMENTATION_PLAN.md through serial subagents, reconciling the living roadmap against what actually exists
agent: build
---

Produce a design document and an implementation plan for the target codebase, and reconcile the project's living roadmap against what actually exists. This command plans and documents; it does not implement application code.

The work runs in one order and the order is load-bearing: **grill the documentation first, then map and design the codebase, then write the plan.** The grill establishes what the project believes about itself and which of those beliefs are false. Designing before that means designing on top of stale claims — a design built on an invariant that turns out never to have been enforced inherits the error, and nothing downstream catches it.

- Phase 0 uses the `grill-with-docs` skill.
- Phases 1 and 2 use the `codebase-design` skill.
- Phase 5 uses `grill-with-docs` again to write the reconciled roadmap back.

## Inputs

- Target path: `$1`
- Design output file: `${2:-DESIGN.md}`
- Plan output file: `${3:-IMPLEMENTATION_PLAN.md}`
- Primary design goal: `${4:-Improve composability by identifying common abstractions, duplicated concepts, and domain boundaries that should be moved into core/shared modules.}`
- Roadmap file: `${5:-design/roadmap.html}`
- Escalation context (optional): `${6:-}` — when this command is run after an `/implement-markdown` escalation or an `/architectural-review`, pass the path to that report here so discovery starts from known findings instead of re-deriving them.
- Token budget per subagent: 30k–50k tokens

Check the plan output file before writing to it. If it holds a plan for work that has already shipped, do not overwrite it — use a named companion file (`<AREA>_IMPLEMENTATION_PLAN.md`) and say so in the response.

## Clean-sweep rule

This is a clean-sweep design. Do not preserve backwards compatibility unless the design explicitly says to preserve it.

Favor removing: obsolete paths, compatibility shims, legacy behavior, duplicate abstractions, stale types, unused helpers, transitional code, unnecessary indirection.

The desired design should be simple, cohesive, direct, idiomatic, readable, and maintainable. Prefer clear domain boundaries over cleverness. Prefer deletion over accommodation. Prefer explicit contracts over implicit behavior. Prefer well-named functions and types over comments explaining confusing code.

Do not recommend TODOs, temporary names, debug statements, commented-out code, speculative abstractions, or partial migrations. Do not recommend comments that reference this plan, phases, or checklist items.

## Required orchestration

Maintain a visible progress ledger in the response while working:

- Current phase/task name
- Subagent attempt number
- Verification attempt number
- Verification status
- Remaining phases/tasks

Do not run subagents in parallel. Each subagent must read the current state of `${2:-DESIGN.md}` and `${3:-IMPLEMENTATION_PLAN.md}` (if they exist) before writing.

## Phase 0: documentation grill

Send exactly one grill subagent, using the `grill-with-docs` skill.

The grill subagent must:

1. If `${6:-}` is set, read that escalation or architectural-review report first and treat its findings as established context.
2. Establish the authority order across the project's documentation — which document decides, which restate it, which are retired — before extracting any claim.
3. Extract the checkable claims those documents make about `$1`, scoped to the target path.
4. Check each claim against executable truth, preferring to run something over reading the code that would run, and reading code over reading another document. Two documents agreeing is not verification.
5. Take every deliverable marked `done` or `shipped` that touches `$1` and check it item by item. A phase claiming completion for something absent is the highest-value finding available and is invisible from both the code and the document.
6. Create or replace `${2:-DESIGN.md}` with a **"Roadmap Drift"** section recording each finding as claim → evidence → classification, plus a short list naming the documents and areas that came back clean.

Work explicitly marked `todo` or deferred whose code does not exist is **not** drift. Reporting it as drift buries the real findings.

The grill does not edit any documentation. Recording the divergence is the deliverable; Phase 5 writes corrections back.

## Phase 1: discovery and codebase map

Send exactly one discovery subagent, using the `codebase-design` skill.

The discovery subagent must read `${2:-DESIGN.md}`'s Roadmap Drift section first and treat those findings as established — it must not re-derive them, and must not produce a map that contradicts a confirmed finding.

It must then:

1. Inspect `$1`.
2. Identify major packages, modules, classes, protocols, services, data flows, and domain boundaries.
3. Record the conventions the codebase already follows, not only its structure — a design that fights an existing convention without saying why gets rejected in review.
4. Check emptiness explicitly: a table with no writer, a protocol with no implementation, or a package that does not exist changes the design and is invisible unless looked for.
5. Create Mermaid (or UML-equivalent) diagrams of the current structure, where a diagram shows a mechanism prose states poorly.
6. Add to `${2:-DESIGN.md}`:
   - A **"Current State"** section: the codebase map, diagrams, conventions, and factual observations.
   - A **"Design Tasks"** section: design areas, each sized for one subagent within a 30k–50k token budget, with acceptance criteria and the likely files to inspect. Say per task whether it can be settled from the artifacts alone or needs application code and design documents read. Where two tasks touch the same object, name which one owns the decision.
7. If a design area is too large for one subagent, split it.

The discovery output is factual and structural. It identifies what needs design, not the design itself.

## Phase 2: serial design loop

For each incomplete design task in `${2:-DESIGN.md}`:

1. Choose exactly one incomplete task.
2. Send exactly one design subagent for that task using the assignment template below.
3. Wait for it to finish before starting the next one.
4. Verify that the subagent updated `${2:-DESIGN.md}` and satisfied the acceptance criteria.
5. Update the visible progress ledger.

Each design subagent must produce, for its assigned area, in `${2:-DESIGN.md}`:

- Target design: the desired module/package layout, key types, and public interfaces, written as concrete signatures or contracts (not prose descriptions of code).
- Explicit contracts: for every proposed interface, its invariants, error behavior, and lifecycle assumptions. Where the caller does not exist yet, this is the specification its future author must honor.
- Deletions: obsolete code, shims, and duplicate abstractions to remove, by file/symbol. State "none" explicitly rather than omitting the section.
- Data flow: a Mermaid diagram if the area involves cross-module flow.
- Rejected alternatives: at most 2–3, one line each, with the reason.
- Open questions: anything requiring a human decision, clearly flagged, with a recommended option and its reasoning. Do not silently pick; do not refuse to recommend.

Where a claim about runtime behavior can be tested cheaply, test it rather than reasoning about it, and record the receipt. Constraints that exist in the source and do not hold at runtime are not visible by reading.

## Phase 3: implementation plan synthesis

After all design tasks are complete, send exactly one planning subagent.

The planning subagent must read the completed `${2:-DESIGN.md}` in full and create or replace `${3:-IMPLEMENTATION_PLAN.md}` with:

1. Goal and non-goals — one short section, restating the primary design goal and explicitly listing what is out of scope, including any open question awaiting a human decision.
2. Milestone sequence — an ordered list of milestones. Each milestone must:
   - Leave the codebase compiling and passing tests when complete (no milestone may end in a broken intermediate state).
   - Be sized for one implementation subagent within a 30k–50k token budget.
   - Order interface/type/contract changes before the implementations that depend on them.
   - Order deletions as early as safely possible so later work is not built on code slated for removal.
   - Where a milestone depends on an unsettled human decision, gate that milestone explicitly and structure the sequence so the rest is not blocked behind it.
3. Per-milestone task breakdown — for each milestone:
   - Task name and one-sentence intent.
   - Files/symbols to create, modify, or delete.
   - The relevant design section in `${2:-DESIGN.md}` (reference by section heading, never by restating the design).
   - Verification: the exact commands to run (build, test, lint) and the observable acceptance criteria that must hold. Every task must be mechanically verifiable; "code looks cleaner" is not acceptance criteria. Commands must exist in this repository — read the build and dependency files rather than assuming a conventional command exists. Where the design introduces a new contract, the task must include writing or updating the tests that pin that contract.
   - Dependencies on other tasks, stated explicitly.
   - Status field, initialized to `pending`.
4. Risk register — the 3–5 highest-risk changes, each with the symptom to watch for and the fallback decision point.
5. Definition of done — global acceptance criteria for the whole plan.

The plan must be self-contained enough that a fresh implementation subagent, given only `${3:-IMPLEMENTATION_PLAN.md}` plus `${2:-DESIGN.md}`, can execute any single milestone without asking questions.

## Phase 4: plan verification

Send exactly one verification subagent. It must:

1. Read `${2:-DESIGN.md}` and `${3:-IMPLEMENTATION_PLAN.md}` in full.
2. Check every plan task against the design for coverage in both directions: every proposed interface, contract, and deletion in the design must map to at least one task, and every task must have a design basis.
3. Check milestone ordering for dependency violations and broken intermediate states.
4. Check that every task's verification is mechanically executable against the actual repository — commands exist, test frameworks and markers are present, referenced files and symbols are where the plan says they are. Verify the plan's own load-bearing claims about the test configuration rather than trusting them.
5. Record findings in a "Verification" section appended to `${3:-IMPLEMENTATION_PLAN.md}`: either `VERIFIED` or a numbered list of defects, each with what is wrong, where, why it breaks execution, and the correction needed. Keep judgment calls you would have made differently in a separate observations section rather than inflating the defect list.

If defects are found, fix them with one additional planning subagent pass, then re-verify. Limit to 2 verification cycles; if defects remain, split them into blocking and non-blocking, surface them to the user, and stop.

## Phase 5: roadmap reconciliation

Send exactly one documentation subagent, using the `grill-with-docs` skill.

The documentation subagent must:

1. Read `${2:-DESIGN.md}`'s Roadmap Drift section — Phase 0 already established the findings; do not re-grill.
2. Read `${5:-design/roadmap.html}` if it exists; treat it as authoritative history and create it fresh, seeded from the design and plan, if it does not.
3. Update `${5:-design/roadmap.html}` so it accurately reflects: what has shipped, what this phase's plan commits to next, and how this phase fits the broader roadmap sequence. Do not restate the full design or plan inline — reference them by section heading.
4. Correct or remove the roadmap language Phase 0 classified as wrong. Where a drift item's resolution depends on a decision the user has not made, correct the false claim without asserting either outcome, and mark the item open.
5. Do not invent roadmap items that neither the design nor the plan supports.

Edit surgically. Confirm the exact current text before replacing it, never rewrite an authoritative document wholesale, and touch nothing outside the identified drift items and the new entry. Match the document's existing markup and status-tag vocabulary.

This phase keeps the living roadmap and the actual implementation plan from diverging. It runs once per `/design-plan` invocation, after the plan is verified.

## Subagent assignment template

```text
## Assignment

Target path:
`$1`

Design file:
`${2:-DESIGN.md}`

Plan file:
`${3:-IMPLEMENTATION_PLAN.md}`

Phase/task name:
[PHASE_OR_TASK_NAME]

Scope:
[PASTE_OR_SUMMARIZE_THE_EXACT_SCOPE]

Acceptance criteria:
[PASTE_OR_SUMMARIZE_ACCEPTANCE_CRITERIA]

Relevant files/directories:
[PASTE_OR_SUMMARIZE_RELEVANT_FILES]

Clean-sweep rule:
Do not preserve backwards compatibility unless this task explicitly requires it.

Token budget:
30k–50k tokens.

Instructions:
- Use the `codebase-design` skill. For Phase 0 and Phase 5, use `grill-with-docs` instead.
- If the scope touches the FastAPI service tier (`src/huron/service`), also load the `fastapi` skill (`.claude/skills/fastapi/`).
- If the scope designs or updates the PostgreSQL schema (`src/huron/schema`, `migrations/`, DDL/indexes/constraints/triggers), also load the `postgresql-table-design` skill (`.claude/skills/postgresql-table-design/`).
- Read the design and plan files before starting, including the sections completed by earlier tasks, so your output does not contradict them.
- Inspect the relevant code before making recommendations.
- Where a claim about runtime behavior can be cheaply tested, test it and record the receipt rather than reasoning about it.
- Produce senior-level, idiomatic, minimal, cohesive output.
- Append or update only your assigned section.
- If the scope cannot fit within the token budget, stop and record a recommended task split in the design file.
```
