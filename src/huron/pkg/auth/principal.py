"""The identity every credential resolver produces, before authorization runs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    groups: frozenset[str] = frozenset()
    scopes: frozenset[str] = frozenset()
    project_id: str | None = None
    authentication_method: str = "unknown"
    #: "user" or "service_account" - drives which roles the subject may hold.
    kind: str = "user"


__all__ = ["Principal"]
