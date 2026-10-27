"""Legacy company bearer-token claim mapping."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.foundation.errors import AuthError

from .broker import COMPANY_USERNAME
from .principal import Principal

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping


class OidcResolver:
    """Resolve a token after an injected verifier has validated its signature.

    The resolver owns no cryptography: ``verify`` is whatever turns a raw
    token into trusted claims asynchronously, and
    the resolver only maps those claims to a :class:`Principal`. The split
    keeps the claim-shape rules testable without keys and lets the
    composition root choose which claims name the subject and the groups.
    """

    def __init__(
        self,
        verify: Callable[[str], Awaitable[Mapping[str, object]]],
        *,
        subject_claim: str,
        groups_claim: str = "groups",
    ):
        """Bind the resolver to a verifier and the claims it reads.

        Args:
            verify: Turns a raw bearer token into its claims, raising
                :class:`AuthError` for a token that must not be trusted.
            subject_claim: The claim naming the principal's subject.
            groups_claim: The claim carrying the principal's groups as a
                list of strings.
        """
        self.verify = verify
        self.subject_claim = subject_claim
        self.groups_claim = groups_claim

    async def resolve(self, credential: str) -> Principal:
        """Verify a bearer token and map its claims to a principal.

        The subject claim must be a valid company username and the groups claim, when
        present, a list of strings; a missing groups claim resolves to an
        empty set rather than an error, so a provider that issues none
        still yields a usable principal. A token the verifier rejects
        propagates its error unchanged.

        Args:
            credential: The raw bearer token.

        Returns:
            A principal with the token's subject and groups and
            ``authentication_method`` ``"oidc"``; no scopes and no project
            restriction.

        Raises:
            AuthError: If the subject claim is not a company username, or the groups
                claim is present but not a list of strings.
        """
        claims = await self.verify(credential)
        subject = claims.get(self.subject_claim)
        groups = claims.get(self.groups_claim, [])
        if (
            not isinstance(subject, str)
            or COMPANY_USERNAME.fullmatch(subject) is None
            or not isinstance(groups, list)
            or not all(isinstance(group, str) for group in groups)
        ):
            raise AuthError("OIDC token has invalid principal claims")
        return Principal(
            subject=subject,
            groups=frozenset(groups),
            authentication_method="oidc",
        )


__all__ = ["OidcResolver"]
