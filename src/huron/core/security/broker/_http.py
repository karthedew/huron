"""Shared validation for usable identity-provider HTTP endpoints."""

from urllib.parse import urlsplit

import httpx


def absolute_url(value: object) -> bool:
    """Check that both URL parsers accept an absolute HTTP endpoint.

    Args:
        value: An untrusted endpoint value from configuration or discovery.

    Returns:
        Whether the endpoint has a usable host, scheme and port.
    """
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
        request_url = httpx.URL(value)
    except (ValueError, httpx.InvalidURL):
        return False
    return (
        parsed.scheme in {"https", "http"}
        and bool(parsed.hostname)
        and bool(request_url.host)
        and (port is None or 0 < port <= 65535)
    )
