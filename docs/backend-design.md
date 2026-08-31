# Backend design at a glance

This page is a map, not a description. **`design/`** at the repository root — fourteen
cross-linked HTML documents — is the complete and only authoritative record of what Huron is and
why; see the "Where to look for what" table on the [Home](index.md) page. Restating its content here
would create a second copy that has to agree with the first forever, which is exactly how the
previous `docs/` tree drifted (see [Conventions](getting-started/conventions.md#the-design-record)).
This page instead orients a new reader — what the fourteen documents cover, the shape of the
system in one paragraph, and, since `design/` is deliberately a fixed target-state record rather
than a status tracker, **what of it actually exists in code today.**

## The shape, in one paragraph

Huron ingests scientific data as immutable **Raw** revisions on an NFS store, builds
source-faithful **Bronze** and canonical **Silver** representations as Zarr + Icechunk
repositories on Ceph RGW, and publishes scientist-derived **Gold** products the same way. The
resource hierarchy is `Organization → Project → Dataset`, with a dataset's revisions forming a
linear, gap-free history and **releases** acting as immutable citation tags into it. PostgreSQL
holds structural state only (identity, sequencing, RBAC, audit, outbox); LanceDB owns all
text/tag/semantic search across all four layers; each store answers exactly one kind of question.
Role-based access control binds identity-provider groups at platform/organization/project/dataset
scope, with the storage **layer** as an independent restriction — no human role can write Silver
or Gold, only pipeline service accounts can.

## The fourteen documents

| Read this for | `design/` file |
|---|---|
| The model, the decisions, the glossary, the worked MCNP example | `index.html` |
| The four stores, the service inventory, data flow, invariants, deployment | `architecture.html` |
| NFS layout, the commit protocol, ingest sessions, retention/purge | `layer-raw.html` |
| Science profiles, extractors, the Bronze build pipeline | `layer-bronze.html` |
| Canonical contracts, the per-dataset Silver repo, concatenation | `layer-silver.html` |
| Products, the derivation record, staleness, tabular/Iceberg products | `layer-gold.html` |
| The PostgreSQL schema, the LanceDB projection, lineage, rebuild | `catalog-search.html` |
| Why Polaris is scoped to Iceberg Gold only, and nothing else | `polaris.html` |
| Roles, capabilities, bindings, the layer permission matrices | `rbac.html` |
| The four credential kinds, the session model, CSRF, admin-provisioned passwords | `auth.html` |
| The FastAPI surface, error codes, data-access grants | `api.html` |
| `huron.open_dataset(...)`, the grant flow, reproducibility pinning | `python-client.html` |
| Pages, flows, admin surfaces, the generated TypeScript client | `frontend.html` |
| Build phases, mechanical gates, sequencing rationale | `roadmap.html` |

Open any of them directly (`design/index.html` in a browser is the front door); they are not part
of this site's build, so there is exactly one copy.

## What's implemented today

`design/roadmap.html` names phases **P0–P10** as the target build order. It's a fixed plan, not a
dashboard — this table is the dashboard, kept here rather than in `design/` because build status
changes on every PR and the design record should not.

| Phase | Delivers | Status |
|---|---|---|
| P0 — Bootstrap | Repo skeleton, tooling, compose stack, CI gates | ✅ Done |
| P1 — Foundations | Domain model, paths/manifest/UUIDv7, hierarchy CRUD + generations, release tags, RBAC (roles, bindings, guards, Postgres-backed store) | ✅ Done — RBAC ahead of where P1 alone requires it; see `RBAC_IMPLEMENTATION_PLAN.md` |
| P2 — Raw ingest & commit | Session state machine, upload plan, POSIX commit protocol, sealing | 🟡 Domain logic and the commit primitives are implemented and unit-tested (`pkg/catalog/ingest.py`, `pkg/rawstore/`) but **not yet wired to HTTP routes** — no `/ingest-sessions` endpoints exist yet |
| P3 — Integrity services | Sweeper, reconciler, `rebuild --from-storage` | ⬜ Not started |
| P4 — Search projection | Outbox consumer, LanceDB tables, `/search` | ⬜ Not started |
| P5 — Governance | Amendments, two-person purge, retention/TTL, quota | 🟡 Amendment fold + field allow-list implemented (`pkg/catalog/amendments.py`); purge, retention, and quota not started |
| P6 — Bronze | Extractor jobs, Icechunk repos, validation gates | ⬜ Not started |
| P7 — Silver | Canonicalizer, contract-driven concatenation | ⬜ Not started |
| P8 — Client GA & grants | STS-vended access grants, `huron` client package | ⬜ Not started — the `/datasets/{id}/layers/{layer}/write-intents` route exists today only as the authorization stub P2 and P8 will hang work off |
| P9 — Gold | Products, derivation records, staleness | ⬜ Not started |
| P10 — Polaris | Sync worker, namespace/table mapping | ⬜ Not started |

Live API surface right now: organizations, projects, and datasets CRUD with generation documents;
release tag create/resolve; `GET /datasets/{id}/layers` (read-only layer state, annotated per
caller); the write-intent authorization stub above; the full RBAC surface (roles, bindings at all
four scopes, service accounts, API keys); policy attachment. Everything else in `api.html` is
still design, not code.

For the day-to-day build order and what's landed in the RBAC slice specifically, see
`RBAC_IMPLEMENTATION_PLAN.md` and `IMPLEMENTATION_PLAN.md` at the repository root.

!!! warning "If this table and `design/` disagree"

    `design/` describes the target system and does not go stale by definition — code either
    matches it or is a bug. This table describes *this checkout* and will go stale the moment a
    phase ships; if you land a phase, update this table in the same change.
