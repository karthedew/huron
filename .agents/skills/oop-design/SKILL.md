---
name: oop-design
description: Design, implement, refactor, and review object-oriented projects by assigning responsibilities, protecting invariants, and choosing design patterns with explicit tradeoffs and simpler alternatives. Use for OOP architecture, class collaborations, and GoF pattern selection; not routine edits merely because a project contains classes.
---

# OOP Design

Produce a design that makes the requested behavior easy to implement and change. Patterns are adaptable design ideas, not required scaffolding or a checklist of classes. Respect the project's language, framework, domain vocabulary, and existing conventions.

## Work from the problem

Inspect relevant code, requirements, tests, and documented decisions before proposing structural changes. Establish the use cases, state invariants, dependency boundaries, and concrete axis of variation. Distinguish observed requirements from speculative future extensions. Ask only about gaps that materially affect the design; otherwise state reasonable assumptions and proceed.

Start with the simplest viable implementation: a function, value object, ordinary class, direct collaboration, or small conditional. Introduce a pattern when it isolates a demonstrated source of change, enforces a meaningful contract, or addresses a measured constraint. A pattern name is not evidence of a better design. Preserve an explicit user request to demonstrate a pattern, while explaining its educational or production tradeoffs.

## Design responsibilities before class hierarchies

- Put behavior with the state and knowledge needed to enforce its rules. Expose domain operations rather than setters that permit invalid combinations. Define which object owns each invariant and when it must hold.
- Distinguish values compared by contents from entities tracked by identity. Prefer immutable values where appropriate; make mutation, aliasing, ownership, and lifecycle explicit.
- Use composition for independently varying behavior. Use inheritance when every subtype can honor the parent contract, including preconditions, results, errors, and side effects. Code reuse alone does not establish substitutability.
- Give interfaces a consumer or extension purpose. Do not create an interface for every class, fragment cohesive behavior into tiny services, or force classes around naturally functional transformations.
- Separate domain decisions from I/O where doing so improves clarity or testing. Assemble dependencies at an application boundary; define who creates, shares, and closes resources. Constructor injection often suffices without a container.
- Organize modules around cohesive responsibilities and reasons to change. Avoid imposing a layered, DDD, or microservice architecture on a small project merely to accommodate patterns.
- Apply SOLID as diagnostic questions about cohesion, extension, substitutability, interface burden, and dependency direction—not as a demand for more abstractions.

## Select only relevant references

Read the relevant entries before recommending or implementing a pattern. Each entry gives mechanism, applicability, rejection criteria, conditional alternatives, and implementation checks. These are decision aids, not a requirement to use all 23 patterns.

| Design pressure | Reference |
| --- | --- |
| Construction, compatible product families, assembly, copying, shared instance scope | [Creational patterns](references/creational.md) |
| Incompatible APIs, independent dimensions, trees, wrappers, subsystem boundaries, memory sharing | [Structural patterns](references/structural.md) |
| Algorithms, lifecycle behavior, workflows, notifications, traversal, undo, requests, grammars | [Behavioral patterns](references/behavioral.md) |
| Similar patterns appear plausible or the user asks which alternative fits | [Comparisons and decision examples](references/selection.md) |
| Source provenance, limitations, or further reading | [Sources](references/sources.md) |

## Turn a choice into working code

For each material design choice, explain the concrete pressure, the simplest alternative, why the selected approach fits, and its added cost. Identify the requirement that would make you reconsider. Scale this explanation to the task; do not produce a design document or decision record unless requested or useful under repository conventions.

Use domain names for code, and pattern names in explanations when useful. Show who calls whom and who owns state; use a small diagram only when it clarifies collaboration. Use native protocols, callable values, records, enums, generators, and framework facilities instead of mechanically translating Java-style class diagrams.

For implementation requests, implement the design within the requested scope. Wire construction and actual call sites; a collection of interfaces and unconnected classes is incomplete. Refactor incrementally, preserving observable behavior unless the user requests a change. Do not accumulate multiple patterns for a single concern without separate reasons.

Validate behavior and boundaries appropriate to the change: domain invariants, interchangeable implementations, invalid transitions, errors, resource cleanup, and relevant integration contracts. Prefer public behavior assertions over tests coupled to the new class layout. Benchmark before claiming performance improvements. Report what changed, why, validation performed, and remaining limitations.
