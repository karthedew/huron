"""Stable Raw lake failures, each answering with its own code and status.

Lake codes are raised by lake operations and their persistence adapters only; the
refusals every domain shares (``NOT_FOUND``, ``FORBIDDEN``, ``IDEMPOTENCY_KEY_REUSED``)
belong to :mod:`huron.core.foundation.errors`.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Final

from huron.core.foundation.errors import DomainError
from huron.schema.catalog_config import Problem

if TYPE_CHECKING:
    from collections.abc import Iterable

PROBLEMS_SHOWN: Final = 50


class SchemaInvalid(DomainError):
    """A metadata schema publish names an invalid, uncomposable or out-of-sequence version.

    Problems point into the publish request ``{name, version, extends, json_schema}``.
    The context carries the first fifty in ``(where, rule, message)`` order and the
    total count, so an enormous document cannot produce an enormous answer.
    """

    code, status_code = "SCHEMA_INVALID", 422

    def __init__(self, problems: Iterable[Problem]) -> None:
        """Order and cap the problems that refuse the publish.

        Args:
            problems: Every failure found, in any order.

        Raises:
            ValueError: If no problem was supplied.
        """
        ordered = sorted(problems, key=lambda p: (p.where, p.rule, p.message))
        if not ordered:
            raise ValueError("An invalid schema needs at least one problem")
        super().__init__(
            f"metadata schema is invalid: {len(ordered)} problem(s)",
            context={
                "problems": [asdict(problem) for problem in ordered[:PROBLEMS_SHOWN]],
                "total": len(ordered),
            },
        )

    @classmethod
    def version_gap(cls, version: int, latest: int) -> SchemaInvalid:
        """Refuse a version that does not directly follow its series' latest.

        Args:
            version: The version the publisher stated.
            latest: The series' latest published version, or 0 for a new name.

        Returns:
            The refusal naming the version the series expects next.
        """
        return cls(
            [Problem("/version", "version_gap", f"expected version {latest + 1}, not {version}")]
        )


class SchemaVersionExists(DomainError):
    """The schema name already holds this version, or a later one; published rows never change."""

    code, status_code = "SCHEMA_VERSION_EXISTS", 409

    def __init__(self, name: str, version: int, latest_version: int) -> None:
        """Name the taken version and the series' latest.

        Args:
            name: The schema series.
            version: The version the publisher stated.
            latest_version: The series' latest published version.
        """
        super().__init__(
            f"metadata schema {name} already has version {latest_version}",
            context={"name": name, "version": version, "latest_version": latest_version},
        )


ERROR_CODES = frozenset({"SCHEMA_INVALID", "SCHEMA_VERSION_EXISTS"})

__all__ = ["ERROR_CODES", "PROBLEMS_SHOWN", "SchemaInvalid", "SchemaVersionExists"]
