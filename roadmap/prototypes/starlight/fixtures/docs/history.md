# Implementation history

Current architecture and target decisions live in `design/`, led by
`design/raw-first.md`. Local delivery plans live under ignored `roadmap/`.
This page provides historical receipts and access to the
completed plans, audits and raw reports removed from the working tree.

The archive is pinned to
[`7846d67a4c404a00830a6bb7d9255978ee5cfe32`](https://github.com/karthedew/huron/tree/7846d67a4c404a00830a6bb7d9255978ee5cfe32),
the domain-owned Core migration. Historical claims describe their recorded tree,
not the current implementation. Every tracked document remains recoverable with
`git show 7846d67:<path>`.

## Domain-owned Core

[Migration commit](https://github.com/karthedew/huron/commit/7846d67a4c404a00830a6bb7d9255978ee5cfe32)
and [complete original plan and receipts](https://github.com/karthedew/huron/blob/7846d67a4c404a00830a6bb7d9255978ee5cfe32/docs/plans/domain-owned-core.md).
The rationale remains in [ADR-0002](adr/0002-domain-owned-core-workflows.md); the
implemented graph is in `design/architecture.html#domain-owned-core`.

The verified migration colocated domain values, rules, workflows and ports under
Core, moved authentication and controller-admission orchestration to their owners,
and retired unused capability placeholders and redundant interfaces.

| Recorded gate | Result |
| --- | --- |
| Static checks | `make lint` passed, including 19 import contracts. |
| Unit coverage | 1,797 passed; 96.39%, above the unchanged 96.01% floor. |
| Contract tests | 49 passed against real adapters. |
| Integration tests | All 15 passed in an isolated Linux/Podman runner, including controlled cutover. |
| Raw acceptance | 9 GiB interrupted upload, resume and byte-identical download passed. |
| OpenAPI | Canonical 144,266 bytes unchanged; SHA-256 `f648da8949b67ce80b7298815fb4042c23b2104db26bee3de60cefd43fc7f0c9`. |
| Duplication | 141 clones / 46 groups against unchanged allowances of 145 / 48. |
| Review | Standards and Spec findings resolved, including delayed-lookup credential expiry regressions. |

Documentation rendering/link/browser checks and migration-scoped whitespace checks
passed. These receipts do not certify a production or NFS deployment, or complete
the remaining P3 activation, recovery and cleanup work.

## Earlier backend work

- [Independent Raw revisions and authorized workflows](https://github.com/karthedew/huron/blob/7846d67a4c404a00830a6bb7d9255978ee5cfe32/docs/plans/backend-restructure.md):
  the earlier namespace migration and independent-submission contract.
- [P2 acceptance run](https://github.com/karthedew/huron/actions/runs/34177077449):
  the historical 9 GiB acceptance proof at commit `db5fc84`.
- [P3 verification archive](https://github.com/karthedew/huron/tree/7846d67a4c404a00830a6bb7d9255978ee5cfe32/p3-evidence):
  original completion, cutover, failure-reproduction and controller-authority reports.
- [Duplication verification archive](https://github.com/karthedew/huron/tree/7846d67a4c404a00830a6bb7d9255978ee5cfe32/duplication-evidence):
  committed reports from the earlier refactoring slices.

## Archived plans and investigations

| Area | Historical documents |
| --- | --- |
| API | [Design](https://github.com/karthedew/huron/blob/7846d67a4c404a00830a6bb7d9255978ee5cfe32/API_DESIGN.md), [execution plan](https://github.com/karthedew/huron/blob/7846d67a4c404a00830a6bb7d9255978ee5cfe32/API_IMPLEMENTATION_PLAN.md), [skill audit](https://github.com/karthedew/huron/blob/7846d67a4c404a00830a6bb7d9255978ee5cfe32/api_skill_audit.md) |
| Authentication and authorization | [Authentication plan](https://github.com/karthedew/huron/blob/7846d67a4c404a00830a6bb7d9255978ee5cfe32/AUTH_IMPLEMENTATION_PLAN.md), [RBAC plan](https://github.com/karthedew/huron/blob/7846d67a4c404a00830a6bb7d9255978ee5cfe32/RBAC_IMPLEMENTATION_PLAN.md) |
| PostgreSQL schema | [Design](https://github.com/karthedew/huron/blob/7846d67a4c404a00830a6bb7d9255978ee5cfe32/SCHEMA_DESIGN.md), [execution plan](https://github.com/karthedew/huron/blob/7846d67a4c404a00830a6bb7d9255978ee5cfe32/SCHEMA_IMPLEMENTATION_PLAN.md), [audit](https://github.com/karthedew/huron/blob/7846d67a4c404a00830a6bb7d9255978ee5cfe32/schema_audit.md) |
| Foundations | [P1 design](https://github.com/karthedew/huron/blob/7846d67a4c404a00830a6bb7d9255978ee5cfe32/P1_DESIGN.md), [P1 execution plan](https://github.com/karthedew/huron/blob/7846d67a4c404a00830a6bb7d9255978ee5cfe32/P1_IMPLEMENTATION_PLAN.md) |
| Raw ingestion | [P2 design](https://github.com/karthedew/huron/blob/7846d67a4c404a00830a6bb7d9255978ee5cfe32/P2_DESIGN.md), [P2 execution plan](https://github.com/karthedew/huron/blob/7846d67a4c404a00830a6bb7d9255978ee5cfe32/P2_IMPLEMENTATION_PLAN.md) |
| Integrity authority | [Authority design](https://github.com/karthedew/huron/blob/7846d67a4c404a00830a6bb7d9255978ee5cfe32/P3_M1B_AUTHORITY_DESIGN.md), [execution plan](https://github.com/karthedew/huron/blob/7846d67a4c404a00830a6bb7d9255978ee5cfe32/P3_M1B_AUTHORITY_IMPLEMENTATION_PLAN.md), [architectural review](https://github.com/karthedew/huron/blob/7846d67a4c404a00830a6bb7d9255978ee5cfe32/P3_M1B_ARCHITECTURAL_REVIEW.md) |
| Integrity progress | [Execution ledger](https://github.com/karthedew/huron/blob/7846d67a4c404a00830a6bb7d9255978ee5cfe32/P3_EXECUTION.md), [M1a validation](https://github.com/karthedew/huron/blob/7846d67a4c404a00830a6bb7d9255978ee5cfe32/P3_M1A_VALIDATION.md), [M1b validation](https://github.com/karthedew/huron/blob/7846d67a4c404a00830a6bb7d9255978ee5cfe32/P3_M1B_VALIDATION.md), [superseded proposal](https://github.com/karthedew/huron/blob/7846d67a4c404a00830a6bb7d9255978ee5cfe32/P3_PROPOSAL.md) |
| Earlier findings and prototypes | [Findings plan](https://github.com/karthedew/huron/blob/7846d67a4c404a00830a6bb7d9255978ee5cfe32/FINDINGS_IMPLEMENTATION_PLAN.md), [retired control-plane plan](https://github.com/karthedew/huron/blob/7846d67a4c404a00830a6bb7d9255978ee5cfe32/CONTROL_PLANE_PLAN.md) |
| Duplication redesign | [Original plan and status ledger](https://github.com/karthedew/huron/blob/7846d67a4c404a00830a6bb7d9255978ee5cfe32/IMPLEMENTATION_PLAN.md), [superseded architecture proposal](https://github.com/karthedew/huron/blob/7846d67a4c404a00830a6bb7d9255978ee5cfe32/design/duplication-architecture.md) |

The root `IMPLEMENTATION_PLAN.md`, `P3_DESIGN.md` and `P3_IMPLEMENTATION_PLAN.md`
were already absent at the start of the 2026-10-04 planning slice (tracked deletions).
No unseen local content was reconstructed or deletion attributed to this slice.
The full then-current `design/roadmap.html` was moved unchanged to local ignored
`roadmap/archive/design-roadmap.html`; its unfinished P3 and duplication work remains
migration input, not completion. Current operator instructions are in
[Controlled cutover](operations/controlled-cutover.md).

## Legacy roadmap receipts

The following are preserved historical claims from the relocated roadmap, not new
test runs or certification of the Raw-first target. The pinned archives above hold
the original plans and reports; current source/tests remain implementation evidence.

- Schema conformance `0008`: recorded as shipped in `da03ece`, applied and
  upgrade/downgrade/upgrade tested on 2026-09-01 against PostgreSQL 16. The schema-map
  check only compares the documentation stamp to the migration head.
- API sweep: recorded as shipped in `600ff2a` on 2026-09-02, with typed responses,
  authenticated versioned routes, problem errors, keyset pagination and four
  binding roots. This does not mean generated SDK/web clients were delivered.
- P2 Raw ingest: historical 9 GiB interrupted upload/resume/download evidence is
  linked above. The tested contract was numbered-part, submission-only revision
  publication; it does not prove tus, inherited full-copy releases or 50-user load.
  Run `34177077449` passed 2026-09-08 UTC at
  `db5fc84cd7bfe049692ef2abb16fb32570ccf5a2`, using 64 MiB parts. The relocated
  record reports 990 local units (94.32% at that historical tree), 13 PostgreSQL
  contracts, lint and strict docs passing; integration then had no tests and was
  explicitly not additional coverage. These old counts do not lower today's floor.
- P3: M1a upload/completion/envelope separation and M1b controller-generation
  authority evidence remain in the P3 archive above. Full activation/startup
  enforcement, recovery and trash cleanup were still outstanding; relocation
  does not mark them complete.
- Domain-owned Core: the exact gate counts and OpenAPI digest remain in the
  [receipt above](#domain-owned-core), not solely in an ignored archive.
- Earlier governance only had the amendment fold and field allow-list implemented;
  schema registry, retention/purge workflows and advanced UI remained planned.
  The frontend shell/design tokens were fixture-backed; T0 generation/session/
  visibility integration was not delivered. These qualifications remain important
  when reading the old roadmap's backend-oriented “done” rows.

## Report housekeeping

Keep concise final receipts and decisions with the relevant documentation; put
bulk command output in CI artifacts or an external working directory. Generated
pyscn reports and coverage JSON are ignored. The committed duplication baseline
at `scripts/duplication_baseline.json` remains an executable regression contract.

Before cleanup, the complete local report trees, including uncommitted additions
and edits, were backed up and byte-compared at
`/tmp/opencode/huron-report-cleanup-7846d67.tar.gz` (SHA-256
`c1631f01d5631f5efd4207ab97c0e4b7f3b6b6b0c0d353c00b2a23091b745e94`).
That local backup is separate from the pinned Git archive and may be discarded
when its owner no longer needs the uncommitted scratch reports.
