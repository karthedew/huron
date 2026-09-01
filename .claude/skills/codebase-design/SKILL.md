---
name: codebase-design
description: Map a codebase's real structure and produce clean-sweep design recommendations with concrete contracts, deletions, and flagged open questions. Use this skill whenever mapping, reviewing, or redesigning a codebase's structure — identifying packages, modules, protocols, domain boundaries, duplicated abstractions and dead paths — and whenever writing a target design that another agent or engineer will implement from. Load it for discovery passes over an unfamiliar target path, for design passes that propose module layouts and public interfaces, and for review passes hunting compatibility shims and unnecessary indirection. It is the skill behind /design-plan's design loop and /architectural-review; use it any time the output is a design document rather than working code.
---

# Codebase design

The output of design work is a document another agent implements from without asking questions.
That standard drives everything below: prose about what the code should look like is not a design,
because it cannot be implemented without re-deriving the decisions. Concrete signatures, concrete
DDL, named symbols to delete — those can.

## Order of work

Design comes **after** the documentation grill and before the implementation plan.

1. `grill-with-docs` establishes what the project believes about itself and which beliefs are
   false.
2. This skill maps what is actually there and designs what should be there.
3. The plan sequences the change into verifiable milestones.

Read the grill's findings first and treat them as established. Re-deriving them wastes budget, and
worse, a design that quietly contradicts a confirmed drift finding will be built on the same false
claim the grill just disproved.

## Reading a codebase inside a budget

You cannot read everything, and pretending otherwise produces a shallow map of a wide surface. Be
deliberate:

**Read fully** — the files that define contracts. Migrations and DDL, protocol and interface
definitions, type and model modules, the module that owns the domain you are designing, and the
tests that pin the behavior you might change. Reading a contract partially is worse than not
reading it, because you will design against a signature you half-remember.

**Skim** — call sites and consumers. You need to know who depends on a thing and roughly how, not
every line of how. Grep for the symbol, read the surrounding few lines, move on.

**Skip** — generated files, lockfiles, vendored dependencies, retired trees, and anything the
grill identified as superseded. Note that you skipped them, so the next reader knows it was a
choice.

**Check emptiness explicitly.** Before designing around a module, confirm something actually uses
it. A table with no writer, a protocol with no implementation, and a package that does not exist
are all common and all invisible unless you look. Whether the code you are designing for exists
yet changes the design: a constraint written for a writer that has not been built is a contract
for a future author, and must be stated as one.

## Map before judging

The discovery output is factual and structural. It says what is there — packages, modules,
protocols, data flows, domain boundaries, the conventions the codebase already follows — and what
needs design. It does not contain the design.

Keeping these separate matters because a map contaminated with opinions gets argued with instead
of used, and because the map is what lets you size the design work honestly.

**Record the conventions you find**, not just the structure. How do migrations author their DDL?
Where does the seed data's source of truth live? What is the house pattern for a guard — a CHECK,
a trigger, application code? A design that fights the existing conventions without saying why will
be rejected in review, and a design that follows them needs no defense.

### Diagrams

Use Mermaid. A diagram earns its place when it shows a **mechanism** that prose states poorly —
the order of operations across a boundary, a lifecycle with branches, the shape of a dependency
graph that is not a tree.

A diagram that lists boxes already named in an adjacent table is decoration. Prefer one diagram
that shows where a constraint is checked relative to a durability point over five that restate the
module list.

## Sizing design tasks

Split the design surface into tasks that each fit one agent's working budget. Sizing is a judgment
about coherence, not line count:

- Group findings that are **one decision**. Every foreign key in a schema asked "does it have an
  index, and is its referential action stated" is a single pass over a single object, even across
  a dozen tables.
- Split findings that share a surface but are **different questions**. "What are this column's
  legal values" and "should this column have a fixed value set at all" look like one task and are
  not — the second can conclude that the first was the wrong question.
- When two tasks touch the same object, say so in both, and name which one owns the decision.
  Sibling tasks that each add an index for the same access path produce a duplicate; sibling tasks
  that each assume the other handled it produce a gap.
- Say per task whether it can be settled from the artifacts alone or needs application code and
  design documents read. That tells the next agent where its budget will go.

## What a design recommendation must contain

**Target design** — concrete signatures, contracts, or DDL. Not a description of them. If the
output is a schema change, write the actual constraint text; if it is a module, write the actual
interface.

**Explicit contracts** — for every proposed interface or constraint: the invariant it enforces,
its error behavior, its lifecycle assumptions, and what it assumes about callers or writers. When
the caller does not exist yet, this section is the specification that future author must honor.

**Deletions, by file and symbol** — what this makes removable. Prefer deletion over accommodation;
a design that only adds is usually a design that has not finished thinking. Say "none" explicitly
rather than omitting the section, so the reader knows it was considered.

**Rejected alternatives** — two or three, one line each, with the reason. This is what stops the
decision being relitigated in six months, and it is the section most often skipped. The reason
matters more than the alternative: "a trigger instead of a composite FK — imperative, and the
declarative form already has a house precedent" tells the next reader something.

**Open questions** — anything needing a human decision, clearly flagged. Recommend an option with
reasoning; do not silently pick, and do not refuse to recommend. Both failures are common: silently
picking hides a decision the owner would have made differently, and refusing to recommend hands
back the work unfinished.

## Proof over inspection

The strongest thing a design pass can do is stop guessing about behavior. If a claim about how the
system behaves can be tested cheaply, test it — apply the migrations to a scratch database and try
the write that should fail; call the function with the input you think it mishandles; run the
query and read the plan.

This routinely overturns confident readings. Constraints that exist in the DDL and do not hold at
runtime, indexes that exist and cannot serve the query they were written for, guards that never
fire on the path that matters — none of these are visible by reading, and all of them are one
command away.

Where you did prove something, say so and give the receipt. Where you could not, say that too:
a design section that leans on unverified behavior is not a defect, but a reader who cannot tell
which sections were proven will trust all of them equally.

## Clean-sweep bias

Unless the task explicitly requires preserving compatibility:

Prefer deletion over accommodation. Prefer explicit contracts over implicit behavior. Prefer clear
domain boundaries over cleverness. Prefer well-named functions and types over comments explaining
confusing code.

Do not propose TODOs, temporary names, commented-out code, speculative abstractions, partial
migrations, or compatibility shims. Do not propose comments, docstrings, test names, or
user-facing strings that reference a plan, its phases, or checklist mechanics — comments explain
enduring intent, and orchestration history is not enduring intent.

A speculative abstraction is worth naming specifically because it is easy to defend and expensive
to keep: structure built for a load that has not arrived, with no pruning benefit, no measured
volume, and an operational failure mode of its own. When you find one, price both keeping it and
removing it rather than assuming the existing choice was deliberate.

## Failure modes to avoid

**Designing past the budget.** If the scope does not fit, stop and record a recommended split
rather than producing a thin pass over all of it.

**Inheriting a number without checking it.** Counts in an upstream document — findings, columns,
tables — are worth re-deriving by enumeration. They are frequently off, and a design that repeats
a wrong count propagates it into the plan.

**Fixing what was already cleared.** When earlier work explicitly recorded that something is
correct as it stands, and why, do not re-flag it. A design that reopens settled questions costs
the reader more than it saves.

**Answering a different question than the one asked.** A task scoped to "should this be
constrained" is not discharged by listing what the constraint would say.
