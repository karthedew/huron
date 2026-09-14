# MiniHuron NFS write benchmarks

Measure concurrent users submitting complete Raw revisions to
[`RawstoreService`](../rawdatastore.py). Each simulated user has a separate dataset
and sends sequential uploads without think time. All users in a scenario start
together and share **one service instance** and its concurrency gates.

This is a **single-process service benchmark**, with an ephemeral in-memory catalog.
MiniHuron has no HTTP endpoint or PostgreSQL catalog implementation yet. Network
request parsing, authentication, database transactions, multiple application workers,
and multiple NFS clients are consequently outside these measurements.

## Run

From the repository root, using the repository environment:

```bash
# Create these directories at locations appropriate for your deployment first.
# /mnt/nfs/benchmarks must already exist on the mounted NFS export.
# /local/ssd/benchmarks is scratch space; /local/ssd/results holds small reports.
uv run python -m minihuron.benchmarks.run \
  --root /mnt/nfs/benchmarks \
  --scratch /local/ssd/benchmarks --output /local/ssd/results \
  --dry-run

# Initial sweep with the service's current default concurrency limits.
uv run python -m minihuron.benchmarks.run \
  --root /mnt/nfs/benchmarks \
  --scratch /local/ssd/benchmarks --output /local/ssd/results \
  --sizes-gb 0 0.001 0.1 1 5 10 \
  --users 1 2 4 8 16 32 64 \
  --uploads-per-user 3 --repeats 3 --max-p95-seconds 300

# Chunk-heavy submission: exact same total bytes split into 256 nested files.
uv run python -m minihuron.benchmarks.run \
  --root /mnt/nfs/benchmarks \
  --scratch /local/ssd/benchmarks --output /local/ssd/results \
  --sizes-gb 0.1 1 10 --files 256 --users 1 4 16 64

# Small local smoke test; does not measure NFS performance.
uv run python -m minihuron.benchmarks.run \
  --root /tmp --scratch /tmp --output /tmp --allow-local \
  --sizes-gb 0 0.00001 --users 1 4 --files 3 \
  --uploads-per-user 2 --repeats 1
```

Sizes are **decimal GB**, from 0 to 10 inclusive (10 GB = 10,000,000,000 bytes).
Zero creates the requested number of empty files, exercising directory creation,
manifests, fsync, rename and publication. It is not an empty manifest, which the
service rejects. File counts can exceed the byte count; remaining files are empty.

The runner checks Linux mount information and requires `nfs`/`nfs4` unless
`--allow-local` is explicit. It records the mount source and options. A missing
root is rejected instead of accidentally creating a local replacement mount.
All storage mutations are inside unique `minihuron-bench-*` directories beneath
the supplied root. Each scenario is removed after its records are written;
reports survive cleanup in a unique `minihuron-results-*` output directory.

## Workload and capacity

The default matrix includes 6 sizes, 7 user counts, 3 repetitions and 3 measured
uploads per user, plus one unmeasured warmup upload per user before each repetition.
The full matrix is intentionally substantial: about **24.54 TB** of submitted data
including warmup, before validation reads and metadata traffic. Run `--dry-run`
first for exact byte counts and peak payload storage requirements.

At 64 users × 3 uploads × 10 GB, a scenario retains **1.92 TB** on the target,
plus a **10 GB** scratch source. Completed revisions remain until the scenario
finishes; cleanup is excluded from timings. Free-space checks reserve 10% plus
64 MiB headroom, but do not predict filesystem quotas, inode exhaustion or
allocation overhead from huge numbers of tiny files. For exploration, reduce
`--uploads-per-user`, `--repeats`, or `--users`.

Synthetic source files contain actual random, non-sparse bytes generated and
hashed **before** timing. Memory is bounded by 4 MiB streaming buffers per active
transfer, rather than upload size. File contents are reused across users/repeats
and likely become cached on the load generator. Storage-side deduplication can
therefore favor these results even though random bytes resist compression. Record
dedup/compression settings when comparing deployments. A fast local SSD for scratch
avoids adding source-read traffic to the NFS under test. Source reads and server
I/O use the configured shared thread pool; source storage/CPU can limit load.

NASA downloads are unnecessary for byte-level NFS measurements. `--files` lets
you approximate a Zarr store's many-file workload without adding download time,
Earthdata credentials or a Zarr dependency. These synthetic files **are not valid
Zarr datasets**. Real Zarr chunk-size distributions, data compressibility, and
metadata layouts would be a separate representative-data workload.

## What gets timed

- **Stage:** dataset storage initialization, reservation and manifest creation.
- **Write:** source streaming, queueing, server hashing, file writes, fsync and receipts.
- **Commit:** queueing, complete checksum validation, rename, inventory validation,
  marker durability and in-memory publication.
- **End-to-end latency:** all three stages, including admission/semaphore waits.
- **Scenario wall time:** synchronized release until every user finishes.

Preparation, dataset registration, warmup and cleanup are excluded. The full
validation scan remains enabled. Neither OS nor NFS caches are dropped; fsync
semantics are those of the real service and configured client/server mount.
Warmup defaults to one full upload per user, not just opening a connection.
`--no-warmup` omits that traffic but does not make the run a cold-cache benchmark.

## Results and finding a user limit

Each run writes:

| File | Contents |
| --- | --- |
| `metadata.json` | Completion status, timestamps, exact settings, Python/platform, mounts, service source SHA-256 and capacity plan |
| `requests.jsonl` | Every measured/warmup attempt, user/repeat identity, phase timings and exception details |
| `scenarios.csv` | Per-size/concurrency/repeat throughput, error rate, p50/p95/p99 and pass/fail |
| `summary.json` | Highest passing tested user count per size and whether the sweep ceiling passed |

Throughput is **successfully committed logical payload MB/s** (decimal MB), not
physical NFS traffic. Failed bytes are not counted; failed attempt time remains
in scenario wall time. Percentiles use nearest rank over all attempts; successful
upload p95 is also reported separately. At zero bytes, use uploads/s and latency.

A concurrency level passes only if **every measured repetition** meets
`--max-p95-seconds` (default 300 seconds) and `--max-error-rate` (default 0), with
at least one success. These are configurable experimental targets, not a product
SLA. Use more uploads/repeats for stable percentiles; a p99 with a handful of
observations is simply the slowest observed request. Inspect `metadata.json` for
`status: complete` before treating the summary as a completed sweep. Partial
reports are retained on interruption; failed warmups abort the sweep with details.

The highest passing **tested** concurrency is not a universal maximum. If the
ceiling passes, extend `--users`; if levels fail, rerun a finer grid around the
boundary and inspect errors, throughput and latency. Non-monotonic passing levels
are retained rather than assuming a clean threshold. Exit 0 means the sweep
completed, even if some levels failed their target; setup/runtime failures exit 2.

Service defaults (`max_io=8`, `max_uploads=4`, `max_validations=2`, `max_ingests=4`)
mean 64 simulated users do **not** imply 64 simultaneous file writers. Compare
controlled runs with `--max-uploads`, `--max-io`, `--max-validations`, `--max-ingests`
and `--threads` to distinguish service admission limits from NFS saturation.
Keep limits fixed within each sweep. For example, compare the baseline to
`--max-uploads 32 --max-io 64 --max-validations 8 --max-ingests 16 --threads 96`.

This is a finite, closed-loop workload: active user count falls as users finish,
and new arrivals are not modeled during overload. It measures this client's
service/NFS path rather than proving production multi-client capacity. Observe
client/server CPU, network, disk and NFS telemetry alongside the reports. NFS
syscalls on an unavailable hard mount can block shutdown; cancellation drains
filesystem work, and the harness deliberately does not promise a hard timeout.
A killed process may leave its uniquely named scratch/target directories behind.

## Verify the harness

```bash
uv run python -m pytest minihuron/benchmarks/tests -m 'unit or contract'
uv run ruff check minihuron/benchmarks
uv run ruff format --check minihuron/benchmarks
```

Tests use temporary local filesystems for observable publication, concurrency,
byte integrity, failed uploads, and reporting. Actual NFS capacity measurements
must run on the intended mounted deployment.
