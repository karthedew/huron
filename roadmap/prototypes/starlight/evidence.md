# DOCS-P evidence — pinned Starlight generated-input experiment

**Verdict: FAIL for the full hypothesis/gate; useful bounded evidence, ready for
independent review of the findings. Not shipped documentation or MVP delivery.**

## Question, authority and scope

Can exact-pinned static Starlight render a deterministic view of canonical Huron
Markdown, preserve source paths/bytes/anchors, validate all local routes/assets at
`/` and `/huron-docs/`, and provide accessible, locally indexed search including
truthful network-failure behavior?

Source contract: full `roadmap/starlight-design.md`, reviewed design/checker attempt
2 `ses_ef16989d2ffe7w6I5eoCqTGC73`. This writer is DOCS-P attempt 1,
`ses_ef15e0eceffextkoojLCG4HlDP`, dispatch
`5f24d96c-59aa-46f9-90c1-a121d99d73fa`, role implementation/activity prototype,
configured **maximum** / Astra `max`. Provider effort acceptance was not observed
or independently proved. This self-check is not independent review.

Read AGENTS, tooling guide, full prototype command/skill/template, orchestration,
verification, testing/docstring conventions, full local playwright-cli skill and
session-management/running-code/request-mocking/playwright-tests references before
applying them. No Core, Svelte or Tailwind integration/source was changed. Existing
test discovery found no docs-specific application tests; root checker behavior and
web's scoped Playwright test conventions were inspected. Filesystem contracts use
Node tests; browser cross-route behavior uses Playwright, not mocks of the adapter.

Exact resource claims remain those in `roadmap/resource-ledger.md`:

- `source:repo/read`, `plan:docs-design/read`: live source/config/docs/design and
  planning/checker records remained read-only.
- `prototype:starlight/write`: only this ignored directory, including corpus,
  package/lock, scripts, tests, caches, output, clean reproduction and evidence.
- `service:docs-prototype/write`: only proved-free `127.0.0.1:4327` previews.
- `browser:docs-prototype/write`: named in-memory `huron-docs-prototype` session and
  ignored `web/.playwright-cli/` plus this prototype's screenshots.
- `build:docs/write`, `cache:uv/write`, `env:python/write`: ordinary root docs gate
  with `UV_CACHE_DIR=/tmp/opencode/huron-effort-uv-cache`.

No delegation, sudo, global installs/config changes, live app services, commits,
staging, branches, pushes, resets, clean, stash, journal changes or promotion.

## Preservation and precise corpus

Initial HEAD `2b2e9c0c9d6b9beafef2e11b840f28535502aa6b`, 51 tracked changes and
4 untracked source/design files belonged to prior work. The snapshot hashed all
553 tracked/untracked source paths (including absent paths), their modes, HEAD,
exact index bytes, staged entries and status. Final preservation verification
passed; see [initial hashes](evidence/initial-state.json) and
[final preservation receipt](evidence/commands/source-preservation-final.log).

[Manifest](content-map.json) contains 14 pages and one local SVG:

- The nine requested canonical fixtures: index, local-development, testing,
  ADR-0001/0002, history, domain guidance, Raw-first and vocabulary.
- Four copied dependency-closure pages: conventions, repository-layout, docstrings,
  controlled-cutover. They keep index/testing/history local links offline rather
  than silently externalizing missing pages.
- One synthetic page with all four native asides, tables, Python braces, backtick
  and tilde fences, footnotes, duplicate headings, explicit anchors, links/definitions,
  and long unbroken identifiers.

**Credential boundary:** local-development is a verbatim lines 1–77 excerpt, clearly
attributed in the generated view. Its later documented development credential
literals were not copied. All other 12 canonical input pages are whole byte-identical
copies. No dev.env, auth state, credentials or application data was copied. Original
source bytes were never modified. [Corpus hashes](evidence/corpus.json) give both
full-source and fixture SHA-256/byte counts and the single excerpt range.

Design HTML is not broadly copied or executed: two explicit, labelled external
repository-source references point at the existing HEAD tree. They are not offline
site navigation or a claim that remote committed content equals the dirty tree.
No production hostname, canonical SEO URL, remote font, CDN, analytics or hosted
search was configured.

## Installed versions and exact API qualification

Node **22.23.2**, npm **10.9.8**; `.npmrc` enforces engines. Exact root dependencies
and all resolved integrities are in [package-lock.json](package-lock.json) and
[package proof](evidence/package-proof.json). Lock SHA-256:

`5857165d1169f134499883b793799a084fd9b64ca6f173bef48201943e91fd70`

| Boundary | Qualified versions |
| --- | --- |
| Renderer | Astro 7.3.5; Starlight 0.42.5; markdown-remark 7.3.0 |
| Check/types | @astrojs/check 0.9.10; TypeScript 5.9.3 |
| E2E | @playwright/test 1.62.1; observed Chromium 151.0.7922.34, installed revision 1234 |
| Named CLI | Existing web Playwright 1.62.1; observed local Chrome 154.0.8037.92 |
| Resolved search | Pagefind 1.5.2; @pagefind/default-ui 1.5.2 |
| AST/YAML/HTML | Exact qualified pins listed in [pins receipt](evidence/pins.md) |

Official manual setup, configuration, authoring and search documentation was fetched
from `https://starlight.astro.build/`. Installed exports and implementation were then
inspected: `@astrojs/starlight/loaders` exports `docsLoader`, accepting `generateId`
and loading `src/content/docs`; `@astrojs/starlight/schema` exports `docsSchema`.
Actual imports returned functions and loader name `starlight-docs-loader`.
Astro 7 uses `markdown.processor: unified(...)` from markdown-remark. No invented
loader base option or `astro build --strict` was used.

The initial `npm install --ignore-scripts` was an inspection-only unpack, NOT a
qualified install. The installed lifecycle inventory and esbuild installer source
were read before ordinary script-enabled install/ci. The sole installed dependency
install/postinstall hook is esbuild 0.28.2's `node install.js`; registry-package
`prepare` scripts are inventoried, not manually run. Normal `npm ci` installed 445
packages and real compiler/image/Pagefind builds succeeded. `npm ls --all` exits 0;
it prints optional platform/provider dependencies as absent and an extraneous
`@img/sharp-wasm32@0.35.5` entry, including immediately after clean ci. This diagnostic
is retained, not edited away. Lock contains 539 package records across platforms.

## Results and counterexamples

### Proven for this corpus

- **39/39 Node tests pass, zero skips/xfails:** seven positive/boundary scenarios
  and 32 explicit negative CLI cases. Missing input/file/fragment/asset, route
  collisions, input/output symlinks, path escape, roadmap dependency, malformed
  YAML/title/aside, duplicate IDs, unknown output file/empty directory, competing
  lock, root-only subbase URL, missing search metadata/WASM and external runtime
  assets fail nonzero. Last good generated input and unknown data are preserved.
- Only an equivalent first H1 is removed from the view; its original anchor is
  retained explicitly. ADR `status: accepted`, H2/H3, duplicate heading suffixes,
  explicit anchors and history/ADR links survive. AST-bounded URL rewrites do not
  touch literal code fences. Native syntax and explicitly recognized PyMdown
  fixture asides render; unknown syntax fails. This temporary conversion is not
  a production compatibility commitment.
- **Both builds pass the strict checker:** 14 corpus pages plus 404, 42 assets,
  620 local URLs/fragments and 38 non-runtime external references per base. Each
  Pagefind index reports all 14 content pages. Full manifests are
  [root](evidence/manifests/root.json) and [subbase](evidence/manifests/subbase.json).
- **Second clean package passes:** `npm ci`, `npm run check`, both builds; complete
  route/content/asset manifests, including HTML and asset byte hashes, are exactly
  equal, not merely route counts. Fixtures and lock match too. Volatile logs alone
  are excluded. See [clean receipt](evidence/clean-reproduction.json) and
  [exact clean commands](evidence/clean-reproduction-commands.json). The build inputs
  still match the final writer package; later browser-only harness diagnostics do
  not alter these artifacts.
- **Wrong engine fails:** ordinary `npm ci` under Node 20.17.0 exits 1/EBADENGINE
  before creating node_modules or changing the lock;
  [negative engine receipt](evidence/wrong-engine.json).
- Normal E2E has zero runtime external attempts and zero console/hydration errors.
  Search queries `Controller generation` and `pinned base` are keyboard-activated
  to the ADR `#_top` and Raw-first `#metadata-and-reproducibility` respectively.
  Nonsense query has zero links and honest empty text; delayed index has visible
  loading followed by real results. All six viewport/theme combinations exercise
  skip-link focus, native mobile menu, modal keyboard boundary/Escape/restored focus,
  copying literal code, overflow checks and genuine HTTP 404.

### F1 — built-in search failure hypothesis disproved

Both complete E2E runs are **24 passed / 6 failed**, zero skipped/flaky tests:
[root report](evidence/e2e-root-final.json),
[subbase report](evidence/e2e-subbase-final.json).
All six failures per base are the unweakened requirement that an aborted index
request visibly fail and leave loading. Pagefind actually requests
`pagefind-entry.json?ts=...`; the qualified injection includes that query string.
Aborting it produces `Failed to load Pagefind metadata` runtime errors, but the UI
remains **“Searching for Controller generation...”** with no visible error/retry
state. Restoring requests plus a full page reload recovers real results; that is
not evidence of an in-dialog recovery control. Named CLI independently exercised
the same owned built fixture (not independent review), including
[failure screenshot](evidence/screenshots/cli-subbase-settled-aborted-index.png),
[recovered screenshot](evidence/screenshots/cli-subbase-settled-recovered-index.png)
and [observations](evidence/commands/browser-subbase-failures.log).

No assertions were skipped, inverted, xfailed or suppressed to pass this case. No
Starlight/Pagefind source or search UI was patched. A production plan must resolve
this counterexample before asserting complete offline/failure-state acceptance.

### F2 — applicable root checker fails on generated/vendor Markdown

Root `make docs` remains green and `git diff --check` is green. The assigned
`python roadmap/check_docs.py` exits 1 because its `roadmap/**/*.md` whitespace scan
includes installed third-party Markdown and Playwright-generated error contexts.
The initial invocation reported 2,270 lines (2,070 vendor whitespace and 200 generated
Playwright lines). The final invocation reports **2,330 lines: 2,070 vendor and 260
Playwright-generated whitespace findings, zero other errors**. These are new artifact-triggered failures of the
existing broad scan, not source-link regressions and not a claim that the supplied
untouched baseline failed. The checker is read-only in this assignment. It and
dependency/report bytes were left intact; no cleanup or exclusion was used to
manufacture a root PASS. The separate explicit authored-source whitespace/reference
check is additional evidence, not a replacement for this failing gate.

### F3 — long table layout needs a production-specific rule

The minimal `overflow-wrap:anywhere` CSS prevents document overflow, and code blocks
are horizontally scrollable/focusable (ArrowRight moved the focused code viewport).
However it also splits ordinary table words into narrow fragments at 390px; see
[light table](evidence/screenshots/cli-table-390-light.png) and
[dark table](evidence/screenshots/cli-table-390-dark.png). Treat this as a visible
quality finding, not full visual acceptance. A bounded column minimum/horizontal
table rule is preferable to wrapping every cell indiscriminately. No full UI redesign
was attempted in this experiment.

## Browser and service evidence

Named CLI matrices cover **390×844, 816×900, 1440×1000 × light/dark at both bases**.
[Root observations](evidence/commands/browser-named-matrix.log) and
[subbase observations](evidence/commands/browser-subbase-matrix.log) include all
local request URLs, zero external attempts, layout dimensions and keyboard results.
Screenshots use `evidence/screenshots/cli-{width}-{theme}-{skip,long-content,search}.png`
and the equivalent `cli-subbase-...` names; mobile navigation, delayed/aborted/recovered
index, table detail and 404 have additional screenshots. The summary inventories all
54 named-CLI screenshots. Representative skip/navigation/failure/recovery images,
all six normal search/long-content matrix images and the detailed mobile tables
were opened and inspected, not merely captured.
Public docs have no authentication/unauthorized state; 404 is tested instead.

Astro 7 automatically backgrounds an agent-launched preview even without an explicit
flag. The first launcher PID therefore differed from the listener and qualification
stopped rather than assuming ownership. Installed CLI code, its launch log, local
`.astro/preview.json`, exact `/proc` cwd/command and `ss` proved the actual owned child.
Later startup explicitly used `--background --json` and checked that handshake.
Owned listeners were **1760353** (root) and **1787728** (subbase); both were stopped
by exact verified PID only. Service start/qualified/stopped receipts preserve full
commands and free-port observations. No live application endpoint was used.
The named browser was closed, all its routes restored and final normal console
reported zero errors. Injected errors and expected 404 console messages are separately
recorded. No browser auth state or credentials were stored.

## Exact reproduction and command outcomes

All commands below ran in this prototype unless another cwd is named. Every npm/npx
invocation, including web CLI commands, used the prototype-owned cache:

```sh
export PATH=/home/karl/.nvm/versions/node/v22.23.2/bin:$PATH
export NPM_CONFIG_CACHE=/home/karl/repo/huron/roadmap/prototypes/starlight/.npm-cache
export ASTRO_TELEMETRY_DISABLED=1
export GIT_OPTIONAL_LOCKS=0
node --version
npm --version
npm install --save-exact astro@7.3.5 @astrojs/starlight@0.42.5 @astrojs/markdown-remark@7.3.0
npm ls --all
npm ci
npm run check
npm test
npm run build
DOCS_BASE=/huron-docs/ npm run check
DOCS_BASE=/huron-docs/ npm run build
```

All exit 0 in the final static gate; `check` reports 0 errors/warnings/hints. Final
rebuild manifests still exactly match the clean package and the browser-tested
artifacts. Ordinary
Astro builds report optional empty i18n/missing custom 404 and missing `site` sitemap
warnings. The generated 404 works; no fabricated site URL was added to hide the
sitemap warning. Strict link validation is an explicit post-build checker.

`node scripts/receipt.mjs NAME COMMAND [ARGS]` captures exact cwd/argv/exit and full
output under `evidence/commands/NAME.{json,log}`; final receipts also include selected
safe environment values and duration. Initial failed harness/API assumptions are
retained: removed sidebar shorthand, returning Array.push from a unist visitor,
Pagefind metadata filename prefix, CLI VM lacking URL, duplicate result labels,
index query strings, native Popover/display:contents and browser-chrome focus.
Corrected probes assert public behavior; genuine F1 remains failed.

For browser reproduction after confirming the service is stopped, choose unused
evidence labels; do not overwrite existing evidence:

```sh
ss -ltnp '( sport = :4327 )'
node scripts/preview.mjs start review-root
DOCS_RUN=review-root npm run test:e2e
# Expected current result: exit 1, 24 passed / 6 failed (F1).
node scripts/preview.mjs stop
DOCS_BASE=/huron-docs/ node scripts/preview.mjs start review-subbase
DOCS_BASE=/huron-docs/ DOCS_RUN=review-subbase npm run test:e2e
node scripts/preview.mjs stop
```

`preview.mjs` uses qualified Astro CLI flags, checks the port and verifies PID identity.
`test:e2e` never starts/reuses an arbitrary server, and refuses existing output labels.
Clean reproduction was `node scripts/reproduce.mjs`; it refuses a pre-existing clean
directory rather than deleting it. The retained clean package can run its own ordinary
`npm ci`/check/build; its browser harness was not used as a substitute for the final
parent-package E2E runs.

Named CLI commands ran from `web/`, with the same PATH/cache exports:

```sh
npx --no-install playwright --version
npx --no-install playwright cli --help
npx --no-install playwright cli -s=huron-docs-prototype open http://127.0.0.1:4327
npx --no-install playwright cli -s=huron-docs-prototype run-code --filename=../roadmap/prototypes/starlight/scripts/cli-matrix.js
npx --no-install playwright cli -s=huron-docs-prototype run-code --filename=../roadmap/prototypes/starlight/scripts/cli-failure.js
npx --no-install playwright cli -s=huron-docs-prototype console
npx --no-install playwright cli -s=huron-docs-prototype route-list
npx --no-install playwright cli -s=huron-docs-prototype close
```

Matrix normal observations pass. Failure script returns an explicit FAIL observation;
CLI transport exit 0 is not a product PASS. The receipt wrapper also recognizes CLI
`### Error` output as failure even when its process exits 0. Do not replay screenshots
over retained evidence; assign fresh paths for independent review.

Root cwd gates (unchanged live renderer):

```sh
git diff --check
python roadmap/check_docs.py
UV_CACHE_DIR=/tmp/opencode/huron-effort-uv-cache make docs
git check-ignore -v roadmap/prototypes/starlight
git ls-files roadmap
```

Outcomes: 0, **1 (F2)**, 0, 0/ignored, 0/empty respectively. No Python application,
web application or .agents npm gate applies to the unchanged boundaries. Their
absence makes no product verification claim.

## Interfaces, limits and minimal follow-up plan

Concrete candidate interfaces, not promoted APIs:

```js
await planContent({ root, input: 'fixtures', manifest: 'content-map.json', base });
// => { files: Record<relativeOutput, Buffer>, proof: { base, inputs, files } }
await prepare({ root, input, manifest, output: 'src/content/docs', base, check: true });
checkSite({ root, dist: 'dist/subbase', base: '/huron-docs/', manifest });
// => exact route/content/asset hashes and checked local/external-reference counts
```

Input/output roots are separate and no-follow checked. An exclusive-create lock
serializes prepares; unknown/modified output refuses replacement. All input/link/title
validation precedes staging/publication. Prior known generations are retained under
`.work/previous-*`, not silently cleaned. Failed prepare exits nonzero and build does
not invoke Astro with stale inputs. This is cooperative local build ownership, not
a hostile-filesystem race defense, fsync/power-loss guarantee, multi-host lock or
production publication transaction. HTML URL checking covers emitted href/src/poster,
srcset, CSS URLs and declared Pagefind metadata/WASM; browser requests qualify the
dynamic search assets for this corpus, not arbitrary future JS/CSS syntax. Generic
MDX, every Markdown extension, browser engines beyond the two observed Chromium
versions, remote-link availability and full production content are not qualified.

Minimal next steps before a live implementation plan may claim readiness:

1. Independently reproduce/review F1 and qualify a small supported search error/retry
   boundary (or an explicitly reviewed package update). Keep the failure assertions
   green-required. No silent pin change or hosted-search fallback.
2. Parent-owned reconciliation of F2: define authored source versus vendor/generated
   evidence in the checker contract, preserving real source/link/whitespace checks.
   This assignment may not edit the checker or delete evidence to evade it.
3. Qualify narrow long-identifier/table CSS against F3 at all six matrix cells;
   preserve horizontal keyboard access and visible focus. Do not import app UI.
4. In an exclusive docs implementation slice, create the design's exact docs package,
   manifest, preparer/checker, content.config, local styles/assets and tests. Map every
   canonical file explicitly, keep original ADR/history/domain paths, and convert
   canonical PyMdown prose once; remove this prototype-only legacy conversion rather
   than adding a permanent renderer compatibility layer. Generalize safely from the
   measured corpus, not by copying the prototype wholesale.
5. Only after replacement gates and independent review, cut over root Makefile/CI,
   docs dependency group/uv lock and ignored output rules; remove only the named
   Zensical config, obsolete extra.css and vendor-mermaid helper. Existing source
   prose/user data is not obsolete. Choose deployment base/URL separately before SEO.
6. Detailed scientist/operator guides and verified MVP examples remain separate
   downstream work tied to actual product receipts. The copied fixture prose still
   contains existing limitations/overclaims; it is not an editorial release.

[Owned file inventory](evidence/owned-files.json) lists all 47 authored/copied paths
and hashes (bulk generated/dependency/evidence artifacts remain in their named owned
subdirectories). [Machine summary](evidence/summary.json) collects counts, browser/network
observations, source hashes, screenshots and clean comparison. Bulk artifacts stay
ignored; cleanup belongs to a later explicitly reconciled owner. Unknown work was
neither overwritten nor automatically reverted.

Independent review: **pending**, no independent PASS claimed by this writer.
