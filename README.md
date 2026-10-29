# Huron

Huron is a catalog and access-control plane for raw scientific data that lives on an NFS share.
Scientists and administrators work through the `huron` command-line tool on machines that mount the
share at `/projects/huron`. A FastAPI service and a PostgreSQL database hold the catalog of
organizations, catalogs, namespaces and collections, their metadata, the role grants and an audit log.

Every directory the CLI creates carries POSIX ACLs derived from the catalog's role-to-LDAP-group
grants, so the filesystem enforces the same reader, contributor and administrator boundaries as the
service. Collection metadata is validated against a schema registry: each catalog is assigned a
schema, and a collection may extend it with an override. Pushes are synchronous commits that carry the
version they were based on, so a push that is behind is refused until the user pulls.

The service never touches file bytes. The CLI copies files over the mount and records them with the
service; `huron check` reports where disk and catalog disagree.

## Quick start

```bash
uv sync
make up          # PostgreSQL and Keycloak for development
make migrate
make api         # http://127.0.0.1:8080
uv run huron config set api_url http://127.0.0.1:8080
uv run huron login
```

## Documentation

- [Architecture](docs/architecture.md)
- [Operator guide](docs/operator.md)
- [User guide](docs/user-guide.md)
- [API error codes](docs/api-errors.md)
- [Architecture decision records](docs/adr/)
- [Implementation plan](IMPLEMENTATION_PLAN.md)

## Development

`make gate` runs the full validation gate: ruff, mypy, ty, import-linter, the unit tier with coverage,
radon, complexipy and the schema-map check. `make test-contract` and `make test-integration` run the
PostgreSQL-backed tiers.
