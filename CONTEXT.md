# Huron

Huron is a datalake for scientific projects. Its Raw lake records which files exist on the Raw volume, who
owns them and what they mean; PostgreSQL holds current state and ONTAP snapshots are the only history.

## Language

### Raw catalog

**Catalog**: A grouping of related Raw data within an Organization, such as `heliophysics`, with access, storage configuration and metadata schema; named by one segment that never changes. _Avoid_: domain; write **Polaris catalog** for the analytical store's.
**Catalog config**: A catalog's selection of one exact metadata schema version and its catalog policy, including snapshot class.
**Config version**: One immutable version of a catalog config; the catalog's current version governs all its collections.
**Segment**: One component of an identifier: a lowercase letter or digit followed by up to 63 of `a-z`, `0-9`, `_`, `-`.
**Vocabulary**: The allowed values of a descriptive metadata field, expressed by its metadata schema.
**Namespace**: An explicitly named grouping within a Catalog or another Namespace, recursively containing namespaces and collections; it may be empty and persists until explicitly deleted. _Avoid_: folder, Polaris namespace.
**Collection**: Managed Raw files and descriptive metadata with a lifecycle, belonging to one Namespace and inheriting Catalog permissions; the only thing that contains files. _Avoid_: dataset, revision.
**Draft**: A collection with a reserved namespace and name and potentially partial metadata, but no directory or files yet.
**Settled**: An Active or Incomplete collection: it has an identity and a directory, may hold files, and never becomes a Draft again.
**Active**: A settled collection whose metadata passes its validator.
**Incomplete**: A settled collection whose metadata stopped passing its validator when its catalog adopted a new schema: a newly required field is missing or a field no longer conforms.
**Resolved**: A successful validation outcome shown with a draft's reserved path preview. _Avoid_: as a state.
**Descriptive fields**: The fields of collection metadata; they describe its contents without determining its location.
**Identifier**: A collection's canonical dotted name, `<catalog>.<namespace path>.<name>`, reserved from draft creation.
**Identifier forms**: Canonical (`heliophysics.psp.fields.enc17.run042`), catalog-rooted (`/psp/fields/enc17/run042`), fully qualified (`heliophysics/psp/fields/enc17/run042`) and mount path; all name one collection.
**Metadata schema**: An immutable, numbered set of metadata rules, selected by a catalog for all its collections; an org base schema or an extension of it. _Avoid_: schema alone.
**Org base schema**: The metadata schema series `org`, which every catalog extension extends.
**Label**: A top-level string member of a collection's metadata, matched by equality in a search.
**Organization**: The top-level ownership and administration scope containing Catalogs; initially there is one, administered by Administrators. _Avoid_: realm.

### Files and changes

**File**: One row per `rel_path` of a collection, holding only its current size, hash, uploader and time.
**rel_path**: A file's path below its collection's directory, checked by the `rel_path` rule, not the segment rule.
**Case-fold key**: The case-folded NFC form of a `rel_path`; two files with one key cannot coexist in a collection.
**Commit**: One request that records a collection's adds and removes after the bytes were written; accepted at once with a commit id, decided later. _Avoid_: publication, revision.
**Commit state**: `queued` or `verifying` while unfinished, then `succeeded` or `failed`, which are final.
**Commit plan**: The outcome of each commit entry (added, overwritten, removed), decided against the current rows.
**File stamp**: A placed file's inode, size, modification and change times, taken after the server hashed it and compared again before its row commits.
**Express slot**: The commit-worker slot kept for small commits, so long pushes cannot starve them.
**Overwrite**: An add to a `rel_path` that already has a row, made only when asked for.
**Publish**: Replacing a collection's descriptive metadata with a full document; nothing happens when nothing changed. _Avoid_: commit.
**Bulk metadata edit**: One merge patch published to an explicit list of collections, all or none.
**Move**: An explicit change of a settled collection's namespace or name within its catalog, preserving its identity and contents. _Avoid_: metadata edit.
**Staging directory**: The catalog-level directory that holds a collection between a move's stage and switch.
**ONTAP snapshot**: A point-in-time copy of the Raw volume: the lake's only history and only undo. _Avoid_: snapshot alone, version.
**Pin**: `(collection id, rel_path, sha256)`, the way downstream lineage names a Raw input.

### Write path

**Volume**: The ONTAP NFS export that holds Raw bytes, mounted at the same prefix on the designated machines and on the Huron pods.
**Mount prefix**: The configured directory, such as `/projects`, where the volume must be mounted before anything is written.
**Push**: The CLI's upload of a working copy, in three phases: copy, commit, cleanup.
**Partial**: A `<name>.<token>.part` file written before placement; it belongs to one staged add and only that add's push resumes it.
**Placement**: Turning a partial into its final name: a link when the name must be new, a rename when overwriting.
**Push lock**: The lock that lets one push at a time run from a working copy.
**Working copy**: A checked-out collection's local state: its base (version and time of the pull), its staged changes and its file listing.
**Stale staged entry**: A staged change that a later pull invalidated; push refuses while one exists.
**Context**: The CLI's current catalog and current collection.
**State directory**: The per-user directory holding the context, tokens and working copies; never the working directory.
**Walkthrough**: The CLI's field-by-field metadata entry for a draft or a metadata file.
**Persistence point**: The moment after each accepted walkthrough answer when it is saved and the walkthrough becomes resumable.
**Prefill**: A walkthrough default taken from the login identity.

### Identity and authority

**Company IdP**: The company's OIDC provider; mocked locally by Keycloak's `company` realm and the fake issuer.
**Group directory**: The company endpoint that lists a user's LDAP groups; mocked locally by `fake-ldap-groups`.
**Token exchange**: Trading a company token for a Huron JWT.
**Huron JWT**: Huron's own short-lived signed token naming a user, their groups and their roles.
**Role**: Administrator at Organization scope, or Catalog Owner, Catalog Contributor and Catalog Reader on an assigned Catalog; Owner includes Contributor and Reader, and Administrator includes all catalog permissions.
**Role mapping**: An identity-provider group assigned Administrator on its Organization or a catalog role on one Catalog; grants combine additively.
**Roles claim**: The `PRINCIPAL_ROLE:<catalog>.<catalog-role>` and `PRINCIPAL_ROLE:administrator` strings in a Huron JWT, for display and other services; lake authority comes from the groups instead.

### Operations

**Reconciler**: The scheduled server job that compares the volume with the catalog, repairs what is safe and reports the rest. _Avoid_: `huron check`, which only reads its findings.
**Finding**: One disagreement the reconciler saw; open until a run repairs it (repaired) or stops seeing it (cleared).
**Sweep**: Clearing every open finding of a catalog that its finished run did not see again.
**Orphan directory**: A physical directory that is not accounted for by the catalog's namespaces or settled collections.
**Polaris projection (deferred)**: A one-way discovery copy of settled collections in Polaris, keyed by collection UUID; never the record.

### Development

**Volume stand-in**: A plain directory with the volume marker, standing in locally for the ONTAP volume.
**Loopback NFS tier**: The Linux-only tests that run against a real NFS mount of a local export.

### Legacy and analytical terms

**Hierarchy**: The legacy organization, project and dataset model behind the legacy `/api/v1` routes.
**Dataset**: A hierarchy and Bronze, Silver and Gold term; never a Raw collection.
**Polaris catalog**: A native Polaris catalog, as the web's browse pages show; outside the Raw lake, which never registers in Polaris. _Avoid_: catalog alone.
**Polaris realm**: Polaris's isolation boundary; a web and analytical-store term the Raw lake does not use.
**Web organization**: The web application's membership root, bound to one Polaris realm.
**Revision**: An Alembic migration revision, and nothing else.

## Relationships

- An **Organization** contains **Catalogs**; Administrator manages its access and appoints Catalog Owners.
- A Catalog Owner manages Reader/Contributor **Role mappings** only on its own **Catalog**; creating a **Collection** confers no additional authority.
- A **Catalog** selects one current **Config version** and **Metadata schema** for every **Collection**.
- A **Catalog** contains **Namespaces**, which may contain other **Namespaces** or leaf **Collections**; only **Collections** contain **Files**.
- A **Collection**'s **Identifier** follows from its explicit **Catalog**, **Namespace** and name; metadata never determines its location.
- A **Commit** changes the **Files** of one **Collection**, and each change appends an audit entry carrying the old and new hash.
- An **Overwrite** or remove leaves the old bytes only in **ONTAP snapshots** taken before it; its audit entry gives the time that selects one.
- A **Role mapping** grants a **Role** to a group; a request's authority is its groups mapped through the current **Role mappings**.
- A catalog extension **Metadata schema** extends one **Org base schema** version; each **Config version** references one extension version.

## Example dialogue

> **Scientist:** I pushed a corrected scan over the old one. Can Huron give me the old bytes back?
> **Developer:** Huron keeps current state only. The collection's log shows the overwrite, the old hash and when it happened. Copy the file out of an ONTAP snapshot taken before then, and `huron add --overwrite` it if it should be current again.

## Flagged ambiguities

- "catalog" means the Raw catalog in Raw text; `heliophysics` may exist both as a Catalog and as a Polaris catalog.
- "schema" has four meanings: metadata schema, the schema map `migrations/schema.sql`, the package `huron.schema`, and the Postgres schema `lake`.
- "snapshot" is always "ONTAP snapshot" in Raw text; Bronze and Icechunk snapshots are different.
- "Project Admin" belongs to the legacy hierarchy vocabulary; Raw uses Catalog Owner.
- The walkthrough's "organization" is an affiliation value in metadata, not the Organization.
- "check": `huron check` reads findings and Incomplete collections; the Reconciler repairs; `check-stack.sh` and `check_schema_map` are tooling.
- "publish" applies to descriptive metadata only; files are committed.
- `metadata.json` beside the data is written by the server from the committed row, never by the CLI.
- "raw" in the web's Polaris pages means a Polaris generic table.
- "Incomplete" covers both "a newly required field is missing" and "a field no longer conforms".
