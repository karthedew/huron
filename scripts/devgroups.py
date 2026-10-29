"""A development LDAP group directory: ``GET /users/{username}/groups`` from a YAML file.

Run with ``python scripts/devgroups.py scripts/dev-groups.yaml 8082``. Development only.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml


def load(path: Path) -> dict[str, list[str]]:
    """The username → groups mapping in ``path``."""
    data = yaml.safe_load(path.read_text()) or {}
    return {str(user): [str(g) for g in groups or []] for user, groups in data.items()}


def answer(groups: dict[str, list[str]], path: str) -> tuple[int, dict[str, object] | None]:
    """The status and body for a request path."""
    parts = path.strip("/").split("/")
    if len(parts) != 3 or parts[0] != "users" or parts[2] != "groups":
        return 400, {"error": "use /users/{username}/groups"}
    if parts[1] not in groups:
        return 404, None
    return 200, {"groups": groups[parts[1]]}


def main(argv: list[str]) -> int:
    """Serve the directory until interrupted."""
    groups = load(Path(argv[0]))
    port = int(argv[1]) if len(argv) > 1 else 8082

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - the http.server hook name
            status, body = answer(groups, self.path)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            if body is not None:
                self.wfile.write(json.dumps(body).encode())

    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()  # noqa: S104
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
