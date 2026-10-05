---
name: design-plan
description: Plan Huron changes from verified code and documentation evidence. Use for /design-plan or revising a design after implementation review exposes a plan defect.
---

# Evidence-based design and roadmap

Choose explicit preparatory profile for non-code design/planning/review when suitable;
future actual code and final complete qualification must use maximum Astra profile.

Read [orchestration](../../workflows/orchestration.md),
[verification](../../workflows/verification.md), the
[design template](../../templates/design-plan.md) and
[domain guidance](../../../docs/agents/domain.md). Main sessions delegate; an
assigned worker executes only its bounded assignment and never delegates.

Use role verification/activity discovery for read-only research; implementation or
fix/activity planning for synthesis; verification/activity review for independent
review. Supply exact claims from the parent's canonical resource dictionary, including
shared check-output. Code excludes ALL work; unrelated non-code may overlap only with
nonconflicting claims. Subject writer → review → fix remains terminally sequenced.
Claims are cooperative coordination, not a sandbox. No manual resume, automatic replay
or stale-lock stealing; resolve uncertainty with the parent. Quit and restart OpenCode
after tooling changes; inspect the actual loaded schema before using concurrency.

1. Establish the requested outcome, exact scope, dirty-tree ownership and authority:
   durable decisions in `design/`, vocabulary in `CONTEXT.md`, local delivery work
   under ignored `/roadmap/`. Read relevant records and actual code before planning.
2. Delegate read-only discovery (`verification` in OpenCode). Extract checkable
   claims and inspect code, tests, writers/consumers, empty scaffolding and configured
   import boundaries. Prefer executable evidence when cheap and safe. Classify each
   claim as implemented, drift, planned or unverified. Planned-but-absent is not drift.
   Treat legacy roadmap completion marks as claims to check, not authority.
3. Delegate design synthesis (`implementation`). Use applicable local area skills,
   real signatures and concrete examples. Assign ownership, invariants, errors,
   authorization, transactions, lifecycle and recovery. Name obsolete paths and
   tests to remove; retain compatibility only when the plan explicitly requires it.
4. Write a local roadmap under `/roadmap/` using the template. Give each phase a
   coherent end state, dependencies, likely interfaces/deletions, acceptance and
   applicable gates. Identify the smallest prototype questions and measurable
   outcomes needed before executable phase planning. Durable decision or glossary
   edits require explicit ownership; record out-of-scope reconciliation for its owner.
5. Delegate independent evidence/design review. The reviewer returns findings; the
   parent records them. Fix through a writer and re-review, at most three reviews.
   Unresolved blockers remain explicit and prevent downstream execution.
6. Hand off bounded questions to `/prototype`, then `/implementation-plan` with the
   reviewed design and evidence. Do not write product code, automatically publish
   issues, or relocate unassigned legacy plans.
