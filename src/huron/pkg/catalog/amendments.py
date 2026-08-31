"""Validation and deterministic folding of append-only metadata amendments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime
    from typing import Any
    from uuid import UUID

from .errors import AmendmentFieldForbidden

AMENDABLE_FIELDS = frozenset(
    {"title", "description", "tags", "coverage", "source", "extensions", "data_classification"}
)


@dataclass(frozen=True, slots=True)
class Amendment:
    id: UUID
    sequence: int
    created_by: str
    created_at: datetime
    changes: Mapping[str, Any]


def validate_amendment(
    changes: Mapping[str, Any], *, may_reclassify: bool = False
) -> dict[str, Any]:
    forbidden = set(changes) - AMENDABLE_FIELDS
    if forbidden:
        names = ", ".join(sorted(forbidden))
        raise AmendmentFieldForbidden(f"fields may not be amended: {names}")
    if "data_classification" in changes and not may_reclassify:
        raise AmendmentFieldForbidden("data_classification requires metadata.reclassify")
    if not changes:
        raise ValueError("an amendment must replace at least one field")
    return dict(changes)


def fold_amendments(base: Mapping[str, Any], amendments: Sequence[Amendment]) -> dict[str, Any]:
    effective = dict(base)
    expected_sequence = 1
    for amendment in sorted(amendments, key=lambda item: item.sequence):
        if amendment.sequence != expected_sequence:
            raise ValueError(
                f"amendment sequence gap: expected {expected_sequence}, got {amendment.sequence}"
            )
        effective.update(validate_amendment(amendment.changes, may_reclassify=True))
        expected_sequence += 1
    return effective
