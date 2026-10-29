"""The authenticated caller of an operation."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Actor"]


@dataclass(frozen=True, slots=True)
class Actor:
    """A user identified by their subject, with the LDAP groups captured at login."""

    subject: str
    display_name: str
    groups: frozenset[str]
