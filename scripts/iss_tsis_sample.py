"""Decode a bounded TSIS-1 TIM scientific sample without changing native values."""

from __future__ import annotations

import csv
import io
import re
from decimal import ROUND_HALF_EVEN, Decimal

import numpy as np
from numpy.typing import NDArray

TSIS_COLUMNS = [
    "time",
    "tsi_1au",
    "instrument_accuracy_1au",
    "instrument_precision_1au",
    "solar_standard_deviation_1au",
    "measurement_uncertainty_1au",
    "tsi_true_earth",
    "instrument_accuracy_true_earth",
    "instrument_precision_true_earth",
    "solar_standard_deviation_true_earth",
    "measurement_uncertainty_true_earth",
    "avg_measurement_date",
    "std_dev_measurement_date",
    "provisional_flag",
]

TSIS_SAMPLE = {
    "catalog": "international_space_station",
    "namespace": ["instruments", "tsis_1"],
    "table": "total_solar_irradiance",
    "title": "ISS TSIS-1 TIM daily total solar irradiance, 2020",
    "url": "https://lasp.colorado.edu/lisird/latis/dap/tsis_tsi_24hr.csv?time%3E=2020-01-01&time%3C2021-01-01",
    "metadata_url": "https://lasp.colorado.edu/lisird/latis/dap/tsis_tsi_24hr.jsond?limit(0)",
    "native_attributes_url": "https://lasp.colorado.edu/lisird/latis/dap/tsis_tsi_24hr.das",
    "hapi_metadata_url": "https://lasp.colorado.edu/lisird/latis/hapi/info?id=tsis_tsi_24hr",
    "documentation": "https://lasp.colorado.edu/tsis/data/tsi-data/",
    "distribution": "https://lasp.colorado.edu/lisird/data/tsis_tsi_24hr/",
    "mission": "https://science.nasa.gov/mission/tsis-1/",
    "doi": "https://doi.org/10.5067/TSIS/TIM/DATA310",
    "source_version": "05",
    "processing_level": "Level 3",
    "source_format": "NASA/LASP LISIRD LaTiS CSV",
    "conversion": (
        "Preserve all native CSV columns, numbers, Julian Date units and provisional_flag "
        "(0=final, 1=provisional). Preserve the source's zero-valued records without "
        "scientific masking or interpolation. Add time_unix_ns as an explicitly derived UTC "
        "coordinate while retaining the original time column."
    ),
    "rights": "NASA EOSDIS data use and citation guidance; cite the data product and LASP source.",
    "rights_url": (
        "https://earthdata.nasa.gov/engage/open-data-services-software-policies/data-use-guidance"
    ),
    "citation_url": "https://disc.gsfc.nasa.gov/data-guidelines",
    "collection_metadata": (
        "https://cmr.earthdata.nasa.gov/search/collections.umm_json?"
        "short_name=TSIS_TSI_L3_24HR&version=05"
    ),
    "caveats": [
        (
            "The downloaded 2020 CSV contains 40 daily records with zero-valued irradiance "
            "fields. Native LaTiS metadata explicitly declares 0 as missing_value for these "
            "fields. The import retains source values and records the declared fill values."
        ),
        "provisional_flag reports final/provisional status, not general measurement validity.",
    ],
    "selection": {"start": "2020-01-01", "stop": "2021-01-01", "columns": TSIS_COLUMNS},
    "kind": "tsis_csv",
}

SampleValues = NDArray[np.float64] | NDArray[np.int64]
SampleArrays = dict[str, tuple[SampleValues, dict[str, object]]]


def _header(field: str) -> tuple[str, str | None]:
    match = re.fullmatch(r"([^()]+?)(?:\s+\(([^()]+)\))?", field.strip())
    if not match:
        raise ValueError(f"Invalid TSIS CSV field: {field!r}")
    return match.group(1).strip(), match.group(2)


def _parameters(metadata: dict[str, object]) -> dict[str, dict[str, object]]:
    dataset = metadata.get("tsis_tsi_24hr")
    if not isinstance(dataset, dict) or dataset.get("parameters") != TSIS_COLUMNS:
        raise ValueError("TSIS metadata does not declare the selected scientific parameters.")
    parameters = dataset.get("metadata")
    if not isinstance(parameters, dict):
        raise ValueError("TSIS metadata does not declare its parameter attributes.")
    result: dict[str, dict[str, object]] = {}
    for name, attributes in parameters.items():
        if not isinstance(name, str) or not isinstance(attributes, dict):
            raise ValueError("TSIS metadata contains an invalid parameter.")
        result[name] = attributes
    return result


def _values(rows: list[list[str]], index: int, integer: bool) -> SampleValues:
    if integer:
        numbers = [Decimal(row[index]) for row in rows]
        if any(not value.is_finite() or value != value.to_integral_value() for value in numbers):
            raise ValueError("TSIS integer parameter contains a noninteger value.")
        return np.asarray([int(value) for value in numbers], dtype=np.int64)
    return np.asarray([float(row[index]) for row in rows], dtype=np.float64)


def parse_tsis_csv(metadata: dict[str, object], payload: bytes) -> SampleArrays:
    """Preserve CSV numbers, native units and flags, and add an explicit UTC coordinate.

    Args:
        metadata: Public LISIRD native JSOND parameter attributes.
        payload: Original LISIRD LaTiS CSV bytes, including its native-unit header.

    Returns:
        Numeric arrays and their Zarr attributes, keyed by scientific parameter name.

    Raises:
        ValueError: The source is empty, malformed or differs from the declared columns.
    """
    parsed = list(csv.reader(io.StringIO(payload.decode("utf-8-sig"))))
    if len(parsed) < 2:
        raise ValueError("TSIS sample must contain a header and observations.")
    fields = [_header(field) for field in parsed[0]]
    names = [name for name, _ in fields]
    if names != TSIS_COLUMNS:
        raise ValueError("TSIS CSV columns differ from the selected scientific parameters.")
    rows = parsed[1:]
    if any(len(row) != len(fields) for row in rows):
        raise ValueError("TSIS CSV contains an incomplete observation.")
    parameters = _parameters(metadata)
    if set(parameters) != set(names):
        raise ValueError("TSIS metadata and CSV declare different scientific parameters.")
    arrays: SampleArrays = {}
    for index, (name, units) in enumerate(fields):
        parameter = parameters[name]
        attrs: dict[str, object] = {
            "_ARRAY_DIMENSIONS": ["time"],
            "description": parameter.get("long_name", name),
            "source_parameter": name,
            "source_metadata": parameter,
        }
        if units is not None:
            attrs["units"] = units
        if parameter.get("missing_value") is not None:
            fill = str(parameter["missing_value"])
            attrs["_FillValue"] = int(Decimal(fill)) if name == "provisional_flag" else float(fill)
            attrs["missing_value"] = attrs["_FillValue"]
        if name in {"time", "avg_measurement_date"} and units not in {"Julian Date", "JD"}:
            raise ValueError(f"TSIS {name} must retain the source Julian Date units.")
        arrays[name] = (_values(rows, index, name == "provisional_flag"), attrs)
    arrays["provisional_flag"][1].update(
        {"flag_values": [0, 1], "flag_meanings": "final provisional"}
    )
    arrays["time"][1]["delivery_metadata_note"] = (
        "JSOND metadata describes its default epoch time delivery; this LaTiS CSV uses the "
        "Julian Date units declared in the original CSV header."
    )
    native_time = arrays["time"][0]
    if not np.isfinite(native_time).all() or (np.diff(native_time) <= 0).any():
        raise ValueError("TSIS observation dates must be finite and strictly increasing.")
    nanoseconds = [
        int(
            (
                (Decimal(row[0]) - Decimal("2440587.5")) * Decimal("86400000000000")
            ).to_integral_value(rounding=ROUND_HALF_EVEN)
        )
        for row in rows
    ]
    arrays["time_unix_ns"] = (
        np.asarray(nanoseconds, dtype=np.int64),
        {
            "_ARRAY_DIMENSIONS": ["time"],
            "units": "nanoseconds since 1970-01-01T00:00:00Z",
            "description": "UTC epoch coordinate derived from the retained source Julian Date.",
            "source_parameter": "time",
            "derivation": (
                "(Julian Date - 2440587.5) * 86400000000000, "
                "rounded to the nearest integer nanosecond"
            ),
        },
    )
    return arrays
