---
description: Execute a markdown plan serially with Astra Medium and pollable subagents
agent: markdown-orchestrator
model: openai/gpt-6-astra
variant: medium
---

Read `.claude/commands/implement-markdown.md` and execute its complete workflow for
the implementation plan `$1`, with arguments `$ARGUMENTS`. Use its OpenCode runtime
branch; the Claude frontmatter and Claude model defaults do not apply here.
Use `implementation_start` and `implementation_status` for serial asynchronous
delegation and polling. Do not use a blocking Task call for this workflow.
