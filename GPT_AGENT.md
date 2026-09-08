# GPT Agent Instructions

Huron is a datalake for scientific and engineering projects. `design/` is the authoritative architecture record; `design/roadmap.html` is the living, cross-phase roadmap.

## Repository Structure & Definitions

1. `./src/huron/pkg` - Domain objects and technical capabilities

The `pkg` directory is the focused building blocks where each package implements a specific domain set of rules or technical capabilities. They expose cohesive objects with clear interfaces.

A package knows how to perform its capability, without coordinating an entire Huron workflow.

For example,`RawStore` knows how to seal a collection of files. It does not decide whether Alice may ingest those files into a particular project.

Rules:

- Keep domain state and its rules together in meaningful objects.
- Hide implementation details behind small public interfaces.
- Keep domain packages independent of FastAPI, Ray, and database drivers.
- Infrastructure packages may use the libraries required for their capability.
- Preserve sibling-package independence where practical; cross-capability coordination belongs in core/.
- Pure utilities can remain functions—classes should have a coherent responsibility.

2. `./src/huron/core` - complete Huron operations

These can be methods on cohesive services such as `DatasetService`, `RawIngestionService`, and `TransformationService`

For example, committing Raw involves:

    Authenticate upstream → core receives the actor
     → resolve dataset ancestry
     → authorize the operation
     → verify upload completeness
     → finalize storage
     → record revision and provenance
     → return a receipt

Core owns that sequence, including idempotency, failure handling, and recovery requirements.
Rules:

- Every public operation enforces its required authorization.
- Accept ordinary Python inputs: actors, IDs, commands, and value objects.
- Return domain results and receipts; raise transport-independent errors.
- Depend on injected interfaces for storage, compute, clocks, and other external capabilities.
- Own transaction boundaries and coordination across storage systems.
- Record lineage as part of publication.
- Never import FastAPI request objects, HTTP response types, deployment settings, or concrete infrastructure adapters.
- Organize by workflow responsibility; avoid a single enormous HuronCore class.

The interface a workflow needs belongs with its consumer. If only core needs a persistence protocol, define it in core. Concrete adapters can satisfy it structurally without importing core.

3. `./src/huron/applications/` - expose and run core

Applications are the processes and commands through which Huron operates.
