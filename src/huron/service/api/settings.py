"""API configuration and deploy-time safety refusals.

Every setting is read from the ``HURON_*`` environment, with ``__``
separating the levels of a nested model (``HURON_OIDC__ISSUER`` populates
``ApiSettings.oidc.issuer``). Validation happens when the settings object
is built, before anything is wired, so a combination that would weaken
authentication or discovery is refused by the process that would have run
it rather than discovered by the first request it answered.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ClassificationValue(BaseModel):
    """One level of the data-classification vocabulary a deployment defines.

    Projects carry a classification ``code`` from this vocabulary. ``order``
    ranks the levels so a binding's maximum classification can be compared
    against a project's; ``discoverable`` says whether a project at this
    level is listed for any principal allowed to discover datasets, or
    only for one whose bindings clear the level. Codes and orders are each
    unique across the vocabulary, which ``ApiSettings`` enforces.
    """

    code: str = Field(min_length=1)
    order: int = Field(ge=0)
    discoverable: bool


class OidcSettings(BaseModel):
    """One configured identity provider.

    ``HURON_OIDC__*`` env vars populate this (``env_nested_delimiter="__"``
    on ``ApiSettings.model_config``). The issuer is discovered at startup;
    the client credentials and redirect URL drive the authorization-code
    login flow, and ``audience`` is what bearer tokens must be issued for.
    """

    issuer: str
    client_id: str
    client_secret: str
    #: e.g. http://localhost:8080/auth/oidc/callback
    redirect_url: str
    scopes: tuple[str, ...] = ("openid", "profile", "email")
    groups_claim: str = "groups"
    #: Audience expected in bearer ID/access tokens; defaults to client_id.
    audience: str | None = None


class ApiSettings(BaseSettings):
    """The API service's configuration, read from ``HURON_*`` and validated.

    Building one succeeds only for a combination the service is willing to
    run: development-only authentication never leaves development, OIDC is
    never selected without a provider, the login-flow cookie is never
    unsigned outside development, and the classification vocabulary is
    non-empty with unique codes and orders. ``create_app`` takes the
    validated object and never reads the environment itself, which is what
    lets tests construct settings directly.
    """

    model_config = SettingsConfigDict(
        env_prefix="HURON_", case_sensitive=False, env_nested_delimiter="__"
    )

    env: Literal["development", "staging", "production"]
    auth_mode: Literal["oidc", "dev-headers"]
    data_root: str = "/data"
    database_url: str
    #: Subject granted a SYSTEM-scope platform_owner binding at startup, so a
    #: fresh deployment has exactly one way in. Unset it once real bindings
    #: exist.
    bootstrap_platform_owner: str | None = None
    classification_vocabulary: list[ClassificationValue]
    #: The configured identity provider. Required when auth_mode="oidc".
    oidc: OidcSettings | None = None
    password_login_enabled: bool = True
    #: Signs the transient huron_login flow cookie. Required outside development.
    login_flow_secret: str = ""
    session_cookie_name: str = "huron_session"
    #: Where /auth/oidc/callback lands the browser after login.
    web_app_url: str = "http://localhost:5173"

    @field_validator("classification_vocabulary")
    @classmethod
    def _refuse_ambiguous_vocabulary(
        cls, vocabulary: list[ClassificationValue]
    ) -> list[ClassificationValue]:
        """Refuse a classification vocabulary that could not rank projects unambiguously.

        A repeated code or order would make classification comparisons
        ambiguous, and an empty vocabulary would leave every project
        unclassifiable.

        Args:
            vocabulary: The configured classification levels.

        Returns:
            The vocabulary unchanged, once every check passed.

        Raises:
            ValueError: If two values share a code; if two share an order;
                or if the vocabulary is empty.
        """
        codes = [value.code for value in vocabulary]
        orders = [value.order for value in vocabulary]
        if len(codes) != len(set(codes)):
            raise ValueError("classification codes must be unique")
        if len(orders) != len(set(orders)):
            raise ValueError("classification orders must be unique")
        if not codes:
            raise ValueError("classification vocabulary may not be empty")
        return vocabulary

    @model_validator(mode="after")
    def _refuse_unsafe_authentication(self) -> Self:
        """Refuse an authentication configuration that would weaken the deploy.

        Each check guards a failure that would otherwise surface only at
        request time: dev-headers outside development would let any client
        name its own subject, OIDC without a provider would leave every
        bearer token unverifiable, and an empty ``login_flow_secret`` would
        leave the pending-login cookie unsigned.

        Returns:
            The settings unchanged, once every combination passed.

        Raises:
            ValueError: If ``auth_mode`` is ``dev-headers`` while ``env`` is
                not ``development``; if ``auth_mode`` is ``oidc`` and
                ``oidc`` is unset; or if ``login_flow_secret`` is empty
                outside development.
        """
        if self.auth_mode == "dev-headers" and self.env != "development":
            raise ValueError("dev-headers auth is refused outside development")
        if self.auth_mode == "oidc" and self.oidc is None:
            raise ValueError("auth_mode=oidc requires the HURON_OIDC__* settings")
        if self.env != "development" and not self.login_flow_secret:
            raise ValueError("login_flow_secret is required outside development")
        return self


def settings_from_environment() -> ApiSettings:
    """Populate every field from ``HURON_*``.

    The call reads argument-less to a type checker, which cannot see that
    pydantic-settings supplies the required fields from the environment.
    Validation runs as part of construction, so an environment describing
    an unsafe combination fails here.

    Returns:
        The validated settings for this process.
    """
    return ApiSettings()  # type: ignore[call-arg]
