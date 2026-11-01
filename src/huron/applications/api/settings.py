"""Service configuration: ``HURON_*`` environment variables over an optional YAML file.

``HURON_CONFIG_FILE`` names a YAML file whose top-level keys are the :class:`Settings` field
names. An environment variable wins over the file, and the file over the defaults. The file is
strict: a missing file, a top-level value that is not a mapping, an unknown key (a typo such as
``organisations``), a key given twice, an ``organizations`` key without a list or an invalid
organization fails startup.
"""

from __future__ import annotations

import os
import uuid
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, PrivateAttr, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from huron.core.lake.organizations.declarations import Declarations, DeclaredOrganization
from huron.core.lake.organizations.models import OrganizationGroups
from huron.pkg.errors import HuronError

if TYPE_CHECKING:
    from importlib.abc import Traversable

__all__ = [
    "CONFIG_FILE_VARIABLE",
    "OrganizationEntry",
    "RoleGroupsEntry",
    "Settings",
    "StrictYamlSource",
]

CONFIG_FILE_VARIABLE = "HURON_CONFIG_FILE"


class RoleGroupsEntry(BaseModel):
    """An organization's LDAP groups per organization-scope role; every role is optional.

    ``org_admin`` administers the organization. ``catalog_admin``, ``contributor`` and ``reader``
    hold their role in every catalog of the organization, existing and future.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    org_admin: list[str] = []
    catalog_admin: list[str] = []
    contributor: list[str] = []
    reader: list[str] = []

    @model_validator(mode="before")
    @classmethod
    def _known_roles(cls, data: Any) -> Any:
        if isinstance(data, dict):
            unknown = sorted(str(key) for key in data if key not in cls.model_fields)
            if unknown:
                raise ValueError(
                    f"groups has unknown roles: {', '.join(unknown)};"
                    f" the roles are {', '.join(cls.model_fields)}"
                )
        return data

    def declared(self) -> OrganizationGroups:
        """The lake's value: groups de-duplicated and sorted per role."""
        return OrganizationGroups(
            org_admin=tuple(self.org_admin),
            catalog_admin=tuple(self.catalog_admin),
            contributor=tuple(self.contributor),
            reader=tuple(self.reader),
        )


class OrganizationEntry(BaseModel):
    """One declared organization in the configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    display_name: str = ""
    description: str = ""
    groups: RoleGroupsEntry = RoleGroupsEntry()
    root: str | None = None
    export: str = ""

    @model_validator(mode="before")
    @classmethod
    def _no_admin_groups(cls, data: Any) -> Any:
        if isinstance(data, dict) and "admin_groups" in data:
            raise ValueError(
                "admin_groups is no longer read; declare the Org Admin groups as"
                " groups.org_admin (groups: {org_admin: [...]})"
            )
        return data

    def declared(self) -> DeclaredOrganization:
        """The lake's value for this entry; raises a ``HuronError`` when it breaks a rule."""
        return DeclaredOrganization(
            name=self.name,
            display_name=self.display_name,
            description=self.description,
            groups=self.groups.declared(),
            root=self.root,
            export=self.export,
        )


class Settings(BaseSettings):
    """Everything the service reads from its environment and its configuration file.

    ``organizations`` present (even an empty list) puts the service in managed mode: the
    configuration declares the organizations. ``HURON_ORGANIZATIONS`` (a JSON list) replaces
    the file's list.
    """

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
    organizations: list[OrganizationEntry] | None = None

    _declarations: Declarations = PrivateAttr(default_factory=Declarations)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Arguments, then ``HURON_*`` variables, then the ``HURON_CONFIG_FILE`` file."""
        sources: list[PydanticBaseSettingsSource] = [init_settings, env_settings]
        path = os.environ.get(CONFIG_FILE_VARIABLE, "")
        if path:
            sources.append(StrictYamlSource(settings_cls, Path(path)))
        return tuple(sources)

    @model_validator(mode="after")
    def _declare(self) -> Settings:
        entries = self.organizations
        try:
            declared = None if entries is None else [entry.declared() for entry in entries]
            self._declarations = Declarations.of(declared)
        except HuronError as error:
            raise ValueError(error.message) from error
        return self

    @property
    def declarations(self) -> Declarations:
        """The declared organizations; unmanaged when ``organizations`` is absent."""
        return self._declarations

    @property
    def token_ttl(self) -> timedelta:
        """How long a Huron token is valid."""
        return timedelta(seconds=self.token_ttl_seconds)

    @property
    def key_overlap(self) -> timedelta:
        """How long a retired signing key still verifies tokens."""
        return timedelta(hours=self.key_overlap_hours)


class StrictYamlSource(YamlConfigSettingsSource):
    """A YAML settings source that refuses a missing file, a non-mapping and unknown keys.

    It also refuses a key given twice (YAML would keep the last one) and an ``organizations``
    key without a value (every entry commented out): ``[]`` is an empty managed list, and
    unmanaged mode is the key removed.
    """

    def __init__(self, settings_cls: type[BaseSettings], path: Path) -> None:
        if not path.is_file():
            raise ValueError(f"{CONFIG_FILE_VARIABLE} names {str(path)!r}, which is not a file")
        self._known = frozenset(settings_cls.model_fields)
        super().__init__(settings_cls, yaml_file=path)

    def _read_file(self, file_path: Path | Traversable) -> dict[str, Any]:
        with file_path.open(encoding="utf-8") as stream:
            try:
                loaded = yaml.load(stream, Loader=_UniqueKeyLoader)  # a SafeLoader subclass
            except yaml.constructor.ConstructorError as error:
                raise ValueError(f"{file_path}: {error}") from error
        if loaded is None:
            return {}
        if not isinstance(loaded, dict):
            raise ValueError(f"{file_path} must hold a mapping of setting names")
        unknown = sorted(str(key) for key in loaded if key not in self._known)
        if unknown:
            raise ValueError(f"{file_path} has unknown settings: {', '.join(unknown)}")
        if "organizations" in loaded and loaded["organizations"] is None:
            raise ValueError(
                f"{file_path}: organizations has no list; write [] to declare none,"
                " or remove the key for unmanaged organizations"
            )
        return loaded


class _UniqueKeyLoader(yaml.SafeLoader):
    """A safe loader that refuses a mapping key given twice, at any depth."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        seen: set[Any] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found the key {key!r} twice",
                    key_node.start_mark,
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)
