"""A fake LDAP group directory, in process and over HTTP."""

from collections.abc import Mapping, Sequence

import httpx


class FakeGroups:
    """A :class:`GroupDirectory` backed by a mapping."""

    def __init__(self, mapping: Mapping[str, Sequence[str]]) -> None:
        self.mapping = {user: list(groups) for user, groups in mapping.items()}

    async def groups_for(self, username: str) -> frozenset[str]:
        return frozenset(self.mapping.get(username, ()))


def groups_transport(
    mapping: Mapping[str, Sequence[str]], status: int = 200
) -> httpx.MockTransport:
    """An HTTP transport answering ``GET /users/{username}/groups`` from ``mapping``."""

    def handler(request: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status)
        parts = request.url.path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "users" and parts[2] == "groups":
            if parts[1] in mapping:
                return httpx.Response(200, json={"groups": list(mapping[parts[1]])})
            return httpx.Response(404)
        return httpx.Response(400)

    return httpx.MockTransport(handler)
