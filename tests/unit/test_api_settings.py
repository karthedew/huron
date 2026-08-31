"""``ApiSettings``' deploy-time refusals: every unsafe combination the
validator exists to catch, exercised once each so a future edit that
silently drops one is caught here rather than at startup in production."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from huron.service.api.settings import ApiSettings, ClassificationValue, OidcSettings

pytestmark = pytest.mark.unit


def _kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "env": "development",
        "auth_mode": "dev-headers",
        "database_url": "postgresql://unused",
        "classification_vocabulary": [ClassificationValue(code="open", order=0, discoverable=True)],
    }
    base.update(overrides)
    return base


def test_defaults_construct_a_working_development_configuration() -> None:
    settings = ApiSettings(**_kwargs())
    assert settings.store_backend == "memory"
    assert settings.password_login_enabled is True
    assert settings.session_cookie_name == "huron_session"
    assert settings.oidc is None


def test_dev_headers_are_refused_outside_development() -> None:
    with pytest.raises(ValidationError, match="dev-headers auth is refused"):
        ApiSettings(**_kwargs(env="production", login_flow_secret="s"))


def test_oidc_auth_mode_requires_oidc_settings() -> None:
    with pytest.raises(ValidationError, match="requires the HURON_OIDC__"):
        ApiSettings(**_kwargs(auth_mode="oidc"))


def test_oidc_auth_mode_succeeds_once_oidc_settings_are_supplied() -> None:
    settings = ApiSettings(
        **_kwargs(
            auth_mode="oidc",
            oidc=OidcSettings(
                issuer="https://idp.example",
                client_id="huron-web",
                client_secret="shh",
                redirect_url="https://app.example/auth/oidc/callback",
            ),
        )
    )
    assert settings.oidc is not None
    assert settings.oidc.audience is None
    assert settings.oidc.scopes == ("openid", "profile", "email")


def test_login_flow_secret_is_required_outside_development() -> None:
    with pytest.raises(ValidationError, match="login_flow_secret is required"):
        ApiSettings(
            **_kwargs(
                env="staging",
                auth_mode="oidc",
                login_flow_secret="",
                oidc=OidcSettings(
                    issuer="https://idp.example",
                    client_id="huron-web",
                    client_secret="shh",
                    redirect_url="https://app.example/auth/oidc/callback",
                ),
            )
        )


def test_login_flow_secret_is_optional_in_development() -> None:
    settings = ApiSettings(**_kwargs(login_flow_secret=""))
    assert settings.login_flow_secret == ""


def test_classification_codes_must_be_unique() -> None:
    with pytest.raises(ValidationError, match="classification codes must be unique"):
        ApiSettings(
            **_kwargs(
                classification_vocabulary=[
                    ClassificationValue(code="open", order=0, discoverable=True),
                    ClassificationValue(code="open", order=1, discoverable=False),
                ]
            )
        )


def test_classification_orders_must_be_unique() -> None:
    with pytest.raises(ValidationError, match="classification orders must be unique"):
        ApiSettings(
            **_kwargs(
                classification_vocabulary=[
                    ClassificationValue(code="open", order=0, discoverable=True),
                    ClassificationValue(code="restricted", order=0, discoverable=False),
                ]
            )
        )


def test_classification_vocabulary_may_not_be_empty() -> None:
    with pytest.raises(ValidationError, match="classification vocabulary may not be empty"):
        ApiSettings(**_kwargs(classification_vocabulary=[]))
