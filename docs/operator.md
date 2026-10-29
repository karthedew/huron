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
  redirects enabled.
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

`scripts/e2e.sh` starts the compose stack, logs in as the development users and walks the user
guide against a temporary directory standing in for the share.
