"""The committed OpenAPI document matches the application."""

import json
from pathlib import Path

from huron.applications.api.openapi import document

SNAPSHOT = Path(__file__).resolve().parents[3] / "docs" / "openapi.json"


def test_committed_openapi_matches_the_application() -> None:
    assert json.loads(SNAPSHOT.read_text()) == document(), "run `make openapi` and commit"
