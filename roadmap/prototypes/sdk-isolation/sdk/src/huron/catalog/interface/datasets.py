"""Dataset retrieval against a labelled packaging fixture, not an authoritative API."""

from uuid import UUID

import httpx

from huron.catalog.interface.errors import DatasetNotFoundError, InvalidResponseError
from huron.catalog.interface.values import Dataset


class Datasets:
    """Retrieve SDK values through a borrowed HTTP client."""

    def __init__(self, http: httpx.Client) -> None:
        """Borrow transport from the composing client.

        Args:
            http: The HTTP client; its owner retains lifetime responsibility.
        """
        self._http = http

    def get(self, dataset_id: UUID) -> Dataset:
        """Fetch and validate one packaging-fixture response.

        Args:
            dataset_id: The exact fixture identity to retrieve.

        Returns:
            An immutable SDK-owned dataset value.

        Raises:
            ValueError: If the request identity is not a UUID.
            DatasetNotFoundError: If the endpoint responds with 404.
            InvalidResponseError: If successful response JSON violates the fixture contract.
        """
        if not isinstance(dataset_id, UUID):
            raise ValueError("dataset_id must be a UUID")
        response = self._http.get(f"packaging-fixture/datasets/{dataset_id}")
        try:
            if response.status_code == 404:
                raise DatasetNotFoundError(str(dataset_id))
            response.raise_for_status()
            try:
                body = response.json()
                if not isinstance(body, dict) or set(body) != {"id", "title"}:
                    raise ValueError("expected the packaging fixture's id/title object")
                if not isinstance(body["id"], str):
                    raise ValueError("expected a string UUID")
                dataset = Dataset(id=UUID(body["id"]), title=body["title"])
                if dataset.id != dataset_id:
                    raise ValueError("response identity differs from request")
                return dataset
            except (TypeError, ValueError) as error:
                raise InvalidResponseError("invalid packaging fixture response") from error
        finally:
            response.close()
