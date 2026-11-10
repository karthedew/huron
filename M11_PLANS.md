# M11 plans: index

Date: 2026-11-10. These five files replace `IMPLEMENTATION_PLAN_LATEST.md` as the plan to execute.
That file stays in the tree as a record. Do not execute it.

## Why the plan was split

M11.5e "Repair" failed its third verification on 2026-11-08, and the old plan stopped there.
A discovery run then reported seven defects (F1 to F7) in the upload and commit code of M11.1 to
M11.7. The replacement plan grew to 42 serial slices. On 2026-11-10 the owner accepted a smaller
scope: fix the data-safety defects, finish the remaining M11 tasks, and defer the rest.

## The files and their order

| Order | File | Content | Needs |
| --- | --- | --- | --- |
| 1 | [M11_PLAN_1_REPAIR.md](M11_PLAN_1_REPAIR.md) | Finish and accept M11.5e | Nothing |
| 2 | [M11_PLAN_2_SAFE_PUBLICATION.md](M11_PLAN_2_SAFE_PUBLICATION.md) | Server fix for F1 to F6 | Plan 1 |
| 3 | [M11_PLAN_3_CLI_RECOVERY.md](M11_PLAN_3_CLI_RECOVERY.md) | CLI fix for F5 and F7 | Plan 1. Task C3 needs plan 2 task S7 |
| 4 | [M11_PLAN_4_STACK_DEPLOY_DOCS.md](M11_PLAN_4_STACK_DEPLOY_DOCS.md) | The remaining old tasks M11.8 to M11.13 | Plans 2 and 3 |
| 5 | [M11_PLAN_5_DEFERRED.md](M11_PLAN_5_DEFERRED.md) | The work that was cut, as a backlog | Not executed |

Plan 3 tasks C1 and C2 do not depend on plan 2. They can run before, between or after its tasks.

## Rules for every plan

- [AGENTS.md](AGENTS.md) holds the layout, the conventions, the gate and the testing standard.
- Sections 3 to 9 of [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) stay the binding design.
  Each plan lists the decisions that it replaces. Do not edit the old plan.
- Execute one plan at a time with `/implement-markdown <plan file>`. One task at a time, the full
  gate for each task, one independent verification before a task is complete.
- Commit after each task that passes verification.
- The gate is `make gate`. A task that changes a PostgreSQL adapter or a migration also runs
  `uv run pytest -m contract`. A task that changes a route also runs `make openapi`, then
  `npm run generate:api`, `npm run check` and `npm test` from `web/`.
- Use the cached images only, with `--pull=never`: `tusproject/tusd:v2.10.1` and `nginx:1.31.8`.
- Preserve `migrations/versions/0003_uploads.py` and the branch `m11.5-escalated`.
- The seven defects are reported by `design/m11-prototype-evidence.md`. They were not reproduced
  again for this split. Each plan's first test for a defect must fail on the current code.

## Decisions that the split changes

| Topic | `IMPLEMENTATION_PLAN_LATEST.md` | These plans |
| --- | --- | --- |
| Writer exclusion | Manual handover after any loss of ownership | One replica and a PostgreSQL advisory lock. The process exits when it loses the lock |
| Quotas | Three levels with reservations | One global limit on staged bytes and a free-space reserve |
| CLI credentials | Approved destinations, provenance, recovery binding | No change to login. `scripts/dev-login.sh` stays |
| CLI source files | Private copy of every staged file | Size, modification time and hash recorded at `add`, checked at `push` |
| Production interlock | Writes disabled from P07 to P39 | No interlock. The old write path works until task S7 replaces it |
| Prototypes | Four experiments before any code | One experiment: the tusd handoff (task S1) |
| Schema | Staged table renamed later | New tables with final names. One later migration drops the old tables |
