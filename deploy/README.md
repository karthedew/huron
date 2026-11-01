# Deploying Huron

Two supported ways to deploy the same thing: the Helm chart [`helm/huron`](helm/huron) and the
kustomize base [`openshift`](openshift). Each one gives you the API Deployment, its Service, an
edge-terminated Route (or, with Helm, an Ingress), the migration Job and the service configuration
`huron.yaml` in a ConfigMap, mounted at `/etc/huron/huron.yaml` and named by `HURON_CONFIG_FILE`.
The Helm chart can also deploy the read-only web. The service mounts no share. It needs PostgreSQL,
the company OIDC provider and the LDAP group directory, nothing else.

## The service configuration

`huron.yaml` holds the API's settings (the field names of `src/huron/applications/api/settings.py`)
plus `organizations`. `HURON_*` environment variables win over the file. The API refuses to start
when the file has an unknown key, so a typo such as `organisations:` fails the rollout and does not
quietly switch the declaration off. Keep the database URL in the Secret, never in the file.

With an `organizations` key (even `organizations: []`) the service is in **managed mode**. At each
start it reconciles the database to the list, under a database lock so replicas starting together
agree:

- it creates each missing organization;
- it updates a changed `display_name` or `description`;
- it sets the groups of each organization-wide role to exactly its `groups`: `org_admin`, and the
  `catalog_admin`, `contributor` and `reader` groups that every catalog of the organization
  inherits.

The API then refuses to create other organizations, to delete a declared one and to change any of
a declared one's organization-wide role groups (409). Grants on a single catalog stay with the API
and add to the inherited ones. An organization you remove from the list is logged as a
warning and stays in the database, usable through the API and the web. It is never deleted; once it
has no catalogs you may delete it. Its directory is another matter: the root came from the list, so
the CLI no longer knows where it is until you declare the organization again with the same root.
Empty an organization while it is still declared, then remove it (see
[docs/operator.md](../docs/operator.md#configuration)). A rename is
one entry removed and another added. Without the key the service is unmanaged: platform admins
create organizations with `huron create org` under the CLI's `mount_prefix`, as before.

Each entry has these fields:

| Field | Required | Meaning |
| --- | --- | --- |
| `name` | yes | The organization's name: lowercase letters, digits, `-` and `_`, starting with a letter or digit, at most 63 bytes, not `huron` or `metadata`. Names must be unique. |
| `display_name`, `description` | no | Shown in the CLI and the web. |
| `groups` | no | The LDAP groups of each organization-wide role, exactly: `org_admin`, `catalog_admin`, `contributor` and `reader`, each an optional list (default none); any other key fails startup. The three catalog roles hold in every catalog of the organization, existing and future. See [LDAP groups and roles](../docs/operator.md#ldap-groups-and-roles) for the recommended groups. |
| `root` | no | The parent of the organization's directory. That directory is always `<root>/<name>`. Without a root it is `<mount_prefix>/<name>` on each CLI machine. The root must be an absolute, normalized path. |
| `export` | no | Informational, such as `nfs1:/export/data1`. The CLI shows it in mount hints. |

Every machine that runs the CLI must mount each root at the same path.

## With Helm

1. Build and push the API image from `Containerfile` (and, for the web, `web/Containerfile`).
2. Create the database secret, which the chart only references:
   `oc create secret generic huron-db --from-literal=HURON_DATABASE_URL=postgresql://huron:…@postgres.example.org:5432/huron`.
3. Write a values file. [`helm/huron/ci/example-values.yaml`](helm/huron/ci/example-values.yaml)
   is a complete example and [`helm/huron/values.yaml`](helm/huron/values.yaml) documents every
   value. `config` is rendered verbatim as `huron.yaml`. `config.instance_id` is required: it is the
   UUID written into the share markers (generate one with `uuidgen`). `values.schema.json` rejects
   unknown `config` keys, `config.database_url`, invalid organization names and relative roots. It
   cannot check that names are unique; the API checks that at startup.
4. Check and install:

   ```sh
   helm lint deploy/helm/huron -f my-values.yaml
   helm template huron deploy/helm/huron -f my-values.yaml   # review what will be applied
   helm upgrade --install huron deploy/helm/huron -n huron -f my-values.yaml
   ```

   The migration Job is a `pre-install,pre-upgrade` hook, so the schema is migrated before the
   release's pods start, on every install and upgrade. It needs only the database secret. A changed
   `config` changes the `checksum/config` annotation of the API pods, so `helm upgrade` rolls them
   and the new pods reconcile the organizations.
5. Check `/readyz` through the Route (`route.enabled`, on by default) or the Ingress
   (`ingress.enabled`). The release notes print the commands.

The web is off by default. Set `web.enabled: true`, `web.origin`, `web.oidc.issuer` and
`web.oidc.existingSecret` (a secret with the confidential client's `HURON_WEB_OIDC_CLIENT_SECRET`).
It talks to the release's API Service unless `web.apiUrl` says otherwise.

## With kustomize (`deploy/openshift`)

1. Build and push the image from `Containerfile` to the registry named in `kustomization.yaml`.
2. Create the secret from `secret.example.yaml` (never commit the filled copy):
   `oc apply -f secret.yaml`.
3. Edit [`openshift/huron.yaml`](openshift/huron.yaml): set `instance_id` to the UUID written into
   the share markers, set the issuer, company issuer and group directory URLs, and declare the
   organizations (or remove the `organizations` key for unmanaged mode). The `configMapGenerator`
   in `kustomization.yaml` turns the file into the ConfigMap `huron-config-<hash>`. An edit changes
   the hash, so `oc apply -k` rolls the API pods.
4. Run the migration: `oc apply -k deploy/openshift` creates the Job; wait for it with
   `oc wait --for=condition=complete job/huron-migrate`.
5. The Deployment starts once the Job succeeds; check `/readyz` through the Route.

Preview the manifests with `kubectl kustomize deploy/openshift`. For a new release, delete the
finished Job (`oc delete job huron-migrate`) before applying again so the migration runs for the
new image.

## Preparing the organization directories

The service never touches the share. After every change to the declared organizations, the storage
administrator prepares their directories on a machine that mounts each root:

```sh
huron adm provision-orgs --dry-run   # what it would do
huron adm provision-orgs             # create <root>/<org>, apply the ACLs, write the marker
huron adm verify-mounts              # one row per organization; every row must say ok
```

`provision-orgs` never creates a root itself and is safe to re-run. It writes the
per-organization marker `<root>/<org>/.huron`, which names this service's instance and the
organization. The CLI refuses disk operations below an organization whose marker is missing or
names another instance or organization. Where only `root` may write a root,
`huron adm provision-orgs --emit-script` prints the same steps as a shell script to hand over.
Organizations without a root use the marker at the mount prefix, which `scripts/init-root.sh`
writes, as before.

## Signing-key rotation

Huron signs its tokens with ES256 keys stored in the database. A platform admin rotates with
`POST /api/v1/admin/signing-keys/rotate`; the previous key keeps verifying tokens for
`HURON_KEY_OVERLAP_HOURS` (24 by default), so rotate at least that long before retiring a key you
suspect. Replicas reload the key ring within `HURON_KEY_CACHE_SECONDS` (60 by default).
