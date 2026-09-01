# Control Plane Implementation Plan

**Scientific Lakehouse — revision control, metadata, manifest, and storage paths**

| | |
|---|---|
| Status | **RETIRED — reference only. Do not implement, do not extract claims from this document.** |
| Retired by | `design/roadmap.html` § 1 (Greenfield stance): "Prototype endpoints, schemas, and plans are retired outright. No dual-running, no compatibility shims." The authoritative REST specification is `design/api.html`; `design/` decides. |
| Date | 2026-08-16 |
| Scope | Raw control plane only |
| Supersedes | The zip-and-store prototype endpoints (discarded, no data migration) |

---

## 0. How to read this document

Sections 1–3 establish scope and the three-store architecture. Sections 4–9 are the durable
contracts — object layout, metadata, manifest, revision lifecycle — and are the parts that are
expensive to change later. Sections 10–14 are implementation surfaces (PostgreSQL, LanceDB, REST,
authorization). Sections 15–17 cover recovery, code structure, and configuration. Section 18 is the
failure-mode table, 19 the build order and acceptance gates, 20 the remaining open items.

Anything marked **INVARIANT** is a property the system must never violate; each one has a
corresponding acceptance test in section 19.

---

## 1. Scope

### In scope

- Immutable, append-only **revisions** of raw scientific artifacts.
- The **metadata contract**: core envelope, namespaced scientific extensions, mutable descriptive
  documents, and post-commit amendments.
- The **manifest contract**: file inventory, path normalization, hashing, and verification.
- **Storage paths**: bucket topology and the exact S3 key layout on Ceph RGW.
- The **ingest session** state machine and the commit protocol, including crash consistency.
- **Reconciliation and recovery** — rebuilding derived state from object storage.
- **Purge** of committed revisions.

### Out of scope for this document

- Zarr/Icechunk canonical materializations, and the raw→canonical transform pipeline. Hooks are
  reserved (section 20) but nothing here depends on them.
- Ray/KubeRay job dispatch, `AnalysisJobSpec`, and lineage edges.
- The Svelte UI and the Go CLI beyond the manifest-construction contract they must honour.
- The full RBAC model. This plan uses the `Authorizer` port and names the permissions it needs;
  role-binding administration is designed separately.

### Explicit non-goals

- **No lakeFS.** Raw scientific data is not merged or branched; new arrivals and corrections are
  naturally new immutable revisions. The Git-like storage indirection buys nothing here and costs
  a physical-address layer that defeats offline readability.
- **No PostgreSQL full-text search.** LanceDB is the only text and semantic search in the system.
  Two text-matching implementations would drift in tokenization, ranking, and tag semantics, and
  the rarely-exercised one would be broken when needed. There is no search fallback by design.
- **No S3 object versioning and no Object Lock.** Versioning happens at the revision level.
- **No FUSE mount, no streaming bus, no workflow orchestrator, no Iceberg catalog.**

---

## 2. Decisions

Each decision below was made deliberately; the "instead of" column records the live alternative so
a future reader knows the choice was considered, not defaulted into.

| # | Decision | Instead of | Why |
|---|---|---|---|
| D1 | Ceph RGW (S3) is the only storage backend in v1 | NFS/POSIX first | Object store is already provisioned; designing for the weaker guarantee (no rename, no hardlink) avoids a rewrite |
| D2 | Object storage sidecars are **authoritative** for metadata content | PostgreSQL as the catalog of record | Data must remain understandable if the platform is lost |
| D3 | PostgreSQL holds **structural state only** — identity, uniqueness, sequencing, locks, RBAC, audit, outbox — plus `title` | Full metadata mirror | Uniqueness constraints and revision-number allocation cannot be enforced in an async projection |
| D4 | LanceDB is a **rebuildable projection** and owns all text/tag/semantic matching | PG `tsvector`/GIN | One implementation per capability; no drifting duplicate |
| D5 | Every revision is a **full logical copy** | Delta or content-addressed pool | Each revision prefix is self-describing and offline-readable |
| D6 | Manifest-diff dedup: unchanged files are materialized by server-side `CopyObject` | Client re-uploads everything | Saves ingest bandwidth and time; protocol-visible so it cannot be retrofitted |
| D7 | Uploads land **directly in the final revision prefix**; absence of `COMMITTED` means invisible | Staging bucket + promote on commit | Commit stays O(1) at any size; no 2× transient storage |
| D8 | Slugs are **immutable** at project, work-item, and dataset level | Rename rewrites the path | Removes async migration, alias records, `MIGRATING` states, and locator drift entirely |
| D9 | **One open ingest session per dataset** (exclusive lock), short TTL with heartbeat | Concurrent sessions | Predictable, gap-free revision numbering; a crashed client releases quickly |
| D10 | Metadata corrections are **admin/steward-only append-only amendments**; contributors create a new revision | Metadata-only revisions, or free editing | Preserves audit trail without duplicating a terabyte to fix a typo |
| D11 | Purge is **tombstone + destroy payload and manifest**; metadata and an audit event survive | Full hard delete | Reconciliation can distinguish lawful purge from silent data loss |
| D12 | SHA-256 computed **in flight** through the API; verification behind a port | Read-back-and-rehash | One pass, no RGW feature dependency; port allows RGW checksums in v2 |
| D13 | Reconciliation and the prefix sweeper ship in **v1** | Deferred | With D7 the sweeper *is* the garbage collector; it is also the LanceDB rebuild path |
| D14 | Mutable descriptive documents use **numbered generations + a `CURRENT.json` pointer** | Overwrite one key | Bucket versioning is off; overwrite would be unrecoverable |
| D15 | OpenShift `TokenReview` from the start, behind a `Principal`/`Authorizer` port | Stub or no auth | No retrofitting through every handler; the port keeps local dev viable |
| D16 | Per-file cap **10 GiB**; larger single artifacts belong in Zarr/Icechunk | Unbounded | Bounds multipart strategy, pod memory, and route timeouts |
| D17 | SQLAlchemy **Core + explicit SQL**, Alembic migrations, asyncpg driver | Async ORM | The schema is small and structural; keeps persistence types out of the domain |
| D18 | `data_classification` is a **deployment-configured vocabulary** | Hard-coded enum | Getting the vocabulary wrong must not require rewriting stored sidecars |
| D19 | Python floor stays 3.12; UUIDv7 hand-rolled in `domain/ids.py` per RFC 9562 §5.7 | Raising the floor to 3.14 for `uuid.uuid7()` | The floor is a broader compatibility decision affecting every dependency and deployment target, not just this one algorithm, so moving it solely for a standard-library convenience function is not proportionate; a third-party UUIDv7 package would still need to pass the domain admission test (D20: no I/O, no global state, no types in public fields), and the algorithm itself is small enough to own and test exhaustively |
| D20 | `domain/` third-party imports are **forbidden, with an explicit allowlist** admitted by a three-clause test: no I/O, no global state, no types in a domain entity's public fields | Prose banning all external imports outright | `rfc8785` (JCS canonicalization) and `jsonschema` (envelope validation) are pure and stateless and `domain/` genuinely needs them; `pydantic` fails the third clause, which is why it stays banned |

### Sizing envelope this design targets

| Dimension | v1 target | Note |
|---|---|---|
| Files per revision | ≤ 10,000 | Manifest stays a single JSON document |
| Bytes per revision | ≤ 1 TiB | |
| Bytes per file | ≤ 10 GiB (enforced) | Rejected at `BeginIngest` with `FILE_TOO_LARGE` |
| Revision cadence | Unknown — instrumented | See section 19; unchanged-byte ratio is a first-class metric |

---

## 3. Architecture: three stores, three jobs

```
                     ┌──────────────────────────────────────────┐
   Go CLI ─┐         │              FastAPI control plane        │
   Svelte ─┼────────▶│  routes → use cases → ports → adapters   │
   Scripts ┘         └───────┬──────────────┬──────────────┬─────┘
                             │              │              │
                   ┌─────────▼────┐  ┌──────▼──────┐  ┌────▼──────────┐
                   │  Ceph RGW    │  │ PostgreSQL  │  │  Projection   │
                   │  (S3)        │  │             │  │  worker       │
                   │              │  │  structural │  │  (sole writer)│
                   │ AUTHORITATIVE│  │  state only │  └────┬──────────┘
                   │  metadata +  │  │  + outbox   │       │
                   │  payload     │  └─────────────┘       ▼
                   └──────────────┘                  ┌───────────────┐
                                                     │   LanceDB     │
                                                     │  (S3-backed)  │
                                                     │  REBUILDABLE  │
                                                     └───────────────┘
```

### Who owns what

**Ceph RGW — authoritative.** Payload bytes, `metadata.json`, `manifest.json`, `COMMITTED`,
amendments, generation documents, purge tombstones. Everything needed to reconstruct the platform's
view of the world exists here. A scientist with only `s3 ls` and `jq` can navigate it.

**PostgreSQL — structural, minimal, rebuildable.** What object storage cannot provide: atomic
allocation, uniqueness constraints, exclusive locks, read-modify-write on idempotency records, and
a transactional outbox. Its rows are derivable from S3 by the reconciler; it is authoritative only
for *sequencing decisions already made*, which the sidecars then record.

**LanceDB — derived, disposable.** All free-text search, tag filtering, and (later) semantic
similarity. Written by exactly one process. If it is lost, it is rebuilt from S3. If it is down,
search returns `503` and **browse keeps working** — because browse is a structural query over
PostgreSQL, not a degraded search.

### The query split (D4), stated precisely

| Query | Served by | Consistency |
|---|---|---|
| List projects / work items | PostgreSQL | Read-your-writes |
| List datasets in a project + work item, paginated | PostgreSQL | Read-your-writes |
| List revisions of a dataset | PostgreSQL | Read-your-writes |
| Resolve a dataset or revision by ID or slug path | PostgreSQL → S3 | Read-your-writes |
| Fetch effective metadata for a revision | S3 (fold amendments) | Strong |
| Free-text search across titles/descriptions | LanceDB | Eventually consistent |
| Filter or search by tag | LanceDB | Eventually consistent |
| Semantic similarity (later phase) | LanceDB | Eventually consistent |

Search responses carry `projection_lag_seconds` and `projection_watermark` so clients can display
staleness honestly rather than pretending.

**INVARIANT A.** No endpoint serves the same logical question from two stores. There is no
fallback path from LanceDB to PostgreSQL or vice versa.

---

## 4. Domain model

```
Project ──1:N──▶ WorkItem ──1:N──▶ Dataset ──1:N──▶ Revision ──1:N──▶ Amendment
   │                 │                  │                │
 slug (immutable) code (immutable)   slug (immutable)  number (monotonic, gap-free)
 id UUIDv7         per-project        id UUIDv7         id UUIDv7
```

| Resource | Identity | Mutable | Immutable |
|---|---|---|---|
| Project | `id` (UUIDv7) + `slug` | title, description, lifecycle | id, slug |
| WorkItem | `(project_id, code)` | display name, description, active | project, code |
| Dataset | `id` (UUIDv7) + `slug` | title, description, owner, lifecycle | id, slug, project, work item |
| Revision | `id` (UUIDv7) + `number` | *(nothing — amendments are separate objects)* | everything |
| Amendment | `(revision_id, sequence)` | *(nothing)* | everything |

**Work items** are a per-project, admin-governed vocabulary. The same code may mean different
things in different projects; the primary key is `(project_id, code)`. Cross-project aggregation by
work item is therefore not meaningful without an explicit mapping, and none is provided.

**Titles versus slugs.** Every resource carries both. The slug is a permanent, URL-safe, path-safe
identifier fixed at creation. The title is free-text, mutable, and is what users see. A user who
wants to "rename" a dataset changes its title; the storage path never moves. A genuinely wrong slug
means creating a new dataset and marking the old one `SUPERSEDED`, which is rare enough to be
acceptable and leaves an honest record.

---

## 5. Object storage layout

### 5.1 Buckets

| Bucket | Purpose | Lifecycle rules |
|---|---|---|
| `{prefix}-raw` | All committed and in-progress revisions, all sidecars | **Only** `AbortIncompleteMultipartUpload` (7 days). Expiration rules are denied by bucket policy. |
| `{prefix}-staging` | Reserved for v2 direct-upload landing zones and register-in-place | `Expiration` after 7 days, safe because nothing authoritative lives here |
| `{prefix}-index` | LanceDB tables | Managed by the projection worker |

Versioning is **off** on all three (D-versioning-off). Object Lock is not enabled — compliance mode
would make purge (D11) impossible, and governance mode requires versioning.

`{prefix}-staging` is empty in v1. It is provisioned now so that the bucket, its policy, and its
lifecycle rule exist before the code that needs them, and so no future change touches the raw
bucket's lifecycle configuration.

**INVARIANT B.** The raw bucket carries no object-expiration lifecycle rule. Deletion from the raw
bucket happens only through application code paths that write an audit event.

### 5.2 Key layout

```
{prefix}-raw/
  projects/{project_slug}--{project_id}/
    project/
      CURRENT.json                       ← pointer: {"generation": 3}
      generations/000003.json            ← immutable descriptive document
    work-items/{work_item_code}/
      work-item/
        CURRENT.json
        generations/000001.json
      datasets/{dataset_slug}--{dataset_id}/
        dataset/
          CURRENT.json
          generations/000002.json
        revisions/
          INDEX.json                     ← derived, regenerated on commit
          000017--{revision_id}/
            metadata.json                ← IMMUTABLE, authoritative snapshot
            manifest.json                ← IMMUTABLE, authoritative inventory
            COMMITTED                     ← IMMUTABLE, written LAST
            amendments/
              0001.json                  ← append-only, never modified
              0002.json
            payload/
              <normalized relative path>
```

Rules:

- IDs are UUIDv7 rendered lowercase without dashes in keys, and with dashes in JSON.
- `{revision_number}` is zero-padded to six digits so lexicographic listing equals numeric order.
- The `--` separator is legal in slugs' complement: slugs match `^[a-z0-9][a-z0-9-]{1,62}$` and are
  forbidden from containing `--`, which makes `slug--id` unambiguously splittable.
- Payload keys are `payload/` + the NFC-normalized, forward-slash relative path from the manifest.
  No re-encoding, no flattening, no hashing into the key.

**Why the slug appears in the key at all.** With immutable slugs (D8) the human-readable component
is free — it never changes, so it can never drift from the catalog. It exists so that `s3 ls` is
navigable by a person who has lost the platform. The `--{id}` suffix guarantees collision safety
even though slug uniqueness is separately enforced in PostgreSQL.

### 5.3 The `COMMITTED` marker

Written last, after payload and both sidecars are durable. It is not a zero-byte flag — it carries
enough to reconstruct catalog state without parsing the other objects:

```json
{
  "schema": "org.example.science.commit-marker/1.0",
  "revision_id": "01991f3c-7a10-7c4b-9b2e-2f8a5c0d1e77",
  "dataset_id": "01991f3c-6d02-7a19-8f31-0b7c4e2a9d10",
  "revision_number": 17,
  "metadata_schema": "org.example.science.raw-metadata/1.0",
  "manifest_sha256": "dd04...64hex",
  "metadata_sha256": "a6e6...64hex",
  "file_count": 412,
  "total_bytes": 91234567890,
  "committed_by": "ldap:karl",
  "committed_at": "2026-08-16T17:22:10.481Z"
}
```

**INVARIANT C.** A revision prefix containing `COMMITTED` is complete and its payload matches
`manifest.json`. A revision prefix without `COMMITTED` is invisible to every read path and is
eligible for sweeping once its session has expired.

### 5.4 `INDEX.json` — derived navigation aid

Regenerated after each commit, amendment, and purge. Never authoritative; the reconciler rebuilds
it from `COMMITTED` markers. It exists so an offline human can see a dataset's history in one GET.

```json
{
  "schema": "org.example.science.revision-index/1.0",
  "dataset_id": "01991f3c-...",
  "generated_at": "2026-08-16T17:22:11Z",
  "revisions": [
    {"number": 17, "id": "01991f3c-...", "committed_at": "...",
     "file_count": 412, "total_bytes": 91234567890,
     "state": "COMMITTED", "amendment_count": 1}
  ]
}
```

### 5.5 Generation documents (D14)

Mutable descriptive state — project, work item, dataset — is stored as immutable numbered
generations plus a tiny overwritten pointer.

- Write path: `PUT generations/{n+1}.json` (fails if it already exists — see below), then
  `PUT CURRENT.json`.
- Read path: `GET CURRENT.json`, then `GET generations/{n}.json`.
- Recovery: if `CURRENT.json` is missing, torn, or points at a nonexistent generation, the
  reconciler takes the highest existing generation number.

Because bucket versioning is off, `generations/{n}.json` must never be overwritten. The generation
number is allocated in PostgreSQL under a row lock, so two concurrent edits cannot pick the same
`n`. Where the RGW deployment supports conditional writes, the plan additionally sends
`If-None-Match: *` as belt-and-braces; this is optional and the design does not depend on it.

---

## 6. Metadata contract

### 6.1 Core envelope

`metadata.json` is a complete, revision-time snapshot — never a pointer to current state.

```json
{
  "schema": "org.example.science.raw-metadata/1.0",
  "dataset_id": "01991f3c-6d02-7a19-8f31-0b7c4e2a9d10",
  "revision_id": "01991f3c-7a10-7c4b-9b2e-2f8a5c0d1e77",
  "revision_number": 17,
  "project": {"id": "01991f3b-...", "slug": "phoenix"},
  "work_item": {"code": "mcnp-criticality"},
  "title": "Criticality sweep for assembly configuration C",
  "description": "Unmodified MCNP inputs and outputs for the approved sweep.",
  "creators": [{"subject": "ldap:karl", "display_name": "Karl Schmidt"}],
  "committed_by": "ldap:karl",
  "committed_at": "2026-08-16T17:22:10.481Z",
  "data_classification": "internal",
  "tags": ["mcnp", "parameter-sweep"],
  "source": {"kind": "simulation", "system": "MCNP"},
  "time_coverage": {"start": null, "end": null},
  "spatial_coverage": null,
  "manifest_sha256": "dd04...64hex",
  "extensions": {
    "org.example.mcnp/1.0": {
      "code_version": "6.3.1",
      "input_deck": "payload/case-c.i",
      "parameter_axes": ["density", "temperature"]
    }
  }
}
```

Required at v1: `schema`, `dataset_id`, `revision_id`, `revision_number`, `project`, `work_item`,
`title`, `creators`, `committed_by`, `committed_at`, `data_classification`, `source.kind`,
`manifest_sha256`. Everything else is optional.

`committed_by` and `committed_at` are **system-generated**. A client-supplied timestamp is never
trusted as the audit time; if a client sends one it is rejected with `400`.

### 6.2 Schema governance (D-schemas)

- **Core envelope** lives in the repository under `schemas/core/`, versioned with the code, changed
  only by PR with CI validation against a corpus of stored sidecars.
- **Namespaced extensions** live in a runtime registry table in PostgreSQL, published by project
  stewards through an admin API. A published `(namespace, version)` row is **immutable**; a fix
  means publishing a new version. Registry rows are mirrored into S3 at
  `_platform/schemas/{namespace}/{version}.json` so recovery does not depend on PostgreSQL.

Validation rules:

- Core and each extension validate independently.
- An unknown or unregistered extension namespace does **not** block a commit unless the dataset's
  `schema_profile` requires that namespace. Unknown data is better stored than rejected.
- Readers **must preserve unknown keys** on read-modify-write. This is the forward-compatibility
  guarantee and is enforced by a round-trip test.

### 6.3 Classification vocabulary (D18)

Codes are stable strings written into sidecars; labels are presentation only. The active vocabulary
comes from deployment configuration validated at startup:

```yaml
classification:
  default: internal
  values:
    - {code: public,       label: "Public",        order: 0}
    - {code: internal,     label: "Internal",      order: 10}
    - {code: confidential, label: "Confidential",  order: 20}
    - {code: restricted,   label: "Restricted",    order: 30}
```

Startup fails if a code in the config is not a valid identifier, if `default` is absent from
`values`, or if a code previously seen in stored data has been removed. Renaming a *label* is free;
removing a *code* requires a documented migration.

### 6.4 Amendments (D10)

Post-commit metadata correction is a **steward-or-above** operation. A contributor who wants
different metadata commits a new revision.

`amendments/0001.json`:

```json
{
  "schema": "org.example.science.metadata-amendment/1.0",
  "amendment_id": "01991f4a-...",
  "revision_id": "01991f3c-7a10-7c4b-9b2e-2f8a5c0d1e77",
  "sequence": 1,
  "issued_by": "ldap:agarcia",
  "issued_at": "2026-08-18T09:14:02.117Z",
  "reason": "Corrected assembly designation; sweep is configuration C2, not C.",
  "changes": {
    "title": "Criticality sweep for assembly configuration C2",
    "tags": ["mcnp", "parameter-sweep", "assembly-c2"]
  }
}
```

**Fields an amendment may change:** `title`, `description`, `tags`, `time_coverage`,
`spatial_coverage`, `source.system`, and any `extensions` document.
Plus `data_classification`, which additionally requires the `metadata.reclassify` permission and
emits its own audit event because it is authorization-relevant.

**Fields an amendment may never change:** any ID, `revision_number`, `project`, `work_item`,
`creators`, `committed_by`, `committed_at`, `manifest_sha256`, `schema`.

**Effective metadata** = base `metadata.json` folded with amendments in ascending `sequence`, each
`changes` object applied as a whole-key replacement (not a deep merge — deep merge on
`extensions` would make removal impossible to express). The fold is implemented once, in the
domain layer, and used by the API, the projection worker, and the reconciler.

**INVARIANT D.** `metadata.json`, `manifest.json`, `COMMITTED`, and every object under `payload/`
are written exactly once and never modified. `amendments/NNNN.json` are appended and never modified
or deleted. `COMMITTED`'s digests cover only the frozen set, so integrity checking never has to
account for amendments.

---

## 7. Manifest contract

### 7.1 Document

```json
{
  "schema": "org.example.science.file-manifest/1.0",
  "hash_algorithm": "sha256",
  "file_count": 412,
  "total_bytes": 91234567890,
  "files": [
    {"path": "payload/case-c.i", "size": 18742,
     "sha256": "a6e6...64hex", "media_type": "text/plain"}
  ]
}
```

`files` is sorted by `path` (byte order, post-normalization). `total_bytes` and `file_count` are
redundant with `files` and are validated, not trusted.

### 7.2 Canonicalization and digests

- The manifest is canonicalized per **RFC 8785 (JCS)** before hashing. Never hash serializer output.
- `manifest_sha256` = SHA-256 of the JCS form. This is the revision's content identity.
- The manifest stored at `manifest.json` is the JCS form itself, so a recovering reader can rehash
  the stored bytes directly with no re-serialization step.
- `metadata_sha256` in `COMMITTED` is computed the same way over `metadata.json`.

### 7.3 Path normalization and rejection rules

Applied by the client when building the manifest **and** re-applied by the server at
`BeginIngest`; a mismatch between the two is a `400`.

1. Paths are relative, forward-slash separated, and always prefixed `payload/`.
2. Unicode **NFC** normalization is applied before hashing and before comparison. (This is not
   optional — macOS clients emit NFD filenames and the same file would otherwise appear as two
   distinct paths.)
3. Rejected outright: absolute paths, any `.` or `..` segment, NUL or control characters, a
   trailing slash, an empty segment, a path exceeding 1024 bytes UTF-8.
4. Rejected outright: symlinks, hardlinks to outside the tree, devices, FIFOs, sockets. Only
   regular files are ingestible.
5. Two entries whose paths are identical after NFC normalization are a `409 PATH_COLLISION`. Two
   entries differing only by case are also a collision — RGW is case-sensitive but many client
   filesystems are not, and a round trip would silently lose a file.
6. Zero-byte files are legal and carry the SHA-256 of the empty string.
7. Empty directories are not represented. If directory structure must survive an empty directory,
   that is a metadata concern, not a payload concern.
8. Executable bits and mtimes are not preserved and take no part in scientific identity.
9. A revision with zero files is rejected (`422 EMPTY_REVISION`).
10. A manifest whose `manifest_sha256` already exists on another revision of the same dataset is
    rejected (`409 DUPLICATE_CONTENT`) — the correct action is an amendment or no action at all.

### 7.4 Size limits (D16)

| Limit | Value | Error |
|---|---|---|
| Bytes per file | 10 GiB | `413 FILE_TOO_LARGE` |
| Files per revision | 10,000 | `413 TOO_MANY_FILES` |
| Bytes per revision | 1 TiB | `413 REVISION_TOO_LARGE` |

All three are configuration with these defaults. `FILE_TOO_LARGE` responses carry a pointer to the
Zarr/Icechunk path in `detail`, because that is the intended answer, not a workaround.

---

## 8. Revision lifecycle and the ingest session

### 8.1 Session state machine

```
                 BeginIngest
                     │
                     ▼
                ┌─────────┐   server CopyObject of deduped files
                │PREPARING│──────────────┐
                └────┬────┘              │
                     │ prepare complete  │
                     ▼                   │
                ┌─────────┐              │
     ┌─────────▶│UPLOADING│◀─────────────┘   client uploads the remainder
     │  resume  └────┬────┘
     │               │ all files accounted for
     │               ▼
     │          ┌─────────┐
     │          │VERIFYING│   hashes compared; nothing re-read from RGW
     │          └────┬────┘
     │               │ CommitIngest
     │               ▼
     │         ┌──────────┐
     │         │COMMITTING│  sidecars + COMMITTED written to S3
     │         └────┬─────┘
     │              │ PG transaction
     │              ▼
     │         ┌─────────┐
     │         │COMMITTED│ (terminal)
     │         └─────────┘
     │
     └── heartbeat expiry / explicit abort / verification failure
              │
              ▼
        ┌──────────────┐
        │ABORTED│FAILED│ (terminal — prefix becomes sweepable)
        └──────────────┘
```

### 8.2 Locking and revision-number allocation (D9)

`BeginIngest` takes an **exclusive advisory lock on the dataset** for the life of the session. A
second `BeginIngest` gets `409 DATASET_LOCKED` with the holder's subject and the session's
`expires_at`.

Because only one session can exist and only it can commit, the revision number is allocated
**at `BeginIngest`** as `max(committed revision_number) + 1` — which is safe under the lock and
lets the final key prefix be known before any byte is written (required by D7).

If the session aborts, the number is simply not used; the next session recomputes the same value.
**Revision numbers are therefore gap-free.** If two sessions ever did allocate the same number, the
prefixes would still differ by `revision_id`, so no data can collide — the number is for humans,
`revision_id` is the durable identity.

**INVARIANT E.** For any dataset, committed `revision_number` values form the contiguous sequence
`1..N`.

### 8.3 Session TTL and heartbeat

- Default TTL: **2 hours**, refreshed to now+TTL by `POST /ingest-sessions/{id}:heartbeat` and by
  any successful part upload.
- The CLI heartbeats every 60 seconds while a transfer is in flight, so a genuinely long transfer
  never expires; a crashed client or a closed laptop releases the dataset within the TTL.
- A `project-admin` may force-abort a session, which is audited.
- Expiry is enforced lazily on access and eagerly by the sweeper.

### 8.4 Upload plan and dedup (D6, D7)

`BeginIngest` returns an `UploadPlan`. Every file carries an `action`:

```json
{
  "ingest_id": "01991f4b-...",
  "revision_id": "01991f4b-9c00-7d31-a8e2-...",
  "revision_number": 18,
  "revision_prefix": "projects/phoenix--01991f3b.../work-items/mcnp-criticality/datasets/assembly-c-sweep--01991f3c.../revisions/000018--01991f4b9c007d31a8e2.../",
  "expires_at": "2026-08-16T19:22:10Z",
  "mode": "api-multipart",
  "max_concurrency": 8,
  "part_size": 67108864,
  "files": [
    {"file_id": "01991f4b-...", "path": "payload/case-c.out",
     "size": 912345678, "action": "upload",
     "url": "/api/v1/transfer/uploads/01991f4b-...",
     "completed_parts": [1, 2, 3]},
    {"file_id": "01991f4b-...", "path": "payload/case-b.i",
     "size": 18742, "action": "server-copy",
     "source_revision_number": 17}
  ]
}
```

- `action: "server-copy"` files are materialized by a preparation worker doing cross-prefix
  `CopyObject` **inside the raw bucket**, concurrently with the client's uploads. The client never
  sends those bytes.
- Dedup source of truth is the parent revision's `manifest.json` read from S3 — which exercises
  the "S3 is authoritative" property on every ingest rather than only during recovery.
- Server-copied files inherit the parent's already-verified SHA-256 and are not rehashed.
- `mode` is the seam for v2: `"presigned-s3"` changes `url` to a presigned RGW URL and nothing else
  about the client's logic.

**INVARIANT F.** The client never chooses the final key prefix and never writes the `COMMITTED`
marker.

### 8.5 Verification (D12)

The API computes SHA-256 incrementally as bytes stream through on their way into the RGW multipart
upload. Nothing is buffered whole; nothing is read back. At `VERIFYING` the session simply checks
that every manifest entry has either a completed upload with a matching digest or a completed
server-copy.

The `ContentVerifier` port has one method and two planned implementations:

| Implementation | When | Requirement |
|---|---|---|
| `InFlightVerifier` | v1 | none |
| `RgwChecksumVerifier` | v2, with direct-to-storage | RGW must support `x-amz-checksum-sha256` (Reef/Squid+). **Confirm the deployed version before depending on this.** |

RGW `ETag` is MD5 and is **never** used as an integrity proof. Under FIPS, `hashlib.md5` must be
called with `usedforsecurity=False` wherever a library requires MD5 for S3 protocol reasons; this
is an explicit startup smoke test (section 19).

---

## 9. Commit protocol and crash consistency

There is no distributed transaction between RGW and PostgreSQL, and the design does not pretend
otherwise. Ordering is chosen so that every crash window leaves a state the reconciler can name.

```
CommitIngest(ingest_id, manifest_sha256, If-Match, Idempotency-Key)

 1. Return the stored result if this idempotency key was already used.        [PG]
 2. Lock the session row; assert state == VERIFYING; assert ETag; assert
    the declared manifest digest matches the session's.                        [PG]
 3. Assert every file is accounted for and every digest matched.               [PG]
 4. Build metadata.json (JCS) and manifest.json (JCS).
 5. PUT manifest.json                                                          [S3]
 6. PUT metadata.json                                                          [S3]
 7. PUT COMMITTED                        ◀── the durability point              [S3]
 8. ONE short transaction: insert revision row, transition session to
    COMMITTED, insert audit event, insert outbox event, store idempotency
    result.                                                                    [PG]
 9. Best-effort: regenerate INDEX.json. Failure here is not an error;
    the reconciler owns this object.                                           [S3]
```

| Crash after step | Storage state | PostgreSQL state | Resolution |
|---|---|---|---|
| 4 | payload present, no sidecars, no marker | session `VERIFYING` | Session expires → sweeper deletes the prefix |
| 5 or 6 | partial sidecars, no marker | session `VERIFYING` | Same — absence of `COMMITTED` governs |
| 7 | complete, marker present | session `VERIFYING` | **Orphan commit.** Reconciler imports the revision row from the marker |
| 8 | complete | revision row present | Normal. Step 9 retried by reconciler |

**INVARIANT G.** A revision row is never published in PostgreSQL before its `COMMITTED` marker is
durable in RGW. Storage leads; the catalog follows.

### 9.1 Idempotency and concurrency control

- `Idempotency-Key` is required on `POST /datasets`, `POST /ingest-sessions`,
  `:commit`, `:amend`, and `:purge`. Keys are stored per `(principal_subject, operation, key)` with
  a request-body digest and the serialized result. Replay with the same body returns the stored
  result; replay with a different body returns `409 IDEMPOTENCY_KEY_REUSED`. Retention: 7 days.
- `If-Match` with an ETag is required on every state transition of an ingest session and on every
  mutation of a descriptive document. The ETag is `W/"{version}"` from the row's `version` column.
- No database transaction is ever held open across an S3 call, a hash computation, or a network
  wait. Sessions are locked with `SELECT ... FOR UPDATE` for the duration of a single short
  statement group, not for the duration of an upload.

---

## 10. PostgreSQL schema

Design skeleton for Alembic. UUIDv7 generated in the application. All timestamps UTC `timestamptz`.
Note what is **absent**: no `tsvector`, no GIN text index, no `pg_trgm`, no full metadata mirror.

```sql
-- ---------------------------------------------------------------- structure

CREATE TABLE projects (
  id              uuid PRIMARY KEY,
  slug            text NOT NULL CHECK (slug ~ '^[a-z0-9][a-z0-9-]{1,62}$'
                                       AND slug NOT LIKE '%--%'),
  title           text NOT NULL,
  lifecycle_state text NOT NULL CHECK (lifecycle_state IN ('ACTIVE','ARCHIVED')),
  generation      integer NOT NULL DEFAULT 1 CHECK (generation > 0),
  version         bigint  NOT NULL DEFAULT 1,
  created_by      text NOT NULL,
  created_at      timestamptz NOT NULL,
  updated_at      timestamptz NOT NULL,
  CONSTRAINT projects_slug_unique UNIQUE (slug)
);

CREATE TABLE work_items (
  project_id      uuid NOT NULL REFERENCES projects(id),
  code            text NOT NULL CHECK (code ~ '^[a-z0-9][a-z0-9-]{1,62}$'
                                       AND code NOT LIKE '%--%'),
  display_name    text NOT NULL,
  active          boolean NOT NULL DEFAULT true,
  generation      integer NOT NULL DEFAULT 1,
  version         bigint  NOT NULL DEFAULT 1,
  created_at      timestamptz NOT NULL,
  PRIMARY KEY (project_id, code)
);

CREATE TABLE datasets (
  id              uuid PRIMARY KEY,
  project_id      uuid NOT NULL,
  work_item_code  text NOT NULL,
  slug            text NOT NULL CHECK (slug ~ '^[a-z0-9][a-z0-9-]{1,80}$'
                                       AND slug NOT LIKE '%--%'),
  title           text NOT NULL,                    -- display column, see D3
  owner_subject   text NOT NULL,
  schema_profile  text NOT NULL,
  lifecycle_state text NOT NULL
                  CHECK (lifecycle_state IN ('ACTIVE','ARCHIVED','SUPERSEDED')),
  generation      integer NOT NULL DEFAULT 1,
  version         bigint  NOT NULL DEFAULT 1,
  created_by      text NOT NULL,
  created_at      timestamptz NOT NULL,
  updated_at      timestamptz NOT NULL,
  FOREIGN KEY (project_id, work_item_code)
    REFERENCES work_items(project_id, code),
  CONSTRAINT datasets_slug_unique UNIQUE (project_id, work_item_code, slug)
);

CREATE INDEX datasets_browse_idx
  ON datasets (project_id, work_item_code, created_at DESC, id DESC)
  WHERE lifecycle_state <> 'SUPERSEDED';

-- ---------------------------------------------------------------- revisions

CREATE TABLE dataset_revisions (
  id                 uuid PRIMARY KEY,
  dataset_id         uuid NOT NULL REFERENCES datasets(id),
  revision_number    bigint NOT NULL CHECK (revision_number > 0),
  state              text NOT NULL
                     CHECK (state IN ('COMMITTED','PURGED','DEGRADED')),
  metadata_schema    text NOT NULL,
  manifest_sha256    char(64) NOT NULL CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'),
  metadata_sha256    char(64) NOT NULL,
  revision_prefix    text NOT NULL,                 -- full S3 key prefix
  file_count         bigint  NOT NULL CHECK (file_count >= 0),
  total_bytes        numeric(30,0) NOT NULL CHECK (total_bytes >= 0),
  amendment_count    integer NOT NULL DEFAULT 0,
  committed_by       text NOT NULL,
  committed_at       timestamptz NOT NULL,
  CONSTRAINT rev_number_unique   UNIQUE (dataset_id, revision_number),
  CONSTRAINT rev_content_unique  UNIQUE (dataset_id, manifest_sha256)
);

CREATE INDEX revisions_by_dataset_idx
  ON dataset_revisions (dataset_id, revision_number DESC);

CREATE TABLE revision_amendments (
  id             uuid PRIMARY KEY,
  revision_id    uuid NOT NULL REFERENCES dataset_revisions(id),
  sequence       integer NOT NULL CHECK (sequence > 0),
  changed_keys   text[] NOT NULL,
  reclassified   boolean NOT NULL DEFAULT false,
  issued_by      text NOT NULL,
  issued_at      timestamptz NOT NULL,
  CONSTRAINT amendment_sequence_unique UNIQUE (revision_id, sequence)
);

-- ---------------------------------------------------------------- ingest

CREATE TABLE ingest_sessions (
  id                     uuid PRIMARY KEY,
  dataset_id             uuid NOT NULL REFERENCES datasets(id),
  state                  text NOT NULL CHECK (state IN
                           ('PREPARING','UPLOADING','VERIFYING','COMMITTING',
                            'COMMITTED','FAILED','ABORTED')),
  revision_id            uuid NOT NULL,
  revision_number        bigint NOT NULL,
  revision_prefix        text NOT NULL,
  expected_manifest_sha  char(64) NOT NULL,
  manifest               jsonb NOT NULL,   -- transient working copy only
  metadata_draft         jsonb NOT NULL,   -- transient working copy only
  file_count             integer NOT NULL,
  total_bytes            numeric(30,0) NOT NULL,
  created_by             text NOT NULL,
  created_at             timestamptz NOT NULL,
  expires_at             timestamptz NOT NULL,
  version                bigint NOT NULL DEFAULT 1,
  committed_revision_id  uuid NULL REFERENCES dataset_revisions(id),
  failure                jsonb NULL
);

-- exactly one live session per dataset
CREATE UNIQUE INDEX ingest_one_open_per_dataset
  ON ingest_sessions (dataset_id)
  WHERE state IN ('PREPARING','UPLOADING','VERIFYING','COMMITTING');

CREATE INDEX ingest_expiry_idx ON ingest_sessions (expires_at)
  WHERE state IN ('PREPARING','UPLOADING','VERIFYING');

CREATE TABLE ingest_files (
  ingest_id       uuid NOT NULL REFERENCES ingest_sessions(id) ON DELETE CASCADE,
  file_id         uuid PRIMARY KEY,
  path            text NOT NULL,
  size            numeric(30,0) NOT NULL,
  expected_sha256 char(64) NOT NULL,
  action          text NOT NULL CHECK (action IN ('upload','server-copy')),
  source_prefix   text NULL,
  state           text NOT NULL CHECK (state IN ('PENDING','ACTIVE','DONE','FAILED')),
  observed_sha256 char(64) NULL,
  s3_upload_id    text NULL,
  completed_parts jsonb NOT NULL DEFAULT '[]',
  UNIQUE (ingest_id, path)
);

-- ---------------------------------------------------------------- governance

CREATE TABLE extension_schemas (
  namespace   text NOT NULL,
  version     text NOT NULL,
  document    jsonb NOT NULL,
  state       text NOT NULL CHECK (state IN ('PUBLISHED','DEPRECATED')),
  published_by text NOT NULL,
  published_at timestamptz NOT NULL,
  PRIMARY KEY (namespace, version)
);

CREATE TABLE role_bindings (
  id             uuid PRIMARY KEY,
  principal_type text NOT NULL CHECK (principal_type IN ('USER','GROUP','SERVICE')),
  principal_name text NOT NULL,
  role           text NOT NULL,
  scope_type     text NOT NULL
                 CHECK (scope_type IN ('SYSTEM','PROJECT','WORK_ITEM','DATASET')),
  project_id     uuid NULL REFERENCES projects(id),
  work_item_code text NULL,
  dataset_id     uuid NULL REFERENCES datasets(id),
  created_by     text NOT NULL,
  created_at     timestamptz NOT NULL,
  revoked_at     timestamptz NULL,
  CHECK (
    (scope_type='SYSTEM'    AND project_id IS NULL AND dataset_id IS NULL) OR
    (scope_type='PROJECT'   AND project_id IS NOT NULL AND work_item_code IS NULL
                            AND dataset_id IS NULL) OR
    (scope_type='WORK_ITEM' AND project_id IS NOT NULL AND work_item_code IS NOT NULL
                            AND dataset_id IS NULL) OR
    (scope_type='DATASET'   AND dataset_id IS NOT NULL)
  )
);

CREATE INDEX role_bindings_principal_idx
  ON role_bindings (principal_type, principal_name) WHERE revoked_at IS NULL;

-- ---------------------------------------------------------------- purge

CREATE TABLE purge_records (
  id                uuid PRIMARY KEY,
  revision_id       uuid NOT NULL REFERENCES dataset_revisions(id),
  reason_code       text NOT NULL,
  reason_detail     text NOT NULL,
  requested_by      text NOT NULL,
  requested_at      timestamptz NOT NULL,
  approved_by       text NOT NULL,
  approved_at       timestamptz NOT NULL,
  objects_destroyed bigint NOT NULL,
  bytes_destroyed   numeric(30,0) NOT NULL,
  completed_at      timestamptz NULL,
  CONSTRAINT purge_two_person CHECK (approved_by <> requested_by)
);

-- ---------------------------------------------------------------- plumbing

CREATE TABLE idempotency_records (
  principal_subject text NOT NULL,
  operation         text NOT NULL,
  key               text NOT NULL,
  request_sha256    char(64) NOT NULL,
  response_status   integer NOT NULL,
  response_body     jsonb NOT NULL,
  created_at        timestamptz NOT NULL,
  PRIMARY KEY (principal_subject, operation, key)
);

CREATE TABLE audit_events (
  sequence      bigserial,
  event_id      uuid NOT NULL,
  occurred_at   timestamptz NOT NULL,
  actor_subject text NOT NULL,
  action        text NOT NULL,
  resource_type text NOT NULL,
  resource_id   uuid NULL,
  decision      text NULL,
  request_id    text NOT NULL,
  details       jsonb NOT NULL DEFAULT '{}',
  PRIMARY KEY (sequence, occurred_at)
) PARTITION BY RANGE (occurred_at);

CREATE TABLE outbox_events (
  id             bigserial PRIMARY KEY,
  event_id       uuid NOT NULL UNIQUE,
  topic          text NOT NULL,
  aggregate_type text NOT NULL,
  aggregate_id   uuid NOT NULL,
  payload        jsonb NOT NULL,
  available_at   timestamptz NOT NULL DEFAULT now(),
  claimed_by     text NULL,
  claimed_at     timestamptz NULL,
  delivered_at   timestamptz NULL,
  attempts       integer NOT NULL DEFAULT 0
);

CREATE INDEX outbox_pending_idx ON outbox_events (available_at, id)
  WHERE delivered_at IS NULL;
```

Outbox claim (the projection worker's only queue mechanism in v1):

```sql
WITH claimed AS (
  SELECT id FROM outbox_events
  WHERE delivered_at IS NULL AND available_at <= now()
  ORDER BY id
  FOR UPDATE SKIP LOCKED
  LIMIT 100
)
UPDATE outbox_events AS o
   SET claimed_by = :worker_id, claimed_at = now(), attempts = o.attempts + 1
  FROM claimed
 WHERE o.id = claimed.id
RETURNING o.*;
```

---

## 11. LanceDB projection

### 11.1 Topology (D4)

- Tables live in `{prefix}-index` on Ceph.
- **Exactly one writer**: the projection worker, a single-replica Deployment. LanceDB OSS has no
  external commit-lock backend available on Ceph (there is no DynamoDB equivalent), so concurrent
  writers are not safe. Single-writer sidesteps the problem entirely rather than working around it.
- API replicas open the tables **read-only** with a bounded in-process cache.
- The worker consumes `outbox_events` and is idempotent: every write is an upsert keyed by
  `dataset_id` or `revision_id`.

### 11.2 Tables

`datasets` — one row per dataset, carrying the effective metadata of its latest revision:

| column | type | note |
|---|---|---|
| `dataset_id` | string, PK | |
| `project_id`, `project_slug`, `work_item_code`, `dataset_slug` | string | filters |
| `title`, `description` | string | FTS-indexed |
| `tags` | list\<string\> | **owned here**, not in PostgreSQL |
| `classification` | string | filter |
| `creators`, `source_kind`, `source_system` | string | |
| `extension_text` | string | flattened extension values, FTS-indexed |
| `latest_revision_number` | int | |
| `created_at`, `updated_at` | timestamp | |
| `embedding` | vector | **null in v1** |

`revisions` — one row per revision, for revision-level search and provenance lookup.

### 11.3 Search in v1 is full-text, not vector

v1 builds LanceDB's FTS index (Tantivy) plus scalar filters. **No embeddings.** Rationale: exact
and lexical retrieval must be correct and fast before similarity is meaningful, an embedding model
is an extra FIPS-validation surface, and the projection schema already reserves the column so
adding vectors later is a rebuild, not a redesign.

### 11.4 Authorization in search

1. Resolve the principal's visible `project_id` set from PostgreSQL.
2. Push it as a hard filter into the LanceDB query **before** ranking and pagination.
3. Re-authorize the returned IDs against PostgreSQL before serialization.

Step 3 is deliberate belt-and-braces: a security predicate should not rest solely on a search
engine's filter pushdown being correct.

**INVARIANT H.** No search response contains an ID the caller is not authorized to discover.

### 11.5 Rebuild

`lakectl projection rebuild` walks the raw bucket, folds amendments, writes a **new** table
version under a fresh prefix, verifies row counts against PostgreSQL, then atomically flips a
pointer object. Readers are never served a half-built index. Rebuild is expected to be routine —
after a schema change, after an embedding model change, after any incident.

---

## 12. REST surface

`/api/v1`, UUIDv7 IDs, RFC 3339 timestamps, cursor pagination, `application/problem+json` errors,
ETags, `Idempotency-Key`. OpenAPI is the published contract and generates the TypeScript, Go, and
Python clients; a breaking change fails CI.

### Projects, work items, datasets

| Method | Path | Notes |
|---|---|---|
| `POST` | `/projects` | slug immutable; writes generation 1 |
| `GET` | `/projects` | structural list, PG |
| `GET` | `/projects/{id}` | |
| `PATCH` | `/projects/{id}` | title/description only; new generation; `If-Match` |
| `POST` | `/projects/{id}/work-items` | admin-governed vocabulary |
| `GET` | `/projects/{id}/work-items` | |
| `POST` | `/datasets` | `Idempotency-Key`; slug immutable |
| `GET` | `/datasets` | filters: `project_id`, `work_item_code`, `lifecycle_state`; PG; cursor |
| `GET` | `/datasets/{id}` | |
| `PATCH` | `/datasets/{id}` | title/description/owner; new generation; `If-Match` |
| `POST` | `/datasets/{id}:archive` | |

### Revisions

| Method | Path | Notes |
|---|---|---|
| `GET` | `/datasets/{id}/revisions` | PG, newest first |
| `GET` | `/revisions/{id}` | includes effective metadata (base + amendments) |
| `GET` | `/revisions/{id}/metadata?effective=false` | the frozen snapshot |
| `GET` | `/revisions/{id}/manifest` | streamed from S3 |
| `GET` | `/revisions/{id}/files/{path}` | issues a short-lived download capability |
| `POST` | `/revisions/{id}:amend` | steward+; `Idempotency-Key` |
| `GET` | `/revisions/{id}/amendments` | |

### Ingest

| Method | Path | Notes |
|---|---|---|
| `POST` | `/ingest-sessions` | body: dataset_id, metadata draft, manifest → `UploadPlan` |
| `GET` | `/ingest-sessions/{id}` | state, per-file progress, ETag |
| `POST` | `/ingest-sessions/{id}:heartbeat` | extends TTL |
| `PUT` | `/transfer/uploads/{file_id}/parts/{n}` | streaming; hashed in flight |
| `POST` | `/transfer/uploads/{file_id}:complete` | completes the RGW MPU |
| `POST` | `/ingest-sessions/{id}:verify` | `UPLOADING` → `VERIFYING` |
| `POST` | `/ingest-sessions/{id}:commit` | `If-Match`, `Idempotency-Key` → `201` + Revision |
| `POST` | `/ingest-sessions/{id}:abort` | |

### Search, admin, operations

| Method | Path | Notes |
|---|---|---|
| `GET` | `/search` | LanceDB; `q`, `tags`, filters; returns `projection_lag_seconds` |
| `POST` | `/admin/extension-schemas` | publish an immutable `(namespace, version)` |
| `POST` | `/admin/revisions/{id}:request-purge` | records intent |
| `POST` | `/admin/purges/{id}:approve` | different subject required; executes |
| `GET` | `/admin/reconciliation/report` | latest scanner findings |
| `POST` | `/admin/reconciliation:plan` / `:apply` | dry-run then apply |
| `GET` | `/healthz`, `/readyz`, `/metrics` | |

### Error contract

```json
{
  "type": "https://lake.example/problems/manifest-mismatch",
  "title": "Manifest verification failed",
  "status": 409,
  "code": "MANIFEST_MISMATCH",
  "detail": "2 files differ from the declared manifest",
  "instance": "/api/v1/ingest-sessions/01991f4b-...:commit",
  "request_id": "01K2P9M3Y9R3P8T8J0YV7K5C0A",
  "errors": [{"path": "payload/run-17.out", "reason": "SHA256_MISMATCH"}]
}
```

Stable codes used by clients for control flow: `DATASET_LOCKED`, `SESSION_EXPIRED`,
`MANIFEST_MISMATCH`, `DUPLICATE_CONTENT`, `PATH_COLLISION`, `EMPTY_REVISION`, `FILE_TOO_LARGE`,
`TOO_MANY_FILES`, `REVISION_TOO_LARGE`, `IDEMPOTENCY_KEY_REUSED`, `PRECONDITION_FAILED`,
`SLUG_IMMUTABLE`, `AMENDMENT_FIELD_FORBIDDEN`, `PROJECTION_UNAVAILABLE`.

---

## 13. Authorization touchpoints

Full RBAC is designed separately; this plan depends only on the `Authorizer` port and these
permissions.

| Permission | Minimum role | Guards |
|---|---|---|
| `dataset.read`, `revision.read` | reader | listing, metadata, manifest |
| `revision.download` | reader | checked again when issuing each download capability |
| `dataset.create`, `revision.create` | contributor | `BeginIngest`, `CommitIngest` |
| `dataset.metadata.update` | steward | `PATCH /datasets`, `:amend` |
| `metadata.reclassify` | steward | amendments touching `data_classification` |
| `work_item.manage` | project-admin | work-item vocabulary |
| `ingest.force_abort` | project-admin | killing another user's session |
| `revision.purge.request` | project-admin | |
| `revision.purge.approve` | platform-admin, ≠ requester | |
| `schema.publish` | platform-admin | extension registry |

Notes that are easy to get wrong:

- **Listing is authorization.** `visible_project_ids` is applied in SQL before pagination, ranking,
  or facet counts — never as a post-filter, which would leak counts and break page sizes.
- **Discovery vs. download are separate checks.** A visible metadata record does not imply payload
  access; the check is repeated when issuing each transfer capability.
- Where existence itself is sensitive, return `404`, not `403`.
- `TokenReview` results are cached briefly (≤60 s); **role bindings are never cached** beyond the
  request.
- Identity is resolved by the `PrincipalResolver` port. Production uses OpenShift `TokenReview`;
  local development uses a trusted-header resolver that **refuses to start** unless
  `ENV=development`.

---

## 14. Purge (D11)

Two-person, audited, and deliberately inconvenient.

1. `POST /admin/revisions/{id}:request-purge` with a reason code and detail. Creates a
   `purge_records` row. Nothing is destroyed.
2. `POST /admin/purges/{id}:approve` by a **different** platform-admin (enforced by a CHECK
   constraint, not by convention).
3. Execution, in order:
   - Mark the revision `PURGED` in PostgreSQL and emit an audit event and outbox event.
   - Write `PURGED` marker object into the revision prefix (see below).
   - Delete every object under `payload/`.
   - Delete `manifest.json`.
   - Update `purge_records` with object and byte counts and `completed_at`.
   - Regenerate `INDEX.json`; emit a projection update so LanceDB drops the revision's file-level
     content.

**What survives:** `metadata.json`, all `amendments/`, `COMMITTED`, the new `PURGED` marker, the
PostgreSQL revision row in state `PURGED`, the `purge_records` row, and the audit events.

**What is destroyed:** all payload bytes, and `manifest.json` — which means filenames and per-file
digests are destroyed, since those are frequently the sensitive material.

```json
{
  "schema": "org.example.science.purge-marker/1.0",
  "revision_id": "01991f3c-...",
  "purge_id": "01991fa0-...",
  "reason_code": "EXPORT_CONTROLLED",
  "requested_by": "ldap:agarcia",
  "approved_by": "ldap:tnguyen",
  "completed_at": "2026-09-02T14:03:55Z",
  "objects_destroyed": 412,
  "bytes_destroyed": 91234567890
}
```

**INVARIANT I.** A revision prefix with `COMMITTED` and no payload is a valid state **only** if a
`PURGED` marker is present. Any other such prefix is data loss and the reconciler raises it as
`DEGRADED`, not as a normal condition. This is the entire reason purge is not a hard delete.

Purge is idempotent and resumable: re-running the execution step re-deletes whatever remains.

---

## 15. Reconciliation and recovery (D13)

Three jobs, one binary, all with `--dry-run` producing a plan before `--apply`.

### 15.1 Sweeper (continuous, every 15 min)

With uploads landing directly in the final prefix (D7), this **is** the garbage collector.

- Find prefixes with no `COMMITTED` whose session is `ABORTED`/`FAILED`/expired, or which have no
  session row at all and are older than 24 h.
- Delete the prefix. Emit an audit event with the object and byte count.
- Abort stale RGW multipart uploads older than 7 days (belt-and-braces with the lifecycle rule).

**Safety rail:** the sweeper refuses to delete any prefix containing `COMMITTED`, and refuses to
run at all if it would delete more than a configurable fraction (default 5%) of prefixes in one
pass — an escape hatch against a bug in expiry logic.

### 15.2 Catalog reconciler (nightly + on demand)

Enumerates `COMMITTED` markers and compares against PostgreSQL:

| Finding | Meaning | Action |
|---|---|---|
| Marker present, no PG row | Crash between S3 step 7 and PG step 8 | **Import** the revision row from the marker |
| PG row present, marker absent | Data loss or unauthorized deletion | Mark `DEGRADED`, alert, **never** delete the row |
| Digest mismatch | Corruption or tampering | Mark `DEGRADED`, alert |
| Marker + no payload + no `PURGED` | Data loss | Mark `DEGRADED`, alert |
| Marker + no payload + `PURGED` | Lawful purge | Ensure PG state is `PURGED` |
| `INDEX.json` stale or missing | Derived object drift | Regenerate |
| `CURRENT.json` torn | Crash between generation write and pointer write | Repoint at the highest generation |

The reconciler **never silently overwrites catalog history.** Imports are additive; disagreements
become `DEGRADED` plus an alert plus a report entry.

### 15.3 Full rebuild

`lakectl rebuild --from-storage` reconstructs PostgreSQL structural rows and the LanceDB projection
from object storage alone, assuming only an empty database with migrations applied. This is the
proof that D2 is real, and it is a gated acceptance test (section 19), not a hope.

Order: projects → work items → datasets (from `CURRENT.json` generations) → revisions (from
`COMMITTED` markers) → amendments → projection rebuild.

RBAC bindings, audit history, and idempotency records are **not** recoverable from object storage
and depend on PostgreSQL backups. This is stated plainly so nobody assumes otherwise: the raw data
is recoverable from S3; the governance record is not.

### 15.4 Backup

| Store | Method | RPO target | Restore test |
|---|---|---|---|
| PostgreSQL | Continuous WAL archiving + nightly base backup | 5 min | Monthly, to an isolated namespace |
| Raw bucket | Ceph replication/EC; optional cross-site sync | n/a | Quarterly object-level restore drill |
| LanceDB | None — rebuilt | n/a | Rebuild timed quarterly |

---

## 16. Code structure

```
lakehouse/
  domain/                    # entities, invariants, errors — no I/O, no framework, allowlisted libs only
    ids.py                   # UUIDv7
    manifest.py              # normalization, JCS canonicalization, digests
    metadata.py              # envelope, amendment fold, allowed-field rules
    revision.py
    ingest_session.py        # the state machine
    errors.py
  application/               # use cases, one class each
    create_dataset.py
    begin_ingest.py          # builds the UploadPlan incl. dedup decisions
    verify_ingest.py
    commit_ingest.py
    amend_revision.py
    purge_revision.py
    search_datasets.py
    reconcile.py
  ports/                     # Protocol definitions only
    catalog.py               # CatalogRepository
    raw_store.py             # RawObjectStore
    verifier.py              # ContentVerifier
    projection.py            # SearchProjection
    principal.py             # PrincipalResolver
    authorizer.py            # Authorizer
    clock.py
  adapters/
    postgres/                # SQLAlchemy Core, explicit SQL, row→dataclass mapping
    rgw/                     # boto3/aiobotocore RawObjectStore
    lancedb/                 # SearchProjection (read) — writes live in the worker
    openshift/               # TokenReview PrincipalResolver
  api/                       # FastAPI routers + Pydantic v2 DTOs. Thin.
  worker/
    projection_worker.py     # sole LanceDB writer, outbox consumer
    sweeper.py
    reconciler.py
    prepare_worker.py        # server-copy dedup materialization
  cli/                       # lakectl: rebuild, reconcile, projection, purge-exec
```

**The structural test:** `lakehouse/domain` and `lakehouse/application` must import neither
FastAPI, SQLAlchemy, boto3, nor lancedb. This is enforced by an import-linter rule in CI, not by
discipline.

### Illustrative use case

```python
class CommitIngest:
    def __init__(self, catalog, raw_store, authorizer, clock):
        self._catalog, self._raw = catalog, raw_store
        self._authz, self._clock = authorizer, clock

    async def execute(self, *, principal, ingest_id, expected_manifest_sha256,
                      expected_etag, idempotency_key) -> Revision:
        if (prior := await self._catalog.idempotent_result(
                principal.subject, "commit_ingest", idempotency_key)):
            return prior

        session = await self._catalog.lock_session(ingest_id)
        await self._authz.require(principal, "revision.create", session.dataset_ref)
        session.require_state(SessionState.VERIFYING)
        session.require_etag(expected_etag)
        session.require_manifest(expected_manifest_sha256)
        session.require_all_files_accounted()          # raises with per-file detail

        revision = session.build_revision(committed_at=self._clock.now(),
                                          committed_by=principal.subject)

        # Storage leads. Idempotent; COMMITTED written last (INVARIANT G).
        await self._raw.put_object(revision.manifest_key, revision.manifest_jcs)
        await self._raw.put_object(revision.metadata_key, revision.metadata_jcs)
        await self._raw.put_object(revision.committed_key, revision.commit_marker_jcs)

        # One short transaction: revision, session, audit, outbox, idempotency.
        await self._catalog.commit_revision(revision, principal, idempotency_key)
        return revision
```

---

## 17. Configuration and deployment

### Deployment units

| Unit | Replicas | Notes |
|---|---|---|
| API (FastAPI/uvicorn) | ≥2 | Stateless; route timeouts sized for 10 GiB part streams |
| Prepare worker | 1–N | Server-copy dedup; idempotent, safe to scale |
| Projection worker | **exactly 1** | Sole LanceDB writer; enforced by `replicas: 1` + `Recreate` |
| Sweeper / reconciler | CronJob | `--dry-run` in report mode, `--apply` on schedule |
| PostgreSQL | HA operator | CloudNativePG or equivalent |

### Key configuration

```
LAKE_S3_ENDPOINT / ACCESS_KEY / SECRET_KEY / REGION
LAKE_S3_BUCKET_RAW / _STAGING / _INDEX
LAKE_S3_MULTIPART_PART_SIZE=67108864
LAKE_LIMIT_MAX_FILE_BYTES=10737418240
LAKE_LIMIT_MAX_FILES_PER_REVISION=10000
LAKE_LIMIT_MAX_REVISION_BYTES=1099511627776
LAKE_INGEST_SESSION_TTL_SECONDS=7200
LAKE_IDEMPOTENCY_RETENTION_DAYS=7
LAKE_SWEEPER_MAX_DELETE_FRACTION=0.05
LAKE_CLASSIFICATION_CONFIG=/etc/lake/classification.yaml
LAKE_AUTH_MODE=tokenreview|dev-header      # dev-header refuses ENV!=development
LAKE_PROJECTION_MAX_LAG_SECONDS=300        # above this, /search warns
```

### OpenShift and FIPS

- Arbitrary non-root UID, read-only root filesystem, dropped capabilities, explicit
  requests/limits. No fixed username assumptions in images.
- Separate service accounts for API, prepare worker, projection worker, and cron jobs. The
  projection worker is the only identity with write access to `{prefix}-index`. The sweeper is the
  only identity permitted `DeleteObject` on `{prefix}-raw`, and only outside committed prefixes;
  purge runs under its own short-lived elevated identity.
- Routes expose only the API. PostgreSQL and RGW are reachable only via NetworkPolicy.
- **FIPS acceptance items** (section 19): every image starts and imports cleanly under FIPS;
  `boto3` multipart paths that compute MD5 use `usedforsecurity=False`; TLS to RGW and to
  PostgreSQL negotiates approved suites; the manifest algorithm string is recorded in every
  manifest and unknown algorithms are rejected by policy.

---

## 18. Failure modes

| Failure | Detection | Behaviour | Recovery |
|---|---|---|---|
| API pod dies mid-upload | Session heartbeat lapses | Session expires; parts retained | Client resumes; `completed_parts` replayed |
| Client vanishes | TTL expiry | Dataset lock released ≤2 h | Sweeper deletes prefix |
| Crash between `COMMITTED` and PG commit | Reconciler | Revision invisible until reconciled | Orphan import |
| PG down | Health check | API returns `503`; no ingest, no browse | PG HA failover |
| RGW down | Health check | `503` on ingest and download | Ceph recovery |
| LanceDB down or stale | Lag metric | `/search` returns `503 PROJECTION_UNAVAILABLE`; **browse unaffected** | Restart worker; rebuild if corrupt |
| Projection worker duplicated (bad rollout) | Commit conflicts in worker log | Writes fail rather than corrupt | `Recreate` strategy + replica alert |
| Two concurrent `BeginIngest` | Partial unique index | Second gets `409 DATASET_LOCKED` | Wait or force-abort |
| Duplicate `Idempotency-Key`, different body | Request digest mismatch | `409 IDEMPOTENCY_KEY_REUSED` | Client uses a fresh key |
| Manifest digest mismatch at verify | In-flight hash | `409 MANIFEST_MISMATCH` with per-file detail | Client re-uploads listed files |
| Payload missing under a committed revision | Reconciler | Revision `DEGRADED`, alert | Restore from Ceph; never auto-delete the row |
| Torn `CURRENT.json` | Reconciler | Highest generation wins | Pointer repaired |
| Sweeper bug proposing mass deletion | Fraction guard | Refuses to run, alerts | Investigate before override |

---

## 19. Build order and acceptance gates

### Phase 1 — Foundations (no ingest yet)

Domain model, manifest normalization and JCS canonicalization, core schema validation, PostgreSQL
migrations, `RawObjectStore` against RGW, `PrincipalResolver` via `TokenReview`, projects / work
items / datasets with generation documents, structural browse endpoints, OpenAPI published.

*Gate:* create a project, work item, and dataset; confirm generation documents and `CURRENT.json`
in the bucket; confirm slug immutability is rejected at the API; import-linter passes.

### Phase 2 — Ingest and commit

Session state machine, dataset lock, revision-number allocation, `UploadPlan`, streaming multipart
transfer with in-flight hashing, verify, commit protocol, sidecars, `COMMITTED`, `INDEX.json`,
idempotency, ETags, download capabilities.

*Gate:* the round-trip and crash tests below.

### Phase 3 — Sweeper and reconciler

Sweeper with fraction guard, catalog reconciler with dry-run plans, `rebuild --from-storage`.

*Gate:* the rebuild test below.

### Phase 4 — Projection and search

Outbox consumer, LanceDB tables, FTS index, `/search` with authorization filtering and lag
reporting, `projection rebuild` with atomic pointer flip.

*Gate:* the search-authorization test below.

### Phase 5 — Amendments, purge, extension registry

Steward amendments with field allow-list, reclassification audit, two-person purge, extension
schema publishing.

*Gate:* the purge and amendment tests below.

### Acceptance gates (all must pass before v1 is called done)

1. **Round trip.** Ingest a tree containing Unicode NFC and NFD filenames, a zero-byte file, a
   nested 8-level path, and a 9 GiB file. Download the revision. Every byte, relative path,
   metadata field, and manifest digest is identical.
2. **Rebuild.** Drop the database, apply migrations, run `rebuild --from-storage`. The visible
   inventory of projects, work items, datasets, revisions, and amendments is identical. Test with
   at least one purged revision present.
3. **Crash consistency.** Fault-inject a kill after `COMMITTED` and before the PG transaction. The
   revision is invisible; the reconciler imports it; no duplicate is created on retry.
4. **Resume.** Interrupt a multi-file upload at 60%. Resume re-sends only the incomplete file and
   cannot commit an incomplete manifest.
5. **Concurrency.** Two clients race `BeginIngest`; exactly one wins with a clear `409`. Revision
   numbers across 100 sequential ingests are exactly `1..100` with no gaps.
6. **Idempotency.** Replaying `:commit` with the same key returns the same revision and creates no
   second revision. Replaying with a different body returns `409`.
7. **Dedup.** A revision that changes 1 file of 500 uploads exactly 1 file; the other 499 are
   server-copied and the new revision prefix is independently complete and downloadable.
8. **Rejection matrix.** Every rule in §7.3 has a test that produces the documented error code.
9. **Search authorization.** A user with access to project A searching a term that matches only
   project B gets zero results, correct pagination, and no leaked facet counts.
10. **Projection independence.** Stop the projection worker and delete the LanceDB tables. Browse,
    list, fetch, ingest, and commit all still work. `/search` returns `503`. Rebuild restores it.
11. **Purge.** Two-person purge destroys payload and manifest, retains metadata, writes markers and
    audit records, is idempotent on re-run, and the reconciler reports it as lawful — not
    `DEGRADED`. Single-person purge is rejected by the database constraint.
12. **Amendment rules.** Every forbidden field is rejected; the fold produces correct effective
    metadata across 3 chained amendments; reclassification emits its own audit event and requires
    the elevated permission.
13. **Unknown-extension round trip.** A sidecar with an unregistered extension namespace survives
    read-modify-write with all keys intact.
14. **FIPS.** Every image starts, imports, and completes a smoke ingest in the FIPS-enabled base
    image.
15. **Contract.** Svelte and Go clients build against the published OpenAPI in CI; a breaking
    change fails the build.

### Instrumentation required at v1

Because revision cadence is unknown (D-cadence), these are first-class metrics from day one, and
the delta-versus-full-copy decision is revisited with data at 90 days:

- Revisions per dataset, distribution.
- Unchanged-byte ratio per revision (bytes server-copied ÷ total bytes).
- Bytes stored versus bytes logically distinct.
- Ingest duration by size bucket; session abandonment rate.
- Projection lag p50/p99; search versus browse call ratio.

---

## 20. Open items

Not blocking implementation, but each needs an owner.

1. **RGW version and conditional-write support.** Confirm whether the deployed Ceph supports
   `x-amz-checksum-sha256` and `If-None-Match` on PUT. Nothing in v1 depends on either; both would
   simplify v2 direct-to-storage and generation writes.
2. **Bucket index sharding.** Estimate the object-count trajectory of `{prefix}-raw` and set RGW
   dynamic resharding policy before, not after, the first large ingest.
3. **`data_classification` values.** The deployment-configured default list is a placeholder. If
   this environment uses controlled-unclassified categories, decide whether classification alone
   gates *discovery* or only *download* — that changes the authorization model, not just a list.
4. **Retention policy.** How long do `ARCHIVED` datasets and `PURGED` revision metadata persist?
   Purge machinery exists; the policy driving it does not.
5. **Embedding model** for the later semantic phase, plus its FIPS validation.
6. **Materialization hooks.** `materializations`, `jobs`, and `lineage_edges` tables are
   deliberately absent here. When Zarr/Icechunk lands, a revision gains a raw *materialization*
   record; nothing in this plan changes, but the linkage should be designed before Phase 5 ships so
   the revision resource does not need a breaking change.
7. **Quota.** No per-project storage quota exists. Decide whether it is enforced at
   `BeginIngest` (application) or by per-project RGW buckets (which would revisit D-buckets).

---

## Appendix — invariant checklist

| | Invariant | Test |
|---|---|---|
| A | No capability is served from two stores; no search fallback | 10 |
| B | Raw bucket has no object-expiration lifecycle rule | Infra policy test |
| C | `COMMITTED` present ⇒ prefix complete and matching the manifest | 1, 3 |
| D | Frozen objects written once; amendments appended only | 12 |
| E | Committed revision numbers are contiguous `1..N` | 5 |
| F | Client never chooses the final prefix nor writes `COMMITTED` | Contract test |
| G | Revision row never published before `COMMITTED` is durable | 3 |
| H | Search never returns an unauthorized ID | 9 |
| I | Committed prefix without payload is valid only with `PURGED` | 11 |
