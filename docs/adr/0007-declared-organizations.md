# Organizations declared in the service configuration, each with its own root

Status: accepted (2026-10-31)

## Context

Organizations were created at run time with `huron create org`, and every organization directory
lived under one mount prefix (`/projects/huron/<org>`). Sites keep organizations' data on NFS
exports of their choosing (`/data1/huron/helio`, `/data1/huron/geo`), the storage administrator, not a platform
admin at a terminal, decides where an export goes, and the list of organizations and their
administrator groups changes rarely and belongs under change control with the rest of the
deployment.

## Decision

The service configuration (`HURON_CONFIG_FILE`, a YAML file; a Helm value or a kustomize ConfigMap)
may declare the organizations: name, display name, description, the exact groups of each
organization-wide role (below) and an optional root. An organization's directory is always
`<root>/<name>`; one without a root stays at the CLI's mount prefix. At startup the service
reconciles the database to the declaration under an advisory lock: it creates missing organizations,
updates changed names and descriptions and replaces each organization-wide role's groups exactly,
and writes nothing when nothing differs. It never deletes: an organization removed from the
configuration is logged and stays usable. While a declaration exists the API refuses to create
organizations, to delete declared ones and to edit any of their organization-wide role groups (409).
The storage administrator prepares each organization directory with `huron adm provision-orgs`,
which writes a per-organization marker the CLI checks before any disk operation below it. No
declaration means the previous behavior.

## Consequences

Organizations, their administrators and their storage follow the deployment's review and rollout,
and two replicas starting together agree. The service still mounts nothing; roots are strings it
reports. Renaming an organization is removing one and declaring another, and the old one stays
until it is emptied and deleted. A mistyped key fails startup instead of silently turning the
declaration off. Every machine that runs the CLI must mount each export at its configured root.

## Organization-wide role groups (2026-10-31)

Decided with the user on 2026-10-31, replacing the entry's `admin_groups`.

Context: a site gives each organization one set of LDAP groups (admins, catalog admins,
contributors, readers) and wants every catalog of the organization, including catalogs created
later, to use them. Granting the same groups on each catalog by hand repeats the configuration in
the database, drifts as catalogs are added and puts access for a whole organization outside change
control.

Decision: each entry's `groups` maps `org_admin`, `catalog_admin`, `contributor` and `reader` to
LDAP groups, each key optional (default none) and any other key a startup error; `admin_groups` is
removed without an alias (pre-release), and a configuration that still uses it fails startup with a
message naming `groups.org_admin`. The three catalog roles may be granted at organization scope.
The authorizer already treats an organization as enclosing its catalogs, so an organization-scope
Contributor holds Contributor privileges in every catalog of the organization, and visibility
follows the existing rule (a role at the organization shows the organization and its catalogs).
Startup reconciliation sets all four organization-scope role sets exactly, under the bootstrap
lock. For a declared organization the API refuses edits of any of the four (409
`ORGANIZATION_DECLARED`); in unmanaged mode they are API-managed: `org_admin` by a Platform Admin,
the three catalog roles by an Org Admin or Platform Admin. An organization-scope Catalog Admin
administers every catalog of the organization, including its per-catalog member grants, but does
not grant organization-wide roles. Per-catalog grants are unchanged and add to the inherited
groups; they cannot remove one. A catalog's effective groups (`GET /catalogs/{catalog}/grants`, the
input of its ACL plans) merge the organization-scope groups in, and
`GET /catalogs/{catalog}/grants/sources` reports each group's source: platform, organization or
catalog.

Consequences: one configuration entry gives an organization its access model, and new catalogs need
no grants. An organization-wide reader sees every catalog of the organization, so a restricted
catalog uses groups of its own and its organization keeps organization-wide groups to people who
may see every catalog. Changing `groups` changes the ACL plans of every catalog of the
organization: after a rollout the directories' owners re-apply ACLs (`huron adm apply-acl`).
`GET /organizations/{org}/grants` now answers every organization-scope role instead of
`{ldap_groups}` for `org_admin` alone.
