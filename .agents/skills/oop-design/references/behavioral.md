# Behavioral decisions

Contents: Chain of Responsibility · Command · Interpreter · Iterator · Mediator · Memento · Observer · State · Strategy · Template Method · Visitor.

## Chain of Responsibility

**Mechanism:** Pass a request along handlers that may act, forward, or stop propagation. [Pattern reference](https://refactoring.guru/design-patterns/chain-of-responsibility).

**Use when:** Handler selection or order varies and the sender should not select a concrete receiver.

**Avoid when:** A fixed sequence of required steps is clearer as a function, or arbitrary short-circuiting could bypass a required operation.

**Alternatives:** Explicit orchestration for mandatory steps; a transformation pipeline when every stage produces the next input; a dispatch map for direct key-based selection.

**Implementation checks:** State whether the first matching handler wins or several handlers run. Specify ordering, unhandled requests, failure propagation, and invocation of the next handler. Mandatory checks must remain unavoidable. Replacing every conditional with a chain can obscure rather than simplify control flow.

## Command

**Mechanism:** Represent a requested action with its inputs as a value or object, separating invocation from execution. [Pattern reference](https://refactoring.guru/design-patterns/command).

**Use when:** Actions need scheduling, queuing, history, routing, or explicit undo behavior.

**Avoid when:** An immediate method call is sufficient and there is no need to manipulate the action independently.

**Alternatives:** A closure for local deferred execution; a typed message and handler for durable dispatch; Memento for restoring local state rather than reversing an operation.

**Implementation checks:** Define receiver lifetime and capture immutable inputs when delayed execution requires stable meaning. Persistence requires versioned serializable data, not a live object graph. Retries require idempotency or deduplication. Undo must be designed; external effects often require compensation and cannot simply be reversed.

## Interpreter

**Mechanism:** Represent grammar constructs as expressions that evaluate against a context. [Scenario source](https://javatechonline.com/when-to-use-which-design-pattern-23-gof-pattern/).

**Use when:** A small, intentionally constrained expression language needs composable semantics, such as local predicates over a record.

**Avoid when:** Grammar size, optimization, diagnostics, or compatibility requirements make a hand-built interpreter difficult to maintain.

**Alternatives:** Ordinary functions for programmer-defined rules; data tables for finite declarative conditions; a maintained parser/evaluator or parser generator for richer languages. Visitor can supply operations over a syntax tree but does not itself parse the input.

**Implementation checks:** Separate parsing from evaluation. Define precedence, types, errors, and resource limits. Do not implement user expressions with unrestricted host-language `eval`. Test malformed syntax and nesting limits as well as valid expressions.

## Iterator

**Mechanism:** Expose sequential traversal without revealing collection representation. [Pattern reference](https://refactoring.guru/design-patterns/iterator).

**Use when:** A custom collection or traversal needs the language's iteration contract, including lazy or alternative traversal orders.

**Avoid when:** The standard collection already provides the needed behavior; do not duplicate it with a custom interface hierarchy.

**Alternatives:** Native iterables and generators for ordinary traversal; a materialized list for small repeatable snapshots; an async iterator or explicit pagination API when I/O is involved.

**Implementation checks:** Define exhaustion, repeatability, mutation during traversal, and resource cleanup on early exit. Distinguish an iterable that creates fresh iterators from a one-shot iterator. A lazy database cursor can retain a connection long after construction.

## Mediator

**Mechanism:** Move interaction rules among colleagues into a coordinator. [Pattern reference](https://refactoring.guru/design-patterns/mediator).

**Use when:** Several components know too much about each other and one cohesive workflow can own their coordination.

**Avoid when:** Collaboration is already simple or a central object would absorb unrelated domain responsibilities.

**Alternatives:** Direct calls for a few stable relationships; Observer for independent reactions; an application service for explicit use-case sequencing.

**Implementation checks:** Keep colleagues focused on their own capabilities. Bound the mediator by workflow or responsibility. Specify reentrancy and failure order. A mediator should remove tangled dependencies, not become an omniscient object through which all communication passes.

## Memento

**Mechanism:** The state owner captures and restores an opaque snapshot while another object retains history. [Pattern reference](https://refactoring.guru/design-patterns/memento).

**Use when:** Local undo or checkpoints need encapsulated state restoration.

**Avoid when:** Full snapshots are too costly, or restoring memory would contradict already-committed external effects.

**Alternatives:** Immutable versions or structural sharing for economical history; Command inverses for reversible operations; database transactions for database rollback. Event sourcing is a separate architectural choice for durable event history, not a free replacement.

**Implementation checks:** Prevent mutable aliasing, constrain which originator can restore a snapshot, and bound history retention. Version persistent snapshots. Test restoration after multiple edits. A snapshot of an object does not roll back an email, payment, or another process.

## Observer

**Mechanism:** A publisher notifies registered dependents about changes without encoding their concrete reactions. [Pattern reference](https://refactoring.guru/design-patterns/observer).

**Use when:** Several independent consumers subscribe and unsubscribe to in-process notifications.

**Avoid when:** The caller needs one result, a strict workflow, or durable delivery guarantees.

**Alternatives:** Direct callbacks for one consumer; Mediator for coordinated reactions; a message broker when durable cross-process delivery is required; polling when its latency and simplicity fit.

**Implementation checks:** Define synchronous versus asynchronous delivery, ordering, listener failures, subscription disposal, and reentrant changes. Avoid retained-listener leaks. Async delivery also needs capacity and backpressure decisions. An in-memory observer list provides no durable or exactly-once delivery guarantee.

## State

**Mechanism:** Delegate state-dependent operations to a representation of the current lifecycle state. [Pattern reference](https://refactoring.guru/design-patterns/state).

**Use when:** Several operations vary by lifecycle state and transition rules are becoming scattered or contradictory.

**Avoid when:** A small stable enum and explicit transition function remain easy to understand.

**Alternatives:** Enum plus switch for a few states; a transition table for mostly data-driven transitions; a state-machine library for hierarchy, parallel states, or complex visualization; Strategy for a policy selected independently of lifecycle.

**Implementation checks:** Assign transition authority, define invalid operations and entry/exit effects, and preserve invariants across transitions. Prevent arbitrary public state replacement from bypassing rules. Stateful instances generally cannot be shared across contexts without care. Test allowed and rejected transitions, not only state-class methods.

## Strategy

**Mechanism:** Give a context an interchangeable implementation of an operation. [Pattern reference](https://refactoring.guru/design-patterns/strategy).

**Use when:** Multiple policies or algorithms satisfy one consumer contract and change independently of that consumer. Selection may occur during construction or at runtime.

**Avoid when:** One trivial behavior is unlikely to vary or alternatives cannot honestly satisfy a common contract.

**Alternatives:** A function or closure for one operation; a small conditional for stable finite choices; State for lifecycle-controlled behavior; Template Method for an intentionally inherited fixed workflow.

**Implementation checks:** Select the policy at an explicit boundary. Define shared input, output, error, and side-effect guarantees. Do not force semantically incompatible operations into one interface merely because their signatures match. Test the shared contract and each policy's distinct behavior.

## Template Method

**Mechanism:** A base class fixes a workflow and delegates selected steps to subclass hooks. [Pattern reference](https://refactoring.guru/design-patterns/template-method).

**Use when:** A stable algorithm skeleton is deliberately extended through inheritance, particularly in an existing framework.

**Avoid when:** Steps need independent runtime combinations, subclasses repeatedly override the skeleton, or hooks expose fragile base-class internals.

**Alternatives:** A function accepting callbacks for simple variation; composition with strategies for independently replaceable steps; an explicit pipeline when stage order is configurable.

**Implementation checks:** Distinguish required steps from optional hooks and document their contracts. Protect the skeleton where the language permits. Avoid calling overridable hooks during construction before subclass state is ready. Test that variants preserve mandatory step order and cleanup.

## Visitor

**Mechanism:** Dispatch an external operation according to concrete element type, commonly through element `accept` and visitor `visit` methods. [Pattern reference](https://refactoring.guru/design-patterns/visitor).

**Use when:** Element types are relatively stable while new operations over them are frequent.

**Avoid when:** New element types appear often, operations naturally belong on the elements, or visitation would expose too much private state. Adding an element type typically affects all visitors.

**Alternatives:** Ordinary polymorphic methods when types grow more often than operations; pattern matching over a closed sum type for exhaustive external operations; Iterator when only traversal is needed.

**Implementation checks:** Decide whether traversal belongs to the visitor or elsewhere. Ensure dispatch selects the concrete type as intended in the chosen language. Handle new variants explicitly. Keep traversal order and mutation rules clear; visitor interfaces do not guarantee those properties.
