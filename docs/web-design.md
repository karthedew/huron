# Huron web on the FastAPI backend — design spec (v2, after independent review)

This document is the design of the web app in `web/`: a read-only client of the Huron API whose
server signs people in with the company identity provider and lets them switch organizations,
browse catalogs, namespaces and collections, and search a catalog or an organization. It is
binding for `web/` together with its dated "Accepted amendment" notes, each of which refines or
replaces the text it follows; a later amendment wins over an earlier one. Sections 10 and 11
record how the rewrite was built (what it removed, and its slices S1 to S6 in order); they bind no
new work.

The rules agents follow in `web/` are in the [root AGENTS.md](../AGENTS.md#frontend-web), and how
to run the app is in [web/README.md](../web/README.md). The web app's own paths (`src/lib/…`,
`src/routes/…`, `e2e/…`) are relative to `web/`; `src/huron/…`, `docs/…` and `tests/…` are
relative to the repository root.

The web app is `web/` (built on branch `cli`): SvelteKit 2.70.3, Svelte 5.56
(runes), Tailwind 4.3, Vite 6.4, Vitest 3.2, Playwright 1.62.1 (Chromium only is installed), adapter-node
5.5.7, Node 26, `@lucide/svelte` 1.37. Backend: the FastAPI service in `src/huron/applications/api`;
its contract is `docs/openapi.json` (kept identical to the code by
`tests/unit/api/test_openapi_snapshot.py`) — where `IMPLEMENTATION_PLAN.md` section 8 differs, the code
and `docs/openapi.json` win (identifier route param is `name`; labels are `key=value` with `key:value`
fallback; the exchange returns no roles).

Already done (by the lead, before this spec's implementation): the API's `CompanyTokenVerifier` now
ignores JWKS entries that are not signing keys or cannot be loaded (`src/huron/core/security/broker/
company.py`, test in `tests/unit/security/test_exchange.py`). Before the fix, a Keycloak JWKS (which
lists an `RSA-OAEP` encryption key) made every exchange answer 500. No other backend change is planned.

## 1. Goal

Replace the web's Polaris/Icechunk/local-account integration with a read-only client of the Huron API:

1. Sign in with the company OIDC provider (same identity as the CLI). The web server exchanges the ID
   token at `POST /api/v1/auth/exchange` for a Huron token that only the web server holds.
2. Switch between the organizations the user can see.
3. Browse an organization's catalogs, each catalog's recursive namespaces and their collections; open
   a collection to see its metadata (rendered against its resolved schema), its state and validation
   problems, recorded files, commits, audit activity and schema.
4. Search a catalog, or an organization (fan-out over its catalogs), from the header and from search
   pages.

## 2. Non-goals

- **No writes from the web.** The service mounts nothing (plan D-18/D-19); the CLI creates
  directories, ACLs and `metadata.json` sidecars on a machine that mounts the share. The UI explains
  this and shows the exact CLI command where the signed-in user could act (section 4.6).
- No Polaris, Icechunk, local password accounts, signup, admin console, schema-registry browsing pages,
  organization-grant panels or logout confirmation dialog.
- No new npm dependencies and no downloads of any kind (blocked here): no `npm install <new>`, no
  `npx --yes`, no `npx playwright install`, no Docker pulls. `@sveltejs/mcp` (the Svelte autofixer) is
  not installed: report it as not run. Only Chromium exists for Playwright.
- No CI job and no OpenShift manifests for the web (record as follow-ups). No backend change beyond the
  JWKS fix above. No change to `docs/openapi.json`.

## 3. Architecture

Backend-for-frontend: the browser talks only to the SvelteKit server; the SvelteKit server holds
sessions in memory and calls the API server-side with `Authorization: Bearer <huron token>`.

```text
browser ──opaque session cookie──▶ SvelteKit server ──Bearer huron token──▶ Huron API /api/v1
                                     │   ▲ id_token ─▶ POST /api/v1/auth/exchange
                     OIDC code+PKCE  ▼   │
                                  company IdP (Keycloak `company` realm in dev)
```

### 3.1 Configuration (`src/lib/server/config.ts`)

A pure `parseConfig(env: Record<string, string | undefined>, { dev })` (unit-tested) plus a memoized
accessor over `$env/dynamic/private` with a reset hook for tests. An empty string counts as unset.
Configuration is read lazily at first use (the build imports server modules; nothing may throw at import).

| Variable | Required | Meaning |
| --- | --- | --- |
| `ORIGIN` | outside dev | Public http(s) origin without path, e.g. `https://huron-web.apps.example.org`. Derives the redirect URI `<ORIGIN>/auth/callback`, the post-logout URI `<ORIGIN>/login?status=signed-out`, cookie `Secure` and `__Host-` naming. In `vite dev`, `event.url.origin` is used instead. |
| `HURON_API_URL` | yes | API origin, e.g. `http://127.0.0.1:8080` (no path; the client appends `/api/v1`). |
| `HURON_WEB_OIDC_ISSUER` | yes | Company IdP issuer (trailing slash stripped). Must equal the API's `HURON_COMPANY_ISSUER` byte for byte, and the browser-facing issuer (Keycloak derives `iss` from the request host; in host-run dev both are `http://127.0.0.1:8081/realms/company`). |
| `HURON_WEB_OIDC_CLIENT_ID` | yes | The web's client, e.g. `huron-web`. Its ID tokens must carry the API's `HURON_COMPANY_AUDIENCE` in `aud` (Keycloak: an audience mapper on the ID token only). IdPs without audience mappers: set this to the API audience's client and register the web's redirect URI there. |
| `HURON_WEB_OIDC_CLIENT_SECRET` | no | Confidential client (`client_secret_basic`); without it the web is a public client. PKCE S256 always. |
| `HURON_WEB_OIDC_SCOPES` | no | Default `openid profile email`. |
| `HURON_WEB_OIDC_LOGOUT` | no | `true` (default): after local logout, redirect to the IdP's `end_session_endpoint` when advertised; `false`: local only. |
| `HURON_WEB_MOUNT_PREFIX` | no | Default `/projects/huron` (the CLI's default). Share paths are shown as `<prefix>/<relative path>`. |
| `HURON_WEB_API_TIMEOUT_MS` | no | Default `10000` for API reads and IdP calls. The exchange uses `max(35000, 3×timeout)` so the API's own dependency errors (`GROUP_DIRECTORY_UNAVAILABLE`, `DEPENDENCY_UNAVAILABLE`) arrive before the web gives up. |

A `ConfigError` names the variable (never its value). Hooks turn it into a 500 whose message names the
variable; `/login` shows `error=config`.

### 3.2 Cookies (`src/lib/server/cookies.ts`)

One helper decides names and options for every set and delete: `{ path: '/', httpOnly, sameSite: 'lax',
secure: origin.protocol === 'https:' }` (always explicit — SvelteKit's default `secure` is wrong for
`http://127.0.0.1`). On https every cookie name gets the `__Host-` prefix.

| Cookie | Written by | Content |
| --- | --- | --- |
| `huron_session` | server | Opaque session id (32 random bytes, base64url), HttpOnly, `Max-Age` until the session expires. |
| `huron_oidc_<first 8 chars of state>` | server | Sealed sign-in transaction (3.4), HttpOnly, `Max-Age=600`; at most 3 at a time (the oldest is deleted). |
| `huron_org` | **browser** (`afterNavigate`) | Remembered organization name, not HttpOnly, `Max-Age` one year. Never set from a load (hover/tap preloads would change it). The server validates it with the segment matcher and against the visible organizations before use. |

### 3.3 Sessions (`src/lib/server/sessions.ts`)

- Store factory with an in-memory implementation; the production accessor anchors one instance on
  `globalThis` (survives Vite HMR). Record: `{ id, huronToken, expiresAt, subject, name, groups,
  createdAt }` — all from `ExchangeOut`, never from the unverified ID token. No ID token is kept.
- **Credentials never leave the module**: hooks put only `locals.user = { subject, name, groups,
  expiresAt, signedInAt }` (plain data) in `App.Locals`. The token is reachable only through
  `api(event)` (3.6), which looks the session up by cookie. Nothing returns the record from a load.
- Expiry: absolute, at the Huron token's `expires_at` minus 30 s. No refresh (the API issues none).
- Caps: at most 10 sessions per subject (that subject's oldest evicted); a global cap of 10 000 — when
  full after sweeping expired records, a new sign-in fails with `service_unavailable` (never evicts
  other users). The sweep timer is `unref()`ed.
- Sign-in deletes the session named by the incoming cookie before creating the new one (new id every
  time). Logout deletes the record and the cookie.
- Limitation to document: sessions are per process and die on restart; run one replica or enable
  sticky sessions.

### 3.4 Sign-in, callback, logout (`src/lib/server/oidc.ts`, `src/lib/server/return-to.ts`)

- **Discovery**: `<issuer>/.well-known/openid-configuration`, cached 1 h; failures cached 5 s. Its
  `issuer` must equal the configured issuer exactly, else `ConfigError`-style failure logged clearly
  (`error=config`). URLs built with `new URL()` + `searchParams.set` (endpoints may carry a query).
- **Transaction** (stateless): `{ state, nonce, codeVerifier, returnTo, exp }` sealed with AES-256-GCM
  using a random key generated at process start (no configuration). state and nonce: 32 random bytes
  base64url; PKCE verifier: 32 random bytes base64url (43 chars), challenge base64url(SHA-256).
  `returnTo` is canonicalized before sealing.
- `/login` (public page, no shell): heading, short copy (section 4.7), one primary link **Sign in with
  your company account** → `/auth/login?returnTo=…`. Status line for known codes only, never echoing
  query text: `status=signed-out|expired`; `error=state_mismatch|idp_error|idp_unavailable|
  token_rejected|groups_unavailable|service_unavailable|config`. Every error shows **Try again**. A
  signed-in visitor is redirected to `returnTo`.
- `GET /auth/login`: create and seal the transaction, set its cookie, `303` to the authorization
  endpoint with `response_type=code, client_id, redirect_uri, scope, state, nonce, code_challenge,
  code_challenge_method=S256`. Discovery/network failure → `/login?error=idp_unavailable`.
- `GET /auth/callback`: pick the transaction cookie by the `state` query parameter's first 8 chars;
  open it (bad seal, expired, missing → if the browser already has a valid session redirect to its
  `returnTo` or `/`, else `state_mismatch`); compare state with `timingSafeEqual` after a length check;
  delete that cookie; IdP `error` parameter → `idp_error`; POST the token endpoint
  (`grant_type=authorization_code, code, redirect_uri, code_verifier`, client auth; network/5xx/timeout →
  `idp_unavailable`, 4xx → `idp_error`); require `id_token`; discard access and refresh tokens; decode
  the payload (the API verifies the signature) and check `iss` = discovery issuer, `aud` contains the
  client id, `azp` (when present) = client id, `nonce` matches, `exp` in the future (any failure →
  `token_rejected`); exchange (401 → `token_rejected`; 503 `GROUP_DIRECTORY_UNAVAILABLE` →
  `groups_unavailable`; other 503/5xx/network → `service_unavailable`); create the session; `303` to
  `returnTo` (default `/`).
- `POST /logout` (a plain form; SvelteKit's origin check covers CSRF in builds): delete session and
  cookie; when logout redirect is enabled and discovery is available and advertises
  `end_session_endpoint`, `303` to it with `client_id` and `post_logout_redirect_uri` only (**never**
  `id_token_hint`: the ID token must not appear in a URL); else `303 /login?status=signed-out`.
  - **Accepted amendment (2026-10-29, S2 review).** SvelteKit's origin check covers less than the
    sentence above claims: it runs in builds only and only for form content types (the HTML ones,
    `application/x-www-form-urlencoded`, `multipart/form-data` and `text/plain`, plus SvelteKit's
    own binary form type; `@sveltejs/kit` 2.70.3 `src/runtime/server/respond.js`), so a bodiless or
    non-form POST passes it, and from another origin of the same site (a `no-cors` fetch, a beacon)
    such a POST carries the Lax session cookie. `POST /logout` therefore compares `Origin` with the
    public origin itself and answers `403` to a foreign, opaque (`null`) or missing `Origin` before
    it touches the session. Consequence for deployment: a proxy in front of the web must pass
    `Origin` through. Covered by `src/routes/auth/auth.server.test.ts` ("refuse a logout from …")
    and `e2e/security.test.ts`. S5 records this in the AGENTS.md "Frontend: `web/`" section.
- **returnTo** (`return-to.ts`): reject unless it starts with a single `/`, has no `\` and no control
  characters, and is at most 1024 characters; then `u = new URL(value, origin)`, require
  `u.origin === origin` **and that `u.pathname` does not start with `//`** (dot segments normalize
  `/..//evil.com` and `/%2e//evil.com` to `//evil.com`, which a `Location` header reads as another
  host), reject when `u.pathname` is `/login`, `/logout` or starts with `/auth/`, and
  return `u.pathname + u.search` (ASCII, percent-encoded, fragment dropped, exactly one leading `/`).
  Default `/`. `/auth/callback` checks the sealed `returnTo` again before redirecting to it. Tests
  cover `//evil.com`, `/\evil.com`, `/\t/evil.com`, encoded slashes, `/./auth/callback`,
  `/x/../auth/login`, `/%2e%2e/auth/login`, `/..//evil.com`, `/.//evil.com`, `/%2e//evil.com`,
  `/x/..//evil.com`, non-ASCII, length, and that every result stays relative to any origin.

### 3.5 Hooks (`src/hooks.server.ts`)

- Resolve `locals.user` from the session cookie. A cookie whose session is gone counts as expired.
- Public paths: `/login`, `/auth/login`, `/auth/callback`, `/logout`, `/healthz`. For any other path
  without a user: programmatic requests (header `x-huron-fetch: 1`, sent only by the explorer's tree
  fetch) get `401 application/json {"code":"UNAUTHENTICATED"}`; everything else gets
  `throw redirect(303, '/login?returnTo=…' + (cookie present ? '&status=expired' : ''))` (SvelteKit
  turns that into a JSON redirect for `__data.json`).
- Headers, applied in `try/finally` by mutating the resolved response (also for redirects and errors
  thrown by loads and endpoints): `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: same-origin`, and `Cache-Control: private, no-store` for every authenticated
  response. Loads never call `setHeaders` for `cache-control`. Accepted deviation: answers SvelteKit
  builds outside `resolve()` carry none of these headers — the hook's own login redirect (thrown, so
  SvelteKit formats it for data and action requests and applies the session-cookie deletion; a
  returned 30x is replaced by SvelteKit's JSON redirect for `__data.json`, dropping headers and
  cookies) and fatal errors such as the `ConfigError` 500 (SvelteKit's static page). They are
  bodiless same-origin 303s or a page without scripts or actions.
- `handleError`: log `{ id, status, path, message, cause }` where `cause` is the error's class name
  only (an unexpected error's message is free text that may quote its input; the stack is logged in
  dev only) — never tokens, codes, verifiers, cookies or secrets; return
  `{ message: <the message argument>, id }`. `App.Error` = `{ message; id?; code? }`.
  - **Accepted amendment (2026-10-29, S2 review).** The logging and the `id` above apply to
    `status >= 500`. SvelteKit also calls `handleError` for its own 4xx errors (a 404 for a path no
    route matches or a form action that does not exist, a 405 for a form POST to a page without
    actions, a 415 for a non-form action body, a 400 for a malformed URI); for those the hook
    returns `{ message }` only, with no log entry and no `id`: they are no failure of this server,
    and §4.5 gives a 404 no reference. Errors thrown with `error()` never reach `handleError`: the
    guard logs API failures itself, and its 500 carries the API's request id. Both error pages show
    "Reference <id>" only when `page.error.id` is present. Covered by `src/hooks.server.test.ts`
    ("neither logs nor references its own %i"). S5 records this in the AGENTS.md "Frontend: `web/`"
    section.

### 3.6 API client (`src/lib/server/huron-api.ts`, `src/lib/server/guard.ts`)

- `class HuronApi` with `{ baseUrl, token, fetch = globalThis.fetch, timeoutMs }` (token in a `#private`
  field; the class instance would make devalue throw if ever returned from a load — fail closed). Uses
  the global fetch with `credentials: 'omit'` and `redirect: 'error'` (never `event.fetch`, which
  forwards browser cookies to same-site hosts). Every path segment is checked (non-empty, not `.`/`..`,
  no `/`, `\` or `%` — the API server decodes `%2F` before routing) and `encodeURIComponent`ed; query arrays repeat the key (`label=a=b&label=c=d`,
  `state=active&state=draft`). Idempotent GETs retry once on a connection reset. Timeouts use
  `AbortSignal.timeout`.
- Methods: `whoami`, `organizations(page)`, `organization(name)`, `catalogs({ organization?, ...page })`,
  `catalog(name)`, `catalogSchema(name)`, `catalogGrants(name)`, `catalogLog(name, page)`,
  `namespaces(catalog, parent, page)`, `namespace(catalog, path)`,
  `namespaceCollections(catalog, path, page)`, `collectionByIdentifier(catalog, rest)`,
  `collection(id)`, `collectionSchema(id)`, `collectionSidecar(id)` (text), `files(id, page)`,
  `commits(id, page)`, `collectionLog(id, page)`, `search(catalog, { q?, labels?, states?, cursor?,
  limit? })`, `schema(id)` (only to name schema ids in activity rows). `page = { cursor?, limit? }`.
  Plus a standalone `exchange(companyToken)`.
- `class HuronApiError extends Error { status; code; title; detail; context; requestId? }` from
  `application/problem+json` (`requestId` = `context.request_id`); non-problem answers → `code: 'HTTP'`;
  network errors/timeouts → `status: 503, code: 'API_UNREACHABLE'`.
- `api(event)` (guard.ts): returns a per-request memoized client (`WeakMap` keyed by `event.locals`) that
  also memoizes GETs by URL within the request; throws the login redirect without a session.
- `fail(event, error)` maps errors with **fixed copy** (never API `detail`/`context`):
  401 → delete session, `303 /login?status=expired&returnTo=<current>`; 403 → `error(403)`;
  404 → `error(404)`; 400 `INVALID_CURSOR`, or a 500 on a request carrying a cursor → `303` to the same
  URL without cursor parameters plus `notice=page_expired`; 422 → `error(400)` unless the caller handles
  it (search shows it inline); 500 → `error(500)` with the API's request id; 503/`API_UNREACHABLE` →
  `error(503)`. Child loads never call `parent()`; they use `api(event)` and the memo.
- **Accepted amendment (2026-10-30, S3a review).** No load returns API JSON whose keys users choose:
  collection `metadata` (labels included), `schema_override`, schema documents. SvelteKit serializes
  page data with devalue (`uneval` into the page, `stringify` for `__data.json`), which throws on an
  object with its own `__proto__` key, and `JSON.parse` keeps such a key from an API answer: one
  contributor's label `__proto__`, or one published schema property of that name, would otherwise
  answer 500 to every viewer. Loads return view models of plain values built on the server (the
  namespace page's `CollectionRow` from `src/lib/collections.ts`; the schema tab's `SchemaView` from
  `src/lib/schema-view.ts`, which also carries the document as JSON text) and keep the rest of the
  metadata on the server. Audit `detail` keys are fixed by the core, so activity entries may pass.
  Covered by the loads' tests ("returns page data SvelteKit can send, …") through
  `src/lib/testing/page-data.ts`. S3b (metadata, problems, labels, schema override) and S4 (results,
  label chips) follow the same rule. S5 records this in the AGENTS.md "Frontend: `web/`" section.
- **Accepted amendment (2026-10-31, S6 review).** Reading API answers.
  - Every answer is parsed with plain `JSON.parse` (`parseJson` in `src/lib/server/json.ts`). Only
    the reads whose digits a page shows keep the digits of integers past 2^53 (`parseExactly`,
    through `HuronApi`'s `exact` option, memoized apart from plain reads): `catalogSchema`,
    `collectionSchema`, and on a collection's Schema tab a second read of the collection when its
    plainly parsed override may hold such an integer (`exactOverride` in
    `src/lib/server/collection.ts`). Before, any run of 16 digits sent a whole answer through the
    reviver, and an ordinary float writes one (1/3 is 0.3333333333333333): the numbers of one
    collection in a namespace of 50 large ones held the web's single process for 8 s on each view
    of the namespace, of every collection page in it and of a matching search, and concurrent
    requests ran into their API timeout. Metadata holds no integer past 2^53 (the API
    canonicalizes it with RFC 8785), so lists, searches and collections lose nothing.
  - An answer is read as a stream, at most 64 MiB of it (`MAX_ANSWER_BYTES`): a longer one, or one
    that declares a longer length, fails as a `502` (logged; a page shows its 500) without being
    read further. Lists carry each collection whole (metadata of up to a mebibyte, problems and a
    schema override of any size), and the web's one process also holds every session; an endless
    answer filled its heap. 64 MiB is above any first page of 50 collections whose metadata keeps
    to the API's limit.
  Covered by `src/lib/server/huron-api.test.ts` ("parses lists, searches and collections without a
  reviver, whatever digits they hold", "keeps the digits of integers past 2^53 in schema documents
  and exact reads", "stops reading an answer once it holds more than its ceiling, …", "refuses an
  answer whose declared length is over its ceiling …"), `src/lib/server/json.test.ts` and the
  collection Schema tab's load test ("reads the collection only once where its override holds no
  integer a parse rounds"). The API offers no smaller listing (§9 follow-ups). S5 records this in
  the AGENTS.md "Frontend: `web/`" section.

### 3.7 Content Security Policy

`kit.csp` in `svelte.config.js`: `mode: 'auto'`, directives `default-src 'self'`, `script-src 'self'`
(SvelteKit adds nonces/hashes), `style-src 'self' 'unsafe-inline'`, `img-src 'self' data:`,
`font-src 'self'`, `connect-src 'self'`, `object-src 'none'`, `base-uri 'self'`,
`frame-ancestors 'none'`. **No `form-action`** (Chromium applies it to the logout form's redirect to the
IdP; record as follow-up). The theme script in `app.html` gets `nonce="%sveltekit.nonce%"`. Verify
`npm run dev`, the build and the e2e sign-in all work under it.

### 3.8 Types (`src/lib/api/`)

- `web/scripts/generate-api-types.mjs` (Node, no dependencies, fully JSDoc-typed, exports
  `generate(document): string` and runs as a CLI) reads `../docs/openapi.json` and writes
  `src/lib/api/openapi.ts`: one export per `components.schemas` entry (pydantic names), `Page_X_` as
  `Page<X>`, `anyOf [T, null]` → `T | null`, optional vs required from `required`,
  `additionalProperties`/untyped objects → `Record<string, unknown>`, `$ref` resolution, string enums as
  unions, `format` noted in a doc comment; deterministic output with a "generated — do not edit" header.
  Any keyword it neither translates nor knows as a pure annotation/constraint (`oneOf`, `allOf`, `not`,
  `prefixItems`, …), and a `$ref` next to type keywords, fails the generation instead of becoming
  `unknown`.
  `npm run generate:api` regenerates; a Vitest test regenerates in memory and fails on drift, and unit-
  tests the generator on small documents. `web/.prettierignore` lists `src/lib/api/openapi.ts`.
- `src/lib/api/types.ts`: friendly aliases (`Organization`, `Catalog`, `Namespace`, `Collection`,
  `CollectionState = State`, `FileRecord`, `Commit`, `AuditEntry`, `SchemaEntry`, `SchemaRef`,
  `EffectiveGroups`, `WhoAmI`, `RoleGrant`, `Page<T>`), hand-written `Problem` (the API's problem
  document is not in the OpenAPI components) and `JsonSchemaDocument`, and UI unions for role scope
  (`platform|organization|catalog`), role (`platform_admin|org_admin|catalog_admin|contributor|reader`)
  and audit action (closed vocabulary in `src/huron/core/lake/audit/models.py`). `HTTPValidationError`
  is generated but not re-exported (never returned). Routes/components import domain types only from
  `$api/types`.

## 4. Routes, layouts and pages

Route tree (exact). `[org=segment]`, `[catalog=segment]`, `[path=dotted]`, `[identifier=dotted]`,
`[id=uuid]` use matchers in `src/params/` (`segment`: `^[a-z0-9][a-z0-9_-]{0,62}$`; `dotted`: segments
joined by `.`, ≤ 255 bytes; `uuid`: canonical lowercase/uppercase hex UUID). Never create unmatched twins
(`[catalog]` next to `[catalog=segment]`).

```text
src/routes/
  +layout.svelte          load-free: imports app.css, renders children
  +error.svelte           friendly error without the shell (errors outside (app))
  login/                  +page.server.ts +page.svelte (public, no shell)
  auth/login/+server.ts   auth/callback/+server.ts   logout/+server.ts   healthz/+server.ts
  (app)/
    +layout.server.ts     user, organizations (limit 500), roles (whoami); never throws except the
                          401→login redirect: API failures return organizationsUnavailable/rolesUnavailable
    +layout.svelte        the shell (4.1)
    +error.svelte         friendly errors inside the shell
    +page.server.ts/.svelte                  /  → remembered org, else the only org, else the list/empty state
    orgs/+page.server.ts/.svelte             all visible organizations (paged)
    orgs/[org=segment]/+layout.server.ts/.svelte   org header + sub-nav (Catalogs · Search)
    orgs/[org=segment]/+page.server.ts/.svelte     catalogs of the org (paged)
    orgs/[org=segment]/search/…                    organization search (5)
    catalogs/[catalog=segment]/+layout.server.ts   catalog, the org's catalogs (≤100), root tree level
    catalogs/[catalog=segment]/+layout.svelte      explorer + breadcrumb + content
    catalogs/[catalog=segment]/(overview)/+layout.svelte   catalog header + sub-nav, only on these 5:
    catalogs/[catalog=segment]/(overview)/+page.*          Overview (root namespaces)
    catalogs/[catalog=segment]/(overview)/search/…         catalog search (5)
    catalogs/[catalog=segment]/(overview)/access/…         effective groups per role
    catalogs/[catalog=segment]/(overview)/activity/…       catalog audit log
    catalogs/[catalog=segment]/(overview)/schema/…         resolved catalog schema
    catalogs/[catalog=segment]/namespaces/[path=dotted]/+page.*      namespace
    catalogs/[catalog=segment]/collections/[identifier=dotted]/+layout.server.ts/.svelte  header + sub-nav
    catalogs/[catalog=segment]/collections/[identifier=dotted]/+page.*      Overview
    …/collections/[identifier=dotted]/files/  commits/  activity/  schema/
    …/collections/[identifier=dotted]/metadata.json/+server.ts
    catalogs/[catalog=segment]/tree/+server.ts     explorer JSON (x-huron-fetch)
    collections/[id=uuid]/+page.server.ts          303 to the identifier URL (activity links)
    search/+page.server.ts/.svelte                 header-search fallback chooser (5)
    account/+page.server.ts/.svelte
src/error.html            branded static fallback (%sveltekit.status%, %sveltekit.error.message%)
```

- **Accepted amendment (2026-10-29, S3a review).** The tree gains
  `catalogs/[catalog=segment]/+error.svelte`. A failure below a catalog the user can see (a namespace
  or collection that does not exist, a tab whose read failed) renders inside the catalog layout:
  its breadcrumbs stop at Org › Catalog with no current crumb, and the explorer marks the catalog
  and no node below it (the address may name nothing that exists). `page.data.organization` is then
  the catalog's organization, so the shell shows it and §4.5's "Back to <org>" names it, also for
  a user with several organizations and none remembered. A failure of the catalog layout itself (a
  concealed or missing catalog) still renders `(app)/+error.svelte`. Both pages render one shared
  component (`ShellError.svelte`). Covered by `src/routes/error.svelte.test.ts`, the catalog
  layout's component test and `e2e/catalogs.test.ts` ("keeps its place and its organization …").

Rules: every tab/sub-nav link is absolute (built with `resolve()`); `app.html` uses
`data-sveltekit-preload-data="tap"`. **Current organization**: `page.data.organization` (a name or
`null`) is the only source for the shell. The org layout and catalog layout return it; every other page
returns the remembered organization (validated segment from the `huron_org` cookie). The shell checks it
against the visible list. `(app)/+layout.svelte` writes `huron_org` in `afterNavigate` when
`page.data.organization` is a visible organization.

- **Accepted amendment (2026-10-31, S6 review).** The rules, as built.
  - Links are built with `resolve()`, never written by hand relative to a tab. During server
    rendering `resolve()` gives page-relative hrefs (`../orgs/helio`), each of which leads to the
    intended path, and hydration makes them absolute; `kit.paths.relative` keeps its default.
  - On a page whose data names no organization, which only `(app)/+error.svelte` renders, the shell
    shows the remembered organization: the one it last wrote to `huron_org`, else the cookie as the
    `(app)` layout read and validated it (`rememberedOrganization`), in both cases checked against
    the visible list. Without scripts the cookie is never written, so the shell shows what the
    server read, or "Choose organization". Covered by `e2e/home.test.ts` ("a page that fails keeps
    the organization the user was in") and `src/routes/(app)/layout.svelte.test.ts` ("keeps the
    organization it last remembered for a later error page").
  - An in-app address no route matches (`/orgs/Bad_Org`, `/orgs/helio/x`,
    `/catalogs/heliophysics/namespaces/a..b`, `/collections/not-a-uuid`) answers 404 with the root
    error page, without the shell. No `(app)/[...rest]` catch-all: it would read the shell's
    organizations and roles for every mistyped or scanned address, and it would be the kind of
    unmatched twin this section forbids.
  S5 records this in the AGENTS.md "Frontend: `web/`" section.

| Page | Content |
| --- | --- |
| `/` | Redirect to the remembered org if visible, else the only visible org; else the organization list; with none, the empty state (4.5). |
| `/orgs` | Cards: `display_name \|\| name` (name as secondary only when different), description, "N catalogs", paged. |
| `/orgs/[org]` | Org header (display name, name, description); catalogs list: display name, name, description, schema `name vN` (links to the catalog's Schema tab), "N namespaces in total", paged; empty state with the org-admin hint (4.6). |
| `/catalogs/[catalog]` (Overview) | Header: display name, name, organization link, description, schema link, "N namespaces in total". Root namespaces (rows with *Holds collections* / *Structure only*, child and collection counts), paged; admin hint for creating namespaces. |
| `…/access` | Effective groups per role (`platform_admin`, `org_admin`, `catalog_admin`, `contributor`, `reader`) with human role names and what each can do; groups the signed-in user belongs to are marked "You"; admin hint `huron catalog grant …` + `huron acl apply …`. |
| `…/activity` | Catalog audit log (4.4), paged by `next_cursor` only. |
| `…/schema` | Resolved schema as a field table (4.3) plus raw JSON in a disclosure. |
| `namespaces/[path]` | Header: name, identifier, badge, counts, share path with copy; child namespaces (`?namespaces_cursor=`) and collections (`?collections_cursor=`) as two-line rows; empty copy depends on `collections_allowed`; hints (4.6). |
| `collections/[identifier]` (Overview) | Header: title (h1), identifier (mono), state badge + explanation (4.3), description. Problems (draft/incomplete) with field titles. Metadata (4.3). Details aside: share path + copy (drafts: "No directory yet"), files "N files", created by/at, updated, activated; *Technical details* disclosure: "Record revision N" (not a data version), id; `metadata.json` link for settled collections; CLI hints (4.6). |
| `…/files` | "N files" (from `file_count`); table (path, size, SHA-256 — short with the full value in a disclosure + copy, recorded at/by) in a scroll region; paged. Drafts and empty: explanatory copy. |
| `…/commits` | Rows: message (or "No message"), actor, host, "+adds / −removes", "revision a → b", time, commit id (last 12 hex + full in title/copy — UUIDv7 prefixes repeat). |
| `…/activity` | Collection audit entries (4.4). |
| `…/schema` | Resolved schema for the collection; schema override shown separately when present. |
| `…/metadata.json` | `+server.ts`: `new Response(body, { headers: { 'content-type': 'application/json', 'content-disposition': 'inline', 'content-security-policy': "default-src 'none'; sandbox" } })` (never the upstream Response). 409/404 → 404 copy. |
| `collections/[id]` | `GET /collections/{id}` → 303 to `/catalogs/<catalog>/collections/<identifier minus catalog>`; 404 copy "Not found, deleted, or you do not have access". |
| `/account` | Name, subject, groups "as of sign-in at <UTC time>" (+ re-sign-in hint), roles as sentences with scope names resolved through the visible organizations and catalogs (`GET /catalogs?limit=500`), session expiry, sign-out button, a short CLI setup block (`huron login`, `huron whoami`) without server URLs. |
| `/healthz` | Public `{"status":"ok"}`. |

- **Accepted amendment (2026-10-30, S3b review).** `collections/[id]` answers the 404 copy ("Not
  found, deleted, or you do not have access.") only when the API answers 403 or 404 for the id. A
  401 still ends the session and redirects to the login (§3.6), and an outage or a server error keeps
  its own page (§4.5): during an outage, "not found" would mislead. The error pages pick their copy
  by status and code (`errorCopy(status, code)` in `src/lib/error-copy.ts`) and never show
  `page.error.message`. Covered by `src/routes/(app)/collections/[id=uuid]/page.server.test.ts` ("says
  a collection it cannot show may have been deleted", "shows an outage as such, not as a missing
  collection") and `e2e/collections.test.ts` ("by id answer 303 to the address by identifier, or say
  the collection may be gone"). S5 records this in the AGENTS.md "Frontend: `web/`" section.

Lists: keyset `Pager` (`<nav aria-label="… pages">`) with **Next page** from `next_cursor` and **First
page** when a cursor is present; empty-page/Next decisions depend only on `next_cursor` (reader activity
pages can be short or empty with a cursor: "No visible entries on this page"). A `notice=page_expired`
shows "That page link expired; showing the first page." Page size 50 (lists), 25 (search).

### 4.1 Shell (`(app)/+layout.svelte`)

Keep today's look (sidebar rail + top bar + mobile bottom nav, `app-*` tokens, Lucide icons, theme toggle,
skip link). Sidebar: **Catalogs** (current org overview, else `/orgs`), **Search** (current scope),
footer **Account** and a one-line read-only note ("Read-only · changes are made with the huron CLI")
replacing "Generic · Iceberg · Icechunk". Top bar: search box (added in the search slice), organization
switcher, theme toggle, account menu (name, subject, Account link, **Log out** = plain POST form, no
dialog). Global loading: a thin top bar after ~200 ms of `navigating`, `aria-busy` on main, polite
visually hidden "Loading…". Mobile bottom nav: Catalogs · Search · Account. Page titles:
`<page> · <context> · Huron`. Skip link targets the page content (explorer comes after content in DOM
order or has its own skip link).

**Organization switcher** (`OrganizationSwitcher.svelte`): `<details bind:open>` closed in
`afterNavigate`; Escape via `<svelte:window onkeydown>` closes and focuses the summary; only one header
menu open at a time; accessible name "Organization: <name>" with visually hidden "switch". Lists visible
organizations (`display_name || name`) with the current one checked, plus **All organizations** (`/orgs`).
Unavailable list → "Organizations unavailable · Try again". Off-org pages show the remembered org or
"Choose organization". Selecting keeps an org-scoped sub-route and its query
(`/orgs/helio/search?q=wind` → `/orgs/geo/search?q=wind`), otherwise goes to `/orgs/<org>`. One org →
static label plus the All link.

- **Accepted amendment (2026-10-30, S4 review).** The shell's search.
  - Navigation: **Search** follows Catalogs in the sidebar, the rail and the bottom navigation. It
    leads to the search of what the page belongs to (`searchScope` in `src/lib/search-links.ts`):
    the catalog of a catalog's page (`page.data.catalog`, which the catalog layout returns), else
    the shell's current organization (the page's, or the remembered visible one), else `/search`.
    It marks the section on the three search pages: `aria-current="page"` where it leads to the
    page shown, `"true"` elsewhere (the chooser, when it leads to the remembered organization's
    search). Catalogs is never current on a search page, the catalog search included. The
    organization's sub-navigation reads **Catalogs · Search**.
  - Search box: a GET form (`role="search"`, "Site search"; `SiteSearch.svelte`) of one field,
    `q`, named after its scope by a visually hidden label ("Search Heliophysics", "Search
    Heliophysics Division", or "Search" where it leads to `/search`; the placeholder repeats it),
    `maxlength` 200. It submits to the scope's search page; with scripts the text is trimmed and an
    empty one leaves the query out (`tidySearchForm`). It sends the text alone: a search's filters
    stay in its page's own form. On a search page it holds that search's text
    (`page.data.search.q`), and it is drawn afresh on every page, so text typed and not sent does
    not follow the user; a change of the fragment alone (the skip link's `#main`) is no other page
    and keeps it. It sits first in the top bar from md on (at most 28rem wide), before the
    switcher; below md it is hidden, and the bottom navigation's Search opens the scoped page.
    `App.PageData` declares `catalog` and `search` for the shell.
  Covered by `src/lib/search-links.test.ts`, `src/lib/design/components/SiteSearch.svelte.test.ts`,
  `src/routes/(app)/layout.svelte.test.ts`, `e2e/site-search.test.ts` and `e2e/shell.test.ts`. S5
  records this in the AGENTS.md "Frontend: `web/`" section.
- **Accepted amendment (2026-10-31, S6 review).**
  - The account menu's form button reads **Sign out**, as on `/account`, in the no-organization
    empty state and in §4.5's "sign out and sign in again": two names for one action fail WCAG
    3.2.4.
  - Switching organizations from an organization's catalogs list keeps no query: that page reads
    only a cursor and a notice, which belong to it. From an organization's search it keeps that
    search as the search reads it (`readSearch`: text, labels and states, without the cursor and
    anything else the address holds), bounded by `sharedSearch` (`src/lib/search.ts`): each of the
    switcher's links may repeat its share of 64 KiB of query text (`SHARED_QUERY_LENGTH`), and at
    least 1 KiB (`LINK_QUERY_LENGTH`); a longer search keeps its text and states alone, else
    nothing. The switcher has one link per visible organization, up to 500: with the address copied
    whole, one crafted link made 7.6 MB of them.
  - The shell's organizations are `{ id, name, display_name }` (`ShellOrganization` in
    `src/lib/organizations.ts`): a platform admin's 500 put every description into each page's
    data. The `/` and `/orgs` cards read their own lists.
  - Without scripts the theme toggle could do nothing, so it is not drawn: `app.html`'s first script
    marks `<html>` with `js`, and the `no-js` variant (`app.css`) hides the toggle. Its icon follows
    the `.dark` class that script sets, so it is right before the page hydrates.
  Covered by `src/lib/search.test.ts` ("sharedSearch"),
  `src/lib/design/components/OrganizationSwitcher.svelte.test.ts`,
  `src/routes/(app)/layout.server.test.ts` and `e2e/shell.test.ts` ("leaves a catalogs list's query
  behind, and keeps of a search what it reads", "the theme toggle"). S5 records this in the
  AGENTS.md "Frontend: `web/`" section.

### 4.2 Explorer (in `catalogs/[catalog]/+layout.svelte`, visible at ≥ lg, after content in DOM order)

- Top level: the organization's catalogs (database icon); the current catalog expanded into namespace
  folders and collection leaves. Wrap in `{#key data.catalog.name}`.
- Server data: the catalog layout returns the root level; namespace and collection page loads return
  `trail` (levels for every ancestor path below the root, computed in parallel, sharing memoized calls
  with the page). The explorer reads levels through `$derived` lookups (`fetched.get(p) ?? server
  level`); client-fetched levels live in a `SvelteMap` inside the keyed instance; never copy props into
  `$state` (svelte-check `state_referenced_locally` is a gate failure).
- Level shape: `{ parent, namespaces, namespacesNext, collections, collectionsNext }` (first page, 50);
  "More…" links to the namespace page. The current node gets `aria-current="page"`; when it is beyond the
  loaded page it is pinned as an extra leaf.
- Rows are links (work without JS). Expand/collapse buttons (`aria-expanded`) render only after mount;
  expanding fetches `/catalogs/[catalog]/tree?parent=` with `x-huron-fetch: 1`, shows `aria-busy` and
  "Loading…", on 401 calls `location.assign('/login?status=expired&returnTo=' + current)`, on other
  failures shows "Couldn't load · Retry"; focus stays on the toggle.
- **Accepted amendment (2026-10-30, S3b review).** The current node gets `aria-current="page"` only
  where its link leads to the page shown: the catalog row on the catalog's Overview, a namespace on its
  page, a collection leaf on the collection's Overview. On a collection's Files, Commits, Activity and
  Schema tabs the leaf gets `aria-current="true"` (it marks the page's section, as the catalog row does
  on the catalog's Access, Activity and Schema tabs since S3a), and no breadcrumb is current: the tab's
  sub-navigation marks the page. Covered by `src/lib/design/components/Explorer.svelte.test.ts` ("marks
  a collection's leaf as the page on its overview, and as its section on a tab") and
  `e2e/collections.test.ts` ("marks its section, not the page, on the collection's other tabs"). S5
  records this in the AGENTS.md "Frontend: `web/`" section.
- **Accepted amendment (2026-10-31, S6 review).** The explorer column (open since S3a).
  - From lg it stays in view and scrolls on its own: `sticky` at 5rem from the top, at most
    `calc(100dvh - 6rem)` tall (`--max-height-explorer`), with 4px of inner padding so that the
    focus rings of rows at its edges are not clipped, and a thin scrollbar (`scrollbar-thin`). On
    load and after each navigation it brings the page's node into view by setting its own
    `scrollTop`, never the window's. In the page flow a tree of 55 stations made a page of 330px of
    content 1,773px tall, with its node below the screen. It keeps its landmark: no `role="region"`
    and no `tabindex` (a §6 exception), since every row is a link and Tab already scrolls it. Of the
    review's two verdicts, this one was chosen over keeping the column in the page flow: without a
    tab stop of its own, the scroller costs keyboard users nothing.
  - Each level is set in by 13px (`ml-3` and its guide line, under the folder's chevron), the first 8
    levels only (`MAX_INDENT`); deeper levels stay at the eighth level's x. Identifiers may nest over
    a hundred namespaces deep (a 22-level chain of one-letter names is legal), and from about the
    14th level the rows left the column and lay over the page, taking its clicks.
  - A page's trail loads 4 levels at a time (`TRAIL_CONCURRENCY`; a 120-level path sent 240 requests
    at once). A level whose read fails is a failed level: its folder says "Couldn't load", with
    "Retry" once scripts run, and the page still shows; the failure is logged, and an expired Huron
    token still ends the session. Levels above the page's own namespace list 10 collections
    (`ANCESTOR_COLLECTIONS`), then "More…": the API lists collections whole, and the explorer shows
    only their names.
  Covered by `src/lib/server/explorer.test.ts`, `src/lib/design/components/Explorer.svelte.test.ts`
  ("says a level on the way that the server could not load failed, and loads it on Retry") and
  `e2e/explorer.test.ts` ("shows the page's node on load without scrolling the window at …", "keeps
  the focus rings of rows at its edges inside it while it scrolls", "keeps a deep tree inside its
  column, beside the content"). S5 records this in the AGENTS.md "Frontend: `web/`" section.

### 4.3 Collection presentation

- States: **Active** — ok tone in the header, no badge in lists. **Incomplete** — warn tone: "The
  catalog's schema now requires fields this collection lacks. Its files are unaffected." **Draft** —
  neutral tone: "Reserved, not yet activated: no directory or files on the share; visible to
  contributors only." Drafts show that explanation instead of share path, metadata.json, files and
  commits.
- Metadata view model (`src/lib/metadata.ts`, unit-tested): fields in walkthrough order (required in
  `required` order, then optional alphabetically), **excluding `title` and `description`** (shown in the
  header), then fields not in the schema under **Other fields**, alphabetically. Label: schema `title`,
  else the humanized key (`start_time` → "Start time"). Values: `date-time` → `<time datetime>` with
  fixed UTC text; `date` → `YYYY-MM-DD`; `email` → `mailto:`; `uri` → link only for `http:`/`https:`
  (`rel="noopener noreferrer"`), else plain text; numbers via the fixed formatter; booleans Yes/No;
  arrays of scalars → chips (keywords are plain chips, not links); arrays of objects → compact list;
  objects → key/value list; `labels` → `key: value` chips linking to catalog search with that label
  (no link when the key contains `=`). **Missing** markers come from `schema.required` minus metadata
  keys (drafts/incomplete). Problems are listed with titles resolved from their JSON pointer
  (`/contacts/0/email` → "Contacts › 1 › Email"; `/` → the field named in the message is not parsed —
  show the message). Never `{@html}`.
- Schema table (`src/lib/schema-view.ts`): rows for every property, nested properties flattened
  (`Contacts › name`, required per level), type, required, constraints (enum/const values, min/max,
  lengths, pattern, format, items), description.
- **Accepted amendment (2026-10-30, S3b review).**
  - Title and description stay out of the metadata list only where the header shows them (non-blank
    text). One that is blank or not text is listed like any other field, and a required one the
    metadata lacks is listed as Missing (a draft without a description shows "Description: Missing").
  - Long metadata is shortened: at most 50 items of one array, object or `labels` (then "and N
    more"), at most 1,000 values in all however they nest (fields, items and labels each count; then
    "and N more fields"), and the first 50 problems (then "and N more problems"). Where the metadata
    is shortened, the Overview says "This metadata is too long to show in full here." and, for a
    settled collection, that `metadata.json` holds all of it. Metadata may take up 1 MiB: drawn in
    full, 400,000 numbers made a 56 MB page that took 11 s to load for every reader, and labelling
    60,000 problems would hold the web's single process for minutes.
  - An `email` value is linked only when it is one address: no `,` `;` `?` `#` `%`, whitespace,
    control characters or characters an address holds only in quotes, so a `mailto:` link never gains
    a second recipient or a header. Anything else shows as text.
  - Nested objects are set in by a guide line, as list items are, so each level reads as its own.
  - A label chip that links to the catalog search is named "<key>: <value>, search the catalog for
    this label": the name starts with the visible text and says where the link leads.
  - A schema override that no longer fits the catalog's schema (problem rule `schema_incompatible`;
    `GET /collections/{id}/schema` answers 422 `SCHEMA_INCOMPATIBLE`), which a later schema assignment
    can bring about: the header explains "Its schema override no longer fits the catalog's schema. Its
    files are unaffected." instead of the Incomplete copy above; the problem shows under "1 problem with
    the schema override", which says the collection is active again (a draft can be activated) once
    the override is fixed or removed and the metadata is valid; the fields show by their keys with a
    note; the Schema tab shows the override alone and explains why there is no composed schema; and
    contributors get the override hints of §4.6 instead of `meta edit` + `meta publish`, which cannot
    run without a schema.
  Covered by `src/lib/metadata.test.ts`, `src/lib/collections.test.ts`,
  `src/lib/collection-state.test.ts`, `src/lib/design/components/MetadataView.svelte.test.ts` and the
  collection layout's, Overview's and Schema tab's tests. S5 records this in the AGENTS.md
  "Frontend: `web/`" section.
- **Accepted amendment (2026-10-30, S4 review).** A label chip links to the catalog search only when
  its key and its value each hold at most 100 code points (`MAX_LABEL_LENGTH` in
  `src/lib/metadata.ts`); a longer label shows as plain text (on the Overview in full). A label may
  take up most of a mebibyte, and a linked chip holds it five times: in its text, its name, its
  link and the page data's value and filter. The web server answers 431 to an address over about
  16 KB, so a link that long never worked. Search results shorten long labels as well (§5). Long
  single values on the Overview stay an open S6 question. Covered by `src/lib/metadata.test.ts`
  ("searches for no label whose key or value is longer than a chip links to"). S5 records this in
  the AGENTS.md "Frontend: `web/`" section.
- **Accepted amendment (2026-10-31, S6 review).** Long text, the open S6 question above.
  Huron-base bounds only the title (200 code points); a draft's metadata need not satisfy it, an
  override may lift it, and every other string may take up most of a mebibyte. Pages show:
  - titles at most 200 code points (`TITLE_LENGTH` in `src/lib/collections.ts`): the collection
    header's h1, each tab's `<title>` and the namespace page's rows, as search results do;
  - the header's description at most 5,000 (`HEAD_DESCRIPTION_LENGTH`): it stands on every tab;
  - on the Overview, each text value, key, field label and label key and value at most 5,000
    (`VALUE_LENGTH` in `src/lib/metadata.ts`), and all of them together at most 100,000
    (`TEXT_BUDGET`), beside the S3b amendment's 1,000 values. A link (`uri`, `email`) too long to
    show in full shows as text, since it would lead elsewhere than it says. This replaces "(on the
    Overview in full)" in the S4 amendment above;
  - problem messages, which quote the value they are about, and the field each names, at most
    1,000 (`PROBLEM_LENGTH`).
  A cut text ends in "…". The Overview's "This metadata is too long to show in full here." also
  shows where the header was shortened (`CollectionSummary.shortened`). Measured before: a
  description of a mebibyte of `<` made each of a collection's five tabs 9.8 MB, and a draft's
  title of a mebibyte made its Overview 5 MB and its namespace page 5.9 MB.
- **Accepted amendment (2026-10-31, S6 review).** Schema tables (`src/lib/schema-view.ts`) show
  at most 200 rows (`MAX_SCHEMA_FIELDS`), then "and N more fields: this schema is too long to show
  in full here."; each cell at most 1,000 code points (`SCHEMA_TEXT_LENGTH`); an enum its first 50
  values, then "and N more" (`MAX_ENUM_VALUES`); and the raw JSON its first 262,144 code points
  (`SCHEMA_JSON_LENGTH`), saying
  "The document is too long to show in full here; this is its beginning." Where a settled
  collection's override is shortened, its Schema tab says that `metadata.json` holds the whole
  override. The API bounds no override: a contributor's override of 20,000 properties (2.5 MB) made
  a Schema tab of 44 MB. Both Schema tabs keep these bounds.
  Covered by `src/lib/collections.test.ts`, `src/lib/metadata.test.ts`, `src/lib/schema-view.test.ts`,
  `src/lib/design/components/SchemaTable.svelte.test.ts` and the collection Schema tab's component
  test ("points to metadata.json for the whole of an override too long to show, …"). S5 records
  this in the AGENTS.md "Frontend: `web/`" section.

### 4.4 Activity

Human labels for every action in the closed vocabulary (e.g. `collection.commit` → "Committed files").
Detail summaries per action (detail keys: platform/organization/catalog grant/revoke `{role,
ldap_group}`; organization/catalog create/delete `{name[, schema_id]}`; `catalog.assign_schema
{schema_id, previous}` → "Assigned schema name vN (was name vM)" via `schema(id)` lookups, deduplicated;
namespace `{path[, collections_allowed]}`; `schema.publish {name, version}`; collection create/delete
`{identifier}`; update_metadata/activate/mark_* `{version}`; set_schema_override `{version, cleared}`;
commit `{adds, removes, host, message, version}`). Collection rows link to the collection by identifier
when `detail.identifier` exists, otherwise to `/collections/<object_id>` ("collection <last 12 hex>").
Raw detail JSON in a disclosure. Timestamps fixed UTC.

- **Accepted amendment (2026-10-30, S3a review).** Entries about an object that no longer exists name
  it without a link: `collection.delete` names `detail.identifier` and `namespace.delete` names
  `detail.path`, as plain text in the summary. A link by identifier would answer 404, or lead to a
  newer collection that reuses the identifier; `/collections/<object_id>` would answer 404 too. Every
  other collection entry links as above; `namespace.create` and `namespace.configure` link to the
  namespace page by `detail.path`. `src/lib/activity.ts` (`GONE`) implements this; covered by
  `src/lib/activity.test.ts` ("links namespaces that still exist and names deleted things without a
  link"). S5 records this in the AGENTS.md "Frontend: `web/`" section.
- **Accepted amendment (2026-10-30, S3b review).** A collection's own Activity tab links no entry's
  target: every entry there is about that collection, so the link would lead back to the page. Covered
  by the activity tab's component test ("lists what happened to the collection without links back to
  it") and `e2e/collections.test.ts` ("lists what happened to it, without links back to itself"). S5
  records this in the AGENTS.md "Frontend: `web/`" section.

### 4.5 States and copy

| State | Copy / behavior |
| --- | --- |
| No visible organizations | "You don't have access to any organization yet." Show the user's groups; with none: "Huron received no groups for your account." Always: "Groups are read when you sign in; if you were just added to a group, sign out and sign in again" + sign-out button. |
| Org with no catalogs | "No catalogs you can see in this organization." + org-admin hint. |
| Namespace empty | Holds collections: "No collections yet." + contributor hint. Structure only: "No namespaces yet." + admin hint. |
| 0 files / 0 commits / empty activity | Specific copy; active collection with no files: contributor hint. |
| 404 | "Not found, or you don't have access." + groups re-sign-in hint + "Back to <org>". |
| 403 | "You don't have permission to see this." |
| 503 | "The Huron service isn't responding." + Try again. |
| 500 | "Something went wrong." + reference id. |
| Organizations unavailable | Shell still renders; switcher shows "Organizations unavailable · Try again". |

### 4.6 Capabilities and CLI hints

- `capabilities(roles, { catalogId?, organizationId? })` (`src/lib/capabilities.ts`, unit-tested) →
  `{ contribute, administerCatalog, administerOrganization, platformAdmin }`: `platform_admin` grants
  all; `org_admin` counts when its `scope_id` is the catalog's organization id (looked up by name in the
  visible organizations); `catalog_admin` (administer + contribute) and `contributor` count when
  `scope_id` is the catalog id. Hints only — the API enforces everything.
- `cliCommand(...)` (`src/lib/cli.ts`, unit-tested, including a namespace named like its catalog) always
  emits `huron --catalog <catalog> <verb> <full identifier> …` (the CLI's `qualify()` prefixes the
  current catalog to bare identifiers). Verify every verb and flag against
  `src/huron/applications/cli/commands/*.py`.
- `CliHint` component: the command in a code block, a copy button (rendered only after mount when
  `navigator.clipboard` exists; otherwise a select-on-focus read-only field), polite "Copied", and
  "This website is read-only; changes are made with the huron CLI on a machine that mounts the share."
- Placement: collection (everyone): `checkout`; (contribute) `add` + `push -m`; draft (contribute)
  `collection activate`; incomplete (contribute) `meta edit` + `meta publish`; namespace that holds
  collections (contribute) `collection create <ns>.<name>`; structure-only namespace and catalog root
  (administerCatalog) `namespace create … [--allow-collections]`; access tab (administerCatalog)
  `catalog grant …` then `acl apply …`; org without catalogs (administerOrganization)
  `catalog create <org> <name>`. Readers see the share path instead.
- **Accepted amendment (2026-10-30, S3b review).** Placement on a collection, in this order:
  everyone gets `checkout`. Contributors then get, for a schema override that no longer fits (§4.3),
  `meta override set <override.json> <identifier>` and `meta override clear <identifier>` as two hints
  ("Replace the schema override with one that fits", "Remove the schema override"); otherwise, for an
  incomplete collection or a draft whose metadata has problems, `meta edit` then `meta publish` (the
  API refuses to activate a draft with problems, so the activate hint alone would mislead). Last comes
  a draft's `collection activate`, or for any other collection "Add files to this collection":
  `checkout`, `add <file>…`, `push -m "<message>"`. That hint checks the collection out itself: `add`
  and `push` act on whichever collection was checked out last (`current()` in
  `src/huron/applications/cli/commands/stage.py`), so without it the files would go to that one. It
  shows for incomplete collections too (the API accepts their commits) and never for drafts (`push`
  refuses them), and the Files tab of a collection with a directory and no files shows the same hint
  to contributors. Readers see the share path and `checkout`. Covered by `src/lib/cli.test.ts`, the
  Overview's and Files tab's component tests and `e2e/collections.test.ts` ("show a reader the share
  path and how to check it out, and a contributor how to push"). S5 records this in the AGENTS.md
  "Frontend: `web/`" section.
- **Accepted amendment (2026-10-30, S4 review).** A hint holds visible characters only. `quote()` in
  `src/lib/cli.ts` writes a word that holds a control character (C0, DEL, C1), a format character
  (Unicode Cf, the bidirectional controls among them) or a line or paragraph separator as `$'…'`,
  with that character as escapes (`\t`, `\n`, `\r`, else each byte of its UTF-8 as three octal
  digits, the form bash's `printf %q` uses), `\\` for a backslash and `\047` for the quote. It also
  quotes a word that starts with `=`, which zsh would expand to a command's path (`=ls`). A search's
  text and labels come from its address, which anyone can write: pasted as they are, Ctrl-U and a
  carriage return in a crafted link erased the typed line and ran a hidden command in a shell
  without bracketed paste, and an escape sequence could end a bracketed paste early; a right-to-left
  override would redraw the hint. `$'…'` is POSIX.1-2024, read by bash, zsh, ksh and mksh (checked
  with bash 5.3 and busybox sh, also when pasted into an interactive bash); dash passes it on
  unread and runs nothing hidden either. Covered by
  `src/lib/cli.test.ts` ("writes the control and format characters of … as escapes", "quotes a word
  that starts with =") and `e2e/search.test.ts` ("copies a command of visible characters only,
  whatever the address holds"). S5 records this in the AGENTS.md "Frontend: `web/`" section.
- **Accepted amendment (2026-10-31, S6 review).** Without a clipboard (an insecure origin), a
  hint narrower than 28rem (`@md` of its own container, as on a phone) shows the wrapped code
  block, which shows every word, and a wider one the field that selects the whole command on
  focus; the other is `display: none`. On a phone
  people read these commands rather than run them, and the field cut each one off at its edge.
  `CopyText` and `CliHint` share their copy logic (`Clipboard` in
  `src/lib/design/components/clipboard.svelte.ts`). Covered by
  `src/lib/design/components/CliHint.svelte.test.ts`, `e2e/catalogs.test.ts` ("without a clipboard,
  shows each command whole on a phone, and as a field with room") and `e2e/organizations.test.ts`.
  S5 records this in the AGENTS.md "Frontend: `web/`" section.

### 4.7 Copy

Login: title "Sign in to Huron", lead "The catalog of raw scientific data on the Huron share.", bullets:
browse catalogs, namespaces and collections; search metadata across your organization; see who can read
each catalog; "Read-only — use the huron CLI to create collections and push files." Meta description:
"Huron catalog of raw scientific data." No Polaris/Icechunk/Lakehouse/NASA copy anywhere.

## 5. Search

- Catalog search (`/catalogs/[catalog]/search`): GET form (`role="search"`, `aria-label="Catalog search"`;
  the header form is "Site search") with `q` (maxlength 200, trimmed), label filters (existing ones as
  removable chip links named "Remove filter <key> = <value>", one `key=value` input to add another),
  state checkboxes — Active and Incomplete checked when no `state` parameter is present; Draft shown only
  when `contribute`; omit `state` parameters when the selection equals the default. Help text: "Matches
  the exact text in identifiers, titles and descriptions. Use labels for exact key=value filters. Sorted
  by identifier." Results: rows (not wrapped in a link) whose link text is the title (fallback
  identifier), identifier as secondary mono text, description clamp, state badge (non-active), label chips
  that add the filter, "N files", updated time; `<mark>` highlighting of `q` in title, identifier and
  description, styled with tokens (`color-mix(in srgb, var(--brand) 30%, transparent)`, color inherit).
  Validate q length and label syntax before calling; an API 422 renders inline. Zero results: list active
  filters as removable links; when `q` has spaces, offer one link per word; offer "Search all of <org>".
  Exact match (first page only, not repeated in the list): trim+lowercase `q`; when it parses as
  `<catalog>.<rest>` or `<rest>` within this catalog, try `collectionByIdentifier` (403/404 ignored).
  Also show the equivalent `huron search <catalog> -q … -l k=v --state …` hint.
- Organization search (`/orgs/[org]/search`): same form; fans out over the org's catalogs (all pages of
  `GET /catalogs?organization=`, capped at 50 catalogs, concurrency 4, 5 results each, overall deadline
  8 s → partial results with "N catalogs did not answer in time"), grouped by catalog with "See all
  results in <catalog>" when that catalog returned a `next_cursor`, per-catalog error notes, and a note
  when the cap truncated the list. Exact match for full identifiers whose first segment is one of the
  org's catalogs. Validation happens once before the fan-out.
- Header search (in the shell): one input, no scope select. Action: catalog search on catalog pages;
  otherwise the current/remembered org's search; otherwise `/search`. Results pages link "Search all of
  <org>" / "Only <catalog>". `/search?q=` without context renders a chooser ("Search 'wind' in: Helio ·
  Geo") that keeps `q`. Below md the bottom-nav Search item opens the scoped search page.
- **Accepted amendment (2026-10-30, S4 review).** The catalog search (`src/lib/search.ts`, the shared
  model; `src/lib/server/search.ts`; `catalogs/[catalog]/(overview)/search`) decides what this section
  leaves open as follows; the organization search and the header box reuse the model.
  - Reading the address: `q` is trimmed and holds at most 200 code points, as the API counts them
    (`maxlength` counts UTF-16 units, so only a hand-made address holds more). A label splits at its
    first `=`, else at its first `:` as the API also accepts, and is written back as `key=value`; a
    label without either or with an empty key, or whose key or value holds more than 100 code points
    (the most a label chip links, §4.3), is an error shown at the field for adding a label, which
    gets the text back; blank labels are ignored, duplicates count once, and labels are kept as
    written. A search holds at most 10 label filters: with more, that field shows an error and the
    form keeps the first ten. As with the text, a search with an error makes no API call. Every link
    that changes a search repeats all its filters, and the form and an empty result list link once
    per filter: before these bounds a hand-made address of 120 filters made a page of 4.3 MB, and
    one label filter of 8,000 characters, on rows that carry it, 11 MB. States other than active,
    incomplete and draft are ignored, and so is draft for a user who may not create collections in
    the catalog (it is never sent); no state left, or exactly the default two, means the default.
  - Canonical address: `q`, each `label`, each `state` (none for the default), then `cursor`. Every
    link the page builds uses it (Pager included), and with scripts the form submits it too: it
    rewrites its own data on `formdata`. Without scripts the browser submits every field (`label=`,
    the checked default states), which reads as the same search; the address then shows them. A
    browser submitting a form itself writes each line break of a field as CR LF, which would make a
    kept filter another one, so the form keeps a filter whose text holds a line break as
    `label_json`, the text as a JSON string; the address reads it as that label, and links and the
    form with scripts write `label`.
  - The exact match honors the search's label and state filters: it is the result whose identifier is
    the text, lifted to the top of the first page and left out of the list on every page (a later
    page leaves out the result with that identifier, which the first page showed, without a
    lookup), so a draft shows there only when the search includes drafts. Text that starts with the
    catalog's name and a dot is a full identifier, as the CLI's `qualify()` reads it; other text is
    an identifier inside the catalog. A lookup answering 403, 404 or `INVALID_SEGMENT` shows
    nothing; other failures are logged and the results still show.
  - The search without text, labels or chosen states lists every collection the user can see, by
    identifier ("No collections yet." when there is none).
  - Results: each title is an `h3` holding the link; titles are cut to 200 code points and
    descriptions to 300 (shown in two lines; a description may take up a mebibyte). A row shows its
    first labels, at most 12 of them and while their text, keys and values together, stays within
    300 code points (then "and N more labels"), each key and value cut to 100 code points; a cut
    label is no link (§4.3); the collection's page shows them all. A chip repeats its text in its
    name, its link and the page data: five rows with a mebibyte-long label made the catalog's Search
    tab, which every reader opens, 25 MB, and each chip that adds a label links to the whole search
    again, so 25 rows of 50 chips made it 1 MB (318 KB with 12). The identifier and the
    description use the foreground color, so `<mark>` text reads at 13.5:1 (light) and 8.2:1
    (dark); muted text would read at 4.4:1 and 3.6:1. A label chip whose filter the search already has
    is no link: it shows with a check and ", in this search". The chips that add a label are named
    "<key>: <value>, add this label to the search", as the collection page's are "<key>: <value>,
    search the catalog for this label".
  - Zero results: the filters to remove are the text ("Remove text “…”"), each label ("Remove filter
    <key> = <value>") and a chosen set of states ("Remove state filter …", back to the default).
    "Search all of <org>" is in the Results section of every page: here as one of these ways out,
    elsewhere as the line after the results, before the page links (§5 asks results pages for
    it). It carries the text and the labels, not the states: each catalog decides who sees its
    drafts. A text of several words offers its first 10 words, each a search of its own that
    keeps the filters. Label filters that give one key two values find nothing without an API
    call: a collection's labels hold one value for each key.
  - An API 422 shows at the field its problem names (`/query/q`, `/query/label…`, or the `label` of
    its context), else at the form, always in fixed copy.
  - Document title: "“<q>” · Search · <catalog> · Huron"; "Search · <catalog> · Huron" without text;
    "Error: Search · <catalog> · Huron" while a field shows an error.
  - The shell's Catalogs item does not claim the catalog search; until the Search item arrives, no
    primary navigation item is current there.
  Covered by `src/lib/search.test.ts`, `src/lib/search-links.test.ts`, the search load's and page's
  tests, `SearchForm`, `SearchResults` and `NoSearchResults` component tests, and `e2e/search.test.ts`
  (among them "explains label filters it will not search for at the field for adding one" and "keeps
  a label filter with a line break when the form is sent without scripts"). Still open for S6: a
  hand-made address of six filters of 100 + 100 four-byte code points, the most the web server's
  16 KB header limit holds, on 25 rows that a contributor gave those labels, makes a page of 4.7 MB
  for whoever opens it (300 links of 14 KB each); the organization search shows more rows. S5
  records this in the AGENTS.md "Frontend: `web/`" section.
- **Accepted amendment (2026-10-30, S4 review).** The organization search (`orgs/[org]/search`,
  `src/lib/server/org-search.ts`) and the chooser (`/search`) decide what this section leaves open
  as follows.
  - Reading: the address is read and checked once, as the catalog search reads it, before any
    catalog is asked; a search with an error asks none. The search has no pages: a `cursor` is
    ignored. The search without text, labels or chosen states asks nothing either: the page shows
    the form and what it covers ("Searches the 2 catalogs of <org> that you can see, and shows
    the first 5 results of each."). It could list five collections of each catalog, not every
    collection as a catalog's search does, and 50 requests on every visit of the tab would buy
    no more than the organization's Catalogs page shows. Label filters that give one key two
    values find nothing without asking.
  - Catalogs: the first 50 by name that the user can see, read page after page (an empty page
    ends the list); with more, a note says "This organization has more than 50 catalogs; its
    search covers the first 50, by name." The listing is an ordinary read: an organization the
    user cannot see answers 404, and its failure is the page's. An organization without catalogs
    says "No catalogs you can see in this organization."
  - Drafts: the form offers Draft when the user may create collections in one of those catalogs;
    each catalog gets draft only where they may (it is never sent elsewhere), and a catalog left
    with no state to search (a search for drafts alone) is skipped and named in a note ("Not
    searched, because only those who may create collections there see drafts: …").
  - Fan-out: four requests at once, five results each (`limit=5`), and one deadline of 8 s for
    the searches and the exact match together; the exact match's lookup is one of the four, asked
    before the catalogs' searches. Requests still running at the deadline are aborted
    (`HuronApi.search` and `collectionByIdentifier` take an optional `signal`; a request with one
    is never memoized), what they do later is dropped, and the catalogs not heard from, started or
    not, are counted in a warn note, "N catalogs did not answer in time.", with a "Search only
    <catalog>" link to each.
  - Failures: a catalog whose search fails shows in its place under its name with "Couldn't
    search this catalog." and its "Search only <catalog>" link, never the API's words; the
    failure is logged, and the other catalogs still show. An expired Huron token still ends the
    session; a refusal (422) shows at the form, as the catalog search shows it, without results.
  - Results: each catalog that found something is a section headed (h2) by its display name,
    which links to the catalog; its rows are the catalog search's (`SearchResults`, titles h3),
    then "See all results in <catalog>" when that catalog has more than five, else "Search only
    <catalog>" (this section's "Only <catalog>", worded to stand alone as a link). Both lead to
    the catalog's search with the search that catalog got. Catalogs that found nothing share one
    line, "No collections match in A and B." Label chips here are text, not links; a filter the
    search has shows with its check. Every link that changes a search repeats its whole address,
    and 50 catalogs of five rows with twelve chips would make 3,000 of them (about 40 MB for a
    crafted address of 14 KB); the catalog's own search, a link away, adds labels from its chips.
    So the links that repeat the address are one per catalog plus the form's and the empty
    state's: measured, that crafted address makes a page of 203 KB when nothing matches (the
    catalog search's: 234 KB); with 50 catalogs of rows its links add, by estimate, about 0.8 MB.
    The rows themselves are bounded by the result's caps (§5's S4 amendment above), 250 at most.
  - Exact match: only a full identifier whose first segment is one of the searched catalogs
    (`identifiedCatalog` in `src/lib/search.ts`), looked up there alone, with that catalog's search
    and the catalog search's rules; it shows first and not again in its catalog's section ("No
    other collections match in …"). No other catalog is ever asked for it.
  - Nothing found: the catalog search's empty state (filters to remove, one search per word) with
    links inside the organization and no wider search; where some catalogs failed or were late it
    says "No collections match in the catalogs that answered.", and where none answered, only the
    notes show.
  - No CLI hint: the CLI searches one catalog at a time (`huron search CATALOG`); each catalog's
    own search, a link away, shows its command.
  - Document title: "“<q>” · Search · <org> · Huron", "Search · <org> · Huron", "Error: Search ·
    <org> · Huron".
  - The chooser (`/search`), where the box leads without a catalog or an organization, reads the
    address as a search does and keeps its text and label filters, not its states: "Search
    “wind” with mission = ace in:" over the visible organizations, each a link to its search;
    without text or labels, "Choose the organization to search:". What fails the check is left
    out of the links, and the page says why. A user with exactly one organization goes straight
    to its search (303) with the address's `q`, `label` and `label_json` as written, so that its
    form explains anything wrong with them; one with none sees §4.5's empty state. Titles as
    above, without the organization.
  Covered by `src/lib/server/org-search.test.ts` (fan-out, cap, concurrency, the deadline with fake
  timers, failures, drafts, the exact match within the organization), the two loads' and pages'
  tests, `src/lib/search.test.ts`, `src/lib/search-links.test.ts`, `e2e/org-search.test.ts`,
  `e2e/site-search.test.ts`, `e2e/faults/org-search.test.ts` (a failing catalog and the deadline)
  and `e2e/layout.test.ts`. S5 records this in the AGENTS.md "Frontend: `web/`" section.
- **Accepted amendment (2026-10-31, S6 review).** What the S4 notes left open.
  - Crafted addresses: accepted as a residual, which closes "Still open for S6" above. The bound is
    the web's own reading of an address, not Node's 16 KB header limit: `q` holds at most 200 code
    points, a label key and value 100 each, and a search 10 filters, so the longest canonical search
    is about 26.6 KB percent-encoded with four-byte code points. Today the header limit caps an
    address at about 14.4 KB, which makes the measured 4.7 MB catalog search page (25 rows that a
    contributor gave those labels); a deployment that raised the limit would get at most about 1.85
    times that. It needs a crafted link and seeded rows, falls on whoever opens the link and
    persists nothing. A total label-text limit is rejected: two CJK filters of 100 + 100 code
    points already take 1,200 bytes.
  - The links that repeat an organization search's address are one per catalog, the form's and
    the empty state's, plus one per visible organization in the switcher (§4.1, bounded by
    `sharedSearch`). The chooser has one per organization, bounded the same way, and says when it
    leaves part of a search out ("This search is too long to repeat in a link to each organization,
    so the links leave out its label filters."). Either repeats at most 64 KiB of query text, or 1
    KiB per organization beyond 64 of them: about 500 KB at 500 organizations, where a crafted
    address made 7.6 MB. The chooser's `organizationList` carries names and ids only.
  - `draftAccess` (whoami and the organizations), like the catalog listing, is an ordinary read
    under the API timeout before the 8 s deadline starts; when it fails the search counts no drafts
    and still runs. The organization search reads it on every visit; deciding the form's Draft
    offer from the shell's roles and reading it only when the address asks for drafts would save
    those two reads and is left for later.
  Covered by `src/lib/search.test.ts` ("sharedSearch"), `src/routes/(app)/search/page.svelte.test.ts`
  ("repeats no more of a long search than each of many links may hold, and says so") and
  `e2e/shell.test.ts`. S5 records this in the AGENTS.md "Frontend: `web/`" section.

## 6. Accessibility, responsiveness, determinism

- Semantic HTML; visible focus; labelled controls; icon-only buttons with `aria-label`; `aria-current`
  on current nav/tree/sub-nav items; sub-navs are `<nav aria-label>` with links (not ARIA tabs); nothing
  hover-only; `Callout` uses `role="note"` (not `alert`) for static content; scroll containers get
  `tabindex="0"`, `role="region"` and an `aria-label`.
- Light-mode token fixes (WCAG AA at 12–13 px): `--brand-strong: #00766a`, `--muted: #5f6773`.
- Layout at 390 px, ~816 px and ≥ 1280 px, light and dark, no horizontal page scroll; long identifiers and
  paths wrap (`break-all`/`overflow-wrap:anywhere`) or scroll inside their container. Use Tailwind 4
  container queries (`@container`) for the details aside and list rows. Breadcrumbs (Org › Catalog ›
  namespace… › collection) on every catalog-layout page.
- Deterministic formatting (`src/lib/format.ts`, unit-tested): fixed `en-US` locale for counts, fixed
  byte units (`1.2 MB`, exact bytes in `title`/`<data value>`), timestamps `YYYY-MM-DD HH:mm UTC` with
  `<time datetime>`. No locale-default `toLocaleString`, no `Date.now()` during render.
- **Accepted amendment (2026-10-31, S6 review).**
  - The explorer's scroll container (§4.2) has no `tabindex`, `role="region"` or `aria-label`: it is a
    `<nav>` whose rows are all links, so Tab scrolls it, and a region role would hide its landmark.
    Other scroll containers keep the rule (`ScrollRegion`).
  - Focus rings have room at the screen's edges: the bottom navigation has 4px of padding below its
    links, and `html` sets `scroll-padding-bottom: 0.75rem` at every width (4.5rem below md). The
    global focus rule stays unlayered, so no utility can weaken it.
  - In forced colors, controls drawn by a fill (the search forms' submit, the sign-in link and the
    account menu's avatar) have a transparent border, which forced colors draw; a sub-navigation
    draws an underline under the current tab only, never a transparent one under the others.
  - A share path offers a line break after each `/` (`<wbr>` in `CopyText`); a segment too long on
    its own still breaks anywhere. Copying copies the path as it is.
  - The static error page (`src/error.html`) sizes its boxes with `border-box`, so its card fits a
    phone.
  Covered by `e2e/shell.test.ts` ("each link of the bottom navigation has room for its whole focus
  ring on screen", "brings what Tab reaches from below the screen into view with its whole focus
  ring", "in forced colors"), `e2e/collections.test.ts` ("answers its metadata.json with a page of
  its own that fits a phone") and `src/lib/design/components/CopyText.svelte.test.ts`. S5 records
  this in the AGENTS.md "Frontend: `web/`" section.

## 7. Testing and gate

- Vitest: `vite.config.ts` adds `svelteTesting()` from `@testing-library/svelte/vite` (installed); server
  modules' test files start with `// @vitest-environment node`. Cover: config, cookies, sessions
  (create/get/expire/caps/delete/no secrets in `locals.user` via devalue), OIDC (authorize URL, PKCE,
  sealing, callback checks incl. azp/iss/aud/nonce/exp, IdP errors, discovery issuer mismatch), return-to,
  API client (URLs, encoding, segment checks, problem parsing, retry, timeouts, no cookie header), guard
  mapping, param matchers, generator + drift, formatters, metadata/schema view models, capabilities, CLI
  hints, search parsing/serialization and org fan-out (cap, concurrency, deadline, errors), explorer
  helpers, and key components (switcher, pager, metadata view, search form) with `@testing-library/svelte`.
- `web/tsconfig.tools.json` type-checks `e2e/**`, `scripts/**` and `playwright.config.ts`; `npm run check`
  runs `svelte-kit sync && svelte-check --tsconfig ./tsconfig.json && tsc -p tsconfig.tools.json`.
- Gate (from `web/`): `npm run check` (0 errors, 0 warnings), `npm test`, `npm run lint`, `npm run build`,
  `npm run test:e2e`. Python gate only when Python changes.
- Playwright (section 8), Chromium only; viewports via overrides (390×844, 816×900, 1440×900). Role-based
  locators; `toMatchAriaSnapshot` for the shell, switcher and explorer (no axe-core available).

## 8. E2E harness and demo stack

- `web/e2e/support/fake-idp.mjs` (dependency-free, one process, two ports):
  - **IdP** (`http://127.0.0.1:8199`): discovery (`issuer` byte-equal to the API's
    `HURON_COMPANY_ISSUER`, no trailing slash; `authorization_endpoint`, `token_endpoint`, `jwks_uri`,
    `end_session_endpoint`, `code_challenge_methods_supported: ["S256"]`); JWKS with the RS256 signing key
    `{kty,n,e,kid,alg:'RS256',use:'sig'}` **plus an `{use:'enc', alg:'RSA-OAEP'}` key** (as Keycloak
    publishes; guards the JWKS fix); one key pair for the process lifetime; `/authorize` validates client,
    redirect-URI allowlist, `response_type=code`, PKCE S256, state, nonce, and renders a sign-in page with
    one button per fixture user plus **Cancel** (redirects back with `error=access_denied`); the POST
    answers **303** to the callback with a one-time code; `/token` checks code, verifier, redirect URI and
    client auth (basic), returns `id_token` (header `{alg:'RS256',typ:'JWT',kid}`; claims `iss`, `aud`
    `[client_id, ...extra audiences]`, `azp`, `sub` `sub-<user>`, `preferred_username`, `name`, `email`,
    `nonce`, `iat`, `exp`) plus a dummy access token; `/logout` redirects to an allowlisted
    `post_logout_redirect_uri`; group directory `GET /users/<username>/groups` → `{"groups":[...]}`, 404 for
    unknown users; test-only `POST /test/id-token {username}` for seeding. Special users: `noaud` (no extra
    audience → exchange 401), `idpfail` (token endpoint answers 503).
  - **Fault proxy** (`http://127.0.0.1:8197`, the web's `HURON_API_URL`): forwards to the API
    (`http://127.0.0.1:8198`); `POST /__test/faults {subject, mode}` with mode `unavailable` (503 problem),
    `unauthorized` (401 `TOKEN_INVALID`), `error500` (500 `INTERNAL` with `context.request_id`), `reset`
    (destroy socket) or `null`; faults apply only to requests whose bearer token's `sub` matches, so
    parallel tests are unaffected.
- API: `uv run uvicorn huron.applications.api.main:app --host 127.0.0.1 --port 8198` with `cwd: '..'` and
  every setting explicit: `HURON_STORE=memory`, `HURON_INSTANCE_ID`, `HURON_ISSUER=http://127.0.0.1:8198`,
  `HURON_COMPANY_ISSUER=http://127.0.0.1:8199`, `HURON_COMPANY_AUDIENCE=huron-cli`,
  `HURON_GROUP_DIRECTORY_URL=http://127.0.0.1:8199`, `HURON_PLATFORM_ADMIN_GROUP=huron-platform-admins`,
  readiness `http://127.0.0.1:8198/readyz`.
- Web: `node build/index.js` (not `npm run start`, which reads `web/.env`) with `ORIGIN=http://localhost:4173`
  (the browser uses `localhost`; IdP and API use `127.0.0.1`, so they are cross-site and SameSite matters),
  `HOST=127.0.0.1`, `PORT=4173`, and every `HURON_*`/`HURON_WEB_*` variable set explicitly (client
  `huron-web`, secret `e2e-secret`, logout enabled, mount prefix `/projects/huron`).
  `reuseExistingServer: false` everywhere; a `setup` project (retries 0) seeds once; test projects depend on
  it; `baseURL = ORIGIN`.
- Fixture (`web/e2e/support/fixture.mjs`, exported for assertions) seeded through the real API
  (`seed.mjs`; tokens via `/test/id-token` + exchange). Users → groups: alice `[huron-platform-admins]`,
  bob `[helio-org-admins]`, carol `[helio-catalog-admins]`, dave `[helio-contributors, geo-readers]`, erin
  `[helio-readers]`, oscar `[helio-readers]` (faults), mallory `[]`, noaud `[helio-readers]`, idpfail
  `[helio-readers]`. Organizations: `helio` "Heliophysics Division" (org_admin helio-org-admins), `geo`
  "Earth Science" (org_admin geo-org-admins), `astro` "Astrophysics" (no fixture grants). Catalogs and
  grants: `heliophysics` and `space-weather` in helio (catalog_admin helio-catalog-admins, contributor
  helio-contributors, reader helio-readers), `geoscience` in geo (reader geo-readers), `exoplanets` in astro.
  heliophysics namespaces: `solar-wind` (structure) → `solar-wind.ace` and `solar-wind.wind` (collections);
  `fields` (collections); `empty` (collections, none); `deep` → `deep.a` → `deep.a.b` → `deep.a.b.c`
  (collections). Collections (created by dave): `solar-wind.ace.mag-l2-2024` (active; labels mission=ace,
  instrument=mag, level=l2; keywords; contacts; start/end times; two commits — 3 adds, then 1 add + 1
  remove), `solar-wind.ace.swepam-2024` (active; mission=ace, instrument=swepam), `solar-wind.ace.mag-l1-draft`
  (draft, title only), `solar-wind.wind.mfi-2023` (active; mission=wind), `fields.run001`…`fields.run060`
  (active; "Encounter 17 run 001"…; mission=psp, encounter=17; run001 holds 120 files), `deep.a.b.c.leaf`
  (active). space-weather: `alerts` (collections) → `kp-index-2024` (has `mission`) and `flare-list-2024`
  (no `mission`); then an org schema `space-weather` extending huron-base with required `mission` is
  assigned, making `flare-list-2024` incomplete. geoscience: `ocean.sst-2024` (active; mission=mur).
  exoplanets: `surveys.tess-sectors` (active).
- `npm run demo` (`web/scripts/demo.mjs`): starts the fake IdP + proxy and the API, seeds, then runs
  `vite dev` (port 5173) with matching env (redirect URIs for `localhost` and `127.0.0.1`:5173); prints the
  URL and users; Ctrl+C stops everything.
- **Accepted amendment (2026-10-30, S4 review).** The fault proxy takes an optional `path`:
  `POST /__test/faults {subject, mode, path}` fails only requests whose path starts with it (one
  fault per subject and path; the longest matching path applies; `mode: null` with a `path` clears
  that one, without it all of the subject's). A new mode, `hang`, never answers, for the
  organization search's deadline. Without `path` the faults work as before. The fixture gains
  `paula` (Paula Park, `huron-platform-admins`), whom only the long walks of `e2e/layout.test.ts`
  sign in as: a user holds at most 10 web sessions (§3.3), and those walks lost alice's session to
  other tests signing in as alice meanwhile. S5 records this in the AGENTS.md "Frontend: `web/`"
  section and in `web/README.md`.
- **Accepted amendment (2026-10-31, S6 review).**
  - Every e2e test imports `test` from `e2e/support/harness.ts`, whose automatic fixture ends each
    web session the test signed in to (`signIn` records its cookie, and the default context's
    cookie is read at the end) with a `POST /logout` carrying that cookie and the web's `Origin`. A
    user holds at most 10 sessions, and sessions outlived their tests by the token's 8 hours, so a
    test that outlived 10 later sign-ins of its user lost its session halfway. Reproduced: a long
    test as carol was signed out by a parallel worker's tenth sign-in, and with the teardown it is
    not. paula stays, though she is no longer needed for this.
  - The fixture gains `space-weather.alerts.storm-count-2024` (dave): its override types `mission`
    as an integer, which huron-base allows, so it activates; the space-weather schema, assigned
    afterwards, types `mission` as text, so the override no longer fits (problem rule
    `schema_incompatible`; `GET /collections/{id}/schema` answers 422 `SCHEMA_INCOMPATIBLE`) and the
    collection is incomplete. The space-weather search for incomplete collections finds it and
    `flare-list-2024`, and the catalog log marks both incomplete. `fixture.mjs` exports
    `titleOf(identifier)`.
  Covered by `e2e/collections.test.ts` ("a collection whose schema override no longer fits"). S5
  records this in the AGENTS.md "Frontend: `web/`" section and in `web/README.md`.

## 9. Repository changes outside `web/`

- `IMPLEMENTATION_PLAN.md`: a dated amendment at the end of section 3 narrowing the "web UI" non-goal to
  this read-only BFF client, and recording the JWKS fix.
- `AGENTS.md`: a concise **Frontend: `web/`** section (sources of truth, required skills, API seam, BFF and
  read-only invariants, gate, visual QA, offline constraints); `web/AGENTS.md` points to it.
- `scripts/keycloak/company-realm.json`: client `huron-web` — confidential with a dev-only secret, standard
  flow only (`directAccessGrantsEnabled` and `implicitFlowEnabled` false), exact redirect URIs
  (`http://localhost:5173/auth/callback`, `http://127.0.0.1:5173/auth/callback`,
  `http://localhost:4173/auth/callback`, `http://127.0.0.1:4173/auth/callback`), exact
  `post.logout.redirect.uris` for `/login?status=signed-out` on the same origins, `pkce.code.challenge.method`
  S256, an audience mapper adding `huron-cli` with `id.token.claim: true` and `access.token.claim: false`,
  no `webOrigins`. A Vitest test reads the realm file and checks these. A live Keycloak run is not possible
  here (no image, downloads blocked) — say so.
- `web/README.md`, `web/.env.example` rewritten (demo stack; real dev stack with `make up`,
  `uv run python scripts/devgroups.py scripts/dev-groups.yaml 8082`,
  `HURON_COMPANY_ISSUER=http://127.0.0.1:8081/realms/company make api`, the web env, recreating only the
  Keycloak volume for existing stacks; production notes: ORIGIN, single replica/sticky sessions). Also
  `CHANGELOG.md` (Unreleased), `docs/architecture.md` (web component), minimal `CONTEXT.md` corrections of
  web/Polaris lines. Pre-existing dev-stack issues found (dev.env issuer host, `scripts/e2e.sh`) are
  reported, not fixed.
- **Accepted amendment (2026-10-31, S6 review).**
  - The realm's `huron-web` client is checked by `tests/unit/test_dev_realm.py`, which the Docker
    workflow wrote (it owns `tests/unit/` and the realm): confidential, standard flow only, PKCE
    S256, exact redirect and post-logout URIs, the audience mapper on the ID token only, no
    `webOrigins`, and the Docker web's secret. No Vitest copy: it would duplicate those checks. The
    redirect URIs also allow port 3000, the Docker web's. `web/.env.example` sets
    `HURON_WEB_OIDC_CLIENT_SECRET` to the realm's development secret.
  - Still S5's: the AGENTS.md section headed exactly "Frontend: `web/`" (so that `web/AGENTS.md`'s
    `#frontend-web` link resolves), a web row in its "Skills by area" (svelte-core-bestpractices,
    svelte-code-writer, tailwind-design-system), and every dated amendment of this spec; the
    `IMPLEMENTATION_PLAN.md` §3 amendment; a web component paragraph in `docs/architecture.md`;
    `CONTEXT.md` lines 91–93 and 123 (drop "as the web's browse pages show" and "web and", the "Web
    organization" entry and the "raw" ambiguity); the `make up` dev stack and the secret in
    `web/README.md`; and a decision on a `huron-cli` client in the fake IdP (device, loopback
    and refresh grants, so that the CLI could sign in to `npm run demo`), which the Docker
    stack now covers. Changes to files the Docker workflow owns (`dev.env`, the
    realm, `CHANGELOG.md`, the root `README.md`) go through the lead.
  - Backend follow-ups (no backend change here beyond the JWKS fix): a crafted company token whose
    header `alg` belongs to the other key type of a known `kid` makes the exchange answer 500
    instead of 401 (`verify()` passes `PyJWK(...).key`; keep the `PyJWK` and pass it to
    `jwt.decode`, with a test in `tests/unit/security/test_exchange.py`); a collection listing
    without metadata, problems and `schema_override` for namespaces, search and the explorer; a
    size limit for `schema_override` and published schema documents, like `MAX_METADATA_BYTES`;
    shorter quoted values in validation messages; the Postgres adapter's labels (one value per key,
    `lower()` against `casefold()`); and the completeness hash of int64 bounds (`rfc8785`).
  - Deployment: compress `text/html` and `application/json` at the route, ingress or reverse proxy
    (adapter-node compresses only prebuilt assets; no page holds a secret for BREACH to extract).
    Sessions live in the one process's memory, so a restart or an out-of-memory kill signs every
    user out, and a container memory limit is headroom shared with the reads of §3.6 and §4.2.
- **Accepted amendment (2026-10-31, S5).** The repository documentation.
  - This spec lives in the repository as `docs/web-design.md`, so that the docs can point at it.
    Its amendments are kept as written; only pointers outside the repository were rewritten.
  - The fake IdP gets no `huron-cli` client. `make app` (`docker-compose.app.yml`) runs Keycloak,
    so the CLI signs in for real, with the device or the loopback flow, to the same API and data
    as the web. `npm run demo`'s fake IdP serves the web alone; `web/README.md` says so and
    points to `make app` for the CLI.
  - `make api` needs no `HURON_COMPANY_ISSUER` on its command line: `dev.env` names
    `http://127.0.0.1:8081/realms/company` now.
  - `web/.env.example` serves `npm run start` at `http://localhost:3000` against the `make up`
    stack, a callback the realm's `huron-web` client lists. 4173 belongs to the e2e harness and
    5173 to `npm run dev` and `npm run demo`; 3000 is free whenever `make up` runs, because
    `make app`, whose web publishes it, uses the same ports as `make up`.
  - A live Keycloak run is possible now, which this section said it was not: the Docker workflow
    signed in through Keycloak's form on `make app`'s stack, and S5 on `make up`'s, with
    `npm run start` and `npm run dev` reading a `.env` copied from `web/.env.example`.
  - Organization and catalog display names and descriptions, and the LDAP group names that
    Activity shows from grants, are drawn whole: the exception to the text bounds of §4.3 and §5.
    The API sets no maximum length for them, but only admins write them: platform admins an
    organization's, org admins a catalog's, and platform, org or catalog admins the groups of the
    roles each may grant. The S6 review left the descriptions uncut for that reason.
  - Web follow-up: `failedSignIn` (`src/lib/server/oidc.ts`) logs an error it does not expect
    whole, message and stack (`huron-web sign-in failed unexpectedly`). Log only its class, as
    `handleError` does (§3.5); until then `web/README.md` names the line as the one log entry that
    may hold free text.

## 10. Removal list

All of `web/src/lib/server/*` (Polaris, Icechunk inspector, accounts, organizations store, settings; keep
only the ideas of `safeReturnTo`), `web/src/lib/api/*` except the new files, `web/src/lib/stores/*`,
`web/src/lib/reserved-slugs*` (routes are prefixed), `web/src/lib/design/polaris.css`,
`web/src/lib/design/components/polaris/*`, `LayerBadges`, `LifecycleChip`, `StalenessBanner`,
`WatermarkNotice`, `PermissionEditor`, `WorkspaceSwitcher`, `KeysetPager` (replaced by `Pager`), and any
component left unused; all legacy routes (`admin`, `browse`, `polaris`, `settings/*`, `signup`, `product`,
`snapshot`, `[org]/…`, old `account`, `login`, `logout`, root `+page.*`, `+layout.*`, `+error.svelte`); all of
`web/e2e/*`; tracked `web/.playwright-cli/*` (and add `.playwright-cli/` to `web/.gitignore`); the unused
`unicode-case-folding` dependency only if `npm uninstall --offline --no-audit --no-fund` works. Keep
`static/`, `tokens.css` (with the contrast fixes), `app.css`, `Badge`, `Card`, `Callout` (role fix),
`EmptyState`, `ThemeToggle`, `Breadcrumbs`, `AuthShell` (rewritten copy, or removed).

## 11. Slices (implementation order)

- **S1 Foundation** — removal (10); config (3.1); cookies (3.2); sessions (3.3); OIDC, return-to and the
  auth routes (3.4); hooks (3.5); API client and guard (3.6); CSP (3.7); types and generator (3.8); route
  matchers; the `(app)` group with `+layout.server.ts`, the shell (4.1) without the header search box,
  switcher, account menu, both error pages, `src/error.html`; pages `/`, `/orgs`, `/orgs/[org]` (layout
  + catalogs list; the Search sub-nav item may point at the search route that arrives in S4 only if hidden
  until then — prefer adding it in S4), `/account`, `/login`, `/healthz`; `format.ts`, `capabilities.ts`,
  `cli.ts`; token contrast fixes; `vite.config.ts` (`svelteTesting`), `.prettierignore`, `.gitignore`;
  unit/component tests. Gate without e2e (the harness is S2).
- **S2 Harness** — section 8 (fake IdP + fault proxy, fixture, seed, Playwright config, demo),
  `tsconfig.tools.json` + `npm run check`, e2e for: unauthenticated redirect + returnTo; sign-in/out;
  `/` redirect rules (erin single org, dave multi-org then remembered); org switcher by keyboard; org
  pages; concealed 404 (erin → `/orgs/astro`); mallory empty state; noaud → token_rejected; idpfail →
  idp_unavailable; Cancel → idp_error; open-redirect returnTo; two interleaved sign-ins in one context;
  expired session (oscar `unauthorized` → `/login?status=expired&returnTo=…`); API outage (oscar
  `unavailable` → shell + 503 page, recovery); cross-site `POST /logout` → 403; no JWT-shaped string and
  no session cookie value in any page body or `__data.json`. Visual QA of S1 screens.
- **S3 Browse** — catalog layout and `(overview)` pages, explorer + tree endpoint, namespace page,
  collection layout + tabs + metadata.json + `/collections/[id]`, metadata/schema view models, activity,
  CLI hints, states (4.5); unit/component tests; e2e for browsing, explorer (expand, 401, retry), paging
  (fields 60, run001 120 files), drafts per role, incomplete problems, deep namespaces, hints per role,
  activity links, page_expired notice, mobile no-horizontal-scroll; visual QA.
- **S4 Search** — section 5 (catalog, organization, header box, `/search` chooser, exact match, zero
  results, CLI hint), switcher keeps search sub-route; unit + e2e; visual QA.
- **S5 Docs & dev stack** — section 9.
- **S6 Final review** — multi-lens review of the whole change, fixes, full gate, visual QA.
