"""Verify exact NASA values, immutable source copies and real Iceberg retry behavior."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import seed_catalog_types as seeder
from pyiceberg.catalog.sql import SqlCatalog
from pyiceberg.table import Table
from test_mission_samples import ACE_CSV, ace_metadata


class CatalogTypeSeedTests(unittest.TestCase):
    """Prove actual SDK storage and recovery without connecting to a live catalog."""

    def test_exact_source_values_units_and_nanosecond_times(self):
        """Scalar columns retain original frames, missing values and submicrosecond timestamps."""
        arrow, schema = seeder.observations(ACE_CSV, json.dumps(ace_metadata()).encode())
        self.assertEqual(arrow.num_rows, 3)
        self.assertEqual(arrow.num_columns, 9)
        self.assertEqual(arrow["time_unix_ns"][0].as_py(), 1577836800123456789)
        self.assertEqual(arrow["magnitude_nt"][1].as_py(), -1e31)
        self.assertEqual(arrow["bgsec_y_nt"][0].as_py(), -1.483)
        self.assertEqual(arrow["bgsm_z_nt"][0].as_py(), -0.435)
        self.assertIn("GSE Cartesian", schema.find_field("bgsec_y_nt").doc)
        self.assertIn("GSM Cartesian", schema.find_field("bgsm_z_nt").doc)

    def test_source_copy_retries_preserve_bytes_and_refuse_conflicting_storage(self):
        """Retrying a source copy leaves its identity unchanged and never overwrites other bytes."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve() / "source" / "data.csv"
            seeder.preserve_file(path, ACE_CSV)
            original = path.stat().st_ino
            seeder.preserve_file(path, ACE_CSV)
            self.assertEqual(path.stat().st_ino, original)
            with self.assertRaisesRegex(RuntimeError, "refusing to overwrite"):
                seeder.preserve_file(path, b"different")
            self.assertEqual(path.read_bytes(), ACE_CSV)
            linked = path.parent / "linked.csv"
            linked.symlink_to(path)
            with self.assertRaisesRegex(RuntimeError, "symlink"):
                seeder.preserve_file(linked, ACE_CSV)

    def test_real_iceberg_readback_and_retry_reuses_the_same_snapshot(self):
        """Actual Parquet and Iceberg metadata round-trip every value without a duplicate append."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            catalog = SqlCatalog("temporary", uri="sqlite:///:memory:", warehouse=root.as_uri())
            catalog.create_namespace(seeder.NAMESPACE)
            arrow, schema = seeder.observations(ACE_CSV, json.dumps(ace_metadata()).encode())
            first = seeder.seed_iceberg(catalog, root, arrow, schema)
            second = seeder.seed_iceberg(catalog, root, arrow, schema)
            verified = seeder.seed_iceberg(catalog, root, arrow, schema, verify_only=True)
            self.assertEqual(first, second)
            self.assertEqual(first, verified)
            table = catalog.load_table((*seeder.NAMESPACE, seeder.TABLE_NAME))
            self.assertEqual(len(table.snapshots()), 1)
            self.assertEqual(first["rows"], 3)
            self.assertTrue(any(root.rglob("*.parquet")))
            self.assertTrue(any(root.rglob("*.avro")))

    def test_recovers_after_table_creation_without_replacing_unexpected_existing_rows(self):
        """A failed append resumes; later user changes are retained and reported as mismatches."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            catalog = SqlCatalog("temporary", uri="sqlite:///:memory:", warehouse=root.as_uri())
            catalog.create_namespace(seeder.NAMESPACE)
            arrow, schema = seeder.observations(ACE_CSV, json.dumps(ace_metadata()).encode())
            with (
                patch.object(Table, "append", side_effect=RuntimeError("interrupted append")),
                self.assertRaisesRegex(RuntimeError, "interrupted append"),
            ):
                seeder.seed_iceberg(catalog, root, arrow, schema)
            result = seeder.seed_iceberg(catalog, root, arrow, schema)
            self.assertEqual(result["rows"], 3)
            table = catalog.load_table((*seeder.NAMESPACE, seeder.TABLE_NAME))
            table.append(arrow.slice(0, 1))
            with self.assertRaisesRegex(RuntimeError, "readback differs"):
                seeder.seed_iceberg(catalog, root, arrow, schema)
            self.assertEqual(
                catalog.load_table((*seeder.NAMESPACE, seeder.TABLE_NAME)).scan().count(), 4
            )


if __name__ == "__main__":
    unittest.main()
