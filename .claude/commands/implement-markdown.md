---
description: Execute a markdown implementation plan for a Python project through serial implementation and verification agents with a strict validation gate, bounded fix loops, and configurable models
agent: build
model: openai/gpt-6-astra
variant: medium
---

You are orchestrating a disciplined, senior-engineer implementation workflow for a Python project from the markdown implementation plan at:

`$1`

## Inputs

- Implementation plan: `$1`
- Model for every role (orchestration, implementation, fixes and verification): `openai/gpt-6-astra`, reasoning effort `medium`.
- `$2`/`$3` must be omitted or equal `openai/gpt-6-astra`; other models are refused.
- Escalation review command: `${4:-/architectural-review}`

### Runtime selection

Detect the host application from its runtime/tool context, not the model's name. If uncertain, ask before delegation. Record the host and resolved settings in the ledger.

- **Claude Code:** requires Astra with Medium reasoning for every role. Verify that the host supports this model and reasoning setting before delegation, using its native configuration rather than assuming OpenCode's `variant` field applies. If unavailable, stop and request a supported runtime; never substitute a Claude model.
- **OpenCode:** enter through `.opencode/commands/implement-markdown.md`, which selects `markdown-orchestrator`. `opencode.json` configures that agent, `markdown-implementer` (implementation and fixes), and `markdown-reviewer` for Astra Medium. The project plugin enforces medium reasoning effort for these agents and refuses model substitution. `$2`/`$3` must be omitted or equal `openai/gpt-6-astra` in this runtime. The Claude frontmatter does not apply to the OpenCode wrapper.
- **Codex:** read this file as workflow instructions when the user supplies its path and a plan, for example `./.claude/commands/implement-markdown.md P3_IMPLEMENTATION_PLAN.md`. This is a prompt invocation, not a shell executable or a registered Codex slash command. Use native subagent tools exposed in the current session. Invoking this workflow authorizes its serial delegation. Confirm the orchestrator and children use Astra with Medium reasoning through exposed runtime settings or supported native parameters before delegation. Inherit settings only when they are confirmed to match. If the required settings cannot be selected or confirmed, stop and request a correctly configured session; do not guess an unexposed value or substitute another model.

#### Codex delegation

Inspect the exposed tool schemas before launching. In sessions exposing `collaboration`, use `spawn_agent` with a unique task name and the complete assignment, record the returned agent ID, receive progress through `send_message`, and inspect status with `list_agents`. Use `wait_agent` with waits of at most 60 seconds between status checks; relay incoming updates promptly. Other Codex surfaces may expose equivalent native tools with different names or arguments: use their actual schemas, not invented aliases. See the [official subagent guidance](https://learn.chatgpt.com/docs/agent-configuration/subagents); the current session's tool definitions govern exact calls.

Launch one child at a time for implementation, fixes, or independent verification. Include an instruction against nested delegation in every assignment. While the child runs, the orchestrator monitors progress and maintains the ledger without editing the child's files or running competing validation. Start the next child only after receiving the current child's final report and confirming its work has stopped. Verification reruns the full gate and reports findings without editing source files; this is a workflow rule, not an OS-level read-only sandbox.

After an interrupted launch, inspect existing agents before dispatching again. An idle agent, timeout, error, or missing final report is indeterminate, not a verification verdict. Inspect any surviving tool processes before replacing an interrupted worker. An interruption does not imply its shell commands stopped. Keep one active child across recovery as well as normal execution; resume the existing assignment through supported native tools when appropriate.

#### OpenCode delegation

OpenCode must expose `implementation_start` and `implementation_status` from `.opencode/plugins/implementation.ts`. Launch with `role`, `title`, and the full assignment in `prompt`; record the returned `sessionID`. The asynchronous launch returns without waiting for completion. Poll `implementation_status` with that ID at least once per minute while active, and relay substantive changes immediately and a short user update at least every 15 minutes. Use an available bounded wait between polls, not a blocking Task call or a tight loop. Polling exposes the latest assistant text and tool activity even when the child cannot push updates directly to the parent.

After an interrupted launch, omit `sessionID` when polling to discover direct children. Inspect the existing child rather than launch a duplicate. A missing final response, API error, or idle status alone is indeterminate, not PASS or proof of a stopped writer. The plugin refuses another child until existing children have terminal response evidence. An explicit abort still requires checking for surviving tool processes before replacement. Do not delete sessions to bypass the serial guard.

#### Runtime readiness

Before the first launch, confirm the selected host's tools and agent settings are available. Only require the tools for that host; Codex does not require the OpenCode plugin or Claude models. If required capabilities are unavailable, report the specific runtime limitation and request a restart or an explicit alternative; do not claim prompt instructions exposed new tools. For OpenCode setup and validation, see `.opencode/README.md`. Keep the full serial loop, validation gate, and iteration cap below in every runtime.

In Codex, escalation commands also name instruction files: present the equivalent prompt invocation of `.claude/commands/architectural-review.md` or `.claude/commands/design-plan.md` with the affected area and evidence paths. Read the requested command and check its own runtime requirements before executing it.

Treat `$1` as the source-of-truth implementation plan. Before doing anything else, read the entire markdown file carefully. Do not begin editing until you understand the full plan, its phases, its sequencing, its stated constraints, and its acceptance criteria.

## Preflight

Before starting the first phase/task, do all of the following and record the results in the progress ledger:

1. Read `pyproject.toml`. Determine the package import path(s) to measure (from `[project]`, `[tool.setuptools]`, `[tool.hatch]`, `[tool.pytest.ini_options]`, or the `src/` layout). State the resolved package path explicitly; every validation command below uses it.
2. Confirm every tool in the validation gate resolves inside the project environment: `uv run ruff --version`, `uv run ty --version`, `uv run mypy --version`, `uv run lint-imports --version`, `uv run pytest --version`, `uv run python -c "import pytest_cov"`, `uv run radon --version`, `uv run complexipy --version`, `uv run --locked pyscn --version` (must be 1.31.1). If any tool is missing, stop immediately and report which tools must be added as dev dependencies. Do not treat a missing tool as "validation not applicable."
3. Run the full validation gate once on the untouched tree to establish a baseline. If the baseline already fails, report the failures and stop; the plan must be executed from a green tree so that every failure during the workflow is attributable to the current phase/task.

## Python validation gate

Every implementation, fix, and verification subagent runs the complete gate. The gate passes only when every command exits 0 and meets the pass conditions below. The sole findings exception is code duplication: clone findings are allowed when the duplication guard passes -- no clone growth or new clone group appears at similarity 0.80 relative to `scripts/duplication_baseline.json`; the native score is reported, not gated. All other zero-findings requirements remain strict. Partial runs, "ran the relevant subset," and skipped tools are not acceptable. Throughout this workflow, a "clean" gate means these pass conditions are met, not that clone output is empty.

Configuration precedence: if `pyproject.toml` (or `ruff.toml`, `ty.toml`, `.coveragerc`) configures a tool, that configuration governs. Any thresholds stated below are fallback defaults that apply only when the project has not configured the tool. Subagents must not loosen configured thresholds, add exclusions, or introduce `# noqa`, `# type: ignore`, `# pragma: no cover`, `@pytest.mark.skip`, or `@pytest.mark.xfail` to make the gate pass; the coverage floor moves only by the re-baseline the `pytest` pass condition below defines.

Run from the repository root, with `<pkg>` replaced by the resolved coverage package
path. Static lint targets `src/`; tests and migration schema-map validation remain
separate required verification. `make lint` is the canonical static gate, including
pydoclint and schema-map validation.

```text
uv run ruff check src
uv run ruff format --check src
uv run ty check
uv run mypy
uv run lint-imports
uv run pytest --cov=<pkg> --cov-report=term-missing
uv run radon cc src --min C
uv run radon mi src --min B
uv run complexipy src --max-complexity-allowed 15
uv run --locked pyscn check src
uv run --locked python scripts/check_duplication.py src
```

Pass conditions:

- `ruff check`: zero diagnostics.
- `ruff format --check`: zero files would be reformatted.
- `ty check`: zero errors.
- `mypy`: zero errors, under the project's configured strictness. No new suppressions.
- `lint-imports`: every import contract kept.
- `pytest`: all tests pass, no tests skipped or xfailed that were not already skipped or xfailed at baseline, total coverage at or above the configured `fail_under` floor, and every file touched in this phase/task at 100% line coverage unless the verification subagent explicitly judges a specific uncovered line to be unreachable defensive code. The floor is a ratchet measured on the unit run: raise it when coverage climbs. It moves down only by a re-baseline, which resets `fail_under` to the newly measured total rounded down to two decimals and is allowed only when the verification subagent confirms, from covered and total statement counts before and after the task, that the whole drop comes from deleted statements that were covered, new PostgreSQL adapter statements that `uv run pytest -m "unit or contract" --cov=<pkg>` covers in full, or both — and that every new or modified file is at 100%. The task records the before and after counts in the plan.
- `radon cc --min C`: empty output. No function, method, or class at cyclomatic grade C or worse.
- `radon mi --min B`: empty output. No module at maintainability grade B or worse.
- `complexipy`: exit 0. No function above the cognitive complexity limit.
- `pyscn check`: exit 0. No dead code or structural complexity findings. Clone warnings are evaluated by the score gate below, not a zero-clones rule; do not skip clone detection.
- `check_duplication.py`: exit 0. This script runs `uv run --locked pyscn analyze --select clones --json --clone-threshold 0.80 <pkg>` and validates the report from that invocation; missing/invalid reports, unsupported versions, disabled clone analysis, incomplete analysis (including diagnostics or failures), and tool failures fail closed. The duplication guard passes when no clone growth or new clone group appears at similarity 0.80 relative to the committed `scripts/duplication_baseline.json`: it fails only if total clones exceed the baseline, a scanned clone group's file signature is unknown to the baseline, or a known signature's group grew larger. pyscn's native JSON `summary.duplication_score` is reported for information alongside cloned/total fragments, pair and group counts; it is never gated, since pyscn 1.31.1 has no native CLI score-threshold flag and this tree's type-2/type-4 structural silhouettes cap the reachable score below 90 (see IMPLEMENTATION_PLAN.md D7). Do not tune detection/exclusions to manufacture a pass, and do not update the baseline (`--update-baseline`) except to ratchet it down when detection has genuinely decreased; raising it is a reviewed manual edit.

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
- New tests do not duplicate existing coverage. Before writing tests, read the existing tests for the code under change and its callers; extend or parametrize an existing test rather than adding one that proves the same behavior.
- Existing fixtures come first. Reuse a shared fixture that fits; adapt an existing fixture when a reasonable change covers the new need; add a new one only when none can. New fixtures are written for reuse by other tests: general names, no single-test assumptions, placed in the shared conftest or support module where other tests can use them.

## Serial loop

Your job is to complete the markdown plan through a strict serial loop:

1. Choose exactly one phase or task from the markdown plan.
2. Send exactly one implementation subagent using the resolved runtime settings to complete that phase or task.
3. After implementation returns, send exactly one verification subagent using the resolved runtime settings to review the result.
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
- Models and reasoning effort in use (orchestrator / implementation / verification)
- Active subagent task ID, start time, last progress-update time, and current operation

Use the markdown plan to determine phase boundaries. If the markdown does not clearly define phases, derive a sensible sequence from the document and state the derived sequence before starting.

For each phase/task, follow this exact loop.

### Progress updates

Every implementation, fix, and verification subagent must send a brief progress update at least every 15 minutes of elapsed time while its assignment remains active, including during validation. Send blockers, repeated failures, and suspected hangs immediately rather than waiting for the next interval. These are progress messages, not final implementation reports or verification verdicts.

Keep each update to 2-4 short lines containing the phase/task, agent role and attempt number, elapsed time, concrete progress since the previous update, current operation or command, and the next step or blocker. If nothing has advanced, say so and identify the last observed activity; do not substitute "still working" for evidence.

The orchestrator must relay each update to the user promptly and refresh the visible ledger. Include this entire progress-update contract verbatim in every implementation, verification, and fix assignment, including resumed assignments.

Before delegation, confirm how the runtime delivers intermediate updates. Use supported streaming or background execution with status polling so a long-running command does not hide progress for more than 15 minutes. Do not cancel or rerun a healthy command merely to produce an update. If intermediate updates are unavailable, disclose that limitation before launching and obtain approval for a checkpoint/resume alternative or for proceeding without live updates; prompt text alone does not guarantee delivery.

When an update is overdue, inspect available task/process status and report the last confirmed activity. If liveness cannot be inspected, state that it is unknown, not that the agent is working or stuck. Do not start a replacement until the previous agent is confirmed stopped. A checkpoint, interruption, or resume does not itself consume another verification attempt or replace any required validation; a checkpoint is not PASS or FAIL.

### Step 1: Implementation subagent

Invoke one implementation subagent using the resolved runtime settings for the current phase/task. The implementation subagent must receive a self-contained assignment that includes:

- The markdown file path: `$1`
- The exact phase/task to implement
- Any relevant acceptance criteria from the markdown
- The resolved package path
- The full Python validation gate, verbatim
- The testing standard, verbatim
- The clean-sweep rule: no backwards compatibility unless explicitly required
- The comment rule: no code comment, docstring, test name, user-facing message, or internal note may reference the markdown, the plan, phases, or checklist mechanics
- The expectation that all touched code should be senior-level, idiomatic, minimal, and beautiful
- The skills to load before editing, resolved by the orchestrator from AGENTS.md's "Skills by area" table for every code area the phase/task touches: `oop-design` for `src/huron/pkg` and `src/huron/core`, `fastapi` for `src/huron/applications/api`, `postgresql-table-design` for PostgreSQL adapters, `migrations/`, and any DDL, index, constraint, or trigger work, and the Svelte and Tailwind skills for `web/`. Name the resolved skills in the assignment; do not leave the lookup to the subagent
- The requirement to run the complete validation gate and paste the actual output of every command
- The requirement to summarize exactly what changed and what validation was run
- The progress-update contract above, verbatim

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

Progress updates:
[PASTE_PROGRESS_UPDATE_CONTRACT_VERBATIM]

Engineering rules:
- Complete this phase/task fully.
- Load these skills before writing code and follow their conventions: [RESOLVED_AREA_SKILLS_FROM_AGENTS_MD]. AGENTS.md's "Skills by area" table assigns them by code area: `oop-design` for `src/huron/pkg` and `src/huron/core`, `fastapi` for `src/huron/applications/api`, `postgresql-table-design` for PostgreSQL adapters, `migrations/`, and any DDL, index, constraint, or trigger work, and the Svelte and Tailwind skills for `web/`. Read each `SKILL.md` in full and apply each skill only to its own area.
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

Validation gate (every command must exit 0 and meet its pass conditions; the duplication guard passes when no clone growth or new clone group appears at similarity 0.80 relative to `scripts/duplication_baseline.json` -- the native score is reported, not gated -- all other zero-findings checks remain strict; configured thresholds in pyproject.toml govern):
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

After implementation returns, invoke one verification subagent using the resolved runtime settings for the same phase/task. The verification subagent must receive a self-contained assignment that includes:

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
- The progress-update contract above, verbatim

The verification subagent must read the markdown file before reviewing. It must inspect the actual code and diff. It must rerun the entire validation gate and base its verdict on what it observes, never on the implementation subagent's pasted output. It must not rubber-stamp. It must look for small problems as well as large ones.

Verification must produce one of two outcomes:

- `PASS`: The phase/task is complete, the gate is clean, and no issues remain.
- `FAIL`: One or more issues remain.

Any non-zero exit or violation of a pass condition is an automatic `FAIL`. Clone findings alone are not a failure when the duplication guard passes -- no clone growth or new clone group appears at similarity 0.80 relative to `scripts/duplication_baseline.json`; the native score is reported, not gated -- every other zero-findings check remains strict. A missing tool, missing/invalid duplication report, or an unconfigured threshold that the implementation relied on is an automatic `FAIL`.

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

Progress updates:
[PASTE_PROGRESS_UPDATE_CONTRACT_VERBATIM]

Validation gate (run every command yourself; do not trust pasted output):
[PASTE_VALIDATION_GATE_VERBATIM]

Testing standard:
[PASTE_TESTING_STANDARD_VERBATIM]

Verification rules:
- Be strict.
- Run the complete validation gate. Any non-zero exit or violation of a pass condition is FAIL. Clone findings are allowed only when the duplication guard passes -- no clone growth or new clone group appears at similarity 0.80 relative to `scripts/duplication_baseline.json`; the native score is reported, not gated -- all other zero-findings checks remain strict.
- Flag every issue, even small ones.
- Check correctness, completeness, code quality, naming, architecture, type annotations, comments, tests, validation, and general code health.
- Load the skills AGENTS.md's "Skills by area" table assigns to the code areas the change touches ([RESOLVED_AREA_SKILLS_FROM_AGENTS_MD]) and check the code against their conventions, each applied only to its own area.
- Check the tests against the testing standard: coverage of error paths and boundaries, behavioral rather than implementation-coupled assertions, determinism, mocking only at I/O boundaries, and no skipped or xfailed tests introduced.
- Confirm every file touched in this phase/task is fully covered, or state precisely which uncovered lines you judge unreachable and why.
- Confirm obsolete code was removed where the clean-sweep change makes it unnecessary.
- Confirm there is no backwards compatibility preservation unless explicitly required by the markdown.
- Confirm no `# noqa`, `# type: ignore`, `# pragma: no cover`, skip or xfail markers, or tool configuration changes were introduced to satisfy the gate. A `fail_under` reset is the one allowed configuration change: check it against the `pytest` pass condition's re-baseline rule using the recorded before and after statement counts.
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

If the verification subagent returns `FAIL` and fewer than 3 verification attempts have been used for this phase/task, invoke a new implementation subagent using the resolved runtime settings whose only job is to fix every verification issue for the current phase/task. The fix implementation subagent must read the markdown file, read the verification report, inspect the code, fix all issues, and rerun the complete validation gate.

If the verification subagent returns `FAIL` on attempt 3, do not send another fix subagent. Execute the escalation procedure in "Iteration cap and escalation" and end the workflow.

Suggested fix implementation subagent prompt:

```text
Read the markdown implementation plan at `$1` before starting.

You are the implementation agent for a verification fix pass on the current phase/task:

[PHASE_OR_TASK_NAME]

The previous verification failed. Fix every issue below before returning:

[PASTE_FULL_VERIFICATION_FIX_LIST]

Package path for validation: [RESOLVED_PACKAGE_PATH]

Progress updates:
[PASTE_PROGRESS_UPDATE_CONTRACT_VERBATIM]

Rules:
- Fix all issues, including small ones.
- Load these skills before writing code and follow their conventions: [RESOLVED_AREA_SKILLS_FROM_AGENTS_MD]. AGENTS.md's "Skills by area" table assigns them by code area: `oop-design` for `src/huron/pkg` and `src/huron/core`, `fastapi` for `src/huron/applications/api`, `postgresql-table-design` for PostgreSQL adapters, `migrations/`, and any DDL, index, constraint, or trigger work, and the Svelte and Tailwind skills for `web/`. Read each `SKILL.md` in full and apply each skill only to its own area.
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

Validation gate (every command must exit 0 and meet its pass conditions; clone findings are allowed only when the duplication guard passes -- no clone growth or new clone group appears at similarity 0.80 relative to `scripts/duplication_baseline.json`; the native score is reported, not gated -- all other zero-findings checks remain strict):
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
