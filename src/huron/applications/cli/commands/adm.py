"""``huron adm``: roles, directory modes, organization mounts, drift checks, repairs and schemas."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from typing import Annotated, Any, Literal

import typer
from rich.console import Console

from huron.applications.cli.commands.common import (
    api,
    grant_sources,
    read_document,
    say,
    services,
    set_groups,
    show,
    show_list,
    table_mode,
    warn_share_groups,
)
from huron.applications.cli.errors import ApiError, StorageFailure, UsageError
from huron.applications.cli.identifiers import resolve_identifier
from huron.applications.cli.inventory import CatalogInventory, take_inventory
from huron.applications.cli.mount import (
    PREFIX_MARKER_HINT,
    PROVISION_HINT,
    UNDECLARED_HINT,
    Mount,
    Site,
)
from huron.applications.cli.output import Column
from huron.applications.cli.services import Services
from huron.core.storage import (
    LakePath,
    Marker,
    MarkerState,
    OrganizationPlace,
    StorageError,
    marker_state,
)
from huron.core.storage.check import (
    ExpectedCollection,
    ExpectedDirectory,
    ExpectedOrganization,
    Finding,
    Severity,
    check,
    check_organization,
)
from huron.core.storage.provision import OrganizationTarget, Provisioner, provision_script

__all__ = ["adm_app", "declared_groups_hint", "register"]

ACCESS = "Access"
SHARE = "Share"
SCHEMAS = "Schemas"

adm_app = typer.Typer(
    help="Run administration tasks: roles, directory modes, drift checks, repairs and schemas.",
    no_args_is_help=True,
)
publish_app = typer.Typer(help="Publish a schema.", no_args_is_help=True)
assign_app = typer.Typer(help="Assign a schema to a catalog.", no_args_is_help=True)
adm_app.add_typer(publish_app, name="publish", rich_help_panel=SCHEMAS)
adm_app.add_typer(assign_app, name="assign", rich_help_panel=SCHEMAS)

Role = Literal["org_admin", "catalog_admin", "contributor", "reader"]
RoleArgument = Annotated[
    Role, typer.Argument(help="`org_admin`, `catalog_admin`, `contributor` or `reader`.")
]
GroupArgument = Annotated[str, typer.Argument(help="An LDAP group.")]
OrgOption = Annotated[
    str | None,
    typer.Option(
        "--org",
        help="The organization, for `org_admin` or for a catalog role in all its catalogs.",
    ),
]
CatalogOption = Annotated[
    str | None,
    typer.Option(
        "--catalog", help="The catalog, for a catalog role. The default is the current catalog."
    ),
]

MOUNT_COLUMNS = [
    Column("ORG", lambda r: r["organization"]),
    Column("PATH", lambda r: r["path"]),
    Column("STATE", lambda r: r["state"]),
]
#: The ``verify-mounts`` state of an organization the managed configuration does not declare.
UNDECLARED = "undeclared"

#: The ``provision-orgs`` row name of the lake path's steps.
LAKE_PATH = "lake path"
STEP_COLUMNS = [Column("ORG", lambda r: r["organization"]), Column("STEP", lambda r: r["step"])]

FINDING_COLUMNS = [
    Column("SEVERITY", lambda f: f["severity"]),
    Column("CODE", lambda f: f["code"]),
    Column("IDENTIFIER", lambda f: f["identifier"]),
    Column("PATH", lambda f: f["path"]),
    Column("DETAIL", lambda f: f["detail"]),
]


def register(app: typer.Typer, panel: str) -> None:
    """Add ``huron adm`` under the help panel ``panel``."""
    app.add_typer(adm_app, name="adm", rich_help_panel=panel)


@adm_app.command("grant", rich_help_panel=ACCESS)
def grant(
    ctx: typer.Context,
    role: RoleArgument,
    group: GroupArgument,
    organization: OrgOption = None,
    catalog: CatalogOption = None,
) -> None:
    """Give a role to an LDAP group on an organization (`--org`) or a catalog (`--catalog`).

    You can grant `org_admin` only on an organization. A catalog role on an organization applies
    to all its catalogs, existing and future. A grant on a catalog adds to those grants.
    """
    target = _grant_target(ctx, role, organization, catalog)
    _set_role(ctx, role, target, sorted({*target.groups, group}))


@adm_app.command("revoke", rich_help_panel=ACCESS)
def revoke(
    ctx: typer.Context,
    role: RoleArgument,
    group: GroupArgument,
    organization: OrgOption = None,
    catalog: CatalogOption = None,
) -> None:
    """Take a role from an LDAP group on an organization (`--org`) or a catalog (`--catalog`).

    A group that holds a catalog role through the organization of the catalog keeps that role in
    all catalogs of the organization. To take that role from the group, revoke it on the
    organization with `--org`.
    """
    target = _grant_target(ctx, role, organization, catalog)
    if group not in target.groups and group in target.inherited:
        raise _inherited(ctx, role, group, target)
    _set_role(ctx, role, target, [g for g in target.groups if g != group])


@adm_app.command("check", rich_help_panel=SHARE)
def check_share(
    ctx: typer.Context,
    catalog: Annotated[
        str | None, typer.Option("--catalog", help="Check only this catalog.")
    ] = None,
    hash_files: Annotated[
        bool, typer.Option("--hash", help="Also compare the `sha256` of each file.")
    ] = False,
) -> None:
    """Report drift between the service and the share. The exit code is 1 when there are findings.

    The check starts with the organization directories. It skips the catalogs of an
    organization when the marker in its own directory is missing or wrong. It also skips the
    catalogs of an organization that the managed service configuration no longer declares, when
    the mount prefix is not its share (`org_undeclared`).
    """
    found = services(ctx)
    names = [catalog] if catalog else [c["name"] for c in api(ctx).pages("/api/v1/catalogs")]
    inventories = [take_inventory(api(ctx), name, files=True) for name in names]
    organizations = {str(i.catalog["organization"]) for i in inventories}
    if catalog is None:
        organizations |= {str(o["name"]) for o in api(ctx).pages("/api/v1/organizations")}
    findings = _drift(found, organizations, inventories, hash_files)
    show_list(ctx, [f.as_dict() for f in findings], FINDING_COLUMNS)
    if findings:
        raise typer.Exit(1)


@adm_app.command("verify-mounts", rich_help_panel=SHARE)
def verify_mounts(ctx: typer.Context) -> None:
    """Check that the directory of each organization is mounted and has this service's marker.

    The table has one row for each organization. Its state is `ok`, `missing`, `no marker`,
    `wrong instance` or `wrong org`. The exit code is 1 when a state is not `ok`. For an
    organization without its own marker, the CLI checks the marker at the mount prefix. An
    organization that the managed service configuration does not declare has no known root.
    Its state is `undeclared`, and it does not make the check fail.
    """
    mount = services(ctx).mount()
    sites = [mount.site_of_view(view) for view in api(ctx).pages("/api/v1/organizations")]
    rows = [_mount_row(mount, site) for site in sites]
    if not rows:
        prefix = {"organization": "-", "path": f"{mount.prefix} (prefix)"}
        rows.append(("prefix", {**prefix, "state": str(mount.prefix_state())}))
    show_list(ctx, [row for _, row in rows], MOUNT_COLUMNS)
    if not _mount_verdict(ctx, rows):
        raise typer.Exit(1)


@adm_app.command("provision-orgs", rich_help_panel=SHARE)
def provision_orgs(
    ctx: typer.Context,
    organization: Annotated[
        str | None, typer.Option("--org", help="Prepare only this declared organization.")
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Print the planned steps. Do not change anything.")
    ] = False,
    emit_script: Annotated[
        bool,
        typer.Option(
            "--emit-script", help="Print an equivalent shell script, for roots that `root` owns."
        ),
    ] = False,
) -> None:
    """Mark the lake path and prepare each declared organization below its root (storage admin).

    The lake path is `mount_prefix` on this machine. The lake path and each root must exist.
    The command writes a marker for this service at the lake path. When an organization
    directory does not exist, the command creates it. The command sets the mode of the directory
    and writes a marker for this service and the organization. You can run the command again
    safely.
    """
    found = services(ctx)
    mount = found.mount()
    lake = Marker(1, found.config.api_url, mount.instance_id())
    targets = [_target(lake, mount, view) for view in _declared(ctx, organization)]
    if emit_script:
        script = provision_script(str(mount.prefix), lake, targets)
        found.out.print(script, markup=False, highlight=False, end="", soft_wrap=True)
        return
    provisioner = Provisioner(found.provision_storage(mount.prefix), str(mount.prefix))
    rows, failed = _provision(found.err, provisioner, lake, targets, dry_run)
    if table_mode(ctx):
        for row in rows:
            say(ctx, f"{row['organization']}: {row['step']}")
    else:
        show_list(ctx, rows, STEP_COLUMNS)
    if failed:
        raise StorageFailure(
            f"the CLI could not prepare {len(failed)} of {len(targets) + 1} directories:"
            f" {', '.join(failed)}",
            hint=(
                "when only `root` may write to a root, run `huron adm provision-orgs --emit-script`"
            ),
        )


@adm_app.command("repair", rich_help_panel=SHARE)
def repair(
    ctx: typer.Context,
    identifier: Annotated[
        str | None,
        typer.Argument(help="`catalog`, `catalog.namespace` or `catalog.namespace.name`."),
    ] = None,
    recursive: Annotated[
        bool,
        typer.Option(
            "--recursive",
            help="Also repair each namespace and each collection below the identifier.",
        ),
    ] = False,
    organization: Annotated[
        str | None, typer.Option("--org", help="Repair the directory of this organization.")
    ] = None,
) -> None:
    """Repair missing directories and wrong permission bits through the API.

    With an identifier, the API repairs each directory from the catalog to the identifier
    (Catalog Admin). It also tries to give the catalog directory its share group. It writes each
    `metadata.json` that has wrong content. A draft collection has no directory. With `--org`, the
    API repairs the directory of the organization (Org Admin).

    The command shows each path that the API changed and each path that it could not repair.
    The exit code is 8 when the API could not repair a path.
    """
    route, body = _repair_request(ctx, identifier, organization, recursive)
    result = api(ctx).post(route, json=body)
    if not table_mode(ctx):
        show(ctx, result)
    warn_share_groups(ctx, result["warnings"])
    for path in result["changed"]:
        say(ctx, f"changed {path}")
    failed = result["failed"]
    for failure in failed:
        say(ctx, f"failed {failure['path']} ({failure['reason']}): {failure['detail']}")
    if failed:
        paths = "path" if len(failed) == 1 else "paths"
        raise StorageFailure(f"the API could not repair {len(failed)} {paths}")
    if not result["changed"]:
        say(ctx, "The API changed nothing")


def declared_groups_hint(role: str) -> str:
    """The hint for a 409 ``ORGANIZATION_DECLARED`` on an organization-wide ``role``."""
    return (
        "the service configuration declares the groups of this organization."
        f" Edit `groups.{role}` there. Then restart the service"
    )


@publish_app.command("schema")
def publish_schema(
    ctx: typer.Context,
    organization: Annotated[str, typer.Argument(help="An organization, or `platform`.")],
    name: str,
    file: Path,
    extends: Annotated[
        str | None, typer.Option("--extends", help="The ID of the schema that it extends.")
    ] = None,
) -> None:
    """Publish the next version of a named schema from a JSON file."""
    document = read_document(file)
    body = {"name": name, "extends_id": extends, "document": document}
    path = (
        "/api/v1/platform/schemas"
        if organization == "platform"
        else f"/api/v1/organizations/{organization}/schemas"
    )
    entry = api(ctx).post(path, json=body)
    say(ctx, f"published {entry['name']} v{entry['version']} ({entry['id']})")


@assign_app.command("schema")
def assign_schema(
    ctx: typer.Context,
    schema_id: str,
    catalog: Annotated[
        str | None, typer.Option("--catalog", help="The default is the current catalog.")
    ] = None,
) -> None:
    """Assign a schema to a catalog and check its collections again."""
    target = catalog or services(ctx).require_catalog()
    result = api(ctx).put(f"/api/v1/catalogs/{target}/schema", json={"schema_id": schema_id})
    counts = result["recompute"]
    say(
        ctx,
        f"{target} now uses {result['assigned']['schema']['name']}"
        f" v{result['assigned']['schema']['version']}:"
        f" {counts['active']} active, {counts['incomplete']} incomplete,"
        f" {counts['changed']} changed",
    )


def _grant_target(
    ctx: typer.Context, role: str, organization: str | None, catalog: str | None
) -> _GrantTarget:
    """Where ``role`` is granted (--org or --catalog) and the groups holding it there."""
    if organization is not None and catalog is not None:
        raise UsageError("use `--org` or `--catalog`, not both")
    if organization is not None:
        path = f"/api/v1/organizations/{organization}/grants"
        groups = tuple(api(ctx).get(path)[role])
        return _GrantTarget(f"{path}/{role}", groups, organization=organization)
    if role == "org_admin":
        raise UsageError(
            "you can grant `org_admin` only on an organization", hint="use `--org <name>`"
        )
    target = catalog or services(ctx).require_catalog()
    sources = grant_sources(ctx, target)

    def held(scope: str) -> tuple[str, ...]:
        return tuple(s["group"] for s in sources if s["role"] == role and s["scope"] == scope)

    return _GrantTarget(
        f"/api/v1/catalogs/{target}/grants/{role}",
        held("catalog"),
        catalog=target,
        inherited=held("organization"),
    )


def _inherited(ctx: typer.Context, role: str, group: str, target: _GrantTarget) -> UsageError:
    """The refusal to revoke on a catalog a role the group holds through the organization."""
    organization = api(ctx).get(f"/api/v1/catalogs/{target.catalog}")["organization"]
    return UsageError(
        f"{group} holds {role} on {target.catalog} through organization {organization},"
        " not through a grant on the catalog",
        hint=(
            "to revoke it on the organization,"
            f" run `huron adm revoke {role} {group} --org {organization}`"
        ),
    )


def _repair_request(
    ctx: typer.Context, identifier: str | None, organization: str | None, recursive: bool
) -> tuple[str, dict[str, Any] | None]:
    """The repair route of ``identifier`` or of ``organization``, and its body."""
    if organization is not None:
        if identifier is not None:
            raise UsageError("use an identifier or `--org`, not both")
        if recursive:
            raise UsageError("use `--recursive` only with an identifier")
        return f"/api/v1/organizations/{organization}/repair", None
    if identifier is None:
        raise UsageError("use an identifier or `--org <org>`")
    target = resolve_identifier(identifier, services(ctx).catalog())
    body = {"target": str(target), "recursive": recursive}
    return f"/api/v1/catalogs/{target.catalog}/repair", body


def _set_role(ctx: typer.Context, role: str, target: _GrantTarget, groups: list[str]) -> None:
    try:
        set_groups(ctx, target.path, groups)
    except ApiError as error:
        if target.organization is not None and error.code == "ORGANIZATION_DECLARED":
            error.hint = declared_groups_hint(role)
        raise


def _drift(
    found: Services,
    organizations: Iterable[str],
    inventories: Iterable[CatalogInventory],
    hash_files: bool,
) -> list[Finding]:
    """Organization findings first, then those of each catalog its organization lets us see."""
    mount = found.mount()
    findings, blocked = _organizations_pass(mount, organizations)
    for inventory in inventories:
        organization = str(inventory.catalog["organization"])
        if organization in blocked:
            continue
        base = mount.verify(organization).base
        findings += _shown(
            base,
            check(
                mount.reader(base),
                _directories(inventory),
                _collections(inventory),
                found.clock.now(),
                hash_files=hash_files,
            ),
        )
    return findings


def _shown(base: Path, findings: Iterable[Finding]) -> list[Finding]:
    """``findings`` with their lake paths shown as paths on this machine."""
    return [replace(f, path=str(base / f.path)) if f.path else f for f in findings]


def _organizations_pass(
    mount: Mount, organizations: Iterable[str]
) -> tuple[list[Finding], set[str]]:
    """Organization findings, and the organizations whose directory forbids looking further."""
    findings: list[Finding] = []
    blocked: set[str] = set()
    for organization in sorted(organizations):
        here, stop = _organization_findings(mount, organization)
        findings += here
        if stop:
            blocked.add(organization)
    return findings, blocked


def _organization_findings(mount: Mount, organization: str) -> tuple[list[Finding], bool]:
    """The findings of one organization, and whether its catalogs must not be looked at.

    An organization without its own marker needs the mount prefix's marker; one the managed
    configuration does not declare gets a warning instead when the prefix is not its share.
    """
    site = mount.site(organization)
    if not site.own_marker:
        if mount.undeclared(site) and mount.prefix_state() is not MarkerState.OK:
            detail = (
                "the service configuration does not declare it,"
                " so the CLI cannot find its directory"
            )
            warning = Finding(
                "org_undeclared", Severity.WARNING, organization, str(site.directory), detail
            )
            return [warning], True
        mount.verify_prefix()
    expected = ExpectedOrganization(
        organization, LakePath.of(organization), mount.instance_id(), site.own_marker
    )
    found = _shown(site.base, check_organization(mount.reader(site.base), expected))
    return found, site.own_marker and _has_error(found)


def _has_error(findings: Iterable[Finding]) -> bool:
    return any(finding.severity is Severity.ERROR for finding in findings)


def _mount_verdict(ctx: typer.Context, rows: Iterable[tuple[str, dict[str, str]]]) -> bool:
    """Print the hints the failing rows call for; whether every counted row is ok."""
    rows = list(rows)
    failed = {kind for kind, row in rows if row["state"] not in {MarkerState.OK, UNDECLARED}}
    hints = {"own": PROVISION_HINT, "prefix": PREFIX_MARKER_HINT}
    for kind in sorted(failed):
        say(ctx, hints[kind])
    if any(kind == UNDECLARED for kind, _ in rows):
        say(ctx, UNDECLARED_HINT)
    return not failed


def _mount_row(mount: Mount, site: Site) -> tuple[str, dict[str, str]]:
    """One organization's row, after the kind of check it got: own, prefix or undeclared."""
    name, directory = site.name, site.directory
    if site.own_marker:
        reader = mount.reader(site.base)
        state = marker_state(reader, LakePath.of(name), mount.instance_id(), name)
        return "own", {"organization": name, "path": str(directory), "state": str(state)}
    if mount.undeclared(site):
        row = {"organization": name, "path": f"{directory} (undeclared)", "state": UNDECLARED}
        return UNDECLARED, row
    prefix = str(mount.prefix_state())
    return "prefix", {"organization": name, "path": f"{directory} (prefix)", "state": prefix}


def _declared(ctx: typer.Context, organization: str | None) -> list[dict[str, Any]]:
    declared = [o for o in api(ctx).pages("/api/v1/organizations") if o.get("declared")]
    if organization is None:
        return declared
    chosen = [o for o in declared if o["name"] == organization]
    if not chosen:
        raise UsageError(
            f"the service configuration does not declare organization {organization}",
            hint="to see the organizations and their paths, run `huron get orgs`",
        )
    return chosen


def _target(lake: Marker, mount: Mount, view: dict[str, Any]) -> OrganizationTarget:
    """The provisioning of a declared organization, whose root lies below the lake path."""
    site = mount.site_of_view(view)
    if not site.base.is_relative_to(mount.prefix):
        raise UsageError(
            f"the root {site.base} of organization {site.name} is not below the lake path"
            f" {mount.prefix}",
            hint="set `mount_prefix` to the directory where this machine mounts `lake_path`",
        )
    base = LakePath.of(*site.base.relative_to(mount.prefix).parts)
    place = OrganizationPlace(site.name, base, own_marker=True)
    return OrganizationTarget(place, replace(lake, organization=site.name))


def _provision(
    err: Console,
    provisioner: Provisioner,
    lake: Marker,
    targets: Iterable[OrganizationTarget],
    dry_run: bool,
) -> tuple[list[dict[str, str]], list[str]]:
    """The steps of the lake path, then of each organization, and the names that failed."""
    jobs: list[tuple[str, Callable[[], list[str]]]] = [
        (LAKE_PATH, partial(provisioner.mark_lake, lake, dry_run=dry_run))
    ]
    jobs += [
        (target.place.name, partial(provisioner.provision, target, dry_run=dry_run))
        for target in targets
    ]
    rows: list[dict[str, str]] = []
    failed: list[str] = []
    for name, job in jobs:
        try:
            steps = job()
        except StorageError as error:
            err.print(f"error: {name}: {error.message}", markup=False, highlight=False)
            failed.append(name)
            continue
        rows += [{"organization": name, "step": step} for step in steps]
    return rows, failed


def _directories(inventory: CatalogInventory) -> list[ExpectedDirectory]:
    return [
        ExpectedDirectory(identifier, disk_path)
        for identifier, disk_path in inventory.directories()
    ]


def _collections(inventory: CatalogInventory) -> list[ExpectedCollection]:
    return [
        ExpectedCollection(
            identifier=c["identifier"],
            state=c["state"],
            created_at=c["created"],
            disk_path=c.get("path"),
            files=c.get("files", {}),
            sidecar=c.get("sidecar"),
        )
        for c in inventory.collections
    ]


@dataclass(frozen=True, slots=True)
class _GrantTarget:
    """Where a role is granted, the groups holding it there and, on a catalog, those inherited.

    ``path`` is the ``PUT`` route; exactly one of ``organization`` and ``catalog`` is set.
    """

    path: str
    groups: tuple[str, ...]
    organization: str | None = None
    catalog: str | None = None
    inherited: tuple[str, ...] = ()
