# FastAPI service audit against the `fastapi` skill

Audit of `src/huron/service/api/` against `.claude/skills/fastapi/SKILL.md` and its six
references (`dependencies`, `path-operations`, `pydantic`, `responses`, `streaming`,
`other-tools`), performed 2026-09-01. Seed document for `/design-plan`; it records findings
only — it proposes no design and commits to no fix.

## Method

Every module under `src/huron/service/api/` was read in full (35 files, 3640 lines), and the
call paths the handlers reach were traced into `pkg/rawstore` and `pkg/rbac`. Two classes of
evidence appear below:

- **source citations** — file and line, for structural facts (what a signature declares, where
  a router's tags are attached, which call is awaited and which is not);
- **executed checks** — FastAPI 0.141.1 (the version `uv.lock` pins, line 866) was installed in
  a scratch environment and interrogated directly, so every feature recommended below is
  confirmed present on the pinned version rather than assumed from the skill's prose.

Receipt for the version check:

    version 0.141.1
    app.frontend        True
    router.frontend     True
    fastapi.sse         EventSourceResponse, ServerSentEvent, KEEPALIVE_COMMENT, ...
    Depends(scope=...)  True

## Conforms — do not re-flag

- No `...` (Ellipsis) as a default in any Pydantic field or parameter declaration.
- No `RootModel` anywhere; list bodies are not wrapped.
- No `ORJSONResponse` or `UJSONResponse` (both deprecated per the skill).
- No `@app.api_route(methods=[...])`: one HTTP operation per function throughout.
- No `StaticFiles` mount and no manual asset serving.
- `Annotated` is used correctly where it is used: `IdempotencyHeader` and `IfMatchHeader`
  (`routes/v1/common.py:15-16`), `CurrentPrincipal` (`authorization.py:218`), and the `_Actor`
  alias (`routes/v1/endpoints/users.py:36`).
- `dataset_layer_writer` (`authorization.py:383`) is a plain function dependency returning a
  frozen `LayerWrite` dataclass — exactly the pattern `references/dependencies.md` prescribes
  in place of `Annotated[SomeClass, Depends()]`. No class dependencies exist in the tree.
- uv, Ruff and ty are configured (`pyproject.toml`); httpx is used rather than requests.
- Domain, auth and role errors are mapped to `application/problem+json` by three
  `@app.exception_handler` registrations (`app.py:138-172`).

## Findings

### F1 — blocking filesystem I/O runs on the event loop  (material)

`HierarchyRepository.create_organization`, `create_project`, `create_dataset`,
`patch_organization`, `patch_project`, `patch_dataset` and `create_release` are synchronous
(`repository.py:459, 481, 522, 572, 600, 676, 702`), take a `threading.RLock`
(`repository.py:255`), and reach `PosixRawStore.write_generation` / `write_tag_once`, which
perform `mkdir`, `os.open`, `os.fsync`, `os.replace` and `fsync_dir`
(`pkg/rawstore/store.py:76-114`, `pkg/rawstore/commit.py:17-38`).

Every one of those is called **unawaited from inside an `async def` path operation** —
`endpoints/organizations.py:30,64`, `endpoints/projects.py:30,69`,
`endpoints/datasets.py:42,81,100`. An `fsync` under load stalls the event loop for every other
in-flight request, and the `RLock` can hold it there. `readyz` (`app.py:179`) stats the
filesystem the same way.

The skill's rule: use `async def` only when nothing inside blocks; in doubt, use `def` and let
FastAPI run it in a threadpool. `references/other-tools.md` offers `asyncer.asyncify()` as the
alternative for keeping the handler async. Both are conformant; this document does not choose.

### F2 — no response models; the OpenAPI schema is empty  (material)

Every v1 handler returns `dict[str, object]` (or `dict[str, str]`), assembled by `jsonable()`
and `page()` in `routes/v1/common.py`. `grep -rn 'response_model' src/huron/service` returns
nothing. Consequences, in the skill's own terms (`references/responses.md`): no response
filtering, no documented response schema for any client, and no Pydantic Rust-side
serialization.

The correct pattern is already present in the tree for contrast: `routes/auth/schema/session.py`
declares `SessionInfo` and `ProviderInfo`, and `endpoints/session.py:18,31` returns them as
declared return types.

Note that `issue_api_key` (`endpoints/auth.py:43-49`) and `issue_service_account_key`
(`endpoints/rbac.py:230-236`) return a plaintext `secret` in the body. That is deliberate — a
key is shown once — but with no response model nothing in the code says so.

### F3 — `GET /api/v1/roles` is unauthenticated  (material)

`list_roles` (`endpoints/rbac.py:41`) takes `request: Request` and immediately `del request`.
It declares no `CurrentPrincipal` and no `require_*` guard, making it the only v1 route without
an actor. The role catalog is not sensitive, but nothing marks the omission as intentional.

`GET /api/v1/search` (`app.py:186`) is likewise unauthenticated; it raises
`ProjectionUnavailable` unconditionally, so it leaks nothing today.

### F4 — shared dependencies are not declared at router level  (material)

Read routes carry `_actor: CurrentPrincipal` as a parameter whose value is never used — the
underscore says so (`endpoints/organizations.py:48,58`, `endpoints/projects.py:51,63`,
`endpoints/datasets.py:65,75,121,135`, `endpoints/policies.py:40`). The skill directs shared
guards to `APIRouter(dependencies=[Depends(...)])`, keeping the parameter only where the value
is consumed. Applied here it also closes F3 structurally rather than by inspection.

### F5 — router prefix and tags are not declared on the router  (material)

All seven v1 routers and all three auth routers are bare `APIRouter()`; tags are passed at
`include_router` (`routes/v1/__init__.py:10-16`) and prefixes are repeated in full on every
path operation. `references/path-operations.md` is explicit that both belong on the `APIRouter`.

Constraint worth recording rather than wishing away: `endpoints/datasets.py` spans both
`/projects/{project_id}/datasets` and `/datasets/{dataset_id}`, and `endpoints/rbac.py` spans
four scope roots, so a single `prefix=` does not fit those modules without splitting them.
Tags carry no such constraint.

### F6 — `Request` is threaded through handlers that only want the repository  (minor)

Nearly every handler declares `request: Request` solely to call `get_repository(request)` or
`get_settings(request)` (`authorization.py:79, 84`). The tree already proves the idiom with
`CurrentPrincipal`; the same treatment for the repository and settings would remove `Request`
from most signatures. It must stay where `request.state.session` is read
(`endpoints/login.py:64`, `endpoints/session.py:19`) and where the per-request binding cache
lives (`authorization.py:225-280`).

### F7 — `limit` is undeclared and silently clamped  (minor)

`limit: int = 50` on three list routes (`endpoints/organizations.py:48`,
`endpoints/projects.py:51`, `endpoints/datasets.py:65`) carries no `Query()` metadata, so
neither the bound nor the default is documented. `page()` then rewrites out-of-range input
silently: `max(1, min(limit, 200))` (`routes/v1/common.py:20`). A caller asking for 5000 gets
200 and is never told.

### F8 — dead parameter  (minor)

`list_roles(request: Request)` followed by `del request` (`endpoints/rbac.py:41-43`).

### F9 — deviations from the skill's tooling and library preferences  (deliberate; decide, do not assume)

Recorded so a later reader does not mistake them for oversights. Each needs a decision, not a
correction:

- **`fastapi dev` / `fastapi run` are unavailable.** `fastapi-cli` is not a dependency
  (`pyproject.toml`, `uv.lock`), there is no `[tool.fastapi] entrypoint`, and both the Makefile
  (`api:` target) and the Containerfile invoke `uvicorn` directly. The Containerfile comment
  says this is on purpose.
- **SQLModel.** `references/other-tools.md` prefers it over SQLAlchemy. Huron's stores use
  asyncpg directly behind protocols, and import-linter contracts
  (`pyproject.toml`, "auth is web-framework-free") deliberately keep both the web framework and
  the ORM out of `pkg`.
- **`app.frontend()`.** `web/build` exists (SvelteKit). The skill directs built frontends to
  `app.frontend()` / `router.frontend()` rather than a `StaticFiles` mount. Huron mounts
  nothing today and serves the shell separately.

## Not in scope

`src/huron/schema` and `migrations/` are being changed concurrently. Nothing in this audit
depends on the database schema, and no finding here should be resolved by a migration.
