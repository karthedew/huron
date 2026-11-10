"""The committed OpenAPI document matches the application."""

import json
from pathlib import Path

from huron.applications.api.openapi import document

SNAPSHOT = Path(__file__).resolve().parents[3] / "docs" / "openapi.json"


def test_committed_openapi_matches_the_application() -> None:
    assert json.loads(SNAPSHOT.read_text()) == document(), "run `make openapi` and commit"


def test_repair_reason_rules_belong_to_the_failure_fields() -> None:
    schemas = document()["components"]["schemas"]
    reason = schemas["FailureReason"]
    assert reason["description"] == "Why a repair could not fix a place."
    fields = schemas["RepairFailureOut"]["properties"]
    for value in reason["enum"]:
        assert f"{value}:" in fields["reason"]["description"]
    assert fields["detail"]["description"] == (
        "Why the repair failed, as text for people. It names the same place as path."
    )
