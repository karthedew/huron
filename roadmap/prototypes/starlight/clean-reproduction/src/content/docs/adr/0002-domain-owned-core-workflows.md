---
status: accepted
title: Domain modules own their workflows
---

> **Throwaway prototype — not shipped documentation.** Canonical source: `docs/adr/0002-domain-owned-core-workflows.md`. Generated rendering view; original source remains authoritative.

<a id="domain-modules-own-their-workflows"></a>

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
graph is recorded in `design/architecture.html#domain-owned-core`. The
[implementation history](/huron-docs/history/#domain-owned-core) records verification and
links to the archived complete migration plan, ownership and removal inventory.

## Subsequent Raw-first target (2026-10-04)

The ownership rationale remains accepted. The selected target in
`design/raw-first.md` supersedes the future package split: combine Raw workflows
and private filesystem adapters as `core/rawstore`, group SQLAlchemy Core table
definitions and asyncpg repositories under database/schema, move Foundation values
to actual owners, and publish supported operations/values/errors/ports through
owner `interface/` directories with root reexports. Collection replaces Project.
The scientist SDK is a separate lightweight distribution with `Client()` and direct
service namespaces, not a server Core facade.

This change favors cohesive Raw lifecycle ownership and stable public imports while
retaining injected consumer ports and domain authorization. It does not authorize
private cross-owner imports or data deletion. Exact moves, migration policy,
prototype evidence and coordinated import-contract cutover remain blocked in local
phase planning. The existing seven-owner `pyproject.toml` graph is still enforced.
