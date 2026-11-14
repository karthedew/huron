# Huron

Huron is a datalake for scientific projects. Its Raw lake records which files exist on the Raw volume, who
owns them and what they mean; PostgreSQL holds current state and ONTAP snapshots are the only history.

## Language

### Raw catalog

**Catalog**: A grouping of related Raw data within an Organization, such as `heliophysics`, with access, one assigned metadata schema and an optional share group; named by one segment that never changes. _Avoid_: domain; write **Polaris catalog** for the analytical store's.
**Segment**: One component of an identifier: a lowercase letter or digit followed by up to 62 of `a-z`, `0-9`, `_`, `-`; at most 63 bytes, and not `huron` or `metadata`.
**Vocabulary**: The allowed values of a descriptive metadata field, expressed by its metadata schema.
**Namespace**: An explicitly named grouping within a Catalog or another Namespace, recursively containing namespaces and collections; it may be empty and persists until explicitly deleted. _Avoid_: folder, Polaris namespace.
**Collection**: Managed Raw files and descriptive metadata with a lifecycle, belonging to one Namespace and inheriting Catalog permissions; the only thing that contains files. _Avoid_: dataset, revision.
**Draft**: A collection with a reserved namespace and name and potentially partial metadata, but no directory or files yet.
**Settled**: An Active or Incomplete collection: it has an identity and a directory, may hold files, and never becomes a Draft again.
**Active**: A settled collection whose metadata passes its validator.
**Incomplete**: A settled collection whose metadata stopped passing its validator when its catalog adopted a new schema: a newly required field is missing or a field no longer conforms.
**Descriptive fields**: The fields of collection metadata; they describe its contents without determining its location.
**Identifier**: The canonical dotted name of a namespace or a collection, `<catalog>.<namespace path>.<name>`, reserved from draft creation. The API path (`helio/heliophysics/…`) starts with the organization instead.
**Metadata schema**: An immutable, numbered registry entry of metadata rules; a catalog is assigned one for all its collections, and a collection may add a schema override. _Avoid_: schema alone.
**Base schema**: `huron-base`, the platform schema that the service seeds; every other metadata schema extends it, directly or through other entries.
**Label**: A top-level string member of a collection's metadata, matched by equality in a search.
**Organization**: The top-level ownership and administration scope containing Catalogs. The service configuration can declare the organizations (managed mode); otherwise platform admins create them. _Avoid_: realm.

### Files and changes

**File**: One row per `rel_path` of a collection, holding only its current size, hash, uploader, time, commit, object and the inode of that object.
**rel_path**: A file's path below its collection's directory, checked by the `rel_path` rule, not the segment rule.
**Case-fold key**: The case-folded NFC form of a `rel_path`; two files with one key cannot coexist in a collection.
**Commit**: One request, named by its request ID, that records a collection's adds and removes; each add names a sealed **Upload**. The API accepts it, does its filesystem steps, then records it. _Avoid_: revision.
**Commit state**: The state of a commit request: `accepted` or `blocked` while pending, then `succeeded`, `rejected` or `abandoned`, which are final. A platform administrator retries or abandons a `blocked` request.
**Commit entry**: One step of an accepted commit (add a file, remove a file, make, remove or prune a directory), in a fixed order and marked done one at a time.
**Overwrite**: An add to a `rel_path` that already has a row; the commit replaces the file and its row.
**Publish**: Replacing a collection's descriptive metadata through a merge patch of the metadata draft. _Avoid_: commit.
**ONTAP snapshot**: A point-in-time copy of the Raw volume: the lake's only history and only undo. _Avoid_: snapshot alone, version.

### Write path

**Volume**: The ONTAP NFS export that holds Raw bytes. The API pod and the upload pod mount it read-write at the **Lake path**. A workstation mounts it read-only at the CLI's **Mount prefix**.
**Mount prefix**: The CLI's configured directory, such as `/projects/huron`, where a workstation mounts the lake path read-only; organizations without a root lie below it. On the machine that runs the provision commands, it is the lake path on that machine. The API has none: it uses the **Lake path**.
**Push**: The CLI's upload of a working copy: each staged add goes through the upload proxy to tusd, then one commit records the adds and removes.
**Partial**: `.<name>.<upload id>.huron-part`, the temporary name beside the target to which a publication links a sealed object, then renames over the target.
**Seal**: The API copying a complete tusd upload into a new file in the organization's **Object area**, syncing it and measuring its size and sha256. The pre-finish hook or the API's own check starts it.
**Object area**: `<root>/<org>/.huron-objects/`, mode `0700`, which holds the sealed copy of each upload. A published file is a hard link to its object, so the area is inside the organization directory and its mount.
**Publication**: The filesystem steps of an accepted **Commit**, one per entry in a fixed order: a hard link from the object to a **Partial** and a `rename`, an unlink, or a directory step. It uses hard links and `rename` only, never a symbolic link.
**Upload**: One upload attempt of one file to one `rel_path` of a collection by one user, named by the client's `attempt_id`. Its states are `receiving`, `sealing`, `ready` and `consumed`, or it ends `failed`, `cancelled` or `expired`. Only its current upload ID is authorized, sealed or published.
**Cleanup**: The periodic removal of objects and tusd files that no row needs, selected by database ID only, never by age or by name.
**Writer lock**: The PostgreSQL session advisory lock that the one writing API process holds. A second process serves reads only; a writer that loses the lock stops.
**Upload pod**: The Deployment of one replica that holds the upload proxy and tusd. Its init container deletes tusd's old lock files.
**Upload proxy**: The nginx container that asks the API to authorize every request except OPTIONS before any byte reaches tusd.
**Lake path**: `HURON_LAKE_PATH`, the volume's mount point in the API pod and in the upload pod. It never changes. Every organization root lies at or below it; startup refuses any other root. An organization directory may be a mount of its own; a hard link stays inside one organization directory, and `.tus-uploads` may be on another filesystem.
**LakePath**: A place on the disk as a tuple of names below the storage root, each checked by `check_lake_name` (not empty, not `.` or `..`, no `/` or NUL, at most 255 bytes). The API's disk code names places only this way, never with an absolute path. _Avoid_: path alone when the API form (`helio/sun/…`) is meant.
**Containment**: The rule that keeps every disk operation inside the **Lake path**: every **LakePath** is opened from a descriptor of the root, one name at a time, with no follow of a symbolic link. There is no device check and no mount-point check. _Avoid_: outside-lake check.
**Symlink in lake**: A symbolic link anywhere below the **Lake path**. It is always an error: the API refuses disk work through it with 409 `SYMLINK_IN_LAKE`, a walk reports it and never enters it, and `huron adm check` reports `symbolic_link`. Huron never makes, follows or removes one; the storage administrator removes it.
**Service UID**: `U`, the fixed UID of the API pod and the upload pod. It owns every directory and file of the lake. Its primary group is the service group. _Avoid_: upload user.
**Share group**: The LDAP POSIX group a catalog names as `share_group`. Its members read the catalog's directory over the mount. Every directory below the catalog inherits it through setgid. A published file keeps the service group of its object, and its mode `0644` lets every member read it. _Avoid_: reader group.
**Repair**: `huron adm repair`: the API running one step for each directory that the rows plan (with `--recursive`, the planned namespaces and settled collections below the target too): it makes the directory when it is missing, sets its permission bits, tries the catalog's group and rewrites a settled collection's `metadata.json`. It lists no directory and changes no mode of a data file. It deletes only a directory that it made itself without the mode `2750` or the group of its parent, and it never sets a setgid bit or a directory group that `U` may not set. A step that meets a **Symlink in lake** fails with the reason `symbolic_link`, and the other steps run.
**Push lock**: The lock that lets one push at a time run from a working copy.
**Working copy**: A checked-out collection's local state: the version that its stage is based on, its staged adds and removes, and a commit whose result the CLI does not have.
**Context**: The CLI's current organization, catalog and collection.
**State directory**: The per-user directory holding the tokens and the working copies; never the working directory.
**Walkthrough**: The CLI's field-by-field metadata entry for a draft or a metadata file.

### Identity and authority

**Company IdP**: The company's OIDC provider; mocked locally by Keycloak's `company` realm.
**Group directory**: The company endpoint that lists a user's LDAP groups; mocked locally by `scripts/devgroups.py`.
**Token exchange**: Trading a company token for a Huron JWT.
**Huron JWT**: Huron's own short-lived signed token naming a user and their LDAP groups. The roles come from the current grants at each request.
**Role**: One of five fixed sets of privileges: Platform Admin, Org Admin, Catalog Admin, Contributor and Reader; each holds the privileges of the roles below it.
**Grant**: A role given to an LDAP group at the platform, at an organization or at a catalog; grants combine additively, and a catalog inherits the organization's catalog roles.

### Operations

**Drift check**: `huron adm check`, a CLI report for administrators that compares the share with the rows and changes nothing. _Avoid_: reconciler, which names the startup reconcile of declared organizations.
**Reconcile**: The startup step (`Reconciler`) that makes the database agree with the declared organizations of the service configuration; it never deletes an organization.
**Finding**: One disagreement that the drift check reports, with a code such as `file_missing` or `pending_commit`.
**Polaris projection (deferred)**: A one-way discovery copy of settled collections in Polaris, keyed by collection UUID; never the record.

### Development

**Volume stand-in**: A plain directory with the volume marker, standing in locally for the ONTAP volume.

### Legacy and analytical terms

**Hierarchy**: The organization, project and dataset model of an earlier design; Huron has no such routes.
**Dataset**: A hierarchy and Bronze, Silver and Gold term; never a Raw collection.
**Polaris catalog**: A native Polaris catalog; outside the Raw lake, which never registers in Polaris. _Avoid_: catalog alone.
**Polaris realm**: Polaris's isolation boundary; an analytical-store term the Raw lake does not use.
**Revision**: An Alembic migration revision, and nothing else.

## Relationships

- An **Organization** contains **Catalogs**; an Org Admin creates its catalogs and grants Catalog Admins.
- A Catalog Admin grants Reader and Contributor on its own **Catalog**; creating a **Collection** confers no additional authority.
- A **Catalog** has one assigned **Metadata schema** for every **Collection**.
- A **Catalog** contains **Namespaces**, which may contain other **Namespaces** or leaf **Collections**; only **Collections** contain **Files**.
- A **Collection**'s **Identifier** follows from its explicit **Catalog**, **Namespace** and name; metadata never determines its location.
- A **Commit** changes the **Files** of one **Collection**, and each commit writes one audit entry.
- An **Overwrite** or remove leaves the old bytes only in **ONTAP snapshots** taken before it; its audit entry gives the time that selects one.
- A **Grant** gives a **Role** to a group; a request's authority is its groups mapped through the current **Grants**.
- Every **Metadata schema** but the **Base schema** extends one other entry.
- A catalog change that needs a change on disk makes it in the same API request, after its transaction commits. A failure on disk is repaired with **Repair**.
- An **Upload** becomes a **File** only through a **Commit** that names its upload ID, after its **Seal**; the service's sha256 must equal the commit's.
- Every disk change of the API names its place as a **LakePath** and obeys **Containment**; a **Symlink in lake** stops that change and keeps its rows.
- The CLI writes nothing to the **Volume**; it reads it through the read-only mount at its **Mount prefix**. The one exception is `huron adm provision-orgs` and `huron adm provision-catalogs` in direct mode, which the storage administrator runs.

## Example dialogue

> **Scientist:** I pushed a corrected scan over the old one. Can Huron give me the old bytes back?
> **Developer:** Huron keeps current state only. The collection's log shows the commit and when it happened. Copy the file out of an ONTAP snapshot taken before then, then `huron add` it and push it if it should be current again.

## Flagged ambiguities

- "catalog" means the Raw catalog in Raw text; `heliophysics` may exist both as a Catalog and as a Polaris catalog.
- "schema" has three meanings: metadata schema, the package `huron.schema`, and the PostgreSQL schema `huron`.
- "snapshot" is always "ONTAP snapshot" in Raw text; Bronze and Icechunk snapshots are different.
- "Project Admin" belongs to the legacy hierarchy vocabulary; Raw uses Catalog Admin.
- The walkthrough's "organization" is an affiliation value in metadata, not the Organization.
- "check": `huron adm check` is the drift check; `check-stack.sh` and `check_schema_map.py` are tooling.
- "publish" applies to descriptive metadata only; files are committed.
- `metadata.json` beside the data is written by the API from its own rendering, never by the CLI.
- "Incomplete" covers both "a newly required field is missing" and "a field no longer conforms".
- "Partial" meant `<name>.huron-part`, copied by the CLI's old NFS-copy push, which is removed. It now means the temporary name of a **Publication**.
- "Version 1" names the first schema migration (`0001_huron`) and the old design history only. There are no version 1 directories or files: production starts from scratch, and nothing converts old data.
- "link" in the lake always means a hard link; a symbolic link is a **Symlink in lake**.
- "sweep" names no job of the API or the lake: `sweep_interval` is the period of the loop that continues accepted commits and runs the **Cleanup**. In the web, the session store's `sweep()` drops expired sessions.
