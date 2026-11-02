# Access and roles

Huron controls access with five fixed roles. Each role is a fixed set of privileges. Huron grants
roles to LDAP groups, never to persons, at the platform, at an organization or at a catalog. The
service reads your groups at login and puts them in your Huron token. On each request, it maps
those groups to roles through the current grants. The CLI then writes the groups of each catalog
into the POSIX ACLs of its directories on the share. This page tells how these parts work
together. The [glossary](../user-guide.md#glossary) defines the other Huron terms.

## The five roles

| Role | ID | Granted at | What the role adds to the roles below it |
| --- | --- | --- | --- |
| Platform Admin | `platform_admin` | the platform | Every privilege. It creates and deletes organizations, grants Org Admins, publishes platform schemas and rotates the signing key. |
| Org Admin | `org_admin` | an organization | It creates and deletes catalogs, grants Catalog Admins and publishes the schemas of the organization. |
| Catalog Admin | `catalog_admin` | an organization or a catalog | It grants Contributors and Readers, assigns the schema of a catalog, creates, configures and deletes namespaces, and deletes any collection. |
| Contributor | `contributor` | an organization or a catalog | It creates collections, writes their metadata and files, and deletes the collections that it created. |
| Reader | `reader` | an organization or a catalog | It reads the organization, the catalog, its collections and its activity. |

Each role holds every privilege of the roles below it in the table. Huron checks privileges, not
role names. A refusal answers 403 `FORBIDDEN`, and `context.privilege` names the privilege that the
operation needs ([API error codes](../api-errors.md)).

A Contributor deletes a collection only when that Contributor created it. A Catalog Admin deletes any
collection of the catalog. The [user guide](../user-guide.md#deleting) tells how to delete a collection.

## Scopes and inheritance

A grant applies at one scope: the platform, one organization or one catalog. A role that you hold
at a scope also holds at each scope that it encloses. The platform encloses everything. An
organization encloses its catalogs.

Huron has no grants on namespaces or collections. Each collection uses the access rules of its
catalog. Creating a collection does not give its creator a separate role. The creator needs a
current role to edit it or delete it.

```text
+------------------------------------------------------------+
| platform        Platform Admin                             |
|  +------------------------------------------------------+  |
|  | organization  Org Admin                              |  |
|  |               Catalog Admin, Contributor, Reader     |  |
|  |               (in every catalog of the organization) |  |
|  |  +------------------------------------------------+  |  |
|  |  | catalog     Catalog Admin, Contributor, Reader |  |  |
|  |  +------------------------------------------------+  |  |
|  +------------------------------------------------------+  |
+------------------------------------------------------------+
```

Platform Admin applies only at the platform, and Org Admin only at an organization. The three
catalog roles apply at a catalog or at an organization. A catalog role at an organization holds in
every catalog of that organization. This includes the catalogs that people create later. When the
service configuration declares the organization, these organization-wide groups are its
`groups.<role>` keys ([LDAP groups and roles](../operator.md#ldap-groups-and-roles)).

A grant on a catalog adds groups to the groups that the catalog inherits. It cannot exclude an
inherited group. Thus an organization-wide Reader sees, and can read, every catalog of the
organization. A catalog that must stay restricted needs groups of its own, and its organization
must have no organization-wide group for those people.

## Roles belong to LDAP groups

A grant is a role, an LDAP group and a scope. Huron never grants a role to a person. LDAP decides
who is in each group. Huron compares the group names literally. It does not expand a group that is
in another group. A group name must not be empty, and it must not start or end with white space.

The service configuration names one platform admin group (`platform_admin_group`). At each start,
the service makes sure that this group holds Platform Admin. The API refuses to revoke the role from
that group.

## How you get your groups

The service gets your groups from the group directory when you log in. These steps occur:

1. You log in to the company OIDC provider: with `huron login` in the CLI, or with the sign-in page
   of the web.
2. The client sends the company ID token to the service (`POST /api/v1/auth/exchange`).
3. The service checks the token against the keys of the company issuer.
4. The service asks the group directory for your groups (`GET /users/{username}/groups`).
5. The service signs a Huron token that holds your groups. The client sends that token with each
   request.

```text
CLI or web        company OIDC       Huron service       group directory
    |                  |                   |                    |
    |--- log in ------>|                   |                    |
    |<-- ID token -----|                   |                    |
    |--- ID token ------------------------>|                    |
    |                  |                   |--- your groups? -->|
    |                  |                   |<-- groups ---------|
    |<-- Huron token (with your groups) ---|                    |
```

When the group directory does not know you, you get a token without groups. When the group
directory cannot answer, the login fails with 503 `GROUP_DIRECTORY_UNAVAILABLE`.

The service reads the groups from your token, and the roles from the grants at the time of each
request. Thus a new grant or a revoke applies at your next request. A change to your membership in
LDAP applies only when the service issues a new token:

- The CLI gets a new token at `huron login`. It also gets one when it renews your token with the
  refresh token of the company provider, less than five minutes before the token expires.
- The web gets a new token when you sign in. After a change to your groups, sign out and sign in
  again.

Until then, a person who left a group keeps the roles of that group. A Huron token is valid for
eight hours by default. `huron whoami` shows your groups and the roles that they hold now. The
[user guide](../user-guide.md#logging-in) tells how to log in.

## What you can see

You see an organization when you hold a role at the platform, at that organization or at one of its
catalogs. You see a catalog when you hold a role at the platform, at its organization or at that
catalog. You see a draft collection only when you can create collections in its catalog.

Huron answers 404 `NOT_FOUND` for an object that you cannot see. It gives the same answer for an
object that does not exist. Thus a refusal does not tell you that an object exists. When you can
see an object but do not have the privilege, Huron answers 403 `FORBIDDEN`.

For example, a Reader of one catalog sees the organization of that catalog. But that Reader cannot
read the organization-wide groups of the organization, because that needs a role at the
organization.

## Who can grant what

| Grant | Privilege | Who holds it |
| --- | --- | --- |
| `platform_admin` on the platform | `ORGANIZATION_GRANT` | Platform Admin, through the API only |
| `org_admin` on an organization | `ORGANIZATION_GRANT` | Platform Admin |
| A catalog role on an organization | `CATALOG_GRANT_ADMIN` at the organization | Org Admin, Platform Admin |
| `catalog_admin` on a catalog | `CATALOG_GRANT_ADMIN` | Org Admin, Platform Admin |
| `contributor` or `reader` on a catalog | `CATALOG_GRANT_MEMBER` | Catalog Admin, Org Admin, Platform Admin |

An organization-wide Catalog Admin grants Contributors and Readers on each catalog of the
organization. But it cannot grant a role on the organization itself.

You grant and revoke roles with
[`huron adm grant`](/docs/reference/cli/adm/#huron-adm-grant) and
[`huron adm revoke`](/docs/reference/cli/adm/#huron-adm-revoke). Use `--org <org>` for an
organization and `--catalog <catalog>` for a catalog. A group can hold a role on a catalog through
its organization only. In that case, `huron adm revoke … --catalog` refuses, and it names the
command that revokes the role with `--org`.

When the service configuration declares an organization, the configuration owns its four
organization-wide roles. At each start, the service sets the groups of `org_admin`,
`catalog_admin`, `contributor` and `reader` to the `groups` of the declaration. The API refuses a
change to these groups with 409 `ORGANIZATION_DECLARED`. The CLI then names the `groups.<role>` key
to edit. You still change the grants on a single catalog of that organization with the CLI. The
[declared organizations](../operator.md#declared-organizations) section tells more.

## How roles become directory ACLs

The service mounts no share. The CLI creates each directory as the user who runs it, and it gives
the directory an ACL plan. A plan is a mode, POSIX ACL entries for groups, and an owning group. The
CLI makes the plan from the groups of the catalog (`GET /api/v1/catalogs/{catalog}/grants`). These
groups include the groups that the catalog inherits. The API never sends ACL entries.

| Directory kind | Mode | Access ACL | Default ACL | Others |
| --- | --- | --- | --- | --- |
| organization | `2771` | Platform Admin and Org Admin `rwx` | the same as the access ACL | `--x` |
| catalog | `2770` | Platform Admin, Org Admin and Catalog Admin `rwx`. Contributor and Reader `r-x` | Platform Admin and Org Admin `rwx` | `---` |
| namespace without collections | `2770` | the same as a catalog | Platform Admin and Org Admin `rwx` | `---` |
| namespace that allows collections | `3770` | Platform Admin, Org Admin, Catalog Admin and Contributor `rwx`. Reader `r-x` | Platform Admin and Org Admin `rwx` | `---` |
| collection | `2770` | the same as a namespace that allows collections | the same as the access ACL | `---` |

Each cell names the groups of a role. When a group holds more than one role, its entry gets the
widest permissions of those roles. New files and directories get the default ACL. Thus the files in
a collection are writable for its Contributors.

The owning group of a directory is the first group, in sorted order, of this list:

- An organization: the Org Admin groups, else the Platform Admin groups.
- A catalog or a namespace without collections: the Catalog Admin groups, else the Org Admin groups.
- A namespace that allows collections, or a collection: the Contributor groups, else the Catalog
  Admin groups.

Each mode sets the setgid bit, so new entries get the owning group of their directory. A namespace
that allows collections also sets the sticky bit. In such a directory, only the owner of an entry,
the owner of the directory or root can delete or rename that entry.

The storage administrator prepares the directory of each declared organization with
[`huron adm provision-orgs`](/docs/reference/cli/adm/#huron-adm-provision-orgs). That command
applies the organization plan ([Adding an organization](../operator.md#adding-an-organization)). With
`acl_backend: none` in the CLI configuration, the CLI sets the modes only.

## Re-applying ACLs

Only the owner of a directory can change its ACL. Thus a grant change does not change the ACLs of
directories that exist. The owners re-apply the plans with
[`huron adm apply-acl <identifier>`](/docs/reference/cli/adm/#huron-adm-apply-acl). Add
`--recursive` to include each directory below the identifier. The command changes only the
directories that you own. It prints each directory that it skips, and then it exits with code 1.

After a change to a catalog role, `huron adm grant` and `huron adm revoke` print the
`huron adm apply-acl <catalog> --recursive` command for each catalog that the change concerns. They
print it in the table output only. After
an operator changes the `groups` of a declared organization, run that command for each catalog of
the organization. For a change to `groups.org_admin`, run `huron adm provision-orgs` to re-apply the
ACL of the organization directory.

`huron adm check` reports a directory whose ACL is not its plan as `acl_drift`, or as
`org_acl_drift` for an organization directory
([Reading `huron adm check`](../operator.md#reading-huron-adm-check)).

API access and filesystem access change separately. Revoking a grant affects the next API
request, but it does not change an existing ACL. The filesystem uses the machine's user and group
identity, not the Huron token. The storage environment must resolve the LDAP groups in the ACLs.
Use the current grants to update the directory ACLs after a role change.

## Seeing grants

[`huron get grants`](/docs/reference/cli/get/#huron-get-grants) prints one row for each role and
group of a catalog. Its `SOURCE` column tells where the grant is:

- `platform`: the grant is on the platform.
- `organization <org>`: the grant is on the organization, and every catalog of it inherits the role.
- `catalog`: the grant is on this catalog only.

A group can show two times for one role, one time for each source. `huron get grants --org <org>`
prints the organization-wide groups of each role. The
[user guide](../user-guide.md#who-has-access) gives examples.

The web shows the same grants on the **Access** tab of a catalog. It puts the groups of each role
under their source: the platform, the organization or the catalog. It marks your groups with **You**.
The **Access** tab of an organization shows the organization-wide groups of its four roles. For a
declared organization, the tab tells you that the service configuration sets these groups. The web
does not change grants. To change a grant, use the CLI ([In a browser](../user-guide.md#in-a-browser)).

## Related pages

- [User guide: Who has access](../user-guide.md#who-has-access)
- [Operator guide: LDAP groups and roles](../operator.md#ldap-groups-and-roles)
- [Operator guide: Declared organizations](../operator.md#declared-organizations)
- [`huron adm` reference](/docs/reference/cli/adm/)
- [`huron get grants` reference](/docs/reference/cli/get/#huron-get-grants)
- [`huron whoami` reference](/docs/reference/cli/whoami/)
- [API error codes](../api-errors.md)
- [How Huron works](how-huron-works.md#who-does-what): who does what in Huron.
- [Drift detection](raw-ingest.md#drift-detection) in How raw ingest works.
