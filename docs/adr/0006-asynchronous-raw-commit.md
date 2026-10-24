---
status: accepted
---

# Raw commits are asynchronous

`POST /api/v1/collections/{id}/commit` answers 202 with a commit id once the cheap checks pass (Owner
decision 3). A bounded per-replica worker re-hashes every add from the mount. It then applies the file
rows, the collection's version bump and the audit entries in one transaction, which also marks the
commit `succeeded`. The CLI polls. A synchronous commit would hold a request open for the length of a
multi-terabyte re-hash, far beyond any route timeout. Durable `queued`/`verifying` state, leases and a
per-file checkpoint let any replica finish a commit after a restart. The final transaction re-stamps
every file (inode, size, mtime and ctime) under the collection lock, so a row never claims bytes that
changed after their hash.

Consequences:

- `If-Match` is checked once, at acceptance. Later changes by others refuse only conflicting files
  (OQ-14.1 (a)).
- Each add's stamp includes ctime, and a changed file is re-verified once before a refusal
  (OQ-14.2 (a)).
- A checkpoint bounds lost hashing to one lease interval (OQ-14.3 (a)).
- `Idempotency-Key` is required on the POST. A 503 `DEPENDENCY_UNAVAILABLE`, including a lake-database
  outage (OQ-18.1 (a)), is retried with the same key. A terminal status is final, and the CLI starts a
  new key only after `failed`.
