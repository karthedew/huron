"""Authenticated self-access summaries and termination of the caller's session."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from huron.core.security.errors import Forbidden
from huron.core.security.types import ScopeCapabilities, SelfAccessSummary

from .access import as_rbac_principal, bindings_for_principal

if TYPE_CHECKING:
    from uuid import UUID

    from huron.core.foundation.clock import Clock
    from huron.core.security.facts import BindingFacts
    from huron.core.security.principal import Principal
    from huron.core.security.sessions import SessionRecord, SessionStore


def _require_own_session(actor: Principal, session: SessionRecord | None) -> None:
    """Refuse a session unrelated to the authenticated actor.

    Args:
        actor: Authenticated caller.
        session: Its resolved session, if any.

    Raises:
        Forbidden: If the caller did not authenticate with this subject's session.
    """
    if session is not None and (
        actor.authentication_method != "session" or actor.subject != session.subject
    ):
        raise Forbidden("session must belong to the authenticated actor")


async def terminate_session(
    actor: Principal, session: SessionRecord | None, store: SessionStore, *, clock: Clock
) -> None:
    """End the authenticated caller's session; bearer credentials remain valid.

    Args:
        actor: Authenticated caller, required independently of transport guards.
        session: Session returned by credential resolution, absent for bearer callers.
        store: Session revocation persistence.
        clock: Revocation time source.
    """
    _require_own_session(actor, session)
    if session is not None:
        await store.revoke(session.id, clock.now())


async def self_access_summary(
    actor: Principal, session: SessionRecord | None, repository: BindingFacts
) -> SelfAccessSummary:
    """Summarize only the authenticated actor's current capabilities and session.

    Args:
        actor: Authenticated caller whose identity determines all binding lookups.
        session: Its authenticated session, absent for bearer callers.
        repository: Current user/group bindings and service-account facts.

    Returns:
        Identity and stable scope/capability ordering, with absolute session expiry.
    """
    _require_own_session(actor, session)
    bindings = await bindings_for_principal({}, repository, as_rbac_principal(actor))
    capabilities_by_scope: dict[tuple[str, UUID | None], set[str]] = defaultdict(set)
    for binding in bindings:
        capabilities_by_scope[(binding.scope_type.value, binding.scope_id)].update(
            binding.capabilities
        )
    scopes = tuple(
        ScopeCapabilities(scope_type, scope_id, tuple(sorted(capabilities)))
        for (scope_type, scope_id), capabilities in sorted(
            capabilities_by_scope.items(), key=lambda entry: (entry[0][0], str(entry[0][1] or ""))
        )
    )
    return SelfAccessSummary(
        actor,
        scopes,
        session.csrf_token if session is not None else None,
        session.absolute_expires_at if session is not None else None,
    )
