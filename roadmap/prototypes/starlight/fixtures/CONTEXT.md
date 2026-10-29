# Huron

Huron catalogs scientific data with governed identity, metadata, access and discovery.

## Language

**Huron control plane**: The unified public surface through which people discover data, manage access and request authorized scientific data operations.

**Huron account**: A persistent human identity with an immutable identifier used for grants, ownership and attribution, independent of login names and display attributes.

**Service account**: A non-human identity used by an application or pipeline, with explicit resource- and layer-scoped authority.

**External login identity**: An identity established by an OIDC provider and identified by its issuer and subject, associated with a Huron account.

**Access group**: A registered group with a stable, issuer-qualified identity whose members can receive Huron role bindings, including groups backed by the company's directory. Its name is a display label.

**Role binding**: An assignment of a Huron role to an account or access group at a platform, organization, collection or dataset scope.

**Client**: The scientist-facing SDK front door, `Client()`, composing direct `search`, `datasets` and `rawstore` services that call the backend.

**Catalog**: The domain owning Organization → Collection → Dataset identity, configuration, metadata contracts and discovery. It is not a mandatory SDK namespace between Client and its services.

**Collection**: An organization-scoped grouping of datasets and role scope. Replaces Project; it is not an additional hierarchy level. Current source still uses Project pending the coordinated migration.

**Dataset**: An independently identified scientific resource within one collection, with title, description, core descriptive fields, scientific metadata and exact published data references.

**Data pond**: A storage-backed capability with its own data rules and lifecycle, supporting one or more storage layers.
_Avoid_: Using pond as a synonym for collection.

**Raw layer**: The landing zone for original scientific files and associated release metadata.
_Avoid_: Bronze file layer.

**Bronze layer**: The layer for source-faithful array representations of scientific data.

**Published data reference**: The identity of one exact published version at a catalog target and layer, optionally qualified by a pond-defined internal selection.

**Silver representation**: A scientifically standardized representation with canonical names, units and coordinates.

**Submission**: A proposed Raw release, described by its base release, file additions and deletions, and required release metadata. The first submission has no base release.

**Raw release**: An immutable, complete and independently stored version of a dataset's Raw files and release metadata, published by one successful push.
_Avoid_: A revision with a separate release tag.

**Base release**: The exact earlier Raw release whose untouched files a submission retains.

**Push**: Submission of changes that publishes one new Raw release when successful.

**Organization metadata contract**: The common metadata fields and constraints that every dataset in an organization must satisfy.

**Metadata extension**: An immutable, versioned collection addition to an organization's common metadata contract, published by an organization owner. Adds fields only; never redefines or weakens organization fields.

**Schema bundle**: The exact organization schema, collection extension, dialect and controlled referenced documents frozen for a submission, with immutable identities and digests.

**Metadata/schema pair**: Scientific metadata together with its exact validating schema bundle. Omitting later metadata inherits both from the pinned base, not the latest schema.

**Directory administrator**: A trusted member of the external directory's stable configured `huron-admin` group. May administer directory membership through that service; is not thereby a Huron platform owner or scientific data reader.

**Publication receipt**: The durable idempotent result identifying one committed, readable release for a submission identity and request fingerprint.

**Lineage**: Recorded relationships connecting published data to its exact input versions and the transformations that produced it.

**Verified payload**: A release file materialized independently from uploaded or retained source files and verified against its declared size and digest before publication.

**Publication**: The transition that makes a completed release authoritative and readable.

**Removal intent**: A durable record identifying the published content selected for purge or expiry under an earlier authorization.

**Pending removal**: A recorded purge or expiry whose physical removal is not yet complete.

## Relationships

- Authentication establishes a **Huron account**; signup alone creates no **Role bindings**.
- Huron enforces resource access; an integrated institutional identity system owns **Access group** membership and supplies trusted membership facts.
- Huron maps trusted **Access groups** to **Role bindings** at its resource scopes; institutional administrators manage the external group membership.
- Institutional group integration supplies effective **Access group** membership, including nested directory membership; signing in alone does not establish group membership.
- Matching login names or email addresses do not link **Huron accounts** automatically.
- External login identities from different clients correlate to a **Huron account** through an explicit, verified mapping.
- A **Service account** receives explicit organization/collection and layer permissions; credential possession does not confer broader write access.
- A collection groups datasets; a **Data pond** governs a storage-backed data lifecycle rather than a membership scope.
- A **Data pond** may support more than one layer; an array pond may serve Bronze, Silver and Gold.
- Pond-internal items inherit their containing dataset/layer's access scope and published version.
- A dataset's Raw file history consists of immutable **Raw releases**.
- Every dataset is subject to its organization's **Organization metadata contract**.
- Collections may apply additive-only versioned **Metadata extensions** in addition to the organization's common requirements.
- A new dataset requires metadata and a schema bundle. Later omission inherits the exact pinned base pair; null is not omission and an empty object is validated as supplied.
- The external directory owns membership facts and directory-write authorization; Huron owns role bindings and resource enforcement.
- A **Submission** retains untouched files from its exact **Base release** and applies explicit additions and deletions.
- Each **Raw release** contains its own complete **Verified payload**, including independently materialized retained files.
- Deleting a file in a **Submission** does not change an earlier **Raw release**.
- **Lineage** links exact published inputs and outputs; a new input version does not change an earlier derivation's history.
- A **Removal intent** can describe a **Pending removal** without establishing current permission to continue deleting.

## Example dialogue

> **Scientist:** Can a push still in progress change my published release?
> **Developer:** No. Publication uses independently materialized, verified payload files.

## Flagged ambiguities

- Existing-data preservation/migration versus a fresh MVP deployment requires the user's decision; no compatibility requirement is not permission to delete data.
- SDK API-token issuer/broker, stale-base publication policy and nominated NFS hardware/SLO remain unresolved. See [the current target](design/raw-first.md#decisions-and-execution-blockers).
- Register-in-place avoids a second upload; it does not promise to avoid a verified storage copy.
