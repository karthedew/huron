# Changelog

## 1.0.0 — 2026-10-29

First release of the rewritten Huron.

Fixed before release, after an independent review:

- Re-validating a catalog's collections re-reads each one under its row lock, so a commit that
  lands mid-assignment is never overwritten.
- A collection whose override no longer composes with a new catalog schema stays readable and
  reports a `schema_incompatible` problem.
- Readers no longer learn about drafts through namespace counts or the catalog audit log, and
  organization catalog counts include only catalogs the caller can see.
- Commits refuse a path that lies inside a recorded or added file, or that would be a directory
  over recorded files.
- `huron collection delete` asks the service first (`DELETE …?dry_run=true`) and refuses
  unrecorded files before removing anything.
- Platform grant changes check the caller before the body; storage and ACL errors exit with 8;
  existing subdirectories keep their mode when files are copied in.

- Organizations, globally named catalogs, recursive namespaces and collections with a draft →
  active ⇄ incomplete lifecycle.
- Five Polaris-shaped roles granted to LDAP groups; the service brokers company OIDC logins into
  ES256 Huron tokens and publishes discovery and JWKS documents.
- A metadata schema registry: platform and organization schemas extending `huron-base`, one
  assignment per catalog, per-collection overrides, re-validation on assignment.
- Synchronous commits carrying a base version; `ETag`/`If-Match` on collections; an append-only
  audit log; RFC 9457 problem documents with stable codes.
- The `huron` CLI: device and loopback login, a metadata walkthrough, directory creation with POSIX
  ACL plans, staging and resumable pushes over the NFS mount, `metadata.json` sidecars, `huron check`
  and `huron acl apply`.
- PostgreSQL schema `huron` (one migration), OpenShift manifests, operator and user guides.
