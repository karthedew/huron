# Huron web beta

SvelteKit frontend for the Polaris checkout’s native Icechunk extension. The main
Catalog and Browse views use live Polaris catalogs, namespaces and repositories.
Organizations own multiple Polaris catalogs. Catalogs group programs or data domains; Raw, Iceberg and Icechunk are dataset types that can share a namespace. Huron supplies persistent local
username/password accounts and manual catalog onboarding; Polaris owns grants.
See [design](../design/polaris.html) and the [API seam](src/lib/api/README.md).

## Local stack

From the repository root:

```sh
scripts/polaris-dev.sh start
scripts/polaris-dev.sh samples
scripts/polaris-dev.sh status
```

Open http://127.0.0.1:5173/login. Sign in as `admin` with the generated password
in `.local/huron/initial-admin.json` (created on the first login-page request).
Admin creates organizations, catalogs and people; catalog settings assign Reader, Writer or
Catalog administrator. New users have no catalog access until assigned. Users
can change their own password in Account; admin can reset passwords or disable
accounts. Self-registration is disabled unless explicitly configured. This local workspace also has
`geoscience_reader`, `heliophysics_reader` and `iss_writer`, each assigned only to its topic catalog.
Their generated passwords are in `.local/huron/topic-demo-accounts.json`; earlier example accounts remain unchanged.
Only the three topic catalogs remain in this local workspace. Legacy example catalog
registrations were retired; their repository files and a private recovery manifest
remain under `.local/polaris/`.

The science importers commit real, bounded datasets to three topic catalogs:

- `geoscience.earth.ocean.mur_sst_sample`: NASA JPL sea-surface temperature and error,
  two daily observations on a 128×128 North Atlantic grid.
- `geoscience.earth.energy.power_solar_sample`: NASA POWER solar and thermal
  irradiance, twelve monthly observations on a 16×16 North America grid.
- `heliophysics.solar_wind.ace.ace_magnetic_field`: NASA ACE Level 2 magnetic-field
  measurements, including GSE/GSM vectors and exact native timestamps.
- `international_space_station.instruments.tsis_1.total_solar_irradiance`: TSIS-1
  measurements from the ISS, with uncertainty and quality fields.

Sources: [NASA JPL MUR](https://podaac.jpl.nasa.gov/dataset/MUR-JPL-L4-GLOB-v4.1),
[MUR public Zarr distribution](https://registry.opendata.aws/mur/),
[NASA POWER Zarr tutorial](https://power.larc.nasa.gov/docs/tutorials/service-data-request/aws/),
[NASA CDAWeb](https://cdaweb.gsfc.nasa.gov/),
[TSIS data guide](https://docserver.gesdisc.eosdis.nasa.gov/public/project/TSIS/159520RevA_TSIS_Data_User_Guide.pdf).
Geoscience is imported from public Zarr. ACE and TSIS scientific CSV measurements
are converted into Zarr arrays; values, coordinates, units, quality fields and
original source checksums are preserved. TSIS native zero-valued missing observations are retained, with scientific missing-value metadata; its provisional flag is preserved separately from validity. Original mission downloads and metadata
live in `.local/polaris/source-files/`. Import retries verify and reuse snapshots.
Receipts live in `.local/polaris/`.

To show all three dataset types together, first run `samples` above to retain the
original ACE downloads, then run these commands from the repository root:

```sh
uv pip install --python .local/polaris/icechunk-venv/bin/python \
  'pyiceberg[pyarrow,sql-sqlite]==0.11.1' 'pyarrow==26.0.0'
.local/polaris/icechunk-venv/bin/python scripts/seed_catalog_types.py
.local/polaris/icechunk-venv/bin/python scripts/seed_catalog_types.py --verify-only
```

The dependencies stay in the ignored local science environment; the SQLite extra
supports the seed's temporary SDK tests. The seed checks pinned source hashes and
copies 480,992 bytes into the existing heliophysics catalog's allowed FILE root:

- `heliophysics.solar_wind.ace.ace_source_files`: a Raw generic-table registration
  pointing to the original ACE CSV and native HAPI metadata.
- `heliophysics.solar_wind.ace.ace_observations`: a native Iceberg table containing
  all 5,401 observations as nine columns, retaining exact UTC nanoseconds, vector
  components, units and missing-value sentinels without resampling.
- `heliophysics.solar_wind.ace.ace_magnetic_field`: the existing Icechunk dataset,
  preserved by this seed.

Retries verify every Iceberg value and reuse its snapshot; conflicting existing
data is never replaced. `--verify-only` checks existing registrations and values
without writing dataset storage or catalog metadata. Receipts are saved to
`.local/polaris/catalog-types-samples.json`. This operator seed creates a genuine
Iceberg snapshot. That external Raw registration does not publish a Huron Raw
revision; use the ingest wizard with a new dataset name to upload its source files
as managed, immutable revisions.

Browse stays inside one catalog of the selected organization. The header has separate organization and catalog selectors. Its filesystem-style Explorer
shows nested namespace folders and repository leaves; expanding a folder loads
that branch with the user’s own Polaris authority. The organization switcher lists Huron memberships; each catalog list intersects those memberships with the current user’s Polaris grants. The default administrator manages all organizations and catalogs.
The compact explorer sits alongside dataset tabs: Overview, Schema, History,
Permissions, Policies and Lineage. Icechunk schema, branches, tags and snapshots
are read from the actual repository. Source lineage shows recorded import
provenance. Permissions show applicable Polaris grants; ordinary users see their
own role assignments. Polaris policy bindings currently support Iceberg tables,
so the Icechunk Policies tab explains that capability limit.

Local PostgreSQL, copied Polaris packages and FILE-backed storage live in ignored
`.local/polaris/`. Huron accounts, their private encryption key and the organization sidecar live in
`.local/huron/`. The organization store defaults to `${HURON_ACCOUNT_STORE}.organizations.json` and can be overridden with `HURON_ORGANIZATION_STORE`; persist it alongside the account store. `stop` preserves data; `refresh` rebuilds the sibling Polaris
checkout and restarts. Requirements: Java 21, native PostgreSQL tools, `uv`, Node
22.9+, installed web dependencies and Docker for Raw PostgreSQL 16. Set `HURON_DATABASE_URL` to use an existing PostgreSQL 15+ Raw database instead. Polaris retains its separate native PostgreSQL instance. Override `POLARIS_PROJECT` and
`POLARIS_JAVA_HOME` for checkout/runtime paths. Restarting does not recreate synthetic repositories or reset grants.

## Endpoint configuration and deployment

Copy `.env.example` to `.env` in `web/`, then configure the server-only Polaris
origin/realm and a private bootstrap credentials file (or environment credentials).
The local launcher respects these settings. Keep a separate `HURON_ACCOUNT_STORE`
for each endpoint/realm; mismatches fail closed. The bootstrap identity needs
Polaris realm administration and must be the realm root/service_admin identity.

```sh
npm install
npm run dev
# adapter-node deployment:
npm run build
npm start
```

`npm start` loads `web/.env`. Set `ORIGIN` to the browser’s public HTTPS origin,
configure `HOST`/`PORT`, and persist the account file, its `.key`, Polaris database
and repository objects. Protect bootstrap credentials and account storage with
private filesystem permissions. `HURON_ADMIN_PASSWORD` seeds only a fresh store;
later changes use Huron account/admin settings. Changing the admin password removes
the initial-password file. Sessions are opaque HttpOnly/SameSite cookies, held
server-side and terminated on restart or password/disable changes. This account
store supports a single deployment host; replicated sessions/identity storage and
OIDC integration remain future deployment work.

The production start script defaults `BODY_SIZE_LIMIT` to 64 MiB for Raw upload
parts, preserving an explicit environment override. Reverse proxies must also
allow 64 MiB request bodies. The Raw bridge applies its own smaller JSON limit and
checks every declared and received part length before publication.

The web supports catalog/namespace administration, Icechunk registration/load/drop,
credential checks, catalog membership and advanced external service principals,
roles, assignments and grants. Huron-managed identities and fixed membership
presets are protected from destructive advanced controls. Upstream secrets remain
server-only; newly created/rotated external principal secrets display once.

FILE catalogs vend no cloud credentials. Direct local SDK access follows OS
permissions and supports one writer. Use a supported object store with Polaris’s
storage isolation/STS configuration for enforced data access and concurrent writes.
Registering a table does not initialize Icechunk; dropping it leaves storage intact.
Polaris has no Icechunk commit, rename, snapshot, branch or tag endpoints.
The server therefore uses the fixed `scripts/inspect_icechunk.py` helper for
metadata inspection after checking the signed-in user's data-read authority.
Configure `HURON_ICECHUNK_PYTHON` and `HURON_ICECHUNK_READ_ROOTS` for the SDK runtime
and approved repository mounts. Roots accept a JSON array or a POSIX colon-separated
list, with paths relative to `web/`. Local defaults cover the existing example and
NASA storage. When packaging the Node application, preserve the repository layout
with `scripts/inspect_icechunk.py`, `web/package.json` and `web/build/`, and provide
the Icechunk/Zarr environment. The inspector does not read array chunks or write data;
unsupported storage or unavailable inspection is shown explicitly.

The Raw ingest page has four steps: Destination, Source, Metadata and Review.
Its explorer lists all accessible catalogs in the selected organization and their
namespace folders. Choose a new dataset or an existing managed Raw dataset, select
files or a directory, supply revision metadata and upload. Files are hashed in a
worker and transferred in bounded parts. Verification and publication use Huron's
existing Raw core: each revision contains exactly the submitted files, and retrying
the same upload returns the same revision. The wizard reports completion only after
Polaris confirms the dataset registration. A registration failure leaves a readable,
committed Raw revision and a retryable pending registration. Keep the page open to
retry; automatic upload recovery after a browser restart is not provided.

The local launcher starts the Raw API on port 8080 with an isolated `huron_raw`
PostgreSQL 16 database on port 5440 (Docker container `huron-raw-local`, persistent volume `huron-raw-local-data`), storage in `.local/huron/raw`, and a persistent private key at
`.local/huron/raw-bridge-key`. It uses credential authentication with development
identity headers disabled. For deployment, configure `HURON_RAW_API_URL`, the same
`HURON_RAW_BRIDGE_SECRET` (at least 32 bytes) in both services, and
`HURON_RAW_POLARIS_AUTHORIZATION=rbac` in the web service. The bridge supports native
Polaris RBAC; other authorization modes fail closed. Persist both Raw storage and
its database. Organization membership, current Polaris data grants and request
target are checked for every operation, including publication and downloads.

Scientific transformation lineage, compute and the generated Huron scientific
client remain planned. Legacy fixture routes redirect to Browse; unsupported
controls are absent from the beta navigation.

## Organizations and dataset types

The first organization migration puts the three existing NASA topic catalogs in
**NASA Science**, preserving their namespaces, datasets and Polaris grants. Other
existing catalogs enter **Huron workspace**. Only existing catalog assignees gain
ordinary organization membership. Organization admins manage people and descriptions;
Polaris catalog privileges remain separately required. Remove catalog roles before
removing organization membership. A global admin assigns or moves catalogs; moving
does not transfer memberships or grants. New upstream catalogs need explicit assignment.

`/settings/organization?organization=nasa-science` manages the organization.
`/settings/catalog?catalog=geoscience` manages the Polaris catalog. The home page
lists the selected organization's accessible catalogs. Dataset lists filter by
name, type and processing layer within the loaded folder page. Layers use
`huron.layer` and bronze/silver/gold namespace placement; conflicts are explicit.

Namespace operations can register existing Raw collection storage (generic format
`raw`), existing Iceberg metadata, or Icechunk repositories. Managed Raw detail
shows committed revisions, checksummed manifests and authenticated downloads from
Huron. External Raw registrations show registration properties only; generic-table
APIs do not supply file manifests or revision history. Non-Raw generic formats are labeled Generic. Iceberg registration uses
`overwrite: false`. No registration operation uploads or converts scientific data.

## Checks

Run from `web/`:

```sh
npm run check
npm test
npm run lint
npm run build
npm run test:e2e
```

Run these checks sequentially. Pause the Vite development server during production
builds and browser tests: simultaneous SvelteKit generators can produce mismatched
server/client bootstrap versions. Restart the local launcher afterward.

Playwright uses an isolated stateful Polaris protocol double and temporary Huron
account storage. Schema/history browser tests use actual temporary Icechunk
repositories seeded through the SDK, rather than fixture inspection responses.
The local launcher installs the required SDK runtime. For tests without the full
stack, create `.local/polaris/icechunk-venv` with `uv venv`, then install
`icechunk==2.3.0 zarr==3.4.1 numpy==2.5.4` using `uv pip install --python` against
that environment, or set `HURON_ICECHUNK_PYTHON` to an existing compatible runtime.
Missing SDK dependencies fail browser-test setup explicitly. Live Polaris/NASA
import checks complement those browser tests.
Root-level routes remain synchronized with `src/lib/reserved-slugs.ts` and the
backend organization-name reservations for the retained scientific core.
