"""Prepare a real isolated Icechunk metadata fixture for frontend browser tests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import icechunk
import numpy as np
import zarr


def seed(path: Path) -> dict:
    """Create two scientific commits and actual branch/tag references in fresh test storage.

    Args:
        path: Fresh repository location under the browser test's temporary storage root.

    Returns:
        Repository location and actual immutable snapshot references.

    Raises:
        RuntimeError: The requested location already contains an initialized repository.
    """
    path = path.resolve()
    path.mkdir(parents=True, exist_ok=True)
    storage = icechunk.local_filesystem_storage(str(path))
    if icechunk.Repository.exists(storage):
        raise RuntimeError("Browser fixture storage must be fresh.")
    repo = icechunk.Repository.create(storage)
    initialized = repo.lookup_branch("main")
    session = repo.writable_session("main")
    group = zarr.group(store=session.store)
    group.attrs.update(
        {
            "description": "Isolated browser test fixture",
            "source_url": "https://example.test/test-fixture",
            "source_selection": {"test_fixture": True},
            "import_receipt": {"test_fixture": True, "arrays": ["temperature"]},
        }
    )
    group.create_array(
        "temperature",
        data=np.arange(8, dtype="float32").reshape(2, 2, 2),
        chunks=(1, 2, 2),
        dimension_names=("time", "lat", "lon"),
        attributes={"_ARRAY_DIMENSIONS": ["time", "lat", "lon"], "units": "kelvin"},
    )
    first = session.commit("Fixture ingest 1")
    repo.create_branch("analysis", first)
    repo.create_tag("baseline", first)
    session = repo.writable_session("main")
    group = zarr.open_group(store=session.store, mode="a")
    group.attrs["description"] = "Isolated browser test fixture, corrected metadata"
    second = session.commit("Fixture metadata correction")
    return {
        "location": path.as_uri(),
        "initialized": initialized,
        "first": first,
        "main": second,
        "analysis": first,
        "baseline": first,
    }


def main() -> None:
    """Write one requested fresh browser-test fixture and report its real references."""
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument("path", type=Path)
    result = seed(arguments.parse_args().path)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
