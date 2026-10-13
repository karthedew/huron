"""Verify lossless TSIS scientific values and honest time-coordinate conversion."""

from __future__ import annotations

import unittest
from copy import deepcopy

import numpy as np
from iss_tsis_sample import TSIS_COLUMNS, parse_tsis_csv

# The first two observations come from the public TSIS-1 TIM 2020 CSV.
HEADER = (
    "time (Julian Date),tsi_1au (W/m^2),instrument_accuracy_1au (W/m^2),"
    "instrument_precision_1au (W/m^2),solar_standard_deviation_1au (W/m^2),"
    "measurement_uncertainty_1au (W/m^2),tsi_true_earth (W/m^2),"
    "instrument_accuracy_true_earth (W/m^2),instrument_precision_true_earth (W/m^2),"
    "solar_standard_deviation_true_earth (W/m^2),measurement_uncertainty_true_earth (W/m^2),"
    "avg_measurement_date (Julian Date),std_dev_measurement_date (days),provisional_flag"
)
FIRST = (
    "2458850.0,1361.4752,0.1698,0.0068,0.05247,0.1777,1408.1773,0.1756,0.0068,"
    "0.05619,0.1844,2458850.249779,0.1471,0"
)
SECOND = (
    "2458851.0,1361.4884,0.1698,0.0068,0.06061,0.1803,1408.229,0.1756,0.0068,"
    "0.06639,0.1877,2458851.055361,0.293,0"
)


def metadata() -> dict[str, object]:
    """Describe native JSOND attributes, including the declared zero fill value."""
    return {
        "tsis_tsi_24hr": {
            "parameters": TSIS_COLUMNS,
            "data": [],
            "metadata": {
                name: {
                    "long_name": name,
                    **({"missing_value": "0"} if name not in {"time", "provisional_flag"} else {}),
                    **({"units": "W/m^2"} if "1au" in name or "earth" in name else {}),
                }
                for name in TSIS_COLUMNS
            },
        }
    }


class TsisCsvTests(unittest.TestCase):
    """Prove scientific field fidelity and malformed-source rejection."""

    def test_preserves_all_scientific_columns_native_units_and_integer_flags(self) -> None:
        """Decode every original source value without scientific-field renaming."""
        arrays = parse_tsis_csv(metadata(), f"{HEADER}\n{FIRST}\n{SECOND}\n".encode())
        self.assertEqual(set(arrays), {*TSIS_COLUMNS, "time_unix_ns"})
        for index, name in enumerate(TSIS_COLUMNS):
            np.testing.assert_array_equal(
                arrays[name][0], [float(FIRST.split(",")[index]), float(SECOND.split(",")[index])]
            )
            self.assertEqual(arrays[name][1]["source_parameter"], name)
            self.assertEqual(arrays[name][1]["_ARRAY_DIMENSIONS"], ["time"])
            if name in {"time", "provisional_flag"}:
                self.assertNotIn("_FillValue", arrays[name][1])
            else:
                self.assertEqual(arrays[name][1]["_FillValue"], 0)
        self.assertEqual(arrays["time"][1]["units"], "Julian Date")
        self.assertEqual(arrays["tsi_1au"][1]["units"], "W/m^2")
        self.assertEqual(arrays["provisional_flag"][0].dtype, np.dtype("int64"))
        self.assertNotIn("units", arrays["provisional_flag"][1])

    def test_derives_utc_epoch_without_discarding_julian_dates(self) -> None:
        """The Julian Date day begins at noon, which the derived coordinate retains."""
        arrays = parse_tsis_csv(metadata(), f"{HEADER}\n{FIRST}\n{SECOND}\n".encode())
        np.testing.assert_array_equal(
            arrays["time_unix_ns"][0], [1577880000000000000, 1577966400000000000]
        )
        np.testing.assert_array_equal(arrays["time"][0], [2458850.0, 2458851.0])

    def test_preserves_declared_fill_values_and_quality_flag_without_masking(self) -> None:
        """A source fill remains available for downstream quality decisions."""
        description = metadata()
        dataset = description["tsis_tsi_24hr"]
        assert isinstance(dataset, dict)
        dataset["metadata"]["tsi_1au"]["missing_value"] = "-9999"
        modified = FIRST.split(",")
        modified[1] = "-9999"
        modified[-1] = "1"
        arrays = parse_tsis_csv(description, f"{HEADER}\n{','.join(modified)}\n".encode())
        self.assertEqual(arrays["tsi_1au"][0][0], -9999)
        self.assertEqual(arrays["tsi_1au"][1]["_FillValue"], -9999)
        self.assertEqual(arrays["tsi_1au"][1]["source_metadata"]["missing_value"], "-9999")
        self.assertEqual(arrays["provisional_flag"][0][0], 1)

    def test_rejects_changed_schema_truncated_rows_and_noninteger_flags(self) -> None:
        """Malformed downloads fail before constructing a repository."""
        with self.assertRaisesRegex(ValueError, "columns differ"):
            parse_tsis_csv(
                metadata(), f"{HEADER.replace('tsi_1au', 'unknown')}\n{FIRST}\n".encode()
            )
        with self.assertRaisesRegex(ValueError, "incomplete observation"):
            parse_tsis_csv(metadata(), f"{HEADER}\n2458850.0,1361.4752\n".encode())
        with self.assertRaisesRegex(ValueError, "noninteger"):
            parse_tsis_csv(metadata(), f"{HEADER}\n{FIRST[:-1]}0.5\n".encode())
        missing = deepcopy(metadata())
        missing["tsis_tsi_24hr"]["metadata"] = {}
        with self.assertRaisesRegex(ValueError, "different scientific parameters"):
            parse_tsis_csv(missing, f"{HEADER}\n{FIRST}\n".encode())


if __name__ == "__main__":
    unittest.main()
