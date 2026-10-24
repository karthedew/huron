---
status: accepted
---

# The Raw catalog of record is Huron's PostgreSQL; Raw is not registered in Polaris

Raw catalogs, namespaces, collections, files, metadata and audit live only in Huron's PostgreSQL, in
schema `lake` (Owner decision 6, option A). Huron holds no Polaris client, credential or service for Raw,
and OD-5 stands. We rejected Polaris generic tables (option B) for three reasons. They have no update,
rename, search or compare-and-set. An S3-only Polaris refuses POSIX base-locations from its next release
(upstream #5748). And Raw bytes sit on ONTAP NFS, which production Polaris does not manage. A later
discovery copy (option C) may be added as a one-way, level-triggered **Polaris projection** of settled
collections, keyed by collection UUID and never read back. Adding it requires an owner decision that
reverses OD-5.

Consequences: the lake keeps invariants P-1 to P-11 (`RAW_LAKE_DESIGN.md` DT-24) so that C stays
additive. This plan creates no projection port, table, worker, marker or dependency. Its closing check
must find no Polaris client import, setting, dependency, compose service or CI job.
