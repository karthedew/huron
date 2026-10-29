# Claude repository instructions

Read and follow [AGENTS.md](AGENTS.md) first. It holds the layout, dependency rules, code
conventions, gate and testing standard. The implementation plan is
[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md); its sections 3–9 are binding design.

Load skills from `.claude/skills/<name>/SKILL.md` by area:

- `oop-design` for `src/huron/core/`.
- `fastapi` for `src/huron/applications/api/` only.
- `postgresql-table-design` for `src/huron/core/metastore/` and `migrations/`.

Plans are executed with `/implement-markdown` (`.claude/commands/implement-markdown.md`): one task at
a time, the full gate per task, an independent verification pass before a task is marked complete.
