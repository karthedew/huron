# Design and local roadmap: DOCS — Starlight developer and user documentation

Status: reviewed — independent design/checker review 2 PASS; bounded prototype authorized, implementation still pending.

## Goal, scope and authority

Independent maximum review `ses_ef16989d2ffe7w6I5eoCqTGC73` closed F1 after the
checker accepted canonical and explicitly retained legacy task headings. All 63
CLI regression cases and complete applicable gates passed; real source/plans/index
and quarantined interrupted fixture were preserved. DOCS-P is eligible and now
authorized by the parent under the user's docs/MVP request. No site is implemented
or dependency build/browser behavior qualified by this design receipt.

Deliver detailed developer AND scientist/operator documentation as a static Starlight
site built under `docs/`. This is a named DOCS workstream, not a renumbering of
000–010. Broad user implementation/Docker/workspace authority is recorded in
[the execution ledger](execution-2026-10-05.md); this assignment owns planning only.
No product source, docs source, build configuration, agent assets or services changed.

Canonical architecture remains [design/raw-first.md](../design/raw-first.md), with
[architecture](../design/architecture.html), [Raw](../design/layer-raw.html),
[identity](../design/auth.html), [SDK](../design/python-client.html) and
[workflow](../design/workflows.html) details. Vocabulary remains
[CONTEXT.md](../CONTEXT.md). Preserve [domain guidance](../docs/agents/domain.md),
[ADR-0001](../docs/adr/0001-controller-generation-is-the-verification-epoch.md),
[ADR-0002](../docs/adr/0002-domain-owned-core-workflows.md) and
[history](../docs/history.md) at their canonical repository paths. Explain workflows
without introducing competing architecture or treating historical receipts as current tests.

## Verified current state and inspected sources

Read all live docs listed in the migration map, `zensical.toml`, `Makefile`, docs
dependency declarations/lock references, `.github/workflows/ci.yml`, Compose,
`scripts/vendor-mermaid.sh`, the canonical guidance/templates/workflows and plans
001–010. Inspected the controlled-cutover test's invocation boundary, not Core design.
No Core or Svelte component analysis/changes; OOP/Svelte skills are not applied here.

| Claim | Direct evidence | Classification |
| --- | --- | --- |
| Current docs renderer | Makefile docs invokes `uv run --group docs zensical build --strict`; zensical.toml navigation and PyMdown configuration; pyproject pins 0.0.57 | Implemented, baseline build exit 0 |
| Documentation is developer-focused | docs/index.md, getting-started pages, backend-design and controlled-cutover | Implemented content, detailed scientist guide absent |
| Canonical references have consumers outside the site | AGENTS and .agents reference docs/agents/domain.md; design HTML references ADRs/history; README links local development | Must preserve paths, not simply move docs into src/content |
| Offline intent | zensical.toml disables webfonts; extra.css uses Material selectors; Mermaid helper requires absent mkdocs.yml | Existing requirement; obsolete helper not a working Starlight asset |
| CI docs gate absent | ci.yml has lint/unit/contract/integration, no docs job; workflow directory also contains acceptance.yml | Migration must add CI, not pretend current CI builds docs |
| Product MVP delivery gaps | Discovery report and plans 001–010; web API README explicitly fixture-backed | Reported current gaps; no application baseline in this writer turn |

Baseline root `make docs`, `git diff --check`, `python roadmap/check_docs.py` all
exit 0 in this writer turn before edits. This qualifies current documentation only.
The local checker tests source links, not generated Astro routes or Pagefind behavior.

### Official API and version evidence

Fetched official [Starlight home](https://starlight.astro.build/),
[getting started](https://starlight.astro.build/getting-started/),
[manual setup](https://starlight.astro.build/manual-setup/),
[configuration](https://starlight.astro.build/reference/configuration/),
[authoring](https://starlight.astro.build/guides/authoring-content/) and
[search](https://starlight.astro.build/guides/site-search/). These are live docs,
not version-pinned installed evidence. Registry queries in writer transcript:

```sh
npm view @astrojs/starlight version engines peerDependencies --json
npm view astro version engines --json
npm view @astrojs/starlight@0.42.5 peerDependencies dist.integrity --json
npm view astro@7.3.5 engines dist.integrity --json
npm view @astrojs/markdown-remark@7.3.0 engines dist.integrity --json
```

All exited 0: Starlight **0.42.5** requires Astro `^7.2.10` and
`@astrojs/markdown-remark ^7.3.0`; Astro **7.3.5** requires Node `>=22.12.0`,
npm `>=9.6.5`. Candidate explicit pins: 0.42.5 / 7.3.5 / 7.3.0 respectively.
Default local Node is 20.17.0 (unsuitable); installed 22.23.2 satisfies the engine.
No Starlight package is installed or lock qualified by this slice. The prototype
must record npm version, package-lock integrities, actual dependency tree and
installed exports; upstream main/template or `latest` is never an installed pin.
If these candidates fail, report exact peer/API failures and propose a reviewed
replacement pin; do not force-install or quietly downgrade engine checks.

## Target architecture and alternatives

Choose an independent static Astro package rooted at `docs/`, no runtime API, no
SSR adapter, no Svelte/Tailwind integration, no credentials or analytics. Prefer
built-in accessible navigation/theme/search and system fonts; local CSS only where
necessary for long code/tables. No remote fonts/CDN scripts/images, no hosted search.
Installation may require an approved registry/mirror; serving the built artifact
must need no external network. Public source/bibliography links can remain explicitly
external references, not runtime dependencies or offline navigation promises.

**One authoring source, generated rendering input.** Keep every current Markdown
file at its existing path; new authoring files under `docs/user/`, `docs/developer/`
and `docs/operations/`. A tracked explicit content manifest and small preparation
script map canonical files to ignored `docs/src/content/docs/` inputs. No symlinks,
hand-maintained duplicate prose or broad copy of the workspace. `docs/src/content.config.ts`
uses official `docsLoader()`/`docsSchema()` over generated files. This modest build
adapter avoids undocumented loader base options (official docsLoader only documents
generateId) and preserves .agents/ADR consumers unchanged.

Proposed ownership (future phase, not created now):

```text
docs/package.json, package-lock.json, .npmrc       exact dependencies; engine-strict
docs/astro.config.mjs, tsconfig.json               static build and strict TS
docs/src/content.config.ts                        official docs collection
docs/content-map.json                             explicit source → route/title map
docs/scripts/prepare-content.mjs                  safe deterministic rendering inputs
docs/scripts/check-site.mjs                       source + emitted links/assets/fragments
docs/scripts/check-content.mjs                    manifest/status/content syntax checks
docs/tests/content.test.mjs                       Node public filesystem contract tests
docs/e2e/docs.spec.ts, playwright.config.ts        independent built-site browser checks
docs/src/styles/custom.css, docs/public/favicon.svg  local owned assets
docs/src/content/docs/, docs/.astro/, docs/dist/   ignored generated artifacts
```

Preparation is a pure file transformation with explicit input/output roots, not a
domain service. Proposed CLI `node scripts/prepare-content.mjs --check` verifies
determinism without modifying canonical inputs. Normal prepare writes only its
manifest-owned output, refuses unknown files/symlink escapes/colliding routes and
publishes staged output only after all inputs validate. Failure leaves last good
output intact but exits nonzero; build must not continue with stale success. No
automatic deletion of unknown generated files; a fresh isolated output root avoids
requiring deletion as recovery. Serialize builds per output directory; simultaneous
builds fail clearly or use separate roots. No database, user auth or storage migration.

Add frontmatter `title` in generated input from manifest, retain existing ADR
`status: accepted`, remove only the first equivalent H1 in the generated view,
preserve every H2/H3 and explicit anchor. Current source Markdown remains readable.
Convert PyMdown `!!!` asides to documented `:::note`/`:::caution` in owned canonical
prose during migration, with corpus tests; do not hide unconverted syntax. MDX is
unnecessary initially. Fence contents (Python braces, shell, SQL) remain literal.

Concrete official example to qualify against installed pins (not installed code):

```js
// docs/astro.config.mjs
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
export default defineConfig({
  integrations: [starlight({
    title: 'Huron',
    pagefind: true,
    sidebar: [
      { label: 'Scientists', items: [{ slug: 'user/overview' }] },
      { label: 'Developers', items: [{ slug: 'getting-started' }] },
      { label: 'Operations', items: [{ slug: 'operations/controlled-cutover' }] },
      { label: 'Design and history', items: [{ slug: 'backend-design' }, { slug: 'history' }] },
    ],
  })],
});
```

```ts
// docs/src/content.config.ts
import { defineCollection } from 'astro:content';
import { docsLoader } from '@astrojs/starlight/loaders';
import { docsSchema } from '@astrojs/starlight/schema';
export const collections = {
  docs: defineCollection({ loader: docsLoader(), schema: docsSchema() }),
};
```

Canonical relative Markdown links are resolved against the original source path,
then rewritten via manifest to site routes, keeping fragments; reject missing
targets/fragments, path escapes, accidental ignored-plan dependencies and unmapped
local links. Preserve existing route slugs (`getting-started/...`, `history`, `adr/...`)
without alias redirects. Design/raw-first and CONTEXT get explicitly attributed,
generated reference pages, never independently authored architectural copies.
Other design HTML/atlases remain canonical repository resources linked as labelled
external source references, not silently copied with broken source/CDN links.
ADR and history references must work offline within site pages; their external
historical Git receipts remain labelled external. Build must not fetch them.
Prototype must qualify deployment under both `/` and `/huron-docs/` base paths;
no invented production hostname. Choose deployment URL/base in the implementation
plan before configuring canonical SEO URLs or promotion (promotion not authorized).

Rejected: move all docs into content (breaks canonical agent/design links); keep
Zensical as a second renderer (duplicate contract); custom content loader immediately
(unnecessary API surface); hosted Algolia (offline requirement); embedding app UI
(couples docs to fixture app and adds framework dependencies). If generated-content
complexity proves excessive, escalate with measured alternative before planning.

## Complete current-document migration map

All 14 current files below are accounted for (13 Markdown + one CSS). No Markdown
source moves/deletions. Route names are intended emitted routes, not source URLs.

| Current canonical path | Generated route / treatment | Content action |
| --- | --- | --- |
| docs/index.md | `/` | Two audience entry points, honest current/target banner; canonical design links |
| docs/getting-started/index.md | `/getting-started/` | Developer quickstart; no-sudo prerequisite alternative; fix claim that lint covers whole gate |
| docs/getting-started/local-development.md | `/getting-started/local-development/` | Current topology/config; safe owned-port setup, never instruct this execution to run make hosts; target stack separate |
| docs/getting-started/repository-layout.md | `/getting-started/repository-layout/` | Current graph vs future cutover; add docs package/source/build ownership |
| docs/getting-started/conventions.md | `/getting-started/conventions/` | Preserve thresholds; replace Zensical instructions; distinguish target design from shipped behavior |
| docs/getting-started/docstrings.md | `/getting-started/docstrings/` | Preserve detailed conventions/examples/anchors |
| docs/getting-started/testing.md | `/getting-started/testing/` | Preserve complete gates, full integration prerequisites and floors; add docs gates |
| docs/backend-design.md | `/backend-design/` | Navigation to canonical records and explicit current/target differences |
| docs/history.md | `/history/` | Preserve receipts, dates, hashes and anchors, especially domain-owned-core; no new product PASS |
| docs/operations/controlled-cutover.md | `/operations/controlled-cutover/` | Preserve supported privileged deployment contract and limitations; not executable under no-sudo host authority |
| docs/agents/domain.md | `/agents/domain/` | Preserve source path/text and local references; expose as contributor reference, not competing instruction |
| docs/adr/0001-controller-generation-is-the-verification-epoch.md | `/adr/0001-controller-generation-is-the-verification-epoch/` | Preserve accepted frontmatter, rationale, links and anchors |
| docs/adr/0002-domain-owned-core-workflows.md | `/adr/0002-domain-owned-core-workflows/` | Preserve chronology and subsequent-target qualifier |
| docs/stylesheets/extra.css | No page | Replace Material-specific presentation only after built tables/code/theme tests; delete obsolete file then |

Additional canonical inputs: `design/raw-first.md` → `/reference/raw-first/` and
`CONTEXT.md` → `/reference/vocabulary/`, generated and attributed; all their local
references need explicit mapping or labelled external canonical source destinations.
Root README, AGENTS, design HTML, web README/API README remain in place. Public
docs must never depend on ignored roadmap paths. Deleted docs/agents/issue-tracker.md
and triage-labels.md are pre-existing user deletions, not migration input to recreate.

## Detailed new content inventory and product synchronization

Each guide must name its audience, prerequisites, exact cwd/version, safe sample
data, expected result, failure/retry behavior, cleanup ownership and verified
evidence reference. Mark **Current**, **Target — not available**, or **Historical**
in visible prose; code samples for targets are explicitly illustrative, not runnable
quickstarts. Publishing the site does not promote any target to Current.

| Proposed source | Required content and status/evidence owner |
| --- | --- |
| docs/user/overview.md | Scientist journey, current fixture limitation, Raw-first scope and later arrays; target overview now, usable walkthrough after 003–009 |
| docs/user/access.md | Login/logout/session expiry, dataset discoverability, directory admin vs Huron roles, request access, no Google-ID-token-as-API-key shortcut; 003/009 receipts |
| docs/user/datasets-metadata.md | Org/Collection/Dataset; title vs immutable identity; schema selection, additive fields; new dataset requirements; omitted/null/empty cases; 004/008/009 |
| docs/user/raw-push.md | First push and exact-base add/delete/replace; independent retention; file path/size/hash checks; across-file tus, transfer vs publication; 005/006 |
| docs/user/recovery.md | Lost response same-identity replay, resume, cancel, expiry, quota/ENOSPC, checksum and revoked access; stale-base choice explicitly unresolved until owner approval; 005/006/008 |
| docs/user/search-export.md | Addressable browse/search, visibility/keyset/freshness, download, pinned export vs live title, citation/lineage disclosure; 007–009 |
| docs/user/python-client.md | Lightweight install and credential provider, Client lifetime, direct services, bounded streaming, example checks; illustrative until isolated wheel + 008 real workflow proof |
| docs/user/web-workflows.md | Screens and keyboard paths for all delivered backend operations; no fixture success as persistence; 009 integrated screenshots/receipts |
| docs/user/schema-administration.md | Org-owner schema/version publication and additive extension errors; separate directory membership gateway vs role binding administration; 003/004/009 |
| docs/developer/documentation.md | Node/npm pin, lock install, authoring/manifest rules, source and generated link checks, offline search, browser matrix, dependency update process; DOCS evidence |
| docs/developer/contributing.md | Safe dirty-tree ownership, branch/commit only explicit, test/fixture reuse, errors and change review; link canonical rules rather than duplicate .agents |
| docs/developer/api-sdk.md | Authoritative OpenAPI, regeneration/mapping, binary tus boundary, public interfaces/transport separation, isolated SDK tests; target script names not runnable until 002/008 |
| docs/developer/frontend.md | SSR/session safety, $api/client contract, fixture truthfulness, generated DTOs, full web gates; source of truth web README/API README and 009 |
| docs/operations/raw-mvp.md | Existing-data inventory/backup/rehearsal, safe startup, migration/recovery/crash state runbooks, capacity/reservations, retention, monitoring, directory outages, NFS qualification; coordinate with 010's existing ownership, do not overwrite |
| docs/operations/performance.md | Nominated hardware/mount topology, bounded k6, distinct users, committed-readable receipts/search, >500 GiB peak calculation, baseline then approved SLO; 010 only |

DOCS shell/source preservation need not wait for product implementation. Product
owners provide verified examples and behavior changes alongside each slice; DOCS
owner integrates prose serially, with exact per-page ownership to avoid collisions
with 008 SDK docs and 010 raw-mvp runbook. Final complete-MVP docs acceptance waits
for all scientist workflows and real operations evidence, not merely generated pages.

## Phase sequence, build/CI ownership and exact deletions

1. **DOCS-P (prototype)**: ignored `roadmap/prototypes/starlight/` only; questions
   below. No promotion, source edits or root lock changes. Independent review required.
2. **DOCS-F (foundation)**: phase planner writes a separate named self-contained
   docs plan after probe evidence. Own package/config/scripts/tests/manifest and
   source prose syntax updates listed above; keep current docs behavior until replacement
   gate passes. Explicit dirty-source reconciliation before any docs edit.
3. **DOCS-C (cutover)**: same reviewed foundation boundary owns root Makefile docs
   and docs-serve recipes, `.github/workflows/ci.yml` new docs job (or separately named
   docs workflow if planner selects it), `.gitignore` generated artifact rules,
   pyproject docs dependency group and uv.lock refresh. Coordinate Makefile ownership
   with 002. Use Node 22.23.2/npm satisfying engines; CI npm ci in docs and root
   make docs; no ignored roadmap dependency. Preserve Python CI jobs and thresholds.
4. **DOCS-G (guides)**: detailed current developer guide + labelled target scientist
   guide; serial product receipts upgrade specific workflows. Independent editorial,
   command/example, accessibility and full documentation gate before verified.

Proposed package commands, owned by DOCS-F and **not available today**:
`prepare-content`, `check`, `test`, `build`, `test:e2e`, `dev`, `preview`.
`check` checks manifest/source and Astro types using a separately pinned qualified
`@astrojs/check` + TypeScript; `test` uses Node test runner on real temporary files;
`build` prepares content, invokes `astro build`, then strict emitted-site checker.
No fictitious `astro build --strict` switch. Root `make docs` becomes
`npm --prefix docs run check` + `npm --prefix docs test` + `npm --prefix docs run build`.
`make docs-serve` uses owned configurable localhost port, not occupied 8000 or web 4173.
CI additionally runs docs e2e on the built artifact with a locked browser version;
no deployment/publishing action is implicitly authorized.

Only after replacement + independent verification: delete `zensical.toml`,
`docs/stylesheets/extra.css`, and `scripts/vendor-mermaid.sh` (obsolete MkDocs-specific
helper, no current Mermaid content requirement). Remove Zensical-only docs dependency
group/comment and lock entries via uv lock; do not remove shared transitive packages
by hand or regenerate unrelated dependency upgrades. Replace Zensical-specific
documentation paragraphs/tests, not historical receipts. No existing docs-specific
test suite was found (`check_docs` test-name search empty); the local checker is a
reuse reference, not a production CI dependency. No speculative deletion of site/,
unknown assets, Markdown sources, ADRs, docs/agents, archives or user data. Inspect
consumers again before authorizing those exact deletions. No legacy renderer shim.

## Bounded prototype questions and exact reproduction design

Prototype owner first reads canonical `.agents/skills/prototype/SKILL.md`, command,
templates and this design; browser owner reads `.agents/skills/playwright-cli/SKILL.md`
and relevant running-code/request-mocking references. No Starlight-specific local
skill exists; inspect official docs plus installed package APIs. Review design first.
All following commands are **future assigned commands, NOT this writer's results**.

After verifying `roadmap/` exists and the new path has no user files, prototype owner
creates an independent package under `roadmap/prototypes/starlight/` with the layout
above and copied minimal canonical fixtures (index, local-development, testing,
ADR-0001/0002, history, domain, Raw-first and vocabulary). Original sources are read-only.
Use a fixed corpus including asides, tables, code braces, footnotes, explicit and
duplicate headings, relative links and fragment references. No product fixture/data.

```sh
# cwd roadmap/prototypes/starlight, after owner creates package.json
export PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH
node --version
npm --version
npm install --save-exact astro@7.3.5 @astrojs/starlight@0.42.5 @astrojs/markdown-remark@7.3.0
npm ls --all
npm ci
npm run check
npm test
npm run build
npm run test:e2e
```

Pin check/types/browser test dependencies after version/API inspection; record exact
choices in prototype package/receipt before executing their commands. No npm create
latest, no --force or --legacy-peer-deps. Reproduce npm ci/build in a second owned
clean directory from package+lock+fixtures; compare route/content/asset manifests,
not volatile log timestamps. Package install scripts must be inspected, not blindly
disabled in a way that hides missing native build dependencies.

| Question | Happy case | Counterexample required / failure criterion |
| --- | --- | --- |
| Locked engine and content build | Node 22.23.2 + exact pins, npm ci, installed exports and generated docs build cleanly twice | Engine-strict refuses Node 20; malformed title/frontmatter and unknown aside syntax fail; no claim that upstream main proves candidate API |
| Canonical links and authority | Source paths/bytes preserved; manifest renders all fixture pages; history/ADR fragments resolve, design target attribution visible | Missing file/fragment, duplicate route, escaping symlink, ignored roadmap link, unknown output and source deletion fail nonzero; failed prepare never reports stale output as success |
| Base path and built artifact | Crawl emitted href/src/id under both `/` and `/huron-docs/`; local assets and expected route set complete | Introduce bad root-only link and missing asset; strict check must reject both; AST-aware source handling must not rewrite code blocks |
| Local Pagefind | Built preview (not dev) finds unique phrase `Controller generation` and `pinned base`; keyboard result activation reaches correct page/anchor with all nonlocal requests blocked | Nonsense query has honest empty state; delay index tests loading; abort index fetch tests visible failure/recovery, not endless spinner or fabricated hits |
| Accessibility/offline | 390×844, 816×900, 1440×1000 × light/dark; skip link, nav, search dialog/focus/Escape, copy code, long table/code; zero runtime external requests | Missing search asset, long unbroken identifier, 404 path and blocked network show truthful states; no console/hydration errors in happy case, expected injected errors recorded separately |

Prototype owns a local fixture HTTP server only after parent assigns service permission
and `ss -ltnp` confirms candidate **4327** free; bind 127.0.0.1 and record PID/command.
Proposed `npm run preview -- --host 127.0.0.1 --port 4327` uses installed Astro CLI
help qualification. Never reuse occupied 8000/5173/9000 or stop another application.
With web's existing installed Playwright verified, browser QA cwd `web/`:

```sh
npx --no-install playwright --version
npx --no-install playwright cli --help
npx --no-install playwright cli -s=huron-docs-prototype open http://127.0.0.1:4327
npx --no-install playwright cli -s=huron-docs-prototype snapshot
npx --no-install playwright cli -s=huron-docs-prototype resize 390 844
npx --no-install playwright cli -s=huron-docs-prototype resize 816 900
npx --no-install playwright cli -s=huron-docs-prototype resize 1440 1000
npx --no-install playwright cli -s=huron-docs-prototype console
npx --no-install playwright cli -s=huron-docs-prototype close
```

Use fresh semantic refs, theme emulation/network interception per canonical skill,
screenshots and machine assertions; don't claim resize alone tests all scenarios.
No authentication/unauthorized state exists for public docs; document 404 instead,
never test Huron permissions via docs. No browsers/services run by this design writer.

Prototype receipt under `roadmap/prototypes/starlight/evidence/` must contain package
and browser versions, exact commands/cwd/exits, lock hash, input/output manifest,
positive AND negative test counts, source-byte preservation evidence, localhost
request log (zero external runtime), screenshots for matrix, limitation/failure
notes and independent reviewer ID. Inline essential results into the later phase
plan; a scratch directory alone does not make that plan executable.

## Acceptance, gates, blockers and next step

Current design gate cwd root: `make docs`; `git diff --check`;
`python roadmap/check_docs.py`; explicit new-text local links/fragments/whitespace;
`git check-ignore -v roadmap/execution-2026-10-05.md roadmap/starlight-design.md`;
`git ls-files roadmap` must be empty. Lifecycle negative/positive validation is in
the execution record. No application Python/frontend suite applies to this prose
and ignored checker boundary; their absence is not a product PASS.

Future prototype gate: every command/scenario above, root docs/diff/checker/ignore
checks, own new text, reproducible clean lock install, independent reruns. Future
implementation gate: root `make docs` replacement remains strict on broken links;
cwd docs `npm ci`, `npm run check`, `npm test`, `npm run build`, `npm run test:e2e`,
named-session visual QA; root `git diff --check`, `uv lock --check` after dependency
cutover, canonical source/reference checks runnable in a fresh checkout. Preserve
Python gates and source thresholds; no new skips/xfails/exclusions. No web gate
unless web code changes (excluded); no agent gate unless agent assets change
(excluded). Each future assignment must resolve actual package pins/scripts/fixtures
before READY; this design's examples are not a self-contained executable phase.

Open: independent design review; exact-pin build/link/search experiment; deployment
base decision; script/test dependency pins; full canonical link manifest; editorial
source-truth reconciliation (existing quickstart overclaims lint/current authority);
no-sudo local identity setup owned by environment/identity phase, not silently fixed
by docs. Existing-data disposition, issuer/Keycloak, stale-base, NFS hardware and
post-baseline SLO remain product-owner decisions. Docs can label them, not approve them.

Review count 0 for this new workstream. Parent commissions independent design
review (max three attempts), then bounded `/prototype`; only reviewed evidence feeds
`/implementation-plan`. No docs implementation, phase READY or independent PASS
is claimed by this writer's self-check.
