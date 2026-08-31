"""Request bodies for the v1 API surface.

Authorization never happens here - bodies validate shape only. The
``require_*`` dependencies in ``huron.service.api.authorization`` decide who
may call each route, and the repository enforces the domain rules.
"""
