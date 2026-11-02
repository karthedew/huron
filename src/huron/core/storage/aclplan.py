"""ACL plans: the mode and POSIX ACL every kind of directory gets from a catalog's groups."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from huron.core.storage.layout import DirectoryKind
from huron.pkg.fs.acl import Acl, AclEntry

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = ["AclPlan", "EffectiveGroups", "diff", "plan"]

RWX, RX, X, NONE = "rwx", "r-x", "--x", "---"


@dataclass(frozen=True, slots=True)
class EffectiveGroups:
    """LDAP groups per role, as ``GET /catalogs/{catalog}/grants`` returns them."""

    platform_admin: tuple[str, ...] = ()
    org_admin: tuple[str, ...] = ()
    catalog_admin: tuple[str, ...] = ()
    contributor: tuple[str, ...] = ()
    reader: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, groups: Mapping[str, Sequence[str]]) -> EffectiveGroups:
        """Read the API body."""
        return cls(**{name: tuple(groups.get(name, ())) for name in cls.__dataclass_fields__})


@dataclass(frozen=True, slots=True)
class AclPlan:
    """The mode, ACL and owning group a directory should have."""

    mode: int
    acl: Acl
    owning_group: str | None


def plan(kind: DirectoryKind, groups: EffectiveGroups) -> AclPlan:
    """The plan for one kind of directory (implementation plan, section 6.2)."""
    admins = {g: RWX for g in (*groups.platform_admin, *groups.org_admin)}
    catalog_admins = {g: RWX for g in groups.catalog_admin}
    readers = {g: RX for g in groups.reader}
    if kind is DirectoryKind.ORGANIZATION:
        return _plan(0o2771, admins, admins, _first(groups.org_admin, groups.platform_admin), X)
    if kind is DirectoryKind.COLLECTION:
        writers = {g: RWX for g in groups.contributor}
        access = {**readers, **writers, **catalog_admins, **admins}
        return _plan(0o2770, access, access, _first(groups.contributor, groups.catalog_admin), NONE)
    if kind is DirectoryKind.NAMESPACE_WITH_COLLECTIONS:
        writers = {g: RWX for g in groups.contributor}
        access = {**readers, **writers, **catalog_admins, **admins}
        return _plan(0o3770, access, admins, _first(groups.contributor, groups.catalog_admin), NONE)
    browsers = {g: RX for g in groups.contributor}
    access = {**readers, **browsers, **catalog_admins, **admins}
    return _plan(0o2770, access, admins, _first(groups.catalog_admin, groups.org_admin), NONE)


def diff(expected: AclPlan, actual: Acl) -> list[str]:
    """Human-readable differences between a plan and an ACL read back, masks ignored."""
    want, have = expected.acl.without_masks(), actual.without_masks()
    problems = [f"missing {e.render()}" for e in sorted(want.access - have.access, key=str)]
    problems += [f"unexpected {e.render()}" for e in sorted(have.access - want.access, key=str)]
    problems += [
        f"missing default:{e.render()}" for e in sorted(want.default - have.default, key=str)
    ]
    problems += [
        f"unexpected default:{e.render()}" for e in sorted(have.default - want.default, key=str)
    ]
    return problems


def _plan(
    mode: int,
    access: Mapping[str, str],
    default: Mapping[str, str],
    owning_group: str | None,
    other: str,
) -> AclPlan:
    group_perms = access.get(owning_group, RX) if owning_group else RX
    return AclPlan(
        mode=mode,
        acl=Acl(_entries(access, group_perms, other), _entries(default, group_perms, other)),
        owning_group=owning_group,
    )


def _entries(named: Mapping[str, str], group_perms: str, other: str) -> frozenset[AclEntry]:
    base = {
        AclEntry("user", None, RWX),
        AclEntry("group", None, group_perms),
        AclEntry("other", None, other),
        AclEntry("mask", None, RWX),
    }
    return frozenset(base | {AclEntry("group", group, perms) for group, perms in named.items()})


def _first(*candidates: tuple[str, ...]) -> str | None:
    for groups in candidates:
        if groups:
            return sorted(groups)[0]
    return None
