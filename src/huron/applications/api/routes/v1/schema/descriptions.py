"""Shared hierarchy PATCH input and translation to a Catalog description change."""

from pydantic import BaseModel

from huron.core.hierarchy.types import DescriptionChange


class DescriptionPatch(BaseModel):
    """Optional descriptive fields shared by the named hierarchy PATCH bodies."""

    #: Accepted so Core can explicitly refuse a changed immutable slug.
    slug: str | None = None
    title: str | None = None
    description: str | None = None

    def to_change(self, expected_version: int) -> DescriptionChange:
        """Translate the body without conflating empty strings with omitted values.

        Args:
            expected_version: The version parsed from the caller's If-Match header.

        Returns:
            A description change retaining null-as-unchanged semantics.
        """
        return DescriptionChange(
            expected_version=expected_version,
            slug=self.slug,
            title=self.title,
            description=self.description,
        )
