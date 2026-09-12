# Independent D3a review

Conclusion: **no actionable findings** in the reviewed creation slice.

Read-only standards and behavior review against IMPLEMENTATION_PLAN.md D3a,
D2 source identity and evidence, and project-local OOP, codebase-design,
FastAPI and PostgreSQL guidance. No gates were independently executed.

- CatalogCreation retains three explicit workflows. Capability admission precedes
  claim-owner validation; child discovery precedes permission errors. Current
  visibility, slug/classification/entry-layer validation and parent reads retain
  their prior ordering. Parent/storage ancestry is read before claim replay for
  project/dataset creation; no parent check was removed to shortcut retries.
- Claim fingerprint computation remains with the same HTTP/Raw callers; claim
  principal comes from the authenticated actor. Shared claimed_result retains
  the prior claim/optional-replay semantics, including release's dataset/tag read.
- Creation ports describe atomic inserts and claim/receipt writes on the existing
  acquired transaction. Insertion precedes off-thread durable generation writing,
  receipt recording and commit. No second transaction or replacement retry ledger
  was introduced. Failed publication propagates for transaction rollback.
- Dataset profiles remain stored verbatim, entry layer validation unchanged,
  classification inherited from the project. Domain record construction and
  timestamps match the prior behavior.
- Both old three-operation creation surfaces are deleted. HTTP creation uses the
  dedicated Creation dependency, Raw receives a CatalogCreation bound to the same
  actor, and the public core export includes CatalogCreation. Storage initialization
  remains in the existing runtime path pending D4; its remaining repository docs
  describe the reduced responsibilities.
- Migrated tests use actual authorized creation rather than a compatibility wrapper;
  existing test functions/behavior assertions were preserved. The test helper seeds
  the required platform-owner grant or binds an undiscovering actor.
- Six new PostgreSQL/POSIX integration cases cover all three creations: matching
  concurrent claims return one identity with one durable document, changed claim
  fingerprints conflict, generation failure leaves neither row nor claim, and a
  retry succeeds. Dataset case explicitly checks unregistered profile strings.
  The description fixture moved into shared integration conftest with module-level
  database isolation; description assertions remain intact.

## Identity and limits

D3a changed/new files compared with D2 `tree-hashes.json` are listed below.
SHA-256 of the sorted JSON path-to-file-SHA-256 map at review completion:

`b5626f523de1594f599dabb71dd863e39f39d2b8fc39d4bcb5838601895912d1`

- `src/huron/applications/api/app.py`
- `src/huron/applications/api/dependencies.py`
- `src/huron/applications/api/routes/v1/endpoints/datasets.py`
- `src/huron/applications/api/routes/v1/endpoints/organizations.py`
- `src/huron/applications/api/routes/v1/endpoints/projects.py`
- `src/huron/core/__init__.py`
- `src/huron/core/_catalog.py`
- `src/huron/core/catalog.py`
- `src/huron/core/catalog_claims.py`
- `src/huron/core/catalog_creation.py`
- `src/huron/core/catalog_ports.py`
- `src/huron/core/ports.py`
- `src/huron/core/raw.py`
- `tests/catalog_creation_support.py`
- `tests/integration/conftest.py`
- `tests/integration/test_catalog_creation.py`
- `tests/integration/test_catalog_descriptions.py`
- `tests/unit/test_authorization_credentials.py`
- `tests/unit/test_authorization_decisions.py`
- `tests/unit/test_authorization_guards.py`
- `tests/unit/test_catalog_lifecycle.py`
- `tests/unit/test_core_workflows.py`
- `tests/unit/test_repository_hierarchy.py`
- `tests/unit/test_repository_rbac.py`

This is inspection evidence, not a passing-gate receipt. Parent/implementer logs
must establish actual static, unit and real-adapter results. No source, test or
plan files were edited by this reviewer. Later material changes require an
updated affected review. Release extraction, governance retirement and final
native score 90 remain outside D3a's review scope.
