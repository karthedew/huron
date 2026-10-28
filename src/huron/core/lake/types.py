"""Lake lifecycle values shared by operations and persistence."""

from enum import StrEnum


class CollectionState(StrEnum):
    """A collection's draft or settled lifecycle state."""

    DRAFT = "draft"
    ACTIVE = "active"
    INCOMPLETE = "incomplete"

    @property
    def settled(self) -> bool:
        """Whether the collection has left its draft state."""
        return self is not CollectionState.DRAFT
