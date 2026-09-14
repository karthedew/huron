"""Upload one local file into Minihuron's raw store.

Run from the repository root::

    uv run python -m minihuron.main /path/to/file --root /existing/storage/root

Each invocation creates a new demo dataset using the benchmark's in-memory
catalog. Uploaded files persist on disk; catalog state and retry identities do
not survive process exit.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from uuid import uuid4

# Support both `python minihuron/main.py` and `python -m minihuron.main`.
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from minihuron.benchmarks.catalog import BenchmarkCatalog
from minihuron.benchmarks.workload import stream_file
from minihuron.rawdatastore import FileSpec, RawstoreService, finish_thread, sha256_file


async def upload_file(source: Path, root: Path) -> Path:
    """Stream a single file and finalize its revision before returning.

    Args:
        source: Local file to upload under its original basename.
        root: Existing absolute storage directory.

    Returns:
        The committed payload's absolute path.
    """
    spec = FileSpec(
        path=source.name,
        size_bytes=source.stat().st_size,
        sha256=await finish_thread(sha256_file, source),
    )
    catalog = BenchmarkCatalog(users=1)
    dataset_id = next(iter(catalog.datasets))
    service = RawstoreService(root, catalog)
    ingest = await service.stage(dataset_id, (spec,), idempotency_key=str(uuid4()))
    await service.write_file(ingest.ingest_id, spec.path, stream_file(source))
    revision = await service.ingest(ingest.ingest_id)
    return root / revision.relative_path / "payload" / spec.path


def main() -> None:
    """Parse command arguments, upload the file, and report its stored path."""
    parser = argparse.ArgumentParser(
        description="Upload one file to the raw store using an ephemeral demo catalog.",
        epilog="Each run creates a new dataset. Files persist; catalog state does not.",
    )
    parser.add_argument("source", type=Path, help="Local file to upload")
    parser.add_argument("--root", required=True, type=Path, help="Existing storage directory")
    args = parser.parse_args()
    source = args.source.expanduser().absolute()
    root = args.root.expanduser().absolute()
    if not source.is_file():
        parser.error(f"Source must be a regular file: {source}")
    if not root.is_dir():
        parser.error(f"Storage root must already exist: {root}")
    try:
        stored_path = asyncio.run(upload_file(source, root))
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"Upload failed: {exc}\n")
    print(f"Uploaded: {stored_path}")


if __name__ == "__main__":
    main()
