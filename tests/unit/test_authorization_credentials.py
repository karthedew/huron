"""Bearer credential precedence and production refusal without a credential."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from starlette.requests import Request

from huron.applications.api.authorization import current_principal
from huron.applications.api.runtime import ApiRuntime
from huron.applications.api.settings import ApiSettings, ClassificationValue, OidcSettings
from huron.core.foundation.errors import AuthError
from huron.core.metastore import SystemClock
from huron.core.rawstore import PosixGenerationStore
from huron.core.security.oidc import OidcResolver
from huron.core.security.rules import RoleBindingAuthorizer
from tests.unit.support import memory_stores

if TYPE_CHECKING:
    from pathlib import Path

    from huron.applications.api.runtime import ApiStores

pytestmark = pytest.mark.unit


def _request(
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
) -> Request:
    """A request with the given method, headers and cookies, as a real Starlette Request."""
    raw_headers = [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()]
    if cookies:
        cookie_header = "; ".join(f"{key}={value}" for key, value in cookies.items())
        raw_headers.append((b"cookie", cookie_header.encode()))
    scope = {"type": "http", "method": method, "path": "/", "headers": raw_headers, "app": None}
    return Request(scope)


def _generations(tmp_path: Path) -> PosixGenerationStore:
    """An initialized, filesystem-backed generation store under ``tmp_path``."""
    store = PosixGenerationStore(tmp_path / "raw")
    store.initialize()
    return store


def _runtime(
    *, generations: PosixGenerationStore, stores: ApiStores, settings: ApiSettings
) -> ApiRuntime:
    """An ApiRuntime wired to the given generation store and stores, with no OIDC configured."""
    return ApiRuntime(
        settings=settings,
        generations=generations,
        hierarchy=stores.hierarchy,
        rbac=stores.rbac,
        authorizer=RoleBindingAuthorizer(),
        api_keys=stores.api_keys,
        principals=stores.principals,
        oidc_resolver=None,
        database_pool=None,
        clock=SystemClock(),
    )


def _settings(*, env: str) -> ApiSettings:
    """``ApiSettings`` for dev-headers in development, or a configured OIDC provider otherwise."""
    kwargs: dict[str, object] = {
        "env": env,
        "database_url": "postgresql://unused",
        "classification_vocabulary": [ClassificationValue(code="open", order=0, discoverable=True)],
    }
    if env == "development":
        kwargs["auth_mode"] = "dev-headers"
    else:
        kwargs["auth_mode"] = "oidc"
        kwargs["oidc"] = OidcSettings(
            issuer="https://idp.example",
            client_id="huron-web",
        )
    return ApiSettings(**kwargs)


# -- current_principal: bearer priority -------------------------------------


async def test_current_principal_never_downgrades_a_bearer_caller_to_its_cookie(
    tmp_path: Path,
) -> None:
    """A bearer token takes priority over a cookie even when the bearer path itself then fails.

    A programmatic caller with both a bearer token and a cookie jar must
    be resolved as the bearer credential, even when that bearer path then
    fails - it must never silently fall through to the cookie.
    """
    stores = memory_stores()
    generations = _generations(tmp_path)
    runtime = _runtime(
        generations=generations, stores=stores, settings=_settings(env="development")
    )

    request = _request(
        method="GET",
        headers={"Authorization": "Bearer some.jwt.token"},
        cookies={"irrelevant": "ignored"},
    )
    with pytest.raises(AuthError, match="no OIDC verifier configured"):
        await current_principal(request, runtime)


async def test_current_principal_resolves_a_bearer_jwt_through_the_configured_verifier(
    tmp_path: Path,
) -> None:
    """A bearer JWT resolves through the configured OIDC verifier to its principal."""
    stores = memory_stores()
    generations = _generations(tmp_path)

    async def verify(_token):
        return {"sub": "carol", "groups": ["astro"]}

    resolver = OidcResolver(verify, subject_claim="sub")
    runtime = ApiRuntime(
        settings=_settings(env="production"),
        generations=generations,
        hierarchy=stores.hierarchy,
        rbac=stores.rbac,
        authorizer=RoleBindingAuthorizer(),
        api_keys=stores.api_keys,
        principals=stores.principals,
        oidc_resolver=resolver,
        database_pool=None,
        clock=SystemClock(),
    )

    request = _request(method="GET", headers={"Authorization": "Bearer some.jwt.token"})
    principal = await current_principal(request, runtime)

    assert principal.subject == "carol"
    assert principal.groups == frozenset({"astro"})


async def test_current_principal_refuses_an_oidc_deployment_with_no_credential_at_all(
    tmp_path: Path,
) -> None:
    """A request with no bearer token is refused outside development authentication.

    Outside ``dev-headers``, an absent bearer credential never enables
    the development header resolver.
    """
    stores = memory_stores()
    generations = _generations(tmp_path)
    runtime = _runtime(generations=generations, stores=stores, settings=_settings(env="production"))

    request = _request(method="GET")
    with pytest.raises(AuthError, match="a bearer credential is required"):
        await current_principal(request, runtime)
