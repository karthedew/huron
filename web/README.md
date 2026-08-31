# Huron web

SvelteKit frontend. Built against `design/frontend.html`; nothing here amends that document.

## Status: interactive frontend prototype

There is no API yet — `openapi/v1.json` is first published at **P1** (`design/roadmap.html`).
Every page therefore renders synthetic fixtures through a single module, `src/lib/api/`, which
is the only place in this app where a domain type is written by hand. See
[`src/lib/api/README.md`](src/lib/api/README.md) — that file explains how the seam is removed.

What exists: a responsive Databricks-inspired workspace, organization switching, Tailwind CSS
design tokens, light and dark modes, catalog search and structural browsing, a guided raw/bronze
ingestion flow, organization membership and Grafana-style role bindings, project settings,
retention consequences, admin health, keyboard/screen-reader affordances, and tests.

What does not exist: real data, authentication, or write operations. Mutating flows stop at the
API seam and say so in the interface; they do not pretend that a fixture-backed action persisted.

## Run

```
npm install
npm run dev          # http://localhost:5173
```

Note: `npm install` must run on the machine you develop on — the dependency tree contains
platform-native binaries (esbuild, rollup).

## Checks

```
npm run check        # svelte-check, TypeScript strict
npm test             # vitest unit tests
npm run test:e2e     # Playwright smoke (npx playwright install once, first time)
npm run build        # production build via adapter-node
```

## One thing to fix in the API, not here

Organization slugs sit at the root of the URL space so that deep links look like
`/{org}/{project}/{dataset}/{release}`. That means an organization slugged `admin`, `browse`,
`ingestion`, `settings`, `account`, `queue`, `product`, or `snapshot` would be shadowed by this app's own routes and be
permanently unreachable. `src/lib/reserved-slugs.ts` records the list and a test fails if a new
root route is added without reserving it — but the actual enforcement belongs in slug validation
at organization creation (P1). Until the API refuses these names, this is a latent trap.
