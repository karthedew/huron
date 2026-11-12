---
name: huron-implementation-plan
description: Turn reviewed Huron design and prototype evidence into self-contained executable phase plans. Use for /implementation-plan and revising phase scope, gates or blockers.
---

# Self-contained phase planning

Resolve profile in every phase: medium Astra for ordinary implementation/fixes/reviews,
or explicitly selected maximum. Final complete qualification requires explicit
verification/review/maximum. Non-code planning permits preparatory.
New classified omission defaults to medium. Legacy-exclusive omission stays maximum.
Neither default permits Low code or substitutes for explicit final qualification.

Read [orchestration](../../workflows/orchestration.md),
[verification](../../workflows/verification.md) and the
[phase-plan template](../../templates/phase-plan.md). Main sessions delegate
synthesis and independent review; workers never delegate.

Plan role/activity separately: implementation/planning for phase synthesis,
verification/discovery for baseline, verification/review for independent review,
implementation or fix/code for actual code (exclusive against ALL work). Resolve
exact claims in one canonical resource dictionary, including shared check-output and
services. Non-code overlap requires nonconflicting claims; subject writer → review →
fix is terminally sequenced. Claims are cooperative coordination, not a sandbox.
Record recovery ownership and loaded schema/restart readiness; no manual resume,
automatic replay or stale-lock stealing. Quit and restart OpenCode after tooling edits.

1. Read the reviewed design, current code/tests, prototype results and exact requested
   scope. Verify actual paths, APIs, installed versions and task commands. Missing
   prototype evidence calls for `/prototype`; unsettled design calls for `/design-plan`.
2. Delegate synthesis into `/roadmap/plans/<id>-<name>.md`. Every phase is independently
   executable by a fresh worker given that file and the repository. Inline essential
   context, decisions, prototype findings/limitations and concrete code examples;
   links alone or “see previous phase” do not make a plan self-contained.
3. Specify exact ownership, file/symbol additions/changes/deletions, interface
   signatures, inputs/results/errors/ports, migrations, dependencies, compatibility
   exceptions and observable acceptance. Include failure cases, authorization and
   crash recovery where relevant. Size serial slices for one writer and one reviewer.
4. Resolve local skills per area and complete applicable gates from actual Makefile,
   CI, package scripts and verification guidance. Copy exact commands/cwd, prerequisites,
   configured thresholds and pass criteria into each slice. Delegate the baseline;
   require independent final reruns. Prose/tooling does not inherit Python tests.
5. Delegate independent plan review: check coverage in both directions against the
   design, concrete examples against installed APIs, feasible ordering, all deletions,
   tests/fixtures, ownership, skills and gates. Return findings without editing the
   plan. Writer fixes and fresh review are serial, at most three reviews.
6. Mark ready only when no unresolved execution blockers remain. Record review
   evidence and the exact `/implement-markdown roadmap/plans/<id>-<name>.md` invocation.
   Keep blocked plans useful with specific owners and next actions; never silently
   convert an unknown into an implementation choice.
