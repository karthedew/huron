# Getting started

```bash
git clone <repo> && cd huron
uv sync                       # runtime + dev dependencies
make hosts                    # once: "127.0.0.1 keycloak" in /etc/hosts
make up                       # PostgreSQL on :5433, MinIO on :9000/:9001, Keycloak on :8081
make migrate                  # alembic upgrade head, configured by dev.env
make test                     # the fast unit suite
```

`make api` then serves the control plane on `http://localhost:8080`, configured by `dev.env`,
and `make web` serves the frontend on `http://localhost:5173`.

Four things are worth knowing before the first change lands:

1. **[`design/`](../index.md) is authoritative.** If code and a design document disagree, the
   design document wins and the code is what gets fixed — see
   [conventions](conventions.md#the-design-record).
2. **`make lint` runs the whole validation gate.** Eleven steps, described in
   [conventions](conventions.md); the docstring rules have [their own page](docstrings.md).
3. **`pytest` runs only the unit suite by default.** The other three suites need real services;
   see [testing](testing.md).
4. **Packages may not import their siblings.** This is mechanically enforced and is the rule new
   contributors trip over most — see [repository layout](repository-layout.md).
