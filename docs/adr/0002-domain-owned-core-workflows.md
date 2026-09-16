---
status: accepted
---

# Domain modules own their workflows

Huron's separate `pkg` and `core` tiers distribute a domain's values, invariants,
authorized operations, and persistence interfaces across the repository. We decided
on 2026-09-15 to colocate them in domain subpackages under `huron.core`, with an
explicit acyclic dependency graph and public interfaces for cross-package callers.
Catalog owns hierarchy identities; Raw owns submission, revision publication and
reads, and release tags; Security combines authentication, identity administration,
and authorization; Integrity owns cross-domain verification and cutover workflows.

Metastore and Rawstore remain concrete adapter packages under Core. Domains own
their consumer interfaces and receive injected implementations. A narrowly scoped
Foundation holds genuinely shared primitives. In particular, Security consumes its
own catalog-fact projections rather than importing Catalog entities, so Catalog can
depend on Security without a reverse edge. Applications call published operations
and construct published adapters, while retaining transport and resource lifetimes.

The trade-off favors locality over the old mutual independence of capability
packages: useful one-way domain dependencies become permitted and mechanically
checked. Combining authentication and authorization avoids a second set of
cross-domain identity projections, while keeping their implementations focused.
Public interfaces include the values, errors, construction requirements, and
failure guarantees callers need; they do not require one all-purpose facade class.

The migration also retires unused future-capability declarations and other code
without a useful current responsibility. Planned capabilities remain in the design
record; useful pure rules, operational guarantees and reserved error-code vocabulary
remain part of the supported contract.

This is an accepted architecture decision, not an implementation receipt. The target
graph is recorded in `design/architecture.html#domain-owned-core`; delivery status
is in `design/roadmap.html#domain-owned-core-migration`. The
[implementation history](../history.md#domain-owned-core) records verification and
links to the archived complete migration plan, ownership and removal inventory.
