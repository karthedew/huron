"""Schema registry errors."""

from __future__ import annotations

from huron.pkg.errors import HuronError, register

__all__ = ["SchemaScope"]

SCHEMA_SCOPE = register("SCHEMA_SCOPE", 422, "Schema scope")


class SchemaScope(HuronError):
    """A schema entry is used outside the scope it belongs to."""

    error_code = SCHEMA_SCOPE
