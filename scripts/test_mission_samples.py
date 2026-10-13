"""Exercise mission CSV conversion and immutable Icechunk publication without external services."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import icechunk
import import_mission_samples as importer
import numpy as np
import zarr
from iss_tsis_sample import TSIS_SAMPLE, parse_tsis_csv
from test_iss_tsis_sample import FIRST, HEADER, SECOND
from test_iss_tsis_sample import metadata as tsis_metadata


def ace_metadata() -> dict:
    """Declare the actual selected HAPI field shapes and physical units.

    Returns:
        HAPI-compatible scientific metadata for offline observations.
    """
    return {
        "status": {"code": 1200},
        "parameters": [
            {"name": "Time", "type": "isotime", "units": "UTC", "fill": None},
            *[
                {
                    "name": name,
                    "type": "double",
                    "units": "nT",
                    "fill": "-1.0E31",
                    "description": name,
                    **({"size": [3]} if name in {"BGSEc", "BGSM"} else {}),
                }
                for name in importer.ACE_PARAMETERS[1:]
            ],
        ],
    }


ACE_CSV = (
    b"2020-01-01T00:00:00.123456789Z,2.732,2.291,-1.483,-0.067,2.291,-1.420,-0.435,0.147\n"
    b"2020-01-01T00:00:15.123456789Z,-1e31,2.125,-1.519,0.136,2.125,-1.505,-0.248,0.239\n"
    b"2020-01-01T00:00:31.123456789Z,2.576,1.969,-1.639,-0.151,1.969,-1.549,-0.555,0.240\n"
)


def legacy_tsis() -> tuple[dict, bytes, bytes]:
    """Provide native science values with the former incomplete fill metadata.

    Returns:
        Original sample settings, incomplete metadata and scientific CSV bytes.
    """
    description = deepcopy(tsis_metadata())
    for entry in description["tsis_tsi_24hr"]["metadata"].values():
        entry.pop("missing_value", None)
    zero = SECOND.split(",")
    for index in range(1, 13):
        zero[index] = "0"
    return (
        {**TSIS_SAMPLE, "metadata_url": "https://example.test/old-metadata"},
        json.dumps(description).encode(),
        f"{HEADER}\n{FIRST}\n{','.join(zero)}\n".encode(),
    )


class MissionSampleTests(unittest.TestCase):
    """Prove original science values, precise times and retained sources survive publication."""

    def test_hapi_fields_units_vectors_and_precise_timestamps(self):
        """Native scalar/vector values and nanosecond timestamps remain unchanged by conversion."""
        arrays = importer.parse_ace_csv(ace_metadata(), ACE_CSV)
        self.assertEqual(set(arrays), {"time", "component", "Magnitude", "BGSEc", "BGSM", "dBrms"})
        self.assertEqual(arrays["BGSEc"][0].shape, (3, 3))
        np.testing.assert_array_equal(arrays["BGSEc"][0][0], [2.291, -1.483, -0.067])
        self.assertEqual(arrays["Magnitude"][0][1], -1e31)
        self.assertEqual(arrays["Magnitude"][1]["_FillValue"], -1e31)
        self.assertEqual(arrays["BGSEc"][1]["coordinate_system"], "GSE")
        self.assertEqual(arrays["BGSM"][1]["coordinate_system"], "GSM")
        self.assertEqual(arrays["component"][1]["labels"], ["x", "y", "z"])
        self.assertEqual(arrays["BGSEc"][1]["units"], "nT")
        self.assertEqual(int(arrays["time"][0][0]), 1577836800123456789)
        np.testing.assert_array_equal(np.diff(arrays["time"][0]), [15_000_000_000, 16_000_000_000])

    def test_changed_hapi_contract_and_malformed_observations_are_refused(self):
        """Changed units, vector size, missing columns and invalid temporal order fail closed."""
        metadata = ace_metadata()
        metadata["parameters"][2]["units"] = "T"
        with self.assertRaisesRegex(RuntimeError, "metadata changed"):
            importer.parse_ace_csv(metadata, ACE_CSV)
        metadata = ace_metadata()
        metadata["parameters"][2]["size"] = [2]
        with self.assertRaisesRegex(RuntimeError, "metadata changed"):
            importer.parse_ace_csv(metadata, ACE_CSV)
        for data in [b"", b"2020-01-01T00:00:00Z,2.7\n"]:
            with self.assertRaisesRegex(RuntimeError, "malformed observations"):
                importer.parse_ace_csv(ace_metadata(), data)
        with self.assertRaisesRegex(RuntimeError, "not increasing"):
            importer.parse_ace_csv(ace_metadata(), b"\n".join(reversed(ACE_CSV.splitlines())))

    def test_persisted_arrays_are_verified_against_retained_sources_and_reused(self):
        """Retries preserve the same snapshot and verify values against exact source bytes."""
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            with (
                patch.object(importer, "STATE", state),
                patch.object(importer, "register") as register,
                patch.object(
                    importer,
                    "download_source",
                    side_effect=[json.dumps(ace_metadata()).encode(), ACE_CSV],
                ) as download,
            ):
                receipt = importer.import_mission_sample(
                    importer.ACE_SAMPLE, importer.parse_ace_csv, "root"
                )
                first_calls = download.call_count
                retried = importer.import_mission_sample(
                    importer.ACE_SAMPLE, importer.parse_ace_csv, "root"
                )
                self.assertEqual(retried["snapshot"], receipt["snapshot"])
                self.assertEqual(download.call_count, first_calls)
                self.assertEqual(register.call_count, 2)
                source = receipt["source_objects"]["data"]
                self.assertEqual(Path(source["local_file"]).read_bytes(), ACE_CSV)
                self.assertEqual(source["sha256"], hashlib.sha256(ACE_CSV).hexdigest())
                self.assertEqual(receipt["arrays"]["Magnitude"]["valid_values"], 2)
                repo = icechunk.Repository.open(
                    icechunk.local_filesystem_storage(
                        str(Path(receipt["location"].removeprefix("file://")))
                    )
                )
                group = zarr.open_group(
                    store=repo.readonly_session(snapshot_id=receipt["snapshot"]).store, mode="r"
                )
                np.testing.assert_array_equal(
                    group["BGSM"][:], importer.parse_ace_csv(ace_metadata(), ACE_CSV)["BGSM"][0]
                )
                self.assertEqual(group["BGSM"].metadata.dimension_names, ("time", "component"))

    def test_registration_failure_can_retry_without_new_download_or_commit(self):
        """A failed upstream registration leaves verified data reusable for a later retry."""
        with tempfile.TemporaryDirectory() as temporary:
            with (
                patch.object(importer, "STATE", Path(temporary)),
                patch.object(importer, "register", side_effect=RuntimeError("Polaris outage")),
                patch.object(
                    importer,
                    "download_source",
                    side_effect=[json.dumps(ace_metadata()).encode(), ACE_CSV],
                ),
                self.assertRaisesRegex(RuntimeError, "Polaris outage"),
            ):
                importer.import_mission_sample(importer.ACE_SAMPLE, importer.parse_ace_csv, "root")
            with (
                patch.object(importer, "STATE", Path(temporary)),
                patch.object(importer, "register"),
                patch.object(importer, "download_source", side_effect=AssertionError("download")),
            ):
                receipt = importer.import_mission_sample(
                    importer.ACE_SAMPLE, importer.parse_ace_csv, "root"
                )
                self.assertEqual(receipt["arrays"]["time"]["shape"], [3])

    def test_modified_original_csv_is_refused(self):
        """A changed retained source cannot be presented as the original scientific observation."""
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(importer, "STATE", Path(temporary)),
            patch.object(importer, "register"),
            patch.object(
                importer,
                "download_source",
                side_effect=[json.dumps(ace_metadata()).encode(), ACE_CSV],
            ),
        ):
            receipt = importer.import_mission_sample(
                importer.ACE_SAMPLE, importer.parse_ace_csv, "root"
            )
            Path(receipt["source_objects"]["data"]["local_file"]).write_bytes(b"changed")
            with self.assertRaisesRegex(RuntimeError, "recorded checksum"):
                importer.import_mission_sample(importer.ACE_SAMPLE, importer.parse_ace_csv, "root")

    def test_concurrent_calls_reuse_a_single_scientific_snapshot(self):
        """A per-table local lock prevents concurrent initialization or competing commits."""
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(importer, "STATE", Path(temporary)),
            patch.object(importer, "register"),
            patch.object(
                importer,
                "download_source",
                side_effect=[json.dumps(ace_metadata()).encode(), ACE_CSV],
            ),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            first = executor.submit(
                importer.import_mission_sample,
                importer.ACE_SAMPLE,
                importer.parse_ace_csv,
                "root",
            )
            second = executor.submit(
                importer.import_mission_sample,
                importer.ACE_SAMPLE,
                importer.parse_ace_csv,
                "root",
            )
            self.assertEqual(first.result()["snapshot"], second.result()["snapshot"])

    def test_tsis_metadata_repair_preserves_original_values_and_snapshot_history(self):
        """Explicit repair adds publisher-declared fill metadata without replacing any values."""
        original_metadata = deepcopy(tsis_metadata())
        for entry in original_metadata["tsis_tsi_24hr"]["metadata"].values():
            entry.pop("missing_value", None)
        zero = SECOND.split(",")
        for index in range(1, 13):
            zero[index] = "0"
        payload = f"{HEADER}\n{FIRST}\n{','.join(zero)}\n".encode()
        original_sample = {**TSIS_SAMPLE, "metadata_url": "https://example.test/old-metadata"}
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(importer, "STATE", Path(temporary)),
            patch.object(importer, "register"),
        ):
            with patch.object(
                importer,
                "download_source",
                side_effect=[json.dumps(original_metadata).encode(), payload],
            ):
                original = importer.import_mission_sample(original_sample, parse_tsis_csv, "root")
            with patch.object(
                importer, "download_source", return_value=json.dumps(tsis_metadata()).encode()
            ) as download:
                repaired = importer.import_mission_sample(
                    TSIS_SAMPLE, parse_tsis_csv, "root", repair_metadata=True
                )
            self.assertNotEqual(original["snapshot"], repaired["snapshot"])
            self.assertEqual(repaired["metadata_repair"]["parent_snapshot"], original["snapshot"])
            self.assertEqual(download.call_count, 1)
            self.assertEqual(repaired["arrays"]["tsi_1au"]["valid_values"], 1)
            self.assertEqual(repaired["arrays"]["tsi_1au"]["minimum"], 1361.4752)
            self.assertEqual(repaired["arrays"]["provisional_flag"]["valid_values"], 2)
            repo = icechunk.Repository.open(
                icechunk.local_filesystem_storage(
                    str(Path(original["location"].removeprefix("file://")))
                )
            )
            before = zarr.open_group(
                store=repo.readonly_session(snapshot_id=original["snapshot"]).store, mode="r"
            )
            after = zarr.open_group(
                store=repo.readonly_session(snapshot_id=repaired["snapshot"]).store, mode="r"
            )
            self.assertNotIn("_FillValue", before["tsi_1au"].attrs)
            self.assertEqual(after["tsi_1au"].attrs["_FillValue"], 0)
            self.assertNotIn("_FillValue", after["provisional_flag"].attrs)
            for name in before.array_keys():
                np.testing.assert_array_equal(before[name][:], after[name][:])
            with patch.object(importer, "download_source", side_effect=AssertionError("download")):
                retried = importer.import_mission_sample(
                    TSIS_SAMPLE, parse_tsis_csv, "root", repair_metadata=True
                )
            self.assertEqual(retried["snapshot"], repaired["snapshot"])

    def test_metadata_repair_is_restricted_to_tsis(self):
        """The explicit correction flag cannot mutate an unrelated scientific repository."""
        with self.assertRaisesRegex(RuntimeError, "restricted"):
            importer.import_mission_sample(
                importer.ACE_SAMPLE, importer.parse_ace_csv, "root", repair_metadata=True
            )

    def test_metadata_repair_refuses_changed_scientific_values(self):
        """Explicit metadata repair cannot replace changed measurements with source values."""
        sample, metadata, payload = legacy_tsis()
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(importer, "STATE", Path(temporary)),
            patch.object(importer, "register"),
        ):
            with patch.object(importer, "download_source", side_effect=[metadata, payload]):
                original = importer.import_mission_sample(sample, parse_tsis_csv, "root")
            repo = icechunk.Repository.open(
                icechunk.local_filesystem_storage(
                    str(Path(original["location"].removeprefix("file://")))
                )
            )
            session = repo.writable_session("main")
            group = zarr.open_group(store=session.store, mode="a")
            group["tsi_1au"][0] = 900
            changed = session.commit("External scientific change")
            with (
                patch.object(
                    importer, "download_source", return_value=json.dumps(tsis_metadata()).encode()
                ),
                self.assertRaisesRegex(RuntimeError, "values changed"),
            ):
                importer.import_mission_sample(
                    TSIS_SAMPLE, parse_tsis_csv, "root", repair_metadata=True
                )
            self.assertEqual(repo.lookup_branch("main"), changed)

    def test_metadata_repair_refuses_a_concurrently_advanced_branch(self):
        """A repair prepared against an older snapshot cannot overwrite a newer commit."""
        sample, metadata, payload = legacy_tsis()
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(importer, "STATE", Path(temporary)),
            patch.object(importer, "register"),
        ):
            with patch.object(importer, "download_source", side_effect=[metadata, payload]):
                original = importer.import_mission_sample(sample, parse_tsis_csv, "root")
            repo = icechunk.Repository.open(
                icechunk.local_filesystem_storage(
                    str(Path(original["location"].removeprefix("file://")))
                )
            )
            advanced = []

            def update_branch(_url):
                session = repo.writable_session("main")
                group = zarr.open_group(store=session.store, mode="a")
                group.attrs["external_edit"] = "preserve this newer commit"
                advanced.append(session.commit("Concurrent metadata edit"))
                return json.dumps(tsis_metadata()).encode()

            with (
                patch.object(importer, "download_source", side_effect=update_branch),
                self.assertRaisesRegex(RuntimeError, "branch changed"),
            ):
                importer.import_mission_sample(
                    TSIS_SAMPLE, parse_tsis_csv, "root", repair_metadata=True
                )
            self.assertEqual(repo.lookup_branch("main"), advanced[0])


if __name__ == "__main__":
    unittest.main()
