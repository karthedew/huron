"""The ASGI entrypoint: read the environment once, then build the app."""

from __future__ import annotations

from .app import create_app
from .settings import settings_from_environment

app = create_app(settings=settings_from_environment())
