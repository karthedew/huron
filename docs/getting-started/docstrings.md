# Docstrings

Every module, class, method and function in `src/`, `migrations/` and `scripts/` carries a
docstring, and every docstring is checked against the code it describes. Two tools enforce this,
and both run in `make lint`:

```bash
uv run ruff check src   # D rules: a docstring exists and is well formed
uv run pydoclint src    # it names every parameter, return, yield and exception
```

`ruff` proves presence and shape (the `D` rule set under `convention = "google"` in
`pyproject.toml`). `pydoclint` proves completeness: a function with parameters and no `Args`
section fails, a `return` with no `Returns` fails, a `raise` with no matching `Raises` entry fails.
Neither can be satisfied with a suppression — see [conventions](conventions.md#formatting-and-lint).

## The shape

Google style. A one-line summary ending in a period, a blank line, optional prose, then the
sections that apply, in this order: `Args`, `Returns` or `Yields`, `Raises`.

```python
def grant_role(
    self,
    *,
    principal: str,
    role_code: str,
    scope_type: ScopeType,
    scope_id: UUID | None,
) -> Binding:
    """Create one role binding, refusing duplicates.

    A binding is unique per principal, role and scope; granting the same
    triple twice is a caller error rather than an idempotent no-op, because
    the second grant almost always means two administrators acted on stale
    views of the same list.

    Args:
        principal: The ``kind:subject`` string the binding is for.
        role_code: A role from :mod:`huron.pkg.rbac.roles`.
        scope_type: Where the role applies.
        scope_id: The organization, project or dataset id, or None for
            SYSTEM scope.

    Returns:
        The stored binding, with its generated id and timestamp.

    Raises:
        BindingExists: If an identical binding is already stored.
        UnknownRole: If ``role_code`` is not a defined role.
    """
```

The rules that follow from the tools, and the ones that are ours:

- **Summary line.** One line, ends with a period, fits in the 100-column limit. Imperative for
  functions and methods ("Return the…", "Refuse…"), a noun phrase for classes and modules ("The
  session store's Postgres adapter."). Ruff enforces the blank line after it (D205) and the
  closing quotes on their own line for multi-line docstrings (D209).
- **Types stay in the signature.** Never repeat a parameter's type in `Args`; `pydoclint` runs
  with `arg-type-hints-in-docstring = false` and rejects them.
- **`Args` names every parameter**, in signature order, including keyword-only ones and
  `*args`/`**kwargs` (written with their stars). `self` and `cls` are never listed. A parameter
  whose description needs more than one line indents the continuation by four spaces.
- **`Returns` whenever the function returns a value.** A function annotated `-> None` with no
  `return` needs no section. A generator or context manager documents `Yields` instead.
- **`Raises` lists exactly the exceptions raised in the function body** — not the ones a callee
  might propagate, which `pydoclint` treats as extraneous. Name the class as the code names it
  (`SlugExists`, `errors.NotFound`, `ValueError`). A bare `raise` inside `except X` counts as
  raising `X`; `raise Y from exc` counts as `Y`.
- **`__init__` documents its own parameters.** The class docstring describes what the object is
  and the invariants it keeps, never the constructor's arguments (`allow-init-docstring = true`;
  pydoclint's DOC304 rejects an `Args` section on a class).
- **Fields are documented where they are declared.** Pydantic models use `Field(description=…)`,
  which is also what the OpenAPI document publishes; dataclass and settings fields use a `#:`
  comment above the field. An `Attributes` section is welcome on a class whose fields carry
  meaning the declarations cannot, but it is not required (`check-class-attributes = false`).
- **Private helpers.** Ruff does not require a docstring on a `_name`. Write one whenever the
  name alone does not say what the helper guarantees; once written, it is held to the same
  completeness rules as a public one.
- **Route functions are also API documentation.** FastAPI publishes a path operation's docstring
  as its OpenAPI `description`, truncated at a form feed. So a route's docstring puts the
  caller-facing prose first, then a line holding only `\f`, then the sections:

  ```python
  @router.post("", status_code=201)
  def create_organization(
      body: CreateOrganization, idempotency_key: IdempotencyHeader, repository: Repository
  ) -> OrganizationView:
      """Create an organization.

      Requires ``organization.create`` at SYSTEM scope. Replaying the same
      ``Idempotency-Key`` returns the original organization instead of a 409.
      \f
      Args:
          body: The slug, title and description to store.
          idempotency_key: The caller's ``Idempotency-Key`` header, if sent.
          repository: The wired hierarchy repository.

      Returns:
          The organization as the API renders it.
      """
  ```

  Everything after `\f` describes dependency-injected parameters that no API client sees; ruff's
  D301 (which would ask for a raw string) is waived for `routes/**/endpoints/*.py` for exactly
  this reason, and nowhere else.

## What a docstring is for

A docstring states what the code guarantees, not how it is written. The reader is the next
engineer at the call site: what does this need from me, what do I get back, what can go wrong,
and what will still be true afterwards. Rationale that would otherwise be lost — why a limit is
what it is, which failure mode a check exists to prevent, which invariant a caller may rely on —
belongs in the prose paragraph. Like comments (see [conventions](conventions.md#comments)),
docstrings never reference an implementation plan, a phase, a task number or a review; they
describe the code as it is.

## Tests

Tests document what they prove, not how they are called. Every test module, class, test function
and fixture carries a summary line — the behavior under test, stated as a fact:
`"""A duplicate slug is refused with 409 and leaves the first organization untouched."""` — and
no `Args`/`Returns` sections. `pydoclint` does not run on `tests/`, and ruff waives D105 and
D107 there so a test double's dunder methods and constructor need none.

## Migrations and scripts

A migration module's docstring says *why* the schema changes (the design decision, the invariant
being added), as it always has; its `upgrade()` and `downgrade()` carry a one-line summary.
Operational scripts under `scripts/` follow the full standard — they are code someone runs when
something has gone wrong, which is exactly when a complete `Raises` section earns its keep.
