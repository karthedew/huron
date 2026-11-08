"""Dependencies that hand the shared runtime, its lake and its disk work to path operations."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Request

from huron.applications.api.disk import Directories, Placements
from huron.applications.api.runtime import Runtime
from huron.core.lake.bootstrap import Lake
from huron.core.lake.organizations.declarations import Declarations
from huron.pkg.errors import HuronError, register

__all__ = [
    "DeclarationsDep",
    "DirectoriesDep",
    "LakeDep",
    "RuntimeDep",
    "UploadsDep",
    "UploadsDisabled",
    "get_declarations",
    "get_directories",
    "get_lake",
    "get_runtime",
    "require_uploads",
    "with_share_root",
]

UPLOADS_DISABLED = register("UPLOADS_DISABLED", 404, "Uploads disabled")


class UploadsDisabled(HuronError):
    """The service has no lake, so it serves no upload route."""

    error_code = UPLOADS_DISABLED


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


def get_directories(runtime: Annotated[Runtime, Depends(get_runtime)]) -> Directories:
    """The directory verbs; without a lake they change nothing on a disk."""
    return runtime.directories


def require_uploads(runtime: Annotated[Runtime, Depends(get_runtime)]) -> Placements:
    """The placement of uploads; without a lake, ``UPLOADS_DISABLED``."""
    if runtime.placements is None:
        raise UploadsDisabled("this service has no lake path. It does not accept uploads")
    return runtime.placements


def with_share_root(row: dict[str, Any], declarations: Declarations) -> dict[str, Any]:
    """``row`` with ``share_root``: the configured root of its ``organization``, or ``None``."""
    return {**row, "share_root": declarations.share_root(row["organization"])}


RuntimeDep = Annotated[Runtime, Depends(get_runtime)]
LakeDep = Annotated[Lake, Depends(get_lake)]
DeclarationsDep = Annotated[Declarations, Depends(get_declarations)]
DirectoriesDep = Annotated[Directories, Depends(get_directories)]
UploadsDep = Annotated[Placements, Depends(require_uploads)]
