# Repository layout

```text
huron/
├── design/                  THE authoritative design record (15 cross-linked HTML documents)
├── IMPLEMENTATION_PLAN.md   build order and code-level mechanics, P0–P10
├── RBAC_IMPLEMENTATION_PLAN.md
├── docs/                    this site — how to work on the repository
├── migrations/              Alembic; schema.sql is a read-only summary of the whole metastore
├── scripts/                 bucket bootstrap and other operational helpers
├── src/huron/               the application (see below)
├── tests/                   unit · contract · integration · acceptance
└── web/                     SvelteKit front end
```

## Backend boundaries

Dependencies point inward: **applications → core → pkg → schema**.

```text
src/huron/
  applications/api/   FastAPI routes, credentials/cookies, settings and lifecycle wiring
  core/               authorized catalog, identity, Raw ingestion and revision reads
  pkg/catalog/        entities, state transitions, manifests and document validation
  pkg/auth/           credentials and identity primitives
  pkg/rbac/           role and scope evaluation
  pkg/rawstore/       POSIX staging, hashing, independent copies, rename and sealing
  pkg/metastore/      PostgreSQL and in-memory persistence adapters
  schema/             canonical JSON schemas, loaders and shared primitive contracts
```

Core's public services bind an authenticated actor and enforce current permissions.
Private core modules implement persistence and ingestion mechanics for those services;
they are not alternate entry points for callers. The API manages HTTP concerns and
constructs adapters. Domain objects own invariants and meaningful transitions; core
composes domain and infrastructure capabilities through consumer-owned protocols.

Domain packages and rawstore remain independent siblings. Metastore may import domain
types to persist them; domains cannot import metastore. Core never imports concrete
storage adapters, database drivers, FastAPI or Ray. Import-linter checks these rules.

Raw revisions contain exactly the submitted files, with no inherited files or shared
hardlinks. Metadata uses a shared Pydantic input contract and authoritative backend
validation. The Python SDK, Ray/Zarr workflows, and other planned deployables gain
packages when implemented; this restructure does not scaffold them.

See [conventions](conventions.md#import-boundaries), root `AGENTS.md`, and
`design/architecture.html` for package rules and workflow responsibilities.
