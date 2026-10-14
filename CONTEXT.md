# Huron

Huron preserves scientific submissions as immutable revisions within datasets.

## Language

**Raw revision**: An immutable, independently stored submission containing exactly its declared files and revision metadata.

**Verified payload**: A revision file materialized independently from upload files and verified against its declared size and digest before publication.

**Publication**: The transition that makes a completed revision authoritative and readable.

**Removal intent**: A durable record identifying the revision content selected for purge or expiry under an earlier authorization.

**Pending removal**: A recorded purge or expiry whose physical removal is not yet complete.

**Organization**: A Huron membership and administration root bound immutably to one configured Polaris realm. Each realm belongs to at most one organization in a deployment. Huron login is shared, while Polaris credentials and grants remain realm-scoped.

**Polaris realm**: The native upstream isolation boundary, containing one root and its catalogs, principals, roles and grants. Huron binds provisioned realms; the Polaris admin tool provisions them.

**Catalog**: A native Polaris catalog under an organization’s realm root, typically grouping a program or scientific data domain. Raw, Iceberg and Icechunk identify dataset formats within catalog namespaces. Catalog names need only be unique inside their realm.

## Relationships

- An **Organization** binds one **Polaris realm**, whose root owns its **Catalogs**.
- Organization membership permits selecting the root; native Polaris grants determine catalog and dataset access.

- A dataset has multiple **Raw revisions**.
- Each **Raw revision** contains its own **Verified payload**, without carrying forward files from earlier revisions.
- A **Removal intent** can describe a **Pending removal** without establishing current permission to continue deleting.

## Example dialogue

> **Scientist:** Can an upload still in progress change my published revision?
> **Developer:** No. Publication uses independently materialized, verified payload files.

## Flagged ambiguities

- Register-in-place avoids a second upload; it does not promise to avoid a verified storage copy.
- Verified payload isolation is agreed design; its completion path is implemented and independently verified (M1a, 2026-09-11).
