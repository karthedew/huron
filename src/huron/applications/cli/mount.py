"""The share as this machine sees it: checked before any disk operation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from huron.applications.cli.errors import StorageFailure
from huron.core.storage import (
    DirectoryKind,
    EffectiveGroups,
    Marker,
    Storage,
    StorageError,
    plan,
    resolve,
    verify_marker,
)

if TYPE_CHECKING:
    from huron.applications.cli.services import Services

__all__ = ["Mount"]


@dataclass
class Mount:
    """The mounted share, verified against the service once per command."""

    services: Services
    _storage: Storage | None = field(default=None, repr=False)
    marker: Marker | None = None

    @property
    def prefix(self) -> Path:
        """Where the share is mounted."""
        return Path(self.services.config.mount_prefix)

    def require(self) -> Storage:
        """The storage, after checking the marker names the service the CLI talks to."""
        if self._storage is not None:
            return self._storage
        storage: Storage = self.services.storage_factory(self.services.config)
        instance = self.services.api().get("/healthz", auth=False)["instance_id"]
        try:
            self.marker = verify_marker(storage, self.prefix, instance)
        except StorageError as error:
            raise StorageFailure(
                error.message,
                hint="run this on a machine that mounts the share, or set mount_prefix",
                code=error.code,
            ) from error
        self._storage = storage
        return storage

    def path(self, relative: str) -> Path:
        """An absolute path on the share for a path the API returned."""
        return resolve(self.prefix, relative)

    def catalog_groups(self, catalog: str) -> EffectiveGroups:
        """Effective groups of a catalog."""
        return EffectiveGroups.from_mapping(
            self.services.api().get(f"/api/v1/catalogs/{catalog}/grants")
        )

    def organization_groups(self, organization: str) -> EffectiveGroups:
        """Platform and organization admin groups, for an organization's directory."""
        api = self.services.api()
        platform = api.get("/api/v1/platform/grants")["ldap_groups"]
        admins = api.get(f"/api/v1/organizations/{organization}/grants")["ldap_groups"]
        return EffectiveGroups(platform_admin=tuple(platform), org_admin=tuple(admins))

    def ensure(self, relative: str, kind: DirectoryKind, groups: EffectiveGroups) -> bool:
        """Create (or repair) a directory with its ACL plan; returns whether it was created."""
        storage = self.require()
        target = self.path(relative)
        created = _storage_call(lambda: storage.ensure_directory(target, plan(kind, groups)))
        self._report(target, "created" if created else "exists")
        return created

    def apply(self, relative: str, kind: DirectoryKind, groups: EffectiveGroups) -> bool:
        """Re-apply a directory's ACL plan; returns whether it changed."""
        storage = self.require()
        target = self.path(relative)
        return _storage_call(lambda: storage.apply_plan(target, plan(kind, groups)))

    def remove(self, relative: str) -> None:
        """Remove an empty directory."""
        storage = self.require()
        target = self.path(relative)
        if _storage_call(lambda: storage.remove_directory(target)):
            self._report(target, "removed")

    def _report(self, target: Path, what: str) -> None:
        note = (
            "" if self.services.config.acl_backend == "posix" else " (modes only: acl_backend none)"
        )
        self.services.err.print(f"{what}: {target}{note}", markup=False, highlight=False)


def _storage_call[T](action: Callable[[], T]) -> T:
    try:
        return action()
    except StorageError as error:
        raise StorageFailure(error.message, code=error.code) from error
