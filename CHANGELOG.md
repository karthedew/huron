# Changelog

## Unreleased

- The web app (`web/`) is rewritten as a read-only client of the API; its Polaris, Icechunk and
  local-account pages are gone. Its SvelteKit server signs people in with the company OIDC
  provider (code flow with PKCE), exchanges the ID token for a Huron token that only the server
  holds, in an in-memory session behind an opaque cookie, and renders every page from its own API
  calls. People switch between the organizations they can see, browse catalogs, their nested
  namespaces and their collections (metadata against the collection's schema, state and problems,
  files, commits, activity and schema), and search a catalog, or an organization across its
  catalogs. Where the signed-in user could change something, the page shows the `huron` command
  for it. The design is `docs/web-design.md`.
- The web's shell has a sidebar, an organization switcher, a search box scoped to the page's
  catalog or organization, an account menu, light and dark themes and a bottom navigation on
  phones. `npm run demo` runs the web against a fake company IdP and the API on its memory store
  with demo data, and `npm run test:e2e` runs its Playwright tests on the same stack.
- `make app` runs the whole application in Docker (`docker-compose.app.yml`, project `huron-app`):
  PostgreSQL with its own volume, the migrations, the API, the development group directory,
  Keycloak 26.0 as the company OIDC provider, the web app (`web/Containerfile`) and a one-shot seed
  that loads the web's e2e demo fixture and changes nothing once it is there. The containers share
  one network namespace with their ports published on 127.0.0.1, so the issuer and every other URL
  are the same in the containers and on the host. `make app-down`, `make app-logs` and
  `make app-reset` stop it, follow its logs and delete its data. Keycloak imports the realm on
  every start, so the realm is never stale, and keeps its in-memory database while it runs
  (`KC_DB_URL_PROPERTIES=;DB_CLOSE_DELAY=-1`): without it H2 dropped the database once the idle
  connection pool closed its last connection, a few minutes after the last request, and every
  sign-in failed until a restart. `HURON_WEB_MOUNT_PREFIX` sets the share path the web shows
  (default `/projects/huron`). It needs Docker Engine 25 or newer for the health checks'
  `start_interval`.
- The development realm has a confidential `huron-web` client and the accounts `admin` (platform
  admin) and `user` (contributor and reader); `dave` also reads `geoscience`, as in the e2e fixture.
- The realm's `huron-cli` client no longer enforces PKCE: Keycloak 26 then demands PKCE at the
  device endpoint too, which the CLI's device flow does not send, so `huron login --device` failed.
  The loopback flow still sends S256 and Keycloak still checks it.
- `dev.env` names the company issuer `http://127.0.0.1:8081/realms/company`, the issuer Keycloak
  stamps into tokens. It named `http://keycloak:8081/…`, which the host cannot resolve and no token
  carries, so `make api` refused every login.
- The API ignores encryption keys, and keys it cannot load, in the company IdP's JWKS. Keycloak 26
  publishes an `RSA-OAEP` encryption key next to its `RS256` signing key, and loading that key
  failed every exchange.
- The `app` profile of `docker-compose.yml` is gone: its containers could not reach the issuer the
  tokens carry. `scripts/e2e.sh` runs on the new stack, as its own compose project with its own
  API image `huron-e2e-api:dev`, which it removes afterwards.
- A root `.dockerignore` keeps the API image's build context to what the image copies.

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
