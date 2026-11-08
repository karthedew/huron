"""``config.yaml``: where the API is, how to log in, and where the share is mounted."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import Any

import yaml

from huron.applications.cli.errors import UsageError

__all__ = ["CONFIG_KEYS", "Config", "config_path"]

CONFIG_KEYS = ("api_url", "issuer", "client_id", "mount_prefix")
_ENVIRONMENT = {
    "api_url": "HURON_API_URL",
    "issuer": "HURON_ISSUER",
    "client_id": "HURON_CLIENT_ID",
    "mount_prefix": "HURON_MOUNT_PREFIX",
}


@dataclass(frozen=True, slots=True)
class Config:
    """The CLI configuration; environment variables override the file."""

    api_url: str = "http://127.0.0.1:8080"
    issuer: str = ""
    client_id: str = "huron-cli"
    mount_prefix: str = "/projects/huron"
    current_organization: str | None = None
    current_catalog: str | None = None
    current_collection: str | None = None

    @classmethod
    def load(cls, path: Path, environ: Mapping[str, str]) -> Config:
        """Read ``path`` (missing is fine) and apply environment overrides."""
        values: dict[str, Any] = {}
        if path.exists():
            loaded = yaml.safe_load(path.read_text()) or {}
            if not isinstance(loaded, dict):
                raise UsageError(f"{path} does not contain a YAML mapping")
            names = {field.name for field in fields(cls)}
            values = {k: v for k, v in loaded.items() if k in names}
        for key, variable in _ENVIRONMENT.items():
            if environ.get(variable):
                values[key] = environ[variable]
        return cls(**values)

    def set(self, key: str, value: str) -> Config:
        """A copy with ``key`` set; only the documented keys may be set."""
        if key not in CONFIG_KEYS:
            raise UsageError(
                f"there is no configuration key {key!r}",
                hint="use one of these keys: " + ", ".join(CONFIG_KEYS),
            )
        return replace(self, **{key: value})

    def save(self, path: Path) -> None:
        """Write atomically with mode 0600."""
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_name(path.name + ".tmp")
        descriptor = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            yaml.safe_dump(asdict(self), handle, sort_keys=True)
        os.replace(part, path)

    def as_dict(self) -> dict[str, Any]:
        """Every value, for ``huron config show``."""
        return asdict(self)


def config_path(environ: Mapping[str, str]) -> Path:
    """``$XDG_CONFIG_HOME/huron/config.yaml``."""
    base = environ.get("XDG_CONFIG_HOME") or str(
        Path(environ.get("HOME", "~")).expanduser() / ".config"
    )
    return Path(base) / "huron" / "config.yaml"
