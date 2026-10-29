"""Public errors for the packaging fixture's HTTP contract."""


class DatasetNotFoundError(LookupError):
    """The fixture endpoint returned HTTP 404."""


class InvalidResponseError(ValueError):
    """A successful response did not satisfy the fixture's value contract."""
