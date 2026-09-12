# M1a implementation audit — 2026-09-11

This attempt finishes local functional acceptance of the existing implementation.
No production Python or database migration was changed. Independent verification
is a subsequent step; this receipt does not certify deployment or all of P3.

## Seven implementation requirements

| Requirement | Inspected implementation | Observable coverage |
| --- | --- | --- |
| Separate upload, completion and envelope; only begin creates the session root | `catalog.paths.StagingPaths`, `rawstore.store.create_staging`, descriptor-relative later writes | `test_rawstore_materialize`: missing/relocated session and ancestor, nested/session symlink refusal, delayed completion/document writers |
| Closed verified independent candidate, durable exclusive installation | `materialize.candidate`, `observe`, `install`; `PosixRawStore._copy_file` | Empty, single-byte and multi-block contents; no writable descriptor at installation, different inode, sealed/link-count-one payload; syscall failures and cancellation |
| Concurrent completions and durable COMPLETE receipts | `_copy_file` verifies installed winners; core `_materialize_file` records after installation with conditional ledger writes | Real filesystem overlapping completions; real PostgreSQL matching/corrupt loser tests; abrupt process death before and after COMPLETE commit; retry preserves installed inode |
| Frozen command and document bytes, validated replay | `IngestService.commit`, PostgreSQL `freeze_commit` row lock and immutable intent trigger, `_publish_envelope`, `inspection.verify_envelope` | Distinct clocks, matching/different keys, changed metadata, modified final documents/payload; publication syscall crash matrix; PostgreSQL process death and exactly-once revision/audit/outbox assertions |
| COMMITTED v2 and v1 decoding; envelope-only rename | `CommitRecord`, committed-v2 schema, `commit.commit_envelope`, exclusive rename and same-device checks | Explicit v1/v2 round-trip and unknown-version refusal; exact final inventory; cross-device refusal; stale upload handles cannot alter published bytes |
| Migration refusal and RECOVERING claim semantics | Migration 0011, `IngestState`, recovery identity trigger, unchanged partial indexes | Real upgrade refuses PREPARING/UPLOADING/VERIFYING/COMMITTING and retains 0010; succeeds after terminalization; RECOVERING remains in both claim predicates and fences stale commit/renewal |
| Schema-map and structural conformance | `migrations/schema.sql` state and trigger annotations, adapter wiring protocols | Schema-map lint; real constraint-name and immutable-intent assertions; strict type checks |

Existing tests inject faults at actual filesystem/database boundaries and inspect
real bytes and persisted rows. Some focused tests are labeled unit but use a real
temporary filesystem. The PostgreSQL contracts are distinct from the large-file
acceptance fixture, whose database stores remain in memory.

## Full-size acceptance observation

`make test-acceptance` ran with a unique temporary base and a JUnit output path in
`PYTEST_ADDOPTS`; the command and unchanged 9 GiB / 144 × 64 MiB transfer are
recorded in `acceptance.log` and `acceptance.xml`. The first client sends 50 parts,
the second resumes the remaining 94, completion returns COMPLETE, commit returns
201, and streamed download verifies exact size, Content-Length and SHA-256.

- Result: 1 passed, 1477 deselected, no skipped tests, in 90.41 seconds.
- Completion request elapsed: 25.140104 seconds.
- Commit request elapsed: 11.347745 seconds. This includes publication inventory
  verification, durable rename and bookkeeping, not an additional payload copy.
- Initial free capacity: 60,035,276,800 bytes (55.91 GiB).
- Sampled peak allocated file bytes: 19,339,444,224 bytes (18.01 GiB).
- Minimum observed filesystem free capacity: 40,686,743,552 bytes (37.89 GiB).
- Final free capacity before fixture cleanup: 50,358,960,128 bytes (46.90 GiB).

Environment: local Darwin/macOS APFS on internal SSD, actual POSIX operations and
loopback uvicorn/httpx, development-header authentication. No NFS, remote storage,
production identity provider, database-backed large-file run or deployment fence
was exercised by this acceptance command.

`storage-observer.py.txt` is the exact external observation script, not application
code. It samples the unique fixture tree approximately every 0.2 seconds, summing
`st_blocks * 512` once per `(st_dev, st_ino)` and observing `shutil.disk_usage.free`.
`storage-samples.csv` retains all 441 samples; `acceptance-storage.json` retains
the run identity and aggregates. These are sampled observations, not exact
instantaneous peaks: walks are not atomic and can miss transient files or growth.
Directory metadata, open-unlinked files and filesystem internals are not included
in the file-block sum; filesystem free capacity also reflects unrelated consumers.
No filesystem block-I/O counter or physical write amplification was measured.
Client response elapsed time is a single local observation, not a latency promise.

The 25 GiB prerequisite is calculated from 18 GiB for coexisting upload and
candidate plus 7 GiB headroom (including the default 1 GiB completion reserve).
The sparse source has negligible allocation and the download streams without a
second file. This calculation applies to one acceptance run; parallel runs,
multiple completers and open upload handles need their own capacity accounting.

## Scope and remaining work

The new test helper refuses insufficient or unavailable capacity before server
startup; five direct tests cover zero, one byte below the minimum, exactly the
minimum, one byte above it, and failed observation. Makefile, AGENTS.md and the
testing guide now state the enforced 25 GiB prerequisite. Acceptance records its
completion/commit durations as JUnit suite properties.

M1b/M1c exclusion, complete legacy verification, cutover and startup remain
unimplemented and required before deploying this protocol. M2–M7 remain pending.
The duplication plan stays paused before D3b; native 90 remains the requirement.
