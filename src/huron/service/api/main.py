"""The ASGI entrypoint: read the environment once, then build the app.

``app`` is what an ASGI server imports (``huron.service.api.main:app``).
Settings are validated at import time, so a process whose ``HURON_*``
environment describes an unsafe combination fails before it binds a port
rather than after it has accepted a request. Nothing else is constructed
here: stores, the OIDC client and the database pool are wired by the
application's lifespan when the server starts it.
"""

from __future__ import annotations

from .app import create_app
from .settings import settings_from_environment

app = create_app(settings=settings_from_environment())
