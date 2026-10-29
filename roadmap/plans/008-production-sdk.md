# Phase 008: production scientist Client SDK

Status: BLOCKED — credential-provider decision, isolated packaging and backend phases.

## Context and outcome

The server distribution currently installs src/huron with Core/storage dependencies;
there is no delivered scientist SDK. Empty server Catalog interface scaffolding is
not a client. Accepted SDK front door is Client(), like Databricks SDK, with direct
client.search/client.datasets/client.rawstore services, not mandatory client.catalog.
Stable imports from huron.client and huron.catalog reexport supported classes/functions
defined in their interface/ subdirectories. SDK is a lightweight separate distribution,
never server Core alias. Array libraries are later optional work, not Raw dependencies.

Complete MVP includes production SDK: Collection catalog, schema governance/validation,
tus streaming/resume/cancellation, pinned-base add/delete/replacement pushes, exact
metadata/schema inheritance, committed-readable receipt replay, PostgreSQL search,
download/export and scoped access. Backend interoperability slice 005 alone is not
production SDK completion. Google login does not provide Huron API-token issuance.

## Prototype evidence

SDK isolation independent review 1 (2026-10-06) succeeded on bounded checks with no
SDK defect: two fresh runs each had 59 observations, 595 behavior outcomes and 340
subcommands; 6,408 RECORD rows across 26 environments had no overlapping paths.
Complete qualification FAIL solely on 2,330 unchanged root-checker artifact whitespace
findings, not PASS. Actual artifacts are under `roadmap/prototypes/sdk-isolation/`;
the original flat `sdk_isolation.py` command remains only an old illustration.
See [prerequisite receipt](../prerequisite-review-2026-10-06.md). No production
namespace change is authorized. Require 005 interoperable Python tus
receipt and 006 crash/retry outcomes. 003 must qualify actual credential provider/
broker and refresh/revocation behavior; no Google ID token bearer shortcut. Minimal
bounded SDK probe uses 1 MiB plus zero-length/variable PATCH/cancel cases against
owned test server, not a 10 GiB buffer. Exact library versions/commands recorded.

## Exact scope and ownership

- Proposed 002-owned SDK layout `sdk/src/huron/client/interface/{client,credentials,errors}.py`,
  `sdk/src/huron/catalog/interface/{datasets,search,metadata,values}.py`, root reexports;
  `sdk/src/huron/rawstore/interface/{uploads,releases,values}.py` for rawstore service.
  Private `sdk/src/huron/_transport/{http,tus,mapping}.py` and generated wire module.
  Exact namespace packaging remains gated by 001/002; do not create duplicate server
  namespace ownership. Public methods must perform actual backend calls.
- `sdk/pyproject.toml`, sdk lockfile, sdk tests and build configuration, root
  `scripts/check_sdk_distribution.py` and OpenAPI generator/check scripts from 002;
  SDK docs and examples. No dependencies on huron.core, asyncpg, SQLAlchemy or FS adapters.
- Existing `openapi/v1.json` planned artifact from 002; publish generated Python wire
  contracts but keep tus streaming handwritten with documented protocol headers/status.
- Proposed `sdk/tests/{unit,contract,integration}/`; preserve server test ownership
  and add root tests/integration/test_sdk_workflow.py against real backend once package
  exists. No server SDK alias/shim, no root application sibling imports.
- Delete earlier prototype-only SDK scaffolding only if found and explicitly inventoried;
  do not delete user catalog/interface files or unknown local client code.

Fresh deployment approved 2026-10-06; no legacy data conversion here or SDK migration
shim. Server bootstrap refuses nonempty targets rather than resetting unrelated data.
No API compatibility shims: map deliberate backend shape
and public SDK value differences. Isolated SDK build/test scripts and CI ownership
must exist before commands below are treated as runnable. Root Python lint source
scope does not automatically check sdk/src.

## Interfaces and implementation examples

Illustrative target (not installed code):

```python
from huron.client import Client
from huron.catalog import Dataset

with Client() as client:
    page = client.search.query(text="beam", collection=collection_id)
    dataset: Dataset = client.datasets.get(dataset_id)
    receipt = client.rawstore.push(dataset.id, base=exact_release,
        additions=[local_file], deletions=["obsolete.csv"])
    exported = client.rawstore.export(receipt.release_id)
```

Client owns transport lifetime, injected credential provider and service composition.
Services expose meaningful operations and typed public errors; no private imports
for callers. Choose sync/async surface through prototype, document cancellation and
resource cleanup; never nest event loops implicitly. Credentials live in approved
provider storage, not source/logs; acquisition/refresh distinct from identity login.
Server remains authoritative for authorization, ancestry and metadata validation.

For new dataset creation, require descriptive fields/scientific metadata/schema bundle.
Later OMITTED sentinel inherits exact pinned-base pair; None explicitly rejects,
{} validates, replacement requires explicit schema. Local validator pinned to backend
profile; resolve immutable refs once, no uncontrolled fetch. Push uploads only new
bytes using bounded chunks, sequential PATCH per file, across-file concurrency limit;
HEAD after ambiguous response, persist resumable identity without credential leakage.
Wait through server verification/copy/commit and return release receipt only when
readable. Distinguish stale-base conflict, auth revocation, invalid metadata, checksum,
capacity and network ambiguity with stable errors. Replays preserve request identity,
not generate a new key on every retry. Download streams; export defaults pinned
snapshot, live titles separately labelled. Retry policy cannot conceal permission loss.

Approved stale-base policy (2026-10-06): base and metadata/schema stay frozen through
upload. Backend compares expected base/current head atomically with catalog publication
under qualified serialization, including expected empty head for concurrent first
pushes. An uncommitted loser has no published lineage/receipt; hidden candidate
cleanup remains recoverable. Map typed stale-base conflict (illustrative HTTP 409)
to caller-visible review/retry, never auto-repin, implicit merge/rebase or reuse of
identity with changed input. Explicit retry resolves a newer base and creates a new
operation identity/fingerprint; omitted metadata inherits that exact pinned pair.
Same-identity already-COMMITTED replay after authorization returns the original outcome
even if head advanced. Test lost-response replay separately from explicit new attempts;
never acknowledge unpublished success or leak hidden head/source details. This is
planned mapping, not current wire or qualified serialization/recovery evidence.

Schema restricted profile 2 has independent bounded review 2 PASS, not product
approval. Correct codec/canonical bytes authority rather than an artificial 1e20
restriction is an unqualified numeric-comparison recommendation, not a selected SDK
profile. Do not silently promote either policy into client validation.

## Serial task slices

1. Pending: isolated wheel/public imports and qualified credential provider; typed
   transport/error/pagination mapping, no storage dependencies. SDK+server gates below.
2. Pending: datasets/schema/search/export service methods and shared validator corpus;
   explicit omission/null/empty and historical bundle cases. Real backend integration.
3. Pending: tus streaming/resume/cancel/full push receipt and bounded memory;
   same-identity replay/revocation/stale-base/error paths. Full 9 GiB acceptance through
   SDK on real backend, not each unit test; keep fixture/behavior reuse.
4. Pending: user docs/build artifacts/clean install and generated-client drift; review
   supported imports and dependency graph. Independent rerun of complete gate.
All serial, skills below, max three reviews; no release/publish to package registry
without explicit user authorization.

## Skills

`.agents/skills/oop-design/SKILL.md`, `.agents/skills/fastapi/SKILL.md` for reviewed
HTTP contracts, `.agents/skills/implementation-plan/SKILL.md`. Consult installed
HTTPX 0.28.1 official API for streaming/lifetimes; inspect pinned generator/provider
versions rather than inventing APIs. No Svelte edits in this phase.

## Acceptance and complete applicable gates

Root locked uv/Python >=3.12: `make lint`;
`uv run pytest -m unit --cov=src/huron --cov-report=term-missing`;
`uv run pytest -m contract`; `uv run pytest -m integration`; `make test-acceptance`;
`make docs`; `git diff --check`; `uv run python scripts/check_openapi.py --check`;
`uv run python scripts/check_sdk_distribution.py`. The last scripts are 002-owned
prerequisites, not existing commands at planning time. Real PG16/testcontainers,
owned API/OIDC/directory, isolated Linux/Podman integration and historical object,
>=25 GiB acceptance disk. No services/no tests is BLOCKED.

SDK cwd after 002 creates config: `uv sync --locked`; `uv run ruff check src tests`;
`uv run ruff format --check src tests`; `uv run mypy src` (strict configured);
`uv run pytest --cov=src/huron --cov-report=term-missing`; `uv build`.
Phase 002/this author owns sdk dev dependencies, pytest marker/default setup,
coverage/import/complexity commands and CI wiring before READY; do not assert current
root gates cover SDK. Set SDK floor no lower than server 96.01%, changed reachable
behavior covered, import isolation check fails on server dependency. Add SDK generation
drift to check_openapi script explicitly; never hand-edit generated wire types.
Keep server thresholds/ratchets, radon C+/MI B+ findings, no skips/xfails/weaker assertions.

Reuse metadata corpus, tests/ingest_client.py semantics and real adapter workflow
fixtures; unit mocks only external HTTP boundary. Measure bounded memory on streaming,
not whole-body TestClient materialization. Record build artifact/contents/dependencies,
versions/exits/coverage/logs and independent baseline/reviewer reruns. No frontend gate.

## Blockers and readiness

001/002 namespace+wheel evidence/scripts, user/identity owner SDK issuer/broker,
003 freshness/provider, 004 metadata, 005 tus, 006 receipt, 007 search/export.
Sync/async surface and SDK exact lint/complexity/import gate configuration require
prototype resolution before `/implement-markdown roadmap/plans/008-production-sdk.md`.

## Execution ledger

Planning writer attempt 1; no SDK implemented/prototypes run; review count 0. Future
parent tracks session/model/role/times/commands, serial reviews and 15-minute progress/
minute polling. No package publish permission implied.

## Escalation / final receipt

BLOCKED draft. Final receipt includes clean install and scientist workflow through
committed readable release, not only a Client class or generated transport.
