# Huron

Huron preserves scientific submissions as immutable revisions within datasets.

## Language

**Raw revision**: An immutable, independently stored submission containing exactly its declared files and revision metadata.

**Verified payload**: A revision file materialized independently from upload files and verified against its declared size and digest before publication.

**Publication**: The transition that makes a completed revision authoritative and readable.

**Removal intent**: A durable record identifying the revision content selected for purge or expiry under an earlier authorization.

**Pending removal**: A recorded purge or expiry whose physical removal is not yet complete.

## Relationships

- A dataset has multiple **Raw revisions**.
- Each **Raw revision** contains its own **Verified payload**, without carrying forward files from earlier revisions.
- A **Removal intent** can describe a **Pending removal** without establishing current permission to continue deleting.

## Example dialogue

> **Scientist:** Can an upload still in progress change my published revision?
> **Developer:** No. Publication uses independently materialized, verified payload files.

## Flagged ambiguities

- Register-in-place avoids a second upload; it does not promise to avoid a verified storage copy.
- Verified payload isolation is agreed design; its completion-path implementation is planned for P3.
