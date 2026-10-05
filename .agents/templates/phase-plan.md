# Phase <id>: <name>

Status: draft / blocked / ready / implementing / verified

## Context and outcome
Self-contained current behavior, user outcome, durable decisions, vocabulary and
prerequisite results. Copy essential context; external links are supplementary.

## Prototype evidence
Question, exact reproduction commands, observed result, limitations and conclusion.
Include concrete code/interface examples and essential evidence inline so a fresh
worker does not depend on a missing scratch artifact. Not-applicable requires an
explicit reason and substitute evidence (e.g. a tooling consistency probe).

## Exact scope and ownership
Files/symbols to create/change/delete, explicit exclusions and dirty-tree ownership.
Dependencies, migration order and compatibility exceptions (default: none).
Specify role/activity and canonical resource dictionary mapping exact claims to
files/services/artifacts, including shared check-output. Code excludes ALL workers
and checks. Non-code overlap needs nonconflicting claims; they are cooperative
coordination, not a sandbox. Isolated ignored prototypes cannot mutate live sources.

## Interfaces and implementation examples
Concrete signatures and representative code using real installed APIs; distinguish
illustration from existing code. Owner/collaborator responsibilities, invariants,
authorization, schema/metadata, concurrency, transactions and failure/recovery.
Include frontend/server/API boundaries, accessibility and all relevant UI states.

## Per-subject serial task slices
For each: objective, files/symbols, inputs/outputs, dependencies, deletions, acceptance,
skills, gate commands and pending status. Each slice must be independently reviewable.
Writer → subject review → fix remains terminally sequenced. Unrelated non-code scopes
may overlap only after their complete claims and check-output ownership are resolved.

## Skills
List exact canonical local skill paths for every affected area, including review.

## Acceptance and complete applicable gates
Observable contracts and failure cases; existing test/fixture reuse; required new
coverage. Exact commands/cwd, versions, infrastructure, pass conditions and evidence
paths selected from `.agents/workflows/verification.md`. Explain non-applicable gates.
Independent baseline and reviewer reruns required; preserve configured thresholds.

## Blockers and readiness
Every unresolved decision/evidence gap with owner and next action. Ready requires
no execution blockers and independent plan review. No silent placeholder decisions.

## Execution ledger
Record explicit profile: maximum for actual code/fixes and final complete qualification,
preparatory only for preparation. Keep configured effort separate from observed model
and provider acceptance not-proven; historical absent profiles remain not-recorded.
Baseline, task/role/attempt, model, child ID, start/last progress time, current command,
findings/verdict, review count (max 3), owned diff and remaining tasks.
Include each child's activity/claims, observedAt/progress age and actual-last-response
terminal evidence. Record loaded schema and required quit/restart after tooling edits.
Recovery requires human authorization and child/process reconciliation; never manually
resume, replay uncertain create/prompt or steal stale locks.

## Escalation / final receipt
Review reports, root cause/plan revision if blocked; otherwise files/deletions,
acceptance evidence, exact gate outcomes and limitations. Preserve dirty work.
