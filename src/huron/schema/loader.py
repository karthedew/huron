"""Load the JSON documents shipped in ``huron/schema/documents``."""

from __future__ import annotations

import copy
import functools
import json
from pathlib import Path
from typing import Any

__all__ = ["DOCUMENTS", "DOCUMENTS_DIR", "load_document"]

DOCUMENTS_DIR = Path(__file__).resolve().parent / "documents"
DOCUMENTS = ("commit-request-v1", "huron-base-v1", "schema-document-v1")


def load_document(name: str) -> dict[str, Any]:
    """Return a fresh copy of the document ``name`` (without the ``.json`` suffix)."""
    if name not in DOCUMENTS:
        raise KeyError(name)
    return copy.deepcopy(_read(name))


@functools.cache
def _read(name: str) -> dict[str, Any]:
    document: dict[str, Any] = json.loads((DOCUMENTS_DIR / f"{name}.json").read_text())
    return document
