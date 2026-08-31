# Getting started

```bash
git clone <repo> && cd huron
uv sync                       # runtime + dev dependencies
make up                       # PostgreSQL on :5433, MinIO on :9000/:9001
make migrate                  # alembic upgrade head
make test                     # the fast unit suite
```

`make api` then serves the control plane on `http://localhost:8080`.

Four things are worth knowing before the first change lands:

1. **[`design/`](../index.md) is authoritative.** If code and a design document disagree, the
   design document wins and the code is what gets fixed — see
   [conventions](conventions.md#the-design-record).
2. **`make lint` runs everything CI runs.** Four checks, described in
   [conventions](conventions.md).
3. **`pytest` runs only the unit suite by default.** The other three suites need real services;
   see [testing](testing.md).
4. **Packages may not import their siblings.** This is mechanically enforced and is the rule new
   contributors trip over most — see [repository layout](repository-layout.md).
