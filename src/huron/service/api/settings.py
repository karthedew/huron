"""API configuration and deploy-time safety refusals."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ClassificationValue(BaseModel):
    code: str = Field(min_length=1)
    order: int = Field(ge=0)
    discoverable: bool


class OidcSettings(BaseModel):
    """One configured identity provider. ``HURON_OIDC__*`` env vars populate
    this (``env_nested_delimiter="__"`` on ``ApiSettings.model_config``)."""

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
    #: "memory" (default) keeps role bindings, service accounts, API keys,
    #: credentials and sessions in process memory alongside the
    #: organization/project/dataset hierarchy, which is not Postgres-backed
    #: yet. "postgres" wires the Postgres-backed RBAC and auth stores
    #: together - they share a pool and the same "FK targets must be real
    #: rows" caveat - instead, which is only safe once the rows their
    #: foreign keys target (organizations, projects) are real Postgres rows,
    #: which requires choosing it explicitly rather than inferring it from
    #: "no repository was injected".
    store_backend: Literal["memory", "postgres"] = "memory"
    classification_vocabulary: list[ClassificationValue]
    #: The configured identity provider. Required when auth_mode="oidc".
    oidc: OidcSettings | None = None
    password_login_enabled: bool = True
    #: Signs the transient huron_login flow cookie. Required outside development.
    login_flow_secret: str = ""
    session_cookie_name: str = "huron_session"
    #: Where /auth/oidc/callback lands the browser after login.
    web_app_url: str = "http://localhost:5173"

    @model_validator(mode="after")
    def refuse_unsafe_combinations(self) -> Self:
        if self.auth_mode == "dev-headers" and self.env != "development":
            raise ValueError("dev-headers auth is refused outside development")
        if self.auth_mode == "oidc" and self.oidc is None:
            raise ValueError("auth_mode=oidc requires the HURON_OIDC__* settings")
        if self.env != "development" and not self.login_flow_secret:
            raise ValueError("login_flow_secret is required outside development")
        codes = [value.code for value in self.classification_vocabulary]
        orders = [value.order for value in self.classification_vocabulary]
        if len(codes) != len(set(codes)):
            raise ValueError("classification codes must be unique")
        if len(orders) != len(set(orders)):
            raise ValueError("classification orders must be unique")
        if not codes:
            raise ValueError("classification vocabulary may not be empty")
        return self
