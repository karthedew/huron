# API seam

The web is a read-only client of the Huron API (`src/huron/applications/api`); its contract is
`docs/openapi.json`.

- `openapi.ts` is generated from `docs/openapi.json` by `scripts/generate-api-types.mjs`: one
  export per `components.schemas` entry, every `Page_X_` as `Page<X>`. Never edit it; run
  `npm run generate:api` after the contract changes. A Vitest test fails when it drifts.
- `types.ts` is what routes and components import: friendly aliases (`Organization`, `Catalog`,
  `Collection`, …), the RFC 9457 `Problem` document (not part of the OpenAPI components), JSON and
  JSON Schema value types, and the role, scope and audit-action unions with a test against the
  Python vocabulary. Routes and components import domain types only from `$api/types`.
- The client is server-only: `$lib/server/huron-api.ts`, reached through `api(event)` in
  `$lib/server/guard.ts`. It validates every answer against these types, calls the API with the
  session's Huron token from the global fetch without cookies, and maps failures to fixed copy
  with `fail(event, error)`.
- The Huron token and the session record never leave `$lib/server`: `locals.user` holds plain
  data only, and nothing returns a client or a session from a load.
