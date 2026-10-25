# Repository layout

```text
huron/
├── design/                             authoritative architecture record and source-linked atlases
├── IMPLEMENTATION_PLAN.md              duplication refactoring sequence and verification gates
├── RAW_LAKE_SPEC.md                    Raw lake spec of record
├── RAW_LAKE_DESIGN.md                  Raw lake design
├── RAW_LAKE_IMPLEMENTATION_PLAN.md     Raw lake implementation plan
├── RAW_STORAGE_DESIGN.md               Raw storage design: superseded, kept as history
├── RAW_STORAGE_IMPLEMENTATION_PLAN.md  Raw storage plan: superseded, kept as history
├── docs/                               this site — how to work on the repository
├── migrations/                         Alembic; schema.sql is a read-only summary of the whole metastore
├── scripts/                            bucket bootstrap and other operational helpers
├── src/huron/                          the application (see below)
├── tests/                              unit · contract · integration · acceptance
└── web/                                SvelteKit front end
```

## Backend boundaries

Dependencies point inward: **applications → core → schema**. Core's domain and adapter
subpackages follow the explicit acyclic graph in root `AGENTS.md` and
`design/architecture.html#domain-owned-core`.

```text
src/huron/
  applications/api/   FastAPI routes, credentials/cookies, settings and lifecycle wiring
  core/foundation/    canonical JSON, identities/names, common errors, retry and clock contracts
  core/security/      authentication, identity, authorization and their complete workflows
  core/catalog/       hierarchy, dataset/layer configuration, descriptions and discovery
  core/metastore/     PostgreSQL and in-memory persistence adapters
  core/rawstore/      POSIX staging, hashing, independent copies, rename and sealing
  schema/             canonical JSON schemas, loaders and shared primitive contracts
```

Domain objects, rules, workflows and consumer-owned ports live together. Public scientific
operations enforce current permissions; credential workflows establish identity and
maintenance operations use explicit deployment authority. Applications call published
operations and construction interfaces; private `_impl` modules hold internal mechanics.

Metastore implements domain persistence/fact interfaces. Rawstore satisfies storage
interfaces structurally and imports only shared Schema contracts. Domains never import
concrete adapters, database drivers, FastAPI or Ray. Import-linter checks the allowed
direct edges, sibling cycles, private surfaces and framework exclusions, including imports
used only for typing.

Raw revisions contain exactly the submitted files, with no inherited files or shared
hardlinks. Metadata uses a shared Pydantic input contract and authoritative backend
validation. The Python SDK, Ray/Zarr workflows, and other planned deployables gain
packages when implemented. Unused future-facing placeholder protocols are retired.

See [conventions](conventions.md#import-boundaries), root `AGENTS.md`, and
`design/architecture.html` for package rules and workflow responsibilities.

Completed plans and per-attempt report dumps are archived through
[Implementation history](../history.md). Generated analysis reports and coverage
JSON stay out of version control; `scripts/duplication_baseline.json` remains tracked.
