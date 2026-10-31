# Agent instructions

These rules apply to every agent working in this repository. The implementation plan is
[`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md); its sections 3–9 are binding design. When this
file and the plan disagree, the plan wins and this file is corrected.

## Layout

```text
src/huron/
  pkg/             generic code with no Huron vocabulary (errors, paging, hashing, fs, acl)
  schema/          JSON Schema documents, validator, naming rules, schema composition
  core/
    security/      broker/ (OIDC exchange, Huron tokens) and rbac/ (roles, privileges, grants)
    lake/          the domain: one subpackage per area (organizations, catalogs, namespaces,
                   collections, files, schemas, audit)
    metastore/     PostgreSQL adapters and in-memory fakes, one subpackage per area
    storage/       share layout, ACL plans, POSIX storage, drift check (used by the CLI)
  applications/
    api/           FastAPI service; routes/v1/{endpoints,schema}
    cli/           Typer CLI; commands/ holds one module per verb group
migrations/        Alembic environment and versions
tests/             unit/ contract/ integration/ acl/ fakes/ support/
web/               SvelteKit web app, a read-only client of the API (see Frontend: web/ below)
docker/            seed/: the one-shot seed of the Docker application stack
docker-compose.app.yml   the whole application in Docker (make app); docker-compose.yml is make up
```

## Dependency rules

Enforced by import-linter (`pyproject.toml`):

- `pkg` imports nothing from `huron`; `schema` imports only `pkg`.
- `core.security` never imports `core.lake`, `core.metastore`, `core.storage` or `applications`.
- `core.lake` never imports `core.metastore`, `core.storage` or `applications`.
- Only `applications` import `core.metastore`.
- The API never imports the CLI or `core.storage`; the CLI never imports the API, the metastore or
  the broker.

## Code conventions

- No directory under `src/` or `tests/` contains an underscore. No `_impl`, `internal` or `private`
  directories; visibility is expressed by names inside modules and by `__init__.py` exports.
- In every module, public classes and functions come first, underscore-prefixed ones after.
  `tests/unit/test_conventions.py` enforces both rules.
- Values are frozen dataclasses; pydantic models only at the API and CLI edges. Operations are
  classes with explicit constructor dependencies; no module-level singletons.
- Ports are `typing.Protocol` classes owned by the package that calls them; adapters live in
  `core.metastore` and `core.storage`.
- Every domain error subclasses `huron.pkg.errors.HuronError` with a registered `ErrorCode`.
- The service is async (asyncpg, httpx.AsyncClient); the CLI is synchronous.
- Docstrings on every public class and function, in plain language.

## Skills by area

| Area | Skill |
| --- | --- |
| `src/huron/core/` | `oop-design` |
| `src/huron/applications/api/` | `fastapi` |
| `src/huron/core/metastore/`, `migrations/` | `postgresql-table-design` |
| `web/` | `svelte-core-bestpractices`, `svelte-code-writer`, `tailwind-design-system` |
| Instruction files | `writing-for-agents` |

## Gate

Run from the repository root; every command must exit 0 and radon must print nothing. `make gate`
runs all of them.

```text
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy
uv run ty check
uv run lint-imports
uv run pytest -m "not integration" --cov=src/huron --cov-report=term-missing
uv run radon cc src --min C
uv run radon mi src --min B
uv run complexipy src --max-complexity-allowed 15
uv run python scripts/check_schema_map.py
```

The gate's pytest run includes the contract tier, so it needs PostgreSQL: `HURON_TEST_DATABASE_URL`
(a server URL whose user may create databases) when set, otherwise a `postgres:16` testcontainer.
`make test` runs the unit tier alone without a database; `uv run pytest -m integration` runs the
integration tier.

## Testing standard

- Every public function and class has direct tests: happy path, boundaries, empty inputs, every error.
- Tests assert behavior, not implementation. Fakes for stores and storage; mocks only at subprocess,
  network and clock boundaries.
- Test names describe behavior and never mention plan task numbers.
- Shared fixtures live in `tests/support/` and `conftest.py` files.

## Frontend: `web/`

`web/` is the SvelteKit app (Svelte 5 runes, Tailwind 4, adapter-node): a read-only client of the
API that signs people in with the company IdP and lets them switch organizations, browse and
search. Paths in this section are repository-relative; npm commands run from `web/`, as
[web/README.md](web/README.md) describes. Load the skills of the `web/` row in
[Skills by area](#skills-by-area) before changing it: `svelte-core-bestpractices` and
`svelte-code-writer` for `.svelte` and `.svelte.ts` files, `tailwind-design-system` for styles
and design tokens.

### Sources of truth

- [docs/web-design.md](docs/web-design.md) is the binding design, with its dated "Accepted
  amendment" notes, which win over the text they follow. Read the section you change and its
  amendments first, and record a deviation as a new dated amendment there. Its sections 10 and 11
  are the history of the rewrite.
- `docs/openapi.json` is the API contract. `npm run generate:api` writes
  `web/src/lib/api/openapi.ts` from it (never edit that file), and `web/src/lib/api/openapi.test.ts`
  fails when the two drift. Routes and components import domain types from `$api/types` only.
- CLI hints build their commands with `web/src/lib/cli.ts`, whose `quote()` writes control and
  format characters as `$'…'` escapes; check each verb and flag against
  `src/huron/applications/cli/commands/`.

### The BFF

- The browser talks only to the SvelteKit server. The server keeps each session in its own memory
  (`web/src/lib/server/sessions.ts`) and calls the API with that session's Huron token, which
  never leaves the server: `locals.user` holds plain data, `api(event)` is the only way to the
  token, and no load returns a client, a session or a token.
- The web is read-only: its API client sends GETs only, apart from the token exchange. Where the
  signed-in user could change something, a `CliHint` shows the `huron` command.
- The server names and sets its cookies in `web/src/lib/server/cookies.ts`: `huron_session` (an
  opaque id) and `huron_oidc_<state prefix>` (a sealed sign-in in progress). `huron_org` (the
  remembered organization) takes its name and attributes from `web/src/lib/organization-cookie.ts`,
  which both sides import: only the browser writes it, in `afterNavigate`. All three carry
  `Path=/` and `SameSite=Lax`, and on https `Secure` and the `__Host-` prefix.
- One process holds every session, so a deployment runs one replica or sticky sessions, and a
  restart or an out-of-memory kill signs everyone out.
- `POST /logout` answers 403 unless `Origin` is the web's own: every sign-out control is a plain
  same-origin form POST, and a proxy in front of the web passes `Origin` through.
- `handleError` (`web/src/hooks.server.ts`) logs, and gives a reference, for status 500 and above
  only. Error pages take their copy from `errorCopy(status, code)` (`web/src/lib/error-copy.ts`),
  never from `page.error.message`.

### The API seam

- Server code reaches the API through `api(event)` (`web/src/lib/server/guard.ts`): one
  `HuronApi` (`web/src/lib/server/huron-api.ts`) per request, which memoizes GETs by URL. Child
  loads call `api(event)`, never `parent()`.
- An answer is read as a stream of at most 64 MiB (`MAX_ANSWER_BYTES`; more is a 502) and parsed
  with plain `JSON.parse`. Only `catalogSchema`, `collectionSchema` and the Schema tab's
  `exactOverride` keep the digits of integers past 2^53 (`parseExactly`); those digits live on the
  objects `parseExactly` returned and are lost on any spread or copy.
- `fail(event, error)` turns a failed read into the page's outcome in fixed copy, never the API's
  `detail` or `context`; a 401 ends the session.
- Loads return view models of plain values built on the server, never API JSON whose keys users
  choose (metadata, labels, `schema_override`, schema documents): devalue throws on an own
  `__proto__` key. Test each load's data with `serializePageData`
  (`web/src/lib/testing/page-data.ts`).

### Bounds

Every string and list a page draws from user data is bounded, except organization and catalog
display names and descriptions and the LDAP group names of grants: only admins write those, and
pages draw them whole. `shortened` (`web/src/lib/format.ts`) cuts text, ending it in "…". Keep
these bounds, and reuse them on new pages:

- Collections (`web/src/lib/collections.ts`, `web/src/lib/metadata.ts`): titles `TITLE_LENGTH`
  200 (h1, `<title>`, namespace rows, search results); the header's description
  `HEAD_DESCRIPTION_LENGTH` 5,000; on the Overview `VALUE_LENGTH` 5,000 per text within
  `TEXT_BUDGET` 100,000, `PROBLEM_LENGTH` 1,000 per problem, `MAX_ITEMS` 50 per array, object,
  label list and problem list, and `MAX_VALUES` 1,000 in all. A label chip links only when its key
  and its value each hold at most `MAX_LABEL_LENGTH` (100) code points.
- Schema tables (`web/src/lib/schema-view.ts`): `MAX_SCHEMA_FIELDS` 200, `SCHEMA_TEXT_LENGTH`
  1,000, `MAX_ENUM_VALUES` 50, `SCHEMA_JSON_LENGTH` 262,144.
- Search (`web/src/lib/search.ts`, reusing `MAX_LABEL_LENGTH` and `TITLE_LENGTH` from above): `q`
  at most `MAX_TEXT_LENGTH` (200) code points, a label's key and value `MAX_LABEL_LENGTH` (100)
  each and at most `MAX_LABEL_FILTERS` (10) filters, all checked before any API call. Results cut
  titles to `TITLE_LENGTH` and descriptions to `DESCRIPTION_LENGTH` (300), and show at most
  `MAX_RESULT_LABELS` (12) chips and `LABELS_LENGTH` (300) code points of labels per row.
  `sharedSearch` gives each organization link its share of `SHARED_QUERY_LENGTH` (64 KiB), at
  least `LINK_QUERY_LENGTH` (1 KiB).
- Organization search: the first `ORGANIZATION_CATALOGS` (50) catalogs and `CATALOG_RESULTS` (5)
  results from each (`web/src/lib/search.ts`), 4 requests at a time (`CONCURRENCY`) and one 8 s
  deadline (`DEADLINE_MS`) that aborts what is late (`web/src/lib/server/org-search.ts`); the
  catalog listing and `draftAccess` are ordinary reads before it starts.
- Explorer (`web/src/lib/server/explorer.ts`, `web/src/lib/design/components/Explorer.svelte`):
  trail levels load 4 at a time (`TRAIL_CONCURRENCY`), levels above the page's namespace list 10
  collections (`ANCESTOR_COLLECTIONS`), and only the first 8 levels indent (`MAX_INDENT`). A level
  that fails says "Couldn't load", with Retry once scripts run. From lg the column is sticky and
  scrolls itself (`--max-height-explorer`, in `web/src/lib/design/app.css`), bringing the page's
  node into view through its own `scrollTop`, with no `role` or `tabindex`.
- Lists page by `next_cursor` (`web/src/lib/paging.ts`): 50 rows (`LIST_PAGE_SIZE`), 25 for
  searches (`SEARCH_PAGE_SIZE`).
- Crafted search addresses are an accepted residual (the longest canonical search is about
  26.6 KB; a 4.7 MB catalog search page was measured); the design's section 5 says why.

### Shell and pages

- `page.data.organization` names the shell's organization: the organization and catalog layouts
  return it, and every other page returns `requestCookies(event).rememberedOrganization()`. On an
  error page the shell shows the organization it last wrote to `huron_org`, else the `(app)`
  layout's validated `rememberedOrganization`. Shell organizations are `{ id, name, display_name }`.
- Every in-app link is built with `resolve()`, whose route ids include the group
  (`resolve('/(app)/orgs/[org=segment]', { org })`). During server rendering it gives
  page-relative hrefs, so `kit.paths.relative` stays at its default. Links to `+server.ts`
  endpoints carry `data-sveltekit-reload`.
- Route parameters use the matchers in `web/src/params/` (`segment`, `dotted`, `uuid`), with no
  unmatched twin and no catch-all route: an address no route matches gets the root 404 page.
- The organization switcher keeps no query from a catalogs list, and from a search page keeps the
  search as `readSearch` reads it, bounded by `sharedSearch`. The account menu's button reads
  "Sign out", as everywhere else.
- `aria-current="page"` marks a link to the page shown, and `"true"` the section it belongs to.
  User text is rendered as text, never with `{@html}`. Scroll containers other than the explorer
  use `ScrollRegion`.
- Without scripts the theme toggle is hidden (`web/src/app.html` adds a `js` class; the `no-js`
  variant hides it). The global focus rule stays unlayered, the bottom navigation keeps 4px below its
  links, and `html` keeps `scroll-padding-bottom` (0.75rem, 4.5rem below md), so focus rings show
  whole.
- In forced colors, controls drawn by a fill have a transparent border, and a sub-navigation
  underlines its current tab only. Share paths offer a line break after each `/` (`<wbr>`).
  Without a clipboard, `CliHint` shows the code block below its own `@md` and the select-on-focus
  field from `@md`.

### Gate and tests

Run from `web/`; every command must pass, `npm run check` with 0 errors and 0 warnings. The Python
gate above runs when Python changes.

```text
npm run check
npm test
npm run lint
npm run build
npm run test:e2e
```

- Server modules' test files start with `// @vitest-environment node`; component tests are
  `*.svelte.test.ts` with `@testing-library/svelte`.
- `npm run test:e2e` builds, then starts the fake IdP (port 8199), its fault proxy (8197), the API
  on the memory store (8198) and the build (`http://localhost:4173`); `npm run demo` uses the same
  backend ports and 5173. One stack runs at a time; for a private one set `HURON_E2E_IDP_PORT`,
  `HURON_E2E_PROXY_PORT`, `HURON_E2E_API_PORT`, `HURON_E2E_WEB_PORT` and `HURON_DEMO_WEB_PORT`.
- Every e2e test imports `test` from `web/e2e/support/harness.ts`: its automatic fixture signs
  out each session the test signed in to, so the cap of 10 sessions per user never ends a running
  test's session.
- Faults are injected only in `web/e2e/faults/`, signed in as `oscar`; that project runs one test
  at a time. `paula` signs in only for the walks of `web/e2e/layout.test.ts`.
- `web/e2e/support/fixture.mjs` holds the seeded data and the expectations: derive assertions from
  it (`titleOf(identifier)`, `visibleOrganizations(user)`). Its incompatible-override case is
  `space-weather.alerts.storm-count-2024`, an incomplete collection whose schema override no
  longer fits the catalog's schema. `make app` seeds the same fixture through Keycloak, so every
  user it names as a creator is a user of `scripts/keycloak/company-realm.json` with the password
  `password`.
- Locate elements by role and accessible name; the shell, the switcher and the explorer have
  `toMatchAriaSnapshot` tests (there is no axe-core).

### Visual QA

After a visible change, capture each changed page with Playwright at 390×844, 816×900 and
1440×900 (the explorer also at 1024 wide), light and dark, and look at every capture: nothing
scrolls sideways, long identifiers and paths wrap, and focus rings show whole. Check filled
controls and sub-navigations in forced colors.

### Offline

Nothing is downloaded or installed: no `npm install`, `npx --yes` or `npx playwright install`, so
no new dependencies, and Chromium is Playwright's only browser. The harness runs the API with
`uv run --offline --no-sync`. The `svelte-code-writer` autofixer (`npx @sveltejs/mcp`) is not
installed: report it as not run.
