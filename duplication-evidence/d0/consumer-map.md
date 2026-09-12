# D0 consumer and preserved-behavior map

This is a deletion map, not a completed migration. The baseline rows describe ownership; D1 read/fact migrations are recorded below and in the updated deletion matrix.
The complete line-level search in `consumer-references.txt` includes source, tests,
configuration, TYPE_CHECKING imports, and the transport aliases `Catalog` and
`Repository`. `deletion-matrix.md` inventories every method/property of the four
retiring symbols. These two files must be updated together through D1–D6.

| Old surface / consumer family | New owner | Actual baseline callers | Preserved behavioral evidence |
| --- | --- | --- | --- |
| CatalogService hierarchy reads | D1 typed collections | core export; API dependencies; organizations/projects/datasets endpoints; ingest_sessions endpoints | test_core_workflows, test_api_catalog_hierarchy, test_api_visibility, test_api_pagination; shared hierarchy_contract via memory and PostgreSQL |
| HierarchyRepository point/page forwards | D1 typed collections and focused reads | CatalogService; scopes; AccessPolicy; repository tests; internal creation/description/release workflows | test_repository_hierarchy; core reads; hidden parents and narrow grants; C collation and visible-before-limit real contracts |
| HierarchyStore hierarchy point/page declarations | D1 catalog_ports typed reads | _catalog; _ingest publication ancestry; _revision_reader resolution; ApiStores.hierarchy; memory/Postgres adapters conform structurally | test_hierarchy_store_memory, test_hierarchy_store; test_commit_intents, test_ingest_process_death, test_verified_raw_ingest, test_api_revisions |
| HierarchyRepository authorization facts | D1 consumer-owned hierarchy/binding facts | access.binding cache, actor bindings, service-account synthesis, visibility, AccessPolicy; scopes.resource_scope/organization_scope/project_scope/dataset_scope | test_authorization_decisions, test_authorization_credentials, test_api_visibility, test_core_workflows; fresh core permission checks |
| HierarchyRepository HTTP authorization | D1 injected fact collaborators; request cache retained | authorization/decisions.py via runtime.Repository; authorization/guards.py both typed symbol and runtime.Repository alias | test_api_router_composition, test_authorization_credentials, test_api_visibility, scope cases in test_authorization_decisions; hidden target before forbidden |
| CatalogService/HierarchyRepository descriptions | D2 collection describe workflow/CAS ports | all three hierarchy PATCH endpoints; direct repository/core tests | test_repository_hierarchy, test_core_workflows, test_api_preconditions, test_catalog_hierarchy_records; new combined PostgreSQL/filesystem concurrency and rollback evidence needed in D2 |
| CatalogService/HierarchyRepository creation | D3a catalog_creation | hierarchy POST endpoints; RawIngestionService.create_in_project; _catalog claim replay/generation; direct test setup | test_core_workflows, test_repository_hierarchy, test_api_catalog_hierarchy; real claim races/rollback; Raw restart integration |
| CatalogService/HierarchyRepository releases | D3b releases | dataset release endpoints; internal revision_ref and ancestry reads | release cases in test_repository_hierarchy, test_api_catalog_hierarchy, test_hierarchy_store and shared hierarchy_contract |
| CatalogService governance | D4 bindings, policies, service_accounts | bindings/policies/service_accounts endpoints; IdentityService service-account lookup/disable; direct core tests | test_repository_rbac, test_api_bindings, test_api_policies, test_api_service_accounts, test_api_api_keys, test_api_users; real RBAC/auth contracts |
| HierarchyRepository runtime lifetime | D4 application startup and concrete storage capability | app._assemble_runtime construction; runtime.ApiRuntime.repository/api_repository/Repository; dependencies builds four authorized services; app._bootstrap; app._raw_store_probe/_raw_store_failure | test_api_app, test_execution_model, test_api_router_composition; startup initializes raw storage before readiness; bootstrap grants only missing owner binding |
| HierarchyWriter catalog mutation declarations | D2/D3 typed transaction writers | _catalog._claim, creation/patch/release transaction bodies; memory/Postgres hierarchy writers; shared contract typing | CAS/no-op/immutable slug, claim replay ownership, durable generation/tag before commit |
| HierarchyWriter/HierarchyStore Raw and revision declarations | D4 focused atomic ports; D6 named complete Raw/revision workflows | _ingest transactions/read paths; _revision_reader; metastore.ingest composition; ApiStores; typed failing-store test wrappers | test_commit_intents, test_ingest_process_death, test_verified_raw_ingest; test_api_ingest_expiry and crash matrix; publication of revision/session/audit/outbox/receipt remains one transaction |
| Old import names and test factories | Owning slice above | tests/hierarchy_contract, contract hierarchy/commit/process-death tests; unit hierarchy/repository/core/authorization/ingest-expiry/execution-model/support; core.__init__; pyproject named-module contracts | Type checking and import-linter remain strict; migrate unique behavioral cases to new public seam, never delete them solely for referring to old names |

## Critical sequencing constraints

AccessPolicy currently receives one repository for both hierarchy and RBAC facts.
Visibility needs project classifications and dataset-parent facts *before* target
discovery; unrestricted ancestor lookup is internal. `dataset_scope` first reads
the dataset with caller visibility and then its project with `Visibility.ALL`.
A narrow dataset grant must not acquire an independent parent-visibility demand.
PostgreSQL organization/project reads include descendant-grant `EXISTS` logic;
child browse still verifies discovery of the addressed parent before paging.

HTTP binding caching lasts one request. Actor-bound core operations recompute
permissions for every operation. These lifetimes cannot be unified accidentally.
IdentityService disabling includes API-key revocation and already-disabled behavior;
the old catalog disable method is not the complete workflow. Raw creation uses
catalog creation but all later ingest phases retain their fencing and membership.
Revision reads resolve authoritative revisions and manifest membership.

`HierarchyRepository.__init__` initializes Raw storage. Its deletion must migrate
this effect to application startup; readiness reads `repository.raw_store.root`,
and bootstrap uses `bindings_at` plus `grant_role`. They cannot disappear with a
facade. Hierarchy adapters are structural conformers; absence of an import from
core.ports does not mean an adapter is unrelated to a port migration.

D0 adds no tests: existing D1 behavior suites already cover hierarchy discovery,
visibility ordering and pages. D1 must add/strengthen direct-core coverage at its
new seam, including permission changes between operations. D2's combined real
CAS/filesystem guarantees remain explicitly outstanding.


## D1 migration receipt

The six organization/project/dataset point/page methods are removed from both
core surfaces and HierarchyStore; both adapters now implement shared typed
collection reads. CatalogService holds actor-bound collection objects without
read forwarding methods. Raw, revision, internal ancestry, API and test callers
use the new readers. Access and scope helpers accept actual typed hierarchy and
binding facts; HTTP keeps its request cache separately from fresh core authority.
Four authorization-fact forwards are removed from HierarchyRepository.
HierarchyStore inherits HierarchyFacts; RbacStore inherits BindingFacts without
repeating their declarations. Unique baseline scenarios are retained.

[D1 evidence](../d1/README.md) records all gates, exact OpenAPI equality, 100% unit
coverage of the new core collection workflow and the real PostgreSQL contracts.
All creation, description, release, governance and later retirement rows remain
open for their assigned slices.


## D2 migration receipt

Descriptive workflows now live in the authorized typed collections, with
DescriptionChange and typed transaction CAS writers. Old patch/update
forwarders and declarations are deleted. GenerationDocuments provides the
shared canonical durable publication behavior for descriptions and creation.
The [D2 evidence](../d2/README.md) records existing behavior, no-op/error ordering,
real PostgreSQL concurrent winner/loser and POSIX rollback cases, complete unit
and real-adapter gates, and exact native measurement. Creation, release and
remaining governance retirement await their own slices.
