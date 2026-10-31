# Operator guide

## Prerequisites

- **LDAP groups.** One platform admin group (for example `huron-platform-admins`) and, per
  organization and catalog, groups for org admins, catalog admins, contributors and readers. Huron
  grants roles to groups; membership is managed in LDAP.
- **The share.** One NFS export mounted at the same path (default `/projects/huron`) on every
  machine where people run the CLI. Users need their LDAP groups resolved on those machines (sssd)
  for POSIX ACLs to apply. Check with `getfacl` that the export honors POSIX ACLs; if it does not,
  set `acl_backend: none` in each user's CLI configuration and Huron applies modes only.
- **A group directory** answering `GET /users/{username}/groups` with `{"groups": [...]}`.
- **An OIDC client** `huron-cli`: public, with the device grant and `http://127.0.0.1` loopback
  redirects enabled. The loopback flow sends PKCE (S256). With Keycloak 26, do not set PKCE as
  required on `huron-cli`: Keycloak then demands PKCE at the device endpoint, which the CLI's
  device flow does not send yet.
- **PostgreSQL 16.**

## Preparing the share

Run once, as a user that owns the prefix (or root):

```bash
scripts/init-root.sh /projects/huron huron-platform-admins https://huron.apps.example.org <instance-uuid>
```

It sets mode 2771 and the platform admin ACL and writes `/projects/huron/.huron`. The CLI refuses to
touch the share unless the marker's `instance_id` equals the service's `HURON_INSTANCE_ID`, so a CLI
pointed at a test service cannot write into production directories.

## Deploying

See [deploy/README.md](../deploy/README.md). Configuration is entirely `HURON_*` environment
variables (`src/huron/applications/api/settings.py`). On first start the service seeds the
`huron-base` schema, a Platform Admin grant for `HURON_PLATFORM_ADMIN_GROUP` and a signing key.

## Deploying the web

The web app (`web/`) is an optional, read-only view of the catalog in a browser. `deploy/` has no
manifests for it yet: build its image from `web/Containerfile` (Node, a non-root user, port 3000)
and run it beside the API. [web/README.md](../web/README.md) has the details.

- **An OIDC client for the web**: confidential, code flow only, PKCE S256, the redirect URI
  `<ORIGIN>/auth/callback` and the post-logout URI `<ORIGIN>/login?status=signed-out`. Its ID
  tokens must carry the API's `HURON_COMPANY_AUDIENCE` in `aud`; with Keycloak, add an audience
  mapper on the ID token.
- **Settings** are environment variables: `ORIGIN`, `HURON_API_URL`, `HURON_WEB_OIDC_ISSUER` (the
  API's `HURON_COMPANY_ISSUER`, byte for byte), `HURON_WEB_OIDC_CLIENT_ID` and
  `HURON_WEB_OIDC_CLIENT_SECRET`, and optionally `HURON_WEB_OIDC_SCOPES`, `HURON_WEB_OIDC_LOGOUT`,
  `HURON_WEB_MOUNT_PREFIX` and `HURON_WEB_API_TIMEOUT_MS`;
  [web/.env.example](../web/.env.example) explains each.
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
huron platform verify-root
huron org create helio
huron org grant helio helio-org-admins
```

## Backups and recovery

Back up PostgreSQL; it is the catalog of record. File recovery is the storage team's snapshot
policy — Huron keeps no file versions. After restoring files from a snapshot, run `huron check` and
reconcile.

## Reading `huron check`

| Finding | What to do |
| --- | --- |
| `namespace_dir_missing`, `collection_dir_missing` | Re-run `huron namespace create …` or `huron collection activate`; both repair directories. |
| `file_missing` | Restore the file, or commit its removal with `huron rm` and `huron push`. |
| `file_changed` | Someone wrote outside the CLI. Push the file again or restore it. |
| `file_unrecorded`, `dir_unrecorded` | Stage and push it, or remove it. |
| `sidecar_stale` | `huron meta publish` (or any metadata change) rewrites `metadata.json`. |
| `acl_drift` | The directory's owner runs `huron acl apply <identifier>`; a storage admin can `chown` directories whose owners have left. |
| `stale_part` | An interrupted copy; the next push reuses or replaces it, or delete it. |
| `incomplete` | Metadata no longer satisfies the catalog schema; edit and publish it. |
| `stale_draft` | Activate or delete the draft. |

## Pre-release check

`scripts/e2e.sh` starts the backend of the Docker stack (`docker-compose.app.yml`) as its own compose
project with an empty database, logs in as the development users and walks the user guide against a
temporary directory standing in for the share, then removes the project, its volume and its API
image `huron-e2e-api:dev`. It needs the ports of `make app` and `make up`, so stop those first.
