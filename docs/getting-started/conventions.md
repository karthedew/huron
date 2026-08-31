# Conventions

```bash
make lint    # every static check CI enforces
```

That is four commands, and all four must be clean:

```bash
uv run ruff check .           # lint
uv run ruff format --check .  # formatting
uv run mypy                   # types
uv run lint-imports           # architectural boundaries
```

## Formatting and lint

`ruff`, line length **100**, rule sets `E`, `F`, `I`, `N`, `UP`, `B`, `SIM`, `TCH`, `RUF`.

Per-file ignores exist and are narrow, each for a stated reason:

- `N818` (exception names should end in `Error`) is waived where a stable public error name
  mirrors its API code — `SlugImmutable`, `Forbidden`, `PrincipalKindNotAllowed`. The wire code
  is the contract; renaming the class to satisfy a linter would desynchronize them.
- `TC001`–`TC003` (move imports into a type-checking block) are waived across
  `src/huron/service/api/**`, because FastAPI resolves annotations at runtime to build dependency
  injection — moving those imports breaks the application.

Do not add a suppression to make a check pass. If a rule genuinely cannot be satisfied, the
narrow per-file ignore goes in `pyproject.toml` with a comment saying why.

## Types

`mypy --strict` covers `src/huron/pkg` and `src/huron/schema`. Services are composition roots full
of third-party wiring and join once the frameworks they compose have settled — which means **new
logic belongs in a package, where it is type-checked**, and services stay thin.

Annotate every public function and method. `Any` is for genuinely open types, not for silencing.

## Import boundaries

Four `import-linter` contracts, all checked in CI:

| Contract | Rule |
|---|---|
| *layers* | `service` → `pkg` → `schema`, never the reverse |
| *independence* (packages) | no `pkg` imports another `pkg` |
| *independence* (services) | no `service` imports another `service` |
| *forbidden* | no web framework, driver or storage SDK inside `pkg/catalog` or `pkg/rbac` |

The forbidden list is `fastapi`, `uvicorn`, `starlette`, `sqlalchemy`, `asyncpg`, `alembic`,
`aiobotocore`, `boto3`, `botocore`, `lancedb`, `icechunk`, `zarr`, `httpx`, `structlog` and
`prometheus_client`. `pydantic` and `jsonschema` are deliberately absent.

When adding a package, add it to the independence contract's module list in the same change.

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
