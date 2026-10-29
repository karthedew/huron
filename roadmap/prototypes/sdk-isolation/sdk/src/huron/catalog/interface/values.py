"""Immutable SDK-owned values, independent of server models."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Dataset:
    """An identified, titled dataset in the deliberately minimal packaging fixture."""

    id: UUID
    title: str

    def __post_init__(self) -> None:
        """Reject invalid values at construction.

        Raises:
            ValueError: If identity or title is not a valid fixture value.
        """
        if not isinstance(self.id, UUID) or not isinstance(self.title, str) or not self.title:
            raise ValueError("Dataset requires a UUID identity and nonempty string title")
