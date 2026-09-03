"""The HTTP route packages, each mounted under its own URL prefix.

``auth`` is the unversioned login surface at ``/auth``; ``v1`` is the
versioned resource API at ``/api/v1``. A route package owns its path
operations and the request and response bodies they exchange, and nothing
else: authorization policy lives in ``huron.service.api.authorization`` and
the domain rules in the repository.
"""
