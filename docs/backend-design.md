# Backend design at a glance

This page is a map, not a description. **`design/`** at the repository root — fifteen
cross-linked HTML documents — is the complete and only authoritative record of what Huron is and
why; see the "Where to look for what" table on the [Home](index.md) page. Restating its content here
would create a second copy that has to agree with the first forever, which is exactly how the
previous `docs/` tree drifted (see [Conventions](getting-started/conventions.md#the-design-record)).
This page instead orients a new reader — what the fifteen documents cover, the shape of the
system in one paragraph, and where to read build status (which lives with the plan itself, in
`design/roadmap.html`).

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
or Gold, only service accounts can.

## The fifteen documents

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
| The end-to-end scientist journey, twice: web UI and Python client | `workflows.html` |
| Build phases, mechanical gates, sequencing rationale | `roadmap.html` |

Open any of them directly (`design/index.html` in a browser is the front door); they are not part
of this site's build, so there is exactly one copy.

## Where build status lives

`design/roadmap.html` is both the plan and the dashboard: the backend build phases (**P0–P10**,
its §2) and the frontend-integration tiers (**T0–T6**, 25 milestones, its §3) each carry a
status tag — `done`, `partial`, or `todo` — and the partial rows say exactly what is shipped
versus outstanding. Landing work updates its tag there in the same change. This page keeps no
status copy of its own, so there is exactly one to keep true.

For the day-to-day build order and what's landed in the auth and RBAC slices specifically, see
`IMPLEMENTATION_PLAN.md` and `RBAC_IMPLEMENTATION_PLAN.md` at the repository root.

!!! warning "One status copy"

    Earlier, `design/` was deliberately status-free and this page held the dashboard. That was
    reversed on 2026-08-31: one document now holds plan and status together. Do not reintroduce
    a status table here — two copies is how drift starts.
