"""Validation and deterministic folding of append-only metadata amendments.

Descriptive metadata is never edited in place. Each change is stored as an
:class:`Amendment` - a numbered, attributed record of the fields it replaces -
and the effective metadata is recomputed by folding the amendments over the
base document in sequence order. Storing the sequence rather than the result
keeps every past value and its author on record and makes the current value
a pure function of what was stored, so two readers can never disagree about
it.

Only the fields in ``AMENDABLE_FIELDS`` may be amended. Everything else -
slugs, identifiers, the fields the storage layout is derived from - is
refused, because other records and paths depend on those values staying put.
"""

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
    """One stored metadata change: which fields it replaced, by whom, and when.

    The amendments to one entity form a gap-free sequence numbered from 1,
    and the sequence, not the timestamp, is the order they fold in.

    Attributes:
        id: The amendment's own identifier.
        sequence: Its 1-based position among the entity's amendments.
        created_by: The principal that made the change.
        created_at: When the change was accepted.
        changes: The replaced fields and their new values. Every key is
            expected to be in ``AMENDABLE_FIELDS``; the fold checks again.
    """

    id: UUID
    sequence: int
    created_by: str
    created_at: datetime
    changes: Mapping[str, Any]


def validate_amendment(
    changes: Mapping[str, Any], *, may_reclassify: bool = False
) -> dict[str, Any]:
    """Check a proposed amendment against the allow-list and return it as a plain dict.

    ``data_classification`` is amendable but guarded separately: changing it
    changes who may read the data, so it needs the ``metadata.reclassify``
    capability rather than plain metadata write access, and the caller
    passes the outcome of that check as ``may_reclassify``. Forbidden fields
    are reported all at once, sorted, so a client can fix its request in one
    round trip.

    Args:
        changes: The fields the amendment replaces, keyed by field name.
        may_reclassify: Whether the caller holds ``metadata.reclassify``;
            consulted only when ``data_classification`` is among the changes.

    Returns:
        A copy of ``changes`` as a plain dict, ready to store or fold.

    Raises:
        AmendmentFieldForbidden: If any field is outside ``AMENDABLE_FIELDS``,
            or ``data_classification`` is changed without ``may_reclassify``.
        ValueError: If ``changes`` is empty.
    """
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
    """Return the effective metadata: ``base`` with every amendment applied in sequence.

    The amendments are sorted by ``sequence`` and must then run 1, 2, 3, ...
    without a gap; a gap means the caller holds an incomplete history, and
    folding what it has would silently yield a document that never existed.
    A later amendment's value for a field wins over an earlier one. Each
    amendment's changes are re-validated with reclassification allowed,
    because whoever stored it was authorized when it was accepted;
    ``AmendmentFieldForbidden`` from that check propagates unchanged.

    Args:
        base: The metadata document the amendments were made against.
        amendments: Every amendment of the entity, in any order.

    Returns:
        A new dict holding the folded document; ``base`` is not modified.

    Raises:
        ValueError: If the sequence numbers do not run from 1 without a gap.
    """
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
