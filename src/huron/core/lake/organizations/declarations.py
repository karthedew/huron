"""Organizations the service configuration declares: their role groups and share roots."""

from __future__ import annotations

import posixpath
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from huron.core.lake.organizations.errors import (
    DeclarationInvalid,
    OrganizationDeclared,
    OrganizationsManaged,
)
from huron.core.lake.organizations.models import OrganizationGroups
from huron.schema.naming import check_segment

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

__all__ = ["UNMANAGED", "Declarations", "DeclaredOrganization"]


@dataclass(frozen=True, slots=True)
class DeclaredOrganization:
    """One organization of the configuration.

    ``root`` is the parent directory of the organization's directory, which is always
    ``<root>/<name>``; ``None`` leaves the location to the CLI's mount prefix. ``export`` is an
    informational NFS source the CLI shows in mount hints. ``groups`` are exactly the LDAP groups
    holding each organization-scope role: Org Admin, and the catalog roles every catalog of the
    organization inherits.
    """

    name: str
    display_name: str = ""
    description: str = ""
    groups: OrganizationGroups = field(default_factory=OrganizationGroups)
    root: str | None = None
    export: str = ""

    def __post_init__(self) -> None:
        check_segment(self.name)
        for role, groups in self.groups.items():
            for group in groups:
                if not group or group != group.strip():
                    raise DeclarationInvalid(
                        f"organization {self.name!r}: groups.{role}: LDAP group names are"
                        " non-empty and unpadded",
                        {"organization": self.name, "role": str(role), "ldap_group": group},
                    )
        if self.root is not None:
            _check_root(self.name, self.root)

    @property
    def title(self) -> str:
        """The display name the organization gets: the declared one, else its name."""
        return self.display_name or self.name

    @property
    def path(self) -> str | None:
        """The organization's directory, ``<root>/<name>``, or ``None`` without a root."""
        return None if self.root is None else posixpath.join(self.root, self.name)

    def as_dict(self) -> dict[str, Any]:
        """The configuration fields the API adds to the organization."""
        return {
            "declared": True,
            "root": self.root,
            "path": self.path,
            "export": self.export or None,
        }


@dataclass(frozen=True, slots=True)
class Declarations:
    """The declared organizations, or ``None`` when the service does not manage organizations.

    Managed mode (an ``organizations`` list, even an empty one) makes the configuration the
    source of organizations: creating one through the API is refused, declared ones cannot be
    deleted and their organization-scope role groups cannot be edited.
    """

    entries: tuple[DeclaredOrganization, ...] | None = None
    _by_name: dict[str, DeclaredOrganization] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        by_name: dict[str, DeclaredOrganization] = {}
        for entry in self.entries or ():
            if entry.name in by_name:
                raise DeclarationInvalid(
                    f"organization {entry.name!r} is declared twice", {"organization": entry.name}
                )
            by_name[entry.name] = entry
        object.__setattr__(self, "_by_name", by_name)

    @classmethod
    def of(cls, entries: Iterable[DeclaredOrganization] | None) -> Declarations:
        """Declarations from any iterable; ``None`` is unmanaged."""
        return cls(None if entries is None else tuple(entries))

    @property
    def managed(self) -> bool:
        """Whether the configuration declares the organizations."""
        return self.entries is not None

    def __iter__(self) -> Iterator[DeclaredOrganization]:
        return iter(self.entries or ())

    def get(self, name: str) -> DeclaredOrganization | None:
        """The declaration of organization ``name``."""
        return self._by_name.get(name)

    def share_root(self, organization: str) -> str | None:
        """The configured root of ``organization``'s directory, or ``None``."""
        found = self.get(organization)
        return None if found is None else found.root

    def require_unmanaged(self) -> None:
        """Raise :class:`OrganizationsManaged` in managed mode."""
        if self.managed:
            raise OrganizationsManaged(
                "organizations are declared in the service configuration", {}
            )

    def require_undeclared(self, organization: str, what: str) -> None:
        """Raise :class:`OrganizationDeclared` when ``organization`` is declared."""
        if self.get(organization) is not None:
            raise OrganizationDeclared(
                f"organization {organization!r} is declared in the service configuration; {what}",
                {"organization": organization},
            )


UNMANAGED = Declarations()


def _check_root(name: str, root: str) -> None:
    normalized = posixpath.normpath(root)
    bad = (
        not root.startswith("/")
        or root.startswith("//")
        or normalized != root
        or ".." in root.split("/")
        or any(ord(c) < 0x20 or ord(c) == 0x7F for c in root)
    )
    if bad:
        raise DeclarationInvalid(
            f"organization {name!r}: root must be an absolute, normalized path",
            {"organization": name, "root": root},
        )
