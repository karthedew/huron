"""The identity every credential resolver produces, before authorization runs.

Whatever the credential was - an API key, an OIDC bearer
token, or a development header - its resolver ends in a :class:`Principal`,
and everything downstream, authorization first, works from that object
rather than from the credential. This module holds only the dataclass so
that every resolver and every consumer can import it without pulling in
the rest of the package.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Principal:
    """An authenticated subject and the facts authorization needs about it.

    Frozen: a principal is a snapshot taken at the moment the credential
    was resolved, and nothing after that point can add a group or widen a
    scope. ``subject`` is the globally unique name the principal is known
    by everywhere else. ``groups`` come from the identity provider's claim
    or explicitly trusted development headers. ``scopes`` and
    ``project_id`` are the restrictions an API key was minted with and are
    empty or ``None`` for every other credential. ``authentication_method``
    records how the subject proved itself (``"api-key"``,
    ``"oidc"`` or ``"dev-headers"``) and is reported back to the caller.
    """

    subject: str
    groups: frozenset[str] = frozenset()
    scopes: frozenset[str] = frozenset()
    project_id: str | None = None
    authentication_method: str = "unknown"
    #: "user" or "service_account" - drives which roles the subject may hold.
    kind: str = "user"


__all__ = ["Principal"]
