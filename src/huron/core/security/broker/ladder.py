"""Catalog authority and the informational role strings carried by Huron tokens."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING, Final, Protocol

from huron.core.foundation.errors import Forbidden

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from uuid import UUID


class Role(IntEnum):
    """A ranked role whose authority includes every lower rank."""

    READER = 10
    DEVELOPER = 20
    PROJECT_ADMIN = 30
    ORGANIZATION_ADMIN = 40
    PLATFORM_OWNER = 50

    @property
    def code(self) -> str:
        """Return the stable lower-case role code.

        Returns:
            The code used by mappings and claims.
        """
        return self.name.lower()

    @property
    def title(self) -> str:
        """Return the human-readable role title.

        Returns:
            The title displayed to a scientist.
        """
        return self.name.replace("_", " ").title()

    @property
    def catalog_scoped(self) -> bool:
        """Return whether this role may be granted on one catalog.

        Returns:
            False for the two global-only administrative roles.
        """
        return self <= Role.PROJECT_ADMIN

    @classmethod
    def from_code(cls, code: str) -> Role:
        """Resolve an exact role code without case normalization.

        Args:
            code: The lower-case code to resolve.

        Returns:
            The corresponding ranked role.

        Raises:
            ValueError: If the code is unknown.
        """
        for role in cls:
            if role.code == code:
                return role
        raise ValueError(f"unknown role code: {code!r}; role codes are lower case")


@dataclass(frozen=True, slots=True)
class CatalogRef:
    """A catalog's stable identity and its current opaque display name."""

    id: UUID
    name: str


@dataclass(frozen=True, slots=True)
class Grant:
    """One ranked role on a catalog, or on all catalogs when catalog is None."""

    role: Role
    catalog: CatalogRef | None


@dataclass(frozen=True, slots=True)
class ReadableCatalogs:
    """A SQL-ready catalog filter; every=True has an empty set of ids."""

    every: bool
    ids: frozenset[UUID]


@dataclass(frozen=True, slots=True, init=False)
class Grants:
    """Immutable authority normalized to the highest role on each scope."""

    _subject: str
    _grants: tuple[Grant, ...]

    def __init__(self, subject: str, grants: Iterable[Grant]) -> None:
        """Capture the highest role per catalog identity and global scope.

        Args:
            subject: The authenticated subject used in refusals.
            grants: Mapping rows in any order, possibly with repeated scopes.

        Raises:
            ValueError: If a global-only role is granted on a catalog.
        """
        scopes: dict[UUID | None, Grant] = {}
        for grant in grants:
            if grant.catalog is not None and not grant.role.catalog_scoped:
                raise ValueError("a global-only role cannot be granted on a catalog")
            key = grant.catalog.id if grant.catalog is not None else None
            previous = scopes.get(key)
            if previous is None or grant.role > previous.role:
                scopes[key] = grant
        ordered = sorted(
            scopes.values(),
            key=lambda grant: (
                grant.catalog is not None,
                grant.catalog.name if grant.catalog else "",
            ),
        )
        object.__setattr__(self, "_subject", subject)
        object.__setattr__(self, "_grants", tuple(ordered))

    def _role(self, catalog_id: UUID | None) -> Role | None:
        return max(
            (
                grant.role
                for grant in self._grants
                if grant.catalog is None or grant.catalog.id == catalog_id
            ),
            default=None,
        )

    def role_on(self, catalog: CatalogRef) -> Role | None:
        """Return the effective role on a catalog, matching its identity only.

        Args:
            catalog: The catalog being addressed.

        Returns:
            The maximum applicable role, or None when no grant applies.
        """
        return self._role(catalog.id)

    def require(self, minimum: Role, catalog: CatalogRef | None = None) -> None:
        """Refuse authority below the minimum without making discovery decisions.

        Args:
            minimum: The least role allowed to perform the operation.
            catalog: The target catalog, or None to require global authority.

        Raises:
            Forbidden: If the effective role is absent or too low.
        """
        held = self._role(catalog.id if catalog else None)
        if held is None or held < minimum:
            scope = f"catalog:{catalog.name}" if catalog else "global"
            raise Forbidden(
                f"{minimum.code} required on {scope} for {self._subject}",
                context={
                    "subject": self._subject,
                    "role": minimum.code,
                    "scope": scope,
                    "held": held.code if held is not None else None,
                },
            )

    def readable(self, minimum: Role = Role.READER) -> ReadableCatalogs:
        """Return the catalogs whose effective role reaches the minimum.

        Args:
            minimum: The minimum role required by the listing.

        Returns:
            All catalogs for a sufficient global role, otherwise matching ids.
        """
        global_role = self._role(None)
        if global_role is not None and global_role >= minimum:
            return ReadableCatalogs(True, frozenset())
        return ReadableCatalogs(
            False,
            frozenset(
                grant.catalog.id
                for grant in self._grants
                if grant.catalog is not None and grant.role >= minimum
            ),
        )

    def __iter__(self) -> Iterator[Grant]:
        """Iterate global authority first, then catalog grants ordered by name.

        Returns:
            An iterator over the normalized grants.
        """
        return iter(self._grants)

    def __bool__(self) -> bool:
        """Return whether the subject holds any role.

        Returns:
            False only when there are no grants.
        """
        return bool(self._grants)


class RoleMappingReader(Protocol):
    """Read current group mappings without caching request authority."""

    async def roles_for_groups(self, groups: frozenset[str]) -> tuple[Grant, ...]:
        """Read all matching rows, returning no rows for unmapped groups.

        Empty groups require no query. Storage failures propagate unchanged.

        Args:
            groups: The verified group membership.

        Returns:
            Every matching grant with the catalog's current id and name.
        """
        ...


ROLE_CLAIM_PREFIX: Final = "PRINCIPAL_ROLE:"


@dataclass(frozen=True, slots=True)
class ClaimedRole:
    """An informational role claim with exact, reversible spelling."""

    role: Role
    catalog: str | None

    def __post_init__(self) -> None:
        """Enforce scope, structure and the Polaris principal-role rule.

        Raises:
            ValueError: If the claim violates any grammar rule.
        """
        if self.catalog is not None:
            if not self.catalog:
                raise ValueError("empty catalog is not allowed")
            if "." in self.catalog:
                raise ValueError("catalog cannot contain a dot; at most one dot is allowed")
            if not self.role.catalog_scoped:
                raise ValueError("a global-only role cannot be claimed on a catalog")
        principal_role = self._principal_role()
        if not 1 <= len(principal_role) <= 256 or principal_role.lower().startswith("system$"):
            raise ValueError(
                "Polaris principal-role rule: length must be 1..256 and cannot start with system$"
            )

    def _principal_role(self) -> str:
        return f"{self.catalog}.{self.role.code}" if self.catalog is not None else self.role.code

    @classmethod
    def of(cls, grant: Grant) -> ClaimedRole:
        """Represent a grant using its catalog's current name.

        Args:
            grant: The grant to render, subject to the claim grammar.

        Returns:
            A validated informational claim.
        """
        return cls(grant.role, grant.catalog.name if grant.catalog is not None else None)

    @classmethod
    def parse(cls, claim: str) -> ClaimedRole:
        """Parse an exact claim without trimming or normalizing case.

        Args:
            claim: The complete prefixed role string.

        Returns:
            The validated role and optional opaque catalog name.

        Raises:
            ValueError: If the prefix, separator or role-code rule is broken.
        """
        if not claim.startswith(ROLE_CLAIM_PREFIX):
            raise ValueError("role claim prefix must be PRINCIPAL_ROLE:")
        body = claim[len(ROLE_CLAIM_PREFIX) :]
        if body.count(".") > 1:
            raise ValueError("at most one dot is allowed")
        catalog, separator, code = body.rpartition(".")
        if not code:
            raise ValueError("empty role code is not allowed")
        if code == "ALL":
            raise ValueError("Polaris pseudo-role ALL is not a Huron role")
        return cls(Role.from_code(code), catalog if separator else None)

    def __str__(self) -> str:
        """Render the exact prefixed role string.

        Returns:
            The canonical claim, retaining the catalog name unchanged.
        """
        return ROLE_CLAIM_PREFIX + self._principal_role()
