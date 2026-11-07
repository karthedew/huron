"""Bodies shared across the API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

__all__ = ["Health", "Page", "ProblemBody", "ServiceUser", "page_of"]


class ServiceUser(BaseModel):
    """The identity that owns the lake: the service's UID, primary GID and service group."""

    uid: int
    gid: int
    group: str


class Health(BaseModel):
    """The liveness answer.

    ``organizations_managed`` is whether the service configuration declares the organizations:
    the CLI then looks for an organization's directory only where its declaration puts it.
    ``uploads_url`` is the public tus endpoint, ``null`` while uploads are off.
    ``service_user`` is ``null`` without a configured service group. ``upload_hook_timeout`` is
    how long tusd waits for a hook, in seconds.
    """

    status: str
    instance_id: str
    version: str
    organizations_managed: bool
    uploads_url: str | None
    service_user: ServiceUser | None
    upload_hook_timeout: int


class Page[T](BaseModel):
    """One page of items and the cursor of the next page."""

    items: list[T]
    next_cursor: str | None = None


class ProblemBody(BaseModel):
    """An RFC 9457 problem document."""

    type: str
    title: str
    status: int
    detail: str
    code: str
    context: dict[str, Any]
    instance: str | None = None


def page_of[M: BaseModel](
    model: type[M], rows: list[dict[str, Any]], next_cursor: str | None
) -> Page[M]:
    """Build a page of ``model`` from rendered rows."""
    return Page[M](items=[model.model_validate(row) for row in rows], next_cursor=next_cursor)
