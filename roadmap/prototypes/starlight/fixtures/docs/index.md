# Huron developer documentation

This site covers **working on Huron**: setting up an environment, running the stack, the checks
CI enforces, and how the repository is laid out.

Architecture lives in **`design/`**. Start with **`design/raw-first.md`** for the current
agreed target and unresolved decisions, and **`CONTEXT.md`** for domain vocabulary.
`design/index.html` provides navigation and explicitly labelled historical proposals;
those proposals do not override the Raw-first target or prove it implemented. The design
record remains in the repository rather than duplicated in this developer site.

!!! info "Where to look for what"

    | Question | Where |
    |---|---|
    | What are Collections, datasets and immutable Raw releases? | `CONTEXT.md`; `design/raw-first.md` |
    | How are the four storage layers laid out? | `design/layer-raw.html` and its siblings |
    | Who owns identity, directory membership and Huron access? | `design/raw-first.md`; `design/auth.html` |
    | What is the current target and local planning convention? | `design/raw-first.md`; ignored `roadmap/plans/` for execution plans |
    | Where are completed plans and old verification reports? | [Implementation history](history.md) |
    | How do I run the tests? | [Testing](getting-started/testing.md) |
    | Why did my PR fail CI? | [Conventions](getting-started/conventions.md) |

Keeping those two sets apart is deliberate. A second prose description of the architecture would
have to agree with `design/` forever, and the last one silently drifted until it described a
different product. These pages describe the *repository*; `design/` describes the *system*.

## Start here

- **[Local development](getting-started/local-development.md)** — environment, services, running the API
- **[Repository layout](getting-started/repository-layout.md)** — the three surfaces and what goes where
- **[Conventions](getting-started/conventions.md)** — the checks that gate every change
- **[Testing](getting-started/testing.md)** — the four suites and when each runs
