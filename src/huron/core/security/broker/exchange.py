"""Exchange a company ID token for a Huron token carrying the user's LDAP groups."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from huron.core.security.broker.company import CompanyTokenVerifier
    from huron.core.security.broker.groups import GroupDirectory
    from huron.core.security.broker.tokens import HuronClaims, TokenIssuer

__all__ = ["ExchangeResult", "TokenExchange"]

_log = structlog.get_logger()


@dataclass(frozen=True, slots=True)
class ExchangeResult:
    """A Huron token and its claims."""

    token: str
    claims: HuronClaims


class TokenExchange:
    """Verifies a company token, looks up groups and issues a Huron token."""

    def __init__(
        self, company: CompanyTokenVerifier, groups: GroupDirectory, issuer: TokenIssuer
    ) -> None:
        self._company = company
        self._groups = groups
        self._issuer = issuer

    async def exchange(self, company_token: str) -> ExchangeResult:
        """Return a Huron token for the user named by ``company_token``."""
        identity = await self._company.verify(company_token)
        groups = await self._groups.groups_for(identity.username)
        token, claims = self._issuer.issue(identity.username, identity.display_name, groups)
        _log.info("broker.exchange", subject=claims.sub, group_count=len(claims.groups))
        return ExchangeResult(token, claims)
