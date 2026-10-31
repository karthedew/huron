# Huron web

A read-only SvelteKit client of the Huron API. People sign in with the company OIDC provider,
switch between the organizations they can see, browse catalogs, namespaces and collections, and
search a catalog or a whole organization. Nothing is changed through the web: where the
signed-in user could change something, the page shows the `huron` command to run on a machine
that mounts the share.

The SvelteKit server is a backend for the browser. It runs the sign-in (code flow with PKCE),
exchanges the ID token at `POST /api/v1/auth/exchange` for a Huron token, and keeps that token in
an in-memory session behind an opaque `huron_session` cookie. The browser never sees a token;
pages are rendered from the server's own API calls. The design, binding with its dated
amendments, is [docs/web-design.md](../docs/web-design.md); the rules for changing this code are
in the [root AGENTS.md](../AGENTS.md#frontend-web).

## Setup

The web is built and tested with Node 26, the version `web/Containerfile` uses. Once after
cloning, with network access, run in `web/`:

```bash
npm ci                            # the packages pinned in package-lock.json
npx playwright install chromium   # the browser of npm run test:e2e
```

On a Linux machine that lacks Chromium's system libraries, add `--with-deps` to the second
command. Recent npm versions skip esbuild's install script and warn about it; the build and the
tests do not need it. The demo and the end-to-end tests also run the API from the project's Python
environment: run `uv sync` once in the repository root.

## Commands

Run from `web/`:

| Command                | What it does                                                                        |
| ---------------------- | ----------------------------------------------------------------------------------- |
| `npm run dev`          | Development server on http://localhost:5173 with the settings in `.env`.            |
| `npm run demo`         | `vite dev` against a fake company IdP and the API, with demo data.                  |
| `npm run check`        | `svelte-kit sync`, `svelte-check`, and `tsc` for `e2e/`, `scripts/` and Playwright. |
| `npm test`             | Unit and component tests (Vitest).                                                  |
| `npm run lint`         | Prettier check.                                                                     |
| `npm run build`        | Production build into `build/` (adapter-node).                                      |
| `npm run test:e2e`     | Build, then the Playwright tests against the fake IdP, the API and the build.       |
| `npm run start`        | Serve the build with the settings in `.env`.                                        |
| `npm run generate:api` | Regenerate `src/lib/api/openapi.ts` from `docs/openapi.json`.                       |

## Try it: `npm run demo`

The demo runs `vite dev` against a stand-in for the company IdP and the API on its memory store,
seeded with the end-to-end fixture. After the [setup](#setup) it needs nothing more: the API runs
with `uv run --offline --no-sync`, so nothing is downloaded. From `web/`:

```bash
npm run demo
```

It prints the addresses and the users once everything is up. Open http://localhost:5173 (or
http://127.0.0.1:5173), choose **Sign in with your company account**, and pick a user on the fake
IdP's page; there are no passwords. Ctrl+C stops everything.

| User      | Groups                              | For                                                               |
| --------- | ----------------------------------- | ----------------------------------------------------------------- |
| `alice`   | `huron-platform-admins`             | Platform admin: sees everything.                                  |
| `paula`   | `huron-platform-admins`             | Platform admin of the e2e layout walks, which no other test uses. |
| `bob`     | `helio-org-admins`                  | Org admin of `helio`.                                             |
| `carol`   | `helio-catalog-admins`              | Catalog admin of `heliophysics` and `space-weather`.              |
| `dave`    | `helio-contributors`, `geo-readers` | Contributor in `helio`, reader of `geoscience`.                   |
| `erin`    | `helio-readers`                     | Reader in `helio`.                                                |
| `oscar`   | `helio-readers`                     | Reader in `helio`, for fault injection.                           |
| `mallory` | none                                | No groups: the page for users without access.                     |
| `noaud`   | `helio-readers`                     | An ID token without the API's audience: the exchange refuses it.  |
| `idpfail` | `helio-readers`                     | The IdP's token endpoint fails.                                   |

The fake IdP serves the web only; the CLI cannot sign in to it. For the CLI and the web against a
real Keycloak, run [`make app`](#everything-in-docker-make-app).

The web calls the API through a fault proxy that makes one user's API calls fail on demand. A
fault follows the subject of the request's Huron token, the username:

```bash
curl -X POST http://127.0.0.1:8197/__test/faults -H 'content-type: application/json' \
  -d '{"subject":"oscar","mode":"unavailable"}'
```

`mode` is `unavailable` (503), `unauthorized` (401: the web ends the session), `error500` (500,
with a request id the error page shows), `reset` (the connection drops), `hang` (no answer comes,
until the web's timeout) or `null` (clear). An optional `path`, such as
`"/api/v1/catalogs/heliophysics/search"`, limits a fault to requests whose path starts with it. A
subject holds one fault per path, the longest matching path applies, and `"mode": null` with a
`path` clears that one alone. `GET /__test/faults` lists the faults in force.

The demo listens on 8199 (the fake IdP and its group directory: the issuer), 8197 (the fault
proxy, the web's API URL), 8198 (the API) and 5173 (the web). Move them with
`HURON_E2E_IDP_PORT`, `HURON_E2E_PROXY_PORT`, `HURON_E2E_API_PORT` and `HURON_DEMO_WEB_PORT`. The
demo starts nothing while another process holds one of its ports; it names the port and its
variable instead.

## Against the development stack: `make up`

This is the real sign-in: PostgreSQL and Keycloak's `company` realm in Docker, the API and the
web on the host. Unlike `make app`, which binds 127.0.0.1 only, this stack's PostgreSQL (user
and password `huron`), Keycloak (admin console `admin` / `admin`) and group directory listen on
every network interface: run it on a machine and network you trust. In the repository root, in
two terminals:

```bash
# Terminal 1: PostgreSQL and Keycloak, the migrations, then the group directory (keep it running)
make up
make migrate
uv run python scripts/devgroups.py scripts/dev-groups.yaml 8082

# Terminal 2: the API on http://127.0.0.1:8080 (keep it running)
make api
```

Then, in a third terminal in `web/`, after the [setup](#setup):

```bash
cp .env.example .env
npm run build
npm run start
```

Open exactly http://localhost:3000, the `ORIGIN` in `.env`: every sign-in comes back to
`http://localhost:3000/auth/callback`, and one started on another address ends with "That sign-in
expired or was already used". Choose **Sign in with your company account** and sign in on
Keycloak's form as `user` / `user`, `admin` / `admin`, or one of the accounts in the root
[README](../README.md#accounts). `npm run dev` reads the same `.env` and serves on
http://localhost:5173 with live reload.

`.env.example` holds the settings for this stack, among them the development secret of the
realm's confidential `huron-web` client, `HURON_WEB_OIDC_CLIENT_SECRET=huron-web-dev-only-secret`.
Without it Keycloak refuses the web's token request, and sign-in ends with "The company sign-in
didn't complete." (`/login?error=idp_error`). The issuer is `http://127.0.0.1:8081/realms/company`
in `.env` and in `dev.env` alike; use `127.0.0.1` for Keycloak, never `localhost`.

The stack's database starts empty, so the web has no organization to show. To browse the demo
data of `make app` instead, load it once, with the API running, from the repository root:

```bash
HURON_SEED_API_URL=http://127.0.0.1:8080 HURON_SEED_ISSUER=http://127.0.0.1:8081/realms/company \
  HURON_SEED_CLIENT_ID=huron-cli HURON_SEED_FIXTURE_DIR=web/e2e/support node docker/seed/run.mjs
```

The data stays in the volume `huron_postgres-data`, and running the seed again changes nothing.

A `make up` Keycloak whose volume predates the `huron-web` client answers the sign-in with "Client
not found"; recreate only its volume, as the root README's
[troubleshooting](../README.md#troubleshooting) describes. `make down` stops PostgreSQL and
Keycloak.

## Everything in Docker: `make app`

`make app`, in the repository root, builds and starts the whole application in Docker:
PostgreSQL, the API, the group directory, Keycloak, this web app on http://localhost:3000 and the
demo data. The CLI on the host signs in to the same Keycloak, with the device or the loopback
flow, and writes through the same API, so what it creates shows here at once.
[Run everything in Docker](../README.md#run-everything-in-docker) in the root README lists the
accounts and covers the CLI's setup, stopping, resetting and troubleshooting. `make up` and
`make app` use the same ports, so run one at a time.

## The gate and the end-to-end tests

Run from `web/`, after the [setup](#setup); each must pass, and `npm run check` must report 0
errors and 0 warnings:

```bash
npm run check
npm test
npm run lint
npm run build
npm run test:e2e
```

The end-to-end tests run the whole stack on this machine, as the demo does. `npm run test:e2e`
builds, then starts the fake IdP and the fault proxy (8199, 8197), the API on the memory store
(8198) and the built web server (`node build/index.js` at http://localhost:4173, which reads no
`.env`), seeds the fixture once, and runs the tests in Chromium. Every process gets every setting
explicitly, so nothing leaks in from `.env` or the shell. The ports are the demo's, so the two
cannot run at the same time; move them with the variables above and `HURON_E2E_WEB_PORT`. The
pieces live in `e2e/support/`:

- `fake-idp.mjs`: the stand-in company IdP and group directory, one sign-in button per fixture
  user, and the fault proxy.
- `fixture.mjs`: the users, groups, organizations, catalogs, namespaces, collections and schema
  the tests assert on; `seed.mjs` creates them through the real API, and `make app` seeds the
  same fixture. One collection, `space-weather.alerts.storm-count-2024`, has a schema override
  that no longer fits its catalog's schema, so it stays incomplete: the case of an incompatible
  override.
- `stack.mjs`: the ports and the environment of every process.
- `harness.ts`: what tests use, such as `signIn(page, user)`, `faults('oscar', mode)` and
  `ApiSession`.

Every test imports `test` from `e2e/support/harness.ts`. Its automatic fixture signs out each
session the test signed in to: a user holds at most 10 web sessions, and the 11th sign-in ends the
oldest, so a test that outlived 10 later sign-ins of its user lost its session halfway. Faults
follow a user, not a test, so only tests in `e2e/faults/` inject them, always for `oscar`, and that
Playwright project runs one test at a time. `paula` signs in only for the long walks of
`e2e/layout.test.ts`.

## In production

- **`ORIGIN`** must be the exact public origin browsers use, such as
  `https://huron-web.apps.example.org`. Sign-in returns to `<ORIGIN>/auth/callback` and sign-out
  to `<ORIGIN>/login?status=signed-out`, so the IdP client lists exactly those; on https every
  cookie is `Secure` and carries the `__Host-` prefix. adapter-node listens on `HOST` and `PORT`
  (`web/Containerfile`: 0.0.0.0 and 3000).
- **Secrets.** `HURON_WEB_OIDC_CLIENT_SECRET` is the only one: keep it in a secret store, never in
  the image or a config map. The web has no other key to configure; it seals sign-ins in progress
  with a random key it makes for itself.
- **One replica, or sticky sessions.** Sessions live in the server's memory: a restart signs
  everyone out, and a replica that did not create a session treats it as expired. Sign-ins in
  progress fail the same way.
- A session ends with its Huron token (30 seconds before it expires); there is no refresh.
- `POST /logout` answers 403 unless the request's `Origin` is the web's own origin (`ORIGIN`):
  SvelteKit checks the origin of form bodies only, and a bodiless POST from another origin of the
  same site carries the session cookie too. A proxy in front of the web must pass `Origin`
  through.
- **Compression.** adapter-node compresses only the prebuilt static assets; pages and
  `__data.json` leave uncompressed. Compress `text/html` and `application/json` at the route,
  ingress or reverse proxy. No page holds a secret for a compression attack to extract.
- **Memory.** One process holds every session and reads API answers of up to 64 MiB each
  (`MAX_ANSWER_BYTES`), and list answers carry each collection's metadata whole. Leave the
  container room above its working set: an out-of-memory kill signs everyone out.
- **Content Security Policy.** Every page carries the policy of `kit.csp` in `svelte.config.js`:
  `default-src 'self'`, scripts from the web's own origin and inline scripts only with SvelteKit's
  nonce, inline styles, `data:` images, no plugins and no framing. It sets no `form-action`,
  because Chromium would apply it to the sign-out's redirect to the IdP. A proxy that injects
  scripts breaks the pages.
- **Logs** go to stderr: `huron-web API call failed` with its reference (the API's request id when
  the API sent one; the 500 page shows it), status, code, title and path;
  `huron-web request failed` for other server errors, with their reference;
  `huron-web sign-in failed: <code>: <reason>`, a warning, or an error for a configuration
  problem; and `huron-web configuration: <variable> …`. They hold no tokens, authorization codes,
  cookies, secrets, query strings or the API's free text (`detail`, `context`). One line is the
  exception: an error sign-in does not expect, such as a bug, logs
  `huron-web sign-in failed unexpectedly` with the error as Node prints it, its message and
  stack, which are free text and may quote anything; the warning
  `huron-web sign-in failed: service_unavailable: unexpected failure` comes next. SvelteKit's own
  4xx answers, such as a 404 for a path no route matches, are neither logged nor given a
  reference.
- `/healthz` answers `{"status":"ok"}` without a session, for probes.
