"""Verify authorized-helper metadata behavior using real temporary Icechunk repositories."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import icechunk
import inspect_icechunk as inspector
import zarr
from seed_icechunk_ui_fixture import seed


class IcechunkInspectorTests(unittest.TestCase):
    """Prove actual schema/history, read-only access and filesystem/metadata safeguards."""

    def test_actual_schema_references_history_and_provenance(self):
        """Actual SDK metadata supplies dimensions, branches, tags, commits and source records."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            path = root / "repository"
            references = seed(path)
            result = inspector.inspect_repository(str(path), [str(root)])
            self.assertEqual(result["snapshot"]["id"], references["main"])
            self.assertEqual(result["snapshot"]["parentId"], references["first"])
            self.assertEqual(
                [entry["message"] for entry in result["history"]],
                ["Fixture metadata correction", "Fixture ingest 1", "Repository initialized"],
            )
            self.assertEqual(
                result["branches"],
                [
                    {"name": "analysis", "snapshotId": references["analysis"]},
                    {"name": "main", "snapshotId": references["main"]},
                ],
            )
            self.assertEqual(
                result["tags"], [{"name": "baseline", "snapshotId": references["baseline"]}]
            )
            self.assertEqual(result["arrays"][0]["shape"], [2, 2, 2])
            self.assertEqual(result["arrays"][0]["dimensions"], ["time", "lat", "lon"])
            self.assertEqual(result["arrays"][0]["chunks"], [1, 2, 2])
            self.assertEqual(result["arrays"][0]["dtype"], "float32")
            self.assertTrue(result["provenance"]["importReceipt"]["test_fixture"])
            self.assertEqual(result["lineage"]["state"], "unavailable")

    def test_metadata_inspection_never_reads_array_values_or_opens_writable_sessions(self):
        """Metadata operations work while array-data reads and writable sessions are forbidden."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            path = root / "repository"
            seed(path)
            with (
                patch.object(zarr.Array, "__getitem__", side_effect=AssertionError("chunk read")),
                patch.object(zarr.AsyncArray, "getitem", side_effect=AssertionError("chunk read")),
                patch.object(
                    icechunk.Repository, "writable_session", side_effect=AssertionError("write")
                ),
            ):
                result = inspector.inspect_repository(str(path), [str(root)])
            self.assertEqual(result["state"], "available")
            self.assertEqual(len(result["arrays"]), 1)

    def test_pinned_initial_snapshot_and_real_branch_selection(self):
        """History links inspect immutable earlier snapshots, including an empty initial state."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            path = root / "repository"
            references = seed(path)
            branch = inspector.inspect_repository(str(path), [str(root)], "analysis")
            self.assertEqual(branch["snapshot"]["id"], references["first"])
            initial = inspector.inspect_repository(
                str(path), [str(root)], snapshot_id=references["initialized"]
            )
            self.assertEqual(initial["state"], "available")
            self.assertEqual(initial["arrays"], [])
            self.assertEqual(initial["history"][0]["message"], "Repository initialized")
            with self.assertRaisesRegex(inspector.InspectionError, "reference-not-found"):
                inspector.inspect_repository(str(path), [str(root)], "missing")

    def test_rejects_outside_roots_repository_symlinks_and_internal_symlinks(self):
        """Neither a registration path nor internal metadata links can escape approved storage."""
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            root = base / "approved"
            root.mkdir()
            path = root / "repository"
            seed(path)
            outside = base / "outside"
            outside.mkdir()
            linked = root / "linked"
            linked.symlink_to(path, target_is_directory=True)
            for candidate in [outside, linked]:
                with self.assertRaisesRegex(inspector.InspectionError, "unsafe-location"):
                    inspector.inspect_repository(str(candidate), [str(root)])
            (path / "untrusted-link").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(inspector.InspectionError, "unsafe-location"):
                inspector.inspect_repository(str(path), [str(root)])

    def test_sensitive_metadata_is_redacted_and_large_values_are_visibly_bounded(self):
        """Credentials in keys and URLs are redacted while scientific attributes survive."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            path = root / "repository"
            seed(path)
            repo = icechunk.Repository.open(icechunk.local_filesystem_storage(str(path)))
            session = repo.writable_session("main")
            group = zarr.open_group(store=session.store, mode="a")
            group.attrs.update(
                {
                    "clientSecret": "never-show-secret",
                    "source_url": "https://name:never-show-password@source.example/data?access_token=never-show-token",
                    "large_note": "A" * 10000,
                    "long_url": "https://name:" + "never-show" * 2000 + "@source.example/data",
                }
            )
            session.commit("Metadata projection test")
            result = inspector.inspect_repository(str(path), [str(root)])
            self.assertTrue(result["redacted"])
            self.assertTrue(result["truncated"])
            self.assertNotIn("never-show", json.dumps(result))
            self.assertEqual(result["arrays"][0]["attributes"]["units"], "kelvin")

    def test_limits_include_selected_branch_and_actual_history_continuation(self):
        """Bound references while preserving the selected branch and real history continuation."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            path = root / "repository"
            references = seed(path)
            repo = icechunk.Repository.open(icechunk.local_filesystem_storage(str(path)))
            repo.create_branch("z-selected", references["first"])
            with (
                patch.object(inspector, "REFERENCE_LIMIT", 2),
                patch.object(inspector, "HISTORY_LIMIT", 2),
            ):
                selected = inspector.inspect_repository(str(path), [str(root)], "z-selected")
                result = inspector.inspect_repository(str(path), [str(root)])
            self.assertTrue(any(entry["name"] == "z-selected" for entry in selected["branches"]))
            self.assertEqual(result["historyNextSnapshotId"], references["initialized"])
            self.assertTrue(result["truncated"])
            with patch.object(inspector, "SCHEMA_LIMIT", 1):
                schema = inspector.inspect_repository(str(path), [str(root)])
            self.assertEqual(schema["arrays"], [])
            self.assertTrue(schema["truncated"])


if __name__ == "__main__":
    unittest.main()
