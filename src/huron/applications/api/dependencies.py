"""Dependencies that hand the shared runtime, its lake and its disk work to path operations."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Request

from huron.applications.api.disk import Placements, ShareGroups
from huron.applications.api.runtime import Runtime
from huron.core.lake.bootstrap import Lake
from huron.core.lake.organizations.declarations import Declarations
from huron.pkg.errors import HuronError, register

__all__ = [
    "DeclarationsDep",
    "LakeDep",
    "RuntimeDep",
    "ShareGroupsDep",
    "UploadsDep",
    "UploadsDisabled",
    "get_declarations",
    "get_lake",
    "get_runtime",
    "get_share_groups",
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


def get_share_groups(runtime: Annotated[Runtime, Depends(get_runtime)]) -> ShareGroups | None:
    """The share groups of catalog directories, or ``None`` when the service has no lake."""
    return runtime.share_groups


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
ShareGroupsDep = Annotated[ShareGroups | None, Depends(get_share_groups)]
UploadsDep = Annotated[Placements, Depends(require_uploads)]
