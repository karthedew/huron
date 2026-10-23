"""Keyset windows that any store can return for a collection it pages."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Window[ItemT]:
    """A visibility-filtered keyset page and whether another visible row follows."""

    items: list[ItemT]
    has_more: bool
