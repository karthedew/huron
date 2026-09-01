# Frontend agent instructions

These instructions apply to all work under `web/`.

## Sources of truth

- Read `../design/frontend.html` before changing frontend behavior or architecture. The design
  record is authoritative; if the implementation disagrees, update the implementation. If a new
  product or architecture decision is required, record it in `design/` in the same change.
- Read `README.md` for the frontend's current delivery status and available commands.
- Read `src/lib/api/README.md` before changing data access, domain types, or fixtures.
- Treat `../design/roadmap.html` as delivery context, not as permission to implement future phases.
  Keep the requested change within the currently available backend contract.

## Required frontend skills

### Svelte

Before planning, reviewing, analyzing, creating, or editing a Svelte component or Svelte module
(`*.svelte`, `*.svelte.ts`, or `*.svelte.js`), read and follow both project-local skills in full:

- `../.claude/skills/svelte-core-bestpractices/SKILL.md`
- `../.claude/skills/svelte-code-writer/SKILL.md`

Use `svelte-core-bestpractices` to guide component structure, reactivity, events, snippets, styling,
context, and modern Svelte 5 syntax. Read the skill's referenced topic files when they apply to the
task.

Use `svelte-code-writer` for Svelte and SvelteKit documentation lookup and code analysis:

- Run `npx @sveltejs/mcp list-sections` and fetch the relevant documentation when syntax, runtime
  behavior, or framework conventions are uncertain.
- Run `npx @sveltejs/mcp svelte-autofixer <path> --svelte-version 5` on every changed `*.svelte`
  file before finalizing it. Review the output, apply valid findings, and rerun until no applicable
  findings remain.
- Treat the autofixer as an additional Svelte-specific review, not as a replacement for the
  project's type checks, tests, formatting, build, or browser QA.

### Tailwind CSS

Before planning, reviewing, analyzing, creating, or editing Tailwind utilities, design tokens,
component variants, responsive styles, dark-mode behavior, or Tailwind configuration, read and
follow the project-local skill in full:

- `../.claude/skills/tailwind-design-system/SKILL.md`

Use `tailwind-design-system` for Tailwind CSS v4 token architecture, reusable component patterns,
responsive behavior, theming, and accessibility. Read its files under `references/` when their
topics apply to the task.

The skill provides implementation guidance; Huron's authoritative design and existing semantic
tokens remain the product contract. Prefer the tokens and patterns in `src/lib/design/tokens.css`
and existing design components over copying generic example tokens or introducing one-off values.

## Frontend lifecycle

Follow this lifecycle for every frontend task. Scale the depth to the size and risk of the change,
but do not skip applicable gates.

### 1. Discover

- Restate the user-visible outcome and identify the affected route, component, store, API function,
  and tests.
- Load both required Svelte skills before analyzing Svelte files, including while operating in Plan
  mode.
- Load the Tailwind design-system skill before analyzing or changing Tailwind classes, design
  tokens, theming, responsive behavior, or shared component styles, including in Plan mode.
- Inspect the existing implementation and nearby tests before proposing or writing code.
- Check the authoritative design and existing design-system components before introducing a new
  interaction, visual pattern, token, or abstraction.
- Identify all important states: loading, empty, success, validation failure, server failure,
  unauthorized or undiscoverable, and narrow/mobile layouts.
- Preserve unrelated working-tree changes. Do not rewrite or clean up code outside the requested
  scope.

### 2. Plan

In Plan mode, do not edit files or run mutating commands. Produce an implementation-ready plan that
includes:

- the user flow and acceptance criteria;
- the exact files or symbols expected to change;
- component and route boundaries, including server-versus-browser responsibilities;
- API-seam or fixture changes, if any;
- accessibility, responsive, dark-mode, and failure-state behavior;
- unit and end-to-end test coverage;
- verification commands and material risks or open decisions.

Resolve questions by inspecting the repository where possible. Ask the user only when a missing
product decision would materially change the result.

### 3. Implement

- Make the smallest cohesive change that fully delivers the requested behavior.
- Follow Svelte 5 and SvelteKit conventions already used in this repository. Keep TypeScript strict;
  do not use `any`, unchecked casts, or suppressed diagnostics to force a build through.
- Prefer existing components in `src/lib/design/components/` and tokens in
  `src/lib/design/tokens.css`. Add a shared component only when more than one concrete use needs it
  or when it owns a meaningful interaction or accessibility contract.
- Keep route loading and server-only behavior in the appropriate `+page.ts`, `+page.server.ts`,
  `+layout.ts`, `+layout.server.ts`, or `+server.ts` module. Do not move secrets or privileged
  credentials into browser code.
- Keep rendering deterministic and SSR-safe. Guard browser-only globals and do not access them
  during server rendering.
- Use semantic HTML, native controls, visible focus, accessible names, and keyboard-complete
  interactions. Do not make pointer hover the only way to discover or operate functionality.
- Cover changed behavior in the same change. Test user-observable contracts rather than internal
  implementation details.
- Do not add speculative abstractions, compatibility shims, temporary TODOs, commented-out code,
  or comments that narrate obvious implementation steps.

### 4. Respect the API seam

Until the generated OpenAPI client replaces the prototype seam:

- Routes and components import domain data through `$api/client` and domain types through
  `$api/types`.
- Only `src/lib/api/client.ts` may import `src/lib/api/fixtures.ts`.
- Do not define domain types in routes or components and do not construct fixture-shaped domain
  objects there.
- Mutating fixture-backed flows must say clearly that they did not persist. Never imply a synthetic
  action changed real data.
- Preserve the API's security semantics: undiscoverable resources render as 404, never as a UI that
  reveals a forbidden resource exists.
- Preserve keyset pagination shapes and projection-watermark/staleness information where the design
  requires them.

### 5. Verify

Run commands from `web/`. The normal completion gate is:

```bash
npm run check
npm test
npm run lint
npm run build
```

- Format only the files changed by the task before running `npm run lint`.
- Run the `svelte-code-writer` autofixer gate on every changed Svelte component before the normal
  completion gate. Record any remaining finding and why it is not applicable.
- Run `npm run test:e2e` for changes to routes, authentication, navigation, forms, responsive
  behavior, or other user-visible interactions. If Playwright cannot run because its browser or a
  required service is unavailable, report that explicitly; do not weaken, skip, or delete the test.
- Add Vitest coverage for pure behavior and API-seam contracts. Add Playwright coverage for
  cross-route behavior and interactions that must work in a real browser.
- Never add a skipped test, loosen an assertion, or suppress a diagnostic merely to make a gate
  green.

### 6. Perform visual QA

For visible UI changes, inspect the running app in a real browser after automated checks:

- verify a narrow mobile viewport, the compact workspace viewport around 816 px, and a wide desktop
  viewport;
- check light and dark modes;
- exercise the primary flow with keyboard navigation and confirm focus remains visible;
- check loading, empty, long-content, validation, and error states affected by the change;
- confirm there is no clipping, unexpected horizontal scrolling, hydration error, or inaccessible
  icon-only control.

Prefer fixing the underlying layout or interaction contract over adding viewport-specific patches.

### 7. Hand off

Finish with a concise report containing:

- the user-visible result;
- the important files changed;
- the verification commands run and their outcomes;
- any check or browser scenario not run, with the reason;
- remaining risks only when they are concrete and relevant.

Do not claim completion while an applicable gate is failing.

## Frontend invariants

- The UI holds no API keys, OIDC tokens, or privileged credentials. Session handling remains
  server-side and tokens never go into `localStorage`.
- Browse and search routes remain server-renderable and directly addressable by stable URLs.
- Candidate versus published state, stale data, retention consequences, and synthetic versus real
  data remain visually explicit.
- Accessibility, responsive behavior, and dark mode are acceptance criteria, not optional polish.
- Root-level routes must remain synchronized with `src/lib/reserved-slugs.ts` and its test so an
  organization slug cannot be shadowed silently.
