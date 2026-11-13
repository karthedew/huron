# Operator guide

## Prerequisites

- **LDAP groups.** One platform admin group (for example `huron-platform-admins`). For each
  organization, groups for org admins, catalog admins, contributors and readers. Catalogs that must
  stay restricted also need groups of their own. Huron grants roles to groups, and LDAP manages the
  membership. [LDAP groups and roles](#ldap-groups-and-roles) recommends a set.
- **The share.** One or more NFS exports. Mount each export at the same path on every machine where
  people run the CLI. The directory of each organization is `<root>/<org>` when the service
  configuration declares a root, for example `/data1/huron/helio` and `/data1/huron/geo`. Otherwise
  the directory is under the mount prefix of the CLI (default `/projects/huron/<org>`). The machines must resolve
  the LDAP groups of the users (sssd), so that the POSIX ACLs apply. Use `getfacl` to check that
  each export honors POSIX ACLs. If an export does not, set `acl_backend: none` in the CLI
  configuration of each user. Huron then applies modes only.
- **A group directory** that answers `GET /users/{username}/groups` with `{"groups": [...]}`.
- **An OIDC client** `huron-cli`: public, with the device grant and `http://127.0.0.1` loopback
  redirects enabled. The loopback flow sends PKCE (S256). With Keycloak 26, do not set PKCE as
  required on `huron-cli`. If you do, Keycloak requires PKCE at the device endpoint, and the device
  flow of the CLI does not send PKCE yet.
- **PostgreSQL 16.**

## Configuration

The service reads `HURON_*` environment variables (`src/huron/applications/api/settings.py`). When
`HURON_CONFIG_FILE` names a YAML file, the service also reads that file. Its top-level keys are the
same settings in lower case without the prefix, plus `organizations`. An environment variable wins
over the file, and the file wins over the defaults.

Keep `HURON_DATABASE_URL` in the environment (a Secret). The file accepts it, but the file is not a
secret store. Unknown top-level keys stop the service at startup, and so do two organizations with
the same name. Thus a typo such as `organisations:` cannot go unnoticed.

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

An `organizations` key, also an empty list, puts the service in managed mode. In managed mode, the
configuration decides which organizations exist and who administers them. Each entry has these
fields:

- `name`: required. The naming rules of every Huron name apply: lowercase letters, digits, `-` and
  `_`, at most 63 bytes.
- `display_name` and `description`: optional.
- `groups`: optional. The LDAP groups of each organization-wide role (see
  [LDAP groups and roles](#ldap-groups-and-roles)).
- `root`: optional. An absolute path. The directory of the organization is always `<root>/<name>`.
- `export`: optional. The NFS source, which the hints of the CLI show.

An organization without `root` is at `<mount_prefix>/<name>`, where the `mount_prefix` of the CLI
points. In an emergency, `HURON_ORGANIZATIONS`, a JSON list, replaces the list of the file.

At every start, the service makes the database agree with the configuration. It holds a lock, so
replicas that start together take turns. The service then does these steps, with the usual audit
entries:

1. It creates the organizations that are missing.
2. It updates the `display_name` and `description` values that changed.
3. It sets the groups of each organization for all four organization-wide roles to exactly its
   `groups`.

When nothing is different, the service writes nothing.

The service never deletes an organization. When you delete an organization from the configuration,
the service logs a warning at startup, with the catalog count of the organization. The organization
stays in the database. Its catalogs, grants and metadata stay usable through the API and the web.

But the CLI cannot find the directory any more. The root came from the configuration, so the CLI no
longer knows where the directory is. It looks for the directory under the mount prefix only. Thus,
after you delete a rooted organization from the configuration, the CLI cannot find its directory.
It finds the directory again when you declare the organization again with the same root. That declaration restores everything.

To retire an organization, do these steps:

1. Empty the organization while it is still declared: delete its collections, namespaces and
   catalogs.
2. Delete its entry from the configuration.
3. Run `huron delete org`. The old directory stays for the storage admin.

For an organization that the configuration no longer declares:

- `huron adm verify-mounts` shows it as `undeclared`, which is not a failure.
- `huron get orgs` marks its path `(undeclared)`.
- `huron adm check` reports `org_undeclared` (a warning), unless the mount prefix is a marked share
  that holds the organization.

In managed mode, the API refuses these requests:

- To create an organization (`ORGANIZATIONS_MANAGED`).
- To delete a declared organization (`ORGANIZATION_DECLARED`).
- To change one of the organization-wide role groups of a declared organization
  (`ORGANIZATION_DECLARED`). `huron adm grant … --org` then names the `groups.<role>` key to edit.

The CLI still grants roles on a single catalog. A rename is a deletion and an addition. The old
organization stays until you empty it and delete it.

Without an `organizations` key, the service is in unmanaged mode:

- Platform admins create organizations with `huron create org`.
- Platform admins grant Org Admins with `huron adm grant org_admin <group> --org <org>`.
- Org Admins grant the organization-wide catalog roles with
  `huron adm grant <role> <group> --org <org>`.
- Every organization is under the mount prefix.

### LDAP groups and roles

`groups` maps each organization-wide role to its LDAP groups. All four keys are optional. The
default of each key is no group. Any other key stops the service at startup, and so does the former
key `admin_groups`.

| Key | Holds | Where |
| --- | --- | --- |
| `org_admin` | Org Admin | the organization and every catalog in it |
| `catalog_admin` | Catalog Admin | every catalog of the organization |
| `contributor` | Contributor | every catalog of the organization |
| `reader` | Reader | every catalog of the organization |

Every catalog inherits these roles without a grant of its own. This applies to the catalogs that
exist and to the catalogs that people create later. A grant on one catalog
(`huron adm grant reader <group> --catalog <catalog>`) adds a group to that catalog. It cannot
exclude an inherited group. `huron get grants --catalog <catalog>` shows each group with its source:
`platform`, `organization <org>` or `catalog`.

The ACLs of the catalog directories name the inherited groups too. Thus, after you change `groups`
and roll out the change, the owners of the directories must run
`huron adm apply-acl <catalog> --recursive` for each catalog of the organization.

The recommended set is one group for each role and organization, plus the group of the platform:

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

- **POSIX groups.** Make each group a POSIX group with a `gidNumber`. Every machine that runs the
  CLI must resolve it through sssd. The ACL entries of the directories name these groups, and
  `setfacl` fails on a group that the machine cannot resolve. `getent group huron-helio-readers`
  must answer on these machines.
- **Nested groups.** Use them only if the group directory (`group_directory_url`) returns them
  flattened, as the effective groups of the user. Huron matches the group names that it gets
  literally. It does not expand a group in a group.
- **Membership changes** take effect at the next login of a user. Huron reads the groups
  from the group directory at sign-in (`huron login` in the CLI, the sign-in of the web). The groups
  then travel in the Huron token. Thus a user who is no longer in a group keeps the role of that
  group until their next sign-in.
- **Restricted catalogs.** An organization-wide reader sees, and can read, every catalog of the
  organization. When only some people may see a catalog, give that catalog groups of its own,
  granted on that catalog (`huron-<org>-<catalog>-readers` and so on). Then keep the
  `groups` of its organization to people who may see every catalog. Or put the restricted catalog
  in an organization of its own.

In unmanaged mode, `huron adm grant <role> <group> --org <org>` grants the same four roles on the
organization. A Platform Admin grants `org_admin`. An Org Admin or a Platform Admin grants the three
catalog roles. An organization-wide Catalog Admin administers each catalog of the organization,
together with its member grants. But that Catalog Admin does not grant organization-wide roles.

### Adding an organization

1. Make sure that the export is mounted at its root on every machine that runs the CLI.
2. Add the entry under `organizations` (the Helm value `config`, or `huron.yaml` in the kustomize
   base). Then roll out the change with `helm upgrade` or `oc apply -k deploy/openshift`. The chart
   restarts the API when the configuration changes.
3. As the storage admin, on a machine with the mount, logged in as a platform admin:

   ```bash
   huron adm provision-orgs --org geo --dry-run   # what it would do
   huron adm provision-orgs --org geo
   huron adm verify-mounts
   ```

`provision-orgs` requires that the lake path and each root exist. It never creates a root. For the
lake path (the `mount_prefix` of the CLI), it does these steps:

1. It gives the lake path the service user and group, and the mode `2751`.
2. It makes `<lake_path>/.tus-uploads` with mode `0700` for the service user and group.
3. It writes the marker `<lake_path>/.huron`, which names the `HURON_INSTANCE_ID` of the service.

For each declared organization, it does these steps:

1. It makes `<root>/<org>` when it does not exist. It gives the directory the service user and
   group, and the mode `2751`. No step is recursive.
2. It makes the object area `<root>/<org>/.huron-objects` with mode `0700` for the service user
   and group.
3. It writes the marker `<root>/<org>/.huron`, which names the `HURON_INSTANCE_ID` of the service
   and the organization.

`provision-orgs` is idempotent. It refuses to overwrite a marker that names another instance or
another organization. Without `--org`, it provisions every declared organization.

Without `--config`, the service user and group come from `GET /healthz`. `--uid` and `--gid`
replace them. The command refuses to start when it does not know both. Usually only `root` may change the owner.
Then `huron adm provision-orgs --emit-script > provision.sh` prints the same steps as a shell
script to run as root. The script refuses a symbolic link at each path that it changes.

`provision-orgs` also works while the API is stopped. With `--config <file>`, it reads the declared
organizations, `instance_id`, `service_uid` and `service_group` from the service configuration file
(`huron.yaml`). It then sends no request to the API. A `lake_path` in the file must be the
`mount_prefix` of the CLI.

The CLI refuses to touch the directory of an organization unless its marker names the instance id
of the service and the organization. Thus the CLI cannot write into an export in these cases:

- The CLI points at a test service.
- The export is mounted at the root of another organization.

`huron adm verify-mounts` shows the `PATH` and `STATE` of each organization. The state is `ok`,
`missing`, `no marker`, `wrong instance` or `wrong org`. The command exits 1 when a state is not
`ok`. An organization that the configuration no longer declares shows `undeclared`, and it does not
make the command fail.

Org Admins then create catalogs as before. Huron never deletes an organization directory that has a
root, also on `huron delete org`.

### The mount prefix, for organizations without a root

Organizations that are neither declared nor rooted are under the mount prefix. In unmanaged mode,
this applies to every organization. Mark the mount prefix one time, as a user that owns the prefix
(or as root):

```bash
huron adm provision-orgs
```

The command writes `/projects/huron/.huron`. The CLI checks the `instance_id` of that marker in
the same way. `huron adm provision-orgs` provisions a
declared organization without a root at `<mount_prefix>/<org>`. That organization has its own
marker.

### Logging

The service writes its log to standard output, one line for each event. Thus the container log
holds it. `log_level` (`HURON_LOG_LEVEL`) sets the lowest level that the service writes: `DEBUG`,
`INFO` (the default), `WARNING`, `ERROR` or `CRITICAL`, in upper or lower case. Any other value stops
the service at startup, as other bad settings do.

Every Huron line has the same shape: a UTC timestamp, the level, the event and the logger, then the
fields of the event:

```text
2026-11-01T09:00:00.123456Z [info     ] bootstrap.organization_created [huron.api.bootstrap] name=helio
2026-11-01T09:00:00.123789Z [info     ] bootstrap.organization_regranted [huron.api.bootstrap] name=helio
2026-11-01T09:00:00.124012Z [warning  ] bootstrap.organization_undeclared [huron.api.bootstrap] catalog_count=3 name=old
2026-11-01T09:05:12.000001Z [error    ] api.unexpected_error           [huron.applications.api.problems] error=... request_id=...
```

At `INFO`, each start reports the changes that the reconcile of
[declared organizations](#declared-organizations) made. It writes one line for each organization,
with its `name`:

- `bootstrap.organization_created`.
- `bootstrap.organization_updated`: the `display_name` or the `description` changed.
- `bootstrap.organization_regranted`: the service set the organization-wide role groups to the
  declared groups.

A start that changed nothing writes none of these lines. The service keeps each organization that
the configuration no longer declares. It reports that organization as
`bootstrap.organization_undeclared` at `WARNING`, with its `name` and `catalog_count`.

Each sign-in through the token exchange writes a `broker.exchange` line at `INFO`, with the subject
and its group count. Each request that failed unexpectedly writes an `api.unexpected_error` line at
`ERROR`. Its `request_id` matches the `request_id` in the 500 response. The startup and access lines
of Uvicorn keep the format and level of Uvicorn (its `--log-level` option). `log_level` does not
change them.

## Deploying

See [deploy/README.md](../deploy/README.md). Huron supports a Helm chart and a Kustomize base:

- The Helm chart is `deploy/helm/huron`. The YAML configuration is in the value `config`.
- The Kustomize base is `deploy/openshift`. The configuration is in `huron.yaml`.

With the Kustomize base, the API mounts the lake read-write and runs as one replica. The upload pod
runs nginx and tusd. The Helm chart does not have the lake and the upload pod yet, and its API
mounts no share. [deploy/README.md](../deploy/README.md) gives the rule of one writer, the probes
and the install order. It also describes the local cluster `deploy/local`.

On the first start, the service does these steps:

1. It seeds the `huron-base` schema.
2. It seeds a Platform Admin grant for `HURON_PLATFORM_ADMIN_GROUP`.
3. It seeds a signing key.
4. It reconciles the declared organizations.

## Deploying the web

The web app (`web/`) is an optional, read-only view of the catalog in a browser. Build its image
from `web/Containerfile` (Node, a non-root user, port 3000) and run it next to the API. The Helm
chart can deploy it (off by default). The Kustomize base does not deploy it.

The image also holds this documentation as a website at `<ORIGIN>/docs/`, without sign-in. The
image builds the website from `docs/`. Give that directory as the build context `docs`. For
example, from the repository root:
`docker build --build-context docs=docs -f web/Containerfile web`.
[web/README.md](../web/README.md) has the details.

- **An OIDC client for the web**: confidential, code flow only, PKCE S256, the redirect URI
  `<ORIGIN>/auth/callback` and the post-logout URI `<ORIGIN>/login?status=signed-out`. Its ID
  tokens must carry the `HURON_COMPANY_AUDIENCE` of the API in `aud`. With Keycloak, add an
  audience mapper on the ID token.
- **Settings** are environment variables: `ORIGIN`, `HURON_API_URL`, `HURON_WEB_OIDC_ISSUER`,
  `HURON_WEB_OIDC_CLIENT_ID` and `HURON_WEB_OIDC_CLIENT_SECRET`. `HURON_WEB_OIDC_ISSUER` must be
  the `HURON_COMPANY_ISSUER` of the API, byte for byte. The optional settings are
  `HURON_WEB_OIDC_SCOPES`, `HURON_WEB_OIDC_LOGOUT`, `HURON_WEB_MOUNT_PREFIX` and
  `HURON_WEB_API_TIMEOUT_MS`. [web/.env.example](../web/.env.example) explains each setting.
- **Share paths.** When the API reports a root for an organization (`share_root`), the web shows a
  share path under that root. The web uses `HURON_WEB_MOUNT_PREFIX` only for organizations without
  a root.
- **The client secret** is the only secret of the web. Keep it in a Secret, never in a ConfigMap
  or in the image.
- **`ORIGIN`** is the exact public origin that browsers use, such as
  `https://huron-web.apps.example.org`. The redirect URIs come from it. On https, it also makes
  every cookie `Secure`, with the `__Host-` prefix. A proxy in front of the web must pass the
  `Origin` header through. If it does not, sign-out answers 403.
- **One replica, or sticky sessions.** Sessions are in the memory of the process. The process seals
  the sign-ins in progress with a key that it makes for itself. Another replica can use neither.
  A restart or an out-of-memory kill signs out every user.
- **Compression** of `text/html` and `application/json` belongs at the Route, the ingress or the
  reverse proxy. The server compresses only its static assets.
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

Back up PostgreSQL. It is the catalog of record. The snapshot policy of the storage team recovers
files. Huron keeps no file versions. After you restore files from a snapshot, run `huron adm check`
and reconcile.

## Reading `huron adm check`

| Finding | What to do |
| --- | --- |
| `org_dir_missing`, `org_marker_missing` | The storage admin runs `huron adm provision-orgs --org <org>`. For an organization that is neither declared nor rooted, use `huron create org` and `huron adm provision-orgs`. Check that the export is mounted at its root. |
| `org_marker_mismatch` | The marker names another instance or organization. The wrong export is mounted at this root, or the CLI points at another service. Fix the mount or `api_url`. Never edit the marker by hand. |
| `stale_link_probe` | Information: a readiness probe stopped and left a `.huron-link-probe-*` file in the organization directory or its object area. Only the service user sees a probe file in the object area. The check keeps it. The storage admin can delete it. |
| `org_undeclared` | A warning. The configuration no longer declares the organization. Thus the CLI cannot find its directory and does not check its catalogs. Declare it again with its root, or empty it and delete it ([Configuration](#configuration)). |
| `namespace_dir_missing`, `collection_dir_missing` | Run `huron create namespace …` or `huron activate collection` again. Both commands fix the directories. |
| `file_missing` | The service records a file that is not on the share. Restore the file. Or commit its removal with `huron rm` and `huron push`. The check does not report a recorded file below a directory that it cannot read. |
| `file_changed` | Someone wrote outside the CLI. Push the file again or restore it. |
| `file_unrecorded`, `dir_unrecorded` | An entry that no row names. In a collection, stage the file and push it, or delete it. Directly in a catalog or namespace directory, delete the entry. |
| `sidecar_stale` | `huron publish meta` (or any metadata change) writes `metadata.json` again. |
| `stale_part` | Information: a `.huron-part` file in a collection, older than one hour. It is the temporary name of a stopped publication, or the part file of a stopped write of `metadata.json`. The check keeps it. Delete the file when no commit request holds the collection. |
| `pending_commit` | Information: a commit request holds the collection. Its directory can hold old and new files until the request ends. A blocked request needs a platform admin. |
| `nfs_file` | Information: an NFS client keeps a deleted file while a process holds it open. The client deletes the file when the process closes it. The check reports these files in an organization directory and below a catalog. A collection cannot record a name that starts with `.nfs`, so the check does not compare the file with a record. |
| `snapshot_dir` | Information: the storage shows its snapshots in a `.snapshot` directory, in an organization directory or below a catalog. A collection cannot record a path with a `.snapshot` segment, so the check does not read that directory. |
| `mode_drift` | A directory or file has the wrong mode or the wrong owner. Or an organization directory does not have the service group. Or a directory below a catalog does not have the setgid bit or the group of the catalog directory. For an organization directory, the storage admin runs `huron adm provision-orgs --org <org>`. For the directory of a catalog, a namespace or a collection, `huron adm repair <identifier> --recursive` fixes the permission bits. For the setgid bit or the group, the storage admin runs `huron adm provision-catalogs`. The storage admin changes the mode of a file and the owner of an entry below an organization directory. |
| `share_group_mismatch` | The storage admin runs `huron adm provision-catalogs`. When this machine does not know the share group, check the group database of the machine. |
| `unreadable` | The account that runs the check cannot read the entry. Run the check as the service user, or as an account in the service group and in every share group. |
| `symbolic_link` | The lake must not contain symbolic links. The storage admin deletes the link. Huron never follows it or deletes it. |
| `incomplete` | The metadata no longer satisfies the catalog schema. Edit the metadata and publish it. |
| `stale_draft` | Activate the draft or delete it. |

## Pre-release check

`scripts/e2e.sh` starts the backend of the Docker stack (`docker-compose.app.yml`) as its own
compose project. The backend includes the lake preparation, tusd and the upload proxy. The project
has an empty database and an override configuration. That configuration puts the lake path and the
organization roots in a temporary directory, so the script does not need `/data1`. The lake has
the same path on the host and in the containers, and the containers run as you. The script then
does these steps:

1. It logs in as the development users.
2. It runs `huron adm provision-orgs`, which finds the lake prepared and changes nothing.
3. It follows the user guide in the stack.
4. It pushes new files, an overwrite, an empty file and a removal through the upload proxy and tusd.
5. It deletes the project, its volume and its API image `huron-e2e-api:dev`.

The script needs the ports of `make app` and `make up`, and port 1080. Stop the stacks first with
`make down`.
