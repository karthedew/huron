"""Initial ownership under trusted deployment authority, before ordinary authorization."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.security.rules import ScopeType

if TYPE_CHECKING:
    from huron.core.security.ports import BindingStore


async def bootstrap_platform_owner(rbac: BindingStore, subject: str | None) -> None:
    """Establish the configured initial owner idempotently under deployment authority.

    This operation is for trusted startup wiring, never a scientist-facing grant.
    It establishes the authority ordinary binding operations require and preserves
    any existing matching system grant, including its original provenance.

    Args:
        rbac: Authoritative binding persistence.
        subject: Configured initial user subject; absent or empty disables bootstrap.
    """
    if not subject:
        return
    principal = f"user:{subject}"
    existing = await rbac.bindings_at(ScopeType.SYSTEM, None)
    already = any(
        item.principal == principal and item.role_code == "platform_owner" for item in existing
    )
    if not already:
        await rbac.grant_role(
            principal=principal,
            role_code="platform_owner",
            scope_type=ScopeType.SYSTEM,
            scope_id=None,
            created_by="bootstrap",
        )
