# Repository layout

```text
huron/
├── design/                  THE authoritative design record (13 cross-linked HTML documents)
├── IMPLEMENTATION_PLAN.md   build order and code-level mechanics, P0–P10
├── RBAC_IMPLEMENTATION_PLAN.md
├── docs/                    this site — how to work on the repository
├── migrations/              Alembic; schema.sql is a read-only summary of the whole metastore
├── scripts/                 bucket bootstrap and other operational helpers
├── src/huron/               the application (see below)
├── tests/                   unit · contract · integration · acceptance
└── web/                     SvelteKit front end
```

## The three surfaces

`src/huron/` has exactly three surfaces, and the dependency between them runs one way —
**service → pkg → schema**:

```text
src/huron/
  service/    composition roots, one per deployable
              api/            the FastAPI control plane
                              authorization.py   the Depends chain: credential → principal → check
                              repository.py      hierarchy + RbacStore/ApiKeyWriter Protocols
                              postgres_rbac.py   the asyncpg implementations of those Protocols
                              routes/v1/         schemas.py + endpoints/
  pkg/        independent libraries
              catalog/        the manifest, hierarchy, layer workflow, and paths
                              paths.py    the sole constructor AND parser of storage paths
                              layers.py   the raw→bronze→silver→gold workflow
              rbac/           the pure decision engine (decide, Binding, Scope)
                              roles.py    the role model — the source of truth for the matrix
              identity/       authentication: credential → Principal
              rawstore/       NFS/POSIX staging, hashing, hardlink dedup, atomic rename, sealing
  schema/     the shared floor: canonical JSON Schema documents plus loaders and types
```

Only the deployables that have real code exist on disk. The others named in
`design/architecture.html` §2 — `prepare`, `bronze_builder`, `canonicalizer`, `product_runner`,
`validator`, `projection`, `polaris_sync`, `sweeper`, `reconciler`, `retention`, `lakectl` — are
created in the change that gives them code, not scaffolded ahead of need. The same applies to
`pkg/`: `objectstore`, `metastore`, `searchindex`, `credentials`, `jobrunner`, `polaris` and
`telemetry` return when they do something.

## The rules that bite in review

**No package imports a sibling package.** A package that needs another's capability declares a
`typing.Protocol` for it and receives a conforming object from a service. Because Protocol
conformance is structural, the implementing package does not import the declaring one either —
which is what makes `pkg/*` genuinely independent rather than merely tidy. `pkg/catalog/ports.py`
is the worked example.

**All glue lives in a service.** A service reads settings, constructs concrete stores, and injects
them. Behavior two services both want becomes a package — never an import of the sibling that
already has it.

**`catalog` and `rbac` hold rules, not I/O.** No web framework, database driver, or storage SDK
reaches them; those arrive as an injected Protocol. Data-modeling and validation libraries
(`pydantic`, `jsonschema`) are deliberately allowed — `schema/` is built on them and `catalog`
validates against `schema/` rather than restating formats.

**A package that wants to log uses stdlib `logging`** and the service configures capture, rather
than every package importing one shared logging module.

All four of these are mechanically enforced; see [conventions](conventions.md#import-boundaries).
