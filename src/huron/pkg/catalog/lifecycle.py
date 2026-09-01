"""Pure dataset lifecycle vocabulary."""

from __future__ import annotations

from enum import StrEnum


class DatasetLifecycle(StrEnum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"
    SUPERSEDED = "SUPERSEDED"
