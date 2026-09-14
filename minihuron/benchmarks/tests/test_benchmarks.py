"""Benchmark publication, failure accounting, and capacity decisions are observable."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from minihuron.benchmarks.catalog import BenchmarkCatalog
from minihuron.benchmarks.metrics import UploadResult, summarize
from minihuron.benchmarks.run import _gb, capacity_summary, mount_details, run_scenario
from minihuron.benchmarks.workload import prepare_payload, stream_file
from minihuron.rawdatastore import (
    BUFFER_SIZE,
    FileSpec,
    IntegrityError,
    RawstoreService,
    RevisionConflict,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.contract
async def test_streaming_preserves_partial_last_block_with_bounded_buffers(tmp_path: Path) -> None:
    """A source larger than the buffer is streamed completely without whole-file allocation."""
    (spec,) = prepare_payload(tmp_path, 2 * BUFFER_SIZE + 17, 1)
    lengths = []
    digest = hashlib.sha256()
    async for block in stream_file(tmp_path / spec.path):
        lengths.append(len(block))
        digest.update(block)
    assert lengths == [BUFFER_SIZE, BUFFER_SIZE, 17]
    assert digest.hexdigest() == spec.sha256
    assert sum(lengths) == spec.size_bytes


@pytest.mark.contract
@pytest.mark.parametrize("size", [0, 10003])
async def test_concurrent_users_publish_exact_independent_revisions(
    tmp_path: Path, size: int
) -> None:
    """Queued concurrent users commit complete independent revisions, including zero bytes."""
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    target.mkdir()
    specs = prepare_payload(source, size, 3)
    results, elapsed = await run_scenario(
        target,
        source,
        specs,
        4,
        2,
        {"max_io": 2, "max_uploads": 1, "max_validations": 1, "max_ingests": 1},
    )
    assert len(results) == 8
    assert all(result.error is None and result.size_bytes == size for result in results)
    assert elapsed >= max(result.seconds for result in results)
    assert len(list(target.glob("datasets/*/revisions/*/COMMITTED"))) == 8
    revisions = list(target.glob("datasets/*/revisions/*"))
    assert len(revisions) == 8
    for revision in revisions:
        manifest = json.loads((revision / "manifest.json").read_text())
        assert sum(file["size_bytes"] for file in manifest["files"]) == size
        for spec in specs:
            payload = revision / "payload" / spec.path
            assert payload.read_bytes() == (source / spec.path).read_bytes()
            assert payload.stat().st_nlink == 1
        assert not (revision / ".incoming").exists()
    assert not list((target / ".staging").iterdir())


@pytest.mark.contract
async def test_corrupt_source_counts_failures_without_publication(tmp_path: Path) -> None:
    """Failed integrity checks contribute errors and no committed throughput."""
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    target.mkdir()
    specs = prepare_payload(source, 31, 1)
    (source / specs[0].path).write_bytes(b"corrupted")
    results, elapsed = await run_scenario(target, source, specs, 3, 2, {})
    assert len(results) == 6
    assert all(result.error and "IntegrityError" in result.error for result in results)
    assert not list(target.glob("datasets/*/revisions/*"))
    summary = summarize(results, elapsed, 300, 0)
    assert summary["errors"] == 6
    assert summary["committed_bytes"] == 0
    assert summary["committed_MB_per_second"] == 0
    assert summary["passed"] is False


@pytest.mark.contract
async def test_catalog_requires_receipts_and_enforces_head_conflicts(tmp_path: Path) -> None:
    """Incomplete revisions cannot publish; competing revisions retain conflict evidence."""
    catalog = BenchmarkCatalog(1)
    dataset = next(iter(catalog.datasets))
    service = RawstoreService(tmp_path, catalog)
    specs = (FileSpec("empty", 0, hashlib.sha256(b"").hexdigest()),)
    first = await service.stage(dataset, specs, idempotency_key="first")
    assert await service.stage(dataset, specs, idempotency_key="first") == first
    second = await service.stage(dataset, specs, idempotency_key="second")
    with pytest.raises(IntegrityError, match="Missing file receipts"):
        await service.ingest(first.ingest_id)
    for ingest in (first, second):
        async with catalog.upload_access(ingest.ingest_id):
            await catalog.file_received(ingest.ingest_id, specs[0])
        (service.fs.staging_root(ingest) / "payload" / "empty").touch()
    revision = await service.ingest(first.ingest_id)
    assert await service.ingest(first.ingest_id) == revision
    with pytest.raises(RevisionConflict):
        await service.ingest(second.ingest_id)
    with pytest.raises(IntegrityError, match="conflicted"):
        await service.ingest(second.ingest_id)
    with pytest.raises(ValueError, match="different files"):
        await catalog.begin_ingest(dataset, (), "first")


@pytest.mark.unit
def test_metrics_include_failure_time_and_only_successful_bytes() -> None:
    """Fast failures cannot contribute bytes or hide their error rate."""
    results = [
        UploadResult(0, 0, 1_000_000, 4, 1, 2, 1, None),
        UploadResult(1, 0, 1_000_000, 10, 1, 8, 1, "OSError: disk full"),
    ]
    metrics = summarize(results, 10, 5, 0)
    assert metrics["committed_MB_per_second"] == 0.1
    assert metrics["error_rate"] == 0.5
    assert metrics["latency_p95_seconds"] == 10
    assert metrics["success_latency_p95_seconds"] == 4
    assert metrics["passed"] is False
    assert summarize(results, 10, 10, 0.5)["passed"] is True
    assert summarize([], 1, 300, 1)["passed"] is False


@pytest.mark.unit
def test_capacity_requires_all_repeats_and_marks_sweep_ceiling() -> None:
    """A failed repeat disqualifies that level while nonmonotonic results remain explicit."""
    rows = [
        {"size_bytes": 0, "users": 1, "passed": True},
        {"size_bytes": 0, "users": 2, "passed": True},
        {"size_bytes": 0, "users": 2, "passed": False},
        {"size_bytes": 0, "users": 4, "passed": True},
        {"size_bytes": 10, "users": 1, "passed": False},
    ]
    first, second = capacity_summary(rows)
    assert first["highest_passing_tested_users"] == 4
    assert first["passing_tested_users"] == [1, 4]
    assert first["passed_at_sweep_ceiling"] is True
    assert second["highest_passing_tested_users"] is None
    assert second["passed_at_sweep_ceiling"] is False


@pytest.mark.unit
@pytest.mark.parametrize("value, expected", [("0", 0), ("10", 10_000_000_000), ("0.000000001", 1)])
def test_decimal_gb_parsing_is_exact(value: str, expected: int) -> None:
    """Fractional GB inputs resolve to exact decimal byte counts."""
    assert _gb(value) == expected


@pytest.mark.unit
@pytest.mark.parametrize("value", ["-1", "10.1", "nan", "inf", "0.0000000001", "invalid"])
def test_invalid_size_inputs_are_rejected(value: str) -> None:
    """Sizes outside the requested range and fractional bytes cannot enter a sweep."""
    with pytest.raises(argparse.ArgumentTypeError):
        _gb(value)


@pytest.mark.contract
def test_cli_reports_complete_sweep_and_cleans_only_owned_data(tmp_path: Path) -> None:
    """The CLI emits persistent reports and removes its sources and revisions only."""
    sentinel = tmp_path / "existing-user-file"
    sentinel.write_text("preserve")
    command = [
        sys.executable,
        "-m",
        "minihuron.benchmarks.run",
        "--root",
        str(tmp_path),
        "--output",
        str(tmp_path),
        "--scratch",
        str(tmp_path),
        "--allow-local",
        "--sizes-gb",
        "0",
        "0.000001",
        "--users",
        "1",
        "2",
        "--files",
        "3",
        "--uploads-per-user",
        "2",
        "--repeats",
        "1",
    ]
    dry_run = subprocess.run([*command, "--dry-run"], capture_output=True, text=True, check=True)
    assert json.loads(dry_run.stdout)["peak_target_payload_bytes"] == 4000
    assert list(tmp_path.iterdir()) == [sentinel]
    subprocess.run(command, capture_output=True, text=True, check=True)
    (output,) = tmp_path.glob("minihuron-results-*")
    assert json.loads((output / "metadata.json").read_text())["status"] == "complete"
    records = [json.loads(line) for line in (output / "requests.jsonl").read_text().splitlines()]
    assert len(records) == 18
    assert sum(not record["warmup"] for record in records) == 12
    assert all(record["error"] is None for record in records)
    assert all(
        row["highest_passing_tested_users"] == 2
        for row in json.loads((output / "summary.json").read_text())
    )
    assert len((output / "scenarios.csv").read_text().splitlines()) == 5
    assert sentinel.read_text() == "preserve"
    assert set(tmp_path.iterdir()) == {output, sentinel}
    assert mount_details(tmp_path)["filesystem"] != "unknown"
