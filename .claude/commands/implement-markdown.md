---
description: Execute a markdown implementation plan for a Python project through serial implementation and verification agents with a strict validation gate, bounded fix loops, and configurable models
agent: build
model: claude-fable-5
---

You are orchestrating a disciplined, senior-engineer implementation workflow for a Python project from the markdown implementation plan at:

`$1`

## Inputs

- Implementation plan: `$1`
- Implementation subagent model: `${2:-anthropic/claude-sonnet-5}`
- Verification subagent model: `${3:-anthropic/claude-opus-5}`
- Escalation review command: `${4:-/architectural-review}`

When spawning subagents, pass the model explicitly: every implementation and fix subagent runs on `${2:-anthropic/claude-sonnet-5}`, and every verification subagent runs on `${3:-anthropic/claude-opus-5}`. If a specified model is unavailable in the current provider configuration, stop immediately and report the available providers instead of silently substituting a model.

Treat `$1` as the source-of-truth implementation plan. Before doing anything else, read the entire markdown file carefully. Do not begin editing until you understand the full plan, its phases, its sequencing, its stated constraints, and its acceptance criteria.

## Preflight

Before starting the first phase/task, do all of the following and record the results in the progress ledger:

1. Read `pyproject.toml`. Determine the package import path(s) to measure (from `[project]`, `[tool.setuptools]`, `[tool.hatch]`, `[tool.pytest.ini_options]`, or the `src/` layout). State the resolved package path explicitly; every validation command below uses it.
2. Confirm every tool in the validation gate resolves inside the project environment: `uv run ruff --version`, `uv run ty --version`, `uv run mypy --version`, `uv run lint-imports --version`, `uv run pytest --version`, `uv run python -c "import pytest_cov"`, `uv run radon --version`, `uv run complexipy --version`, `uv run pyscn --version`. If any tool is missing, stop immediately and report which tools must be added as dev dependencies. Do not treat a missing tool as "validation not applicable."
3. Run the full validation gate once on the untouched tree to establish a baseline. If the baseline already fails, report the failures and stop; the plan must be executed from a green tree so that every failure during the workflow is attributable to the current phase/task.

## Python validation gate

Every implementation, fix, and verification subagent runs the complete gate. The gate passes only when every command exits 0 and produces no findings. Partial runs, "ran the relevant subset," and skipped tools are not acceptable.

Configuration precedence: if `pyproject.toml` (or `ruff.toml`, `ty.toml`, `.coveragerc`) configures a tool, that configuration governs. Any thresholds stated below are fallback defaults that apply only when the project has not configured the tool. Subagents must not loosen configured thresholds, add exclusions, or introduce `# noqa`, `# type: ignore`, `# pragma: no cover`, `@pytest.mark.skip`, or `@pytest.mark.xfail` to make the gate pass.

Run from the repository root, with `<pkg>` replaced by the resolved package path:

```text
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run mypy
uv run lint-imports
uv run pytest --cov=<pkg> --cov-report=term-missing
uv run radon cc <pkg> --min C
uv run radon mi <pkg> --min B
uv run complexipy <pkg> --max-complexity-allowed 15
uv run pyscn check <pkg>
```

Pass conditions:

- `ruff check`: zero diagnostics.
- `ruff format --check`: zero files would be reformatted.
- `ty check`: zero errors.
- `mypy`: zero errors, under the project's configured strictness. No new suppressions.
- `lint-imports`: every import contract kept.
- `pytest`: all tests pass, no tests skipped or xfailed that were not already skipped or xfailed at baseline, total coverage at or above the configured `fail_under` floor — that floor is a ratchet: never lower it, and raise it when coverage climbs — and every file touched in this phase/task at 100% line coverage unless the verification subagent explicitly judges a specific uncovered line to be unreachable defensive code.
- `radon cc --min C`: empty output. No function, method, or class at cyclomatic grade C or worse.
- `radon mi --min B`: empty output. No module at maintainability grade B or worse.
- `complexipy`: exit 0. No function above the cognitive complexity limit.
- `pyscn check`: exit 0. No dead code, no code clones, no structural complexity findings.

Complexity failures and the clean sweep: consolidating legacy paths often pushes a function over a complexity limit. The correct fix is a better decomposition along domain boundaries, not mechanical extraction of arbitrary helpers to satisfy the metric. If a function genuinely requires complexity beyond the limit to express its domain logic correctly, that is a plan-defect signal to be raised in the verification report, not a reason to suppress the check.

## Testing standard

"Extensive unit tests" means the following, and subagents must be held to it:

- Every new or modified public function, method, and class has direct tests.
- Tests cover the happy path, boundary conditions, empty and degenerate inputs, and every error path the code raises or handles.
- Tests assert behavior and contracts, not implementation details. A test that would break under a correct refactor is a defect.
- Tests are deterministic. No reliance on wall-clock time, network, randomness without a seed, or test ordering.
- Mocking is used only at genuine I/O boundaries (filesystem, network, subprocess, clock). Do not mock the code under test or its collaborators within the package.
- Tests for deleted code are deleted, not skipped, commented out, or left failing.
- Test names describe the behavior under test in plain language. They must not reference the plan, phases, or task numbers.
- Fixtures and parametrization are used to remove duplication; test files are held to the same quality bar as production code.

## Serial loop

Your job is to complete the markdown plan through a strict serial loop:

1. Choose exactly one phase or task from the markdown plan.
2. Send exactly one implementation subagent (model: `${2:-anthropic/claude-sonnet-5}`) to complete that phase or task.
3. After implementation returns, send exactly one verification subagent (model: `${3:-anthropic/claude-opus-5}`) to review the result.
4. If verification finds any issue of any size, send another implementation subagent to fix every issue.
5. Send another verification subagent.
6. Repeat implementation -> verification, subject to the iteration cap below.
7. When a phase/task passes verification, move to the next phase/task.
8. Continue until the entire markdown plan is complete.

Do not run multiple implementation or verification subagents in parallel. There must only ever be one active subagent for this workflow at a time.

## Iteration cap and escalation

Each phase/task is allowed a maximum of 3 verification attempts. That is: initial implementation -> verification #1, fix pass -> verification #2, fix pass -> verification #3.

If verification #3 returns `FAIL`, stop the entire workflow immediately. Do not attempt a fourth fix pass, do not move to the next phase/task, and do not claim partial completion of the failed phase/task.

On escalation, do the following and nothing else:

1. Revert or clearly isolate incomplete changes if the working tree is in a broken state, so the repository builds and the full validation gate passes. If a clean revert is not possible, report the exact state of the tree.
2. Write an escalation report as a new `## Escalation` section appended to `$1`, containing:
   - The failed phase/task name and all 3 verification reports.
   - Your diagnosis of why the plan-as-written could not be implemented (ambiguous scope, wrong assumptions about the codebase, missing design decisions, underspecified contracts, irreducible complexity that conflicts with the gate, or task too large for one subagent).
   - The specific design questions that must be answered before implementation can resume.
3. Instruct the user to run `${4:-/architectural-review}` against the affected area, seeded with the escalation report, so the architecture underlying the failed plan gets reassessed before anyone replans against it. Provide the exact command invocation they should run, with arguments filled in.
4. Recommend that once the architectural review completes, the user re-run `/design-plan` for the same area, passing both the escalation report and the architectural review output as escalation context, to produce a corrected design and implementation plan.
5. End the workflow. Repeated verification failure is a signal that the plan is defective, not that more fix passes are needed.

## Global engineering standards

This is a clean-sweep implementation. Do not preserve backwards compatibility unless the markdown plan explicitly says to preserve it. Remove obsolete paths, compatibility shims, legacy behavior, duplicate abstractions, stale types, unused helpers, and transitional code.

The final code should be beautiful: simple, cohesive, direct, idiomatic Python, readable, and maintainable. Prefer clear domain boundaries over cleverness. Prefer deletion over accommodation. Prefer explicit contracts over implicit behavior. Prefer well-named functions and types over comments explaining confusing code. All public functions and methods carry complete type annotations; `Any` is used only where the type is genuinely open.

Do not leave TODOs, temporary names, debug statements, print statements, commented-out code, speculative abstractions, or partial migrations.

Do not mention the markdown implementation plan in code comments, commit-style notes, docstrings, user-facing strings, test names, or internal comments. Comments must read like senior-level engineering commentary about the code itself, not like references to an external checklist. For example:

Bad:

- `# Added for Phase 2 of the markdown`
- `# Per the implementation plan, remove legacy fallback`
- `# TODO from markdown`

Good:

- `# Normalize provider identifiers before cache lookup so equivalent aliases share one entry.`
- `# Fail closed here because partially configured credentials can route requests to the wrong backend.`

Comments should be rare. Add them only when they clarify non-obvious intent, invariants, security boundaries, lifecycle assumptions, or subtle tradeoffs.

## Required orchestration behavior

Maintain a visible progress ledger in your own response as you work. The ledger should track:

- Resolved package path used by the validation gate
- Preflight result and baseline gate status
- Current phase/task name
- Implementation attempt number
- Verification attempt number (n of 3)
- Verification status
- Remaining phases/tasks
- Models in use (implementation / verification)

Use the markdown plan to determine phase boundaries. If the markdown does not clearly define phases, derive a sensible sequence from the document and state the derived sequence before starting.

For each phase/task, follow this exact loop.

### Step 1: Implementation subagent

Invoke one implementation subagent (model: `${2:-anthropic/claude-sonnet-5}`) for the current phase/task. The implementation subagent must receive a self-contained assignment that includes:

- The markdown file path: `$1`
- The exact phase/task to implement
- Any relevant acceptance criteria from the markdown
- The resolved package path
- The full Python validation gate, verbatim
- The testing standard, verbatim
- The clean-sweep rule: no backwards compatibility unless explicitly required
- The comment rule: no code comment, docstring, test name, user-facing message, or internal note may reference the markdown, the plan, phases, or checklist mechanics
- The expectation that all touched code should be senior-level, idiomatic, minimal, and beautiful
- The requirement to load the `fastapi` skill (`.claude/skills/fastapi/`) before editing, when the phase/task touches the FastAPI service tier (`src/huron/service`)
- The requirement to load the `postgresql-table-design` skill (`.claude/skills/postgresql-table-design/`) before editing, when the phase/task designs or updates the PostgreSQL schema (`src/huron/schema`, `migrations/`, or any DDL, index, constraint, or trigger work)
- The requirement to run the complete validation gate and paste the actual output of every command
- The requirement to summarize exactly what changed and what validation was run

The implementation subagent must read the markdown file before editing. It must inspect the relevant code before changing it. It must make the smallest complete set of changes necessary to finish the current phase/task while removing obsolete code made unnecessary by the clean sweep.

The implementation subagent should not defer known issues to later phases unless the markdown explicitly assigns those issues to a later phase.

Suggested implementation subagent prompt:

```text
Read the markdown implementation plan at `$1` before starting.

You are the implementation agent for the current phase/task:

[PHASE_OR_TASK_NAME]

Scope:
[PASTE_OR_SUMMARIZE_THE_EXACT_SCOPE_FROM_THE_MARKDOWN]

Acceptance criteria:
[PASTE_OR_SUMMARIZE_ACCEPTANCE_CRITERIA]

Package path for validation: [RESOLVED_PACKAGE_PATH]

Engineering rules:
- Complete this phase/task fully.
- If this phase/task touches the FastAPI service tier (`src/huron/service`), load the `fastapi` skill (`.claude/skills/fastapi/`) before writing code, and follow its conventions.
- If this phase/task designs or updates the PostgreSQL schema (`src/huron/schema`, `migrations/`, or any DDL, index, constraint, or trigger work), load the `postgresql-table-design` skill (`.claude/skills/postgresql-table-design/`) and follow its conventions.
- This is a clean sweep. Do not preserve backwards compatibility unless the markdown explicitly requires it.
- Remove obsolete code, dead paths, compatibility shims, stale tests, unused types, and transitional abstractions made unnecessary by this work.
- Do not reference the markdown, implementation plan, phase numbers, checklist mechanics, or this orchestration process in code comments, docstrings, test names, user-facing strings, or internal comments.
- Comments must be senior-engineer comments about enduring code intent only. Avoid comments unless they clarify non-obvious invariants, lifecycle rules, security implications, or tradeoffs.
- Keep the code beautiful: simple, idiomatic Python, cohesive, direct, well-named, fully type-annotated, and maintainable.
- Prefer deletion and simplification over layering new abstractions on old ones.
- Do not leave TODOs, debug logs, print statements, commented-out code, temporary names, partial migrations, or speculative abstractions.
- Never add `# noqa`, `# type: ignore`, `# pragma: no cover`, skip or xfail markers, or config exclusions to make validation pass. If the gate cannot be satisfied without them, stop and explain why.

Testing standard:
[PASTE_TESTING_STANDARD_VERBATIM]

Validation gate (every command must exit 0 with no findings; configured thresholds in pyproject.toml govern):
[PASTE_VALIDATION_GATE_VERBATIM]

Process:
1. Read `$1`.
2. Inspect the relevant code and tests.
3. Implement the current phase/task completely.
4. Write, update, or remove tests to meet the testing standard.
5. Run the complete validation gate. Fix findings and rerun until every command is clean.
6. Report:
   - Files changed
   - What changed
   - Obsolete code removed
   - Tests added, changed, and removed, with the behaviors they cover
   - The exact output of every validation command
   - Any risks or follow-up concerns
```

### Step 2: Verification subagent

After implementation returns, invoke one verification subagent (model: `${3:-anthropic/claude-opus-5}`) for the same phase/task. The verification subagent must receive a self-contained assignment that includes:

- The markdown file path: `$1`
- The exact phase/task being verified
- The implementation summary
- The resolved package path
- The full Python validation gate, verbatim
- The testing standard, verbatim
- The current diff or instruction to inspect the current working tree
- The clean-sweep rule
- The comment rule
- The requirement to run the complete validation gate itself, independently of the implementation summary
- The requirement to flag every issue, including small ones
- The requirement to check code quality, comments, naming, tests, architecture, deletion of obsolete code, validation completeness, and general code health
- Which verification attempt this is (1, 2, or 3 of 3)

The verification subagent must read the markdown file before reviewing. It must inspect the actual code and diff. It must rerun the entire validation gate and base its verdict on what it observes, never on the implementation subagent's pasted output. It must not rubber-stamp. It must look for small problems as well as large ones.

Verification must produce one of two outcomes:

- `PASS`: The phase/task is complete, the gate is clean, and no issues remain.
- `FAIL`: One or more issues remain.

Any non-zero exit or non-empty finding from the gate is an automatic `FAIL`. A missing tool or an unconfigured threshold that the implementation relied on is an automatic `FAIL`.

If verification returns `FAIL`, it must provide a precise fix list. Every issue must be actionable, specific, and tied to files, symbols, behavior, tests, or validation gaps.

On verification attempt 3, the verification subagent must additionally state, for each remaining issue, whether it believes the issue is fixable within the current plan or reflects a defect in the plan itself. This assessment feeds the escalation report.

Suggested verification subagent prompt:

```text
Read the markdown implementation plan at `$1` before starting.

You are the verification agent for the current phase/task:

[PHASE_OR_TASK_NAME]

This is verification attempt [N] of 3.

Scope:
[PASTE_OR_SUMMARIZE_THE_EXACT_SCOPE_FROM_THE_MARKDOWN]

Implementation summary:
[PASTE_IMPLEMENTATION_AGENT_SUMMARY]

Package path for validation: [RESOLVED_PACKAGE_PATH]

Your job is to verify the implementation against the markdown plan and senior engineering standards. Inspect the working tree, relevant files, tests, and diff. Do not rely on the implementation summary for anything you can check yourself.

Validation gate (run every command yourself; do not trust pasted output):
[PASTE_VALIDATION_GATE_VERBATIM]

Testing standard:
[PASTE_TESTING_STANDARD_VERBATIM]

Verification rules:
- Be strict.
- Run the complete validation gate. Any non-zero exit or any finding is FAIL.
- Flag every issue, even small ones.
- Check correctness, completeness, code quality, naming, architecture, type annotations, comments, tests, validation, and general code health.
- Where the change touches the FastAPI service tier (`src/huron/service`), load the `fastapi` skill (`.claude/skills/fastapi/`) and check the code against its conventions.
- Where the change designs or updates the PostgreSQL schema (`src/huron/schema`, `migrations/`, DDL, indexes, constraints, triggers), load the `postgresql-table-design` skill (`.claude/skills/postgresql-table-design/`) and check the schema against its conventions.
- Check the tests against the testing standard: coverage of error paths and boundaries, behavioral rather than implementation-coupled assertions, determinism, mocking only at I/O boundaries, and no skipped or xfailed tests introduced.
- Confirm every file touched in this phase/task is fully covered, or state precisely which uncovered lines you judge unreachable and why.
- Confirm obsolete code was removed where the clean-sweep change makes it unnecessary.
- Confirm there is no backwards compatibility preservation unless explicitly required by the markdown.
- Confirm no `# noqa`, `# type: ignore`, `# pragma: no cover`, skip or xfail markers, or tool configuration changes were introduced to satisfy the gate.
- Confirm no code comments, docstrings, test names, user-facing strings, or internal comments reference the markdown, implementation plan, phase numbers, checklist mechanics, or this orchestration process.
- Confirm comments are senior-level and explain enduring code intent only.
- Confirm no TODOs, debug logs, print statements, commented-out code, temporary names, partial migrations, or speculative abstractions remain.
- Where a complexity finding exists, judge whether the right fix is a better domain decomposition or whether the required complexity is irreducible and signals a plan defect.

Return exactly one status:

PASS

or

FAIL

If PASS, include:
- Why the phase/task is complete
- The exact output of every validation command you ran
- Any residual risk worth knowing, without creating unnecessary follow-up work

If FAIL, include:
- A numbered fix list
- Each issue's severity: small, medium, or large
- File/symbol/location when possible
- The expected correction
- The exact output of every failing validation command
- If this is attempt 3 of 3: for each issue, state whether it is fixable within the current plan or indicates a plan defect (ambiguous scope, wrong codebase assumptions, missing design decisions, irreducible complexity, or oversized task)
```

### Step 3: Fix loop

If the verification subagent returns `FAIL` and fewer than 3 verification attempts have been used for this phase/task, invoke a new implementation subagent (model: `${2:-anthropic/claude-sonnet-5}`) whose only job is to fix every verification issue for the current phase/task. The fix implementation subagent must read the markdown file, read the verification report, inspect the code, fix all issues, and rerun the complete validation gate.

If the verification subagent returns `FAIL` on attempt 3, do not send another fix subagent. Execute the escalation procedure in "Iteration cap and escalation" and end the workflow.

Suggested fix implementation subagent prompt:

```text
Read the markdown implementation plan at `$1` before starting.

You are the implementation agent for a verification fix pass on the current phase/task:

[PHASE_OR_TASK_NAME]

The previous verification failed. Fix every issue below before returning:

[PASTE_FULL_VERIFICATION_FIX_LIST]

Package path for validation: [RESOLVED_PACKAGE_PATH]

Rules:
- Fix all issues, including small ones.
- If this phase/task touches the FastAPI service tier (`src/huron/service`), load the `fastapi` skill (`.claude/skills/fastapi/`) before writing code, and follow its conventions.
- If this phase/task designs or updates the PostgreSQL schema (`src/huron/schema`, `migrations/`, or any DDL, index, constraint, or trigger work), load the `postgresql-table-design` skill (`.claude/skills/postgresql-table-design/`) and follow its conventions.
- Do not ignore, defer, or partially address any verification item.
- This is a clean sweep. Do not preserve backwards compatibility unless explicitly required by the markdown.
- Remove obsolete code made unnecessary by the fix.
- Do not reference the markdown, implementation plan, phase numbers, checklist mechanics, or this orchestration process in code comments, docstrings, test names, user-facing strings, or internal comments.
- Comments must be senior-engineer comments about enduring code intent only.
- Keep the code beautiful: simple, idiomatic Python, cohesive, direct, well-named, fully type-annotated, and maintainable.
- Do not leave TODOs, debug logs, print statements, commented-out code, temporary names, partial migrations, or speculative abstractions.
- Never add `# noqa`, `# type: ignore`, `# pragma: no cover`, skip or xfail markers, or config exclusions to make validation pass.
- Complexity findings are fixed by better domain decomposition, not by mechanically extracting helpers to satisfy the metric.

Testing standard:
[PASTE_TESTING_STANDARD_VERBATIM]

Validation gate (every command must exit 0 with no findings):
[PASTE_VALIDATION_GATE_VERBATIM]

Process:
1. Read `$1`.
2. Read the verification report.
3. Inspect the relevant code and tests.
4. Fix every issue.
5. Run the complete validation gate. Fix findings and rerun until every command is clean.
6. Report:
   - Each verification issue and how it was fixed
   - Files changed
   - Obsolete code removed
   - The exact output of every validation command
   - Any remaining risk
```

## Completion criteria for a phase/task

A phase/task is complete only when:

- The implementation satisfies the markdown scope and acceptance criteria
- The verification subagent returns `PASS` within 3 verification attempts
- The verification subagent independently ran the full validation gate and every command was clean
- No verification issues remain, including small ones
- Tests meet the testing standard and no suppression markers or config exclusions were introduced
- Code comments do not reference the markdown, phases, checklist mechanics, or orchestration process
- The code is clean, idiomatic, maintainable, and free of obsolete compatibility paths unless explicitly required

## Completion criteria for the whole markdown plan

The entire markdown plan is complete only when every phase/task has individually passed the implementation -> verification loop within its iteration cap, and the full validation gate is clean on the final tree.

At the end, provide a final summary with:

- Completed phases/tasks
- Number of implementation attempts per phase/task
- Number of verification attempts per phase/task
- Files materially changed
- Major obsolete paths removed
- Final validation gate output
- Coverage at baseline and at completion
- Final risks or notes, if any

Do not claim completion if any phase/task has not passed verification. If the workflow ended in escalation, say so explicitly, name the failed phase/task, and repeat the exact `${4:-/architectural-review}` invocation the user should run, followed by the recommended `/design-plan` re-run.
