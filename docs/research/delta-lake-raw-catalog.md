# Delta Lake for the Huron Raw catalog

Verified on 24 October 2026. Keep PostgreSQL as the Raw catalog of record under the
current design. Delta Lake could store the catalog's rows, but replacing their
database with Delta would leave the scientific file workflows in Huron and require
new choices for transaction coordination and integrity enforcement. Delta becomes
more attractive if the requirement changes to analytical tables consumed directly
by multiple data engines.

## The Huron requirement

Raw collections contain scientific files on the ONTAP NFS mount. The accepted
design records their current paths, hashes, sizes, owners and metadata in PostgreSQL;
ONTAP snapshots retain old bytes. One commit must update file rows, the collection
version, audit entries and commit status together after the worker verifies the
mounted bytes. Metadata uses composed, versioned JSON Schema documents.
[Catalog decision](../adr/0004-raw-catalog-of-record-is-huron-postgresql.md),
[recovery decision](../adr/0005-no-raw-versioning.md),
[commit decision](../adr/0006-asynchronous-raw-commit.md),
[metadata decision](../adr/0003-metadata-schemas-compose-by-extends.md)

These are accepted requirements for the new lake, not completed implementation:
at this review, `src/huron/core/lake` does not exist and the migration chain ends at
`0013_retire_releases`. The legacy implementation remains in place.

## What Delta would store

A Delta table stores rows in Parquet and records table changes in a transaction
log. Its metadata describes that table: its schema, data files and transactions.
Huron's file descriptions could be ordinary rows such as
`collection_id, rel_path, sha256, size, metadata`, but their NFS paths would be
values in those rows. The external scientific files would remain outside Delta's
transaction and retention machinery. This follows from Delta's table format and
the separation Huron requires between catalog rows and mounted bytes.
[Delta format](https://docs.delta.io/delta-faq/),
[transaction protocol](https://github.com/delta-io/delta/blob/master/PROTOCOL.md)

Consequently, time travel over such a catalog would recover an earlier row and
hash; it would not recover an overwritten external file. Huron would still need
hash verification, safe placement, mount permissions, reconciliation, snapshot
recovery, authorization and metadata validation. Databricks makes a similar
product distinction: Unity Catalog Volumes govern arbitrary files, while tables
govern tabular data.
[Unity Catalog Volumes](https://docs.databricks.com/aws/en/volumes/)

## Transactions and integrity

Ordinary filesystem-backed Delta tables coordinate commits independently. This
does not directly provide Huron's atomic change across `files`, `collections`,
`audit_log` and commit state. Putting everything into one Delta table could change
the transaction boundary, but would also redesign the data model and its queries.
[Delta transactions](https://delta-io.github.io/delta-rs/latest/how-delta-lake-works/delta-lake-acid-transactions/)

The statement that Delta *never* supports transactions across tables is now too
broad. Delta Lake 4.0.1 and later define catalog-managed tables, where a compatible
catalog coordinates commits; direct filesystem access is unsupported. Databricks
currently provides transactions across tables for Unity Catalog managed tables
with Catalog commits and supported compute. Adopting that coordinating stack is a
different deployment choice from using a Delta library over the existing mount.
[Catalog-managed tables](https://docs.delta.io/delta-catalog-managed-tables/),
[Databricks transactions](https://docs.databricks.com/aws/en/transactions/)

Delta enforces column schemas and supports `NOT NULL` and row-level `CHECK`
constraints. These do not replace Huron's composed JSON Schema, identity rules or
collection lifecycle. Databricks primary, foreign and unique key declarations are
informational rather than enforced. Huron would need another mechanism for
guarantees such as one current row per collection/path and consistent references.
[Delta constraints](https://docs.delta.io/delta-constraints/),
[Databricks constraints](https://docs.databricks.com/aws/en/tables/constraints)

## Operational tradeoffs

Delta supports updates, deletes, merges and concurrent writers; Spark is not
required. The Rust implementation exposes the Python `deltalake` package and works
with local filesystems and cloud storage. Rejecting Delta merely because the
catalog is small or Huron is Python would be misleading.
[delta-rs](https://delta-io.github.io/delta-rs/latest/),
[supported operations](https://delta-io.github.io/delta-rs/latest/feature-table/)

Its optimistic transactions can conflict when updates touch overlapping files.
Frequent small writes accumulate small files, for which Delta recommends
compaction. Obsolete data files require retention and vacuum management; table
history also has retention. This adds work for a catalog dominated by individual
record changes, although latency and contention need measurement against an
actual workload. It is not evidence that every Delta deployment would be slow.
[Concurrency](https://docs.delta.io/concurrency-control/),
[compaction](https://docs.delta.io/best-practices/),
[vacuum and history](https://docs.delta.io/delta-utility/)

Using an NFS path would also require verifying the chosen client's atomic-write,
durability and listing guarantees on the real mount. Filesystem accessibility
alone does not establish safe concurrent commits.
[Storage requirements](https://docs.delta.io/delta-storage/)

## Recommended boundary

Keep the transactional catalog in PostgreSQL and keep scientific file policy in
Huron. This uses an existing database for persistence rather than implementing a
new table-storage engine. Delta would replace that database's representation of
catalog rows, while leaving most of the custom domain work intact.

Revisit Delta for a concrete requirement to store extracted tabular measurements
or to distribute an analytical copy of catalog data to Delta-aware engines. Such
a copy would need explicit freshness, authorization and deletion semantics; it
would be a separate future decision, not a second source of truth or an existing
feature. That preserves the present Raw contract while leaving an appropriate
place for a table format if an analytical workload justifies it.
