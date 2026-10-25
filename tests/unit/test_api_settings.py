"""``ApiSettings``' deploy-time refusals, one unsafe combination at a time.

Every unsafe combination the validators exist to catch is exercised
once, so a future edit that silently drops one is caught here rather
than at startup in production.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from huron.applications.api.settings import ApiSettings, ClassificationValue, OidcSettings

pytestmark = pytest.mark.unit


def _kwargs(**overrides: object) -> dict[str, object]:
    """The baseline ``ApiSettings`` constructor kwargs, merged with any overrides given."""
    base: dict[str, object] = {
        "env": "development",
        "auth_mode": "dev-headers",
        "database_url": "postgresql://unused",
        "classification_vocabulary": [ClassificationValue(code="open", order=0, discoverable=True)],
    }
    base.update(overrides)
    return base


def test_defaults_construct_a_working_development_configuration() -> None:
    """The default constructor kwargs produce a working development configuration."""
    settings = ApiSettings(**_kwargs())
    assert "store_backend" not in ApiSettings.model_fields
    assert settings.password_login_enabled is True
    assert settings.session_cookie_name == "huron_session"
    assert settings.oidc is None


def test_dev_headers_are_refused_outside_development() -> None:
    """``dev-headers`` auth mode is refused outside a development environment."""
    with pytest.raises(ValidationError, match="dev-headers auth is refused"):
        ApiSettings(**_kwargs(env="production", login_flow_secret="s"))


def test_oidc_auth_mode_requires_oidc_settings() -> None:
    """``oidc`` auth mode is refused unless OIDC settings supply the required config."""
    with pytest.raises(ValidationError, match="requires the HURON_OIDC__"):
        ApiSettings(**_kwargs(auth_mode="oidc"))


def test_oidc_auth_mode_succeeds_once_oidc_settings_are_supplied() -> None:
    """Supplying OIDC settings allows ``oidc`` auth mode, with default audience and scopes."""
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
    """An empty ``login_flow_secret`` is refused outside development, where it is required."""
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
    """An empty ``login_flow_secret`` is accepted in development, where it is optional."""
    settings = ApiSettings(**_kwargs(login_flow_secret=""))
    assert settings.login_flow_secret == ""


def test_classification_codes_must_be_unique() -> None:
    """Two classification values sharing a code are refused as non-unique."""
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
    """Two classification values sharing an order are refused as non-unique."""
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
    """An empty classification vocabulary is refused outright."""
    with pytest.raises(ValidationError, match="classification vocabulary may not be empty"):
        ApiSettings(**_kwargs(classification_vocabulary=[]))
