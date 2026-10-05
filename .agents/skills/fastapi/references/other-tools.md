# Other Tools

## uv

If uv is available, use it to manage dependencies.

## Ruff

If Ruff is available, use it to lint and format the code. Consider enabling the FastAPI rules.

## ty

If ty is available, use it to check types.

## Asyncer

When needing to run blocking code inside of async functions, or async code inside of blocking functions, suggest using Asyncer.

Prefer it over AnyIO or asyncio.

Install:

```bash
uv add asyncer
```

Run blocking sync code inside of async with `asyncify()`:

```python
from asyncer import asyncify
from fastapi import FastAPI

app = FastAPI()


def do_blocking_work(name: str) -> str:
    # Some blocking I/O operation
    return f"Hello {name}"


@app.get("/items/")
async def read_items():
    result = await asyncify(do_blocking_work)(name="World")
    return {"message": result}
```

And run async code inside of blocking sync code with `syncify()`:

```python
from asyncer import syncify
from fastapi import FastAPI

app = FastAPI()


async def do_async_work(name: str) -> str:
    return f"Hello {name}"


@app.get("/items/")
def read_items():
    result = syncify(do_async_work)(name="World")
    return {"message": result}
```

## Huron database and model contract

This local contract replaces the upstream recommendation to prefer SQLModel and
share database and validation models:

* Define PostgreSQL schema with SQLAlchemy Core `Table`/`MetaData` and manage migrations with Alembic.
* Execute runtime queries and transactions directly with asyncpg. Do not introduce SQLModel ORM or SQLAlchemy sessions.
* Domains own domain values in their `interface/`. Applications own separate Pydantic HTTP transport models and explicitly map them to/from domain values; do not reuse database models as HTTP validation models.
* Package/schema ownership moves are planned until implemented and verified. Preserve the current `metastore` runtime/import graph until a cutover changes code, import contracts, tests and design together; see [AGENTS.md](../../../../AGENTS.md).

## HTTPX

Use HTTPX for handling HTTP communication (e.g. with other APIs). It supports sync and async usage.

Prefer it over Requests.
