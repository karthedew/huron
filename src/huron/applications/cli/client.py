"""The Huron API client: problem documents become CLI errors; lists are paged."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx

from huron import __version__
from huron.applications.cli.deadline import Deadline, DeadlinePassed
from huron.applications.cli.errors import ApiError, CliError, ExitCode

__all__ = ["ApiClient", "if_match"]

_RETRIES = 2


class ApiClient:
    """Calls the API with the caller's Huron token."""

    def __init__(
        self,
        http: httpx.Client,
        base_url: str,
        token: Callable[[], str] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = http
        self._base = base_url.rstrip("/")
        self._token = token
        self._sleep = sleep

    def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | list[tuple[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
        auth: bool = True,
        deadline: Deadline | None = None,
    ) -> httpx.Response:
        """Send a request; any non-2xx answer raises :class:`ApiError`.

        With ``deadline``, the time that remains limits the timeout of the request and each
        sleep before the CLI sends a GET again. A request that times out when no time remains
        raises :class:`~huron.applications.cli.deadline.DeadlinePassed`.
        """
        sent = {"User-Agent": f"huron-cli/{__version__}", **(headers or {})}
        if auth and self._token is not None:
            sent["Authorization"] = f"Bearer {self._token()}"
        url = path if path.startswith("http") else f"{self._base}{path}"
        response = self._send(method, url, json, params, sent, deadline)
        if response.is_success:
            return response
        raise _error(response)

    def get(self, path: str, **kwargs: Any) -> Any:
        """GET and decode JSON."""
        return self.request("GET", path, **kwargs).json()

    def post(self, path: str, **kwargs: Any) -> Any:
        """POST and decode JSON (``None`` for an empty answer)."""
        return _body(self.request("POST", path, **kwargs))

    def put(self, path: str, **kwargs: Any) -> Any:
        """PUT and decode JSON."""
        return _body(self.request("PUT", path, **kwargs))

    def patch(self, path: str, **kwargs: Any) -> Any:
        """PATCH and decode JSON."""
        return _body(self.request("PATCH", path, **kwargs))

    def delete(self, path: str, **kwargs: Any) -> None:
        """DELETE."""
        self.request("DELETE", path, **kwargs)

    def pages(self, path: str, params: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
        """Every item of a paged listing."""
        query = dict(params or {})
        while True:
            page = self.get(path, params=query)
            yield from page["items"]
            if not page.get("next_cursor"):
                return
            query["cursor"] = page["next_cursor"]

    def _send(
        self,
        method: str,
        url: str,
        json: Any,
        params: Any,
        headers: dict[str, str],
        deadline: Deadline | None,
    ) -> httpx.Response:
        attempts = _RETRIES + 1 if method == "GET" else 1
        for attempt in range(attempts):
            timeout = self._http.timeout if deadline is None else deadline.limit(self._http.timeout)
            try:
                return self._http.request(
                    method, url, json=json, params=params, headers=headers, timeout=timeout
                )
            except httpx.TransportError as error:
                timed_out = isinstance(error, httpx.TimeoutException)
                if timed_out and deadline is not None and deadline.remaining() <= 0:
                    raise DeadlinePassed from error
                if attempt + 1 == attempts or not self._pause(0.5 * (attempt + 1), deadline):
                    raise CliError(
                        f"the Huron API at {self._base} is unreachable: {error}",
                        ExitCode.FAILED,
                        hint="to check `api_url`, run `huron config show`",
                    ) from error
        raise AssertionError("unreachable")  # pragma: no cover

    def _pause(self, seconds: float, deadline: Deadline | None) -> bool:
        """Sleep before a GET is sent again; ``False`` when the deadline leaves no time."""
        if deadline is None:
            self._sleep(seconds)
            return True
        return deadline.pause(seconds)


def if_match(version: int) -> dict[str, str]:
    """The ``If-Match`` header for a collection version."""
    return {"If-Match": f'"{version}"'}


def _body(response: httpx.Response) -> Any:
    return response.json() if response.content else None


def _error(response: httpx.Response) -> CliError:
    try:
        document = response.json()
    except ValueError:
        document = None
    if isinstance(document, dict) and "code" in document:
        return ApiError.from_problem(response.status_code, document)
    return CliError(f"the API answered HTTP {response.status_code}", ExitCode.FAILED)
