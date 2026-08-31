"""Invariant N: every published snapshot states where it came from.

Three origins and no fourth: a ``promotion`` descends from a lower layer in
this lake, an ``external`` block roots lineage at a source Huron does not
hold, and a ``derivation`` is a Gold product version's record. The negative
cases are the point - a provenance document that can omit its source is not
provenance.
"""

from __future__ import annotations

from typing import Any

import pytest
from jsonschema import ValidationError

from huron.schema import validate, validator

pytestmark = pytest.mark.unit

SCHEMA = "snapshot-provenance-v1.json"
DIGEST = "sha256:" + "a" * 64


def promotion(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema": "urn:huron:snapshot-provenance:1",
        "kind": "promotion",
        "source_layer": "raw",
        "source_dataset": "run-0042",
        "source_revision_id": "0192f1a0-0000-7000-8000-000000000001",
        "source_revision_number": 1,
        "source_files": {"outp": DIGEST},
        "profile": "mcnp-run@1.0.0",
        "container_digest": DIGEST,
        "built_at": "2026-08-30T17:40:12Z",
    }
    return document | overrides


def external(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema": "urn:huron:snapshot-provenance:1",
        "kind": "external",
        "source_system": "npl-neutron-monitor",
        "source_uri": "https://feed.example.org/monitor/v2",
        "source_digest": DIGEST,
        "window": {"start": "2026-08-30T00:00:00Z", "end": "2026-08-30T01:00:00Z"},
        "profile": "neutron-monitor@2.1.0",
        "contract": "neutron-flux/1",
        "ingested_by": "sa:npl-feed",
        "ingested_at": "2026-08-30T01:00:12Z",
        "container_digest": DIGEST,
    }
    return document | overrides


def derivation(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema": "urn:huron:snapshot-provenance:1",
        "kind": "derivation",
        "product": "shielding-dose-response",
        "product_version": "1.0.0",
        "inputs": [
            {"dataset": "ne/study/sweep", "layer": "silver", "snapshot_id": "S117"},
            {
                "dataset": "reference-data/icrp/coefficients",
                "layer": "silver",
                "snapshot_id": "S031",
                "external": True,
            },
        ],
        "transformation": {
            "name": "flux-to-dose",
            "container_digest": DIGEST,
            "entrypoint": "aether run flux_to_dose.py",
            "parameters": {"integration_dim": "energy"},
        },
        "validation": {"suite": "dose-product-v1", "passed_at": "2026-08-30T19:00:00Z"},
        "produced_snapshot": "G021",
        "published_by": "user:karl",
        "published_at": "2026-08-30T19:02:41Z",
    }
    return document | overrides


def test_the_schema_itself_is_valid() -> None:
    validator(SCHEMA)


def test_each_origin_validates() -> None:
    for document in (promotion(), external(), derivation()):
        validate(SCHEMA, document)


def test_a_snapshot_must_state_an_origin() -> None:
    with pytest.raises(ValidationError):
        validate(SCHEMA, {"schema": "urn:huron:snapshot-provenance:1"})
    with pytest.raises(ValidationError):
        validate(SCHEMA, {"schema": "urn:huron:snapshot-provenance:1", "kind": "trust_me"})


def test_a_promotion_must_name_what_it_descends_from() -> None:
    orphan = promotion()
    del orphan["source_revision_id"]
    with pytest.raises(ValidationError):
        validate(SCHEMA, orphan)
    from_bronze = promotion(source_layer="bronze", source_snapshot_id="B187")
    del from_bronze["source_revision_id"]
    del from_bronze["source_revision_number"]
    validate(SCHEMA, from_bronze)
    # ...and never both: a snapshot descends from exactly one thing.
    with pytest.raises(ValidationError):
        validate(SCHEMA, promotion(source_snapshot_id="B187"))


def test_an_external_entry_must_name_its_source_and_its_service_account() -> None:
    """A lineage root is only honest if it says whose custody the data left."""
    anonymous = external()
    del anonymous["source_system"]
    with pytest.raises(ValidationError):
        validate(SCHEMA, anonymous)
    with pytest.raises(ValidationError):
        validate(SCHEMA, external(ingested_by="user:karl"))


def test_streaming_windows_are_optional_but_well_formed() -> None:
    windowless = external()
    del windowless["window"]
    validate(SCHEMA, windowless)
    with pytest.raises(ValidationError):
        validate(SCHEMA, external(window={"start": "2026-08-30T00:00:00Z"}))


def test_a_derivation_without_inputs_is_not_a_product() -> None:
    with pytest.raises(ValidationError):
        validate(SCHEMA, derivation(inputs=[]))
    incomplete = derivation()
    del incomplete["transformation"]
    with pytest.raises(ValidationError):
        validate(SCHEMA, incomplete)


def test_origins_do_not_borrow_each_other_s_fields() -> None:
    """No document may claim an external entry and a derivation at once."""
    with pytest.raises(ValidationError):
        validate(SCHEMA, external(inputs=[]))
    with pytest.raises(ValidationError):
        validate(SCHEMA, derivation(source_system="npl-neutron-monitor"))
