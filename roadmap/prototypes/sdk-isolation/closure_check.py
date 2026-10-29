"""Evaluate actual wheel dependency metadata using the isolated build-time packaging library."""

import argparse
from email.parser import BytesParser
import json
from pathlib import Path
from zipfile import ZipFile

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def main():
    """Require a complete, minimal active dependency closure, not just a name denylist."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", action="append", required=True)
    parser.add_argument("--wheel", type=Path, action="append", required=True)
    args = parser.parse_args()
    available = {}
    for wheel in args.wheel:
        with ZipFile(wheel) as archive:
            metadata = BytesParser().parsebytes(archive.read(next(
                path for path in archive.namelist() if path.endswith(".dist-info/METADATA")
            )))
        name = canonicalize_name(metadata["Name"])
        assert name not in available
        available[name] = {
            "version": metadata["Version"],
            "requires_dist": metadata.get_all("Requires-Dist", []),
        }
    environment = {**default_environment(), "extra": ""}
    pending = [canonicalize_name(name) for name in args.root]
    reached = set()
    edges = []
    while pending:
        name = pending.pop()
        if name in reached:
            continue
        reached.add(name)
        for text in available[name]["requires_dist"]:
            requirement = Requirement(text)
            if requirement.marker is not None and not requirement.marker.evaluate(environment):
                continue
            assert not requirement.url and not requirement.extras, text
            dependency = canonicalize_name(requirement.name)
            assert dependency in available, f"unlocked dependency: {text}"
            assert requirement.specifier.contains(available[dependency]["version"])
            edges.append([name, dependency])
            pending.append(dependency)
    assert reached == set(available), f"extraneous wheel inputs: {set(available) - reached}"
    print(json.dumps({"roots": args.root, "packages": available, "active_edges": sorted(edges)}))


if __name__ == "__main__":
    main()
