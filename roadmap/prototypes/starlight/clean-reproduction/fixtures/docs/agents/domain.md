# Domain evidence and decisions

Read root `CONTEXT.md` for vocabulary and relevant `design/` records for durable
architecture before discovery, planning or domain work. `AGENTS.md` distinguishes
current implementation from agreed targets; its scoped migration constraints apply.
The configured import graph remains enforced until its explicit cutover.

## Verify claims

Use code, tests and safe executable probes to classify claims as **implemented**,
**drift**, **planned** or **unverified**. Two agreeing documents are not proof.
Check writers, consumers and empty scaffolding. A feature deliberately marked
planned is not drift merely because its implementation is absent. Legacy plans
and local `roadmap/archive/` material are migration inputs, not shipped-feature evidence.

## Record the right kind of knowledge

- Durable decisions and rationale belong in tracked `design/` records; reconcile
  affected pages within the assigned scope. Read relevant historical `docs/adr/`
  records when present and surface conflicts rather than silently overriding them.
- `CONTEXT.md` is the glossary. Use its terms consistently and propose concrete
  additions when a real vocabulary gap is discovered.
- Local delivery roadmaps, experiments, evidence and execution ledgers belong under
  ignored `/roadmap/`; self-contained phase plans belong in `/roadmap/plans/`.
  Reusable planning and assignment templates live in `.agents/templates/`.

Follow `/design-plan` → `/prototype` → `/implementation-plan` → `/implement-markdown`.
Read the local command/skill and the orchestration/verification contracts before
using that flow. Each executable phase includes context, prototype evidence,
concrete code examples, exact scope/interfaces/deletions/skills, acceptance and
complete applicable gates. Unresolved blockers prevent execution.

An assignment to tooling does not authorize edits to the glossary, architecture,
product or legacy plans. Capture out-of-scope conflicts with evidence for the
owning slice; preserve user changes and data. Relocate legacy plans only when
explicitly assigned. Issues, branches, commits and production promotion require
an explicit user request, not an implicit lifecycle step.
