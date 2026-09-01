---
name: grill-with-docs
description: Cross-examine a project's own documentation against what its code actually does, and report the divergences as specific claim-versus-specific-evidence findings. Use this skill whenever producing or updating a design or planning document for a codebase that already has documentation — design records, roadmaps, ADRs, READMEs, generated schema maps — and whenever reconciling a living roadmap against what has really shipped. Load it BEFORE mapping or designing anything, so the design work starts from what the project believes about itself and knows which of those beliefs are false. Also use it whenever asked to check whether documentation is current, whether a phase marked done actually shipped, or why the docs and the code disagree.
---

# Grill with docs

Documentation is the project's memory of its own intentions. Code is what it actually does. The
gap between them is where bad designs come from: a design built on a stale claim inherits the
staleness, and nobody notices until the migration fails or the invariant turns out never to have
been enforced.

Grilling comes **first**, before the codebase map and before any design work. Read what the
project believes about itself, find out which beliefs are false, and hand that forward. A map
drawn without it records what the code does but not where the code has quietly diverged from what
everyone thinks it does — and that divergence is usually the most valuable thing on the page.

## What a grill is not

It is not proofreading, and it is not a documentation-quality review. You are not looking for
unclear prose, missing sections, or typos. You are looking for **claims that are not true**.

It is also not a fix-it pass. Recording that a claim is false is the deliverable. Editing the
document is a separate, later act by whoever owns it — and doing it here destroys the record the
design phase needs.

## Method

### 1. Establish the authority order before reading anything closely

Documents in a repo are not peers, and treating them as peers is the fastest way to produce
worthless findings. Before extracting a single claim, determine:

- **Which document is authoritative** — the one that decides, whose word overrides the others.
- **Which are derived** — they restate the authority and can be stale without anything being wrong
  in the design itself.
- **Which are retired** — superseded trees that still sit in the repo. A "finding" against a
  retired document is noise.
- **Which document carries status as well as intent.** A roadmap that tags phases `done` / `todo`
  is making falsifiable claims about the present, not just plans about the future. These are the
  highest-yield claims in any repo.

Repository conventions usually state this explicitly — check `CLAUDE.md`, `AGENTS.md`, `README`,
or the documents' own headers. If the authority order is genuinely unclear, that ambiguity is
itself a finding worth reporting.

### 2. Extract claims, not impressions

Walk the relevant documents and build an inventory of **checkable assertions** — sentences that
say the system has, does, enforces, or contains something specific.

A claim is checkable when you can name the artifact that would prove or disprove it: a file, a
symbol, a table, a constraint, a command's output. "The ingest path is robust" is not a claim.
"Every snapshot states one of three origins" is a claim — there is a CHECK constraint that either
exists or does not.

Scope the inventory to the target path. Grilling the whole repo when the design touches one
subsystem produces a long list nobody will act on.

### 3. Check each claim against executable truth

Evidence has a strict rank, and using a weaker form when a stronger one is available is how
grills go wrong:

1. **Running it** — apply the migrations and query the catalog; execute the function; run the
   command. Strongest, and often much cheaper than it sounds.
2. **Reading the code that would run** — the DDL, the function body, the actual query text.
3. **Reading a generated or derived artifact** — a schema dump, an OpenAPI file, a lockfile.
4. **Reading another document.**

Level 4 is not verification. If a design document and a roadmap agree with each other, you have
learned that two documents agree — nothing about the system. When a claim can only be checked at
level 4, say so explicitly rather than reporting it as confirmed.

Prefer a negative check where one exists. "The constraint is present" is weaker than "the write it
is supposed to refuse was refused" — the second catches constraints that exist but do not work.
A `CHECK` passes on NULL; a `BEFORE UPDATE` trigger never fires on INSERT. A claim can be true of
the DDL text and false of the database.

### 4. Classify every finding — this is where the value is

Each checked claim lands in exactly one bucket, and the bucket determines who acts and how:

- **Current** — the claim holds. Worth recording in bulk (one line) so the next reader knows it
  was checked and does not re-check it.
- **Documentation is wrong** — the system is right, the document misdescribes it. Someone edits
  the document.
- **Code has diverged** — the document states the intended behavior, the code does something else,
  and the document is the one that should win. **This is a bug report, not a documentation fix**,
  and it must not be quietly resolved by editing the doc to match the code.
- **Not yet built** — the document describes a future intention and marks it as such. **This is
  not drift.** A milestone tagged `todo` whose code does not exist is the system working as
  designed. Reporting it as drift is the single most common way to make a grill useless, because
  it buries the real findings in noise.
- **Claimed done, not done** — a document asserts something has shipped and it has not. This is
  the highest-value class in the whole method: it is invisible from the code (nothing looks
  broken) and invisible from the document (it reads as settled). Look for it deliberately by
  taking every `done`, `shipped`, or past-tense deliverable and checking it item by item.

The distinction between "not yet built" and "claimed done, not done" is the discipline the whole
skill turns on. Both look like "documented thing does not exist in the code." Only the tag on the
document tells them apart, and only one of them is a finding.

### 5. Report as claim → evidence → classification

Every finding names the document and location, quotes the claim, cites the specific evidence with
a file and line or a command and its output, and states the class.

**Never write "the docs may be stale", "this section appears outdated", or "consider reviewing".**
A finding that does not say precisely which sentence is false, and precisely what proves it,
cannot be acted on and will not be.

Where you looked and found no divergence, say so by name. "No drift in the RBAC document, the raw
layer document, or the architecture document" tells the next reader exactly how much of the
surface is already checked, and is far more useful than silence.

## Output shape

Return a structured list ready to drop into a design document's drift section:

```markdown
### Drift N — <short name>

**Claim.** <document> <section>: "<quoted assertion>"
**Reality.** <file:line, or the command and its result>
**Class.** Documentation is wrong | Code has diverged | Claimed done, not done
**Consequence.** <one line: what a reader who believed this would get wrong>
```

Then a short "checked, no drift found" list naming the documents and areas that came back clean.

The consequence line earns its place. A finding whose consequence is "nothing, this is cosmetic"
should be reported as such and ranked last; a finding whose consequence is "a design built on this
would enforce an invariant that does not exist" belongs at the top.

## Judgment calls worth getting right

**Count things rather than characterizing them.** "The generated map is incomplete" is weak.
"The map contains zero `CREATE INDEX` statements against the six the migrations create" is a
finding that settles an argument.

**When a document tells the reader how to regenerate or reproduce something, try it.** Instructions
that cannot produce the artifact they claim to produce are a common and entirely invisible form of
drift — the file looks maintained and the command has never been run.

**Distinguish the document being wrong from the document being ambiguous.** If two readings are
possible and the code implements one, that is a clarity finding, not a correctness finding; label
it that way rather than inflating it.

**Do not grill the future.** Speculative sections, rejected alternatives, and explicitly deferred
work are not claims about the present. Skip them.
