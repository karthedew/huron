---
name: codebase-design
description: TODO — describe when this skill should trigger and what it does (e.g. "Use when mapping, reviewing, or redesigning a codebase's structure: identifying packages, domain boundaries, contracts, and duplicated abstractions, and producing diagrams and clean-sweep design recommendations."). Codex and Codex subagents match skills against this description, so it needs to be specific enough to trigger reliably from /design-plan and /architectural-review.
---

# codebase-design

TODO: this is a scaffold, not real skill content. All three lifecycle commands (`/design-plan`, `/architectural-review`, and the subagent assignments they issue) reference this skill by name, but the actual methodology — how to map a codebase, what a good structural diagram contains, how to judge domain boundaries and propose clean-sweep designs — hasn't been specified yet. Replace this file with the real skill before relying on it.

Suggested shape, based on how it's invoked by the commands:

## When this skill applies

- Discovery passes that map an unfamiliar target path: packages, modules, classes, protocols, services, data flows, domain boundaries
- Design passes that propose target module layouts, public interfaces, and explicit contracts (invariants, error behavior, lifecycle assumptions)
- Review passes that hunt duplicated abstractions, compatibility shims, dead paths, and unnecessary indirection to delete

## What it should do

1. Define how to inspect a codebase systematically within a fixed token budget (what to read fully vs. skim vs. skip).
2. Define the diagram standard: Mermaid (or UML-equivalent) diagrams of current structure and proposed data flows.
3. Define what a design recommendation must contain: concrete signatures or contracts, deletions by file/symbol, rejected alternatives with reasons, open questions flagged for a human.
4. Encode the clean-sweep bias: prefer deletion over accommodation, explicit contracts over implicit behavior, domain boundaries over cleverness.

## What it should return

Sections ready to append to DESIGN.md or architectural_review.md, in the formats those commands' assignment templates specify.
