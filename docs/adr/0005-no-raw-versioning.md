---
status: accepted
---

# Raw keeps no versions; ONTAP snapshots are recovery

The Raw lake records current state only: one file row per `rel_path`, overwritten in place by an
explicit `overwrite`, and removed by `rm` (`spec:32`). ONTAP volume snapshots are the only history and the
only undo, as with Databricks Volumes and Snowflake stages. This reverses the immutable-revision model
(old `AGENTS.md:105-119`, `dataset_revisions`, OD-1's version half). Copying every submission
independently made each correction a full re-upload. The spec's operators restore from `.snapshot`
instead. The append-only `audit_log` is what makes snapshots usable: every overwrite and remove keeps
the old hash, size, uploader and time, and so names the snapshot to restore from.

Consequences: downstream lineage pins a Raw input as `(collection id, rel_path, sha256)` and verifies
it by hash (`AGENTS.md` lineage-pin rule). Pinned bytes outlive a change only as long as the snapshot
policy keeps them. Data that must be retained needs a SnapLock volume chosen up front (`spec:328`). The
server never deletes user-named content except partials.
