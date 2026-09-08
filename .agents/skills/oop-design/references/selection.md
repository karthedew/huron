# Resolve competing designs

Use intent and actual change pressure to choose; similar delegation diagrams do not imply interchangeable patterns. This file contains original decision guidance and illustrative scenarios, informed by the linked pattern references in the family files.

## Questions that separate common candidates

| Candidates | Deciding question |
| --- | --- |
| No pattern / any pattern | What observed change or invariant becomes simpler enough to justify the new indirection? |
| Simple factory / Factory Method | Is runtime selection enough, or must subclasses customize creation inside an inherited workflow? |
| Factory Method / Abstract Factory / Builder | Does creation vary through subclass hooks, require a compatible family, or require staged assembly? |
| Prototype / Flyweight | Do clients need independent copies or shared immutable payloads? |
| Adapter / Facade | Must you satisfy an existing consumer contract or provide a smaller subsystem API? |
| Adapter / Bridge | Are you translating an existing mismatch or separating two independently growing dimensions? |
| Decorator / Proxy | Is the wrapper composing features or governing access/lifetime? Some implementations serve both intents. |
| Strategy / State | Is variation an independently chosen policy or behavior tied to lifecycle transitions? |
| Strategy / Template Method | Should steps vary by composition or by subclassing a fixed workflow? |
| Command / Strategy | Must an action be retained and executed separately, or is an algorithm being substituted? |
| Command / Memento | Is history about requested operations or restorable local state? Undo may combine them. |
| Observer / Mediator / Chain | Are reactions independent broadcasts, centrally coordinated interactions, or ordered handler decisions? |
| Composite / Iterator / Visitor | Is the need uniform tree behavior, traversal abstraction, or new operations over stable types? |

## Decision examples

### Small exporter with two formats

A utility has two short, stable formatting branches. Keep a direct conditional or two functions. If independent format implementations develop substantial behavior, use a callable or Strategy contract. A registry may select the formatter; it does not justify a creator-subclass hierarchy. Reconsider when new formats repeatedly require risky changes to the orchestration.

### Integration with two external document stores

Start with adapters translating provider behavior into the domain's actual needs. Assemble the selected implementation at startup. Introduce an Abstract Factory only if each backend must supply several mutually compatible collaborators. Do not assume unrelated provider capabilities can satisfy one contract; make unsupported capabilities explicit.

### Approval lifecycle

An enum and transition function suffice for a short workflow. State becomes useful when approve, revise, and withdraw each have substantial state-specific rules spread across conditionals. Whichever representation is chosen, the domain owner validates transitions. State classes do not solve concurrent updates or persisted transition atomicity; those require separate implementation decisions.

### Retry and caching wrappers

Decorator can compose client behaviors, but the order is part of semantics. Establish which failures are retryable, whether effects are idempotent, and what cache freshness means before composing wrappers. A Proxy may describe the same wrapper's access role. Choose clear contracts over insisting on one pattern label.

### Expanding syntax analysis

For stable syntax node types and frequently added analyses, Visitor can isolate operations. If syntax variants change often, compare exhaustive pattern matching or operations on the nodes. A separate parser still turns input into the tree. Interpreter is suitable only if evaluating that small grammar is itself the problem.

## From design to implementation

For a nontrivial choice, a compact explanation can use:

> Pressure: [observed problem]. Choose [approach] because [specific fit]. Prefer it over [simpler option] only because [limitation]. Cost: [indirection, state, lifecycle, or extension tradeoff]. Reconsider when [concrete change]. Validate [observable contract].

Then implement a complete use case through the collaboration, including dependency assembly and failure paths. Choose a function for a stateless one-operation policy when the language supports it well; introduce an object when it must own configuration, state, lifecycle, or several cohesive operations. Do not add empty base classes, factories, or dependency containers solely to make a diagram look like a textbook pattern.
