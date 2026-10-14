# Data access seam

The beta Catalog/Browse/Admin routes use live Polaris server operations. Types
for Polaris metadata and Huron accounts live here and are re-exported by
`types.ts`. Server-only clients authenticate each upstream operation as the
signed-in user’s individual Polaris principal; credentials/tokens are never
serialized to the browser. Bootstrap authority is confined to account provisioning,
realm administration and filtered catalog discovery. Polaris owns catalog grants. Huron owns organization membership and immutable realm bindings, and server routes intersect membership with native grants before accessing data.

Dataset inspection is a server-only adapter: it checks the current user's Polaris
read authority, confines FILE storage to configured mounts, and calls a fixed
Icechunk/Zarr metadata reader. Typed projections carry actual schema, references,
history and recorded import provenance. They do not imply scientific publication
or invented downstream lineage. Native Iceberg metadata uses its own Polaris
endpoint; storage credentials and OAuth configuration are never included.

Components consume typed page/action data. Scientific synthetic examples continue
to import through `$api/client`; only `client.ts` may import `fixtures.ts`.
The Raw ingest wizard uses typed browser functions in `$api/client` to call the
authenticated `/ingestion/api` bridge. It transfers actual file parts, verifies
checksums and publishes immutable revisions through the existing Huron Raw core.
The server checks current organization membership and native Polaris RBAC grants
on each operation, then sends a short-lived request-bound delegation to the Raw
API. Browser DTOs never contain delegation credentials. A committed revision is
registered in Polaris with a stable Huron dataset ID; pending registration is
retryable without publishing a second revision. Managed Raw detail reads the
revision list and manifests through the same authorization boundary. External
generic-table registrations retain metadata-only behavior; unknown storage formats
remain Generic.
Legacy scientific fixture routes are not available in beta navigation and redirect
to live Browse.

A generated client from `openapi/v1.json` remains planned for integration with the
Huron scientific backend. Replace hand-written scientific declarations and fixture
implementations at this seam when those frontend workflows are connected. Do not
infer scientific publication/lineage guarantees from Polaris repository registration.

- Domain types belong here, not in routes/components.
- No component/route imports fixtures directly or fabricates domain records.
- All real server operations preserve upstream authorization and concealed-resource
  404 semantics; synthetic actions never imply persistence.
- Stable browse URLs preserve exact namespace boundaries and keyset tokens.

Organization roots map one-to-one to configured Polaris realms. The server selects an
accessible organization before constructing the realm-specific client; public organization
DTOs carry the realm name, never connection credentials. Catalog names are unique only
inside a realm. Generated Browse URLs and every Raw request include the organization,
and a frozen Raw target retains it through retries. Account login is global; credentials,
grant discovery, catalog membership and Raw backend identities remain realm-scoped.
