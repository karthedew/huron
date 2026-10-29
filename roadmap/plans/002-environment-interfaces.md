# Phase 002: environment, public interfaces and isolated SDK contract

Status: BLOCKED — phase 001 evidence, exact move inventory and runner/topology closure unresolved.

## Context and outcome

Current pyproject enforces seven owners: foundation/security/catalog/raw/integrity/
metastore/rawstore. Applications depend inward on Core then schema. Existing
catalog root exports CatalogCreation/DatasetCollection/OrganizationCollection/
ProjectCollection; Raw exports RawIngestionService/RawRuntime/Releases/
RevisionReadService. Catalog/interface files are empty pre-existing user work.
Do not treat them as delivered supported interfaces or overwrite unknown content.

Accepted target: catalog, combined rawstore workflow+private filesystem adapters,
security, database/schema with asyncpg repositories, integrity. All supported
operations/values/errors/ports in interface/ and root reexports; no private or
type-only cross-owner imports. Move foundation by responsibility. SDK Client()
has direct search/datasets/rawstore; stable huron.client and huron.catalog reexport
their interface surface in a lightweight separate distribution, never server alias.

Today make up starts PG16:5433, MinIO:9000/9001, Keycloak:8081. make stack adds
migrate/API:8080, not frontend. Target adds persistent Raw volume, frontend deliberate
same-origin/session, external directory mock, local OIDC fixture/Google config and
pinned k6 profile. MinIO is optional later infrastructure. No service starts in the
planning turn; future environment changes require ownership/capacity preflight.

## Prototype evidence

SDK independent review 1 (2026-10-06) found no SDK defect and bounded checks succeeded;
complete qualification FAIL solely on 2,330 root-checker artifact whitespace findings.
This supersedes the original no-packaging-probe claim, not the namespace decision or
production approval blocker. Topology remains unqualified. The original proposed root
`uv run python roadmap/prototypes/sdk_isolation.py` is superseded only for the bounded
experiment by artifacts under `roadmap/prototypes/sdk-isolation/`. Still required:
the early fixture-only web/session topology probe and root
`k6 run --vus 2 --iterations 2 roadmap/prototypes/k6-buffers.js`.
Record wheel contents, dependency isolation/coexistence, cookie routing and exact
k6 pin/API/bounded-buffer receipt. None requires 003 identity or 009 UI implementation;
fixture receipts are not integrated Google/directory, real-NFS or full-load evidence.
Reproduce using clean temporary environment, not current editable server install.
Exact SDK distribution name/namespace arrangement is a readiness blocker because
two distributions must not both own huron/__init__.py. Do not add a shim to hide it.

## Exact scope and ownership

Proposed paths, not existing files to create during planning:

- `src/huron/core/{catalog,rawstore,security,integrity}/interface/{__init__,operations,values,errors,ports}.py`
  where justified; roots reexport the supported inventory, not every private class.
- Move `core/raw/_impl/*` workflows into `core/rawstore/_impl/`; move existing
  `rawstore/{store,inspection,completion,materialize,maintenance,commit}.py` and
  remaining adapter helpers into `rawstore/_impl/filesystem/`. Delete old owned raw
  paths only with all consumers/tests rewired in one graph cutover.
- Proposed `core/database/{schema,repositories}/`: move current `core/metastore/`
  adapters to repositories; SQL table definitions arrive with 004. Preserve direct
  asyncpg queries and explicit row/domain mapping. Remove old metastore at cutover.
- Foundation proposed responsibility map: `canonical.py` → `src/huron/schema/canonical.py`;
  `names.py` + path formatting in `identifiers.py` → catalog interface identity/path
  values; UUID minting injected from applications into owners; `retry.py` shared
  catalog mutation identity/receipt contract → catalog/interface/retry.py, with
  security independent of Catalog using its own consumer-owned claim contract;
  `clock.py` → narrow consumer-owned clock ports in security/rawstore/integrity,
  concrete clock at applications. `errors.py` split error-by-error into owner errors
  with API mapping. Remove foundation only after no consumers remain. This proposed
  map needs a symbol-by-symbol cycle/caller inventory from 001 before READY.
- `applications/api/{runtime,dependencies,capabilities}.py`, lakectl consumer imports,
  `pyproject.toml` full import graph, conformance tests and docs/ADR update together.
- Proposed `sdk/pyproject.toml`, `sdk/src/huron/{client,catalog}/interface/`, root
  reexports and no server dependencies; `scripts/check_sdk_distribution.py` and
  `scripts/check_openapi.py` (new owned scripts); `openapi/v1.json` canonical artifact.
  Phase 008 fills services, no empty namespaces advertised as implemented behavior.
- Future `docker-compose.yml`, Containerfile, `web/Containerfile`, `dev.env.example`,
  Makefile, `scripts/check-stack.sh`, `scripts/oidc-test/`, `dev/directory/`,
   `tests/load/` minimal pinned profile consuming the exact version/image digest and
   filesystem API/buffer receipt owned by 001. Identity implementation belongs to 003.
   Full load scripts, real-NFS/generator-at-scale qualification and SLO thresholds
   belong to 010. This profile cannot be READY unpinned and does not depend on 010.

Fresh deployment approved 2026-10-06: no legacy-data conversion is required. Schema
bootstrap/Alembic initialization and nonempty-target refusal/operator action must
still be qualified. No deletion authority: do not reset migrations, volumes,
old revision/tag data or unrelated dirty
source. Inventory every remaining rawstore/metastore file and affected test before
cutover; current glob scope is not authorization to delete unknown work. Rename
Project semantics in 004, not halfway through a package-only move.

## Interfaces and implementation examples

Existing `Clock.now() -> datetime`; `IdempotencyClaim(principal, key, request_sha256)`;
existing catalog root imports private implementations directly. Proposed:

```python
# sdk public caller; illustrative until isolation proof
from huron.client import Client
from huron.catalog import Dataset
# server caller; no SDK/server alias
from huron.core.rawstore import RawIngestionService
```

Class definitions or construction functions in interface may delegate to private
implementations; consumers import roots or supported interface only. Keep a small
consumer-owned persistence port and meaningful workflow operations, not wrappers
for every helper. Runtime lifespan owns pool/storage closing; no sibling application
imports. DTOs stay in applications; domain values never share DB/Pydantic models.

## Serial task slices

1. Pending: inventory exported symbols/import consumers/test owners and prove proposed
   graph acyclic with type-only edges. Files: pyproject and ignored inventory. Gate:
   lint/import contracts + docs checks; no package deletions until reviewed inventory.
2. Pending: environment topology and health checks on dedicated dev stack, persistent
   Raw restart proof, same-origin frontend session fixture. Directory/OIDC container
   contract scaffolding is qualified with fixtures here; actual directory authority
   is implemented in 003. Thus this slice proves topology, not a complete usable MVP
   stack. Files: Compose/build/scripts/settings; no production promotion. Full backend
    + frontend gate below; consume 001's k6 pin for the opt-in minimal profile.
    003 and 009 close functional stack acceptance; their receipts are not entry
    prerequisites for this fixture-based topology slice.
3. Pending: one coordinated owner/interface cutover, retaining existing behavior and
   real durability coverage. Delete obsolete raw/metastore/foundation modules and
   replaced import tests only as mapped; full Python/contract/integration/acceptance.
4. Pending: isolated SDK wheel and OpenAPI artifact/generation script ownership,
   consumer smoke tests and import isolation. Full gates plus new commands below.
All slices use relevant skills, independent baseline/final review, max 3 reviews.

## Skills

`.agents/skills/implementation-plan/SKILL.md`, `.agents/skills/oop-design/SKILL.md`,
`.agents/skills/fastapi/SKILL.md`, `.agents/skills/postgresql-table-design/SKILL.md`,
`.agents/skills/svelte-code-writer/SKILL.md`,
`.agents/skills/svelte-core-bestpractices/SKILL.md`,
`.agents/skills/playwright-cli/SKILL.md`. Load Tailwind only for styling changes.

## Acceptance and complete applicable gates

Root locked uv, Python >=3.12: `make lint`;
`uv run pytest -m unit --cov=src/huron --cov-report=term-missing`;
`uv run pytest -m contract`; `uv run pytest -m integration`; `make test-acceptance`;
`make docs`; `git diff --check`. Preserve 96.01% floor, complexity thresholds and
duplication baseline (no new/growing clone at 0.80); radon C+/MI B+ are findings.
Real PG16/testcontainers + isolated Linux/Podman controlled-cutover runner and
historical Git object; >=25 GiB free acceptance disk. Missing services/no tests is
BLOCKED. Reuse tests/contract/test_catalog_store.py and tests/integration fixtures,
existing public behavior/import tests; no blind rewrite/skips/xfails/suppressions.

Future environment smoke: root `docker compose config --quiet`, `make stack`,
`make check` on owned ports only, once phase authorized; confirm persistence across
owned API restart. Container roles cannot be labelled delivered before this proof.
Frontend cwd web: `npm run check`, `npm test`, `npm run lint`, `npm run build`,
`npm run test:e2e`; autofixer every changed Svelte file via
`npx @sveltejs/mcp svelte-autofixer <path> --svelte-version 5`; named-session CLI
mobile/816px/wide/light/dark/keyboard/loading/error QA, own endpoint/browser first.

New script ownership here (commands NOT runnable today): root
`uv run python scripts/check_sdk_distribution.py` builds/installs an isolated wheel
and rejects server deps/imports; `uv run python scripts/check_openapi.py --check`
compares live generated canonical schema to artifact. Proposed sdk cwd:
`uv sync --locked`, `uv run pytest`, `uv build`; author owns sdk lock/test/build
configuration before these run. Add CI and SDK coverage/import gates with no weaker
server source coverage; do not claim root make lint covers sdk/src automatically.
Independent baselines/reruns capture command/cwd/version/exit/counts/logs.

## Blockers and readiness

001 packaging/fixture-topology and pinned-k6 API/buffer evidence, exact foundation/error/consumer inventory,
namespace ownership and identity broker decision. Fresh deployment is approved,
not runner readiness or permission to remove controlled-cutover/durability tests.
Author must revise concrete file inventory after probes, independently review plan,
then use `/implement-markdown roadmap/plans/002-environment-interfaces.md` only when READY.

## Execution ledger

Planning writer attempt 1; no product commands run; review count 0. No baseline
application PASS claimed. Parent records future child/model/start/update/command,
15-minute progress and minute polls; one writer/reviewer at a time.

## Escalation / final receipt

BLOCKED draft. Record actual moves/deletions and isolation/stack receipts after
execution; never equate package presence with implementation.
