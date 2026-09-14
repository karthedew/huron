"""Run a closed-loop concurrency/size sweep against one RawstoreService."""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import math
import platform
import re
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING

from minihuron.benchmarks.catalog import BenchmarkCatalog
from minihuron.benchmarks.metrics import UploadResult, summarize
from minihuron.benchmarks.workload import prepare_payload, stream_file
from minihuron.rawdatastore import RawstoreService, finish_thread

if TYPE_CHECKING:
    from uuid import UUID

    from minihuron.rawdatastore import FileSpec


def _gb(value: str) -> int:
    try:
        size = Decimal(value) * 1_000_000_000
        if not size.is_finite() or not 0 <= size <= 10_000_000_000 or size != int(size):
            raise ValueError
        return int(size)
    except (InvalidOperation, ValueError, OverflowError) as exc:
        raise argparse.ArgumentTypeError("Use 0..10 decimal GB, resolving to whole bytes") from exc


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Must be positive")
    return number


def _directory(value: str) -> Path:
    path = Path(value).resolve()
    if not path.is_dir():
        raise argparse.ArgumentTypeError(f"Directory must already exist: {path}")
    return path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=_directory, help="Existing NFS directory")
    parser.add_argument(
        "--output", type=_directory, default=Path.cwd(), help="Existing results parent"
    )
    parser.add_argument("--scratch", type=_directory, default=Path(tempfile.gettempdir()))
    parser.add_argument(
        "--sizes-gb", nargs="+", type=_gb, default=[0, 10**6, 10**8, 10**9, 5 * 10**9, 10**10]
    )
    parser.add_argument("--users", nargs="+", type=_positive, default=[1, 2, 4, 8, 16, 32, 64])
    parser.add_argument("--files", type=_positive, default=1, help="Files per submission")
    parser.add_argument("--uploads-per-user", type=_positive, default=3)
    parser.add_argument("--repeats", type=_positive, default=3)
    parser.add_argument(
        "--no-warmup", action="store_true", help="Omit the unmeasured upload per user"
    )
    parser.add_argument("--max-p95-seconds", type=float, default=300.0)
    parser.add_argument("--max-error-rate", type=float, default=0.0)
    parser.add_argument("--max-io", type=_positive, default=8)
    parser.add_argument("--max-uploads", type=_positive, default=4)
    parser.add_argument("--max-validations", type=_positive, default=2)
    parser.add_argument("--max-ingests", type=_positive, default=4)
    parser.add_argument("--threads", type=_positive, default=32)
    parser.add_argument("--allow-local", action="store_true", help="Allow a non-NFS smoke test")
    parser.add_argument(
        "--dry-run", action="store_true", help="Print workload/capacity plan without writing"
    )
    return parser


def mount_details(path: Path) -> dict[str, str]:
    """Resolve the longest matching Linux mount, retaining its NFS options.

    Args:
        path: Absolute resolved target directory.

    Returns:
        Mount point, filesystem, source, and mount options, or an unknown filesystem.
    """
    mountinfo = Path("/proc/self/mountinfo")
    if not mountinfo.exists():
        return {"filesystem": "unknown"}
    best: dict[str, str] = {"filesystem": "unknown"}
    for line in mountinfo.read_text().splitlines():
        before, after = line.split(" - ", 1)
        fields, filesystem = before.split(), after.split()
        mount = re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), fields[4])
        if path.is_relative_to(mount) and len(mount) > len(best.get("mount", "")):
            best = {
                "mount": mount,
                "filesystem": filesystem[0],
                "source": filesystem[1],
                "options": fields[5],
                "super_options": filesystem[2],
            }
    return best


async def _upload(
    service: RawstoreService,
    dataset: UUID,
    source: Path,
    specs: tuple[FileSpec, ...],
    user: int,
    upload: int,
) -> UploadResult:
    started = checkpoint = time.perf_counter()
    timings = {"stage": 0.0, "write": 0.0, "commit": 0.0}
    phase = "stage"
    error = None
    try:
        ingest = await service.stage(dataset, specs, idempotency_key=f"{user}-{upload}")
        timings[phase] = time.perf_counter() - checkpoint
        phase, checkpoint = "write", time.perf_counter()
        for spec in specs:
            chunks = stream_file(source / spec.path)
            try:
                await service.write_file(ingest.ingest_id, spec.path, chunks)
            finally:
                await chunks.aclose()
        timings[phase] = time.perf_counter() - checkpoint
        phase, checkpoint = "commit", time.perf_counter()
        await service.ingest(ingest.ingest_id)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        timings[phase] = time.perf_counter() - checkpoint
    return UploadResult(
        user,
        upload,
        sum(spec.size_bytes for spec in specs),
        time.perf_counter() - started,
        timings["stage"],
        timings["write"],
        timings["commit"],
        error,
    )


async def run_scenario(
    root: Path,
    source: Path,
    specs: tuple[FileSpec, ...],
    users: int,
    uploads: int,
    limits: dict[str, int],
) -> tuple[list[UploadResult], float]:
    """Release users together; each submits another upload after the previous finishes.

    Dataset registration is outside measurement; stage, transfer, commit and all
    semaphore waits are inside. All users share the same service and I/O gates.

    Args:
        root: Existing isolated storage root.
        source: Prepared source directory.
        specs: Complete submission manifest.
        users: Concurrent simulated users.
        uploads: Sequential uploads per user.
        limits: RawstoreService concurrency options.

    Returns:
        Every upload result and total measured wall time.
    """
    catalog = BenchmarkCatalog(users)
    service = RawstoreService(root, catalog, **limits)
    release = asyncio.Event()

    async def writer(user: int, dataset: UUID) -> list[UploadResult]:
        await release.wait()
        return [
            await _upload(service, dataset, source, specs, user, index) for index in range(uploads)
        ]

    tasks = [
        asyncio.create_task(writer(user, dataset)) for user, dataset in enumerate(catalog.datasets)
    ]
    await asyncio.sleep(0)
    started = time.perf_counter()
    release.set()
    try:
        batches = await asyncio.gather(*tasks)
    finally:
        # Drain filesystem work before the caller removes its isolated directory.
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return [result for batch in batches for result in batch], time.perf_counter() - started


def capacity_summary(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Require every repeat at a concurrency level to meet its acceptance target.

    Args:
        rows: Completed measured scenarios.

    Returns:
        Highest passing tested concurrency per size, with sweep-boundary context.
    """
    summaries = []
    for size in sorted({int(str(row["size_bytes"])) for row in rows}):
        selected = [row for row in rows if row["size_bytes"] == size]
        levels = sorted({int(str(row["users"])) for row in selected})
        passing = [
            level
            for level in levels
            if all(row["passed"] for row in selected if row["users"] == level)
        ]
        summaries.append(
            {
                "size_bytes": size,
                "highest_passing_tested_users": max(passing, default=None),
                "passing_tested_users": passing,
                "highest_tested_users": max(levels),
                "passed_at_sweep_ceiling": max(levels) in passing,
            }
        )
    return summaries


def _check_space(root: Path, scratch: Path, source_bytes: int, target_bytes: int) -> None:
    # Include a margin for manifests, directory entries, allocation rounding and other writers.
    margin = 64 * 1024**2
    target_required = math.ceil(target_bytes * 1.1) + margin
    source_required = math.ceil(source_bytes * 1.1) + margin
    if root.stat().st_dev == scratch.stat().st_dev:
        target_required += source_required
    elif shutil.disk_usage(scratch).free < source_required:
        raise OSError(f"Insufficient scratch space; need approximately {source_required} bytes")
    if shutil.disk_usage(root).free < target_required:
        raise OSError(f"Insufficient target space; need approximately {target_required} bytes")


async def _sweep(args: argparse.Namespace, output: Path) -> list[dict[str, object]]:
    limits = {
        key: getattr(args, key)
        for key in ("max_io", "max_uploads", "max_validations", "max_ingests")
    }
    rows: list[dict[str, object]] = []
    with (
        (output / "requests.jsonl").open("x") as requests,
        (output / "scenarios.csv").open("x", newline="") as table,
    ):
        csv_writer = None
        for size in args.sizes_gb:
            _check_space(
                args.root, args.scratch, size, size * max(args.users) * args.uploads_per_user
            )
            with tempfile.TemporaryDirectory(
                prefix="minihuron-source-", dir=args.scratch
            ) as source_name:
                source = Path(source_name)
                print(f"Preparing {size / 1e9:g} GB in {args.files} file(s)", flush=True)
                specs = await finish_thread(prepare_payload, source, size, args.files)
                for users in args.users:
                    for repeat in range(args.repeats):
                        for warmup in [True, False] if not args.no_warmup else [False]:
                            uploads = 1 if warmup else args.uploads_per_user
                            _check_space(args.root, args.scratch, 0, size * users * uploads)
                            with tempfile.TemporaryDirectory(
                                prefix="minihuron-bench-", dir=args.root
                            ) as target:
                                results, elapsed = await run_scenario(
                                    Path(target), source, specs, users, uploads, limits
                                )
                                # Record failures even in warmup, before cleaning this scenario.
                                scenario = {
                                    "size_bytes": size,
                                    "users": users,
                                    "repeat": repeat + 1,
                                    "warmup": warmup,
                                }
                                for result in results:
                                    requests.write(json.dumps(scenario | asdict(result)) + "\n")
                                requests.flush()
                                if warmup:
                                    if any(result.error for result in results):
                                        raise RuntimeError("Warmup failed; inspect requests.jsonl")
                                    continue
                                row = (
                                    scenario
                                    | {"files": args.files}
                                    | summarize(
                                        results, elapsed, args.max_p95_seconds, args.max_error_rate
                                    )
                                )
                                rows.append(row)
                                if csv_writer is None:
                                    csv_writer = csv.DictWriter(table, fieldnames=list(row))
                                    csv_writer.writeheader()
                                csv_writer.writerow(row)
                                table.flush()
                                print(json.dumps(row), flush=True)
                                (output / "summary.json").write_text(
                                    json.dumps(capacity_summary(rows), indent=2) + "\n"
                                )
    return rows


def main() -> int:
    """Validate a sweep, record its environment, and run the measured workload.

    Returns:
        Zero for a complete sweep, two for setup/runtime failure or interruption.
        Individual failed capacity levels remain valid benchmark results.
    """
    parser = _parser()
    args = parser.parse_args()
    if not math.isfinite(args.max_p95_seconds) or args.max_p95_seconds <= 0:
        parser.error("--max-p95-seconds must be finite and positive")
    if not 0 <= args.max_error_rate <= 1:
        parser.error("--max-error-rate must be between zero and one")
    args.sizes_gb = sorted(set(args.sizes_gb))
    args.users = sorted(set(args.users))
    mount = mount_details(args.root)
    if mount["filesystem"] not in {"nfs", "nfs4"} and not args.allow_local:
        parser.error(
            "--root is not a detected NFS mount; use --allow-local only for local experiments"
        )
    largest = max(args.sizes_gb)
    measured_bytes = sum(args.sizes_gb) * sum(args.users) * args.repeats * args.uploads_per_user
    plan = {
        "measured_payload_bytes": measured_bytes,
        "warmup_payload_bytes": 0 if args.no_warmup else measured_bytes // args.uploads_per_user,
        "peak_target_payload_bytes": largest * max(args.users) * args.uploads_per_user,
        "peak_scratch_payload_bytes": largest,
        "scenario_count": len(args.sizes_gb) * len(args.users) * args.repeats,
        "mount": mount,
    }
    print(json.dumps(plan, indent=2), flush=True)
    if args.dry_run:
        return 0
    output = Path(tempfile.mkdtemp(prefix="minihuron-results-", dir=args.output))
    service_path = Path(__file__).parents[1] / "rawdatastore.py"
    metadata = {
        "started_utc": datetime.now(UTC).isoformat(),
        "status": "running",
        "scope": "single-process RawstoreService; in-memory catalog; no HTTP",
        "config": {
            key: str(value) if isinstance(value, Path) else value
            for key, value in vars(args).items()
        },
        "size_unit": "decimal GB (1,000,000,000 bytes)",
        "platform": platform.platform(),
        "python": sys.version,
        "rawdatastore_sha256": hashlib.sha256(service_path.read_bytes()).hexdigest(),
        "scratch_mount": mount_details(args.scratch),
        "plan": plan,
    }
    metadata_path = output / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Results: {output}", flush=True)
    try:
        with ThreadPoolExecutor(max_workers=args.threads) as executor, asyncio.Runner() as runner:
            runner.get_loop().set_default_executor(executor)
            runner.run(_sweep(args, output))
        metadata["status"] = "complete"
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        metadata["status"] = "incomplete"
        metadata["error"] = f"{type(exc).__name__}: {exc}"
        print(metadata["error"], file=sys.stderr)
        return 2
    finally:
        metadata["finished_utc"] = datetime.now(UTC).isoformat()
        metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
