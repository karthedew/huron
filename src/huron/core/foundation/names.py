"""Lexical names and identity-bearing path components."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Protocol

from .errors import PathRuleViolation

if TYPE_CHECKING:
    from uuid import UUID

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,79}$")
ORG_PROJECT_SLUG_MAX = 62
DATASET_SLUG_MAX = 80
RESERVED_ROOT_SLUGS = frozenset(
    {
        "admin",
        "browse",
        "account",
        "queue",
        "product",
        "polaris",
        "snapshot",
        "search",
        "api",
        "auth",
        "login",
        "logout",
        "signup",
        "settings",
        "ingestion",
    }
)


class Slugged(Protocol):
    """Read-only identity and slug accepted by layout constructors."""

    @property
    def id(self) -> UUID:
        """The entity identity."""
        ...

    @property
    def slug(self) -> str:
        """The path-safe stable name."""
        ...


def validate_slug(slug: str, max_len: int) -> None:
    """Check a lower-case slug without an ambiguous double-hyphen separator.

    Args:
        slug: Candidate name.
        max_len: Maximum accepted length.

    Raises:
        PathRuleViolation: If the slug violates the lexical or length rules.
    """
    if max_len < 2 or not SLUG.fullmatch(slug) or "--" in slug or len(slug) > max_len:
        raise PathRuleViolation(f"invalid slug: {slug!r}")


def validate_org_slug(slug: str) -> None:
    """Check an organization slug, including reserved root-route names.

    Args:
        slug: Candidate organization name.

    Raises:
        PathRuleViolation: If the name shadows a reserved root route.
    """
    validate_slug(slug, ORG_PROJECT_SLUG_MAX)
    if slug in RESERVED_ROOT_SLUGS:
        raise PathRuleViolation(f"reserved organization slug: {slug!r}")
