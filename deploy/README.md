# Deploying Huron

Huron has two ways to deploy: the kustomize base [`openshift`](openshift) and the Helm chart
[`helm/huron`](helm/huron). Both give you the API Deployment, its Service, the migration Job and
the service configuration `huron.yaml` in a ConfigMap. The API reads it at `/etc/huron/huron.yaml`,
which `HURON_CONFIG_FILE` names.

- The kustomize base also deploys the lake and the uploads: the claim `huron-lake`, which the API
  mounts read-write, and the upload pod `huron-uploads` with nginx and tusd. It has a Route for the
  API and a Route for `/files`.
- The Helm chart does not have the lake and the upload pod yet. Its API mounts no share. It has a
  Route or an Ingress, and it can also deploy the read-only web. See
  [Helm: not yet delivered](#helm-not-yet-delivered).

The service needs PostgreSQL, the company OIDC provider and the LDAP group directory. With the
kustomize base, it also needs the NFS export of the lake. The overlay [`local`](local) runs the
kustomize base on a kind cluster of a development machine
([The local cluster](#the-local-cluster-deploylocal)).

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
| `root` | no | The parent of the organization's directory. That directory is always `<root>/<name>`. Without a root it is `<lake_path>/<name>` in the API pod and `<mount_prefix>/<name>` on each CLI machine. The root must be an absolute, normalized path, at or below `lake_path` when `lake_path` is set. |
| `export` | no | Informational, such as `nfs1:/export/data1`. The CLI shows it in mount hints. |

Every machine that runs the CLI must mount each root at the same path.

## With Helm

1. Build and push the API image from `Containerfile` (and, for the web, `web/Containerfile`, with
   the repository's `docs/` as the build context `docs`:
   `docker build --build-context docs=docs -f web/Containerfile web`).
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

The base holds these files:

| File | Content |
| --- | --- |
| `deployment.yaml` | The API Deployment `huron`: one replica, the strategy `Recreate`, the lake at `lake_path`, the service user and group |
| `service.yaml`, `route.yaml` | The API Service `huron` on port 8080, and its edge Route with a timeout of 300 s |
| `uploads.yaml` | The upload pod `huron-uploads`, its Service on port 1080, its Route for the path `/files` with a timeout of 3600 s, and the claim `huron-lake` |
| `migrate-job.yaml` | The Job `huron-migrate`, which runs `alembic upgrade head` |
| `huron.yaml` | The service configuration, through the `configMapGenerator` `huron-config` |
| `nginx-uploads.conf.template` | The nginx configuration of the upload pod, through the `configMapGenerator` `huron-uploads-nginx` |

There is no NetworkPolicy. A NetworkPolicy selects pods and ports, not HTTP paths, and the hooks
route of the API is safe without one.

### The lake claim

The claim `huron-lake` asks for a `ReadWriteMany` volume with `storageClassName: ""`, so no storage
class makes a volume for it. The cluster administrator makes the PersistentVolume of the export and
binds it to the claim. The mount options belong to that volume, for example `vers=3`, `proto=tcp`,
`hard`, `timeo=600`, `sec=sys`, `rsize=65536`, `wsize=65536` and `local_lock=none`. The API pod and
the upload pod mount the claim at `lake_path` (`/data1/huron`). If you change `lake_path` in
`huron.yaml`, change the `mountPath` of the lake in both pods, tusd's `-upload-dir` and
`HURON_UPLOAD_DIR` of the init container too.

### The service user and the service group

Both pods run as one user `U` with the primary group `G`, never as root, with the seccomp profile
`RuntimeDefault`. Each container drops all capabilities and has a read-only root filesystem.

- `U` is the first UID of the namespace's pinned range. The restricted SCC (`restricted-v2`)
  accepts `runAsUser: U` only inside the range of the annotation `openshift.io/sa.scc.uid-range`.
  The cluster administrator pins this annotation when they make the namespace.
- `G` is the `gidNumber` of the service group, an LDAP POSIX group with no human members.
- Set `runAsUser: U`, `runAsGroup: G` and `supplementalGroups: [G]` in `deployment.yaml` and in
  `uploads.yaml`. Set `service_uid: U` and `service_group: <name of G>` in `huron.yaml`. The
  example values are `1000700000` and `huron-svc`.
- The API takes the number of `G` from its own process, which is `runAsGroup`. `service_group` is
  the name that `/healthz` reports with it.

### The export rules

- Make the export read-write only for the nodes that run the API pod and the upload pod. Put the
  upload pod on those nodes with `nodeSelector`, `tolerations` and `affinity` in `uploads.yaml`.
- Every other client mounts the export read-only.
- The export trusts UIDs (`sec=sys`). A user who is root on a client can read each file, and a
  process on a read-write client that claims `U` can write the lake.

### One writer and one tusd

- The API is the one writer of the lake. Never run two API pods. `deployment.yaml` sets one replica
  and the strategy `Recreate`, so a rollout stops the old pod before the new pod starts. A second
  API process that finds the writer lock held serves reads only. The lock does not stop a late
  disk call of a dead pod.
- tusd locks an upload with a hard link: a lock file `<id>.lock` in `.tus-uploads` that holds the
  process ID of tusd. The test that this process is alive works only inside one PID namespace. So
  `uploads.yaml` also sets one replica and the strategy `Recreate`.
- tusd runs as process 1 of its container. After an unclean stop, a new tusd finds its own process
  ID in an old lock file. It then refuses the upload until the lock times out. So the init container
  `clean-locks` removes `*.lock`, `*.lock.*` and `*.stop` in `.tus-uploads` before tusd starts.
  This is safe only because there is one upload pod and the old pod is gone.
- During a rollout, the API or the uploads are not available for a short time.

### Probes and the grace period

- The readiness probe of the API asks `/readyz` with a timeout of 3 s, every 5 s, and fails after 3
  misses. `/readyz` checks the database, the key ring and the lake. On the lake, the writer writes
  and removes a file in `.tus-uploads`. Then it makes a hard link from the object area into each
  declared organization directory, and removes the link. The API waits at most 2 s for this probe.
- The liveness probe of the API asks `/healthz`, which makes no call to the lake. A hung NFS server
  thus makes the API pod not ready, and Kubernetes does not restart it.
- The upload pod has the same readiness timing on `/readyz` of nginx, which asks tusd for
  `OPTIONS /files/`. Its liveness probe asks `/livez`, which nginx answers itself.
- `terminationGracePeriodSeconds` of both pods is 90 s. It must stay longer than
  `upload_hook_timeout` (60 s), the longest time that the CLI waits for a seal. If you change
  `upload_hook_timeout` (at most 55 minutes), change tusd's `-hooks-http-timeout` to the same
  value, and make both grace periods longer.

### Install order

1. Build the image from `Containerfile` and push it to the registry that `kustomization.yaml`
   names.
2. The cluster administrator makes the namespace with its pinned UID range, and the
   PersistentVolume of the export for the claim `huron-lake`.
3. Create the secret from `secret.example.yaml` (never commit the filled copy):
   `oc apply -f secret.yaml`.
4. Edit [`openshift/huron.yaml`](openshift/huron.yaml). Set `instance_id` to a new UUID: the API
   refuses the example value. Set the issuer, company issuer and group directory URLs,
   `uploads_url`, `service_uid` and `service_group`. Declare the organizations, or remove the
   `organizations` key for unmanaged mode. Set the same host in both Routes and in
   `HURON_UPLOADS_HOST` of `uploads.yaml`, and `U` and `G` in both pods. An edit of `huron.yaml`
   changes the name of the ConfigMap `huron-config-<hash>`, so `oc apply -k` rolls the API pod.
5. The storage administrator prepares the lake path and the organization directories
   ([Preparing the organization directories](#preparing-the-organization-directories)). The API
   does not start on a lake path that it cannot write, and the init container of the upload pod
   needs `.tus-uploads`.
6. Run `oc apply -k deploy/openshift`. Wait for the migration with
   `oc wait --for=condition=complete job/huron-migrate`. Until the Job ends, the API pod can fail
   to start and start again.
7. Wait for `oc rollout status deployment/huron` and `oc rollout status deployment/huron-uploads`.
   Then check `/readyz` through the Route.

Preview the manifests with `kubectl kustomize deploy/openshift`. For a new release, delete the
finished Job (`oc delete job huron-migrate`) before you apply again, so that the migration runs for
the new image.

## The local cluster (`deploy/local`)

The overlay `deploy/local` runs the base on the kind cluster `huron-local` of a development
machine, in the namespace `huron`. The lake there is a directory of the host, so the CLI on the host reads
the same files as the pods. The overlay changes the base in these points:

- The claim `huron-lake` binds to the PersistentVolume `huron-local-lake`, a `hostPath` volume at
  the node directory `/huron-lake`.
- PostgreSQL runs as the StatefulSet `huron-postgres` on the storage class `standard`
  (local-path). The init container of the Job `huron-migrate` waits until PostgreSQL answers.
- The Job `huron-lake-init` prepares the lake before the API pod and the upload pod start. It
  runs `scripts/dev-provision.py --config /etc/huron/huron.yaml` from the API image, which runs
  `huron adm provision-orgs --config`. The Job runs as the service user.
- Keycloak and the group directory run as two more containers of the API pod, on 127.0.0.1:8081
  and 127.0.0.1:8082.
- Two Ingresses for the host `localhost` replace the Routes, because no router serves a Route on
  this cluster. ingress-nginx serves them at `https://localhost:18444`. Each Ingress names its host.
  ingress-nginx gives its own default certificate to an Ingress with no host, and to a request
  with no server name, for example to `https://127.0.0.1:18444` (measured 2026-11-13). The
  Ingress of `/files` has
  `proxy-body-size: "0"`, `proxy-request-buffering: "off"`, and `proxy-read-timeout` and
  `proxy-send-timeout` of `"3600"`.
- The pods run as UID 1000 and GID 1000. GID 1000 has no name in the API image, so
  `service_group: huron` of `deploy/local/huron.yaml` is only the name that `/healthz` reports.
  That file declares the organizations of `huron.dev.yaml` with no root, so each one lies directly
  below `lake_path`.
- Each image is in the local cache, and each container has `imagePullPolicy: Never`: the API image
  `huron:local`, which the script builds from this repository, `tusproject/tusd:v2.10.1`,
  `nginx:1.31.8`, `postgres:16` and `quay.io/keycloak/keycloak:26.0`.

The cluster has one node. That node shows the host directory of the lake at `/huron-lake`, and
kind publishes port 443 of the node on 127.0.0.1:18444 of the host. A kind node gets its mounts and
its ports only when you make the cluster. `deploy/local/kind.yaml.template` holds the kind
configuration, with the node image `kindest/node:v1.35.5`. kind needs an absolute host path, so
the script writes the file with `K8S_LOCAL_LAKE` in place of `@K8S_LOCAL_LAKE@`.

The script gives `K8S_LOCAL_KUBECONFIG` (default `$HOME/.kube/huron-local.config`) to each kubectl
and kind command. So it never reads or changes your default kubeconfig, and its current context
stays. The cluster uses port 18444, so it can run beside another cluster that holds port 18443.

Four Makefile targets run `scripts/k8s-local.sh`. Run them as the host user with UID 1000 and
GID 1000.

- `make k8s-local-cluster` makes the cluster once: `kind create cluster` with the written
  configuration, then the kind manifest of ingress-nginx controller v1.15.1
  (`https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.15.1/deploy/static/provider/kind/deploy.yaml`).
  It needs the `kind` binary, and it pulls the node image and the ingress-nginx images when they
  are not in the cache. It refuses to start when the cluster `huron-local` exists. To make the
  cluster again, run `kind delete cluster --name huron-local --kubeconfig <K8S_LOCAL_KUBECONFIG>`
  first. `scripts/k8s-local.sh kind-config` prints the configuration.

- `make k8s-local` builds `huron:local` and imports the five images into the node with
  `docker save | docker exec <node> ctr -n k8s.io images import -`, so it needs no `kind`
  binary. It pulls no image. It makes a local certificate authority and a certificate for
  `localhost` in `.k8s-local/`, which git ignores, and stores the certificate as the TLS Secret
  `huron-local-tls`. It makes the ConfigMaps of the realm `scripts/keycloak/company-realm.json`
  and of `scripts/dev-groups.yaml`. Then it applies the overlay in two steps. First it applies
  each object but the Deployments `huron` and `huron-uploads`, and waits for the Jobs
  `huron-migrate` and `huron-lake-init`. Then it applies the two Deployments and waits for the
  rollouts. A deploy again in the same namespace also starts the API pod again. The pod then runs
  the image that this run imported.
- `make k8s-local-smoke` needs 127.0.0.1:8081, so stop `make app` and `make up` first. It runs
  `kubectl port-forward` to Keycloak in the API pod, and logs in on the host as the platform
  administrator `alice` with `scripts/dev-login.sh`. The token stays in a temporary directory on
  the host. It makes a catalog, a namespace and a collection, and pushes a new file, then an
  overwrite and an empty file, through `https://localhost:18444/files/`. It reads the files in the
  host directory and runs `huron adm check --hash` with the host directory as the mount prefix.
  The check must report no finding. Then it deletes the collection, the namespace and the catalog.
- `make k8s-local-down` first checks that the node of the cluster binds `K8S_LOCAL_LAKE` at
  `/huron-lake`. It refuses another cluster and deletes nothing there. Then it deletes the
  namespace `huron` and the PersistentVolume. The database goes
  with the namespace, because its claim is in the namespace. The host directory of the lake stays.
  With `K8S_LOCAL_PURGE=1` it also deletes the content of that directory, the image `huron:local`
  and the five images in the node. The cluster, ingress-nginx and `.k8s-local/` stay.
- A purge refuses a lake that is your home directory or a directory above it, such as `/`. It also
  refuses a user other than the service user, and a lake directory that the node does not show
  now. In each case it deletes nothing.
- When the smoke stops before its end, its catalog `smoke` can stay, and the next smoke stops at
  the create of that catalog. Delete the collection `smoke.checks.run`, the namespace
  `smoke.checks` and the catalog `smoke` first, or run `make k8s-local-down` and
  `make k8s-local` again with a purged lake.
- After `make k8s-local-down` without `K8S_LOCAL_PURGE=1`, the next `make k8s-local` starts with an
  empty database and the old lake. A catalog directory that is not empty then stops a create of the
  same catalog with `STORAGE_FAILED`. Delete the catalog directories first, or purge the lake.

The variables:

| Variable | Default | Meaning |
| --- | --- | --- |
| `K8S_LOCAL_KUBECONFIG` | `$HOME/.kube/huron-local.config` | The kubeconfig file of the cluster. `make k8s-local-cluster` writes it. |
| `K8S_LOCAL_CONTEXT` | `kind-huron-local` | The kubectl context. The script refuses to start when the current context of `K8S_LOCAL_KUBECONFIG` is another one. |
| `K8S_LOCAL_LAKE` | `$HOME/.local/share/huron-k8s-local/lake` | The host directory of the lake. The script refuses to deploy when the node does not show it at `/huron-lake`. |
| `K8S_LOCAL_PURGE` | not set | `1` makes `make k8s-local-down` delete the lake content and the images. Only the value `1` does this. Another value keeps them. |

With the default `K8S_LOCAL_LAKE`, the local cluster shares no lake directory with `make app` or
`make up`, and it always has its own database. A token of one stack is not valid on the other.

## Preparing the organization directories

The API does not make the lake path or the directories of the declared organizations. After every
change to the declared organizations, the storage administrator prepares them on a machine that
mounts the lake read-write, as root:

```sh
huron adm provision-orgs --dry-run   # what it would do
huron adm provision-orgs             # the lake path, .tus-uploads, each <root>/<org> and the markers
huron adm verify-mounts              # one row per organization; every row must say ok
```

On that machine, the CLI's `mount_prefix` is the lake path. `provision-orgs` gives the lake path
the owner `U:G` and the mode `2751`, makes `.tus-uploads` and writes the marker of the lake path.
For each organization it makes `<root>/<org>` with the owner `U:G`, the mode `2751` and the object
area `.huron-objects`, and writes the marker `<root>/<org>/.huron`. It never makes a root itself and
is safe to run again. The marker names this service's instance and the organization. The CLI and
the API refuse disk operations below an organization whose marker is missing or names another
instance or organization.

- Without the API, for example before the first deploy, add `--config deploy/openshift/huron.yaml`.
  The command then reads the organizations and the service user from that file and sends no
  request to the API.
- Where only `root` may write a root, `huron adm provision-orgs --emit-script` prints the same steps
  as a shell script to hand over.

## Helm: not yet delivered

The Helm chart has no upload pod, no lake volume and no upload settings yet. Until then, deploy
the uploads with the kustomize base. The Helm work adds:

- The values `lake.claim`, `lake.path`, `serviceUser.uid`, `serviceUser.gid`, `serviceUser.group`,
  `uploads.enabled`, the nginx and tusd images, `uploads.url`, the upload size limit,
  `uploads.hookTimeout` (at most 55 minutes), `uploads.nodeSelector`, `uploads.tolerations` and
  `uploads.affinity`, with their schema.
- The upload Deployment with the init container that removes the lock files, its Route, and its
  Ingress with the ingress-nginx defaults of the uploads.
- The nginx ConfigMap from a copy of `deploy/openshift/nginx-uploads.conf.template`.
- The lake volume and the security context of the API, and one writable replica only.
- The production values. These need a record of the measurement of setgid inheritance on the
  export.

## Signing-key rotation

Huron signs its tokens with ES256 keys stored in the database. A platform admin rotates with
`POST /api/v1/admin/signing-keys/rotate`; the previous key keeps verifying tokens for
`HURON_KEY_OVERLAP_HOURS` (24 by default), so rotate at least that long before retiring a key you
suspect. Replicas reload the key ring within `HURON_KEY_CACHE_SECONDS` (60 by default).
