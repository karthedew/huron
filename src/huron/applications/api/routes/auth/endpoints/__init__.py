"""The ``/auth`` path operations: one module per concern; each exposes ``router``.

``login`` holds password login and logout, ``oidc`` the browser half of the
OIDC code flow, and ``session`` identity introspection and login-method
discovery. The package router in ``routes.auth`` includes all three.
"""
