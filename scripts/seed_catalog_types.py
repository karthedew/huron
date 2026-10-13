"""Register retained NASA ACE source files and their exact observations as Raw and Iceberg.

Run with .local/polaris/icechunk-venv/bin/python scripts/seed_catalog_types.py.
Dependencies: pyiceberg[pyarrow]==0.11.1. The existing NASA Icechunk sample is unchanged.
Native REST operations use local deployment credentials; no credentials are printed or stored
in scientific metadata. Registration does not claim a Huron Raw revision or scientific lineage.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote, unquote, urlparse

import pyarrow as pa
from import_mission_samples import ACE_SAMPLE, parse_ace_csv
from polaris_dev import BASE_URL, REALM, exists, obtain_token, request, save
from pyiceberg.catalog.rest import RestCatalog
from pyiceberg.exceptions import NoSuchTableError
from pyiceberg.schema import Schema
from pyiceberg.types import DoubleType, LongType, NestedField

if TYPE_CHECKING:
    from pyiceberg.catalog import Catalog

STATE = Path(__file__).resolve().parents[1] / ".local" / "polaris"
CATALOG = "heliophysics"
NAMESPACE = ("solar_wind", "ace")
RAW_NAME = "ace_source_files"
TABLE_NAME = "ace_observations"
DATA_HASH = "abc23cc8f079789ab1ad92caf868303397c2ed2f50d77efe3d2fe87c867e00b6"
METADATA_HASH = "e267b2bc0ccf9d4f14d8bdab622b3dd5fb8fe5d91e6f69e109f63456fa5f05d8"
SEED_ID = "huron-nasa-ace-catalog-types-v1"
RAW_PATH = (
    f"/api/catalog/polaris/v1/{CATALOG}/namespaces/{quote(chr(31).join(NAMESPACE))}/generic-tables"
)


def source_bytes(state: Path = STATE) -> tuple[bytes, bytes]:
    """Read pinned, bounded original downloads and verify both source identities.

    Args:
        state: Local Polaris sandbox directory.

    Returns:
        Original scientific CSV and native HAPI metadata bytes.

    Raises:
        RuntimeError: A source exceeds its size bound or does not match its pinned checksum.
    """
    source = state / "source-files" / CATALOG / "ace_magnetic_field"
    result = []
    for digest, suffix in [(DATA_HASH, "data.csv"), (METADATA_HASH, "metadata.json")]:
        path = source / f"{digest}-{suffix}"
        if path.is_symlink() or path.stat().st_size > 1024 * 1024:
            raise RuntimeError("A NASA source is not a bounded regular download.")
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != digest:
            raise RuntimeError("A retained NASA source checksum does not match.")
        result.append(payload)
    return result[0], result[1]


def observations(payload: bytes, metadata: bytes) -> tuple[pa.Table, Schema]:
    """Represent every selected ACE scalar and vector component without resampling.

    Args:
        payload: Selected NASA HAPI CSV observations.
        metadata: Their native HAPI parameter descriptions.

    Returns:
        Exact Arrow values and an Iceberg schema with units, frames and fill-value semantics.
    """
    arrays = parse_ace_csv(json.loads(metadata), payload)
    columns = {"time_unix_ns": arrays["time"][0], "magnitude_nt": arrays["Magnitude"][0]}
    for frame in ["BGSEc", "BGSM"]:
        for index, component in enumerate("xyz"):
            columns[f"{frame.lower()}_{component}_nt"] = arrays[frame][0][:, index]
    columns["dbrms_nt"] = arrays["dBrms"][0]
    fields = [
        NestedField(
            field_id=index + 1,
            name=name,
            field_type=LongType() if index == 0 else DoubleType(),
            required=True,
            doc=(
                "Exact UTC nanoseconds since 1970-01-01T00:00:00Z; native ACE sampling."
                if index == 0
                else "NASA ACE/MAG magnetic field in nT; native -1e31 missing values retained. "
                + ("GSE Cartesian component." if name.startswith("bgsec") else "")
                + ("GSM Cartesian component." if name.startswith("bgsm") else "")
            ),
        )
        for index, name in enumerate(columns)
    ]
    arrow_schema = pa.schema(
        [
            pa.field(name, pa.int64() if index == 0 else pa.float64(), nullable=False)
            for index, name in enumerate(columns)
        ]
    )
    return pa.Table.from_pydict(columns, schema=arrow_schema), Schema(*fields)


def preserve_file(path: Path, payload: bytes) -> None:
    """Publish a retained source copy once and refuse to replace differing existing bytes.

    Args:
        path: Destination inside the verified catalog storage root.
        payload: Exact source bytes.

    Raises:
        RuntimeError: Existing storage is a symlink or contains different bytes.
    """
    if any(parent.is_symlink() for parent in [path, *path.parents]):
        raise RuntimeError("Refusing a symlink in the local sample destination.")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise RuntimeError("Existing source copy differs; refusing to overwrite it.")
        return
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
        temporary = Path(output.name)
        try:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                if path.is_symlink() or path.read_bytes() != payload:
                    raise RuntimeError("Existing source copy changed during publication.") from None
        finally:
            temporary.unlink(missing_ok=True)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def seed_iceberg(
    catalog: Catalog, root: Path, expected: pa.Table, schema: Schema, *, verify_only: bool = False
) -> dict:
    """Create or resume one native table and verify every row before reporting success.

    Args:
        catalog: Authenticated native REST catalog or temporary SDK test catalog.
        root: Verified catalog FILE storage root.
        expected: Exact source observations.
        schema: Scientific column schema.
        verify_only: Require existing metadata and data without creating or appending anything.

    Returns:
        Actual snapshot, row count, schema fields and source identity.

    Raises:
        RuntimeError: Existing metadata or observations do not match the owned sample.
    """
    identifier = (*NAMESPACE, TABLE_NAME)
    destination = root.joinpath(*NAMESPACE, TABLE_NAME)
    if any(parent.is_symlink() for parent in [destination, *destination.parents]):
        raise RuntimeError("Refusing a symlink in the Iceberg sample destination.")
    location = destination.as_uri()
    properties = {
        "huron.seed": SEED_ID,
        "huron.layer": "bronze",
        "source.sha256": DATA_HASH,
        "source.dataset": "AC_H0_MFI",
        "source.url": ACE_SAMPLE["url"],
        "source.title": ACE_SAMPLE["title"],
        "source.doi": ACE_SAMPLE["doi"],
        "description": (
            f"All {expected.num_rows:,} ACE/MAG observations for 2020-01-01; vectors expanded "
            "into columns, no resampling. Native missing-value sentinel -1e31 is retained."
        ),
        "format-version": "2",
    }
    try:
        table = catalog.load_table(identifier)
    except NoSuchTableError:
        if verify_only:
            raise RuntimeError("The Iceberg sample is not registered.") from None
        table = catalog.create_table(identifier, schema, location=location, properties=properties)
    if (
        table.location() != location
        or any(
            table.properties.get(key) != value
            for key, value in properties.items()
            if key != "format-version"
        )
        or table.schema() != schema
    ):
        raise RuntimeError("Existing Iceberg registration differs; refusing to modify it.")
    if table.current_snapshot() is None:
        if verify_only:
            raise RuntimeError("The Iceberg sample has no committed observations.")
        table.append(
            expected, snapshot_properties={"source.sha256": DATA_HASH, "huron.seed": SEED_ID}
        )
    table.refresh()
    actual = table.scan().to_arrow().sort_by("time_unix_ns")
    if not actual.equals(expected.sort_by("time_unix_ns"), check_metadata=False):
        raise RuntimeError("Iceberg readback differs from the exact ACE source observations.")
    snapshot = table.current_snapshot()
    if snapshot is None:
        raise RuntimeError("The Iceberg sample did not publish a snapshot.")
    return {
        "catalog": CATALOG,
        "namespace": list(NAMESPACE),
        "table": TABLE_NAME,
        "format": "iceberg",
        "snapshotId": str(snapshot.snapshot_id),
        "metadataLocation": table.metadata_location,
        "rows": actual.num_rows,
        "columns": actual.column_names,
        "sourceSha256": DATA_HASH,
    }


def run(*, verify_only: bool = False) -> dict:
    """Seed only the existing local heliophysics catalog using its deployment credentials.

    Args:
        verify_only: Require and verify existing registrations without modifying storage or Polaris.

    Returns:
        Verified Raw registration and Iceberg snapshot receipts, containing no credentials.

    Raises:
        RuntimeError: The local catalog, source copies or existing registration differs.
    """
    payload, metadata = source_bytes()
    arrow, schema = observations(payload, metadata)
    if arrow.num_rows != 5401:
        raise RuntimeError("The pinned ACE day has an unexpected observation count.")
    credentials = json.loads((STATE / "credentials.json").read_text())
    token = obtain_token(credentials["admin"])
    catalog_metadata = request(f"/api/management/v1/catalogs/{CATALOG}", token=token)
    root = STATE / "nasa-storage" / CATALOG
    configured = urlparse(catalog_metadata["properties"]["default-base-location"])
    allowed = catalog_metadata["storageConfigInfo"].get("allowedLocations", [])
    if (
        catalog_metadata["type"] != "INTERNAL"
        or catalog_metadata["storageConfigInfo"]["storageType"] != "FILE"
        or configured.scheme != "file"
        or configured.netloc
        or Path(unquote(configured.path)).resolve() != root.resolve()
        or root.as_uri() + "/" not in [entry.rstrip("/") + "/" for entry in allowed]
        or any(parent.is_symlink() for parent in [root, *root.parents])
    ):
        raise RuntimeError("The heliophysics catalog is not the expected local FILE sandbox.")
    raw_root = root.joinpath(*NAMESPACE, RAW_NAME)
    if any(parent.is_symlink() for parent in [raw_root, *raw_root.parents]):
        raise RuntimeError("Refusing a symlink in the Raw sample destination.")
    for name, content in [("ace_2020-01-01.csv", payload), ("hapi_metadata.json", metadata)]:
        target = raw_root / name
        if verify_only:
            if target.is_symlink() or target.read_bytes() != content:
                raise RuntimeError("The retained Raw copy differs from its original source.")
        else:
            preserve_file(target, content)
    raw = {
        "name": RAW_NAME,
        "format": "raw",
        "base-location": raw_root.as_uri(),
        "doc": (
            "Original NASA ACE/MAG HAPI CSV and native metadata; 2020-01-01 UTC. "
            "Catalog registration only, no Huron Raw revision is asserted."
        ),
        "properties": {
            "huron.dataset-type": "raw",
            "huron.layer": "bronze",
            "source.dataset": "AC_H0_MFI",
            "source.url": ACE_SAMPLE["url"],
            "source.title": ACE_SAMPLE["title"],
            "source.sha256": DATA_HASH,
        },
    }
    if not exists(f"{RAW_PATH}/{RAW_NAME}", token):
        if verify_only:
            raise RuntimeError("The Raw sample is not registered.")
        request(RAW_PATH, token=token, method="POST", data=raw)
    if request(f"{RAW_PATH}/{RAW_NAME}", token=token)["table"] != raw:
        raise RuntimeError("Existing Raw registration differs; refusing to replace it.")
    catalog = RestCatalog(
        CATALOG,
        uri=f"{BASE_URL}/api/catalog",
        warehouse=CATALOG,
        token=token,
        **{
            "oauth2-server-uri": f"{BASE_URL}/api/catalog/v1/oauth/tokens",
            "header.Polaris-Realm": REALM,
            "header.X-Iceberg-Access-Delegation": "",
            "py-io-impl": "pyiceberg.io.pyarrow.PyArrowFileIO",
        },
    )
    receipt = seed_iceberg(catalog, root, arrow, schema, verify_only=verify_only)
    return {"raw": raw, "iceberg": receipt, "sourceBytes": len(payload) + len(metadata)}


def main() -> None:
    """Serialize local runs and save receipts after both registrations and values are verified."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    with (STATE / "catalog-types.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        receipt = run(verify_only=args.verify_only)
        if not args.verify_only:
            save(STATE / "catalog-types-samples.json", receipt)
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
