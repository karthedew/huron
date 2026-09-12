# Architecture toward a native duplication score of 90

Status: **proposal**, 2026-09-10. Source baseline: `6082088`.
This document proposes a refactoring program; it does not mark it implemented,
certify a score of 90, or change M1a's delivery status.

## Recommendation

Replace the repeated catalog interfaces with cohesive, authorized workflow
modules. Use typed collections for the genuinely shared `get`, `browse`, and
`describe` operations; keep creation and publication operations explicit. Remove
the current public-to-internal forwarding layer instead of adding another layer
over it. Inside persistence adapters, share typed query execution while retaining
explicit projections, visibility predicates, decoders, and transaction writers.

This combines a smaller interface with explicit domain rules. It offers more
leverage than further helper extraction: one implementation of a complete
operation can replace repeated methods across core and persistence. Splitting
files alone, or moving repeated code behind new forwarding methods, does not
deliver that change.

The governing constraints remain [the architecture](architecture.html),
[Raw ingestion](layer-raw.html), [authorization](rbac.html), and
[repository instructions](../AGENTS.md). The implemented durability evidence and
remaining M1a limits are recorded in [the validation record](../P3_M1A_VALIDATION.md).
M1b/M1c cutover and deployment remain outside this proposal.

## Baseline and the size of the target

The fresh command was:

```sh
uv run --locked python scripts/check_duplication.py src
```

It returned exit 1 because the score is below the gate. The complete report is
`.pyscn/reports/analyze_20260910_070754.json`, generated locally with pyscn 1.31.1.
All 109 source Python files were analyzed; none were skipped.

| Measurement | Baseline |
| --- | ---: |
| Native duplication score | 50/100 |
| Cloned fragments / all fragments | 241 / 800 |
| Cloned fraction | 30.125% |
| Clone pairs | 319 |
| Clone groups | 60 |

The separate overall health score is 90/A. It does not satisfy the duplication
gate and is not a ranking against other projects.

The [pinned analyzer](https://github.com/ludo-technologies/pyscn/blob/v1.31.1/domain/analyze.go)
uses the [shared scoring function](https://github.com/ludo-technologies/polyscan/blob/core/v0.2.7/core/domain/scoring.go).
Its rounding requires a cloned fraction **strictly below 7.5%** to score at least
90. The checker must continue using the native report score; this calculation
explains the target rather than replacing the gate.

| Final total fragments | Maximum cloned fragments for 90 |
| ---: | ---: |
| 800 | 59 |
| 700 | 52 |
| 600 | 44 |

Removing methods usually shrinks both counts. In a simplified model where each
deleted fragment was cloned and nothing else changes, reaching 90 from 241/800
would require removing at least 196 fragments: `(241 - 196) / (800 - 196)` is
below 7.5%. Actual refactors can also remove clone relationships from surviving
fragments, add necessary implementations, and create new matches. Consequently,
neither a line-count reduction nor a sum of candidate fragments predicts the
final score.

### Where the 241 fragments live

These are disjoint file buckets, counted from `clone.clones`. They describe the
inventory, **not promised removals**. Counting only group members would miss two
fragments in this report; pair counts are a different measure again.

| Area | Cloned fragments |
| --- | ---: |
| HTTP transport and application wiring | 65 |
| Hierarchy persistence and row decoding | 45 |
| Catalog workflows and shared core ports | 37 |
| Other domain, authorization, and identity code | 31 |
| Raw ingestion, revision reads, and storage | 28 |
| Identity, RBAC, and authentication persistence | 25 |
| Catalog record declarations and methods | 10 |
| **Total** | **241** |

Concrete clusters include twelve pagination declarations/delegators across
`core/catalog.py`, `core/_catalog.py`, and `core/ports.py`; twenty-five lookup-like
fragments across persistence adapters; twelve scope-specific binding endpoints;
and twenty-six structurally similar value/response declarations. Some members of
the same scanner group perform different operations. In particular, a locking
read, credential lookup, role revocation, and discoverable catalog read cannot
share a policy merely because their bodies resemble one another.

## Three alternatives considered

### 1. Minimize entry points

A typed collection could expose only `get`, `browse`, and
`change(Create[draft] | Describe)`. The result would retain that collection's
concrete entity type. It would hide authorization, idempotency, descriptive
transitions, and generation publication.

This has high potential leverage for common reads and descriptive updates.
Creation is the weakness: project classification, dataset profiles and entry
layers, root/parent scope, and dataset-specific persistence need different inputs
and preparation. A universal `change` grows several type parameters and callbacks.
Those callbacks become a second interface callers and maintainers must learn.

### 2. Separate workflows and use focused persistence ports

Give catalog management, discovery, binding/policy administration, ingestion,
and revision reads the capabilities each consumes. Share typed read execution
inside adapters, while keeping operation-specific transaction writers.

This gives the best locality for security and durability rules. PostgreSQL and
memory already provide two real adapters, so the persistence seam is justified.
Port splitting alone offers no score improvement: the redundant methods must
actually disappear. Excessive fine-grained ports would also burden composition.

### 3. Optimize the ordinary caller

Expose actor-bound organization, project, dataset, and binding operations that
perform the entire workflow. HTTP handlers pass typed inputs and receive domain
results. Existing response models can validate and filter those results without
an explicit conversion in every handler.

This is the clearest caller experience. It removes the mirrored authorized and
unauthorized catalog surfaces. Separate classes that repeat every method for each
entity, however, would preserve much of today's structural duplication.

### Chosen combination

Use alternative 3's complete authorized operations, alternative 1's shared typed
read/description implementation, and alternative 2's transaction discipline.
Keep creation explicit. Avoid a universal command bus, generic CRUD manager,
runtime-generated router registry, or reflection-based persistence framework.

## Proposed interfaces and ownership

Illustrative use of the proposed interfaces:

```python
# Application wiring supplies the concrete typed collection and authenticated actor.
project = await projects.get(project_id)
page = await projects.browse(organization_id, window=requested_window)
updated = await projects.describe(
    project_id,
    DescriptionChange(expected_version=project.version, title="New title"),
)

# Creation retains a concrete input and its own parent/classification contract.
created = await creation.create_project(
    organization_id,
    ProjectDraft(slug="analysis", title="Analysis", description="", classification="open"),
    claim=claim,
)
```

These names are proposed, not existing interfaces. `projects` has a statically
known `Project` result; `browse` returns the existing typed window shape. A
description change preserves current PATCH semantics: omitted or null title and
description fields retain their values; an empty string replaces them. Changed
slugs fail before version comparison, and a stale no-op still fails. A collection
is selected by trusted application wiring, not by caller-supplied table names,
model names, or capability strings.

### Authorized catalog operations

Consolidate authorization and orchestration from
[`core/catalog.py`](../src/huron/core/catalog.py) and
[`core/_catalog.py`](../src/huron/core/_catalog.py). Target responsibilities are:

- A shared described collection for organizations, projects, and datasets.
- Explicit organization/project/dataset creation workflows.
- A release module for immutable tag publication and resolution.
- Binding, policy, and service-account administration with their distinct rules.
- Authorization facts used internally for fresh ancestry, classification, and
  binding evaluation.

Application composition may bundle these objects, but the bundle has no second
set of forwarding methods. Bootstrap and readiness take their actual required
capabilities rather than an unauthorized copy of all scientific operations.

The shared collection owns visibility calculation, parent discovery, descriptive
validation, optimistic concurrency, and generation publication. Concrete typed
construction fixes the resource kind, reader, update capability, and parent scope
together; these must not be independently configurable. The collection can retain
its actor and collaborators, but recomputes visibility and permissions for every
operation.

Use the existing shared descriptive transition and closed
organization/project/dataset dispatch inside one workflow. It owns authorization
and domain validation, then either returns a no-op or opens a transaction for CAS,
immutable path resolution, durable generation writing, and commit. Preserve the
existing committed ancestry reads; moving them onto a transaction connection is
a separate semantic change requiring justification. Typed writers perform
persistence. Resource definitions have no sequencing hooks such as `before_save`,
`authorize`, or `after_update`. If an operation requires them, split that operation
out; a large callback descriptor is an interface failure.

Retain `Organization`, `Project`, `Dataset`, and `Release` as distinct domain
concepts. The first slice can reuse the existing shared descriptive transition in
[`records.py`](../src/huron/pkg/catalog/records.py). Do not force unrelated value
objects into one record type, or add a hierarchy of classes merely to reduce
scanner matches.

### Persistence seams

Replace repeated point/window execution in
[`metastore/hierarchy.py`](../src/huron/pkg/metastore/hierarchy.py) with typed read
collections and adapter-private query execution. A fixed `Projection[T]` pairs an
explicit SQL column selection with its decoder; a fixed selection owns its
joins, visibility predicate, cursor ordering, and bound parameters.

The useful shared operations are required lookup, optional lookup, and keyset
page execution. Missing-row behavior is an explicit part of each operation.
SQL identifiers come only from trusted definitions; request values are bound
parameters. Memory implements the same observable collection contract using its
own data structures, not SQL inheritance.

Keep explicit typed decoders in [`rows.py`](../src/huron/pkg/metastore/rows.py)
where aliases, joined fields, JSON, enums, nullability, or nested values differ.
A `Model(**dict(row))` convention would conceal those contracts. Shared query
execution must not absorb a locking read or mutating `RETURNING` statement into
an ordinary read path.

Split the broad [`core/ports.py`](../src/huron/core/ports.py) by actual consumers
and atomic operations. Catalog mutation, Raw publication, and binding
administration need different capabilities. Within each transaction, all reads
and writes that require atomicity use the same connection or staged memory
transaction. A narrow port must not open a second independent transaction behind
the workflow's back.

### HTTP transport

Keep existing paths, named schemas, headers, status codes, and explicit HTTP
operations. Use `response_model=ExistingView` when returning an internal domain
record with a different public schema. Retain special transport work such as
ETags, Location, retry status, streaming, and redaction where the contract needs it.

Share hierarchy view fields only within that real schema family. Preserve
separate named organization/project/dataset response types and entity-specific
fields. The three PATCH models also have a shared descriptive contract worth
measuring. Do not unify credentials, leases, policies, or revision receipts just
because each declares fields.

Binding endpoints can consume a typed, authorized binding collection resolved
from the path. System and resource scopes still have explicit authorization rules;
collection membership is checked before a binding may be revoked. HTTP guards
remain early transport checks; every core operation remains independently secure.

### Raw and identity operations

Where a public Raw operation forwards to an internal implementation, put mandatory
authorization and the workflow in one module. Retain named `receive_part`,
`complete`, `verify`, `commit`, and `abort` operations. Lease fencing, file
membership, owner/admin exceptions, immutable intent, and crash recovery are
distinct contracts, not variants of generic CRUD.

Later identity/RBAC work may share genuine required/optional read mechanics and
existing policy calculations. Token parsing, expiry, revocation, service-account
authority, and human session rules remain explicit. Similar syntax is insufficient
evidence for a shared security policy.

## Measured prototype

An isolated source-copy experiment introduced a shared six-field hierarchy view
base (`id`, `slug`, `title`, `description`, `version`, `created_at`) for
`OrganizationView`, `ProjectView`, and `DatasetView`. Production source was not
modified.

| Same full-source scanner configuration | Baseline | Three-view prototype |
| --- | ---: | ---: |
| Python files analyzed / skipped | 109 / 0 | 110 / 0 |
| Native duplication score | 50 | 50 |
| Cloned / total fragments | 241 / 800 | 237 / 798 |
| Clone pairs | 319 | 312 |
| Clone groups | 60 | 60 |

Fresh-process full OpenAPI documents were equal after normalizing the order of
JSON Schema `required` arrays. All three view and three page component names
remained present; the implementation base did not appear as a public component.
A separate FastAPI response experiment returned an organization domain record
through `response_model=OrganizationView`: its JSON matched explicit
`model_validate`, and the internal `generation` field stayed excluded.

This proves a narrow schema/serialization opportunity and a small measured clone
reduction. It does not prove the complete module design, all response families,
or runtime behavior for a production refactor.

Temporary evidence is under `/private/tmp/huron-common-caller-design/`, including
`verify_schemas.py`, the two source copies, preserved scanner reports, and OpenAPI
documents. Run the verifier from the repository's locked environment with
`uv run --no-sync python /private/tmp/huron-common-caller-design/verify_schemas.py`.
The temporary artifacts are not durable delivery records; retain equivalent
evidence with an implementation change before relying on it for acceptance.

## Migration order and acceptance

### 1. Prove one complete catalog slice

First implement organization/project/dataset read collections through both
existing adapters, including the typed query executor needed for these reads.
Move their authorization into the workflow and remove the corresponding old
wrappers, declarations, and adapter delegators. Measure the full source tree.

Then migrate descriptive updates and their transaction ports through the same
three concrete collections. Preserve the existing domain transition behavior and
measure again. These three actual uses test whether the shared interface earns
its keep; separate readings show which change affects duplication.

Cover direct core calls and HTTP calls for hidden targets, wrong parents, narrow
grants, stale versions, immutable slugs, and no-ops. Confirm visibility filtering
precedes pagination, existing collation/cursors are preserved, and hidden parents
remain undiscoverable. Prove failed CAS writes no generation; a successful update
writes its durable generation before committing PostgreSQL; filesystem failure
rolls back the database change. Test these guarantees with PostgreSQL and the real
filesystem, including concurrent updates.

Remeasure the entire `src` tree. Record native score, cloned/total fragments,
remaining matching symbols, file coverage, tests, and any newly introduced
matches. If the collection only relocates wrappers or requires an extensible
callback framework, revise it before expanding the migration.

### 2. Remove the remaining mirrored catalog surface

Move explicit creation, release publication, and binding/policy administration
into their authorized workflow modules. Share common mechanics where the operation
contract is the same; retain the existing ordering of claim ownership, discovery,
validation, and permission errors. Matching idempotent retries return the same
result; mismatched commands still conflict. Retire `HierarchyRepository` only
after its real responsibilities have moved and all callers have migrated.

### 3. Simplify transport and persistence around the new interfaces

Apply the measured hierarchy schema reuse, response-model serialization, shared
PATCH inputs, and the proven read executor to other compatible reads. Verify full
OpenAPI and response behavior, including secret-field exclusion and error ordering. Keep explicit SQL
decoders and transaction writers when they own distinct contracts. Migrate tests
to the new public seams while preserving every unique behavioral and failure case.

### 4. Reassess the remaining inventory

Use the new report to choose identity/RBAC read mechanics and any remaining
authorized-to-internal forwarding for the next complete slices. Raw changes must
retain M1a's proven crash states and transaction boundaries. After freezing the
intent in PostgreSQL, filesystem publication remains a separate durable phase;
revision, session, audit, outbox, and retry receipt publication remain one later
database transaction. No proposed adapter creates a distributed transaction.

A residual clone allowance is necessary for distinct contracts. At a final 600
fragments, for example, at most 44 can remain cloned. Recompute this allowance
from each actual report. If useful refactors leave more, the next step is a new
architectural assessment of those exact matches; the current proposal does not
establish that all of them can be safely eliminated.

### 5. Complete the unchanged gates and independent review

Before claiming the architecture achieves the target, run `make lint`, the unit
coverage gate, and affected contract/integration suites. Any ingestion/durability
changes also require the applicable acceptance suite with P3's disk prerequisite
satisfied. Run documentation-site checks when site documents change. Independently
review authorization, transaction grouping, type precision, and whether old
interfaces truly disappeared.

Keep pyscn 1.31.1, the existing analyzer settings and source scope, the native
90 threshold, import contracts, coverage/complexity thresholds, and required
tests. Do not gain points by exclusions, suppressed findings, padding the
denominator, removing documentation, or changing declaration syntax solely to
evade detection. The final complete native report and all applicable gates are
the evidence of completion.

## Dependency and test strategy

Domain transitions, canonical documents, and RBAC calculations are in-process
dependencies: test their behavior directly. PostgreSQL and POSIX storage are
locally substitutable dependencies: use injected ports for deterministic core
tests and real adapters for locking, visibility SQL, transaction rollback,
durability, and crash recovery. Existing OIDC/provider integrations remain
external dependencies behind their credential interfaces.

Applications own concrete pools, stores, authentication extraction, and resource
lifetimes. Core owns the authorized workflows and consumer ports. Metastore and
rawstore implement I/O without importing core policy or transport. Preserve the
existing import contracts and verify structural conformance at application wiring.

This proposal establishes a concrete architecture and a measured first
opportunity. **Reaching native 90 remains an implementation hypothesis**, to be
resolved by the complete catalog slice and subsequent full-source measurements.
