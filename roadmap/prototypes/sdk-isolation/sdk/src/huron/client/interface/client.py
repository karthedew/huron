"""A synchronous client composing dataset access and owning its HTTP transport."""

from types import TracebackType
from typing import Self

import httpx

from huron.catalog import Datasets


class Client:
    """Own one HTTP client, with no credential discovery or constructor requests."""

    def __init__(
        self,
        *,
        base_url: str = "https://packaging-fixture.invalid/",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """Compose services over an owned transport.

        Args:
            base_url: Fixture endpoint, not a configured Huron API endpoint.
            transport: Optional external HTTP seam; ownership transfers to this client.
        """
        self._http = httpx.Client(base_url=base_url, transport=transport, trust_env=False)
        self.datasets = Datasets(self._http)

    @property
    def is_closed(self) -> bool:
        """Whether the owned transport has been closed."""
        return self._http.is_closed

    def close(self) -> None:
        """Close the owned HTTP transport, idempotently."""
        self._http.close()

    def __enter__(self) -> Self:
        """Enter the owned HTTP client's context.

        Returns:
            This client.
        """
        self._http.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close resources without suppressing a caller exception.

        Args:
            exc_type: The caller exception type, if any.
            exc_value: The caller exception, if any.
            traceback: The caller traceback, if any.
        """
        self.close()
