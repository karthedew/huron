"""Verify NASA sample decoding and immutable retry behavior without network services.

Run with .local/polaris/icechunk-venv/bin/python scripts/test_nasa_samples.py.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import icechunk
import import_nasa_samples as importer
import numpy as np
import zarr
from numcodecs import Blosc, FixedScaleOffset


def source_store(path: Path) -> dict:
    """Create an offline Zarr v2 source with NASA POWER's filter and compression.

    Args:
        path: Temporary source store directory.

    Returns:
        Complete named sample configuration with a file URL.
    """
    group = zarr.open_group(path, mode="w", zarr_format=2)
    values = (270 + np.arange(120, dtype="float32") / 8).reshape(4, 5, 6)
    group.create_array(
        "temperature",
        data=values,
        chunks=(2, 3, 4),
        filters=[FixedScaleOffset(offset=1000, scale=100, dtype="<f4", astype="<f4")],
        compressor=Blosc(cname="zstd", clevel=3, shuffle=Blosc.BITSHUFFLE),
        fill_value=np.nan,
        attributes={
            "_ARRAY_DIMENSIONS": ["time", "lat", "lon"],
            "units": "kelvin",
            "valid_min": 0,
            "valid_max": 500,
        },
    )
    for name, values in {
        "time": np.arange(4, dtype="int64"),
        "lat": np.linspace(-90, 90, 5),
        "lon": np.linspace(-180, 180, 6),
    }.items():
        group.create_array(
            name,
            data=values,
            chunks=values.shape,
            attributes={"_ARRAY_DIMENSIONS": [name]},
        )
    zarr.consolidate_metadata(path)
    return {
        "catalog": "offline_science",
        "table": "temperature",
        "title": "Offline scientific sample",
        "url": path.as_uri(),
        "documentation": "https://example.test/documentation",
        "distribution": "https://example.test/distribution",
        "variables": ["temperature"],
        "selection": {"time": [1, 4], "lat": [1, 5], "lon": [2, 6]},
    }


class NasaSampleTests(unittest.TestCase):
    """Exercise public source and import operations using real Zarr and Icechunk."""

    def test_filter_and_edge_decode_matches_standard_reader(self):
        """Decoded multi-chunk selections match the installed standard Zarr reader exactly."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "source"
            sample = source_store(path)
            reader = importer.PublicZarrSample(sample["url"])
            actual, attrs = reader.array("temperature", sample["selection"])
            expected = zarr.open_group(path, mode="r")["temperature"][1:4, 1:5, 2:6]
            np.testing.assert_array_equal(actual, expected)
            self.assertEqual(attrs["units"], "kelvin")
            self.assertEqual(len(reader.objects), 9)
            self.assertEqual(
                reader.downloaded_bytes, sum(item["bytes"] for item in reader.objects.values())
            )

    def test_missing_chunks_match_standard_reader(self):
        """Absent source chunks become fill values and are recorded as absent provenance."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "source"
            sample = source_store(path)
            (path / "temperature" / "0.0.0").unlink()
            reader = importer.PublicZarrSample(sample["url"])
            actual, _ = reader.array("temperature", sample["selection"])
            expected = zarr.open_group(path, mode="r")["temperature"][1:4, 1:5, 2:6]
            np.testing.assert_array_equal(actual, expected)
            self.assertEqual(reader.objects["temperature/0.0.0"], {"missing": True})

    def test_packed_mur_style_decode_matches_standard_reader(self):
        """Packed integer Blosc data retain raw values and CF temperature calibration."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "source"
            group = zarr.open_group(path, mode="w", zarr_format=2)
            values = np.array([-32768, -1000, 0, 1000, 2000], dtype="int16")
            group.create_array(
                "temperature",
                data=values,
                chunks=(3,),
                filters=None,
                compressor=Blosc(cname="lz4", clevel=5),
                fill_value=-32768,
                attributes={
                    "_ARRAY_DIMENSIONS": ["time"],
                    "scale_factor": 0.001,
                    "add_offset": 298.15,
                    "units": "kelvin",
                    "valid_min": -32767,
                },
            )
            zarr.consolidate_metadata(path)
            reader = importer.PublicZarrSample(path.as_uri())
            actual, attrs = reader.array("temperature", {"time": [0, 5]})
            np.testing.assert_array_equal(actual, group["temperature"][:])
            summary = importer.summarize(actual, attrs)
            self.assertEqual(summary["valid_values"], 4)
            self.assertAlmostEqual(summary["minimum"], 297.15)
            self.assertAlmostEqual(summary["maximum"], 300.15)

    def test_absent_chunk_with_undefined_fill_is_refused(self):
        """An absent chunk with null fill cannot fabricate deterministic observations."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "source"
            sample = source_store(path)
            metadata_path = path / ".zmetadata"
            metadata = json.loads(metadata_path.read_text())
            metadata["metadata"]["temperature/.zarray"]["fill_value"] = None
            metadata_path.write_text(json.dumps(metadata))
            (path / "temperature" / "0.0.0").unlink()
            reader = importer.PublicZarrSample(sample["url"])
            with self.assertRaisesRegex(RuntimeError, "undefined fill value"):
                reader.array("temperature", sample["selection"])

    def test_packed_cf_validity_precedes_scale_offset(self):
        """Mask packed missing and invalid values before computing physical statistics."""
        values = np.array([-32768, -999, -10, 0, 10, 200], dtype="int16")
        result = importer.summarize(
            values,
            {
                "_FillValue": -32768,
                "missing_value": [-999, 0],
                "valid_range": [-10, 10],
                "scale_factor": 0.5,
                "add_offset": 100,
                "units": "kelvin",
            },
        )
        self.assertEqual(result["valid_values"], 2)
        self.assertEqual(result["minimum"], 95)
        self.assertEqual(result["maximum"], 105)
        with self.assertRaisesRegex(RuntimeError, "no valid scientific"):
            importer.summarize(np.array([-999, np.nan]), {"missing_value": -999})

    def test_download_and_decoded_output_limits(self):
        """Byte budgets and declared uncompressed sizes stop imports before large allocations."""
        with tempfile.TemporaryDirectory() as temporary:
            sample = source_store(Path(temporary) / "source")
            reader = importer.PublicZarrSample(sample["url"])
            with patch.object(importer, "MAX_OBJECT_BYTES", 2):
                with self.assertRaisesRegex(RuntimeError, "Source object exceeds"):
                    reader.download("temperature/0.0.0")
                with self.assertRaisesRegex(RuntimeError, "bounded output limit"):
                    reader.array("temperature", sample["selection"])
            with (
                patch.object(importer, "MAX_DOWNLOAD_BYTES", reader.downloaded_bytes + 1),
                self.assertRaisesRegex(RuntimeError, "total download limit"),
            ):
                reader.download("temperature/0.0.0")

    def test_retry_after_registration_failure_reuses_committed_data(self):
        """A Polaris registration failure is retried without downloading or committing again."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            sample = source_store(path / "source")
            with patch.object(importer, "STATE", path / "state"):
                with (
                    patch.object(importer, "register", side_effect=RuntimeError("Polaris outage")),
                    self.assertRaisesRegex(RuntimeError, "Polaris outage"),
                ):
                    importer.import_sample(sample, "trusted-token")
                location = (
                    path
                    / "state"
                    / "nasa-storage"
                    / sample["catalog"]
                    / "examples"
                    / sample["table"]
                )
                repo = icechunk.Repository.open(icechunk.local_filesystem_storage(str(location)))
                snapshot = repo.lookup_branch("main")
                with (
                    patch.object(importer, "register") as register,
                    patch.object(
                        importer, "PublicZarrSample", side_effect=AssertionError("download")
                    ),
                ):
                    receipt = importer.import_sample(sample, "trusted-token")
                self.assertEqual(receipt["snapshot"], snapshot)
                self.assertEqual(repo.lookup_branch("main"), snapshot)
                register.assert_called_once()
                self.assertEqual(receipt["arrays"]["temperature"]["attributes"]["units"], "kelvin")

    def test_initialized_empty_repository_is_recoverable(self):
        """An interrupted initial write resumes from its empty committed Icechunk snapshot."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            sample = source_store(path / "source")
            location = (
                path / "state" / "nasa-storage" / sample["catalog"] / "examples" / sample["table"]
            )
            location.mkdir(parents=True)
            repo = icechunk.Repository.create(icechunk.local_filesystem_storage(str(location)))
            initialized = repo.lookup_branch("main")
            with (
                patch.object(importer, "STATE", path / "state"),
                patch.object(importer, "register"),
            ):
                receipt = importer.import_sample(sample, "trusted-token")
            self.assertNotEqual(receipt["snapshot"], initialized)
            group = zarr.open_group(
                store=repo.readonly_session(snapshot_id=receipt["snapshot"]).store, mode="r"
            )
            self.assertEqual(group["temperature"].shape, (3, 4, 4))

    def test_concurrent_imports_share_the_same_committed_snapshot(self):
        """Local import locking prevents two callers from publishing competing repositories."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            sample = source_store(path / "source")
            with (
                patch.object(importer, "STATE", path / "state"),
                patch.object(importer, "register"),
                ThreadPoolExecutor(max_workers=2) as executor,
            ):
                first = executor.submit(importer.import_sample, sample, "trusted-token")
                second = executor.submit(importer.import_sample, sample, "trusted-token")
                self.assertEqual(first.result()["snapshot"], second.result()["snapshot"])

    def test_changed_provenance_and_missing_variables_are_refused(self):
        """Existing snapshots cannot be silently adopted for another source or incomplete schema."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            sample = source_store(path / "source")
            with (
                patch.object(importer, "STATE", path / "state"),
                patch.object(importer, "register"),
            ):
                receipt = importer.import_sample(sample, "trusted-token")
                changed = {**sample, "url": "https://example.test/another-source"}
                with self.assertRaisesRegex(RuntimeError, "different provenance"):
                    importer.import_sample(changed, "trusted-token")
                repo = icechunk.Repository.open(
                    icechunk.local_filesystem_storage(
                        str(Path(receipt["location"].removeprefix("file://")))
                    )
                )
                session = repo.writable_session("main")
                group = zarr.open_group(store=session.store, mode="a")
                del group["lon"]
                session.commit("Simulate an incomplete external edit")
                with self.assertRaisesRegex(RuntimeError, "incomplete or different variables"):
                    importer.import_sample(sample, "trusted-token")

    def test_existing_registration_at_another_location_is_refused(self):
        """A conflicting Polaris table is retained rather than rewritten or adopted."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            location = path / "catalog" / "examples" / "table"
            sample = {"catalog": "catalog", "table": "table", "title": "Scientific sample"}

            def response(resource, **kwargs):
                if resource == "/api/management/v1/catalogs/catalog" and not kwargs.get("method"):
                    return {
                        "storageConfigInfo": {
                            "storageType": "FILE",
                            "allowedLocations": [location.parents[1].as_uri()],
                        }
                    }
                if resource.endswith("icechunk-tables/table"):
                    return {"table": {"location": "file:///different/repository"}}
                return {}

            with (
                patch.object(importer, "exists", return_value=True),
                patch.object(importer, "request", side_effect=response) as request,
                self.assertRaisesRegex(RuntimeError, "different location"),
            ):
                importer.register(sample, location, "trusted-token")
            self.assertTrue(all(not call.kwargs.get("method") for call in request.call_args_list))


if __name__ == "__main__":
    unittest.main()
