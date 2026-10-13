"""Import bounded public NASA Zarr samples into the local Polaris Icechunk sandbox.

Run with .local/polaris/icechunk-venv/bin/python scripts/import_nasa_samples.py.
Existing snapshots are verified and reused; registered data is never overwritten.
"""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import itertools
import json
import math
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import urlopen

import icechunk
import numpy as np
import zarr
from numcodecs import get_codec
from polaris_dev import exists, obtain_token, request, save

STATE = Path(__file__).resolve().parents[1] / ".local" / "polaris"
MAX_OBJECT_BYTES = 100 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024
SAMPLES = (
    {
        "catalog": "geoscience",
        "catalog_title": "NASA geoscience · Earth oceans and energy",
        "namespace": ["earth", "ocean"],
        "table": "mur_sst_sample",
        "title": "NASA JPL MUR sea surface temperature · North Atlantic sample",
        "url": "https://mur-sst.s3.us-west-2.amazonaws.com/zarr-v1",
        "documentation": "https://podaac.jpl.nasa.gov/dataset/MUR-JPL-L4-GLOB-v4.1",
        "distribution": "https://registry.opendata.aws/mur/",
        "variables": ["analysed_sst", "analysis_error"],
        "selection": {"time": [0, 2], "lat": [12000, 12128], "lon": [11000, 11128]},
    },
    {
        "catalog": "geoscience",
        "catalog_title": "NASA geoscience · Earth oceans and energy",
        "namespace": ["earth", "energy"],
        "table": "power_solar_sample",
        "title": "NASA POWER monthly solar and thermal irradiance · North America sample",
        "url": "https://nasa-power.s3.us-west-2.amazonaws.com/syn1deg/temporal/power_syn1deg_monthly_temporal_lst.zarr",
        "documentation": "https://power.larc.nasa.gov/docs/tutorials/service-data-request/aws/",
        "distribution": "https://registry.opendata.aws/nasa-power/",
        "variables": ["ALLSKY_SFC_SW_DWN", "ALLSKY_SFC_LW_DWN"],
        "selection": {"time": [228, 240], "lat": [110, 126], "lon": [95, 111]},
    },
)


class PublicZarrSample:
    """Read only intersecting Zarr v2 chunks, recording downloaded object hashes."""

    def __init__(self, root: str):
        """Load consolidated source metadata and initialize bounded provenance tracking.

        Args:
            root: Public Zarr v2 store URL.
        """
        self.root = root
        self.downloaded_bytes = 0
        self.objects: dict[str, dict[str, object]] = {}
        self.metadata = json.loads(self.download(".zmetadata"))["metadata"]

    def download(self, path: str, *, missing_ok: bool = False) -> bytes | None:
        """Fetch a bounded object, recording its checksum or an absent chunk.

        Args:
            path: Object key relative to the source store.
            missing_ok: Whether an absent object is an uninitialized Zarr chunk.

        Returns:
            Object bytes, or None for an explicitly permitted absent chunk.
        """
        remaining = MAX_DOWNLOAD_BYTES - self.downloaded_bytes
        if remaining <= 0:
            raise RuntimeError("Import exceeds bounded total download limit.")
        try:
            with urlopen(f"{self.root}/{path}", timeout=60) as response:
                data = response.read(min(MAX_OBJECT_BYTES, remaining) + 1)
        except (HTTPError, URLError) as error:
            missing = (isinstance(error, HTTPError) and error.code == 404) or (
                isinstance(error, URLError) and isinstance(error.reason, FileNotFoundError)
            )
            if not missing_ok or not missing:
                raise
            self.objects[path] = {"missing": True}
            return None
        if len(data) > MAX_OBJECT_BYTES:
            raise RuntimeError(f"Source object exceeds bounded import limit: {path}")
        self.downloaded_bytes += len(data)
        if self.downloaded_bytes > MAX_DOWNLOAD_BYTES:
            raise RuntimeError("Import exceeds bounded total download limit.")
        self.objects[path] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        return data

    def array(self, name: str, selection: dict[str, list[int]]) -> tuple[np.ndarray, dict]:
        """Decode only chunks intersecting a selection, preserving packed values and metadata.

        Args:
            name: Source variable or coordinate name.
            selection: Half-open source index bounds for every dimension.

        Returns:
            Selected values and their original scientific attributes.
        """
        spec = self.metadata[f"{name}/.zarray"]
        attrs = self.metadata[f"{name}/.zattrs"].copy()
        dimensions = attrs["_ARRAY_DIMENSIONS"]
        bounds = [selection[dimension] for dimension in dimensions]
        if spec["zarr_format"] != 2 or spec["order"] != "C":
            raise RuntimeError("This sample reader requires C-order Zarr v2 arrays.")
        if any(
            start < 0 or end <= start or end > size
            for (start, end), size in zip(bounds, spec["shape"], strict=True)
        ):
            raise RuntimeError(f"Source dimensions changed; review selection for {name}.")
        chunks = tuple(spec["chunks"])
        dtype = np.dtype(spec["dtype"])
        shape = tuple(end - start for start, end in bounds)
        if dtype.kind not in "iuf" or any(chunk <= 0 for chunk in chunks):
            raise RuntimeError("This sample reader requires numeric arrays with positive chunks.")
        if math.prod(shape) * dtype.itemsize > MAX_OBJECT_BYTES:
            raise RuntimeError(f"Selected array exceeds bounded output limit: {name}")
        if math.prod(chunks) * dtype.itemsize > MAX_OBJECT_BYTES:
            raise RuntimeError(f"Decoded chunk exceeds bounded output limit: {name}")
        fill = spec["fill_value"]
        if isinstance(fill, str) and fill in {"NaN", "Infinity", "-Infinity"}:
            fill = {"NaN": np.nan, "Infinity": np.inf, "-Infinity": -np.inf}[fill]
        output = np.empty(shape, dtype=dtype)
        indices = [
            range(start // chunk, (end - 1) // chunk + 1)
            for (start, end), chunk in zip(bounds, chunks, strict=True)
        ]
        for index in itertools.product(*indices):
            key = spec.get("dimension_separator", ".").join(map(str, index))
            decoded = self.download(f"{name}/{key}", missing_ok=True)
            if decoded is None:
                if fill is None:
                    raise RuntimeError(f"Absent chunk has undefined fill value: {name}/{key}")
                values = np.full(chunks, fill, dtype=dtype)
            else:
                if spec["compressor"]:
                    decoded = get_codec(spec["compressor"]).decode(decoded)
                for codec in reversed(spec["filters"] or []):
                    decoded = get_codec(codec).decode(decoded)
                values = np.frombuffer(decoded, dtype=dtype)
                if values.size != math.prod(chunks):
                    raise RuntimeError(f"Invalid decoded chunk size for {name}/{key}")
                values = values.reshape(chunks)
            starts = [
                max(start, i * chunk)
                for (start, _), i, chunk in zip(bounds, index, chunks, strict=True)
            ]
            ends = [
                min(end, (i + 1) * chunk)
                for (_, end), i, chunk in zip(bounds, index, chunks, strict=True)
            ]
            source = tuple(
                slice(start - i * chunk, end - i * chunk)
                for start, end, i, chunk in zip(starts, ends, index, chunks, strict=True)
            )
            target = tuple(
                slice(start - bound[0], end - bound[0])
                for start, end, bound in zip(starts, ends, bounds, strict=True)
            )
            output[target] = values[source]
        if fill is not None and np.isfinite(fill):
            attrs.setdefault("_FillValue", fill)
        return output, attrs


def summarize(values: np.ndarray, attrs: dict) -> dict:
    """Summarize valid observations after masking packed missing values and unpacking.

    Args:
        values: Packed values copied from the source array.
        attrs: Source CF attributes, including validity and packing information.

    Returns:
        Shape, dtype, valid observation count, physical range and units.
    """
    valid = np.isfinite(values)
    if "_FillValue" in attrs:
        valid &= values != attrs["_FillValue"]
    if "missing_value" in attrs:
        valid &= ~np.isin(values, np.atleast_1d(attrs["missing_value"]))
    if "valid_range" in attrs:
        lower, upper = attrs["valid_range"]
        valid &= (values >= lower) & (values <= upper)
    else:
        if "valid_min" in attrs:
            valid &= values >= attrs["valid_min"]
        if "valid_max" in attrs:
            valid &= values <= attrs["valid_max"]
    if not valid.any():
        raise RuntimeError("Selected sample contains no valid scientific observations.")
    physical = values[valid].astype("float64") * attrs.get("scale_factor", 1) + attrs.get(
        "add_offset", 0
    )
    if not np.isfinite(physical).all():
        raise RuntimeError("Source packing metadata produces nonfinite scientific observations.")
    return {
        "shape": list(values.shape),
        "dtype": str(values.dtype),
        "valid_values": int(valid.sum()),
        "minimum": float(physical.min()),
        "maximum": float(physical.max()),
        "units": attrs.get("units"),
    }


def register(sample: dict, location: Path, token: str) -> None:
    """Register verified storage without replacing a catalog or table at another location.

    Args:
        sample: Named source, selection and catalog destination.
        location: Local immutable repository location.
        token: Trusted Polaris administrator token.
    """
    catalog = sample["catalog"]
    catalog_path = f"/api/management/v1/catalogs/{catalog}"
    levels = sample.get("namespace", ["examples"])
    encoded_namespace = quote("\x1f".join(levels), safe="")
    base = location.parents[len(levels)].as_uri()
    if not exists(catalog_path, token):
        request(
            "/api/management/v1/catalogs",
            token=token,
            method="POST",
            data={
                "catalog": {
                    "name": catalog,
                    "type": "INTERNAL",
                    "readOnly": False,
                    "properties": {
                        "default-base-location": base,
                        "description": sample.get("catalog_title", sample["title"]),
                        "polaris.config.allow.client-specified.table.location": "true",
                    },
                    "storageConfigInfo": {"storageType": "FILE", "allowedLocations": [base]},
                }
            },
        )
    else:
        configured = request(catalog_path, token=token)
        if configured["storageConfigInfo"]["storageType"] != "FILE" or base not in configured[
            "storageConfigInfo"
        ].get("allowedLocations", []):
            raise RuntimeError(
                f"Existing catalog {catalog} has different storage; refusing to adopt it."
            )
    table = (
        f"/api/catalog/polaris/v1/{catalog}/namespaces/{encoded_namespace}"
        f"/icechunk-tables/{sample['table']}"
    )
    registered = exists(table, token)
    if registered:
        loaded = request(table, token=token)
        if loaded["table"]["location"].rstrip("/") != location.as_uri().rstrip("/"):
            raise RuntimeError(
                "Registered repository has a different location; refusing to replace it."
            )
    # Native catalog_admin grants management but needs an explicit data privilege.
    request(
        f"{catalog_path}/catalog-roles/catalog_admin/grants",
        token=token,
        method="PUT",
        data={"grant": {"type": "catalog", "privilege": "CATALOG_MANAGE_CONTENT"}},
    )
    request(
        f"/api/management/v1/principal-roles/service_admin/catalog-roles/{catalog}",
        token=token,
        method="PUT",
        data={"catalogRole": {"name": "catalog_admin"}},
    )
    for depth in range(1, len(levels) + 1):
        current = levels[:depth]
        namespace_path = (
            f"/api/catalog/v1/{catalog}/namespaces/{quote(chr(31).join(current), safe='')}"
        )
        if not exists(namespace_path, token):
            request(
                f"/api/catalog/v1/{catalog}/namespaces",
                token=token,
                method="POST",
                data={
                    "namespace": current,
                    "properties": {"description": "Public mission data stored as Zarr in Icechunk"},
                },
            )
    if not registered:
        request(
            table.rsplit("/", 1)[0],
            token=token,
            method="POST",
            data={
                "name": sample["table"],
                "location": location.as_uri(),
                "properties": {
                    "description": sample["title"],
                    "source": sample["url"],
                    "source-documentation": sample["documentation"],
                    "sample": "true",
                    "source-selection": json.dumps(sample["selection"]),
                },
            },
        )
    loaded = request(table, token=token)
    if loaded["table"]["location"].rstrip("/") != location.as_uri().rstrip("/"):
        raise RuntimeError(
            "Registered repository has a different location; refusing to replace it."
        )
    request(table + "/credentials?access-mode=read", token=token, expected=200)
    request(table + "/credentials?access-mode=read-write", token=token, expected=200)


async def _has_keys(store: icechunk.IcechunkStore) -> bool:
    iterator = store.list()
    try:
        async for _ in iterator:
            return True
        return False
    finally:
        await iterator.aclose()


def _verify(sample: dict, group: zarr.Group) -> dict:
    if (
        group.attrs.get("source_url") != sample["url"]
        or group.attrs.get("source_selection") != sample["selection"]
    ):
        raise RuntimeError("Existing sample has different provenance; refusing to overwrite it.")
    receipt = dict(group.attrs["import_receipt"])
    expected_names = {*sample["variables"], "time", "lat", "lon"}
    if set(receipt["arrays"]) != expected_names or set(group.array_keys()) != expected_names:
        raise RuntimeError("Existing sample has incomplete or different variables.")
    if (
        receipt["catalog"] != sample["catalog"]
        or receipt["namespace"] != sample.get("namespace", ["examples"])
        or receipt["table"] != sample["table"]
        or receipt["source"] != sample["url"]
        or receipt["selection"] != sample["selection"]
    ):
        raise RuntimeError("Existing import receipt has different provenance.")
    for name, expected in receipt["arrays"].items():
        array = group[name]
        values = array[:]
        actual = hashlib.sha256(values.tobytes()).hexdigest()
        if actual != expected["sha256"]:
            raise RuntimeError(f"Persisted array checksum mismatch: {name}")
        attrs = dict(array.attrs)
        if "attributes" in expected and attrs != expected["attributes"]:
            raise RuntimeError(f"Persisted scientific metadata mismatch: {name}")
        summary = summarize(values, attrs)
        if any(summary[key] != expected[key] for key in summary):
            raise RuntimeError(f"Persisted scientific summary mismatch: {name}")
        shape = [
            sample["selection"][dimension][1] - sample["selection"][dimension][0]
            for dimension in attrs["_ARRAY_DIMENSIONS"]
        ]
        if list(values.shape) != shape:
            raise RuntimeError(f"Persisted array dimensions mismatch: {name}")
    return receipt


def import_sample(sample: dict, token: str) -> dict:
    """Import a bounded sample, or verify and register the same existing snapshot.

    Args:
        sample: Public source variables, exact selection and destination identity.
        token: Trusted Polaris administrator token.

    Returns:
        Receipt pinning the verified snapshot, source objects and local location.
    """
    location = (
        STATE
        / "nasa-storage"
        / sample["catalog"]
        / Path(*sample.get("namespace", ["examples"]))
        / sample["table"]
    )
    location.parent.mkdir(parents=True, exist_ok=True)
    lock = location.parent / f".{location.name}.import.lock"
    descriptor = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(descriptor, "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            return _import_sample(sample, token)
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _import_sample(sample: dict, token: str) -> dict:
    location = (
        STATE
        / "nasa-storage"
        / sample["catalog"]
        / Path(*sample.get("namespace", ["examples"]))
        / sample["table"]
    )
    storage = icechunk.local_filesystem_storage(str(location))
    repo = None
    receipt = None
    snapshot = None
    if icechunk.Repository.exists(storage):
        repo = icechunk.Repository.open(storage)
        snapshot = repo.lookup_branch("main")
        store = repo.readonly_session(snapshot_id=snapshot).store
        if asyncio.run(_has_keys(store)):
            group = zarr.open_group(store=store, mode="r")
            receipt = _verify(sample, group)
    if receipt is None:
        source = PublicZarrSample(sample["url"])
        arrays = {}
        summaries = {}
        for name in [*sample["variables"], "time", "lat", "lon"]:
            values, attrs = source.array(name, sample["selection"])
            arrays[name] = (values, attrs)
            summaries[name] = {
                **summarize(values, attrs),
                "sha256": hashlib.sha256(values.tobytes()).hexdigest(),
                "attributes": attrs,
            }
        receipt = {
            "catalog": sample["catalog"],
            "namespace": sample.get("namespace", ["examples"]),
            "table": sample["table"],
            "source": sample["url"],
            "documentation": sample["documentation"],
            "selection": sample["selection"],
            "downloaded_bytes": source.downloaded_bytes,
            "source_objects": source.objects,
            "arrays": summaries,
            "imported_at": datetime.now(UTC).isoformat(),
        }
        location.mkdir(parents=True, exist_ok=True)
        if repo is None:
            repo = icechunk.Repository.create(storage)
        session = repo.writable_session("main")
        group = zarr.group(store=session.store)
        group.attrs.update(
            {
                "description": sample["title"],
                "source_url": sample["url"],
                "source_documentation": sample["documentation"],
                "source_distribution": sample["distribution"],
                "source_selection": sample["selection"],
                "import_receipt": receipt,
            }
        )
        for name, (values, attrs) in arrays.items():
            group.create_array(
                name,
                data=values,
                chunks=values.shape,
                attributes=attrs,
                dimension_names=attrs["_ARRAY_DIMENSIONS"],
            )
        snapshot = session.commit("Import bounded NASA public Zarr sample with provenance")
        verified = zarr.open_group(
            store=repo.readonly_session(snapshot_id=snapshot).store, mode="r"
        )
        receipt = _verify(sample, verified)
    receipt["snapshot"] = snapshot
    receipt["location"] = location.as_uri()
    register(sample, location, token)
    print(
        f"Verified {sample['catalog']}.{'.'.join(sample.get('namespace', ['examples']))}."
        f"{sample['table']}: {receipt['snapshot']}; "
        f"downloaded {receipt['downloaded_bytes']:,} bytes"
    )
    return receipt


def main() -> None:
    """Import both named public NASA samples and save their verified receipts."""
    credentials = json.loads((STATE / "credentials.json").read_text())
    token = obtain_token(credentials["admin"])
    receipts = [import_sample(sample, token) for sample in SAMPLES]
    save(STATE / "nasa-samples.json", receipts)


if __name__ == "__main__":
    main()
