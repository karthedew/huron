# The seam

**Everything in this directory is scaffolding with a scheduled demolition date.**

`design/frontend.html` §1 specifies that the API client is _generated_ from `openapi/v1.json`,
so that a contract change breaks the TypeScript build. That spec does not exist yet — the API
lands in **P1** (`design/roadmap.html` §2), which is where `openapi/v1.json` is first published.

Until then this directory is the only place in the app where a domain type is written by hand.
Pages import from `$api/client` and never construct a shape of their own. When P1 ships:

1. Generate the client from `openapi/v1.json` into `src/lib/api/generated/`.
2. Delete `types.ts` and `fixtures.ts`.
3. Repoint `client.ts` at the generated client, keeping its function signatures.

If step 3 requires touching anything _outside_ this directory, the seam leaked and that is a
bug worth fixing rather than working around.

## Rules while the seam exists

- No component or route may define a domain type. Import it from `$api/types`.
- No component or route may import `fixtures.ts` directly — only `client.ts` may.
- Fixture data is obviously synthetic. It is not a demo dataset and must never be
  mistaken for one; it exists to prove layout and states render.
