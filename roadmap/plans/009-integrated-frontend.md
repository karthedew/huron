# Phase 009: actual backend-integrated complete MVP frontend

Status: BLOCKED — 001 fixture probe and 002–008 backend/SDK prerequisites; integrated acceptance unrun.

## Context and outcome

Current SvelteKit frontend is fixture-backed behind `$api/client`; API types are
handwritten UI projections, not authoritative DTOs. Current web/package.json provides
check/test/lint/build/test:e2e. web/playwright.config.ts uses 4173 and preview signed
session secret; development serves 5173. A screenshot or fixture mutation is not
backend integration. Complete MVP includes actual UI for all delivered backend features.

Target Organization → Collection → Dataset (Collection replaces Project); immutable
full-copy release per push, no revision/tag step; required metadata/schema and
additive-only extensions published by org owners; later metadata omission inherits
exact pinned base pair, no latest adoption. Google sessions and external directory
membership authority are separate from Huron role bindings. All Huron requests via
$api/client; credentials and session resolution server-side, no browser token storage.

Fresh deployment approved 2026-10-06: no legacy Project/account/upload/revision/tag
data conversion is MVP acceptance. Schema bootstrap remains required in backend
phases; nonempty targets refuse with operator action, never reset unrelated data.
This policy-only reconciliation authorizes no production UI or Svelte code changes.

## Prototype evidence

No session/projection prototype run. 001 web owner owns the early fixture-only
session/topology probe, with no dependency on this phase or 003 receipts, in copied ignored
`roadmap/prototypes/web-session/`, declares scripts, runs from there `npm run check`,
`npm test`, `npm run lint`, `npm run build`, `npm run test:e2e`; named-session local
Playwright CLI confirms SSR browse/search, same-origin cookie/CSRF and tus upload
without exposing credentials. Its signed session/OIDC, directory and HTTP fixtures
and proposed DTOs establish topology feasibility only, not integrated authentication
or authoritative wire compatibility.

This phase owns the later integrated session/projection qualification in slice 1,
after 002–008 and specifically 003 Google/directory authority receipts. Compare their
authoritative OpenAPI DTOs against actual frontend projections; enumerate missing
counts/reverse cursors/slug resolutions rather than inventing fields. Record real
Google login/session and separate directory/Huron authorization acceptance here.
Carry early 001 route candidates forward, then resolve exact files before each slice;
do not require this phase's integrated receipt to enter 001, 002 or this phase.
Do not inspect/change arbitrary .svelte files without both local Svelte skills.

## Exact scope and ownership

- `web/src/lib/api/{client,types,fixtures}.ts`, proposed generated/ wire client and
  internal transport/mapping/tus modules, README; only client.ts may import fixtures.ts.
  002/008 OpenAPI artifact/generation check integrates TypeScript drift here.
- `web/src/hooks.server.ts` if present or create, server session module,
  `web/src/routes/{login,logout,signup}/` server actions and UI; existing preview
  session fixture is explicitly replaced for integrated mode, not production auth.
- `web/src/routes/[org]/` Collection rename: inventory `[project]` routes/params,
  links/loaders/components and tests before move to `[collection]`; root routes
  synchronized with `web/src/lib/reserved-slugs.ts` and its test.
- `web/src/routes/{browse,ingestion,admin,settings,account}/`, root search route;
  server loaders/actions and relevant lib components for exact operation matrix below.
   This is a bounded feature inventory; use 001's candidate inventory and resolve the
   actual file/symbol list against delivered contracts here before the owning slice
   is READY, not a license to rewrite every component.
- `web/e2e/`, existing API seam/Vitest fixtures, `web/playwright.config.ts`, package
  generation script. Update Compose same-origin frontend wiring from 002 only if
  required with endpoint ownership. No real provider secrets in test code/logs.
- Remove fixture-backed production handlers, obsolete revision/tag and configurable
  policy UI/DTOs/tests once their real replacements exist. Preserve useful mock data
  for explicit component tests; synthetic operations visibly say not persisted.
- Later array routes (product/snapshot/queue) remain clearly future capability;
  do not invent backend functionality to keep prototype screens interactive.

No credentials in localStorage/sessionStorage; migrate existing prototype state by
discarding only owned ephemeral fixture state, not user data. No fake writes. No
compatibility shim for unsupported fields/old Project URLs unless phase explicitly approved.

## Interfaces and implementation examples

Current contract is `$api/client` plus `$api/types` presentation values. Proposed
loader/service shape, illustrative until prototype resolves actual exports:

```typescript
// server loader: request-scoped transport, session never serialized into page data
const page = await api.search({ text, cursor }, { fetch, session });
return { results: page.items, nextCursor: page.nextCursor, freshness: page.freshness };
```

Map generated wire types deliberately; keep URLs/errors/keyset/CSRF/retry/tus in
web/src/lib/api. Browser uses same-origin session-backed requests; Huron bearer
credentials remain on server. Avoid process-global user transport and SSR shared
state. Search/browse URL owns query/cursor, SSR-safe, undiscoverable→404. Opaque keyset
cursor has no invented reverse/count fields. Release progress distinguishes upload,
verification/copy, publication and committed readable; resume/cancel/error can recover.

Approved stale-base policy: keep base and exact metadata/schema immutable during
upload. Backend atomically compares expected base/current head in catalog publication
under qualified serialization, including expected empty head for first-push races.
An uncommitted loser yields typed conflict (illustrative HTTP 409), hidden candidate,
no published lineage/receipt and recoverable cleanup, never a success notification.
Show caller review and explicit retry against a newly resolved newer base with a new
operation identity/fingerprint; no automatic repin, implicit merge/rebase or changed
input under old identity. Omission then inherits the newly pinned exact pair, not
latest implicitly. After authorization, already-COMMITTED same-identity replay shows
the original outcome even after head advances. Preserve nondisclosure and publication
authorization rechecks. Wire mapping and DB/FS crash/serialization proof remain
unqualified prerequisites, not implemented UI behavior.

Operation-to-screen acceptance matrix (all required, not backend-only follow-up):

| Backend operation | UI behavior |
| --- | --- |
| login/session/logout | Google redirect, current account, expired/unauthorized state; session/CSRF server-side |
| organization/collection/dataset CRUD/descriptions | browse/create/edit with current permission/version errors and Collection naming |
| schema+extension publish/list/read | org-owner authoring/publishing, additive conflict errors, immutable version/digest display |
| metadata validate/create/update submission | required/scientific fields, exact selected schema, omitted/null/empty distinctions and pinned-base inheritance |
| tus/upload/cancel/publish/read | across-file progress, sequential PATCH, resume, explicit add/delete/replace, copy/commit states, readable receipt/download; stale-base conflict review/new-identity retry and committed replay after head advancement |
| search/export | addressable SSR keyset results/freshness; pinned export and separately labelled live titles |
| role bindings | scoped simple roles/inherited facts, no configurable policy feature |
| directory gateway | group/create/add/remove exposed only when external authority permits; Huron owner cannot bypass external huron-admin |
| operations/status errors | accurate failure/capacity/retry messages, no hidden-resource leakage or fabricated admin metrics |

## Serial task slices

1. Pending: integrated session/projection qualification after 002–008 (including 003
   Google/directory receipts), then generated wire+mapping/session/same-origin seam;
   real login/logout and API-error boundary. Exact routes/hooks/API files, all web
   gates and auth integration. This phase owns the receipt, not 001.
2. Pending: Collection browse/descriptions/schema registry/metadata forms, replace
   named fixtures, accessibility and permission/version cases. All web gates.
3. Pending: Raw submit/tus/resume/cancel/committed receipt/download/export; server
   session-safe streaming and conflict states. All web + real backend workflow gates.
4. Pending: PostgreSQL search and role/directory gateway, truthful errors/freshness;
   ensure every operation matrix row covered by real API interaction. All gates.
5. Pending: complete responsive/light-dark/keyboard/state QA and production build,
   remove obsolete production fixture paths, regeneration drift. Independent final rerun.
One writer/reviewer per slice, skills below, max three reviews. Resolve actual file
inventory before dispatch; preserve unrelated dirty client.ts/types.ts/fixtures.ts work.

## Skills

`.agents/skills/svelte-code-writer/SKILL.md`,
`.agents/skills/svelte-core-bestpractices/SKILL.md`,
`.agents/skills/tailwind-design-system/SKILL.md`,
`.agents/skills/playwright-cli/SKILL.md`, `.agents/skills/fastapi/SKILL.md` for API
transport review, `.agents/skills/implementation-plan/SKILL.md`; OOP and PostgreSQL
skills additionally if backend changes require replanned ownership.

## Acceptance and complete applicable gates

Web cwd, locked npm ci and supported Node (local 22.23.2 PATH
`/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH`):

```sh
npx @sveltejs/mcp svelte-autofixer <path> --svelte-version 5
npm run check
npm test
npm run lint
npm run build
npm run test:e2e
```

Autofixer every changed .svelte, apply valid findings then rerun; format only owned
files. Playwright CLI installed 1.62.1 local skill, named session `raw-mvp-009`:
`npx --no-install playwright cli -s=raw-mvp-009 open http://localhost:4173` after
proving endpoint ownership and CLI syntax against local skill. Record screenshots/
DOM/console/network in ignored artifacts: mobile, 816px, wide, light/dark, keyboard/
focus, loading/empty/long content/validation/error/unauthorized, overflow/hydration.
Use only named owned session cleanup, never kill unrelated browsers/services.

Root: `make docs`, `git diff --check`,
`uv run python scripts/check_openapi.py --check` with TypeScript regeneration drift
owned here before execution. Backend integration prerequisites real PG16/API/Raw
volume/local OIDC/directory and approved Google config, owned 4173; e2e must exercise
actual service persistence and reload, not preview fixtures. Fixture mode explicitly
labelled, no fake mutation success. SDK example output matches 008.

If any Python/backend/session transport changes: root `make lint`,
`uv run pytest -m unit --cov=src/huron --cov-report=term-missing`,
`uv run pytest -m contract`, `uv run pytest -m integration`; Raw streaming/publication
changes add `make test-acceptance` (>=25 GiB, isolated Linux/Podman integration runner
and historical object). Preserve 96.01%, imports/complexity/duplication (0.80 no
new/growing clones), radon C+/MI B+ findings, no skips/xfails/weaker assertions. Reuse
API seam/behavior/e2e fixtures; mocks only external boundaries. Independent baselines
and reviewer reruns with exits/versions/logs and coverage; missing infra is BLOCKED.

## Blockers and readiness

Entry: 001 fixture-only session/topology evidence and candidate route inventory;
002 stack, 003 identity/Google/directory receipts, 004 catalog/schema, 005/006
transfer/release, 007 search/export, 008 SDK examples, independent plan review and
separate execution authorization. Per-slice: resolve exact component/route ownership;
slice 1 produces integrated session/projection evidence required by slices 2–5.
Completion: every operation matrix row and same-origin/auth-provider behavior must
have real integrated receipts and complete gates. These outputs are not entry gates.
Independent review before `/implement-markdown roadmap/plans/009-integrated-frontend.md`.

## Execution ledger

Planning writer attempt 1; no Svelte code/QA/prototype executed; review count 0.
Future parent logs model/role/session/times/commands, minute polls, 15-minute progress
and serial writer/reviewer exclusion. No fixture screenshot counted as MVP PASS.

## Escalation / final receipt

BLOCKED draft. Final receipt reports every operation matrix row, real persistence,
responsive/accessibility state evidence and limitations. No completion while any
delivered backend feature is represented only by a synthetic UI action.
