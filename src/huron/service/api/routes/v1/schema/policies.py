"""Request and response bodies owned by ``endpoints/policies.py``."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from huron.pkg.catalog.manifest import canonical_bytes
from huron.pkg.rbac import ScopeType

MAX_POLICY_SPEC_BYTES = 1_048_576

# The caller's own JSON, opaque to this service: not typed beyond "an
# object". Written as a plain assignment, not a `TypeAlias`-annotated one,
# because ruff's UP040 rule rewrites any `TypeAlias`-annotated alias into a
# PEP 695 `type` statement, and Pydantic treats a `type` statement (unlike
# a plain assignment) as a named schema - it would publish a `PolicySpec`
# $ref in place of the inline object schema a bare `dict[str, object]`
# annotation produces.
PolicySpec = dict[str, object]


class CreatePolicy(BaseModel):
    """The body of ``POST /policies``: a definition that grants nothing until attached.

    ``policy_type`` is a lowercase identifier the caller's tooling switches
    on; ``spec`` is the caller's own JSON object, stored and returned
    verbatim and never interpreted by the service. The one thing checked
    about ``spec`` is its size: at most ``MAX_POLICY_SPEC_BYTES`` (1 MiB)
    in canonical form.
    """

    policy_type: str = Field(pattern=r"^[a-z][a-z0-9_]{1,62}$")
    name: str = Field(min_length=1)
    spec: PolicySpec

    @field_validator("spec")
    @classmethod
    def _bounded_spec(cls, spec: PolicySpec) -> PolicySpec:
        """Refuse a ``spec`` larger than ``MAX_POLICY_SPEC_BYTES`` in canonical form.

        The size is measured on the RFC 8785 canonical encoding - the
        bytes the service would actually store and hash - so the ceiling
        does not depend on how the caller happened to space or order the
        JSON it sent. Raised inside validation, the error reaches the
        caller as the ``REQUEST_INVALID`` 422 every schema violation gets.

        Args:
            spec: The caller's JSON object, already parsed.

        Returns:
            ``spec`` itself, unchanged.

        Raises:
            ValueError: If the canonical encoding exceeds
                ``MAX_POLICY_SPEC_BYTES``, naming both sizes.
        """
        size = len(canonical_bytes(spec))
        if size > MAX_POLICY_SPEC_BYTES:
            raise ValueError(
                f"spec is {size} bytes, exceeding the {MAX_POLICY_SPEC_BYTES} byte limit"
            )
        return spec


class AttachPolicy(BaseModel):
    """The body of a ``policy-attachments`` POST: which policy to bind to this scope.

    The scope - an organization, a project or a dataset - is named by the
    route, so the body carries only the policy's id. Attaching is the
    guarded act; the same policy attached twice at one scope is refused
    with ``ATTACHMENT_EXISTS``.
    """

    policy_id: UUID


class PolicyView(BaseModel):
    """A policy definition. Creating one grants nothing; attaching it does.

    ``spec`` is the caller's own JSON, stored and returned verbatim: the
    service does not interpret it, so it is not typed beyond "an object".
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    policy_type: str
    name: str
    spec: PolicySpec
    created_by: str
    created_at: datetime


class PolicyAttachmentView(BaseModel):
    """One policy bound to one scope.

    ``scope_type`` is never ``SYSTEM``: policies attach at an organization,
    a project or a dataset, so ``scope_id`` always names one of those.
    """

    model_config = ConfigDict(from_attributes=True)

    policy_id: UUID
    scope_type: ScopeType
    scope_id: UUID
    attached_by: str
    attached_at: datetime
