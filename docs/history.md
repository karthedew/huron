# Implementation history

Current architecture and delivery status live in `design/` and
`design/roadmap.html`. This page provides historical receipts and access to the
completed plans, audits and raw reports removed from the working tree.

The archive is pinned to
[`7846d67a4c404a00830a6bb7d9255978ee5cfe32`](https://github.com/karthedew/huron/tree/7846d67a4c404a00830a6bb7d9255978ee5cfe32),
the domain-owned Core migration. Historical claims describe their recorded tree,
not the current implementation. Every tracked document remains recoverable with
`git show 7846d67:<path>`.

## Release tag retirement

On 2026-10-15 the owner retired Raw release tags: a dataset keeps only its full, numbered
revisions. Every removed file remains recoverable with `git show 248f7bf:<path>`.

| Removed | Contents |
| --- | --- |
| Workflow | `core/raw/_impl/releases.py`: authorized tag creation, resolution and browsing. |
| Values and ports | `Release`, `RevisionRef`, `ReleaseStore`, `ReleaseTransaction`, `RawStore.write_tag_once`, `release_tag_file`, tag-name validation and the `TAG_EXISTS`/`TAG_WITHDRAWN` errors. |
| Adapters | Release reads and writes in both hierarchy stores, their row mappers, and the POSIX write-once tag file. |
| API | The three `/api/v1/datasets/{dataset_id}/releases` routes, their models and the tag cursor. |
| Authorization | The `release.create` capability, granted to developers, project admins and platform owners. |
| Tests | The release integration test and its helper, and the release cases of the shared hierarchy, repository, API and role tests. |

Migration `0013_retire_releases` drops the `releases` table with its indexes and trigger, the
`releases_immutable()` function and the `release.create` capability with its grants; it cannot
be downgraded. Tag documents already written under a dataset's `releases/` directory stay on
disk, where nothing reads them. Idempotency receipts of past tag requests stay in
`idempotency_records`; until one expires, it refuses reuse of its key for any other request, as
every receipt does. The `dataset_revisions_id_dataset_id_unique` constraint, which only release
citations referenced, also remains.

## Legacy cutover retirement

On 2026-10-15 the owner retired the one-time v1→v2 cutover machinery and the API-key
Books uploader. Raw keeps verified completion, frozen commit documents and
`committed-v1.json` decoding. Every removed file remains recoverable with
`git show 8b6f270:<path>`.

| Removed | Contents |
| --- | --- |
| Integrity domain | `core/integrity/`: cutover preparation and validation, controller admission and its generation epoch, legacy revision and generation verification, evidence models and ports. |
| Operator CLI | `applications/lakectl/` and its `lakectl` console script: controller socket server, container-engine observations, settings and wiring. |
| Adapters | `core/metastore/legacy.py`, `core/metastore/maintenance.py` and `core/rawstore/maintenance.py`, plus revision-directory parsing in `core/raw/paths.py`. |
| Contracts | `protocol-inventory-v1.json` and `protocol-transition-v1.json`. |
| Deployment | `deploy/controlled/` (systemd units, role SQL, example configuration) and the controlled-cutover operator page. |
| Tests | Unit and contract tests of the integrity domain, controller, `lakectl`, maintenance adapters, writer exclusion and protocol documents; the controlled-cutover integration test and its Podman deployment helper. |
| Books uploader | `scripts/main.py` and its test; scripted uploads return with the SDK and API keys. |

Import-linter keeps 16 contracts: the Integrity edges, Integrity's private-surface
contract and the application-independence contract are gone. The rule that applications
never import each other stays in `AGENTS.md`; its contract returns with a second
application. [ADR-0001](adr/0001-controller-generation-is-the-verification-epoch.md) is
superseded, and the P3 design and implementation plan at the repository root are kept
only as history.

Database objects that only the retired code used remain until a later migration drops
them: the `reconciliation_findings` table, the `DEGRADED` value of
`dataset_revisions.state`, audit rows of kind `integrity.cutover`, and the manually
created roles `huron_app_legacy`, `huron_app_verified` and `huron_cutover`.

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
| Integrity services | [P3 design](https://github.com/karthedew/huron/blob/f1c44e3d56b10806c05373fce5b51c7a44abf146/P3_DESIGN.md), [P3 execution plan](https://github.com/karthedew/huron/blob/f1c44e3d56b10806c05373fce5b51c7a44abf146/P3_IMPLEMENTATION_PLAN.md) |
| Integrity authority | [Authority design](https://github.com/karthedew/huron/blob/7846d67a4c404a00830a6bb7d9255978ee5cfe32/P3_M1B_AUTHORITY_DESIGN.md), [execution plan](https://github.com/karthedew/huron/blob/7846d67a4c404a00830a6bb7d9255978ee5cfe32/P3_M1B_AUTHORITY_IMPLEMENTATION_PLAN.md), [architectural review](https://github.com/karthedew/huron/blob/7846d67a4c404a00830a6bb7d9255978ee5cfe32/P3_M1B_ARCHITECTURAL_REVIEW.md) |
| Integrity progress | [Execution ledger](https://github.com/karthedew/huron/blob/7846d67a4c404a00830a6bb7d9255978ee5cfe32/P3_EXECUTION.md), [M1a validation](https://github.com/karthedew/huron/blob/7846d67a4c404a00830a6bb7d9255978ee5cfe32/P3_M1A_VALIDATION.md), [M1b validation](https://github.com/karthedew/huron/blob/7846d67a4c404a00830a6bb7d9255978ee5cfe32/P3_M1B_VALIDATION.md), [superseded proposal](https://github.com/karthedew/huron/blob/7846d67a4c404a00830a6bb7d9255978ee5cfe32/P3_PROPOSAL.md) |
| Earlier findings and prototypes | [Findings plan](https://github.com/karthedew/huron/blob/7846d67a4c404a00830a6bb7d9255978ee5cfe32/FINDINGS_IMPLEMENTATION_PLAN.md), [retired control-plane plan](https://github.com/karthedew/huron/blob/7846d67a4c404a00830a6bb7d9255978ee5cfe32/CONTROL_PLANE_PLAN.md) |
| Duplication redesign | [Original plan and status ledger](https://github.com/karthedew/huron/blob/7846d67a4c404a00830a6bb7d9255978ee5cfe32/IMPLEMENTATION_PLAN.md), [superseded architecture proposal](https://github.com/karthedew/huron/blob/7846d67a4c404a00830a6bb7d9255978ee5cfe32/design/duplication-architecture.md) |

The duplication backlog remains at the repository root. Archiving earlier reports
does not complete the backlog's outstanding work. The controlled-cutover operator
instructions were retired with the machinery they described; see
[Legacy cutover retirement](#legacy-cutover-retirement).

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
