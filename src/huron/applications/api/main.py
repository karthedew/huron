"""The ASGI entry point: ``uvicorn huron.applications.api.main:app``."""

from huron.applications.api.app import create_app
from huron.applications.api.settings import Settings

app = create_app(Settings())  # pyright: ignore
