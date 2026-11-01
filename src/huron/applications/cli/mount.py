"""The share as this machine sees it: each organization's directory, checked before any disk use.

Every API path starts with its organization (``<organization>/<catalog>/…``). The organization's
root comes from ``GET /api/v1/organizations/{organization}`` (cached for the command); without
one, the CLI's ``mount_prefix`` stands in. An organization with a root, or any declared one, is
guarded by the marker in its own directory; the others by the marker at the mount prefix. Every
path :class:`Mount` hands out has passed that check, so no disk operation can skip it.

When the service manages its organizations (``organizations_managed`` of ``GET /healthz``), an
organization it does not declare (removed from the configuration, or left from unmanaged mode)
has no known root: it is only looked for under the mount prefix, and the commands that survey
every organization report it as undeclared instead of failing on the prefix marker.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from huron.applications.cli.errors import StorageFailure
from huron.core.storage import (
    DirectoryKind,
    EffectiveGroups,
    Marker,
    MarkerState,
    OrganizationPlace,
    Storage,
    StorageError,
    marker_state,
    place_of,
    plan,
    resolve,
    verify_marker,
)

if TYPE_CHECKING:
    from huron.applications.cli.services import Services

__all__ = ["PREFIX_MARKER_HINT", "PROVISION_HINT", "UNDECLARED_HINT", "Mount"]

PROVISION_HINT = "prepare organization directories with: huron adm provision-orgs"
PREFIX_MARKER_HINT = (
    "organizations without a root live under mount_prefix: mount the share there"
    " (huron config set mount_prefix <dir>) and mark it once with scripts/init-root.sh"
)
UNDECLARED_HINT = (
    "an organization the service configuration no longer declares has no known root; declare it"
    " again with its root to reach its directory, or delete it once it has no catalogs"
)
_PREFIX_HINT = "run this on a machine that mounts the share, or set mount_prefix"


@dataclass
class Mount:
    """The mounted share, verified against the service once per organization and command."""

    services: Services
    _storage: Storage | None = field(default=None, repr=False)
    _health: Mapping[str, Any] | None = field(default=None, repr=False)
    _places: dict[str, OrganizationPlace] = field(default_factory=dict, repr=False)
    _verified: dict[Path, Marker] = field(default_factory=dict, repr=False)

    @property
    def prefix(self) -> Path:
        """Where the share is mounted, for organizations without a root."""
        return Path(self.services.config.mount_prefix)

    @property
    def storage(self) -> Storage:
        """The storage adapter; paths for it come from :meth:`path` and :meth:`base`."""
        if self._storage is None:
            self._storage = self.services.storage_factory(self.services.config)
        return self._storage

    def instance_id(self) -> str:
        """The service's instance id, from ``GET /healthz``."""
        return str(self._service_health()["instance_id"])

    def managed(self) -> bool:
        """Whether the service configuration declares the organizations (``GET /healthz``)."""
        return bool(self._service_health().get("organizations_managed"))

    def undeclared(self, place: OrganizationPlace) -> bool:
        """Whether ``place`` is an organization the managed configuration does not declare."""
        return not place.declared and self.managed()

    def prefix_state(self) -> MarkerState:
        """The state of the marker at the mount prefix, without raising."""
        return marker_state(self.storage, self.prefix, self.instance_id())

    def place(self, organization: str) -> OrganizationPlace:
        """Where ``organization`` lives on this machine (not yet verified)."""
        found = self._places.get(organization)
        if found is None:
            found = self.place_of_view(
                self.services.api().get(f"/api/v1/organizations/{organization}")
            )
        return found

    def place_of_view(self, view: Mapping[str, Any]) -> OrganizationPlace:
        """The place of an organization from its API view (``root`` and ``declared``); cached."""
        name, root, export = str(view["name"]), view.get("root"), view.get("export")
        try:
            found = place_of(
                name,
                None if root is None else str(root),
                bool(view.get("declared")),
                self.prefix,
                str(export) if export else None,
            )
        except StorageError as error:
            raise StorageFailure(error.message, code=error.code) from error
        self._places[name] = found
        return found

    def verify(self, organization: str) -> OrganizationPlace:
        """The place of ``organization``, after checking the marker that guards it."""
        place = self.place(organization)
        self._check(place)
        return place

    def verify_catalog(self, catalog: str) -> OrganizationPlace:
        """The place of the organization owning ``catalog``, verified."""
        view = self.services.api().get(f"/api/v1/catalogs/{catalog}")
        return self.verify(str(view["organization"]))

    def verify_prefix(self) -> Marker:
        """The marker at the mount prefix, which guards organizations without their own."""
        return self._marker(self.prefix, None, _PREFIX_HINT)

    def base(self, organization: str) -> Path:
        """The verified directory the organization's API paths are relative to."""
        return self.verify(organization).base

    def path(self, relative: str) -> Path:
        """An absolute, verified path on the share for a path the API returned."""
        _storage_call(lambda: resolve(self.prefix, relative))  # refuse escapes before any lookup
        place = self.verify(relative.split("/")[0])
        return _storage_call(lambda: place.resolve(relative))

    def catalog_groups(self, catalog: str) -> EffectiveGroups:
        """Effective groups of a catalog."""
        return EffectiveGroups.from_mapping(
            self.services.api().get(f"/api/v1/catalogs/{catalog}/grants")
        )

    def organization_groups(self, organization: str) -> EffectiveGroups:
        """Platform and organization admin groups, for an organization's directory."""
        api = self.services.api()
        platform = api.get("/api/v1/platform/grants")["ldap_groups"]
        admins = api.get(f"/api/v1/organizations/{organization}/grants")["org_admin"]
        return EffectiveGroups(platform_admin=tuple(platform), org_admin=tuple(admins))

    def ensure(self, relative: str, kind: DirectoryKind, groups: EffectiveGroups) -> bool:
        """Create (or repair) a directory with its ACL plan; returns whether it was created."""
        target = self.path(relative)
        storage = self.storage
        created = _storage_call(lambda: storage.ensure_directory(target, plan(kind, groups)))
        self.report(target, "created" if created else "exists")
        return created

    def apply(self, relative: str, kind: DirectoryKind, groups: EffectiveGroups) -> bool:
        """Re-apply a directory's ACL plan; returns whether it changed."""
        target = self.path(relative)
        storage = self.storage
        return _storage_call(lambda: storage.apply_plan(target, plan(kind, groups)))

    def remove(self, relative: str) -> None:
        """Remove an empty directory."""
        target = self.path(relative)
        storage = self.storage
        if _storage_call(lambda: storage.remove_directory(target)):
            self.report(target, "removed")

    def report(self, target: Path, what: str) -> None:
        """A ``<what>: <path>`` line on standard error, noting when only modes are applied."""
        note = (
            "" if self.services.config.acl_backend == "posix" else " (modes only: acl_backend none)"
        )
        self.services.err.print(f"{what}: {target}{note}", markup=False, highlight=False)

    def _service_health(self) -> Mapping[str, Any]:
        if self._health is None:
            self._health = self.services.api().get("/healthz", auth=False)
        return self._health

    def _check(self, place: OrganizationPlace) -> Marker:
        if not place.own_marker:
            if self.undeclared(place):
                return self._marker(self.prefix, None, f"{place.name}: {UNDECLARED_HINT}")
            return self.verify_prefix()
        source = f" (from {place.export})" if place.export else ""
        return self._marker(
            place.directory,
            place.name,
            f"check that {place.base} is mounted here{source}; {PROVISION_HINT} (storage admin)",
        )

    def _marker(self, directory: Path, organization: str | None, hint: str) -> Marker:
        found = self._verified.get(directory)
        if found is not None and found.organization == organization:
            return found
        instance = self.instance_id()
        try:
            marker = verify_marker(self.storage, directory, instance, organization)
        except StorageError as error:
            raise StorageFailure(error.message, hint=hint, code=error.code) from error
        self._verified[directory] = marker
        return marker


def _storage_call[T](action: Callable[[], T]) -> T:
    try:
        return action()
    except StorageError as error:
        raise StorageFailure(error.message, code=error.code) from error
