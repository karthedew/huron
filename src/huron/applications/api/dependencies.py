"""Dependencies that hand the shared runtime and its lake to path operations."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Request

from huron.applications.api.disk import LakeDisk
from huron.applications.api.runtime import Runtime
from huron.core.lake.bootstrap import Lake
from huron.core.lake.organizations.declarations import Declarations

__all__ = [
    "DeclarationsDep",
    "DiskDep",
    "LakeDep",
    "RuntimeDep",
    "get_declarations",
    "get_disk",
    "get_lake",
    "get_runtime",
    "with_share_root",
]


def get_runtime(request: Request) -> Runtime:
    """The runtime built at startup."""
    runtime: Runtime = request.app.state.runtime
    return runtime


def get_lake(runtime: Annotated[Runtime, Depends(get_runtime)]) -> Lake:
    """The lake's operations."""
    return runtime.lake


def get_declarations(runtime: Annotated[Runtime, Depends(get_runtime)]) -> Declarations:
    """The organizations the configuration declares."""
    return runtime.declarations


def get_disk(runtime: Annotated[Runtime, Depends(get_runtime)]) -> LakeDisk | None:
    """The lake's disk, or ``None`` when the service has no lake."""
    return runtime.disk


def with_share_root(row: dict[str, Any], declarations: Declarations) -> dict[str, Any]:
    """``row`` with ``share_root``: the configured root of its ``organization``, or ``None``."""
    return {**row, "share_root": declarations.share_root(row["organization"])}


RuntimeDep = Annotated[Runtime, Depends(get_runtime)]
LakeDep = Annotated[Lake, Depends(get_lake)]
DeclarationsDep = Annotated[Declarations, Depends(get_declarations)]
DiskDep = Annotated[LakeDisk | None, Depends(get_disk)]
