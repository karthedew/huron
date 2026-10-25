"""Who the caller is, what they may do, and what they may discover.

The public surface, by module: ``cookies`` (``CookieSpec`` and the two
specs the service issues), ``credentials`` (``current_principal`` and the
``CurrentPrincipal``/``CurrentSession`` dependencies that turn a request's
credential into a principal), ``scopes`` (path identifier to RBAC scope,
404 before 403), ``decisions`` (the per-request ``BindingCache``, the
bindings a caller is judged by, ``check`` - the one allow-or-403 call - and
``current_visibility``, the caller's ``Visibility`` computed once per
request) and ``guards`` (the ``require_*`` factories that routes declare). Routes import
from here, never from the modules.
"""

from .cookies import CookieSpec, login_flow_cookie, session_cookie
from .credentials import CurrentPrincipal, CurrentSession, current_principal
from .decisions import (
    BindingCache,
    CurrentVisibility,
    as_rbac_principal,
    bindings_for_principal,
    check,
    current_visibility,
)
from .guards import (
    require_dataset,
    require_organization,
    require_project,
    require_system,
)

__all__ = [
    "BindingCache",
    "CookieSpec",
    "CurrentPrincipal",
    "CurrentSession",
    "CurrentVisibility",
    "as_rbac_principal",
    "bindings_for_principal",
    "check",
    "current_principal",
    "current_visibility",
    "login_flow_cookie",
    "require_dataset",
    "require_organization",
    "require_project",
    "require_system",
    "session_cookie",
]
