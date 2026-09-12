# huron

Control plane for a raw-data-first scientific lakehouse: organizations, projects and datasets
with immutable revisions, four storage layers (raw on NFS; Bronze/Silver/Gold as Zarr + Icechunk
repositories on Ceph RGW), and role-based access control scoped to the storage layer.

- **Design record — authoritative:** [`design/index.html`](design/index.html). Fifteen
  cross-linked documents covering the model, the layers, RBAC, and every decision with its
  rejected alternative. Where code and design disagree, the design wins.
- **Duplication refactoring plan:** [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md).
- **Historical authentication and authorization plans:**
  [`AUTH_IMPLEMENTATION_PLAN.md`](AUTH_IMPLEMENTATION_PLAN.md) and
  [`RBAC_IMPLEMENTATION_PLAN.md`](RBAC_IMPLEMENTATION_PLAN.md).
- **Developer documentation:** [`docs/`](docs/) — environment, conventions, testing, repository
  layout. Build it with `make docs`, or read the Markdown directly.

```bash
uv sync && make up && make migrate && make test
```
