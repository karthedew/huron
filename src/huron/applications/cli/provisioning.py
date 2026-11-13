"""The input of ``huron adm provision-orgs``: the service's instance, its declared organizations
and the service owner, from the API or from the service configuration file.

The service configuration file is the YAML file that the API reads through
``HURON_CONFIG_FILE``. With ``--config``, ``huron adm provision-orgs`` reads only
``instance_id``, ``organizations`` (each one's ``name`` and ``root``), ``service_uid``,
``service_group`` and ``lake_path`` from it, and sends no request to the API. So the storage
administrator can prepare the lake while the API is stopped. The ``HURON_*`` variables of the
API are not read: to the CLI, some of them are its own settings.

``huron adm provision-catalogs`` does not read the service configuration file. It always sends
requests to the API. It uses only ``below_lake_path`` from this module.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from huron.applications.cli.errors import UsageError
from huron.applications.cli.mount import Mount, Site
from huron.core.lake.organizations.declarations import Declarations, DeclaredOrganization
from huron.core.storage import LakePath, Marker, OrganizationPlace
from huron.core.storage.provision import OrganizationTarget, Owner
from huron.pkg.errors import HuronError

__all__ = ["Provisioning", "below_lake_path", "from_file", "from_service"]

_OWNER_HINT = "use `--uid <uid>` and `--gid <gid>`"


@dataclass(frozen=True, slots=True)
class Provisioning:
    """What the provision of the organizations needs.

    ``sites`` are the declared organizations on this machine. ``uid`` and ``gid`` are the
    service user and the service group, each ``None`` when the source does not give it.
    ``hint`` tells how to see the declared organizations, ``None`` when there is no command
    for it.
    """

    instance_id: str
    sites: tuple[Site, ...]
    uid: int | None
    gid: int | None
    hint: str | None = None

    def owner(self, uid: int | None, gid: int | None) -> Owner:
        """The owner of the prepared directories: ``uid`` and ``gid`` when given, else the
        source's. Refuses when neither gives one of them.
        """
        chosen_uid = self.uid if uid is None else uid
        chosen_gid = self.gid if gid is None else gid
        if chosen_uid is None or chosen_gid is None:
            raise UsageError("the CLI does not know the service user and group", hint=_OWNER_HINT)
        return Owner(chosen_uid, chosen_gid)

    def chosen(self, organization: str | None) -> list[Site]:
        """Every declared organization, or only ``organization``."""
        if organization is None:
            return list(self.sites)
        found = [site for site in self.sites if site.name == organization]
        if not found:
            raise UsageError(
                f"the service configuration does not declare organization {organization}",
                hint=self.hint,
            )
        return found

    def targets(
        self, lake_path: Path, api_url: str, owner: Owner, organization: str | None
    ) -> tuple[Marker, list[OrganizationTarget]]:
        """The marker of the lake path and the target of each chosen organization."""
        lake = Marker(1, api_url, self.instance_id)
        targets = [
            OrganizationTarget(
                OrganizationPlace(site.name, below_lake_path(lake_path, site), own_marker=True),
                Marker(1, api_url, self.instance_id, site.name),
                owner,
            )
            for site in self.chosen(organization)
        ]
        return lake, targets


def from_service(mount: Mount, views: Sequence[Mapping[str, Any]]) -> Provisioning:
    """The provisioning that the API gives: the declared organizations among ``views`` and
    ``service_user`` of ``GET /healthz``.
    """
    sites = tuple(mount.site_of_view(view) for view in views if view.get("declared"))
    user = mount.service_user()
    uid = None if user is None else int(user["uid"])
    gid = None if user is None else int(user["gid"])
    hint = "to see the organizations and their paths, run `huron get orgs`"
    return Provisioning(mount.instance_id(), sites, uid, gid, hint)


def from_file(path: Path, lake_path: Path, gid_of: Callable[[str], int | None]) -> Provisioning:
    """The provisioning that the service configuration file ``path`` gives.

    ``lake_path`` is where this machine mounts the lake path. ``gid_of`` gives the gid of the
    service group on this machine; a group that it does not know gives no gid.

    These are the checks, and the only ones. The file must hold a YAML mapping. ``instance_id``
    must be a string that is a UUID. ``lake_path``, when present and not null, must be a string
    that names this machine's lake path. ``organizations``, when present, must be a list of
    mappings. In each mapping, ``name`` must be a string that is a valid name, and ``root``,
    when present and not null, a string that is an absolute, normalized path. One name must not
    occur two times. ``service_uid``, when present, must be a YAML integer of 0 or more.
    ``service_group``, when present and not null, must be a string. As in the API, a null value
    of ``lake_path``, ``service_group`` or ``root`` is the same as no value, and a null value of
    ``instance_id``, ``organizations``, ``service_uid`` or ``name`` is refused. The other API
    checks are not the same. For example, the API refuses an unknown key or a key that occurs
    two times. It accepts a uid in quotes or a boolean uid, such as ``service_uid: "1000"`` or
    ``service_uid: true``, which this function refuses.
    """
    settings = _settings(path)
    _same_lake_path(path, _string(path, settings, "lake_path"), lake_path)
    sites = tuple(
        Site(entry.name, lake_path, rooted=False, declared=True)
        if entry.root is None
        else Site(entry.name, Path(entry.root), rooted=True, declared=True)
        for entry in _declarations(path, settings)
    )
    uid = settings.get("service_uid")
    if "service_uid" in settings and (not isinstance(uid, int) or isinstance(uid, bool) or uid < 0):
        raise UsageError(f"{path}: service_uid must be a number of 0 or more")
    group = _string(path, settings, "service_group")
    gid = None if group is None else gid_of(group)
    return Provisioning(_instance_id(path, settings.get("instance_id")), sites, uid, gid)


def below_lake_path(lake_path: Path, site: Site) -> LakePath:
    """The lake path of the root of ``site``, which must be the lake path or lie below it."""
    if not site.base.is_relative_to(lake_path):
        raise UsageError(
            f"the root {site.base} of organization {site.name} is not below the lake path"
            f" {lake_path}",
            hint="set `mount_prefix` to the directory where this machine mounts `lake_path`",
        )
    return LakePath.of(*site.base.relative_to(lake_path).parts)


def _settings(path: Path) -> dict[str, Any]:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise UsageError(f"the CLI cannot read {path}: {error.strerror}") from error
    except yaml.YAMLError as error:
        raise UsageError(f"{path} is not valid YAML: {error}") from error
    if not isinstance(loaded, dict):
        raise UsageError(f"{path} does not contain a YAML mapping")
    return loaded


def _string(path: Path, settings: Mapping[str, Any], key: str) -> str | None:
    """The value of ``key``, ``None`` when it is absent; refuses a value that is not a string."""
    value = settings.get(key)
    if value is not None and not isinstance(value, str):
        raise UsageError(f"{path}: {key} must be a string")
    return value


def _instance_id(path: Path, value: object) -> str:
    if not isinstance(value, str):
        raise UsageError(f"{path}: instance_id must be a UUID")
    try:
        return str(uuid.UUID(value))
    except ValueError as error:
        raise UsageError(f"{path}: instance_id must be a UUID") from error


def _same_lake_path(path: Path, value: str | None, lake_path: Path) -> None:
    if value is not None and Path(value) != lake_path:
        raise UsageError(
            f"{path} sets lake_path {value}, but the lake path on this machine is {lake_path}",
            hint="set `mount_prefix` to the directory where this machine mounts `lake_path`",
        )


def _declarations(path: Path, settings: Mapping[str, Any]) -> Declarations:
    if "organizations" not in settings:
        return Declarations()
    value = settings["organizations"]
    if not isinstance(value, list) or not all(isinstance(entry, dict) for entry in value):
        raise UsageError(f"{path}: organizations must be a list of mappings")
    for entry in value:
        if not isinstance(entry.get("name", ""), str):
            raise UsageError(f"{path}: the name of each organization must be a string")
        if not isinstance(entry.get("root", ""), str | None):
            raise UsageError(f"{path}: the root of each organization must be a string")
    try:
        return Declarations.of(
            DeclaredOrganization(name=entry.get("name", ""), root=entry.get("root"))
            for entry in value
        )
    except HuronError as error:
        raise UsageError(f"{path}: {error.message}") from error
