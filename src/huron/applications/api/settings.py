"""Service configuration from ``HURON_*`` environment variables."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["Settings"]


class Settings(BaseSettings):
    """Everything the service reads from its environment."""

    model_config = SettingsConfigDict(env_prefix="HURON_", extra="ignore")

    database_url: str = ""
    store: Literal["postgres", "memory"] = "postgres"
    instance_id: uuid.UUID
    issuer: str
    audience: str = "huron"
    token_ttl_seconds: int = 8 * 3600
    key_overlap_hours: int = 24
    key_cache_seconds: int = 60
    company_issuer: str
    company_audience: str
    group_directory_url: str
    platform_admin_group: str
    pool_size: int = 10
    log_level: str = "INFO"

    @property
    def token_ttl(self) -> timedelta:
        """How long a Huron token is valid."""
        return timedelta(seconds=self.token_ttl_seconds)

    @property
    def key_overlap(self) -> timedelta:
        """How long a retired signing key still verifies tokens."""
        return timedelta(hours=self.key_overlap_hours)
