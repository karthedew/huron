---
name: huron-prototype
description: Run a bounded throwaway experiment to resolve a Huron design question before phase planning. Use for /prototype, state-model experiments and UI exploration.
---

# Prototype a decision, capture evidence

An explicit preparatory profile may run isolated throwaway probes, never live code.
Actual-code dispatch uses medium or explicitly selected maximum Astra profile.
Final complete qualification requires explicit verification/review/maximum.
Report configured selection separately from observed model/provider acceptance.

Read [orchestration](../../workflows/orchestration.md),
[verification](../../workflows/verification.md) and the
[evidence template](../../templates/prototype.md). Main sessions delegate the
experiment and independent review; assigned workers never delegate.

Use implementation or fix/activity prototype only for owned ignored throwaway work
with isolated resources. Live code/config/service mutation is exclusive code, not
prototype. Declare exact claims from the parent's canonical resource dictionary,
including shared check-output/services; claims are cooperative coordination, not a
sandbox. Unrelated non-code may overlap only with nonconflicting claims; subject
writer → verification/review → fix remains terminally sequenced. No manual resume,
automatic replay or stale-lock stealing. Reconcile recovery with the parent; quit
and restart OpenCode after tooling changes and inspect the actual loaded schema.

1. Read the design and actual relevant code with required area skills. State one
   bounded uncertainty, hypothesis and observable success/failure criteria.
2. Choose the smallest useful experiment: state-model walkthrough, API/adapter
   probe, UI variation or configuration/asset-consistency probe. Use real adapters
   when the question is about durability, locking or transfer semantics; a fake
   only proves the model. Record installed versions and exact APIs.
3. Work under ignored `/roadmap/prototypes/<name>/`, with evidence under `/roadmap/`.
   Give an exact reproduction command/cwd. Keep inputs and state isolated and mark
   artifacts non-production. Product source edits or shared service mutation require
   explicit scope. Never overwrite unknown files or delete someone else's data.
4. Exercise the counterexample/failure as well as the happy case. For visible UI,
   use the Svelte/Tailwind skills as applicable and local `playwright-cli` for named
   browser sessions, viewport/theme/keyboard/failure-state evidence. Verify service
   ownership before use. No global installs or broad browser/process shutdown.
5. Write the evidence template: observations, commands, outputs, limitations,
   decision and concrete interface/code examples. Delegate independent review of
   whether the evidence answers the question; fix and re-review serially, max three
   reviews. An experiment that disproves the design is useful evidence, not a PASS
   on the proposed implementation. Unresolved questions remain blockers.
6. Pass the conclusions to `/implementation-plan`. Durable accepted decisions go
   to `design/` only in an owned documentation slice. Prototype results never
   automatically create branches, commits, issues or production changes.
