"""OIDC login state verification, identity provisioning and durable session issuance."""

from __future__ import annotations

import hmac
from typing import TYPE_CHECKING

from huron.core.security.authentication_errors import AuthError
from huron.core.security.errors import OidcNotConfigured, UsernameTaken
from huron.core.security.oidc import LoginFlow, code_challenge_s256
from huron.core.security.principals import PrincipalSubjectExists
from huron.core.security.sessions import create_session
from huron.core.security.types import LoginSession, OidcLoginResult, OidcLoginStart

if TYPE_CHECKING:
    from huron.core.foundation.clock import Clock
    from huron.core.security.oidc import OidcClient
    from huron.core.security.principals import PrincipalStore
    from huron.core.security.sessions import SessionStore


class OidcAuthentication:
    """Own the complete code flow; applications transport its signed state and secrets."""

    def __init__(
        self,
        client: OidcClient | None,
        principals: PrincipalStore,
        sessions: SessionStore,
        *,
        clock: Clock,
        flow_secret: bytes,
        flow_max_age: int = 600,
    ) -> None:
        """Bind provider verification, persistence and pending-login lifetime.

        Args:
            client: Configured provider, absent when OIDC login is unavailable.
            principals: Identity provisioning without automatic account linking.
            sessions: Issued-session persistence.
            clock: Flow and session time source.
            flow_secret: Key for pending-login state signatures.
            flow_max_age: Maximum pending-login age in seconds.

        Raises:
            OidcNotConfigured: If no provider is available.
        """
        if client is None:
            raise OidcNotConfigured("no identity provider is configured")
        self._client = client
        self._principals = principals
        self._sessions = sessions
        self._clock = clock
        self._flow_secret = flow_secret
        self._flow_max_age = flow_max_age

    def begin(self, *, return_to: str = "/") -> OidcLoginStart:
        """Create signed state, nonce and PKCE proof for a provider login.

        Args:
            return_to: Transport-sanitized local return path.

        Returns:
            Provider target and signed pending state.
        """
        flow = LoginFlow.new(return_to=return_to, now=self._clock.now())
        url = self._client.authorization_url(
            state=flow.state,
            nonce=flow.nonce,
            code_challenge=code_challenge_s256(flow.code_verifier),
        )
        return OidcLoginStart(url, flow.encode(self._flow_secret))

    async def finish(self, *, flow_token: str, code: str, state: str) -> OidcLoginResult:
        """Verify the flow and provider code, provision identity and persist a session.

        Args:
            flow_token: Signed pending-login state returned by the caller.
            code: Provider authorization code.
            state: Provider echo of the flow state.

        Returns:
            Persisted login and authenticated local return path.

        Raises:
            AuthError: If state differs or the provisioned identity is disabled.
            UsernameTaken: If a local identity already reserves the provider subject.
        """
        flow = LoginFlow.decode(
            flow_token, self._flow_secret, max_age=self._flow_max_age, now=self._clock.now()
        )
        if not hmac.compare_digest(state, flow.state):
            raise AuthError("OIDC state mismatch")
        user = await self._client.exchange_code(
            code=code, code_verifier=flow.code_verifier, nonce=flow.nonce
        )
        try:
            principal = await self._principals.upsert_oidc_user(user)
        except PrincipalSubjectExists as exc:
            raise UsernameTaken(str(exc)) from exc
        if principal.disabled_at is not None:
            raise AuthError(f"principal is disabled: {principal.subject}")
        record, token = create_session(
            principal.subject,
            groups=user.groups,
            authentication_method="oidc",
            now=self._clock.now(),
        )
        await self._sessions.add(record)
        return OidcLoginResult(LoginSession(record, token, principal.display_name), flow.return_to)
