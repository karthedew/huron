"""Company identity verification over a caller-owned asynchronous HTTP client."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import timedelta
from typing import TYPE_CHECKING, Final

import httpx
import jwt

from huron.core.foundation.errors import AuthError, DependencyUnavailable, DomainError
from huron.core.security.broker._http import absolute_url
from huron.core.security.broker.ladder import Grants
from huron.core.security.broker.tokens import _validate_times

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from huron.core.foundation.clock import Clock
    from huron.core.security.broker.groups import GroupDirectory
    from huron.core.security.broker.ladder import RoleMappingReader
    from huron.core.security.broker.tokens import HuronTokenIssuer, IssuedToken

COMPANY_USERNAME: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@-]{0,127}")
JWKS_TTL: Final = timedelta(minutes=5)
JWKS_REFETCH_FLOOR: Final = timedelta(seconds=60)
COMPANY_ALGORITHMS: Final = ("RS256", "ES256")


def _unavailable(reason: str) -> DependencyUnavailable:
    return DependencyUnavailable(context={"dependency": "company_idp", "reason": reason})


def _public_keys(document: Mapping[str, object]) -> dict[str, jwt.PyJWK]:
    entries = document.get("keys")
    if not isinstance(entries, list):
        raise ValueError("keys must be an array")
    keys = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("a JWK must be an object")
        if entry.get("kty") not in ("RSA", "EC") or entry.get("alg") not in (
            None,
            *COMPANY_ALGORITHMS,
        ):
            continue
        kid = entry.get("kid")
        if not isinstance(kid, str) or not kid:
            raise ValueError("a JWK needs a kid")
        keys[kid] = jwt.PyJWK.from_dict(entry)
    return keys


def _token_header(token: str) -> tuple[str, str]:
    header = jwt.get_unverified_header(token)
    algorithm, kid = header["alg"], header["kid"]
    if algorithm not in COMPANY_ALGORITHMS or not isinstance(kid, str) or not kid:
        raise ValueError("token requires an allowed algorithm and a non-empty kid")
    return algorithm, kid


class CompanyTokenVerifier:
    """Verify company signatures with lazy discovery and bounded key refreshes."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        issuer: str,
        audiences: frozenset[str],
        clock: Clock,
    ) -> None:
        """Capture policy without fetching discovery or taking client ownership.

        Args:
            http: Caller-owned asynchronous client, including timeout policy.
            issuer: Exact absolute company issuer URL without a trailing slash.
            audiences: Nonempty set of accepted client identifiers.
            clock: Source of cache and token validity time.

        Raises:
            ValueError: If the issuer or audiences are invalid.
        """
        if not absolute_url(issuer) or issuer.endswith("/") or "?" in issuer or "#" in issuer:
            raise ValueError(
                "issuer must be an absolute URL without trailing slash, query or fragment"
            )
        if not audiences or any(not isinstance(a, str) or not a for a in audiences):
            raise ValueError("audiences must contain non-empty strings")
        self._http, self._issuer, self._audiences, self._clock = http, issuer, audiences, clock
        self._lock = asyncio.Lock()
        self._jwks_uri: str | None = None
        self._keys: dict[str, jwt.PyJWK] = {}
        self._expires: datetime | None = None
        self._refetched: datetime | None = None

    async def verify(self, token: str) -> Mapping[str, object]:
        """Validate the signature and required claims, returning claims unchanged.

        Discovery and key retrieval failures propagate as DependencyUnavailable.

        Args:
            token: Compact signed company JWT.

        Returns:
            Verified claims without interpreting subject or membership.

        Raises:
            AuthError: If the token cannot be trusted.
        """
        try:
            algorithm, kid = _token_header(token)
            key = await self._key(kid)
            if algorithm != key.algorithm_name:
                raise AuthError("token algorithm does not match its signing key")
            payload = jwt.decode(
                token,
                key.key,
                algorithms=[algorithm],
                issuer=self._issuer,
                audience=list(self._audiences),
                options={
                    "require": ["iss", "aud", "exp", "iat"],
                    "verify_exp": False,
                    "verify_iat": False,
                    "verify_nbf": False,
                    "verify_sub": False,
                    "verify_jti": False,
                },
            )
            _validate_times(payload, self._clock.now())
            return payload
        except (jwt.PyJWTError, KeyError, ValueError) as exc:
            raise AuthError(str(exc)) from exc

    async def _document(self, url: str) -> dict[str, object]:
        try:
            response = await self._http.get(url, headers={"Accept": "application/json"})
        except httpx.TimeoutException as exc:
            raise _unavailable("timeout") from exc
        except httpx.TransportError as exc:
            raise _unavailable("unreachable") from exc
        if response.status_code != 200:
            raise _unavailable("status")
        try:
            document = response.json()
            if not isinstance(document, dict):
                raise ValueError("document must be an object")
            return document
        except ValueError as exc:
            raise _unavailable("malformed") from exc

    async def _discover(self) -> str:
        if self._jwks_uri is None:
            document = await self._document(self._issuer + "/.well-known/openid-configuration")
            if "issuer" not in document or not absolute_url(document.get("jwks_uri")):
                raise _unavailable("malformed")
            if document["issuer"] != self._issuer:
                raise _unavailable("issuer_mismatch")
            self._jwks_uri = str(document["jwks_uri"])
        return self._jwks_uri

    async def _key(self, kid: str) -> jwt.PyJWK:
        async with self._lock:
            now = self._clock.now()
            fresh = self._expires is not None and now < self._expires
            if fresh and kid in self._keys:
                return self._keys[kid]
            if (
                kid not in self._keys
                and self._refetched is not None
                and now < self._refetched + JWKS_REFETCH_FLOOR
            ):
                raise ValueError("unknown kid inside key refresh floor")
            await self._refresh(kid, now)
            if kid not in self._keys:
                raise ValueError("unknown kid after key refresh")
            return self._keys[kid]

    async def _refresh(self, kid: str, now: datetime) -> None:
        self._refetched = now
        document = await self._document(await self._discover())
        try:
            keys = _public_keys(document)
        except (ValueError, TypeError, KeyError, jwt.PyJWTError) as exc:
            raise _unavailable("malformed") from exc
        if self._expires is None and kid in keys:
            self._refetched = None
        self._keys, self._expires = keys, now + JWKS_TTL


class TokenExchange:
    """Exchange verified company identity for current directory-backed Huron claims."""

    def __init__(
        self,
        verifier: CompanyTokenVerifier,
        directory: GroupDirectory,
        mappings: RoleMappingReader,
        issuer: HuronTokenIssuer,
        *,
        subject_claim: str,
    ) -> None:
        """Compose identity verification, current authority and token issuance.

        Args:
            verifier: Company signature and claim verifier.
            directory: Source of current directory membership.
            mappings: Reader of current group-role mappings.
            issuer: Huron signer with loaded key material.
            subject_claim: Company claim containing the verbatim username.
        """
        self._verifier, self._directory = verifier, directory
        self._mappings, self._issuer = mappings, issuer
        self._subject_claim = subject_claim

    async def exchange(self, company_token: str) -> IssuedToken:
        """Resolve identity and current authority before signing, without writes.

        Args:
            company_token: Compact company token whose own groups are ignored.

        Returns:
            Huron token carrying every directory group and current roles.

        Raises:
            AuthError: If verification, username validation or user lookup fails.
            DomainError: If a dependency or signing material is unavailable.
        """
        facts: dict[str, object] = {
            "subject": None,
            "outcome": "INTERNAL_ERROR",
            "group_count": None,
            "role_count": None,
            "kid": None,
        }
        logger = logging.getLogger(__name__)
        try:
            claims = await self._verifier.verify(company_token)
            subject = claims.get(self._subject_claim)
            if not isinstance(subject, str) or COMPANY_USERNAME.fullmatch(subject) is None:
                raise AuthError(f"company token has no usable {self._subject_claim}")
            facts["subject"] = subject
            groups = await self._directory.groups_for(subject)
            if groups is None:
                raise AuthError(f"{subject} is unknown to the group directory")
            facts["group_count"] = len(groups)
            if len(groups) > 100:
                logger.warning(
                    "auth.exchange.large_groups",
                    extra={"subject": subject, "group_count": len(groups)},
                )
            grants = Grants(subject, await self._mappings.roles_for_groups(groups))
            facts["role_count"] = len(tuple(grants))
            issued = self._issuer.issue(subject, groups, grants)
            facts.update(outcome="issued", kid=issued.claims.kid)
            return issued
        except (AuthError, DomainError) as exc:
            facts["outcome"] = exc.code
            raise
        finally:
            logger.info("auth.exchange", extra=facts)
