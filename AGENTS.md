# Repository agent instructions

Huron is a datalake for scientific projects. Read this file before working in the
repository. `CLAUDE.md` adds Claude-specific command guidance; shared engineering
rules belong here so the two files do not maintain competing copies.

## Design authority and migration status

- `design/` is the architecture record; `design/roadmap.html` tracks implementation
  status. Read the relevant documents and inspect the code before planning work.
- Core domain subpackages own their values, rules and reusable workflows;
  applications expose their public interfaces. Future compute, client and
  transformation capabilities remain planned. Migration evidence is recorded in
  `docs/history.md#domain-owned-core`.
- These agreed boundaries and ingestion rules supersede conflicting older design
  descriptions. Reconcile affected design pages, imports, tooling, tests, and
  entry points when implementing the relevant migration. Do not silently change
  unrelated runtime behavior or mark planned capabilities as built.
- Explicit task scope governs: a review or documentation request does not authorize
  implementing the architecture. Preserve unrelated working-tree changes.

## Package boundaries

```text
src/huron/
  core/
    foundation/    Shared errors, canonical JSON, IDs, names, retry and clock contracts
    security/      Authentication, identity, authorization and their workflows
    catalog/       Hierarchy, dataset configuration, layer rules and discovery
    raw/           Ingestion, revision publication/reads and expiry
    metastore/     PostgreSQL and in-memory adapters
    rawstore/      POSIX storage adapters
  applications/    Runnable entry points, transport, configuration, and wiring
  schema/          Shared document contracts and validation
```

### Domain-owned workflows and adapters

- Colocate domain objects, invariants, authorized operations and consumer-owned
  interfaces with the domain responsible for them. Keep focused operations rather
  than an all-purpose Core or repository class.
- Public scientific operations accept authenticated actors, IDs, commands and
  values; return domain results/receipts; and enforce authorization, discovery and
  input access themselves. Early HTTP guards do not replace these checks.
- Security establishes identity through credential workflows. Bootstrap, expiry and
  operator maintenance use explicit trusted deployment authority. Security consumes
  its own narrow catalog-fact projections; full hierarchy entities belong to Catalog.
- Raw owns storage-first publication and its single-connection transaction recording
  revision, session outcome, audit, outbox and retry receipt.
- Inject storage, persistence, clocks and external capabilities through interfaces
  owned by their consumers. One adapter may structurally satisfy several interfaces;
  verify conformance at application wiring. Domains decide the workflow and adapters
  perform I/O, locking and atomic persistence.
- Domain packages exclude HTTP request/response types, deployment settings, concrete
  adapters, web frameworks, database drivers, storage SDKs and compute runtimes.
  Security may use credential-related HTTP/cryptographic libraries. Concrete
  Metastore and Rawstore implementations may use their required infrastructure libraries.
- Foundation contains genuinely shared primitives, not domain workflows or future
  capabilities. Retire unused scaffolding and redundant implementation while preserving
  useful pure rules, supported contracts and unique behavioral evidence.

### `applications/`: expose and run core

- Own API, worker, reconciler and operator-command entry points, as they are built.
- Read settings, construct concrete adapters, inject core services, and manage
  process startup/shutdown and resource lifetimes.
- Own transport details: HTTP parsing and serialization, credential extraction,
  cookies/CSRF, queue consumption, command arguments and terminal output.
- Resolve credentials through Security and pass the resulting actor to domain
  operations. Translate domain results/errors into transport-specific responses.
- Do not implement reusable business workflows here. Applications must not import
  sibling applications; share behavior through Core's public interfaces.

### Dependency rules and OOP

- Direction: `applications → core → schema`. Within Core, the permitted direct
  Huron dependencies are:

  | Owner | May import |
  | --- | --- |
  | `foundation` | No Huron packages |
  | `security` | `foundation` |
  | `catalog` | `security`, `foundation` |
  | `raw` | `catalog`, `security`, `foundation`, `schema` |
  | `metastore` | `catalog`, `raw`, `security`, `foundation` |
  | `rawstore` | `schema` |

- Cross-package callers use published interfaces: root operations and supported
  value/error/port/codec modules. `_impl` subtrees are private. Applications import
  concrete adapters for composition/lifecycle, not for re-exported domain values.
- Import-linter enforces declared edges, sibling acyclicity including type-only
  imports, exhaustive Core ownership, private surfaces and framework exclusions.
  Domain-to-adapter dependencies are forbidden even indirectly. Keep `core.__init__`
  minimal and Schema independent. These are package-level rules, not a requirement
  that every private implementation module form a DAG.
- Favor object-oriented design through encapsulation and composition: meaningful
  methods, controlled state changes, small interfaces and injected collaborators.
  Immutable domain objects are encouraged where useful. Keep pure calculations as
  functions when an object adds no responsibility. Avoid inheritance hierarchies,
  generic managers, and classes that merely wrap unrelated functions.
- The scientist-facing Python SDK calls the backend; it does not import server core
  or require server storage dependencies. Local validation may share lightweight
  contracts, but the backend remains authoritative.

## Scientific workflow contracts

- Dataset creation establishes identity and stable configuration. Getting a dataset
  retrieves that identity; each successful Raw upload creates a new immutable revision.
- Proposed Raw client surface: `dataset.upload(source=..., metadata=...)`, accepting
  a file, files or a directory, with required revision metadata. Validate metadata
  with Pydantic in the client and again on the backend. Verify paths, sizes, checksums
  and actual transfer completeness separately.
- Each Raw revision contains exactly that submission's complete files. No automatic
  carry-forward, parent-manifest diffing, hardlink deduplication across revisions,
  or Git-like file tracking. Migration `0010_independent_raw` refuses legacy
  hardlink ledgers until their files are copied or re-ingested.
- Raw upload hides staging and commit from the normal client API. A successful return
  means committed and readable. A retry of the same upload identity must return the
  same revision; a distinct upload creates a new revision.
- Bronze processing can use the Ray-backed array engine to convert pinned Raw inputs
  into candidate Zarr data. Direct-to-Bronze ingestion records an external origin
  rather than inventing a Raw parent. Execution/storage integrations remain planned
  until implemented and verified.
- Candidate writes are not authoritative publication. Core validates and finalizes
  completed output; storage access must prevent workers from bypassing publication.
  Define recoverable crash states across storage and PostgreSQL, not an imaginary
  distributed transaction. Scientific approval, if required, is distinct from commit.
- Lineage connects exact input revisions/snapshots, processing runs and output
  snapshots. Record immutable code identity, parameters, origin, initiating actor,
  execution identity and outcomes. Publish catalog lineage with the output record
  in the same database transaction. Preserve previous chains and failed-run evidence.
- Resolve dataset ancestry on the server. The token determines identity, never a
  caller-supplied username. Authorize every input and the exact output layer/target.
- Interactive compute carries delegated scientist authority. Approved platform jobs
  may use constrained service-account authority; arbitrary user code must not inherit
  broad service-account privileges. Scope worker grants to authorized inputs and
  candidate outputs; recheck authorization at publication.
- Cross-project derivations must respect output classification and disclosure policy.
  Lineage does not grant source access; filter inaccessible lineage details.

## Skills by area

Read the actual `SKILL.md` before applying a skill. Repository skills live under
`.claude/skills/<name>/SKILL.md`; `.agents/skills/` also contains agent-facing copies.
Do not assume the copies or their methodology are identical. Use the applicable
available copy, report material discrepancies, and follow explicit user scope.

| Area or task | Skills to use |
| --- | --- |
| Writing, designing, refactoring or reviewing code in `core/` | Project-local `oop-design` |
| Architecture, boundary changes, structural review | `codebase-design`; inspect whether its methodology is implemented before relying on it |
| Sharpening a plan or design by interview, updating `CONTEXT.md` and ADRs | `grill-with-docs`, which calls `grilling` and `domain-modeling` |
| Checking plans and roadmap claims against implementation | No separate skill; `/design-plan` Phase 0 and Phase 5 specify the method inline |
| API-service code: endpoints, dependencies, request Pydantic models, streaming, HTTP errors and wiring | `fastapi` exclusively for `applications/api` |
| PostgreSQL adapters, schema, migrations, indexes, constraints and transaction design | `postgresql-table-design` |
| Non-HTTP application entry points | Capability-specific guidance for the entry point; apply `oop-design` to accompanying `core/` changes |
| Svelte components/modules in `web/` | Both project-local `svelte-code-writer` and `svelte-core-bestpractices`; see frontend requirements below |
| Tailwind, tokens, responsive styles and theming in `web/` | Project-local `tailwind-design-system`; see frontend requirements below |
| JSON document contracts in `schema/` | Relevant domain/validation guidance; PostgreSQL skill only if database design is actually involved |

Use `.claude/skills/oop-design/SKILL.md` for `core/` code. Do not load
the retired encapsulation skill, even if an older agent-facing copy remains.
FastAPI-service code uses only the `fastapi` skill; do not impose the OOP skill on
routers, dependencies or API wiring. For a task spanning boundaries, apply skills
to their respective files: database migrations use PostgreSQL guidance, and extracted
domain/workflow code uses `oop-design`. Repository-wide workflow and verification
rules still apply.

No project-local Ray/Zarr skill is currently provided. For those integrations, inspect
installed versions and use the libraries' official documentation; do not invent APIs
or treat illustrative conversation snippets as existing interfaces.

## Development workflow

1. **Understand:** read scoped instructions, relevant design, code, tests, and tooling.
   Identify the requested operation, owning layer, current behavior and intended change.
   Follow the user's task; do not select unrelated roadmap work on a fresh session.
2. **Resolve and design:** for substantive behavior or multi-layer changes, establish
   inputs/outputs, object responsibilities, authorization, lineage, transaction and
   failure semantics, and acceptance checks before implementing. Record unresolved
   decisions and distinguish planned features from implementation drift. Reuse settled
   conversation decisions instead of reopening them automatically.
3. **Implement:** work in reviewable workflow slices; keep transport thin and enforce
   rules at the reusable boundary. Update relevant design documents with behavior changes.
4. **Verify:** exercise public behavior and failure cases, run the checks below, and
   inspect the diff for boundary violations and accidental changes.
5. **Review and report:** state what changed, evidence, and remaining limitations.
   If repeated failures expose a design defect, diagnose and revise the plan rather
   than repeating blind fixes or suppressing checks. Never discard unrelated work.

Documentation-only and small localized changes use this workflow proportionately;
no new planning artifacts, application tests, or architecture ceremony are required
when they would not verify the change. Explicitly invoked command workflows may
specify additional artifacts and gates; read their definitions.

## Testing and tools

Use `uv` with the repository's `pyproject.toml` and lockfile. Use `rg` for discovery.
Read `Makefile` and `.github/workflows/ci.yml` for executable commands; do not assume
that a command name runs all test categories.

### Verification by boundary

- Domain packages: deterministic unit tests for invariants, transitions and errors;
  use Hypothesis for properties such as path rules and canonicalization.
- Infrastructure packages: contract tests against real adapters; use temporary
  filesystems and PostgreSQL testcontainers where applicable. In-memory doubles do
  not prove database locking, filesystem durability or storage isolation.
- Domain workflows: test complete operations with injected ports, covering permission denials,
  wrong-target access, idempotent retries, incomplete transfers, concurrency conflicts,
  recovery, and exact lineage. Add real-service tests for guarantees fakes cannot prove.
- Applications: test transport/authentication mapping, wiring and lifecycle; use the
  existing HTTPX/ASGI and respx patterns where appropriate. Keep core behavioral
  coverage independent of HTTP tests.
- Test observable contracts rather than private call sequences. Control time and
  randomness. Mock external boundaries, not the domain behavior under test.

### Commands and gates

```sh
make lint
uv run pytest -m unit --cov=src/huron --cov-report=term-missing
uv run pytest -m contract
uv run pytest -m integration
# For ingestion/durability acceptance changes; requires at least 25 GiB free disk:
make test-acceptance
# When changing documentation included in the documentation site:
make docs
```

- During implementation, use focused tests for feedback. Before completing Python
  changes, run `make lint` and the unit coverage gate, plus affected contract,
  integration and acceptance suites. Explicit plan/command gates may require more.
- Plain `pytest` and `make test` select unit tests by default. The CI integration job
  currently tolerates no collected tests; that is not evidence of integration coverage.
- `make lint` runs Ruff lint/format, pydoclint, mypy strict, ty, import-linter, the
  schema-map check, radon, complexipy, pyscn and the duplication regression guard.
  Inspect findings as well as exit codes,
  especially radon's reported complexity/maintainability grades.
- Static lint targets `src/`. Tests remain separate behavioral verification; the
  migration schema-map check remains required. Source thresholds and import contracts
  apply unchanged across the entire source tree.
- Preserve configured coverage and complexity thresholds; do not add suppressions,
  exclusions, skips or weaker contracts to hide failures. Cover new/touched behavior
  and explain any unverified paths. Report missing infrastructure and baseline failures
  accurately rather than claiming a full pass.
- For instruction-only Markdown changes, check links/paths, consistency with commands
  and configuration, and `git diff --check`; Python tests do not validate prose.
- Follow `docs/getting-started/docstrings.md`: Google-style Python docstrings matching
  signatures, with test summaries describing the behavior proved. Comments and names
  explain enduring behavior, not plan phases or checklist mechanics.

## Frontend: `web/`

The frontend is a SvelteKit application alongside the Python packages, not a Python
package under `applications/`. It consumes the backend API and owns presentation,
interaction, route loading and browser/server UI concerns. It must not duplicate
core authorization, publication or lineage rules; client checks provide feedback,
while the backend enforces permissions and invariants.

These rules apply to all work under `web/`. Paths below are repository-relative
unless a command explicitly runs from `web/`. `web/AGENTS.md` points here so all
agents use the same source of frontend instructions.

### Sources of truth

- Read `design/frontend.html` before changing frontend behavior or architecture. The design
  record is authoritative; if the implementation disagrees, update the implementation. If a new
  product or architecture decision is required, record it in `design/` in the same change.
- Read `web/README.md` for the frontend's current delivery status and available commands.
- Read `web/src/lib/api/README.md` before changing data access, domain types, or fixtures.
- Treat `design/roadmap.html` as delivery context, not as permission to implement future phases.
  Keep the requested change within the currently available backend contract.

### Required frontend skills

#### Svelte

Before planning, reviewing, analyzing, creating, or editing a Svelte component or Svelte module
(`*.svelte`, `*.svelte.ts`, or `*.svelte.js`), read and follow both project-local skills in full:

- `.claude/skills/svelte-core-bestpractices/SKILL.md`
- `.claude/skills/svelte-code-writer/SKILL.md`

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

#### Tailwind CSS

Before planning, reviewing, analyzing, creating, or editing Tailwind utilities, design tokens,
component variants, responsive styles, dark-mode behavior, or Tailwind configuration, read and
follow the project-local skill in full:

- `.claude/skills/tailwind-design-system/SKILL.md`

Use `tailwind-design-system` for Tailwind CSS v4 token architecture, reusable component patterns,
responsive behavior, theming, and accessibility. Read its files under `references/` when their
topics apply to the task.

The skill provides implementation guidance; Huron's authoritative design and existing semantic
tokens remain the product contract. Prefer the tokens and patterns in `web/src/lib/design/tokens.css`
and existing design components over copying generic example tokens or introducing one-off values.

### Frontend lifecycle

Apply the shared development workflow above with these frontend-specific steps. Scale the depth
to the size and risk of the change, but do not skip applicable gates. Instruction-only Markdown
changes use the documentation verification rule above; they do not require application or browser tests.

#### 1. Discover

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

#### 2. Plan

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

#### 3. Implement

- Make the smallest cohesive change that fully delivers the requested behavior.
- Follow Svelte 5 and SvelteKit conventions already used in this repository. Keep TypeScript strict;
  do not use `any`, unchecked casts, or suppressed diagnostics to force a build through.
- Prefer existing components in `web/src/lib/design/components/` and tokens in
  `web/src/lib/design/tokens.css`. Add a shared component only when more than one concrete use needs it
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

#### 4. Respect the API seam

Until the generated OpenAPI client replaces the prototype seam:

- Routes and components import domain data through `$api/client` and domain types through
  `$api/types`.
- Only `web/src/lib/api/client.ts` may import `web/src/lib/api/fixtures.ts`.
- Do not define domain types in routes or components and do not construct fixture-shaped domain
  objects there.
- Mutating fixture-backed flows must say clearly that they did not persist. Never imply a synthetic
  action changed real data.
- Preserve the API's security semantics: undiscoverable resources render as 404, never as a UI that
  reveals a forbidden resource exists.
- Preserve keyset pagination shapes and projection-watermark/staleness information where the design
  requires them.

#### 5. Verify

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

#### 6. Perform visual QA

For visible UI changes, inspect the running app in a real browser after automated checks:

- verify a narrow mobile viewport, the compact workspace viewport around 816 px, and a wide desktop
  viewport;
- check light and dark modes;
- exercise the primary flow with keyboard navigation and confirm focus remains visible;
- check loading, empty, long-content, validation, and error states affected by the change;
- confirm there is no clipping, unexpected horizontal scrolling, hydration error, or inaccessible
  icon-only control.

Prefer fixing the underlying layout or interaction contract over adding viewport-specific patches.

#### 7. Hand off

Finish with a concise report containing:

- the user-visible result;
- the important files changed;
- the verification commands run and their outcomes;
- any check or browser scenario not run, with the reason;
- remaining risks only when they are concrete and relevant.

Do not claim completion while an applicable gate is failing.

### Frontend invariants

- The UI holds no API keys, OIDC tokens, or privileged credentials. Session handling remains
  server-side and tokens never go into `localStorage`.
- Browse and search routes remain server-renderable and directly addressable by stable URLs.
- Candidate versus published state, stale data, retention consequences, and synthetic versus real
  data remain visually explicit.
- Accessibility, responsive behavior, and dark mode are acceptance criteria, not optional polish.
- Root-level routes must remain synchronized with `web/src/lib/reserved-slugs.ts` and its test so an
  organization slug cannot be shadowed silently.
