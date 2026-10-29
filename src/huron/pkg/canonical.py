"""Canonical JSON bytes (RFC 8785) and stable document hashes."""

from __future__ import annotations

import hashlib
from typing import Any

import rfc8785

__all__ = ["canonical_bytes", "document_sha256"]


def canonical_bytes(document: Any) -> bytes:
    """Serialize ``document`` as RFC 8785 canonical JSON."""
    return bytes(rfc8785.dumps(document))


def document_sha256(document: Any) -> str:
    """Return the lowercase hex sha256 of the canonical bytes of ``document``."""
    return hashlib.sha256(canonical_bytes(document)).hexdigest()
