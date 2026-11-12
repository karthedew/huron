# Domain guidance for agents

## Sources of authority

Read [AGENTS.md](../../AGENTS.md) for repository rules and package boundaries.
Read the relevant sections of [IMPLEMENTATION_PLAN.md](../../IMPLEMENTATION_PLAN.md) before changing behavior.
Use [CONTEXT.md](../../CONTEXT.md) for domain terms.
Record disagreements between these sources and the code before proposing a change.

The [concept guides](../concepts/how-huron-works.md) explain the user workflow.
The [web design](../web-design.md) governs the web client.
The [OpenAPI document](../openapi.json) defines the API contract.

## Design evidence

Trace each operation through its caller, domain owner, ports, adapters, and tests.
Check both producers and consumers of stored values.
Distinguish implemented behavior from planned behavior and unverified assumptions.
A completed task marker is a claim to check, not test evidence.

For state changes, identify authorization, transaction boundaries, concurrency, retries, and crash recovery.
Use real filesystem and database adapters when a decision depends on their behavior.
Record what each experiment proves and what remains unverified.

Keep decisions with the documentation that governs the affected area.
Do not relocate an existing plan without an explicit assignment.
Use the [planning workflow](../../.agents/workflows/orchestration.md) for ownership and dispatch.
Use the [verification contract](../../.agents/workflows/verification.md) for evidence and gates.
Resolve gate commands against the current worktree before execution.
