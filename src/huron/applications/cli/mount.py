"""The share as this machine sees it: each organization's directory, checked before any read.

Every API path starts with its organization (``<organization>/<catalog>/…``). The organization's
root comes from ``GET /api/v1/organizations/{organization}`` (cached for the command); without
one, the CLI's ``mount_prefix`` stands in. An organization with a root, or any declared one, is
guarded by the marker in its own directory; the others by the marker at the mount prefix. Every
path :class:`Mount` hands out has passed that check, so no disk read can skip it.
:class:`Mount` writes nothing. Only the provision commands write, through
``huron.core.storage.provision``.

When the service manages its organizations (``organizations_managed`` of ``GET /healthz``), an
organization it does not declare (removed from the configuration, or left from unmanaged mode)
has no known root: it is only looked for under the mount prefix, and the commands that survey
every organization report it as undeclared instead of failing on the prefix marker.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from huron.applications.cli.errors import StorageFailure
from huron.core.storage import (
    LakePath,
    Marker,
    MarkerState,
    ShareReader,
    StorageError,
    marker_state,
    verify_marker,
)
from huron.pkg.errors import HuronError

if TYPE_CHECKING:
    from huron.applications.cli.services import Services

__all__ = ["PREFIX_MARKER_HINT", "PROVISION_HINT", "UNDECLARED_HINT", "Mount", "Site"]

PROVISION_HINT = (
    "To prepare the organization directories, run `huron adm provision-orgs` (storage admin)"
)
PREFIX_MARKER_HINT = (
    "Organizations without a root are below `mount_prefix`. Mount the share there."
    " To set the prefix, run `huron config set mount_prefix <dir>`."
    " To write the marker, run `huron adm provision-orgs` (storage admin)"
)
UNDECLARED_HINT = (
    "An organization that the service configuration no longer declares has no known root."
    " To reach its directory, declare it again with its root."
    " Alternatively, delete it when it has no catalogs"
)
_PREFIX_HINT = "run this command on a machine that mounts the share, or set `mount_prefix`"


@dataclass(frozen=True, slots=True)
class Site:
    """Where an organization's directory is on this machine, and which marker guards it.

    ``base`` is the organization's root, or the mount prefix when it has none; the CLI reads
    the organization through a storage rooted at ``base``, where its API paths are lake paths.
    An organization with a root, or any declared one, carries its own marker in its directory;
    the others share the marker at the mount prefix. ``export`` is the NFS source of the root,
    for hints only.
    """

    name: str
    base: Path
    rooted: bool
    declared: bool = False
    export: str | None = None

    @property
    def own_marker(self) -> bool:
        """Whether the organization's directory carries its own marker."""
        return self.rooted or self.declared

    @property
    def directory(self) -> Path:
        """The organization's directory on this machine."""
        return self.base / self.name


@dataclass
class Mount:
    """The mounted share, verified against the service once per organization and command."""

    services: Services
    _readers: dict[Path, ShareReader] = field(default_factory=dict, repr=False)
    _health: Mapping[str, Any] | None = field(default=None, repr=False)
    _sites: dict[str, Site] = field(default_factory=dict, repr=False)
    _verified: dict[tuple[Path, str | None], Marker] = field(default_factory=dict, repr=False)

    @property
    def prefix(self) -> Path:
        """Where the share is mounted, for organizations without a root."""
        return Path(self.services.config.mount_prefix)

    def reader(self, base: Path) -> ShareReader:
        """The read-only storage rooted at ``base``; one per directory and command."""
        found = self._readers.get(base)
        if found is None:
            found = self._readers[base] = self.services.storage_factory(base)
        return found

    def instance_id(self) -> str:
        """The service's instance id, from ``GET /healthz``."""
        return str(self._service_health()["instance_id"])

    def service_user(self) -> Mapping[str, Any] | None:
        """The service user's ``uid``, ``gid`` and ``group`` from ``GET /healthz``; ``None``
        when the service does not report them.
        """
        found = self._service_health().get("service_user")
        return None if found is None else dict(found)

    def managed(self) -> bool:
        """Whether the service configuration declares the organizations (``GET /healthz``)."""
        return bool(self._service_health().get("organizations_managed"))

    def undeclared(self, site: Site) -> bool:
        """Whether ``site`` is an organization the managed configuration does not declare."""
        return not site.declared and self.managed()

    def prefix_state(self) -> MarkerState:
        """The state of the marker at the mount prefix, without raising."""
        return _storage_call(
            lambda: marker_state(self.reader(self.prefix), LakePath(), self.instance_id())
        )

    def site(self, organization: str) -> Site:
        """Where ``organization`` lives on this machine (not yet verified)."""
        found = self._sites.get(organization)
        if found is None:
            found = self.site_of_view(
                self.services.api().get(f"/api/v1/organizations/{organization}")
            )
        return found

    def site_of_view(self, view: Mapping[str, Any]) -> Site:
        """The site of an organization from its API view (``root`` and ``declared``); cached."""
        name, root, export = str(view["name"]), view.get("root"), view.get("export")
        if root is None:
            base, rooted = self.prefix, False
        else:
            base, rooted = _root(name, str(root)), True
        found = Site(
            name, base, rooted, bool(view.get("declared")), str(export) if export else None
        )
        self._sites[name] = found
        return found

    def verify(self, organization: str) -> Site:
        """The site of ``organization``, after checking the marker that guards it."""
        site = self.site(organization)
        self._check(site)
        return site

    def verify_catalog(self, catalog: str) -> Site:
        """The site of the organization owning ``catalog``, verified."""
        view = self.services.api().get(f"/api/v1/catalogs/{catalog}")
        return self.verify(str(view["organization"]))

    def verify_prefix(self) -> Marker:
        """The marker at the mount prefix, which guards organizations without their own."""
        return self._marker(self.prefix, None, _PREFIX_HINT)

    def share(self, organization: str) -> ShareReader:
        """The verified storage that the organization's API paths are lake paths in."""
        return self.reader(self.verify(organization).base)

    def locate(self, relative: str) -> tuple[ShareReader, LakePath]:
        """The verified storage and the lake path of a path the API returned."""
        location = _storage_call(lambda: LakePath.parse(relative))
        return self.share(location.names[0]), location

    def _service_health(self) -> Mapping[str, Any]:
        if self._health is None:
            self._health = self.services.api().get("/healthz", auth=False)
        return self._health

    def _check(self, site: Site) -> Marker:
        if not site.own_marker:
            if self.undeclared(site):
                return self._marker(self.prefix, None, f"{site.name}: {UNDECLARED_HINT}")
            return self.verify_prefix()
        source = f" (from {site.export})" if site.export else ""
        return self._marker(
            site.base,
            site.name,
            f"check that {site.base} is mounted on this machine{source}. {PROVISION_HINT}",
        )

    def _marker(self, base: Path, organization: str | None, hint: str) -> Marker:
        found = self._verified.get((base, organization))
        if found is not None:
            return found
        instance = self.instance_id()
        directory = LakePath() if organization is None else LakePath.of(organization)
        try:
            marker = verify_marker(self.reader(base), directory, instance, organization)
        except StorageError as error:
            raise StorageFailure(error.message, hint=hint, code=error.code) from error
        self._verified[(base, organization)] = marker
        return marker


def _root(name: str, root: str) -> Path:
    """The root of organization ``name`` as a path; refuses one that is not absolute and normal."""
    path = PurePosixPath(root)
    if not path.is_absolute() or str(path) != (root.rstrip("/") or "/") or ".." in path.parts:
        raise StorageFailure(
            f"the root {root!r} of organization {name} is not an absolute, normalized path"
        )
    return Path(root)


def _storage_call[T](action: Callable[[], T]) -> T:
    try:
        return action()
    except HuronError as error:
        raise StorageFailure(error.message, code=error.code) from error
