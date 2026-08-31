"""Execute a multi-statement DDL block one statement at a time.

``migrations/env.py`` runs migrations over an async engine on the
``asyncpg`` driver (matching the app's own runtime driver). SQLAlchemy's
asyncpg dialect always issues a PostgreSQL ``PREPARE`` (extended query
protocol) for every statement, and Postgres's extended protocol refuses a
``Parse`` message containing more than one command
("cannot insert multiple commands into a prepared statement") - there is no
driver flag to opt out of this. A plain ``op.execute(one_big_ddl_block)``
therefore fails the moment a revision's DDL has more than one statement.

Every revision here still authors its DDL as a single readable
triple-quoted block (docstring-adjacent, easy to scan); ``execute_sql``
lets that stay as-is by splitting the block into individually-preparable
statements at run time.
"""

from __future__ import annotations

from alembic import op


def execute_sql(block: str) -> None:
    """Execute each ``;``-terminated statement in `block` separately."""
    for statement in _split(block):
        op.execute(statement)


def _split(block: str) -> list[str]:
    """Split `block` into statements at top-level ``;`` boundaries.

    Boundaries inside the following are ignored - the only quoting forms
    this project's migrations use:

    - ``--`` line comments, which run to end of line
    - single-quoted string literals, with ``''`` as the escaped-quote form
      (used by regex ``CHECK`` patterns like ``'^[a-z0-9]...$'``)
    - ``$$...$$`` or ``$tag$...$tag$`` dollar-quoted bodies (the plpgsql
      trigger functions, whose bodies contain their own semicolons)
    """
    statements: list[str] = []
    start = 0
    i = 0
    n = len(block)
    while i < n:
        ch = block[i]
        if block[i : i + 2] == "--":
            newline = block.find("\n", i)
            i = n if newline == -1 else newline + 1
            continue
        if ch == "'":
            i += 1
            while i < n:
                if block[i] == "'":
                    if block[i : i + 2] == "''":
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue
        if ch == "$":
            end_tag = block.find("$", i + 1)
            if end_tag == -1:
                i += 1
                continue
            tag = block[i : end_tag + 1]
            close = block.find(tag, end_tag + 1)
            i = n if close == -1 else close + len(tag)
            continue
        if ch == ";":
            statement = block[start:i].strip()
            if statement:
                statements.append(statement)
            start = i + 1
        i += 1
    tail = block[start:].strip()
    if tail:
        statements.append(tail)
    return statements
