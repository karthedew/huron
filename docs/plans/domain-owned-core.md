# Domain-owned Core migration

## Status and authority

The architecture and inventory choices in interview questions Q1–Q14 were accepted
on 2026-09-15, including removal of non-useful code within the migration. The design
frontier is closed and the user authorized execution. The source migration and
workflow extractions are implemented and verified, with both independent review
axes closed. The ownership/deletion maps below retain pre-migration
paths as relocation evidence, not current import instructions.

The authoritative target graph and responsibilities are in
`design/architecture.html#domain-owned-core`. Delivery status belongs to
`design/roadmap.html#domain-owned-core-migration`. The rationale is recorded in
[ADR-0002](../adr/0002-domain-owned-core-workflows.md). The
[earlier restructuring plan](backend-restructure.md) remains a historical delivery
record for the former `applications → core → pkg → schema` layout.

## Migration contract

Move from the old import namespaces in one coordinated repository cutover. Preserve
HTTP/OpenAPI responses, ASGI and console entry points, stored document and controller
state formats, authorization and discovery semantics, retry identity, transaction
boundaries, and storage durability. Existing scientific capabilities retain their
current delivery status.

Use the current working tree as the baseline. It already includes catalog workflow
changes, a revised duplication checker and baseline, UML atlases and their renderer,
and other user work. Record the starting diff and preserve those changes. This plan
does not replace the root `IMPLEMENTATION_PLAN.md` duplication work.

## Resolved inventory decisions

### Cross-layer vocabulary and rules

The former `pkg/catalog/layers.py` contained vocabulary and pure rules used by dataset
configuration and the API, including Bronze/Silver/Gold names. Moving it wholesale
to Raw would introduce `catalog → raw`.

Retain the cohesive layer vocabulary, entry/promotion rules, and principal-kind
eligibility rules under published `core.catalog.layers`. Security evaluates capability/layer codes without
importing that Catalog enum. Catalog and Raw workflows compose the domain eligibility
rules with Security's authority checks. Keep cross-layer layout declarations in
Catalog's paths interface; Raw owns staging, revision and release paths. These rules
and path calculations do not establish processing or product workflows.

### Future-facing placeholder interfaces

The old catalog ports declare `SearchProjection`, `ScopedCredentials`,
`CredentialVendor`, `JobDispatcher`, and subject-only `Principal`/`PrincipalResolver`
protocols without implemented consumers. A source owner for job dispatch would
otherwise require an unimplemented compute module or unrelated Catalog ownership.

Retire these unused placeholder declarations from runtime source, retaining their
planned capabilities in the relevant design pages. Repository-wide reference
inspection found no executable consumers in source, tests, scripts, annotations or
embedded subprocess programs. Existing clock/storage protocol tests exercise useful
behavior and migrate with those contracts. Preserve implemented pure rules, including
amendment calculations, and the published reserved error-code vocabulary. Place
existing amendment rules with Raw metadata; do not add an amendment workflow.

## Removal scope and evidence

Remove non-useful code throughout the touched `src/huron` migration surface, including
dead declarations, obsolete compatibility surfaces, redundant wrappers, orphaned
imports and superseded implementation. Usefulness means supporting current behavior,
an agreed invariant, a supported interface, a storage/protocol guarantee or an
operational requirement. A lack of internal callers alone does not establish that a
public pure rule is useless; a test that only checks an obsolete alias exists does
not justify retaining that alias.

The inspected removal set is:

| Removal | Evidence and preservation condition |
| --- | --- |
| Six future-facing declarations in `pkg/catalog/ports.py` | No executable consumers; retain the useful `Clock` and storage interfaces under their new owners. |
| `RoleBindingAuthorizer.decide` forwarding method | Adds no instance behavior and has only a delegation-equivalence test; retain the canonical `decide` function, classification/visibility operations and authorization behavior tests. |
| Ignored `created_by` arguments on actor-bound binding, policy and account creation; ignored `attached_by` on policy attachment | Operations replace these arguments with their bound actor. Remove the redundant public arguments/caller plumbing while preserving stored provenance and attribution tests. Persistence interfaces still receive authoritative attribution. |
| Metastore re-exports of `AuditEvent`, `IdempotencyClaim`, `LedgerEntry`, `Replay`, `Visibility`, `Window` | Migrate real consumers to the canonical domain/Foundation interfaces; remove namespace-only assertions and retain value/ledger behavior tests. |
| Duplicate `IdempotencyClaim` import in `core/raw.py`, other orphaned imports, old `pkg` initializer and empty database placeholder | Remove after caller migration; keep meaningful package/entry-point initializers. |
| Redundant `schema/documents/.gitkeep` | The directory contains tracked document resources. |
| Old pathname-based `rawstore.commit.fsync_tree` | No production caller; descriptor-based `flush_tree` supports current publication. Preserve required file/directory flush, child-before-parent durability, sealed-tree and failure coverage through the retained path before removal. Keep the still-used `fsync_dir`. |

Reassess additional candidates against the same criterion while migrating. Keep a
reviewable deletion inventory explaining either the absent responsibility or its
retained replacement. Remove a superseded interface only after its real callers and
unique behavior have moved: this applies to `AccessPolicy.dataset`, broad hierarchy
ports and old construction interfaces. Private ingestion/revision mechanics,
claim/replay behavior, persisted SQL contracts, document resources and historical
evidence remain useful. Changes to tests must preserve unique behavioral evidence;
deleting a required assertion is not a substitute for preserving its guarantee.

## Source ownership map

Paths in this table name the migration baseline; targets name the new owners. Split mixed
files at symbol boundaries rather than moving the containing file indiscriminately.

| Current source | Target and important symbols |
| --- | --- |
| `core/catalog_creation.py`, `catalog_collections.py`, `catalog_documents.py` | Catalog: creation, typed collections, descriptions and generation documents. |
| `core/raw.py`, `_ingest.py`, `revisions.py`, `_revision_reader.py`, `releases.py` | Raw: complete authorized operations and private mechanics; publish ledger, download and expiry results. |
| `core/access.py`, `scopes.py`, `identity.py`, `bindings.py`, `policies.py`, `service_accounts.py` | Security: authority, account/credential administration, policies and bindings. |
| `core/integrity/` | Integrity: cutover, generation/revision verification and evidence contracts. |
| `core/catalog_ports.py`, `core/ports.py`, consumed `pkg/catalog/ports.py` protocols | Split into each consumer's Catalog, Raw, Security or Integrity ports; shared clock goes to Foundation. |
| `core/idempotency.py` | Foundation gets generic request hashing; Raw gets manifest-specific `session_claim`. |
| `core/catalog_claims.py` | Preserve claim/replay behavior in the consuming operation; any reused helper must have an explicit public owner. Foundation owns retry primitives, not transaction orchestration. |
| `pkg/catalog/records.py` | Catalog gets organization/project/dataset records; Raw gets releases and publication audit records; Security gets bindings, policies, attachments and service accounts; Foundation gets generic JSON conversion. |
| `pkg/catalog/models.py` | Catalog gets `EntityRef`; Raw gets revision references/records and publication outbox events. |
| `pkg/catalog/persistence.py` | Catalog gets `PlatformRoot` and published `Window`; Raw gets `LedgerEntry`; Foundation gets `IdempotencyClaim` and `Replay`. |
| `pkg/catalog/manifest.py` | Raw gets manifests and path/content validation; Foundation gets JSON values and canonicalization/hash primitives. |
| `pkg/catalog/ingest.py`, `documents.py`, `metadata.py` | Raw: session/file transitions, commit evidence, codecs, revision indexes and `MetadataSubmission`. |
| `pkg/catalog/ids.py` and generic safe-name validation | Foundation: preserve identity generation, encoding and name rules. |
| `pkg/catalog/paths.py` | Catalog hierarchy/generation and cross-layer paths; Raw staging/revision/release paths; generic lexical validation in Foundation. |
| `pkg/catalog/lifecycle.py`, `layers.py`, `amendments.py` | Lifecycle vocabulary and layer rules in Catalog; amendment rules in Raw. |
| `pkg/catalog/errors.py`, `failures.py` | Common failures in Foundation; owner-specific failures with their domains; transport-only failures in applications. Inventory reserved codes explicitly. |
| `pkg/auth/`, `pkg/rbac/` | Security mechanisms, rules, values, errors and ports, except concrete memory stores. |
| `MemoryApiKeyStore`, `MemoryCredentialStore`, `MemoryPrincipalStore`, `MemorySessionStore` | Metastore; remove Security re-exports that would import adapters transitively. |
| `pkg/metastore/`, `pkg/rawstore/` | Corresponding Core adapter packages, including legacy maintenance adapters. |
| `schema/` and its document resources | Existing shared document contracts and validation. Raw/Integrity models never become dependencies of Schema. |

Remove the old `pkg` namespace after migrating callers. The empty `pkg/database`
directory contains no implementation. Audit imports in scripts, test helpers,
patch targets, subprocess program strings, source introspection and deployment
references as well as ordinary Python import statements.

## Published interfaces

These are intended import locations, not requirements to create empty modules or a
class for every function. Public modules should own a meaningful caller contract;
internal implementation can be composed freely within its owner.

| Package | Published surface |
| --- | --- |
| `core.foundation` | Focused `errors`, `canonical`, `identifiers`, `names`, `retry`, and `clock` modules. No Huron imports. |
| `core.catalog` | Creation and organization/project/dataset collection operations at the root; `types`, `errors`, `ports`, `paths`, and `layers`. |
| `core.raw` | `RawRuntime` constructs actor-bound ingestion and revision-read operations and owns trusted expiry; `Releases` handles immutable tags. Published types/errors/ports, manifest/metadata/document codecs, paths/retry and amendment rules support those operations. |
| `core.security` | Access/identity/governance operations, `PasswordAuthentication`, `OidcAuthentication`, `CredentialAuthentication`, `terminate_session`, `self_access_summary` and trusted `bootstrap_platform_owner`; published types/errors/ports and credential/role interfaces. |
| `core.integrity` | `CutoverService` including `validate_sequence`, and `ControllerAdmission`; evidence/state/identity values and external authority, observation, exclusion and persistence ports. |
| `core.metastore` | Concrete PostgreSQL and memory adapter constructors, maintenance adapters and clock implementation. Domain values are imported from their owners. |
| `core.rawstore` | POSIX and maintenance storage constructors, lifecycle and adapter-specific failures. Structural conformance keeps its only Huron dependency at `schema.storage`. |

Use a protected `_impl` subtree for private implementations where this makes import
enforcement explicit. Root exports may import their own implementation. Published
types must not import workflow implementations or ports. Keep `huron.core.__init__`
minimal; importing Foundation must not initialize Security or concrete adapters.

Domain constructors receive ports, clocks and plain configuration values. Applications
create and close the pool, HTTP clients, storage adapters and background tasks. Add a
public construction function only where callers would otherwise need private mechanics.
Keep authenticated `Principal` distinct from its narrower RBAC projection, with an
unambiguous exported name for each.

## Workflow contracts to preserve

### Security and catalog facts

Security owns narrow projections for authoritative project classification, dataset
parents, scope ancestry, discoverability/existence and organization naming. Metastore
supplies these facts using the existing visibility predicates. Security makes the
authority decisions. Full dataset retrieval belongs to Catalog, replacing
`AccessPolicy.dataset() -> Dataset`.

Preserve dataset-scoped discovery, visible ancestors, filtering before keyset limits,
404 for undiscoverable resources, fresh operation checks, credential-specific
restrictions, and disabled-account behavior. A caller-provided visibility object must
not become a substitute for authorization. Catalog's current call to private
`AccessPolicy._resolve_scope` must be replaced with a supported operation.

### Raw and releases

Raw owns session/file/lease rules and the complete storage-first publication workflow.
Its consumer-owned persistence interface retains these atomic groups:

1. Session/revision-number reservation, retry claim, audit and opening receipt.
2. First `COMMITTING` transition, immutable `CommitIntent`, and unfinished commit receipt.
3. Locked session check, revision insertion, `COMMITTED` transition, audit, outbox and
   completed retry receipt, on one database connection and transaction.

Filesystem publication remains between freeze and final database recording, with the
derived revision index updated afterward. Dataset creation plus first upload remains
an ordered recoverable operation rather than a newly invented distributed transaction.

Preserve the global `(principal, key)` retry namespace, fingerprint encoding and
unfinished-commit retention. Release creation keeps its existing target lookup,
permissions, database/tag-file ordering and dataset-level `releases/{tag}.json` path.
The current lookup resolves a registered revision without a state predicate; this
migration must not add a new committed-state or payload-read prerequisite.

Catalog receives a narrow generation-storage interface. Raw receives a cohesive
storage interface, with internal facets where useful. One POSIX object can implement
both. Generation replacement, exclusive tag creation and idempotent envelope-document
installation remain distinct operations with distinct retry semantics.

### API and authentication

Keep early HTTP guards through public inspection/authorization operations, preserving
pre-body rejection and discovery/error ordering. Complete domain operations enforce
authorization independently of the guards.

Extract password authentication through persisted session issuance, OIDC begin/finish
login, credential resolution/bookkeeping, session termination, self-access summaries
and trusted initial-owner bootstrap into Security. Preserve credential precedence,
failure mapping, optional rehash behavior, bounded off-event-loop password work,
session lifetime and OIDC flow checks. Sample credential expiry/activity time after
awaited lookup, and derive OIDC validation lifetime from the issued cookie's lifetime.
Applications own credential extraction,
cookies, CSRF, redirects and response serialization.

API expiry retains scheduling, cancellation and logging while calling a published Raw
maintenance operation. Bootstrap and expiry retain their trusted deployment authority;
ordinary scientist operations continue requiring authenticated actors.

Compose public error-code vocabularies in the application instead of inspecting a
private manifest implementation. Preserve all parameterized path codes and reserved
codes, AuthError/RoleError mapping and the existing file-range 416 response. Keep
independent implementation/raise-site evidence in error-contract tests.

### Integrity and operator application

Extract reusable controller epoch, evidence-admission and restart-exclusion policy
behind Integrity's public interface. Keep Podman-specific observations/control,
kernel peer authentication, socket transport, settings, durable I/O and process
lifetime in injected application capabilities. Add a complete stored-sequence
validation operation so the CLI does not coordinate evidence loading and validation.

Preserve [ADR-0001](../adr/0001-controller-generation-is-the-verification-epoch.md):
epoch advancement precedes the relevant refusal or writer termination; failed live
observations including cancellation invalidate the epoch; bad receipt arguments do
not invalidate someone else's valid epoch; an active run still excludes restart;
persistence failure cannot leave the old epoch admissible in memory. Preserve
controller-state JSON, socket operations, CLI flags and evidence decoding. The full
legacy scan stays outside the serialized controller request loop.

Relocation changes the source-path-based digest recorded for newly executed code.
Historical records retain their original identities. Existing incomplete protocol
activation, startup-gating, recovery and storage-certification work stays planned.

## Execution slices

These are review and feedback slices within one coordinated cutover. They do not
authorize shipping mixed namespaces, forwarding shims or weaker temporary contracts.

1. **Baseline and relocation inventory.** Confirm the complete plan. Capture HEAD,
   working diff, OpenAPI and source/error/removal inventories. Run the
   current gates before source edits and record failures accurately. Build the
   file/symbol relocation map used by imports, source links and duplication accounting.
2. **Foundation and owned contracts.** Remove the confirmed unused placeholder
   interfaces. Split mixed values/errors/paths/retry code;
   introduce narrow consumer ports and public types. Preserve canonical bytes, IDs,
   error vocabulary and static document resources. Move memory auth adapters with
   their PostgreSQL counterparts.
3. **Security and catalog operations.** Colocate their rules and workflows, implement
   security-owned fact projections in both real and memory adapters, and extract
   reusable authentication/bootstrap operations. Verify direct non-HTTP authority and
   real-adapter discovery/pagination behavior.
4. **Raw and publication.** Move ingest/evidence/revision/release rules and operations,
   narrow persistence/storage views, and publish construction, inspection and expiry
   interfaces. Exercise retries, incomplete transfers, conflicts and crash windows.
5. **Integrity and application consumers.** Extract controller policy with injected
   observation/state capabilities. Rewire API dependencies/runtime/guards, authentication,
   expiry, readiness/construction and `lakectl` exclusively through public interfaces.
   Preserve startup/shutdown order and early rejections.
6. **Graph, tools and documentation cutover.** Complete the usefulness-based deletion
   pass and its evidence inventory. Remove old imports and namespace;
   replace the old layer/independence contracts with the classified target graph and
   private-surface protection. Reconcile duplication paths, Ruff path configuration,
   source-linked design, instructions, tests and scripts.
7. **Complete gate and handoff.** Run the full gate below, compare OpenAPI and stored
   contracts with baseline, inspect import and complexity findings and the complete
   diff, and update delivery status from evidence. Missing infrastructure or a failing
   required test prevents a complete-delivery claim.

## Import enforcement and tooling

Use import-linter's explicit allowed direct importers or direct forbidden edges,
package-level acyclic-sibling checks with type-only imports included, exhaustive Core
subpackage inventory, and protected implementation modules. Package roots may export
their own implementation. Domain-to-adapter prohibitions include indirect imports.
Apply those prohibitions to the classified domain packages, not the whole enclosing
Core package, which now contains adapters.

Preserve framework exclusions for Foundation/domain code, allowing the existing
credential-related libraries in Security and concrete driver/storage libraries in
adapters. Applications remain independent siblings. Adapter imports in applications
belong to composition/lifecycle code, not routes importing re-exported domain values.

Prove the gate rejects a forbidden direct edge, a type-only reverse edge, an indirect
adapter dependency, a private implementation import and an unclassified Core package.
It must accept permitted root re-exports and the declared one-way edges. This is a
subpackage policy, not a claim that every internal Python module forms a DAG.

The current duplication guard is path-sensitive. Capture its current-tree report
before relocation. Remap genuine one-to-one paths with clone totals, group sizes,
scanner version and threshold preserved. Review splits/merges against the original
fragments; do not regenerate a permissive baseline from the finished tree. Reject
unexplained new or grown clone groups and rerun the unchanged full-source guard.

## Documentation reconciliation during implementation

Update the implemented-boundary sections of `design/architecture.html` and
`design/roadmap.html` only when the migration is verified. Reconcile `AGENTS.md`,
`CLAUDE.md`, package docstrings, repository-layout/conventions/testing guides,
`design/core-map.html`, affected API/Raw/auth/RBAC/catalog design references, all
affected Markdown/HTML UML atlas pairs and their renderer inputs. Coordinate edits
to the active duplication plan and user-owned atlases with their current contents.
Historical delivery receipts retain their historical paths and results.

## Acceptance evidence

| Contract | Required evidence |
| --- | --- |
| Public interfaces and DAG | Positive/negative import-contract checks, typed wiring conformance, no old imports including embedded subprocess programs. |
| Useful implementation only | Reviewed deletion inventory, absence of retired placeholders/aliases, migrated real callers, preserved unique invariants and operational behavior through the retained interfaces. |
| Authority and discovery | Direct domain tests plus API mapping tests for unauthenticated/undiscoverable/wrong-target access, dataset-only grants, current permissions and account disablement. |
| Catalog and releases | PostgreSQL-backed creation/CAS/idempotency, visibility-before-limit pagination, generation/tag-file ordering and release target compatibility. |
| Raw publication | Real PostgreSQL/POSIX tests for reservation/freeze/final-record atomicity, independent completion, checksum/size failures, retries, concurrency and process death. |
| Authentication and lifecycle | Existing HTTPX/respx and direct Security tests for password/OIDC/API-key/session behavior, bootstrap idempotence, bounded blocking work and resource cleanup. |
| Operator integrity | Direct epoch/admission tests and full controlled-cutover integration, including failure/cancellation/persistence and restart exclusion. |
| External contracts | Pre/post OpenAPI comparison, error-code/status/body tests, exact stored-document/evidence/controller-state formats, ASGI and `lakectl` entry points. |
| Large transfers | Full-size acceptance upload/resume/download through a real HTTP socket. |
| Documentation | Strict site build plus source/anchor checks for standalone design HTML and atlas companions. |

Run from the repository root using its uv environment and lockfile:

```sh
make lint
uv run pytest -m unit --cov=src/huron --cov-report=term-missing
uv run pytest -m contract
uv run pytest -m integration
make test-acceptance
make docs
git diff --check
```

`make lint` includes Ruff, pydoclint, mypy, ty, import-linter, the schema-map check,
radon, complexipy, pyscn and the duplication guard. Inspect findings as well as exit
codes. Preserve the configured coverage and complexity thresholds; the current
coverage floor is 96.01%. Tests retain unique behavioral evidence while their imports
and construction change; an in-memory adapter does not replace a PostgreSQL contract.

### Infrastructure and baseline qualifications

PostgreSQL suites require a working testcontainers endpoint and disposable PostgreSQL
16. Controlled cutover additionally requires Linux, Podman, root or noninteractive
sudo on an isolated test deployment, and the pinned historical Git object
`db5fc84cd7bfe049692ef2abb16fb32570ccf5a2`. Ensure runner history contains that object.
Retain required SELinux labeling on enforcing hosts. Raw acceptance needs at least
25 GiB free on the actual test-data filesystem.

Historical D4 receipts include a cutover failure because sudo required a password and
a failure under the previous native-duplication-score gate. The current working-tree
duplication checker uses a different regression contract. A fresh baseline was captured
before this migration; the final receipts below cover the complete current source.
A deselected cutover test or zero collected integration tests is not a completed gate.

## Execution and verification receipts

Baseline: `e71e685310ef44820de567a967acc74fb8752581` plus the preserved working-tree
changes. Baseline lint passed, 1,692 unit tests passed at 96.02%, 49 contract tests
passed, and the full-size acceptance test passed. Fourteen ordinary integration
tests passed on the host; the unchanged controlled-cutover test passed in an isolated
Podman-capable runner because the host lacks Podman and noninteractive sudo.

All seven execution slices are complete. Source now has 161 Python modules; the old
`pkg` source namespace and obsolete flat Core interfaces are removed. Authentication,
self-session and bootstrap workflows belong to Security. `ControllerAdmission`,
`MaintenanceGrant` and `DeploymentIdentity` own Integrity policy; the application
resource context yields `CutoverService` directly. The deletion inventory was extended
to remove the superseded authentication dependency wrappers and per-operation operator
wrappers while retaining their behavioral evidence.

Final checks after review fixes:

| Check | Result |
| --- | --- |
| `make lint` | Pass: Ruff/format, pydoclint, mypy, ty, 19 import contracts, schema map, radon, complexipy, pyscn and duplication guard. |
| Unit coverage gate | 1,797 passed; 96.39% coverage against the unchanged 96.01% floor. |
| Contract suite | 49 passed against real adapters. |
| Complete integration suite | 15 passed together in the isolated Linux/Podman runner, including real controlled cutover; no integration case skipped or excluded. |
| Raw acceptance | Full-size 9 GiB interrupted upload/resume/download test passed. |
| OpenAPI | Canonical 144,266 bytes retain SHA-256 `f648da8949b67ce80b7298815fb4042c23b2104db26bee3de60cefd43fc7f0c9`. |
| Complexity and duplication | No radon C-or-worse complexity or B-or-worse maintainability findings; complexipy maximum 15 retained. Final 141 clones / 46 groups against the unchanged 145 / 48 allowances. |
| Documentation | Strict site build, regenerated atlas companions, source/anchor and diagram consistency checks, and light/dark browser checks at 390/816/1440 px passed. |
| Whitespace and imports | Migration-scoped diff check passed; no retired executable imports or old `pkg` Python source remains. Whole-tree diff check still reports unrelated baseline whitespace in `minihuron/rawstore.py:24`. |

The duplication baseline's paths were reconciled using original fragment contents,
hashes and locations; counts, individual group allowances, scanner version 1.31.1 and
similarity threshold 0.8 were preserved. Two genuinely new duplicate groups introduced
by the controller extraction were resolved through shared grant/identity rules and
resource ownership, rather than added to the baseline.

### Standards review

The independent review identified application HTTP parsing inside the credential
workflow and duplicated OIDC lifetime configuration. Both were corrected: the API
extracts the token, preserving absent versus present-empty behavior, and runtime
wiring supplies the cookie's actual max-age. Reinspection found no outstanding
Standards finding.

### Spec review

The review reproduced credentials expiring during awaited lookup being accepted
because the extracted workflow sampled time too early. Resolvers now receive the
clock and sample it at the original post-lookup check point. Deterministic regression
tests cover key expiry, session idle/absolute expiry and late activity, plus cookie
lifetime and header-presence cases. Six regression cases failed before correction
and passed afterward. Reinspection found no outstanding Spec finding.

Local detailed receipts are under `/tmp/opencode/huron-migration-baseline` and
`/tmp/opencode/huron-migration-final` (`*-reviewed.log` records the final source gate).
The final complete integration receipt is under
`/tmp/opencode/huron-cutover-runner/20260916T190405Z-huron-cutover-4d6f1b35245e`;
both pytest and container exited zero and the owned container/volume were removed.
It ran `uv run --locked pytest -m integration -vv -s --junitxml=/logs/integration.xml`
against a copy of the current source with the pinned historical Git object, using
private Podman services without a host-engine socket. The retained runner image is
`sha256:a23621092bd8dc4e2d80e767562718a83b1cf20fb22c5e7ab36db7c7edd39d94`.
