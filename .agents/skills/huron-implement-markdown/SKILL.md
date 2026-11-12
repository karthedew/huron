---
name: huron-implement-markdown
description: Execute a self-contained Huron phase plan through delegated baseline, serial implementation, independent review and fixes. Use for /implement-markdown.
---

# Execute an implementation plan

Ordinary actual-code implementation/fix children and reviews use explicit medium Astra.
Preserve explicitly selected maximum. Final complete qualification requires explicit
verification/review/maximum. Low baselines/planning reviews and Medium reviews are not
final qualification. Inspect the loaded profile schema after restart and record
configured effort separately from observed model/provider acceptance.

Read and follow the full [implementation workflow](../../workflows/implement-markdown.md),
[orchestration contract](../../workflows/orchestration.md) and
[verification contract](../../workflows/verification.md).

The phase plan is the assignment source. Main sessions delegate the untouched
baseline, one writer, independent reviewer reruns and fixes using the
[assignment template](../../templates/assignment.md). Workers never delegate.
No execution with unresolved blockers; no PASS from incomplete gates or self-checks.
At most three independent reviews per slice. On failure preserve dirty work and
return the concrete defect to design/prototype/phase planning as appropriate.

Dispatch implementation/fix with activity code for actual code: exclusive against
ALL workers and checks. Verification uses discovery for baseline and review for
independent review. Declare exact claims from one canonical resource dictionary,
including subject ownership and shared check-output. Unrelated non-code may overlap
only with nonconflicting claims; writer → subject review → fix stays terminally
sequenced. Claims are cooperative coordination, not a sandbox. No manual resume,
automatic replay or stale-lock stealing; recovery needs human authorization and
child/process reconciliation. Quit and restart OpenCode after tooling changes;
the loaded schema and effort enforcement remain unchanged until restart.
