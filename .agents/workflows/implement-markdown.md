# Execute a self-contained phase plan

Read the entire supplied plan, [orchestration contract](orchestration.md),
[verification contract](verification.md) and [assignment template](../templates/assignment.md).
This workflow applies to Python, frontend, documentation and tooling with their
complete applicable gates, not a blanket Python gate.

## Preflight

Resolve explicit profile as well as activity/claims. Ordinary code implementation,
fixes and reviews use `profile: medium`. Explicit maximum assignments remain Max.
Final complete qualification requires explicit verification/review/maximum.
Baseline/planning reviews may explicitly use preparatory. New classified omission
defaults to medium. Legacy-exclusive omission defaults to maximum. Low cannot run
code or legacy-exclusive. Verify loaded schema and fixed-agent configuration after restart,
distinguishing configured effort from observed assistant model/provider acceptance.

1. Confirm scope, ownership and runtime readiness. Record existing tracked and
   untracked changes without treating them as disposable. Read the exact interfaces,
   deletions, examples, dependencies and prototype evidence. A plan with unresolved
   blockers, missing acceptance/gates or unverified assumptions is not executable:
   return it to `/implementation-plan` (or `/design-plan` for a decision defect).
2. Resolve required local skills for every affected area. Fill the assignment
   template with the complete applicable gate and testing/progress contract.
3. Resolve activity and exact claims in the parent's canonical resource dictionary,
   including shared check-output/service writes and the writer's subject label.
   Claims are cooperative, not a sandbox. Uncertain independence requires *:write
   or exclusive code. Delegate a read-only baseline using `verification` with
   `discovery` activity. This is preflight, not review
   attempt 1. Run all applicable commands on the untouched slice and capture outputs,
   exit status, prerequisites and findings. Baseline failure blocks execution until
   an explicit plan revision assigns the remediation or establishes a verified
   independent boundary. Never reset unrelated changes to obtain a green baseline.

## Per-subject serial implementation / independent review / fix

For each explicitly scoped task, in dependency order:

1. Delegate one `implementation` worker with `code` activity for actual code; it is
   exclusive against ALL workers and competing checks, regardless of claims. Give it the full phase context, exact
   ownership, examples, skills, acceptance and gate, plus the assignment contract.
   It inspects code/tests, implements the complete slice, removes only obsolete
   owned paths, runs the entire applicable gate and returns evidence.
2. Confirm a terminal response and stopped work, then delegate a fresh independent
   `verification` worker with `review` activity and the subject's claims (review 1
   of at most 3). It reads the actual plan/code/diff,
   tests acceptance, architecture and skills compliance, and independently reruns
   **all** applicable gates. It does not edit source or trust implementer output.
3. On FAIL before review 3, delegate one `fix` worker with every finding and the same
   complete contract. It fixes all owned findings and reruns the full gate; send a
   fresh independent reviewer next. No overlapping subject writes/reviews/gate reruns;
   actual-code fixes remain globally exclusive. Unrelated non-code scopes may overlap
   only after activity, claims, service ownership and complete check-output gates are
   resolved as nonconflicting. Isolated ignored prototypes are not live code edits.
4. PASS requires all acceptance criteria, complete passing gates and no unresolved
   findings. Missing infrastructure or an incomplete check is BLOCKED, never PASS.
   An interrupted review retains its attempt number and must finish before counting
   a verdict; checkpoints and idle statuses are not verdicts.
5. After review 3 fails, stop. Record all three reports, exact dirty-tree ownership,
   remaining failures and plan defects in the local execution record. Preserve
   incomplete work; never auto-revert unknown files/data. Route design defects to
   `/design-plan`, new experiments to `/prototype`, and revised phase contracts to
   `/implementation-plan`. Do not start a fourth review or the next task.

The parent records child IDs, times, commands, evidence, attempt counts and verdicts
in the plan's ledger. Only independently passed tasks become complete. Final handoff
lists files/deletions, acceptance evidence, exact checks/outcomes, baseline versus
new failures, blocked work and any restart requirement. Do not claim completion
while applicable gates fail or independent verification is outstanding.

Read bounded progress separately from actual-last-response terminal evidence. Never
resume children outside admission, replay uncertain create/prompt, reset journal data
or steal a stale lock. Recovery needs human authorization and child/process evidence.
Quit and restart OpenCode after tooling changes; the loaded schema and effort stay unchanged.
The tooling writer stops after the complete self-check. Quiesce and restart before
any further dispatch or Medium record. The independent Maximum review runs afterward.
