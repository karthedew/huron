# Independent D1 review

Conclusion: **no actionable findings** in the reviewed D1 changes.

Reviewed read-only against D0 contracts and IMPLEMENTATION_PLAN.md D1, using the
project-local OOP, codebase-design, FastAPI, and PostgreSQL guidance. Scope:

- Typed collection/port construction and fixed resource-reader-parent selection.
- Fresh visibility on each core operation versus the preserved request binding cache.
- Internal pre-discovery classification/parent facts and narrow dataset grants.
- Parent discovery before child paging; unrestricted ancestry remains internal.
- PostgreSQL fixed projections, explicit decoders, bound parameter types,
  descendant-grant predicates, filtering before LIMIT, C collation and cursors.
- Memory adapter parity and committed reads across unchanged mutation transactions.
- HTTP dependency/runtime wiring, Raw publication ancestry, revision discovery.
- Removed old point/page declarations and callers; typed imports and aliases.
- Direct core tests for narrow grants, hidden sibling, revocation on retained
  collections, absent targets and hidden/absent browse parents. Existing test
  functions were preserved; no new suppressions or weakened configuration found.

D2 descriptions, D3 creation/releases, D4 retirement, and later score targets are
outside this review; their remaining implementations are not D1 defects.

## Identity and limits

Baseline HEAD: `6082088dbcf0eda6309e099f122ef01588ead088`.
Reviewed the current uncommitted source/test diff from that HEAD plus new
`catalog_collections.py`, `catalog_ports.py`, and `queries.py`. The snapshot digest
below is SHA-256 of a sorted JSON mapping of those changed/new file paths to their
SHA-256 contents, captured when preserving this review:

`2bc371466f06cfe10b27d6247cb565dbacaec216218fec705137a8125ac299b7`

No production or test files were edited by this reviewer. No tests, scanner runs,
or other verification gates were independently executed; the conclusion is an
inspection result, not a gate PASS claim. The implementer's separate evidence is
required before declaring the slice tested. Later source edits require affected
review and verification to be refreshed.

## Final declaration review

Refreshed after `RbacStore` inherited `BindingFacts` and its redundant
`bindings_for` / `service_account_by_subject` declarations were removed. Their
signatures and full behavioral docstrings now live on the inherited consumer port.
Compiled-grant shape, expiry responsibility, disabled-account visibility and
missing-account errors remain documented unchanged. No runtime adapter or
workflow logic changes in this final move; no actionable defect found. The digest
above identifies the refreshed final D1 snapshot. No independent gates were run.
