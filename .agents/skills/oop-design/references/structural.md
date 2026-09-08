# Structural decisions

Contents: Adapter · Bridge · Composite · Decorator · Facade · Flyweight · Proxy.

## Adapter

**Mechanism:** Translate an existing collaborator into the contract a consumer expects. [Pattern reference](https://refactoring.guru/design-patterns/adapter).

**Use when:** A vendor or legacy API has incompatible calls, data, or error semantics and the consumer needs a stable boundary.

**Avoid when:** Both interfaces can be changed coherently, or the wrapper just forwards identical methods without protecting a boundary.

**Alternatives:** A conversion function for data-only mismatch; direct refactoring for internally controlled APIs; Facade for a simpler subsystem entry point.

**Implementation checks:** Translate semantics, including units, nullability, errors, cancellation, and ownership—not only names. Test the adapter against the provider contract. Do not hide unavoidable capability differences behind misleading promises.

## Bridge

**Mechanism:** An abstraction delegates to a separate implementation family so both dimensions can evolve independently. [Pattern reference](https://refactoring.guru/design-patterns/bridge).

**Use when:** Two real dimensions produce a multiplication of subclasses, such as report kinds and rendering backends with their own behaviors.

**Avoid when:** Only one dimension varies, combinations are mostly invalid, or the second hierarchy is hypothetical.

**Alternatives:** Strategy for a replaceable algorithm; plain composition for a fixed collaborator; Adapter for retrofitting an incompatible API.

**Implementation checks:** Design a small implementation contract that supports each abstraction without backend type checks. Test meaningful combinations. Keep unsupported combinations explicit rather than pretending the full Cartesian product works.

## Composite

**Mechanism:** Leaves and containers support common operations; containers delegate through a recursive structure. [Pattern reference](https://refactoring.guru/design-patterns/composite).

**Use when:** Clients need uniform operations over whole-part trees, such as evaluating nested rule groups and individual rules.

**Avoid when:** Group operations have fundamentally different meanings, or the data is a graph with shared nodes and cycles requiring different traversal rules.

**Alternatives:** Explicit tree data plus recursive functions for mostly data-oriented structures; Iterator for traversal alone; Visitor when many external operations target stable node types.

**Implementation checks:** Decide parent ownership, allowed sharing, cycle prevention, and aggregation semantics. Keep child-management methods off leaf contracts if they cannot support them. Verify empty groups and nested structures.

## Decorator

**Mechanism:** Wrap a component with the same contract to compose additional behavior. [Pattern reference](https://refactoring.guru/design-patterns/decorator).

**Use when:** Optional behaviors must be combined independently around individual objects without a subclass for every combination.

**Avoid when:** Behavior is universal and trivial, wrappers require concrete downcasts, or ordering makes the system harder to reason about than explicit orchestration.

**Alternatives:** Direct implementation for one stable behavior; functions or middleware for call wrapping; Strategy for replacing the core algorithm; Proxy for controlling access to a target.

**Implementation checks:** Specify wrapper order, exception propagation, resource closure, and whether repeated wrapping is valid. Test relevant compositions, especially retry or caching around side effects. A language annotation called a decorator is not necessarily this object pattern.

## Facade

**Mechanism:** Expose a focused operation over a more complex subsystem. [Pattern reference](https://refactoring.guru/design-patterns/facade).

**Use when:** Several callers repeat a subsystem interaction or need insulation from its internal coordination.

**Avoid when:** The facade becomes an all-purpose service containing unrelated policy, or it hides operations whose failure and cost callers must control.

**Alternatives:** A module function for stateless coordination; a cohesive application service for a use case; Adapter when compatibility is the problem.

**Implementation checks:** Keep a bounded responsibility and specify partial failure behavior. A convenient method does not make several external effects atomic. Preserve meaningful errors and access to necessary capabilities.

## Flyweight

**Mechanism:** Share intrinsic state between many logical objects; supply instance-specific context separately. [Pattern reference](https://refactoring.guru/design-patterns/flyweight).

**Use when:** Measurements show many duplicates of large, shareable values materially increase memory use.

**Avoid when:** Shared data must mutate independently, object counts are small, or lookup and synchronization cost exceed savings.

**Alternatives:** Ordinary immutable value reuse or interning for simple cases; compact arrays for dense data; caching for repeated computation; Prototype for independent copies.

**Implementation checks:** Make shared state immutable or control mutation rigorously. Define keys, retention/eviction, and identity semantics. Measure total memory including the lookup structure; sharing a payload does not remove per-instance overhead.

## Proxy

**Mechanism:** A substitute controls access to a target while presenting its contract. [Pattern reference](https://refactoring.guru/design-patterns/proxy).

**Use when:** Lazy creation, access checks, remote access, or caching belongs at the target boundary.

**Avoid when:** Apparent transparency conceals latency, network failure, stale data, or side effects the caller must reason about explicitly.

**Alternatives:** An explicit service client for remote semantics; a lazy supplier for deferred construction; Decorator for composable enrichment; Adapter for contract translation.

**Implementation checks:** Define failure, timeout, identity, initialization races, and cache invalidation as relevant. Never infer that interface compatibility makes a remote operation behave like an in-memory call. Keep authorization enforceable at the actual protected boundary.
