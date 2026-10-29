"""Dependencies that hand the shared runtime and its lake to path operations."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from huron.applications.api.runtime import Runtime
from huron.core.lake.bootstrap import Lake

__all__ = ["LakeDep", "RuntimeDep", "get_lake", "get_runtime"]


def get_runtime(request: Request) -> Runtime:
    """The runtime built at startup."""
    runtime: Runtime = request.app.state.runtime
    return runtime


def get_lake(runtime: Annotated[Runtime, Depends(get_runtime)]) -> Lake:
    """The lake's operations."""
    return runtime.lake


RuntimeDep = Annotated[Runtime, Depends(get_runtime)]
LakeDep = Annotated[Lake, Depends(get_lake)]
