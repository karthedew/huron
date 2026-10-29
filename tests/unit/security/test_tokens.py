"""Signing keys, Huron tokens, discovery."""

from datetime import timedelta

import jwt
import pytest

from huron.core.security.broker import (
    KeyRing,
    TokenInvalid,
    TokenIssuer,
    TokenVerifier,
    discovery_document,
    generate_key,
)
from huron.core.security.broker.keys import thumbprint
from huron.pkg.clock import FrozenClock
from tests.support.clock import frozen

ISS, AUD = "https://huron.test", "huron"


def make(
    clock: FrozenClock, *, overlap: timedelta = timedelta(hours=1)
) -> tuple[KeyRing, TokenIssuer, TokenVerifier]:
    ring = KeyRing([generate_key(clock)], overlap, clock)
    return (
        ring,
        TokenIssuer(ring, clock, ISS, AUD, timedelta(hours=8)),
        TokenVerifier(ring, ISS, AUD, clock),
    )


def test_generated_keys_derive_their_kid_from_the_thumbprint() -> None:
    key = generate_key(frozen())
    assert key.kid == thumbprint(key.public_jwk)[:16]
    assert key.public_jwk["alg"] == "ES256"
    assert "BEGIN PRIVATE KEY" in key.private_pem


def test_issued_tokens_verify_and_carry_sorted_groups() -> None:
    clock = frozen()
    ring, issuer, verifier = make(clock)
    token, claims = issuer.issue("dave", "Dave", ["b", "a", "a"])
    assert claims.groups == ("a", "b")
    verified = verifier.verify(token)
    assert verified == claims
    assert jwt.get_unverified_header(token)["kid"] == ring.current.kid


def test_a_token_verifies_with_only_the_published_jwks() -> None:
    clock = frozen()
    ring, issuer, _ = make(clock)
    token, _ = issuer.issue("dave", "Dave", ["g"])
    public = jwt.PyJWK(ring.jwks()["keys"][0])
    payload = jwt.decode(
        token,
        public.key,
        algorithms=["ES256"],
        audience=AUD,
        options={"verify_exp": False, "verify_iat": False},
    )
    assert payload["sub"] == "dave"


def test_expired_tokens_are_refused() -> None:
    clock = frozen()
    _, issuer, verifier = make(clock)
    token, _ = issuer.issue("dave", "Dave", [])
    clock.advance(timedelta(hours=8))
    with pytest.raises(TokenInvalid, match="expired"):
        verifier.verify(token)


@pytest.mark.parametrize(
    "mutation", ["issuer", "audience", "unknown_key", "garbage", "hs256", "groups", "missing"]
)
def test_tokens_that_do_not_match_are_refused(mutation: str) -> None:
    clock = frozen()
    ring, issuer, verifier = make(clock)
    key = ring.current
    payload = {
        "sub": "s",
        "name": "n",
        "groups": ["g"],
        "iss": ISS,
        "aud": AUD,
        "iat": 1,
        "exp": 4_000_000_000,
        "jti": "j",
    }
    headers = {"kid": key.kid}
    token: str
    if mutation == "issuer":
        token = jwt.encode({**payload, "iss": "other"}, key.private_pem, "ES256", headers)
    elif mutation == "audience":
        token = jwt.encode({**payload, "aud": "other"}, key.private_pem, "ES256", headers)
    elif mutation == "unknown_key":
        token = jwt.encode(payload, generate_key(clock).private_pem, "ES256", {"kid": "nope"})
    elif mutation == "garbage":
        token = "not.a.token"
    elif mutation == "hs256":
        token = jwt.encode(payload, "x" * 32, "HS256", headers)
    elif mutation == "groups":
        token = jwt.encode({**payload, "groups": "g"}, key.private_pem, "ES256", headers)
    else:
        del payload["jti"]
        token = jwt.encode(payload, key.private_pem, "ES256", headers)
    with pytest.raises(TokenInvalid) as raised:
        verifier.verify(token)
    assert raised.value.status == 401
    assert issuer is not None


def test_retired_keys_verify_within_the_overlap_only() -> None:
    clock = frozen()
    old = generate_key(clock)
    ring = KeyRing([old], timedelta(minutes=30), clock)
    token, _ = TokenIssuer(ring, clock, ISS, AUD, timedelta(hours=8)).issue("u", "U", [])
    clock.advance(timedelta(minutes=1))
    new = generate_key(clock)
    rotated = KeyRing([old.retire(clock.now()), new], timedelta(minutes=30), clock)
    assert rotated.current.kid == new.kid
    verifier = TokenVerifier(rotated, ISS, AUD, clock)
    assert verifier.verify(token).sub == "u"
    assert {key["kid"] for key in rotated.jwks()["keys"]} == {old.kid, new.kid}
    clock.advance(timedelta(minutes=31))
    with pytest.raises(TokenInvalid, match="unknown key"):
        verifier.verify(token)
    assert rotated.find(old.kid) is None


def test_a_ring_without_an_active_key_has_no_current_key() -> None:
    clock = frozen()
    ring = KeyRing([generate_key(clock).retire(clock.now())], timedelta(0), clock)
    with pytest.raises(LookupError):
        _ = ring.current


def test_discovery_document_points_at_the_jwks() -> None:
    document = discovery_document("https://huron.test/")
    assert document["issuer"] == "https://huron.test/"
    assert document["jwks_uri"] == "https://huron.test/jwks.json"
    assert document["id_token_signing_alg_values_supported"] == ["ES256"]
