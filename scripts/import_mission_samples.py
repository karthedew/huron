"""Convert bounded NASA mission science CSV responses into verified local Icechunk Zarr.

Run with .local/polaris/icechunk-venv/bin/python scripts/import_mission_samples.py.
Source CSV and metadata bytes are retained with SHA-256 hashes; retries reuse the snapshot.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import fcntl
import hashlib
import inspect
import io
import json
import math
import os
import re
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

import icechunk
import numpy as np
import zarr
from import_nasa_samples import register, summarize
from polaris_dev import obtain_token, save

STATE = Path(__file__).resolve().parents[1] / ".local" / "polaris"
MAX_SOURCE_BYTES = 25 * 1024 * 1024
MAX_OBSERVATIONS = 100_000
ACE_PARAMETERS = ["Time", "Magnitude", "BGSEc", "BGSM", "dBrms"]
ACE_QUERY = {
    "id": "AC_H0_MFI",
    "parameters": ",".join(ACE_PARAMETERS),
    "time.min": "2020-01-01T00:00:00Z",
    "time.max": "2020-01-02T00:00:00Z",
    "format": "csv",
}
ACE_SAMPLE = {
    "catalog": "heliophysics",
    "namespace": ["solar_wind", "ace"],
    "table": "ace_magnetic_field",
    "title": "NASA ACE/MAG Level 2 magnetic field · 1 January 2020",
    "url": "https://cdaweb.gsfc.nasa.gov/hapi/data?" + urlencode(ACE_QUERY),
    "metadata_url": "https://cdaweb.gsfc.nasa.gov/hapi/info?id=AC_H0_MFI",
    "documentation": "https://cdaweb.gsfc.nasa.gov/misc/NotesA.html#AC_H0_MFI",
    "distribution": "https://spase-metadata.org/NASA/NumericalData/ACE/MAG/L2/PT16S",
    "selection": {
        "start": ACE_QUERY["time.min"],
        "stop": ACE_QUERY["time.max"],
        "parameters": ACE_PARAMETERS,
    },
    "doi": "https://doi.org/10.48322/e0dc-0h53",
    "acknowledgement": "ACE/MAG instrument team, ACE Science Center, and CDAWeb team at GSFC/SPDF",
    "source_format": "NASA CDAWeb HAPI CSV",
    "conversion": "CSV numeric values and exact UTC timestamps converted to Zarr; no resampling.",
}

ArrayMap = dict[str, tuple[np.ndarray, dict]]
MissionParser = Callable[[dict, bytes], ArrayMap]


def _utc_nanoseconds(value: str) -> int:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z", value):
        raise RuntimeError("Source timestamp is not an exact UTC ISO timestamp.")
    result = np.datetime64(value[:-1], "ns")
    if np.isnat(result):
        raise RuntimeError("Source timestamp is invalid.")
    return int(result.astype("int64"))


def parse_ace_csv(metadata: dict, payload: bytes) -> ArrayMap:
    """Decode the selected ACE/MAG HAPI fields without changing sampling or missing values.

    Args:
        metadata: Native NASA HAPI info response.
        payload: Native CSV response for the configured observation interval.

    Returns:
        Scalar and vector science arrays, an exact UTC time coordinate and component labels.

    Raises:
        RuntimeError: Source metadata, values or timestamps differ from the selected contract.
    """
    if metadata.get("status", {}).get("code") != 1200:
        raise RuntimeError("NASA HAPI metadata does not report a successful request.")
    parameters = {parameter["name"]: parameter for parameter in metadata["parameters"]}
    if parameters["Time"]["type"] != "isotime" or parameters["Time"]["units"] != "UTC":
        raise RuntimeError("ACE source time metadata changed.")
    for name in ACE_PARAMETERS[1:]:
        parameter = parameters[name]
        expected_size = [3] if name in {"BGSEc", "BGSM"} else []
        if (
            parameter["type"] != "double"
            or parameter["units"] != "nT"
            or parameter.get("size", []) != expected_size
        ):
            raise RuntimeError(f"ACE source parameter metadata changed: {name}")
    rows = list(csv.reader(io.StringIO(payload.decode("utf-8"))))
    if not rows or len(rows) > MAX_OBSERVATIONS or any(len(row) != 9 for row in rows):
        raise RuntimeError("ACE source contains empty, oversized or malformed observations.")
    times = np.array([_utc_nanoseconds(row[0]) for row in rows], dtype="int64")
    start = _utc_nanoseconds(ACE_SAMPLE["selection"]["start"])
    stop = _utc_nanoseconds(ACE_SAMPLE["selection"]["stop"])
    if not ((times >= start) & (times < stop)).all() or not (np.diff(times) > 0).all():
        raise RuntimeError("ACE timestamps are not increasing within the requested interval.")
    numeric = np.asarray([row[1:] for row in rows], dtype="float64")
    if not np.isfinite(numeric).all():
        raise RuntimeError("ACE CSV contains unexpected nonfinite values.")
    arrays: ArrayMap = {
        "time": (
            times,
            {
                "_ARRAY_DIMENSIONS": ["time"],
                "units": "nanoseconds since 1970-01-01T00:00:00Z",
                "calendar": "proleptic_gregorian",
                "standard_name": "time",
                "source_parameter": "Time",
                "description": "Exact source UTC timestamps encoded as Unix nanoseconds.",
            },
        ),
        "component": (
            np.arange(3, dtype="int8"),
            {
                "_ARRAY_DIMENSIONS": ["component"],
                "units": "1",
                "labels": ["x", "y", "z"],
                "description": "Cartesian component index; coordinate frame is on the vector.",
            },
        ),
    }
    offset = 0
    for name in ACE_PARAMETERS[1:]:
        parameter = parameters[name]
        width = math.prod(parameter.get("size", [1]))
        values = numeric[:, offset : offset + width]
        if width == 1:
            values = values[:, 0]
        attrs = {
            "_ARRAY_DIMENSIONS": ["time", "component"] if width > 1 else ["time"],
            "source_parameter": name,
            "description": parameter["description"],
            "units": parameter["units"],
            "_FillValue": float(parameter["fill"]),
        }
        if width > 1:
            attrs["coordinate_system"] = "GSE" if name == "BGSEc" else "GSM"
            attrs["component_labels"] = ["x", "y", "z"]
        summarize(values, attrs)
        arrays[name] = (np.ascontiguousarray(values), attrs)
        offset += width
    return arrays


def download_source(url: str) -> bytes:
    """Fetch one bounded public source response.

    Args:
        url: Official source data or metadata URL.

    Returns:
        Complete response bytes.

    Raises:
        RuntimeError: The response is empty or exceeds the source byte budget.
    """
    with urlopen(url, timeout=60) as response:
        payload = response.read(MAX_SOURCE_BYTES + 1)
    if not payload or len(payload) > MAX_SOURCE_BYTES:
        raise RuntimeError("Source response is empty or exceeds the bounded mission import limit.")
    return payload


def _retain_source(sample: dict, name: str, url: str, payload: bytes) -> dict:
    digest = hashlib.sha256(payload).hexdigest()
    directory = STATE / "source-files" / sample["catalog"] / sample["table"]
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{digest}-{name}"
    if path.exists():
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RuntimeError(
                "Retained source response was changed; refusing to replace provenance."
            )
    else:
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as output:
            temporary = Path(output.name)
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        try:
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    return {"url": url, "bytes": len(payload), "sha256": digest, "local_file": str(path)}


async def _has_keys(store: icechunk.IcechunkStore) -> bool:
    iterator = store.list()
    try:
        async for _ in iterator:
            return True
        return False
    finally:
        await iterator.aclose()


def _source_payload(item: dict) -> bytes:
    path = Path(item["local_file"])
    if not path.is_file():
        raise RuntimeError("Retained mission source bytes do not match their recorded checksum.")
    payload = path.read_bytes()
    if len(payload) != item["bytes"] or hashlib.sha256(payload).hexdigest() != item["sha256"]:
        raise RuntimeError("Retained mission source bytes do not match their recorded checksum.")
    return payload


def _verify(sample: dict, group: zarr.Group, parser: MissionParser) -> dict:
    if (
        group.attrs.get("source_url") != sample["url"]
        or group.attrs.get("source_selection") != sample["selection"]
    ):
        raise RuntimeError(
            "Existing mission sample has different provenance; refusing to overwrite."
        )
    receipt = dict(group.attrs["import_receipt"])
    if (
        receipt["catalog"] != sample["catalog"]
        or receipt["namespace"] != sample["namespace"]
        or receipt["table"] != sample["table"]
        or receipt["source"] != sample["url"]
        or receipt["selection"] != sample["selection"]
        or set(receipt["arrays"]) != set(group.array_keys())
        or receipt["source_objects"]["metadata"]["url"] != sample["metadata_url"]
        or receipt["source_objects"]["data"]["url"] != sample["url"]
    ):
        raise RuntimeError("Existing mission receipt has different or incomplete scientific data.")
    sources = {}
    for name, item in receipt["source_objects"].items():
        sources[name] = _source_payload(item)
    reference = parser(json.loads(sources["metadata"]), sources["data"])
    if set(reference) != set(receipt["arrays"]):
        raise RuntimeError("Persisted mission arrays do not match the retained source columns.")
    for name, expected in receipt["arrays"].items():
        array = group[name]
        values = array[:]
        attrs = dict(array.attrs)
        if (
            hashlib.sha256(values.tobytes()).hexdigest() != expected["sha256"]
            or attrs != expected["attributes"]
            or attrs != reference[name][1]
            or not np.array_equal(values, reference[name][0], equal_nan=True)
            or list(array.metadata.dimension_names) != attrs["_ARRAY_DIMENSIONS"]
        ):
            raise RuntimeError(f"Persisted mission values or scientific metadata mismatch: {name}")
        summary = summarize(values, attrs)
        if any(summary[key] != expected[key] for key in summary):
            raise RuntimeError(f"Persisted mission summary mismatch: {name}")
    return receipt


def import_mission_sample(
    sample: dict, parser: MissionParser, token: str, *, repair_metadata: bool = False
) -> dict:
    """Persist and register scientific arrays, retaining exact source bytes and snapshot identity.

    Args:
        sample: Mission source URLs, selected interval and catalog destination.
        parser: Decoder of the official metadata and CSV response into scientific arrays.
        token: Trusted Polaris administrator token.
        repair_metadata: Explicitly correct TSIS scientific metadata without changing array values.

    Returns:
        Provenance receipt pinning verified storage and source responses.

    Raises:
        RuntimeError: Metadata repair is requested for an unsupported sample.
    """
    if repair_metadata and (
        sample["catalog"] != "international_space_station"
        or sample["namespace"] != ["instruments", "tsis_1"]
        or sample["table"] != "total_solar_irradiance"
    ):
        raise RuntimeError("Metadata repair is restricted to the ISS TSIS scientific sample.")
    location = (
        STATE / "nasa-storage" / sample["catalog"] / Path(*sample["namespace"]) / sample["table"]
    )
    location.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        location.parent / f".{location.name}.import.lock", os.O_RDWR | os.O_CREAT, 0o600
    )
    with os.fdopen(descriptor, "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            return _import_mission_sample(sample, parser, token, location, repair_metadata)
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _code_identity(parser: MissionParser) -> dict:
    parser_path = inspect.getsourcefile(parser)
    identity = {Path(__file__).name: hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    if parser_path:
        identity[Path(parser_path).name] = hashlib.sha256(
            Path(parser_path).read_bytes()
        ).hexdigest()
    return identity


def _source_context(sample: dict) -> dict:
    return {
        key: sample[key]
        for key in [
            "doi",
            "mission",
            "source_version",
            "processing_level",
            "rights",
            "acknowledgement",
            "caveats",
            "native_attributes_url",
            "hapi_metadata_url",
            "rights_url",
            "citation_url",
            "collection_metadata",
        ]
        if key in sample
    }


def _repair_metadata(
    sample: dict, parser: MissionParser, repo: icechunk.Repository, snapshot: str, group: zarr.Group
) -> tuple[dict, str]:
    if (
        group.attrs.get("source_url") != sample["url"]
        or group.attrs.get("source_selection") != sample["selection"]
    ):
        raise RuntimeError("Existing sample differs from the requested metadata repair.")
    original = dict(group.attrs["import_receipt"])
    if (
        original["catalog"] != sample["catalog"]
        or original["namespace"] != sample["namespace"]
        or original["table"] != sample["table"]
        or original["selection"] != sample["selection"]
        or original["source"] != sample["url"]
    ):
        raise RuntimeError("Existing receipt differs from the requested metadata repair.")
    if original["source_objects"]["metadata"]["url"] == sample["metadata_url"]:
        try:
            return _verify(sample, group, parser), snapshot
        except RuntimeError:
            pass
    data = original["source_objects"]["data"]
    for item in original["source_objects"].values():
        _source_payload(item)
    payload = _source_payload(data)
    if data["url"] != sample["url"]:
        raise RuntimeError("Original TSIS source bytes changed; metadata repair is refused.")
    metadata_bytes = download_source(sample["metadata_url"])
    metadata = json.loads(metadata_bytes)
    arrays = parser(metadata, payload)
    if set(arrays) != set(group.array_keys()) or set(arrays) != set(original["arrays"]):
        raise RuntimeError("TSIS array set changed; metadata repair is refused.")
    summaries = {}
    for name, (reference, attrs) in arrays.items():
        values = group[name][:]
        if values.dtype != reference.dtype or not np.array_equal(values, reference, equal_nan=True):
            raise RuntimeError(f"TSIS values changed; metadata repair is refused: {name}")
        if hashlib.sha256(values.tobytes()).hexdigest() != original["arrays"][name]["sha256"]:
            raise RuntimeError(f"TSIS values differ from the original receipt: {name}")
        summaries[name] = {
            **summarize(values, attrs),
            "sha256": original["arrays"][name]["sha256"],
            "attributes": attrs,
        }
    new_source = _retain_source(sample, "metadata.json", sample["metadata_url"], metadata_bytes)
    objects = {**original["source_objects"], "metadata": new_source}
    if original["source_objects"]["metadata"] != new_source:
        objects["previous_metadata"] = original["source_objects"]["metadata"]
    receipt = {
        **original,
        "arrays": summaries,
        "source_objects": objects,
        "source_context": _source_context(sample),
        "conversion": sample["conversion"],
        "conversion_code": _code_identity(parser),
        "downloaded_bytes": sum(item["bytes"] for item in objects.values()),
        "metadata_repair": {
            "parent_snapshot": snapshot,
            "repaired_at": datetime.now(UTC).isoformat(),
            "reason": "Apply native LISIRD missing-value metadata; retain original values.",
        },
    }
    session = repo.writable_session("main")
    if session.snapshot_id != snapshot or repo.lookup_branch("main") != snapshot:
        raise RuntimeError("TSIS branch changed while preparing metadata repair; retry.")
    writable = zarr.open_group(store=session.store, mode="a")
    for name, (_, attrs) in arrays.items():
        writable[name].attrs.clear()
        writable[name].attrs.update(attrs)
    writable.attrs.update(
        {
            "source_metadata": metadata,
            "source_context": receipt["source_context"],
            "conversion": sample["conversion"],
            "import_receipt": receipt,
        }
    )
    repaired = session.commit(
        "Correct TSIS native missing-value metadata, preserving all values", rebase_tries=0
    )
    verified = _verify(
        sample,
        zarr.open_group(store=repo.readonly_session(snapshot_id=repaired).store, mode="r"),
        parser,
    )
    return verified, repaired


def _import_mission_sample(
    sample: dict, parser: MissionParser, token: str, location: Path, repair_metadata: bool
) -> dict:
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
            if repair_metadata:
                receipt, snapshot = _repair_metadata(sample, parser, repo, snapshot, group)
            else:
                receipt = _verify(sample, group, parser)
    if repair_metadata and receipt is None:
        raise RuntimeError("Metadata repair requires an existing populated TSIS sample.")
    if receipt is None:
        metadata_bytes = download_source(sample["metadata_url"])
        payload = download_source(sample["url"])
        metadata = json.loads(metadata_bytes)
        arrays = parser(metadata, payload)
        if not arrays:
            raise RuntimeError("Mission parser returned no scientific arrays.")
        source_objects = {
            "metadata": _retain_source(
                sample, "metadata.json", sample["metadata_url"], metadata_bytes
            ),
            "data": _retain_source(sample, "data.csv", sample["url"], payload),
        }
        summaries = {
            name: {
                **summarize(values, attrs),
                "sha256": hashlib.sha256(values.tobytes()).hexdigest(),
                "attributes": attrs,
            }
            for name, (values, attrs) in arrays.items()
        }
        context = _source_context(sample)
        code_identity = _code_identity(parser)
        receipt = {
            "catalog": sample["catalog"],
            "namespace": sample["namespace"],
            "table": sample["table"],
            "source": sample["url"],
            "documentation": sample["documentation"],
            "selection": sample["selection"],
            "source_format": sample["source_format"],
            "conversion": sample["conversion"],
            "conversion_code": code_identity,
            "source_context": context,
            "source_objects": source_objects,
            "downloaded_bytes": len(metadata_bytes) + len(payload),
            "arrays": summaries,
            "imported_at": datetime.now(UTC).isoformat(),
        }
        if repo is None:
            location.mkdir(parents=True, exist_ok=True)
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
                "source_metadata": metadata,
                "source_format": sample["source_format"],
                "conversion": sample["conversion"],
                "source_context": context,
                "doi": sample.get("doi", ""),
                "acknowledgement": sample.get("acknowledgement", ""),
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
        snapshot = session.commit(
            "Import NASA mission science observations from retained CSV sources"
        )
        receipt = _verify(
            sample,
            zarr.open_group(store=repo.readonly_session(snapshot_id=snapshot).store, mode="r"),
            parser,
        )
    receipt["snapshot"] = snapshot
    receipt["location"] = location.as_uri()
    register(sample, location, token)
    print(
        f"Verified {sample['catalog']}.{'.'.join(sample['namespace'])}.{sample['table']}: "
        f"{snapshot}"
    )
    return receipt


def main() -> None:
    """Import the requested heliophysics and ISS mission samples into the local catalogs."""
    from iss_tsis_sample import TSIS_SAMPLE, parse_tsis_csv

    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument("--dataset", choices=["all", "ace", "tsis"], default="all")
    arguments.add_argument(
        "--repair-metadata",
        action="store_true",
        help="Commit a TSIS metadata-only correction while preserving the prior snapshot.",
    )
    options = arguments.parse_args()
    selected = options.dataset
    if options.repair_metadata and selected != "tsis":
        arguments.error("--repair-metadata requires --dataset tsis.")
    credentials = json.loads((STATE / "credentials.json").read_text())
    token = obtain_token(credentials["admin"])
    receipts = []
    if selected in {"all", "ace"}:
        receipts.append(import_mission_sample(ACE_SAMPLE, parse_ace_csv, token))
    if selected in {"all", "tsis"}:
        receipts.append(
            import_mission_sample(
                TSIS_SAMPLE, parse_tsis_csv, token, repair_metadata=options.repair_metadata
            )
        )
    save(STATE / "mission-samples.json", receipts)


if __name__ == "__main__":
    main()
