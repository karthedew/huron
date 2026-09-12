# Independent D2 standards and behavior review

Conclusion: **no actionable findings** in the reviewed D2 source and tests.

Read-only review against IMPLEMENTATION_PLAN.md D2 and the D1 source snapshot
(`duplication-evidence/d1/tree-hashes.json` and `source-working.diff`), using the
project-local OOP, codebase-design, FastAPI and PostgreSQL instructions.

Inspected DescriptionChange, concrete typed collections, GenerationDocuments,
consumer-owned description transaction ports, memory/PostgreSQL typed CAS writers,
runtime typing, three PATCH endpoints and migrated/new behavioral tests.

- Fixed concrete construction binds entity reader, scope/capability and storage;
  callers cannot independently choose an entity-kind capability for a collection.
- Describe discovers the target and checks update authorization before domain
  validation. Fresh visibility is retained; narrow dataset ancestry still uses
  the existing internal unrestricted ancestor reads.
- Existing domain describe owns slug-before-version and stale-no-op checks;
  null fields retain values, empty strings replace them. Valid no-ops return
  before transaction creation or generation publication.
- PostgreSQL CAS uses the enclosing writer connection and bound values, with
  trusted closed table selection. No-match fails before generation writing.
  Memory keeps its previous committed-version comparison and staged replacement.
- Successful CAS precedes committed ancestry reads, then generation writing
  off the event loop, then transaction exit/commit. Generation failure propagates
  through the transaction for rollback. No independent transaction was introduced.
- Generation serialization matches the prior canonical document/schema behavior;
  creation's shared document calls retain their off-thread placement.
- Old patch/update forwards and declarations are removed. HTTP models and
  precondition conversion remain unchanged. Migrated repository behavior tests
  now exercise actual authorized collections; unique test functions were retained.
- New direct-core tests cover all three kinds for no-op, stale/slug precedence,
  empty replacement and authorization beyond discovery. New integration tests
  synchronize matching pre-reads against PostgreSQL, verify exactly one CAS winner
  and one generation write, and test generation failure rollback plus retry for
  all three entity kinds using POSIX storage. Thread checks verify publication
  runs outside the event-loop thread.

## Snapshot and limitations

D2 changed/new files relative to the D1 hash inventory were hashed individually.
SHA-256 of the sorted JSON path-to-SHA-256 mapping:

`c5097d1b36ef0484921f77586acf12ba3a00a2b15992bf61e1e7e1f32791aa9c`

Files inspected in this bounded change:

- `src/huron/applications/api/routes/v1/endpoints/datasets.py`
- `src/huron/applications/api/routes/v1/endpoints/organizations.py`
- `src/huron/applications/api/routes/v1/endpoints/projects.py`
- `src/huron/applications/api/runtime.py`
- `src/huron/core/_catalog.py`
- `src/huron/core/catalog.py`
- `src/huron/core/catalog_collections.py`
- `src/huron/core/catalog_documents.py`
- `src/huron/core/catalog_ports.py`
- `src/huron/core/ports.py`
- `src/huron/pkg/metastore/hierarchy.py`
- `tests/hierarchy_contract.py`
- `tests/integration/test_catalog_descriptions.py`
- `tests/unit/test_core_workflows.py`
- `tests/unit/test_repository_hierarchy.py`

No tests, scanners or verification gates were independently run. This conclusion
is source/test inspection, not a gate PASS claim; integration assertions describe
what the authored tests prove when executed, not an independent execution receipt.
The implementer's/parent's gate logs remain required. Later material changes need
a refreshed affected review. D3–D7 and final native 90 remain outside this review.
