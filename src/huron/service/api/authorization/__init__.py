"""Who the caller is, and what they may do."""

from .cookies import CookieSpec, login_flow_cookie, session_cookie
from .credentials import CurrentPrincipal, CurrentSession, current_principal
from .decisions import BindingCache, as_rbac_principal, bindings_for_principal, check
from .guards import (
    LayerWrite,
    dataset_layer_writer,
    require_dataset,
    require_organization,
    require_project,
    require_system,
)
from .scopes import dataset_scope, organization_scope, project_scope

__all__ = [
    "BindingCache",
    "CookieSpec",
    "CurrentPrincipal",
    "CurrentSession",
    "LayerWrite",
    "as_rbac_principal",
    "bindings_for_principal",
    "check",
    "current_principal",
    "dataset_layer_writer",
    "dataset_scope",
    "login_flow_cookie",
    "organization_scope",
    "project_scope",
    "require_dataset",
    "require_organization",
    "require_project",
    "require_system",
    "session_cookie",
]
