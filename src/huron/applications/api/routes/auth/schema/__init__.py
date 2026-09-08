"""Request and response bodies for the unversioned ``/auth`` routes.

Authorization never happens here - bodies validate shape only. Who may log
in, and how a credential resolves to a principal, is decided by
``pkg.auth`` and the endpoint handlers themselves, not by these models.
"""
