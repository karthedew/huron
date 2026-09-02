"""API service: the FastAPI control plane.

Every control-plane route. Streams raw uploads with in-flight SHA-256, issues
access grants, enforces authorization on every request. Stateless, >=2
replicas.

Composition root: constructs the concrete stores from settings and injects
them into catalog use cases. Routers and DTOs stay thin -- no rule that
belongs in a package is restated here.
"""

from .app import create_app
from .settings import ApiSettings

__all__ = ["ApiSettings", "create_app"]
