"""Verified lake identity with authority resolved from current group mappings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from huron.core.security.broker.ladder import Grants

if TYPE_CHECKING:
    from huron.core.security.broker.ladder import RoleMappingReader
    from huron.core.security.broker.tokens import HuronTokenVerifier


@dataclass(frozen=True, slots=True)
class Actor:
    """Immutable signed identity and current authority for one request."""

    subject: str
    groups: frozenset[str]
    grants: Grants


class LakeAuthentication:
    """Authenticate signed identity before reading its current scoped authority."""

    def __init__(self, verifier: HuronTokenVerifier, mappings: RoleMappingReader) -> None:
        """Capture the token verifier and current mapping reader.

        Args:
            verifier: Verifier for the trusted Huron issuer and signing keys.
            mappings: Reader of current directory-group role mappings.
        """
        self._verifier = verifier
        self._mappings = mappings

    async def authenticate(self, token: str) -> Actor:
        """Verify a token and resolve its groups once without caching authority.

        Args:
            token: Compact Huron JWT presented by the caller.

        Returns:
            Immutable identity with grants from the current mappings.
        """
        claims = self._verifier.verify(token)
        groups = frozenset(claims.groups)
        rows = await self._mappings.roles_for_groups(groups)
        return Actor(subject=claims.sub, groups=groups, grants=Grants(claims.sub, rows))
