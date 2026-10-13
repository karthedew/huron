"""Short-lived, request-bound authority delegated by the authenticated web server."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Literal
from uuid import UUID

import jwt
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from huron.core.foundation.errors import ResourceNotFound
from huron.core.security.authentication_errors import AuthError
from huron.core.security.errors import Forbidden
from huron.core.security.principal import Principal
from huron.core.security.rules import Binding, ScopeType

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping

    from huron.core.security.types import ServiceAccount


NamespaceSegment = Annotated[str, Field(min_length=1, max_length=256)]
_RAW_BRIDGE_KEY: TypeAdapter[bytes] = TypeAdapter(Annotated[bytes, Field(min_length=32)])


def raw_bridge_key(secret: str) -> bytes:
    """Validate and encode a deployment's private delegation signing key.

    Args:
        secret: Configured secret, never a browser credential.

    Returns:
        At least 32 UTF-8 bytes for the signing algorithm.
    """
    return _RAW_BRIDGE_KEY.validate_python(secret.encode())


class DelegationTarget(BaseModel):
    """The exact upstream catalog object authorized by the web server."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    endpoint: str = Field(min_length=1, max_length=2048)
    realm: str = Field(min_length=1, max_length=256)
    catalog: str = Field(min_length=1, max_length=256)
    namespace: tuple[NamespaceSegment, ...] = Field(max_length=32)
    name: str = Field(min_length=1, max_length=256)


class _Claims(BaseModel):
    """Validated claims following cryptographic verification."""

    model_config = ConfigDict(extra="forbid")

    iss: Literal["huron-web"]
    aud: Literal["huron-raw"]
    sub: str
    iat: int
    exp: int
    method: str
    path: str
    body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    headers: dict[str, str]
    target: DelegationTarget
    permissions: frozenset[Literal["read", "write", "create"]]


@dataclass(frozen=True, slots=True)
class RawDelegation:
    """An authenticated actor and its bounded authority for one HTTP request."""

    actor: Principal
    target: DelegationTarget
    permissions: frozenset[str]
    expires_at: datetime
    body_sha256: str

    def require(self, permission: str) -> None:
        """Require one delegated capability before executing its domain operation.

        Args:
            permission: The required read, write or create capability.

        Raises:
            Forbidden: If the request lacks the capability.
        """
        if permission not in self.permissions:
            raise Forbidden("the delegated request does not permit this operation")

    def require_scope(
        self, *, target: DelegationTarget | None = None, owner: str | None = None
    ) -> None:
        """Hide resources whose persisted target or owner differs from this request.

        Args:
            target: Authoritative external mapping, when resolving a dataset.
            owner: Authoritative session owner, when resolving an upload.

        Raises:
            ResourceNotFound: If either supplied fact is outside the delegated scope.
        """
        if (target is not None and target != self.target) or (
            owner is not None and owner != self.actor.subject
        ):
            raise ResourceNotFound("no such Raw resource")

    def verify_body(self, body: bytes) -> None:
        """Verify the request body before dispatching a JSON operation.

        Args:
            body: Exact received bytes.

        Raises:
            AuthError: If the body differs from the signed request.
        """
        if not hmac.compare_digest(hashlib.sha256(body).hexdigest(), self.body_sha256):
            raise AuthError("delegated request body does not match")

    def verified_chunks(self, chunks: Iterable[bytes]) -> Iterator[bytes]:
        """Verify a streamed transfer before its consumer records successful completion.

        Args:
            chunks: Unbuffered transfer bytes.

        Yields:
            Each chunk unchanged.

        Raises:
            AuthError: After consumption if bytes differ from the signed request.
        """
        digest = hashlib.sha256()
        for chunk in chunks:
            digest.update(chunk)
            yield chunk
        if not hmac.compare_digest(digest.hexdigest(), self.body_sha256):
            raise AuthError("delegated transfer body does not match")


class RawDelegationVerifier:
    """Verify the trusted BFF's signature, lifetime, actor and exact request binding."""

    def __init__(self, secret: str) -> None:
        """Configure the private shared signing key.

        Args:
            secret: At least 32 UTF-8 bytes, never a browser credential.

        """
        self._secret = raw_bridge_key(secret)

    def verify(
        self, token: str, *, method: str, path: str, headers: Mapping[str, str]
    ) -> RawDelegation:
        """Authenticate a signed request without trusting caller-supplied identity headers.

        Args:
            token: The compact signed JWT.
            method: Actual uppercase HTTP method.
            path: Actual URL path, including its query string.
            headers: Actual lowercase retry and precondition headers.

        Returns:
            The verified actor and request authority.

        Raises:
            AuthError: If any signature, claim or request binding is invalid.
        """
        try:
            decoded = jwt.decode(
                token,
                self._secret,
                algorithms=["HS256"],
                issuer="huron-web",
                audience="huron-raw",
                options={"require": ["iss", "aud", "sub", "iat", "exp"]},
            )
            claims = _Claims.model_validate(decoded)
            subject = claims.sub.removeprefix("huron-web:")
            UUID(subject)
        except (jwt.PyJWTError, ValidationError, ValueError) as error:
            raise AuthError("invalid Raw web delegation") from error
        expected = {key: value for key, value in headers.items() if value}
        valid = (
            claims.sub == f"huron-web:{subject}"
            and 0 < claims.exp - claims.iat <= 60
            and claims.method == method
            and claims.path == path
            and claims.headers == expected
        )
        if not valid:
            raise AuthError("Raw web delegation does not match this request")
        return RawDelegation(
            Principal(claims.sub, authentication_method="web-delegation"),
            claims.target,
            frozenset(claims.permissions),
            datetime.fromtimestamp(claims.exp, UTC),
            claims.body_sha256,
        )


class DelegatedBindings:
    """Request-local grants; no persistent roles or service-account authority."""

    def __init__(self, bindings: tuple[Binding, ...]) -> None:
        """Bind this request's verified grants.

        Args:
            bindings: Exact grants constructed from authenticated authority.
        """
        self._bindings = bindings

    async def bindings_for(self, identifiers: frozenset[str]) -> tuple[Binding, ...]:
        """Return only grants naming this actor.

        Args:
            identifiers: Authenticated subject identifiers.

        Returns:
            The matching grants.
        """
        return tuple(item for item in self._bindings if item.principal in identifiers)

    async def service_account_by_subject(self, subject: str) -> ServiceAccount:
        """Refuse all service-account authority.

        Args:
            subject: The requested service-account name.

        Returns:
            Never returns a service account.

        Raises:
            ResourceNotFound: Always; this bridge delegates human authority only.
        """
        raise ResourceNotFound("no delegated service account")


def raw_dataset_bindings(delegation: RawDelegation, dataset_id: UUID) -> DelegatedBindings:
    """Project verified web authority onto the existing Raw authorization policy.

    Args:
        delegation: Cryptographically verified human authority.
        dataset_id: The stored mapping's exact dataset identity.

    Returns:
        Expiring dataset-scoped discovery and Raw read/write grants.
    """
    capabilities = {"dataset.discover"}
    capabilities.update(f"data.{item}" for item in delegation.permissions & {"read", "write"})
    return DelegatedBindings(
        (
            Binding(
                principal=f"user:{delegation.actor.subject}",
                capabilities=frozenset(capabilities),
                scope_type=ScopeType.DATASET,
                scope_id=dataset_id,
                expires_at=delegation.expires_at,
                layers=frozenset({"raw"}),
            ),
        )
    )
