# Claude repository instructions

Read and follow [AGENTS.md](AGENTS.md) first. It is the shared source for package
boundaries, OOP conventions, skills by area, scientific workflows, RBAC/lineage,
verification, and scoped frontend instructions. Do not maintain alternate versions
of those rules here.

## Architecture and skills

The implemented layout is `src/huron/{pkg,core,applications}`, with `schema/` as the
shared document-contract floor. Follow the ownership and dependency rules in AGENTS.md.

Read skills from `.claude/skills/<name>/SKILL.md`:

- `oop-design` when writing, designing, refactoring or reviewing `pkg/` and `core/`
  code. Use the project-local copy; the previous encapsulation skill is retired.
- `fastapi` exclusively for API-service code, in
  `src/huron/applications/api/`. Do not apply
  `oop-design` to this service. For changes spanning layers, apply each skill only
  to its corresponding area; shared workflow and verification rules still apply.
- `postgresql-table-design` for database schema, migrations and persistence design;
  `src/huron/schema/` contains document contracts and is not automatically SQL work.
- `grill-with-docs` to sharpen a plan by interview: it calls `grilling` and
  `domain-modeling`, updating `CONTEXT.md` and ADRs as terms and decisions settle.
  Checking roadmap claims against executable evidence is `/design-plan`'s own
  Phase 0 method, not a separate skill.
- `codebase-design` for structural planning/review only to the extent its actual
  contents supply a methodology; inspect it rather than assuming it is complete.
- Frontend skills and gates are defined in AGENTS.md’s **Frontend: `web/`** section.
  Load both `svelte-code-writer` and `svelte-core-bestpractices` for Svelte work, and
  `tailwind-design-system` for Tailwind/design-system work. `web/AGENTS.md` is a
  discovery pointer to those shared rules, not a separate lifecycle.

## Claude command workflow

The general lifecycle is understand → resolve/design → implement → verify/review,
with scope and gates specified in AGENTS.md. Continue the requested task and settled
session decisions. Do not automatically choose a roadmap phase or interview the user
again merely because a session is new.

For substantial planned changes, the committed commands in `.claude/commands/`
provide the following workflow. Read a command before invoking it; when the user
explicitly invokes one, follow its additional artifact and verification requirements.

1. **Resolve requirements and check documentation.** Use `grill-with-docs` to
   interview the user and settle vocabulary and decisions; it is a skill, not a
   committed slash-command file. Publish the settled spec with `to-spec`. Claims
   about what has shipped are checked in `/design-plan` Phase 0; keep those findings
   separate from later corrections. Ask focused questions only for unresolved
   decisions that affect design.
2. **`/design-plan`.** Defined in `.claude/commands/design-plan.md`. Planning only;
   produces a design and implementation plan, including current state, target design,
   roadmap drift, alternatives and mechanically verifiable milestones. Default
   artifacts are `DESIGN.md` and `IMPLEMENTATION_PLAN.md`; use task-specific locations
   when existing work would otherwise be overwritten.
3. **`/implement-markdown`.** Defined in `.claude/commands/implement-markdown.md`.
   Executes a plan through serial implementation and verification. Its explicit
   workflow requires a baseline, full gate for each attempt, and at most three
   verification attempts per task before architectural escalation. Read its current
   model/tool requirements rather than copying defaults into this file. Include
   AGENTS.md's `make lint` checks and relevant non-unit suites; default pytest alone
   does not exercise them. Do not revert unrelated user work during escalation.
4. **`/architectural-review`.** Defined in `.claude/commands/architectural-review.md`.
   Structural review only; produces findings and a synthesis, optionally using an
   escalation report to inform a revised design plan.

When a command calls for subagents, keep its implementation/verification sequence
serial. Do not assume other agents or environments can invoke Claude slash commands;
AGENTS.md supplies the tool-independent workflow.

Documentation-only and small localized tasks do not require this full command loop.
Apply proportionate verification from AGENTS.md. Report checks actually performed
and any unresolved gaps; never present a planned migration as completed code.

## Agent skills

### Issue tracker

Issues and specs live in GitHub Issues for `karthedew/huron`, via the `gh` CLI.
See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical triage roles use their default label strings.
See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` and `docs/adr/` at the repo root. `design/` remains
the architecture record. See `docs/agents/domain.md`.

### Implementation workflow

Plans produced by `/design-plan` are executed by `/implement-markdown`, not by
the `implement` or `implement-spec` skills. Implementation and verification
subagents load skills by code area from AGENTS.md's "Skills by area" table.
`to-spec` publishes the spec issue that `code-review` later checks against. When
tickets are wanted, `to-tickets` (not the older `to-issues`) breaks the spec into
tracer-bullet tickets; keep one ticket per plan task.
