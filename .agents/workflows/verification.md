# Applicable gates and testing contract

Final complete qualification requires explicit `profile: maximum` (Astra Max),
verification role and review activity. Baseline and preparatory reviews may use
`profile: preparatory`; they do not substitute for complete maximum qualification.
Record configured profile/effort separately from observed model and unproven
provider effort acceptance. Never silently downgrade when Max is unavailable.

Select gates from actual changed boundaries, not file count or a Python-project
assumption. Copy exact commands, working directories, prerequisites and pass
conditions into the phase plan and every baseline/implementation/fix/review
assignment. Run the **complete applicable** set; additive boundaries add gates.
Explain non-applicability. Missing tools/services are blockers, not exclusions.

Dispatch verification with discovery activity (baseline) or review activity, with exact subject read
claims and write claims for every shared check-output, cache, service, browser profile
or port it mutates. For example `.agents` npm tests need build:agent-tools:write.
The parent owns the canonical resource dictionary; labels are cooperative coordination,
not a sandbox. Review never races its subject writer, and code excludes ALL checks.
Unrelated non-code checks overlap only when their complete resource sets do not
conflict. Record every admitted child's observation/progress timestamps and terminal
evidence independently; earlier cross-message progress is not completion. Missing or
uncertain ownership blocks admission; do not resume/replay or steal locks to run gates.

## All changes

- Inspect actual files/diff against acceptance and ownership; run `git diff --check`
  from the root. Check new untracked text too (ordinary git diff omits it).
- Verify referenced paths, commands, skill allowlist and documented delivery claims.
  Instructions/prose require proportionate checks, not application suites.
- Site documentation changes: root `make docs` (strict site build).
- Agent config/assets/plugin changes: supported Node (see `.agents/package.json`),
  then from `.agents/`, `npm run check` and `npm test`. For config changes inspect
  actual `opencode debug config` and workflow agents via `opencode debug agent`;
  project only known fields into output to avoid exposing provider credentials.
  Verify `git check-ignore` for artifacts and no tracked `roadmap/` files.

## Python code changes

Run from root using the locked `uv` environment:

```sh
make lint
uv run pytest -m unit --cov=src/huron --cov-report=term-missing
```

Add affected real-adapter and workflow suites (record exact selected paths if
bounded by a plan; do not silently shrink scope):

```sh
uv run pytest -m contract
uv run pytest -m integration
# Ingestion/durability acceptance changes; at least 25 GiB free disk:
make test-acceptance
```

`make test`/plain pytest select units by default. CI tolerating no integration
tests is not integration evidence. `make lint` includes Ruff lint/format,
pydoclint, mypy strict, ty, import-linter, schema-map, radon, complexipy, pyscn and
the duplication guard. Inspect diagnostics as well as exits: radon grade C+
complexity or B+ maintainability is a finding even if the command exits zero.
Keep configured thresholds, coverage floor, source scope and import contracts.
The duplication guard permits only the existing baseline: no new clone group or
growth at similarity 0.80; native score is informational. Do not raise its baseline
or alter detection/exclusions to pass. Explain uncovered touched behavior with
specific lines and risks, and cover it when reachable; do not invent a lower floor.

## Frontend code changes

From `web/`, run autofixer on **every changed `.svelte` file**:

```sh
npx @sveltejs/mcp svelte-autofixer <path> --svelte-version 5
npm run check
npm test
npm run lint
npm run build
```

Review autofixer output, apply valid findings and rerun until none apply. Format
only owned changed files before lint. For routes/auth/navigation/forms/responsive
behavior and other visible interactions add `npm run test:e2e`. For visible UI
changes add real-browser QA using local `playwright-cli`: narrow mobile, around
816px compact and wide desktop, light/dark, keyboard/focus, loading/empty/long
content/validation/error states, clipping/overflow, hydration and console errors.
Use named sessions, prove endpoint ownership and keep artifacts ignored. Record
unavailable browsers/services explicitly; do not weaken e2e tests to pass.

## Testing standard (paste with resolved gate into assignments)

Before adding tests, find existing public-behavior coverage, parametrization,
scoped conftest/fixtures and helpers; reuse or extend them. Discover fixtures with
pytest `--fixtures`/`--fixtures-per-test` when unclear. Test changed contracts,
happy/error paths, boundaries, permissions, retries, concurrency and recovery as
applicable. Assert observable outcomes rather than private call sequences. Control
time/randomness, isolate mutable state, and mock only external I/O. Real filesystem
and PostgreSQL contracts prove durability/locking that fakes cannot. Frontend pure
behavior/API seams use Vitest; cross-route interactions use Playwright. Delete
obsolete owned tests instead of skipping them. Comments/docstrings/test names
describe enduring behavior, not plan phases. No suppressions, exclusions, skips,
xfails, weakened assertions, thresholds or contracts to manufacture a pass.

## Evidence and verdict

Capture exact command/cwd, versions, exit code, relevant full output or local log
path, findings, counts and coverage where applicable. Preserve baseline versus new
failure attribution and all unrelated dirty work. Independent reviewers inspect
the actual result and rerun gates themselves: copied implementer receipts are not
independent evidence. PASS means complete acceptance and green applicable gates;
FAIL gives actionable file/symbol findings; BLOCKED names the missing evidence or
infrastructure and required next action. Both FAIL and BLOCKED prevent completion.
