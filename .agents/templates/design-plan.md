# Design and local roadmap: <name>

Resolve explicit profile. Preparatory may be used for design work. Ordinary future
code/fixes/reviews use medium Astra or explicitly selected maximum, never a Low fallback.
Final complete qualification requires explicit verification/review/maximum.

## Goal, scope and authority
User outcome, exclusions, settled decisions and relevant design/glossary records.

## Verified current state
Claim → code/test/command evidence → implemented / drift / planned / unverified.
Inspect writers, consumers and empty scaffolding; two agreeing docs are not proof.

## Target and alternatives
Owners, public interfaces with signatures, invariants, authorization, persistence,
failure/recovery semantics and data flow. Explain rejected alternatives briefly.

## Phase sequence
Dependencies, owned files/symbols, deletions, observable acceptance and likely gates.
Each phase leaves a coherent verifiable boundary. Explicit compatibility exceptions.
Specify role/activity and a canonical resource dictionary with exact claims for
files, services and shared check-output. Code excludes ALL work; non-code overlap
requires nonconflicting claims, never concurrent subject writer/reviewer. Claims are
cooperative coordination, not a sandbox. Include restart readiness and recovery
ownership: no manual resume, automatic replay or stale-lock stealing.

## Prototype questions
Per phase: uncertainty, smallest experiment, success/failure criteria and artifact
location under `/roadmap/`. For prose/tooling, a focused consistency/runtime probe
can supply evidence rather than a product prototype.

## Decisions and blockers
Owner, recommendation and evidence needed. Unresolved execution blockers prevent
implementation. Durable decisions go to `design/`, terms to `CONTEXT.md` within scope.

## Review and next step
Independent findings, disposition and `/prototype` inputs; no shipped claims without
implementation and verification evidence.
