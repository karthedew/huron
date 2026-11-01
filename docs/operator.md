# Operator guide

## Prerequisites

- **LDAP groups.** One platform admin group (for example `huron-platform-admins`) and, per
  organization, groups for org admins, catalog admins, contributors and readers, plus groups of
  their own for catalogs that must stay restricted. Huron grants roles to groups; membership is
  managed in LDAP. [LDAP groups and roles](#ldap-groups-and-roles) recommends a set.
- **The share.** One or more NFS exports, each mounted at the same path on every machine where
  people run the CLI. Each organization's directory is `<root>/<org>`: with a root declared in the
  service configuration (for example `/data1/huron/helio` and `/data1/huron/geo`), or
  else under the CLI's mount prefix (default `/projects/huron/<org>`). Users need their LDAP groups
  resolved on those machines (sssd) for POSIX ACLs to apply. Check with `getfacl` that each export
  honors POSIX ACLs; if one does not, set `acl_backend: none` in each user's CLI configuration and
  Huron applies modes only.
- **A group directory** answering `GET /users/{username}/groups` with `{"groups": [...]}`.
- **An OIDC client** `huron-cli`: public, with the device grant and `http://127.0.0.1` loopback
  redirects enabled. The loopback flow sends PKCE (S256). With Keycloak 26, do not set PKCE as
  required on `huron-cli`: Keycloak then demands PKCE at the device endpoint, which the CLI's
  device flow does not send yet.
- **PostgreSQL 16.**

## Configuration

The service reads `HURON_*` environment variables
(`src/huron/applications/api/settings.py`) and, when `HURON_CONFIG_FILE` names one, a YAML file
whose top-level keys are the same settings in lower case without the prefix, plus `organizations`.
An environment variable wins over the file, and the file over the defaults. Keep
`HURON_DATABASE_URL` in the environment (a Secret); the file accepts it, but it is not a secret
store. Unknown top-level keys and two organizations with the same name stop the service at
startup, so a typo such as `organisations:` cannot go unnoticed.

```yaml
instance_id: 0192b6a0-0000-7000-8000-000000000001
issuer: https://huron.apps.example.org
company_issuer: https://login.example.org/realms/company
company_audience: huron-cli
group_directory_url: https://groups.example.org
platform_admin_group: huron-platform-admins
organizations:
  - name: helio
    display_name: Heliophysics
    groups:
      org_admin: [huron-helio-admins]
      catalog_admin: [huron-helio-catalog-admins]
      contributor: [huron-helio-contributors]
      reader: [huron-helio-readers]
    root: /data1/huron
    export: nfs1.example.org:/export/data1
  - name: geo
    display_name: Geoscience
    groups:
      org_admin: [huron-geo-admins]
      reader: [huron-geo-readers]
    root: /data1/huron
```

### Declared organizations

An `organizations` key, even an empty list, puts the service in managed mode: the configuration
decides which organizations exist and who administers them. Each entry has a `name` (the naming
rules of every Huron name: lowercase letters, digits, `-` and `_`, at most 63 bytes), and optionally
`display_name`, `description`, `groups` (the LDAP groups of each organization-wide role, below),
`root` (an absolute path; the organization's directory is always `<root>/<name>`) and `export` (the
NFS source, shown in the CLI's hints). An organization without `root` lives at
`<mount_prefix>/<name>`, where the CLI's `mount_prefix` points. `HURON_ORGANIZATIONS`, a JSON list,
replaces the file's list in an emergency.

At every start the service brings the database in line, under a lock so replicas starting together
take turns: it creates missing organizations, updates changed display names and descriptions, and
sets each organization's groups for all four organization-wide roles to exactly its `groups`, with
the usual audit entries. When nothing differs it writes nothing. It never deletes: an organization
you remove from the configuration is logged as a warning at startup (with its catalog count) and
stays in the database: its catalogs, grants and metadata remain usable through the API and the web.
Its directory does not follow it, though: the root came from the configuration, so the CLI no longer
knows where the directory is and looks for it under the mount prefix only. Removing a rooted
organization from the configuration therefore strands its directory until you declare it again with
the same root, which restores everything. To retire one, empty it while it is still declared (delete
its collections, namespaces and catalogs), then remove the entry, then `huron delete org`, which
leaves the old directory to the storage administrator. `huron adm verify-mounts` shows such an
organization as `undeclared` (not a failure), `huron get orgs` marks its path `(undeclared)` and
`huron adm check` reports `org_undeclared` (a warning) unless the mount prefix is a marked share
where it lives. In managed mode the API refuses to create organizations (`ORGANIZATIONS_MANAGED`),
to delete declared ones and to change any of their organization-wide role groups
(`ORGANIZATION_DECLARED`; `huron adm grant … --org` names the `groups.<role>` key to edit instead).
Grants on a single catalog stay with the CLI. A rename is a removal and an addition: the old
organization stays until it is emptied and deleted.

Without an `organizations` key the service is unmanaged: platform admins create organizations with
`huron create org` and grant Org Admins with `huron adm grant org_admin <group> --org <org>`, Org
Admins grant the organization-wide catalog roles with `huron adm grant <role> <group> --org <org>`,
and every organization lives under the mount prefix.

### LDAP groups and roles

`groups` maps each organization-wide role to its LDAP groups. All four keys are optional and
default to no group; any other key, and the former `admin_groups`, stops the service at startup.

| Key | Holds | Where |
| --- | --- | --- |
| `org_admin` | Org Admin | the organization and every catalog in it |
| `catalog_admin` | Catalog Admin | every catalog of the organization |
| `contributor` | Contributor | every catalog of the organization |
| `reader` | Reader | every catalog of the organization |

Every catalog inherits these, the existing ones and those created later, without a grant of its
own. A grant on one catalog (`huron adm grant reader <group> --catalog <catalog>`) adds a group to
that catalog; it cannot remove an inherited one. `huron get grants --catalog <catalog>` shows each
group with its source: `platform`, `organization <org>` or `catalog`. The catalog directories' ACLs
name the inherited groups too, so after changing `groups` and rolling out, the directories' owners
run `huron adm apply-acl <catalog> --recursive` for each catalog of the organization.

The recommended set, one group per role and organization plus the platform's:

| Group | Role |
| --- | --- |
| `huron-platform-admins` | Platform Admin (`platform_admin_group`) |
| `huron-<org>-admins` | `groups.org_admin` |
| `huron-<org>-catalog-admins` | `groups.catalog_admin` |
| `huron-<org>-contributors` | `groups.contributor` |
| `huron-<org>-readers` | `groups.reader` |

```yaml
platform_admin_group: huron-platform-admins
organizations:
  - name: helio
    groups:
      org_admin: [huron-helio-admins]
      catalog_admin: [huron-helio-catalog-admins]
      contributor: [huron-helio-contributors]
      reader: [huron-helio-readers]
    root: /data1/huron
```

- **POSIX groups.** Make each one a POSIX group with a `gidNumber`, resolvable through sssd on
  every machine that runs the CLI: the directories' ACL entries name these groups, and `setfacl`
  fails on a group the machine cannot resolve. `getent group huron-helio-readers` must answer there.
- **Nested groups** only if the group directory (`group_directory_url`) returns them flattened, as
  the user's effective groups. Huron matches the group names it receives literally and does not
  expand a group within a group.
- **Membership changes** take effect at a user's next login: the groups are read from the group
  directory at sign-in (the CLI's `huron login`, the web's sign-in) and travel in the Huron token,
  so someone removed from a group keeps its role until their next sign-in.
- **Restricted catalogs.** An organization-wide reader sees, and can read, every catalog of the
  organization. Give a catalog that only some people may see groups of its own, granted on that
  catalog (`huron-<org>-<catalog>-readers` and so on), and keep its organization's `groups` to
  people who may see every catalog, or put the restricted catalog in an organization of its own.

In unmanaged mode the same four roles are granted at the organization with
`huron adm grant <role> <group> --org <org>`: `org_admin` by a Platform Admin, the three catalog
roles by an Org Admin or Platform Admin. An organization-wide Catalog Admin administers each catalog
of the organization (including its member grants) but does not grant organization-wide roles.

### Adding an organization

1. Have the export mounted at its root on every machine that runs the CLI.
2. Add the entry under `organizations` (the Helm value `config`, or `huron.yaml` in the kustomize
   base) and roll it out: `helm upgrade` (the chart restarts the API when the configuration
   changes), or `oc apply -k deploy/openshift`.
3. As the storage administrator, on a machine with the mount, signed in as a platform admin:

   ```bash
   huron adm provision-orgs --org geo --dry-run   # what it would do
   huron adm provision-orgs --org geo
   huron adm verify-mounts
   ```

`provision-orgs` requires the root to exist (it never creates one), creates `<root>/<org>` with
mode 2771 and the organization's ACL (the platform and Org Admin groups; modes only with
`acl_backend: none`) and writes the marker `<root>/<org>/.huron`, naming the service's
`HURON_INSTANCE_ID` and the organization. It is idempotent, and it refuses to overwrite a marker that
names another instance or organization. Without `--org` it provisions every declared organization.
When only `root` may write the root, `huron adm provision-orgs --emit-script > provision.sh` prints
the same `mkdir`, `chmod`, `chgrp`, `setfacl` and marker steps as a shell script to run as root.

The CLI refuses to touch an organization's directory unless its marker names the service's instance
id and the organization, so a CLI pointed at a test service, or an export mounted at another
organization's root, cannot be written into. `huron adm verify-mounts` shows each organization's
`PATH` and `STATE`: `ok`, `missing`, `no marker`, `wrong instance` or `wrong org`, and exits 1 when
any is not `ok`; an organization the configuration no longer declares shows `undeclared` and does
not fail it. Org Admins then create catalogs as before; Huron never removes an organization
directory that has a root, even on `huron delete org`.

### The mount prefix, for organizations without a root

Organizations that are neither declared nor rooted (every organization in unmanaged mode) live
under the mount prefix, marked once, as a user that owns the prefix (or root):

```bash
scripts/init-root.sh /projects/huron huron-platform-admins https://huron.apps.example.org <instance-uuid>
```

It sets mode 2771 and the platform admin ACL and writes `/projects/huron/.huron`; the CLI checks
that marker's `instance_id` the same way. A declared organization without a root is provisioned at
`<mount_prefix>/<org>` by `huron adm provision-orgs` and carries its own marker.

## Deploying

See [deploy/README.md](../deploy/README.md): a Helm chart (`deploy/helm/huron`, the YAML
configuration in the value `config`) and a Kustomize base (`deploy/openshift`, the configuration in
`huron.yaml`) are both supported. The API mounts no share in either. On first start the service
seeds the `huron-base` schema, a Platform Admin grant for `HURON_PLATFORM_ADMIN_GROUP` and a signing
key, and reconciles the declared organizations.

## Deploying the web

The web app (`web/`) is an optional, read-only view of the catalog in a browser. Build its image
from `web/Containerfile` (Node, a non-root user, port 3000) and run it beside the API; the Helm
chart can deploy it (off by default), the Kustomize base does not.
[web/README.md](../web/README.md) has the details.

- **An OIDC client for the web**: confidential, code flow only, PKCE S256, the redirect URI
  `<ORIGIN>/auth/callback` and the post-logout URI `<ORIGIN>/login?status=signed-out`. Its ID
  tokens must carry the API's `HURON_COMPANY_AUDIENCE` in `aud`; with Keycloak, add an audience
  mapper on the ID token.
- **Settings** are environment variables: `ORIGIN`, `HURON_API_URL`, `HURON_WEB_OIDC_ISSUER` (the
  API's `HURON_COMPANY_ISSUER`, byte for byte), `HURON_WEB_OIDC_CLIENT_ID` and
  `HURON_WEB_OIDC_CLIENT_SECRET`, and optionally `HURON_WEB_OIDC_SCOPES`, `HURON_WEB_OIDC_LOGOUT`,
  `HURON_WEB_MOUNT_PREFIX` and `HURON_WEB_API_TIMEOUT_MS`;
  [web/.env.example](../web/.env.example) explains each. The web shows a share path under the
  organization's root when the API reports one (`share_root`), and under
  `HURON_WEB_MOUNT_PREFIX` only for organizations without a root.
- **The client secret** is the web's only secret: keep it in a Secret, never in a ConfigMap or the
  image.
- **`ORIGIN`** is the exact public origin browsers use, such as
  `https://huron-web.apps.example.org`: the redirect URIs derive from it, and on https it makes
  every cookie `Secure` with the `__Host-` prefix. A proxy in front of the web must pass the
  `Origin` header through, or sign-out answers 403.
- **One replica, or sticky sessions.** Sessions live in the process's memory, and sign-ins in
  progress are sealed with a key the process makes for itself: another replica can use neither,
  and a restart or an out-of-memory kill signs everyone out.
- **Compression** of `text/html` and `application/json` belongs at the Route, ingress or reverse
  proxy: the server compresses only its static assets.
- `/healthz` answers without a session, for probes.

## First steps after deployment

```bash
huron config set api_url https://huron.apps.example.org
huron config set issuer https://login.example.org/realms/company
huron login
huron adm provision-orgs     # managed mode: every declared organization
huron adm verify-mounts
```

In unmanaged mode, create organizations and their Org Admins instead:

```bash
huron create org helio
huron adm grant org_admin huron-helio-admins --org helio
huron adm grant reader huron-helio-readers --org helio     # as an Org Admin: every helio catalog
huron adm verify-mounts
```

## Backups and recovery

Back up PostgreSQL; it is the catalog of record. File recovery is the storage team's snapshot
policy — Huron keeps no file versions. After restoring files from a snapshot, run `huron adm check` and
reconcile.

## Reading `huron adm check`

| Finding | What to do |
| --- | --- |
| `org_dir_missing`, `org_marker_missing` | The storage administrator runs `huron adm provision-orgs --org <org>` (for an organization that is neither declared nor rooted, `huron create org` and `scripts/init-root.sh`). Check that the export is mounted at its root. |
| `org_marker_mismatch` | The marker names another instance or organization: the wrong export is mounted at this root, or the CLI points at another service. Fix the mount or `api_url`; never edit the marker by hand. |
| `org_acl_drift` | The organization directory's owner re-runs `huron adm provision-orgs --org <org>`. |
| `org_undeclared` | A warning: the configuration no longer declares the organization, so its directory cannot be located and its catalogs are not checked. Declare it again with its root, or empty and delete it ([Configuration](#configuration)). |
| `namespace_dir_missing`, `collection_dir_missing` | Re-run `huron create namespace …` or `huron activate collection`; both repair directories. |
| `file_missing` | Restore the file, or commit its removal with `huron rm` and `huron push`. |
| `file_changed` | Someone wrote outside the CLI. Push the file again or restore it. |
| `file_unrecorded`, `dir_unrecorded` | Stage and push it, or remove it. |
| `sidecar_stale` | `huron publish meta` (or any metadata change) rewrites `metadata.json`. |
| `acl_drift` | The directory's owner runs `huron adm apply-acl <identifier>`; a storage admin can `chown` directories whose owners have left. |
| `stale_part` | An interrupted copy; the next push reuses or replaces it, or delete it. |
| `incomplete` | Metadata no longer satisfies the catalog schema; edit and publish it. |
| `stale_draft` | Activate or delete the draft. |

## Pre-release check

`scripts/e2e.sh` starts the backend of the Docker stack (`docker-compose.app.yml`) as its own compose
project with an empty database and an override configuration whose organization roots lie in a
temporary directory, so it does not need `/data1`. It logs in as the development users,
prepares the organization directories with `huron adm provision-orgs` and walks the user guide
there, then removes the project, its volume and its API image `huron-e2e-api:dev`. It needs the ports of `make app` and `make up`, so stop both first with `make down`.
