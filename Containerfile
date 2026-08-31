# Multi-stage build: resolve the locked venv with uv, then copy just the
# venv and application code into a slim runtime image with no build tooling
# and no root user. Development-only convenience (reload, dev headers) lives
# on the host via `make api`; this image is the containerized path (`make
# stack`) and always runs plain uvicorn.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS build
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
# --no-dev excludes the whole [dependency-groups].dev group (ruff, mypy,
# ty, radon, complexipy, pyscn, the test toolchain, ...) - none of it is
# needed to run the service, and pyscn's environment marker never affects
# a --no-dev resolve since the entire group is skipped.
RUN uv sync --frozen --no-install-project --no-dev
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --frozen --no-dev

FROM python:3.12-slim-bookworm
RUN useradd --system --uid 1001 huron
WORKDIR /app
COPY --from=build --chown=huron:huron /app /app
ENV PATH="/app/.venv/bin:$PATH"
USER huron
EXPOSE 8080
CMD ["uvicorn", "huron.service.api.app:app", "--host", "0.0.0.0", "--port", "8080"]
