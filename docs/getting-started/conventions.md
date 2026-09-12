# Conventions

```bash
make lint    # every static check CI enforces
```

Static lint covers `src/`. Tests run separately as documented in AGENTS.md, and
migration schema-map validation remains required. Source thresholds and import
contracts apply unchanged:

```bash
uv run ruff check src                            # lint, including docstring presence and shape
uv run ruff format --check src                   # formatting
uv run pydoclint src                             # docstrings match signatures (see below)
uv run mypy                                      # types, strict
uv run ty check                                  # types, second opinion
uv run lint-imports                              # architectural boundaries
uv run python scripts/check_schema_map.py        # migrations/schema.sql is current
uv run radon cc src --min C                      # complexity; output must be empty
uv run radon mi src --min B                      # maintainability; output must be empty
uv run complexipy src --max-complexity-allowed 15
uv run --locked pyscn check src                 # dead code, complexity, clones
uv run --locked python scripts/check_duplication.py src  # native score must reach 90
```

## Formatting and lint

`ruff`, line length **100**, rule sets `E`, `F`, `I`, `N`, `UP`, `B`, `SIM`, `TCH`, `RUF`, `FAST`
and `D` (docstrings, Google convention — see [docstrings](docstrings.md)).

Per-file ignores exist and are narrow, each for a stated reason:

- `N818` (exception names should end in `Error`) is waived where a stable public error name
  mirrors its API code — `SlugImmutable`, `Forbidden`, `PrincipalKindNotAllowed`. The wire code
  is the contract; renaming the class to satisfy a linter would desynchronize them.
- `TC001`–`TC003` (move imports into a type-checking block) are waived across
  `src/huron/applications/api/**`, because FastAPI resolves annotations at runtime to build dependency
  injection — moving those imports breaks the application.
- `D301` (raw string for a docstring with a backslash) is waived for route modules
  (`routes/**/endpoints/*.py` and `app.py`), whose docstrings hold a `\f` so that FastAPI stops the
  published OpenAPI description before the `Args`/`Returns`/`Raises` sections.

Do not add a suppression to make a check pass. If a rule genuinely cannot be satisfied, the
narrow per-file ignore goes in `pyproject.toml` with a comment saying why.

## Types

`mypy --strict` and `ty` cover all of `src/`, including application wiring, core,
packages and schemas. Applications stay thin and reusable workflows belong in core.

Annotate every public function and method. `Any` is for genuinely open types, not for silencing.

## Import boundaries

`make lint` runs the import-linter contracts declared in `pyproject.toml`:

| Boundary | Rule |
|---|---|
| Layers | `applications` → `core` → `pkg` → `schema` |
| Domain independence | auth, catalog, RBAC and rawstore do not import one another |
| Infrastructure | metastore may import domain types; domains never import metastore |
| Core | injected ports, no concrete adapters, HTTP framework or compute runtime |
| Domain logic | no web framework, database driver or storage SDK |
| API authorization | routes use the authorization package's public surface |

Applications may import concrete adapters to wire core services. Pydantic and JSON Schema
validation are allowed in domain contracts. Add appropriate boundaries when introducing
new packages; do not weaken existing contracts to conceal reverse dependencies.

## The design record

`design/` is authoritative. Where code and a design document disagree, **the design document wins
and the code is what gets fixed**. Where `design/` is silent, decide fresh and record the decision
there first — in the same change that implements it, not afterwards.

This is why `docs/` covers only the repository: two prose descriptions of one architecture have to
agree forever, and the previous `docs/` tree drifted until it described a different product
entirely.

## Slugs and paths

Every organization, project and dataset carries an immutable, URL-safe `slug` fixed at creation
and a mutable display `title`. **No role can change a slug** — not an organization admin, not the
platform owner. A slug is baked into the storage path, so an immutable slug is what makes paths
permanently stable, which is what makes citations durable.

`pkg/catalog/paths.py` is the sole constructor **and parser** of storage paths. Never build one by
string concatenation elsewhere; the reconciler and sweeper depend on the round-trip property that
`parse_revision_dir(revision_dir(...))` recovers the original identity.

## Comments

Comments are rare and explain enduring intent — an invariant, a lifecycle assumption, a security
boundary, a subtle trade-off. They do not narrate the code, and they never reference an
implementation plan, a phase, a task number, or a review process.

## Docstrings

Every module, class, function and method carries one, and `pydoclint` holds it to the
signature. The standard, with examples, is its own page: [docstrings](docstrings.md).

## Documentation

This site is built by [Zensical](https://zensical.org), the Material for MkDocs team's successor
to MkDocs + Material, configured in `zensical.toml`.

```bash
make docs         # zensical build --strict — fails on broken internal links
make docs-serve   # live reload on :8000
```

`--strict` is what makes a broken cross-reference a build failure rather than a warning, so leave
it in place.

!!! warning "Do not add a Mermaid diagram without vendoring it first"

    The site is expected to serve on networks with no egress. `font = false` in `zensical.toml`
    keeps webfonts out entirely — a built site contains no reference to `fonts.googleapis.com` or
    `fonts.gstatic.com`, and that is worth re-checking after a toolchain upgrade:

    ```bash
    make docs && grep -rl "fonts.googleapis.com\|fonts.gstatic.com" site/
    ```

    The runtime bundle does contain lazy loaders that fetch from `unpkg.com` — Mermaid, Pyodide,
    GLightbox, Ace. Each is gated behind a feature actually appearing on a page, and none of these
    pages use one, so nothing is fetched today. Adding a single ```` ```mermaid ```` fence changes
    that silently: on a network that blocks `unpkg.com` the diagram renders as a raw code block
    **and search stops working on every page containing one**, because the failed script aborts
    the bundle before the search handler is wired up. It looks like a search bug and it is not.
    `scripts/vendor-mermaid.sh` exists for this; it was written against Material's
    `extra_javascript` and needs adapting to Zensical before it is used.
