"""Company username and group mapping after asynchronous bearer verification."""

import pytest

from huron.core.foundation.errors import AuthError
from huron.core.security.oidc import OidcResolver

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("username", ["alice", "Karl.Schmidt@corp", "a" * 128])
@pytest.mark.parametrize("groups", [None, [], ["physics", "physics", "math"]])
async def test_oidc_resolver_maps_explicit_claims(username, groups) -> None:
    """Configured claims preserve username spelling and normalize group membership."""

    async def verify(token):
        assert token == "bearer"
        claims = {"login": username, "sub": "opaque-id"}
        if groups is not None:
            claims["teams"] = groups
        return claims

    principal = await OidcResolver(verify, subject_claim="login", groups_claim="teams").resolve(
        "bearer"
    )
    assert principal.subject == username
    assert principal.groups == frozenset(groups or [])
    assert principal.authentication_method == "oidc"
    assert principal.scopes == frozenset()
    assert principal.project_id is None


@pytest.mark.parametrize(
    "claims",
    [
        {},
        {"sub": "opaque-id"},
        {"preferred_username": None},
        {"preferred_username": 1},
        {"preferred_username": ""},
        *(
            {"preferred_username": name}
            for name in ["a" * 129, " bad", "bad/actor", "bad%actor", "bad\n", "_bad"]
        ),
        {"preferred_username": "alice", "groups": "physics"},
        {"preferred_username": "alice", "groups": [1]},
    ],
)
async def test_oidc_resolver_refuses_invalid_principal_claims(claims) -> None:
    """Invalid usernames and malformed group claims never establish a principal."""

    async def verify(token):
        return claims

    with pytest.raises(AuthError):
        await OidcResolver(verify, subject_claim="preferred_username").resolve("bearer")


async def test_oidc_resolver_propagates_verification_refusal() -> None:
    """A verifier refusal cannot fall through to claim mapping."""

    async def verify(token):
        raise AuthError("refused")

    with pytest.raises(AuthError, match="refused"):
        await OidcResolver(verify, subject_claim="preferred_username").resolve("bearer")
