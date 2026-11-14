# Operator guide

## Prerequisites

- **LDAP groups.** One platform admin group (for example `huron-platform-admins`). For each
  organization, groups for org admins, catalog admins, contributors and readers. Catalogs that must
  stay restricted also need groups of their own. Huron grants roles to groups, and LDAP manages the
  membership. [LDAP groups and roles](#ldap-groups-and-roles) recommends a set.
- **The share.** One or more NFS exports, the lake. The API pod and the upload pod mount the lake
  read-write at `lake_path`. Every other client mounts it read-only
  ([The lake and its users](#the-lake-and-its-users)). The storage admin runs the provision steps
  as root on a machine with a writable mount ([Install order](#install-order)). The directory of each organization is
  `<root>/<org>` when the service configuration declares a root, for example `/data1/huron/helio`
  and `/data1/huron/geo`. Otherwise the directory is `<lake_path>/<org>`. Huron uses no POSIX ACLs.
  Directory modes and the share group of a catalog control who reads the files on the share. A
  catalog without a share group is readable only by `U` and the members of `G`.
- **Workstations that read the share.** A push does not need the mount. `huron status` and
  `huron adm check` read the share. On these machines, mount the lake read-only at the same path
  everywhere, and set the CLI's `mount_prefix` to that path. The machines must give each user the
  LDAP groups of that user (sssd), because the export checks the groups that the client sends.
- **An OpenShift namespace** with a pinned UID range, for the service user `U`
  ([The lake and its users](#the-lake-and-its-users)).
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

An organization without `root` is at `<lake_path>/<name>`. On a workstation, the CLI finds it
below its `mount_prefix`, where the workstation mounts the lake path. In an emergency,
`HURON_ORGANIZATIONS`, a JSON list, replaces the list of the file.

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
- Every organization is directly below the lake path. On a workstation, it is below the mount
  prefix.

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

These groups control the API only. A change of `groups` changes no directory on the share. Read
access on the share comes from the share group that a catalog can have
([Share groups](#share-groups)).

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

- **POSIX groups.** A role group needs no `gidNumber`, because Huron compares its name only. A
  share group must be a POSIX group with a `gidNumber`. Each workstation that reads the share must
  resolve it through sssd. For example, `getent group huron-helio-readers` must answer there.
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

While a declared organization has no directory or no marker, the readiness probe of the API
fails ([The hard mount and readiness](#the-hard-mount-and-readiness)). The one API pod is then not
ready, for every organization, and the CLI cannot log in. So prepare the new organization before
the API reads its declaration:

1. Make sure that the export holds the root of the organization. The API pod and the upload pod
   must mount it, and each workstation that reads the share mounts it at the same path.
2. Add the entry under `organizations` in your copy of `huron.yaml` (or the Helm value `config`).
   Do not apply it yet.
3. As the storage admin, as root on a machine with a writable mount
   ([Where the storage admin works](#where-the-storage-admin-works)), prepare the organization
   from that file. With `--config`, the command sends no request to the API:

   ```bash
   huron adm provision-orgs --config huron.yaml --org geo --dry-run   # what it would do
   huron adm provision-orgs --config huron.yaml --org geo
   ```

4. Apply the configuration with `oc apply -k deploy/openshift` or `helm upgrade`. The changed
   configuration starts the API pod again.
5. Log in as a platform admin, and run `huron adm verify-mounts`. Each row must say `ok`.

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

Without `--config`, the service user and group come from `GET /healthz`. With `--config`, the
user is `service_uid` of the file, and the group is the gid of `service_group` in the group
database of this machine. When the file has no `service_uid`, give `--uid`. When it has no
`service_group`, or this machine cannot resolve the name, give `--gid`. `--uid` and `--gid` also
replace the values of the source. The command refuses to start when it does not know both. Usually
only `root` may change the owner. In that case, `huron adm provision-orgs --emit-script >
provision.sh` prints the same steps as a shell script to run as root. The script refuses a symbolic link at each path that it changes.

`provision-orgs` also works while the API is stopped or not ready. With `--config <file>`, it
reads the declared organizations (each `name` and `root`), `instance_id`, `service_uid` and
`service_group` from the service configuration file (`huron.yaml`). It then sends no request to
the API. A `lake_path` in the file must be the `mount_prefix` of the CLI. `--org` accepts each
organization that the file declares. The markers name the `api_url` of the CLI configuration.

The API and the CLI use the directory of an organization only when its marker names the instance
id of the service and the organization. Thus Huron writes nothing into an export in these
cases:

- The CLI or the API points at a test service.
- The export is mounted at the root of another organization.

`huron adm verify-mounts` shows the `PATH` and `STATE` of each organization. The state is `ok`,
`missing`, `no marker`, `wrong instance` or `wrong org`. The command exits 1 when a state is not
`ok`. An organization that the configuration no longer declares shows `undeclared`, and it does not
make the command fail.

Org Admins then create catalogs. The API makes the directory of each catalog, namespace and
collection. `huron delete org` removes the directory of the organization only when it is empty. A
provisioned organization directory holds its marker and its object area, so it stays for the
storage admin.

### The mount prefix, for organizations without a root

Organizations that are neither declared nor rooted are directly below the lake path. In unmanaged
mode, this applies to every organization. They share the marker at the lake path, which names only
the instance. `huron adm provision-orgs` writes it as root:

```bash
huron adm provision-orgs
```

On a workstation, this marker is at `<mount_prefix>/.huron`, for example
`/projects/huron/.huron`. The CLI checks its `instance_id` in the same way. A declared organization
without a root is at `<lake_path>/<org>` too, but it has its own marker.

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

A service with a lake also writes these events:

| Event | Level | When |
| --- | --- | --- |
| `ownership.reader` | WARNING | At startup, another session holds the writer lock. This process serves reads only ([One writer](#one-writer)). |
| `ownership.lost` | ERROR | The writer lost its lock. The process starts no new step on the lake and stops. |
| `task.failed` | ERROR | A seal, a publication or a run of the periodic loop failed. `work` names the kind of work. A later run tries the work again. |
| `seal.skipped` | INFO | The check of a complete upload did not start a seal. `reason` tells why, for example a lock file of tusd. |
| `cleanup.failed` | WARNING | The cleanup could not remove a file. The next run tries it again. |
| `disk.directory_kept` | WARNING | A delete kept a directory that is not empty. |
| `disk.link_found` | WARNING | A delete of a collection found a symbolic link and kept it. |
| `disk.cancelled_action_failed` | ERROR | A disk action failed after its request ended. |

## Deploying

See [deploy/README.md](../deploy/README.md). Huron has a Kustomize base and a Helm chart:

- The Kustomize base is `deploy/openshift`. The configuration is in `huron.yaml`. It deploys the
  API with the lake, and the upload pod.
- The Helm chart is `deploy/helm/huron`. The YAML configuration is in the value `config`. The
  chart does not have the lake and the upload pod yet, and its API mounts no share
  ([Helm: not yet delivered](#helm-not-yet-delivered)).

With the Kustomize base, the API mounts the lake read-write and runs as one replica. The upload pod
runs nginx and tusd. [deploy/README.md](../deploy/README.md) gives the manifests, the probes and
the install order in detail. It also describes the local cluster `deploy/local`
([Local cluster](#local-cluster)).

On the first start, the service does these steps:

1. It seeds the `huron-base` schema.
2. It seeds a Platform Admin grant for `HURON_PLATFORM_ADMIN_GROUP`.
3. It seeds a signing key.
4. It reconciles the declared organizations.

## The lake and its users

The API is the only process that writes the lake, apart from tusd, which writes only
`.tus-uploads`. The API makes the directories, writes each `metadata.json` and publishes each
committed file. The CLI writes nothing to the lake, apart from the provision commands of the
storage admin.

### The service user and the service group

The API pod and the upload pod run as one user `U` with the primary group `G`. `U` owns every
directory and every file of the lake.

- **Choose `U`** as the first UID of the namespace's pinned range. The restricted SCC
  (`restricted-v2`) accepts `runAsUser: U` only inside the range of the annotation
  `openshift.io/sa.scc.uid-range`. The cluster administrator pins this annotation when they make
  the namespace. Thus `U` stays the same, and the export can trust it.
- **Choose `G`** as the `gidNumber` of the service group, an LDAP POSIX group with no human
  members.
- Set `runAsUser: U`, `runAsGroup: G` and `supplementalGroups: [G]` in both pods. Set
  `service_uid: U` and `service_group: <name of G>` in `huron.yaml`. The API takes the number of
  `G` from its own process. `service_group` is only the name that `/healthz` reports.

The pods never run as root. Each container drops all capabilities and has a read-only root
filesystem.

### The API's mount

The API pod and the upload pod mount the claim `huron-lake` at `lake_path`, for example
`/data1/huron`. The PersistentVolume of the export holds the mount options, for example `vers=3`,
`hard` and `sec=sys`. `lake_path` is a fixed mount point. Every organization root is `lake_path`
or a directory below it. The API refuses to start with a root outside it.

The lake holds these entries of Huron:

| Entry | Mode | Content |
| --- | --- | --- |
| `<lake_path>/.huron` | `0644` | The marker of the lake path. It names the instance. |
| `<lake_path>/.tus-uploads` | `0700` | The files of tusd. It can be on another filesystem. |
| `<root>/<org>` | `2751` | The organization directory, with the service group. |
| `<root>/<org>/.huron` | `0644` | The marker of the organization. |
| `<root>/<org>/.huron-objects` | `0700` | The object area: one sealed copy of each upload. |

The API publishes a file with a hard link from the object area, and a hard link cannot cross two
mounts. Thus the object area must be in the organization directory, on its filesystem and its
mount. The walks of Huron do not enter `.huron-objects`. `huron adm check` lists each object
area, but only as `U`. There it reports probe files, links and entries that it cannot stat.

### The export rules

- Make the export read-write only for the clients that run the API pod and the upload pod. Put
  the upload pod on those nodes with `nodeSelector`, `tolerations` and `affinity` in
  `uploads.yaml`.
- Every other client mounts the export read-only (`ro`).
- The export does not need POSIX ACLs. Huron sets none.

### Where the storage admin works

The provision commands and their scripts change owners, groups and modes as root. So the storage
admin runs them as root, or runs the scripts that `--emit-script` prints. The machine needs a
writable mount: the storage system's own shell, or a client that the export does not squash. The
install order does this before the export becomes read-only for every client except those of the
API pod and the upload pod ([Install order](#install-order)).

The design gives no route for such work after that restriction. This work includes these steps:

- `huron adm provision-orgs` for a new organization.
- `huron adm provision-catalogs` for a new catalog with a share group.
- A `chmod` as root for `mode_drift`.
- The deletion of a file in [Missing or changed files](#missing-or-changed-files).

This guide does not give a route either. Agree on the route with the storage team.

### The limit of AUTH_SYS

The export uses AUTH_SYS (`sec=sys`). It trusts the UID and the groups that a client sends. Thus
the read and write rules of Huron hold only against users who are not root on a client. Root on
any client can read every file. A process on a read-write client that claims `U` can write the
lake. `huron adm check` reports such a change as drift.

### The hard mount and readiness

The lake is a `hard` NFS mount. During an NFS outage, a disk call waits without end. The API runs
each disk call in its own pool of threads, never in the request loop. The readiness probe
(`/readyz`) waits at most 2 seconds for its probe of the lake, and keeps the answer for 10 seconds.
The probe has these parts:

- The writer writes and removes a file in `.tus-uploads`.
- The writer makes a hard link from the object area into each declared organization directory,
  and removes the link.

The probe of the pod has a timeout of 3 s, a period of 5 s and a failure threshold of 3. The
liveness probe (`/healthz`) makes no call to the lake. Thus an NFS outage makes the API pod not
ready, and Kubernetes does not restart it. Browsing through the API also stops while the pod is
not ready.

A readiness probe that stops can leave a `.huron-link-probe-*` file. `huron adm check` reports it as
`stale_link_probe` when it is older than one hour.

## The upload pod

The Deployment `huron-uploads` runs nginx and tusd in one pod with one replica and the strategy
`Recreate`. nginx is the only container that the Service reaches. tusd listens on 127.0.0.1.

- nginx asks the API (`GET /api/v1/uploads/auth`) to authorize each request except `OPTIONS`,
  before a byte reaches tusd. Each tus request must carry the Huron token of the user. A request
  on an upload needs the token of the user that started the upload. nginx keeps an allow for
  30 seconds.
- tusd calls the API for the hooks `pre-create` and `pre-finish`, with the `Authorization` header
  of the client. tusd refuses download, termination and concatenation.
- A chunk is at most 64 MiB. The Route of `/files` has a timeout of 3600 s.

tusd locks an upload with a hard link: a lock file `<id>.lock` in `.tus-uploads` that holds the
process ID of tusd. The test that this process is alive works only inside one PID namespace. After
an unclean stop, a new tusd can find its own process ID in an old lock file, and it then refuses
the upload. So the init container `clean-locks` removes `*.lock`, `*.lock.*` and `*.stop` in
`.tus-uploads` before tusd starts. This is safe only because one upload pod runs and the old pod
is gone. Never run two upload pods.

`terminationGracePeriodSeconds` of both pods is 90 s. It must stay longer than
`upload_hook_timeout` (60 s in `huron.yaml`), the longest time that the CLI waits for a seal.

To change `upload_hook_timeout`, change these values together. Its maximum is 55 minutes.

1. `upload_hook_timeout` in `huron.yaml`.
2. tusd's `-hooks-http-timeout` in `uploads.yaml`: the same value as `upload_hook_timeout`.
3. tusd's `-request-completion-timeout`: the same value as `-hooks-http-timeout`.
4. tusd's `-network-timeout`: longer than `-hooks-http-timeout`, for example by 60 seconds.
5. `terminationGracePeriodSeconds` of the API pod and of the upload pod: longer than
   `upload_hook_timeout`.

For example, for 15 minutes: `upload_hook_timeout: 900`, `-hooks-http-timeout=15m`,
`-request-completion-timeout=15m`, `-network-timeout=16m` and a grace period of 960 s. The base
has 60 s, 60 s and 2 minutes, which fit only a hook timeout of 60 s. `docker-compose.uploads.yml`
has the same tusd flags for development.

nginx waits at most 120 s for an answer of tusd (`proxy_read_timeout` in
`nginx-uploads.conf.template`), and the Route of `/files` waits 3600 s. Neither value changes with
the hook timeout. The pre-finish hook of the API answers within about 20 seconds. Then the CLI
reads the state of the upload for at most `upload_hook_timeout`. When nginx stops a request after
120 s, the client gets 504, and the CLI reads the state of the upload in the same way.

## Share groups

The share group of a catalog is an LDAP POSIX group. Its members read the catalog directory over
the read-only mount. Set it with `huron create catalog --share-group <group>` or
`huron set catalog <catalog> --share-group <group>`. `--no-share-group` clears it.

| Directory | Mode | Group |
| --- | --- | --- |
| organization | `2751` | the service group |
| catalog | `2750` | the share group, or the service group without one |
| namespace, collection and the directories in a collection | `2750` | inherited from the parent through setgid |

A file has the mode `0644` and keeps the service group. The directories above it decide who reads
it. A catalog without a share group is readable by nobody but `U` and the members of `G`.

`U` cannot give a directory a group of which `U` is not a member. Thus the API tries to give the
catalog directory its share group, and usually it cannot. It then answers with the warning
`SHARE_GROUP_PENDING`. The storage admin then runs this as root, on a machine with a writable
mount ([Where the storage admin works](#where-the-storage-admin-works)):

```bash
huron adm provision-catalogs --dry-run   # the catalogs that need the group
huron adm provision-catalogs             # or --emit-script, for a script that root runs
```

The command gives each selected catalog directory, and each directory in it, the group of the
catalog and the mode `2750`. Files keep their group and mode. A directory below the catalog then
inherits the group from its parent. This inheritance on the export is not measured yet
([Setgid measurement (pending)](#setgid-measurement-pending)).

**The `supplementalGroups` option, for a small site.** List the `gidNumber` of each share group
in `supplementalGroups` of the API pod, beside `G`. The API is then a member of each share group,
and it can set the group itself. AUTH_SYS sends at most 16 groups, so about 14 share groups fit.
The API resolves the name of a share group with the group database of its pod. The API image has
no LDAP group in that database. Without a way to resolve the names in the pod, the API still
answers with `SHARE_GROUP_PENDING`.

## Install order

[deploy/README.md](../deploy/README.md#install-order) gives each command. The order follows the
install order of `IMPLEMENTATION_PLAN.md` section 3, with one change. The lake path and the
organizations are prepared before the first deploy, from the configuration file. The reason is
that the API does not start on a lake path that it cannot write.

1. Build the API image from `Containerfile`, and push it to the registry of the cluster.
2. The cluster administrator makes the namespace with its pinned UID range, and the
   PersistentVolume of the export for the claim `huron-lake`.
3. Create the Secret with `HURON_DATABASE_URL`.
4. Edit `huron.yaml`: a new `instance_id`, the URLs, `uploads_url`, `service_uid`,
   `service_group`, the capacity settings and the organizations. Set `U` and `G` in both pods.
5. The storage admin makes each root. Huron never makes a root. Then the storage admin prepares
   the lake path and each organization. This runs as root, on a machine with a writable mount that
   the export does not squash. On a client with the `huron` CLI and that mount, first set
   `mount_prefix` to the lake path on that machine. Then run
   `huron adm provision-orgs --config deploy/openshift/huron.yaml`, which sends no request to the
   API. A `lake_path` in the file that is not the `mount_prefix` stops the command with a usage
   error before any change. In the storage system's own shell, where the CLI may not run, run the
   script that `huron adm provision-orgs --config … --emit-script` prints on a machine with the
   CLI. The script uses the absolute paths of that `mount_prefix`, so the lake path must have the
   same path in the shell.
6. Apply the base with `oc apply -k deploy/openshift`. Wait for the Job `huron-migrate`, then for
   the two rollouts. Check `/readyz` through the Route.
7. On a client with the CLI and a lake mount, set `api_url` and `issuer`, log in and run
   `huron adm verify-mounts`, as [First steps after deployment](#first-steps-after-deployment) shows. Its
   `huron adm provision-orgs` is not needed: step 5 did it. Then create the catalogs with their
   share groups.
8. For each `SHARE_GROUP_PENDING` warning, the storage admin runs
   `huron adm provision-catalogs --emit-script > catalogs.sh` on a client with the CLI and a lake
   mount. That command reads the API and the share to select the catalogs. The storage admin runs
   the script as root on a machine as in step 5, with the lake path at the same path. The script
   gives each group by its name, so that machine must resolve the share groups
   ([Share groups](#share-groups)).
9. Make the export read-only for every client except those of the API pod and the upload pod.
10. Mount the share read-only (`ro`) on the workstations.
11. Run `huron adm check` ([Reading `huron adm check`](#reading-huron-adm-check)). It must report
    no `mode_drift`, no `share_group_mismatch`, no `symbolic_link` and no `unreadable`.

After step 9, the design gives no route for a later provision step
([Where the storage admin works](#where-the-storage-admin-works)).

Production starts from an empty lake and an empty database. No data of an earlier design moves
into the lake.

## Symbolic links in the lake

The lake must not contain symbolic links. Huron makes none, follows none and removes none. The API
opens each name of a path with no follow. A link stops the disk work through it:

- A directory verb answers 409 `SYMLINK_IN_LAKE` and keeps its rows. `context.path` names the link.
- A step of a commit request blocks the request with the reason `symbolic_link`.
- A repair reports the link as a failure with the reason `symbolic_link`, and the other steps run.
- `huron adm check` reports the link as `symbolic_link`.

The storage admin removes the link. Then run the work again: `huron adm repair` for a directory
verb, or a retry for a blocked request ([Blocked commit requests](#blocked-commit-requests)).

## One writer

The API is the one writer of the lake. Never run two writable API pods. `deployment.yaml` sets one
replica and the strategy `Recreate`, so a rollout stops the old pod before the new pod starts.

At startup the API takes a PostgreSQL session advisory lock on a connection of its own. That
connection has the `application_name` `huron-writer` and TCP keepalives. Every 10 seconds the API
checks that the connection still answers.

- **A second process** that finds the lock held serves reads only and logs `ownership.reader`. It
  does not try to take the lock again. Its commit route and the resolve route answer 503
  `LAKE_UNAVAILABLE` with the reason `writer_lock`. A directory verb keeps its rows, then answers
  the same error, as for any disk failure after a commit.
- **When the writer loses its lock**, it logs `ownership.lost`, it is no longer ready, and it
  starts no new filesystem step. It then stops itself, and the platform starts it again. The new
  process takes the lock again.
- **When the database still holds the old session**, the new process finds the lock held. It then
  serves reads only. The keepalives let the server end the old session within about a minute.
  Look for `ownership.reader` in the log. When it is there, start the API pod again.

The lock is not a fence against a late NFS call of a process that died. So the rule of one pod
stays necessary. Plan the API as a single point of failure: while it is down, no upload and no
commit can complete.

## Publication of a commit

A push uploads each file through tusd. The API seals each upload: it copies the bytes into the
object area of the organization, syncs the copy and measures its size and SHA-256. A commit then
names each sealed upload by its ID. The API publishes a commit request in these steps:

1. **Acceptance.** One transaction checks the base version, the paths, the privilege and each
   upload. It saves the request with its entries, and marks the collection as held by the request.
   The request is `accepted`. A second commit for the collection gets 409 `COLLECTION_BUSY`.
2. **The steps.** For each entry in a fixed order, the API does one filesystem step. It links the
   object to a temporary name and renames it over the target, removes a file, or makes or removes
   a directory. It syncs the directory, then marks the entry done in its own short transaction.
3. **The final transaction.** It writes the file rows, the new version, the file count and the
   audit record. It frees the collection and marks the uploads consumed. The request is
   `succeeded`.

The commit route waits 5 seconds. A request that does not end in that time gets 202, and the
client reads its state at `GET /api/v1/commit-requests/{request_id}`. The states are `rejected`,
`accepted`, `blocked`, `succeeded` and `abandoned`. `accepted` and `blocked` are pending.

**Mixed visibility.** While a request is pending, the API and the web show the files and the
version of the last commit that succeeded. On the share, the directory of the collection can hold
a mix. The entries that are done show the new state, and the others show the old state. Each
single file changes in one rename, so a reader never sees half of a file. `huron adm check`
reports `pending_commit` for the collection and does not compare its files. A blocked request
keeps this mix until a platform admin resolves it.

At startup, the API continues each `accepted` and `blocked` request. Its periodic loop continues
each `accepted` request that has no task, every `sweep_interval`. A storage error leaves the
request pending, and a later run does the entries that are not done.

**A reader on another client.** The API replaces a file with a rename. The old file keeps a name
in the object area until the cleanup removes its object, after the commit. A process on another
NFS client that still has the old file open can then get the error `Stale file handle` (`ESTALE`).
Open the file again to read the new bytes. The behaviour of the export for this case is not
measured yet ([Setgid measurement (pending)](#setgid-measurement-pending)).

## Blocked commit requests

A step blocks a request when it finds an entry that the request does not expect. The API changes
nothing at that entry. The request stays `blocked`, and it holds the collection, until a platform
admin resolves it.

### How to read a blocked request

- The push of the contributor waits up to 10 minutes for the request, then stops with exit code 6
  and `PUBLICATION_BLOCKED`.
- `huron -o json describe collection <identifier>` shows `pending_request` with the state `blocked`
  and the time `since`. It also shows the `id` of the collection.
- `huron adm check` reports `pending_commit` for the collection.
- The refusal of the request tells what the step found. `GET /api/v1/commit-requests/{request_id}`
  gives it only to the user that sent the request. `huron status` of that user shows the request
  ID. With access to the database, read every blocked request:

```sql
select id, request_id, subject, collection_id, refusal, updated_at
from huron.commit_requests where state = 'blocked';
```

The column `id` identifies the request. A request ID is unique only for one user, so the queries
below use `id`.

The refusal has the code `PUBLICATION_BLOCKED`, a `detail` and a `context`. `context.ordinal`
names the entry, `context.path` names the place on the lake and `context.reason` tells what the
step found:

| Reason | What the step found |
| --- | --- |
| `foreign_entry` | An entry that is not the file or the directory that the request expects. |
| `directory_missing` | No directory where the request expects one. |
| `directory_not_empty` | A file that Huron did not record, in a directory that the request removes to free a path. |
| `object_missing` | The sealed object of an add does not exist, or it is another file. |
| `symbolic_link` | A symbolic link. |
| `inode_unknown` | A file to remove whose inode Huron does not know. |

The entries of a request and their state are in the table `huron.commit_entries`:

```sql
select ordinal, action, rel_path, upload_id, done_at
from huron.commit_entries where commit_request_id = '<id>'
order by ordinal;
```

### Retry and abandon

A platform admin resolves a blocked request through the API. No `huron` command does this yet.
Send `POST /api/v1/admin/collections/{collection_id}/pending-request` with one of these bodies:

- `{"resolution": "retry"}`: the request becomes `accepted`, and the API runs the entries that are
  not done again. Correct the cause first. For example, the storage admin moves a foreign file
  away or removes a symbolic link. A step that is still blocked blocks the request again.
- `{"resolution": "abandon"}`: possible only when no entry is done. The request becomes
  `abandoned`, the collection is free and the uploads are `ready` again. The push of the
  contributor then stops with exit code 6 and keeps the stage. A request with a done entry gets
  409 `STATE_CONFLICT`. `context.done` lists the done entries, at most 20.

For example, with the token of the CLI (`huron whoami` renews it first):

```bash
huron whoami
token="$(jq -r .huron_token "${XDG_STATE_HOME:-$HOME/.local/state}/huron/tokens.json")"
curl -sS -X POST -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
  -d '{"resolution": "retry"}' \
  https://huron.apps.example.org/api/v1/admin/collections/<collection id>/pending-request
```

The answer is the request after the change. Only the writer resolves a request. Another process
answers 503 `LAKE_UNAVAILABLE`.

After an abandon for the reason `object_missing`, the uploads are `ready`, but the object is still
missing. A new push would use the same upload and block again. So the contributor stages each file
of the request again with `huron add`, which starts a new upload at the next push.

### A request with done entries and a lost object

The reason `object_missing` with a done entry has no automatic exit. A retry blocks again, and an
abandon is refused. The API identifies a sealed object by its inode, so a copy of the bytes is a
different file. Do these steps:

1. Read the request and its entries, as above. For the entry of `context.ordinal`, read the
   object of its upload:

   ```sql
   select id, path, size, sha256, inode, state from huron.objects
   where upload_id = '<upload ID>';
   ```

   Continue only when `state` is `sealed`. For any other state, stop and report the case to the
   developers of Huron. The cleanup does not handle a published file whose object is `removed`.
2. Find a copy of the bytes whose SHA-256 is the `sha256` of the object. The source file of the
   contributor is a copy: `huron status` of the contributor shows it in the column `FROM`. A
   snapshot of the lake can hold one too.
3. Put the copy into the object area as `U`. Only `U` can write the object area, and the API pod
   runs as `U` with the lake mounted read-write. So copy the file into the API pod, then
   install it at the path of the object. The column `path` gives
   `<org>/.huron-objects/<upload ID>`, and the file is `<root>/<org>/.huron-objects/<upload ID>`
   on the lake. For an organization without a root, `<root>` is `lake_path`.

   ```bash
   pod="$(oc get pods -l app.kubernetes.io/component=api -o jsonpath='{.items[0].metadata.name}')"
   oc cp <copy> "$pod:/tmp/object"
   oc exec "$pod" -- install -m 0644 /tmp/object <root>/<org>/.huron-objects/<upload ID>
   oc exec "$pod" -- sync <root>/<org>/.huron-objects/<upload ID> <root>/<org>/.huron-objects
   oc exec "$pod" -- rm /tmp/object
   ```

   `sync` with the file and the object area writes both to the disk, as the seal does for its
   own copy.

   `oc exec` runs as the user of the pod, which is `U`. `/tmp` of the API pod is an `emptyDir` on
   the disk of the node, so a large copy uses that disk until you remove it.
4. Check the copy. `oc exec "$pod" -- sha256sum <object file>` must print the `sha256` of the
   object.
5. Read the inode of the copy with `oc exec "$pod" -- stat -c %i <object file>`. Write it into
   the object row. The column is a signed `bigint`. It holds an inode of 9223372036854775808 or
   more as that inode minus 18446744073709551616. This statement does the conversion:

   ```sql
   update huron.objects
   set inode = (case when n >= 9223372036854775808 then n - 18446744073709551616 else n end)::bigint
   from (select <inode>::numeric as n) as copy
   where upload_id = '<upload ID>' and state = 'sealed';
   ```

6. Retry the request. The step then links the copy, and the request can succeed.

This procedure follows the code of the publication. Nobody has run it on a cluster yet.

When no copy with that SHA-256 exists, Huron cannot complete the request. Keep the request
blocked: it holds only its collection. Report the case to the developers of Huron.

## Uploads: capacity and lifetime

These settings of `huron.yaml` limit the uploads. A value of `0` is no limit.

| Setting | Default | Meaning |
| --- | --- | --- |
| `max_upload_bytes` | `0` | The largest file of one upload. A larger file gets 413 `UPLOAD_TOO_LARGE`. Set tusd's `-max-size` to the same value. |
| `max_staged_bytes` | `0` | The most bytes of all uploads in `receiving`, `sealing` or `ready`. Each upload counts two times: the file of tusd and its sealed copy. A new upload that does not fit gets 429 `CAPACITY_EXCEEDED`. |
| `min_free_bytes` | 1 GiB | The free space that each filesystem must keep after a new upload. A new upload that does not fit gets 429 `CAPACITY_EXCEEDED`. |
| `attempt_ttl` | 7 days | The lifetime of an upload after its last activity. |
| `sweep_interval` | 10 minutes | The time between two runs of the periodic loop. |

The free-space check reads `statvfs` of two filesystems: the one of `.tus-uploads` and the one of
the object area of the organization. When they are one filesystem, the upload needs two times its
size there. A quota or the snapshot reserve of the export can change what `statvfs` reports. That
measurement is not made yet ([Setgid measurement (pending)](#setgid-measurement-pending)).

The defaults set no limit on the size of a file and on the staged bytes. Set both for production.

An upload expires `attempt_ttl` after its last activity. Activity is a `PATCH` that nginx
authorized, or the end of a seal. Expiry applies to an upload in `receiving` or `sealing`, and to
a `ready` upload that no commit request holds. The periodic loop marks such uploads `expired`.
A later push of the file starts a new upload.

## Cleanup

The periodic loop runs every `sweep_interval`. It continues each `accepted` request that has no
task. Then it cleans up the lake:

1. It marks the uploads past `attempt_ttl` as `expired`.
2. It removes each object that no file row and no pending request names, when its upload ended,
   was consumed or is not current. It removes the file only while it has the inode of the object.
3. It removes the files of tusd (the data and `.info`) of each upload ID that is not current, or
   whose upload ended or was consumed.

The database decides each removal by object ID or by upload ID. The cleanup never removes a file
because of its age or the form of its name. It never touches an upload whose seal runs. A file in
`.tus-uploads` that this database did not issue stays. A failed removal goes to the log as
`cleanup.failed`, and the next run tries it again.

The object area holds a second name of each published file: the object and the file in the
collection are one inode. Thus the object of a published file uses no more space. A replaced or removed file frees
its space only when the cleanup removes its object.

## Helm: not yet delivered

The Helm chart `deploy/helm/huron` has no upload pod, no lake volume and no upload settings yet.
Its API mounts no share, so it takes no upload and no commit. Until the chart has them, deploy
the uploads with the Kustomize base. Task M11.13 of the implementation plan adds these parts to
the chart:

- The values of the lake, the service user, the uploads and the scheduling of the upload pod, with
  their schema. The values include the capacity settings and the upload lifetime, with no
  unlimited default.
- The upload Deployment with the init container that removes the lock files, its Route, and its
  Ingress with the ingress-nginx defaults of the uploads.
- The nginx ConfigMap.
- The lake volume and the security context of the API. The schema allows one writable replica
  only.
- The production values. These need the record of the setgid measurement on the export
  ([Setgid measurement (pending)](#setgid-measurement-pending)).

## Local cluster

The overlay `deploy/local` runs the Kustomize base on the kind cluster `huron-local` of a
development machine, in the namespace `huron`. The lake is a directory of the host, which the node
shows at `/huron-lake`. The claim `huron-lake` binds to a `hostPath` PersistentVolume there, so the
CLI on the host reads the same files as the pods. The Job `huron-lake-init` prepares the lake
before the API pod and the upload pod start. It runs `huron adm provision-orgs --config` as the
service user.

| Command | What it does |
| --- | --- |
| `make k8s-local-cluster` | Makes the cluster `huron-local` once, with ingress-nginx on 127.0.0.1:18444. |
| `make k8s-local` | Builds the API image, loads the cached images into the node and applies the overlay. |
| `make k8s-local-smoke` | Logs in on the host, pushes files through the Ingress, nginx and tusd, and runs `huron adm check --hash` from the host directory. |
| `make k8s-local-down` | Deletes the namespace `huron` and the PersistentVolume. The lake content stays. |

The variables are these:

- `K8S_LOCAL_CONTEXT` (default `kind-huron-local`): the kubectl context. The script refuses to
  start in another context.
- `K8S_LOCAL_KUBECONFIG` (default `$HOME/.kube/huron-local.config`): the kubeconfig of the cluster.
  The script never reads your default kubeconfig.
- `K8S_LOCAL_LAKE`: the host directory of the lake.
- `K8S_LOCAL_PURGE`: only the value `1` makes `make k8s-local-down` also delete the lake content
  and the images.

[deploy/README.md](../deploy/README.md#the-local-cluster-deploylocal) gives the details and the
refusals of a purge.

## Setgid measurement (pending)

The read model of the share needs the export to give a new directory the setgid bit and the group
of its parent. This inheritance on the production export is not measured yet. The production
values of the Helm chart need the record. Do these steps on the real export, where `U` is not a
member of the share group `S`:

1. As root, make a directory `t` with the owner `U`, the group `S` and the mode `2750`.
2. As `U`, with `umask 022`, run `mkdir -m 0750 t/d; touch t/f; stat -c '%a %U %G' t/d t/f`.
   Expect `2750 U S` for `t/d` and `644 U S` for `t/f`.
3. As root, run `chgrp S t/d; chmod 2750 t/d`, then `stat -c '%a %G' t/d`. Expect `2750 S`.
4. Record the date, the `stat` lines and the security style of the volume (UNIX, NTFS or mixed)
   in this guide, under a heading with the date.

These measurements on the export are not made yet either:

- A hard link from the object area into a collection directory of each organization root.
- A rename over a file that a reader on another client holds open. The record also tells what
  the directory then lists.
- A removal of a file that a process on the same client holds open. The record also tells what the
  directory then lists.
- The time to copy and hash 10 GiB through the mount, compared with `upload_hook_timeout`.
- What `statvfs` reports with the quota and snapshot settings of the export.

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

Run these commands on a machine that mounts the lake, because `huron adm verify-mounts` reads it.
`huron adm provision-orgs` also needs root on a writable mount
([Where the storage admin works](#where-the-storage-admin-works)). After step 5 of the
[Install order](#install-order), it changes nothing.

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

PostgreSQL is the catalog of record. The lake holds the bytes. The two must agree: the rows name
each object by its path and its inode, and each pending request names its entries. Thus a backup
holds both, taken at the same point, and a restore puts back both, from the same point. A restore
of PostgreSQL alone, or of the lake alone, is not supported.

To take a backup at one point, do these steps:

1. Stop the API and the upload pod: scale `deployment/huron` and `deployment/huron-uploads` to 0
   replicas.
2. Make the backup of PostgreSQL, for example with `pg_dump`.
3. Make the snapshot of the lake. It includes the object area of each organization, and
   `.tus-uploads` when that directory is on the same filesystem.
4. Scale both Deployments to 1 replica again.

To restore, stop both Deployments, restore PostgreSQL and the lake from the same point, then start
both again. The rows record the inode of each file, and the steps of a commit and the cleanup
compare it. So the restore of the lake must keep the inode numbers. A copy of the files gets new
inode numbers. Ask the storage team which restore of the export keeps them. Then run
`huron adm check --hash`.

`.tus-uploads` can be on another filesystem ([The API's mount](#the-apis-mount)). The design says
nothing about its backup. It holds the files of tusd. The bytes of a sealed upload are also in the
object area. A restore can lack the file of an upload that is still `receiving`. Then the next push
of that file starts the upload of the file again.

Huron keeps no earlier version of a file. To get the old bytes of one file back, copy the file out
of a snapshot, then stage it with `huron add` and push it. That makes a new commit.

## Reading `huron adm check`

The check is a report for administrators. It only reads the share. It checks each catalog that the
account can read through the API. It reads the share with the user and the groups of the account
on that machine.

No single account sees everything. The check needs two things on its machine:

- **Read access to every entry.** The service user `U` reads every entry. An account in the
  service group `G` and in every share group reads every entry but the object areas. Any other
  account gets an `unreadable` finding for each entry that it cannot read, outside the object
  areas. The check skips an object area for every account but `U`, with no finding.
- **The names of the share groups.** The check resolves the name of each share group with the
  group database of its machine, for example through sssd. When it cannot resolve a name, it
  reports `share_group_mismatch` with the detail `this machine does not know the share group
  <group>`.

So run the check in one of these two ways, or in both:

- **On a workstation**, as an account in `G` and in every share group, with the LDAP groups
  through sssd. This checks the share groups. It does not see a probe file in an object area,
  because only `U` reads the object areas.
- **In the API pod, as `U`.** This reads every entry, the object areas included. The API image
  has no LDAP group in its group database. So the check reports `share_group_mismatch` for each
  catalog that has a share group, and it exits with code 1. Read the other findings, and check the
  share groups on a workstation.

The check exits with code 1 when it has findings, and with code 2 when it cannot use the share.

To run the check as `U`, use the API pod. The API image holds the `huron` CLI, and a shell in the
pod runs as `U` with the lake at `lake_path`. The CLI there needs a configuration and a login of
its own. The root filesystem of the pod is read-only, so keep both in `/tmp`, the writable
`emptyDir` of the pod:

```bash
oc exec -it deploy/huron -- sh
export XDG_CONFIG_HOME=/tmp/huron/config XDG_STATE_HOME=/tmp/huron/state
export HURON_API_URL=http://127.0.0.1:8080                  # the API in the same pod
export HURON_ISSUER=https://login.example.org/realms/company
export HURON_MOUNT_PREFIX=/data1/huron                      # lake_path
huron login --device    # open the link on your own machine, sign in as a platform admin
huron adm check
huron logout            # delete the token in the pod
```

The pod must reach the issuer for the login. The token stays in `/tmp` of the pod until
`huron logout` or until the pod stops. The local cluster runs the check from the host mount, not
in a pod, so this route is not tested on a cluster.

| Finding | What to do |
| --- | --- |
| `org_dir_missing`, `org_marker_missing` | The storage admin runs `huron adm provision-orgs --org <org>`. For a declared organization, the API is not ready meanwhile, so add `--config <huron.yaml>`: the command then sends no request to the API. For an organization that is neither declared nor rooted, `huron adm repair --org <org>` makes its directory, and `huron adm provision-orgs` writes the marker at the lake path. Check that the export is mounted at its root. |
| `org_marker_mismatch` | The marker names another instance or organization. The wrong export is mounted at this root, or the CLI points at another service. Fix the mount or `api_url`. Never edit the marker by hand. |
| `stale_link_probe` | Information: a readiness probe stopped and left a `.huron-link-probe-*` file in the organization directory or its object area. Only the service user sees a probe file in the object area. The check keeps it. The storage admin can delete it. |
| `org_undeclared` | A warning. The configuration no longer declares the organization. Thus the CLI cannot find its directory and does not check its catalogs. Declare it again with its root, or empty it and delete it ([Configuration](#configuration)). |
| `namespace_dir_missing`, `collection_dir_missing` | Run `huron adm repair <identifier> --recursive`. The API makes the directories that the rows plan. |
| `file_missing` | The service records a file that is not on the share. Follow [Missing or changed files](#missing-or-changed-files). The check does not report a recorded file below a directory that it cannot read. |
| `file_changed` | A process changed the file outside Huron, or the disk failed. Follow [Missing or changed files](#missing-or-changed-files). |
| `file_unrecorded`, `dir_unrecorded` | An entry that no row names. Only the storage admin can delete it, because the share is read-only for users. A commit that adds a file at that path blocks with the reason `foreign_entry` until the entry is gone. |
| `sidecar_stale` | `huron adm repair <identifier>` writes `metadata.json` again. Any metadata change writes it too. |
| `stale_part` | Information: a `.huron-part` file in a collection, older than one hour. It is the temporary name of a stopped publication, or the part file of a stopped write of `metadata.json`. The check keeps it. The storage admin can delete the file when no commit request holds the collection. |
| `pending_commit` | Information: a commit request holds the collection. Its directory can hold old and new files until the request ends. A blocked request needs a platform admin ([Blocked commit requests](#blocked-commit-requests)). |
| `nfs_file` | Information: an NFS client keeps a deleted file while a process holds it open. The client deletes the file when the process closes it. The check reports these files in an organization directory and below a catalog. A collection cannot record a name that starts with `.nfs`, so the check does not compare the file with a record. |
| `snapshot_dir` | Information: the storage shows its snapshots in a `.snapshot` directory, in an organization directory or below a catalog. A collection cannot record a path with a `.snapshot` segment, so the check does not read that directory. |
| `mode_drift` | A directory or file has the wrong mode or the wrong owner. Or an organization directory does not have the service group. Or a directory below a catalog does not have the setgid bit or the group of the catalog directory. What to do depends on the entry. For the directory of a declared organization, the storage admin runs `huron adm provision-orgs --org <org>`, which sets the owner, the group and the mode. For the directory of an organization that the configuration does not declare, `provision-orgs` refuses. There `huron adm repair --org <org>` fixes the permission bits, and the storage admin corrects a wrong owner or group as root. For the directory of a catalog, a namespace or a collection, `huron adm repair <identifier> --recursive` fixes the permission bits. A repair can change a mode only while the API is in the group of the directory. Below a catalog with a share group, the API is usually not in that group. Then the repair fails with `mode_drift` and the detail `The API is not in the group …`. A repair does not plan a directory inside a collection. For a missing setgid bit or a wrong group of any directory below a catalog, the storage admin runs `huron adm provision-catalogs`. It gives each directory of the selected catalogs the group of the catalog and the mode `2750`. The storage admin corrects as root any other wrong mode that the repair cannot fix. The storage admin also corrects the mode or the owner of a file ([Where the storage admin works](#where-the-storage-admin-works)). |
| `share_group_mismatch` | The storage admin runs `huron adm provision-catalogs`. When this machine does not know the share group, check the group database of the machine. In the API pod, expect this finding for each catalog with a share group: check the share groups on a workstation. |
| `unreadable` | The account that runs the check cannot read the entry. Run the check as the service user, or as an account in the service group and in every share group. |
| `symbolic_link` | The lake must not contain symbolic links. The storage admin deletes the link. Huron never follows it or deletes it. Then run the work again that the link stopped ([Symbolic links in the lake](#symbolic-links-in-the-lake)). |
| `incomplete` | The metadata no longer satisfies the catalog schema. Edit the metadata and publish it. |
| `stale_draft` | Activate the draft or delete it. |

### Missing or changed files

A step of a commit identifies a recorded file by the inode in its row. A replace of the file
expects that inode at the path, and so does a removal. These steps follow from the code of the
publication and the CLI. Nobody has run them yet.

**Before a push of the path.** A contributor cannot see the recorded inode. An operator with
access to the database compares it with the file on the share. The finding gives the identifier
of the collection and the path of the file below the root, such as
`helio/heliophysics/solar-wind/run7/kp/q1.txt`. `huron -o json describe collection <identifier>`
gives the `id` of the collection and its `path`. The path in the collection is the path of the
finding after that `path` and a `/`, as `huron get files <identifier>` shows it. Read the row:

```sql
select inode from huron.files where collection_id = '<id>' and rel_path = '<path in the collection>';
```

The column is a signed `bigint`. It holds an inode of 9223372036854775808 or more as that inode
minus 18446744073709551616, so add 18446744073709551616 to a negative value. On a machine that
mounts the share, `stat -c %i <file>` prints the inode of the file.

- `file_changed`, with the recorded inode: the file changed in place. The contributor stages the
  file again with `huron add <file> --as <path in the collection>`, then runs `huron push`.
- `file_changed`, with another inode: the step needs the path empty. The storage admin moves the
  file out of the collection directory, or keeps a copy and deletes it
  ([Where the storage admin works](#where-the-storage-admin-works)). Then continue as for a
  missing file.
- `file_missing`: the contributor stages the removal with `huron rm <path in the collection>` and
  pushes it. The removal of a missing file succeeds. Then the contributor stages the file with
  `huron add` and pushes it.

**After a push of the path blocked.** A replace of a missing file, or of a file with another inode,
blocks with `foreign_entry`. The push waits up to 10 minutes for the request, then stops with exit
code 6 and `PUBLICATION_BLOCKED`. The working copy keeps the commit. So `huron rm` and `huron add`
stop with exit code 6 until a `huron push` gets the end of the request. Read the entries of the
request ([Blocked commit requests](#blocked-commit-requests)).

- No entry is done: a platform admin abandons the request. The next `huron push` of the
  contributor gets the end of the request: it stops with exit code 6 and keeps the stage. The
  first `huron rm <path in the collection>` unstages the add, and a second one stages the
  removal. For a file with another inode, the storage admin first moves the file out of the
  collection directory, or keeps a copy and deletes it. Then the contributor pushes the removal,
  and stages and pushes the file again.
- An entry is done: a retry blocks again, because the path still does not hold the recorded inode,
  and an abandon is refused. Huron has no procedure for this case. Keep the request blocked and
  report the case to the developers of Huron.

A copy that the storage admin puts back gets a new inode, so a later replace or removal of it
blocks in the same way.

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
