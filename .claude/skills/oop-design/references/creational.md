# Creational decisions

Contents: Factory Method · Abstract Factory · Builder · Prototype · Singleton.

## Factory Method

**Mechanism:** An existing creator workflow calls an overridable product-creation method; subclasses select the concrete product. [Pattern reference](https://refactoring.guru/design-patterns/factory-method).

**Use when:** A framework or reusable workflow intentionally supports subclass extension and must construct products through that extension point.

**Avoid when:** Configuration merely chooses a constructor, or introducing a creator hierarchy is the only reason for inheritance.

**Alternatives:** A simple factory function or constructor registry handles runtime selection. Inject a callable factory when creation varies independently of the workflow. Use Abstract Factory when several related product types must stay compatible.

**Implementation checks:** Keep the workflow dependent on the product contract. Specify fresh versus reused instances and ownership. Exercise the workflow with multiple products. Do not call every static `create()` function a GoF Factory Method; a dispatch table does not require subclassing.

## Abstract Factory

**Mechanism:** One factory contract creates a family of related products; each concrete factory supplies a compatible variant. [Pattern reference](https://refactoring.guru/design-patterns/abstract-factory).

**Use when:** Switching a backend requires matching collaborators—for example, a storage session and its transaction implementation—and mixing families would be invalid.

**Avoid when:** There is one product type, no compatibility constraint, or product categories change constantly. Adding a category affects every factory.

**Alternatives:** A simple factory handles one product. Explicit dependency assembly suffices for a fixed combination. Builder handles staged assembly of one result rather than selecting a product family.

**Implementation checks:** Select the family at the composition boundary. Keep its products interoperable without leaking concrete types into consumers. Check cross-product compatibility; factory names alone do not enforce it.

## Builder

**Mechanism:** Accumulate construction inputs or steps, then produce a complete result; optionally reuse a construction sequence for different representations. [Pattern reference](https://refactoring.guru/design-patterns/builder).

**Use when:** Assembly has meaningful stages, interdependent options, or several representations. A fluent API may help complex caller-driven construction.

**Avoid when:** A few named arguments with defaults already describe a valid object clearly. Optional fields alone are not sufficient justification.

**Alternatives:** Named constructor arguments or a configuration value for simple assembly; named factory functions for useful presets; Abstract Factory for compatible product families.

**Implementation checks:** Validate cross-field invariants at completion, prevent partial results escaping, and define whether the builder is reusable. Avoid mutable aliasing between builder and completed objects. Add a director only when a reusable assembly recipe actually exists.

## Prototype

**Mechanism:** Create a new object through the copying contract of an existing instance. [Pattern reference](https://refactoring.guru/design-patterns/prototype).

**Use when:** Runtime-configured instances are useful templates, or copying preserves configuration that is difficult to reconstruct through the client interface.

**Avoid when:** Instances contain identities, locks, sockets, subscriptions, or ownership that cannot safely be duplicated. Copying is not inherently cheaper than construction.

**Alternatives:** Copy-with operations on immutable values for small variations; constructor/factory for clear initialization; Flyweight for sharing data rather than duplicating it.

**Implementation checks:** Define shallow versus deep copying, shared subgraphs, cycles, and identity regeneration. Confirm mutating the copy cannot unexpectedly change its source. Benchmark if cost reduction is the motivation; serialization is not automatically a correct clone operation.

## Singleton

**Mechanism:** Restrict class instances within a defined runtime scope and expose a shared access point. [Pattern reference](https://refactoring.guru/design-patterns/singleton).

**Use when:** A legacy or framework contract truly requires unique class access and that scope is understood. Prefer explicit application-owned lifetime when uniqueness alone is the requirement.

**Avoid when:** It merely shortens dependency passing, hides mutable state, conflates tenants, or claims uniqueness across processes or machines.

**Alternatives:** Construct one object at startup and inject it for application lifetime; scoped containers for request or tenant lifetime; immutable configuration values for settings. Cross-process coordination needs an appropriate external protocol or authority.

**Implementation checks:** Establish initialization and shutdown ownership, safe publication, concurrent access, and test isolation. Thread-safe creation does not make subsequent operations thread-safe. A single pool manager may own many connections; do not replace it with one globally shared connection by analogy.
