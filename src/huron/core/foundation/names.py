"""Lexical names and identity-bearing path components."""

from __future__ import annotations

import re
from typing import Protocol
from uuid import UUID

from .errors import PathRuleViolation

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,79}$")
TAG = re.compile(r"^[a-z0-9][a-z0-9._-]{1,62}$")
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


def validate_tag(tag: str) -> None:
    """Check a release tag's lexical filename rules.

    Args:
        tag: Candidate tag.

    Raises:
        PathRuleViolation: If the tag violates the lexical rules.
    """
    if not TAG.fullmatch(tag):
        raise PathRuleViolation(f"invalid release tag: {tag!r}")


def split_component(component: str, max_len: int) -> tuple[str, UUID]:
    """Decode an unambiguous slug and lower-case hexadecimal UUID component.

    Args:
        component: Encoded slug--identity directory component.
        max_len: Maximum slug length.

    Returns:
        The slug and UUID.

    Raises:
        PathRuleViolation: If the separator or UUID encoding is invalid.
    """
    slug, separator, hex_id = component.rpartition("--")
    if not separator:
        raise PathRuleViolation(f"unparseable component: {component!r}")
    validate_slug(slug, max_len)
    if len(hex_id) != 32 or hex_id.lower() != hex_id or not re.fullmatch(r"[0-9a-f]{32}", hex_id):
        raise PathRuleViolation(f"invalid path UUID: {hex_id!r}")
    return slug, UUID(hex=hex_id)
