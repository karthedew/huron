---
name: grill-with-docs
description: TODO — describe when this skill should trigger and what it does (e.g. "Use when producing or updating design/planning documents, to cross-check proposed design decisions against existing project documentation and flag drift before it's written down."). Codex and Codex subagents match skills against this description, so it needs to be specific enough to trigger reliably from /design-plan.
---

# grill-with-docs

TODO: this is a scaffold, not real skill content. `/design-plan` (`.Codex/commands/design-plan.md`) now references this skill by name in its discovery and roadmap-reconciliation phases, but the actual methodology — how it should "grill" existing documentation, what counts as drift, how findings should be reported — hasn't been specified yet. Replace this file with the real skill before running `/design-plan` in a way that depends on it.

Suggested shape, based on how it's invoked in `/design-plan`:

## When this skill applies

- Being asked to produce or update DESIGN.md / IMPLEMENTATION_PLAN.md for a codebase that already has documentation (README, docs/, design/roadmap.html, inline docstrings, ADRs, etc.)
- Reconciling design/roadmap.html against what has actually shipped

## What it should do

1. Locate the existing documentation relevant to the target path.
2. Cross-reference documented intent/behavior against what the code actually does.
3. Surface concrete mismatches (not vague "docs may be stale" — specific claims vs. specific code).
4. Distinguish "documentation is wrong" from "documentation describes a still-valid future intention the code hasn't reached yet."

## What it should return

A structured list of drift findings that `/design-plan` can drop into DESIGN.md's "Roadmap Drift" section and use when rewriting design/roadmap.html.
