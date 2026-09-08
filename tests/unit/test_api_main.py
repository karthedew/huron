"""Proves that importing the ASGI entrypoint reads ``HURON_*`` once and builds the app.

This is the one place in the tier where that environment read is allowed
to happen at import time.
"""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

import pytest
from fastapi import FastAPI
from pydantic import ValidationError

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def test_importing_main_reads_the_environment_and_builds_the_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Importing ``main`` with a complete environment builds a ``FastAPI`` app."""
    monkeypatch.setenv("HURON_ENV", "development")
    monkeypatch.setenv("HURON_AUTH_MODE", "dev-headers")
    monkeypatch.setenv("HURON_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("HURON_DATABASE_URL", "postgresql://unused")
    monkeypatch.setenv(
        "HURON_CLASSIFICATION_VOCABULARY",
        '[{"code": "open", "order": 0, "discoverable": true}]',
    )
    sys.modules.pop("huron.applications.api.main", None)
    try:
        module = importlib.import_module("huron.applications.api.main")
        assert isinstance(module.app, FastAPI)
    finally:
        sys.modules.pop("huron.applications.api.main", None)


def test_importing_main_with_no_environment_fails_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Importing ``main`` with no environment set raises ``ValidationError`` instead of importing.

    The whole reason this module is separate from ``app.py``: reading the
    environment is allowed to fail loudly here, at the one import site that
    does it, rather than silently inside every test that imports the
    package.
    """
    for name in (
        "HURON_ENV",
        "HURON_AUTH_MODE",
        "HURON_DATA_ROOT",
        "HURON_DATABASE_URL",
        "HURON_CLASSIFICATION_VOCABULARY",
    ):
        monkeypatch.delenv(name, raising=False)
    sys.modules.pop("huron.applications.api.main", None)
    try:
        with pytest.raises(ValidationError):
            importlib.import_module("huron.applications.api.main")
    finally:
        sys.modules.pop("huron.applications.api.main", None)
