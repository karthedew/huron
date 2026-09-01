# Huron developer documentation

This site covers **working on Huron**: setting up an environment, running the stack, the checks
CI enforces, and how the repository is laid out.

It does not describe the architecture. That lives in **`design/`** — fifteen cross-linked
documents in the repository root that are the complete and only authoritative record of what
Huron is and why. Open `design/index.html` in a browser; it is deliberately not part of this
site, so there is exactly one copy of it.

!!! info "Where to look for what"

    | Question | Where |
    |---|---|
    | What is a dataset? Why are releases tags? | `design/index.html` |
    | How are the four storage layers laid out? | `design/layer-raw.html` and its siblings |
    | Who can write Silver? | `design/rbac.html` |
    | What order is this being built in? | `design/roadmap.html`, `IMPLEMENTATION_PLAN.md` |
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
