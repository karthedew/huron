"""``LakePath``: the one way to name a place on the lake."""

from __future__ import annotations

from dataclasses import dataclass

from huron.schema.naming import check_lake_name

__all__ = ["LakePath"]


@dataclass(frozen=True, slots=True, order=True)
class LakePath:
    """A place below the storage root, as a tuple of names; ``LakePath()`` is the root.

    Each name passed :func:`~huron.schema.naming.check_lake_name`, so no name is empty, ``.``
    or ``..``, or holds a ``/``. There is no absolute form: only a storage adapter turns a
    lake path into a place on a disk.
    """

    names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in self.names:
            check_lake_name(name)

    @classmethod
    def of(cls, *names: str) -> LakePath:
        """The lake path of ``names``, outermost first."""
        return cls(names)

    @classmethod
    def parse(cls, text: str) -> LakePath:
        """The lake path of an API path such as ``helio/sun/wind``.

        An empty text, an empty name (``a//b``, ``/a``, ``a/``), ``.`` and ``..`` are refused
        with ``NAME_INVALID``.
        """
        return cls(tuple(text.split("/")))

    def joinpath(self, *names: str) -> LakePath:
        """The lake path of ``names`` below this one."""
        return LakePath((*self.names, *names))

    @property
    def parent(self) -> LakePath:
        """The lake path one name up; the root is its own parent."""
        return LakePath(self.names[:-1])

    @property
    def name(self) -> str:
        """The last name; the root's is ``""``."""
        return self.names[-1] if self.names else ""

    def relative_to(self, base: LakePath) -> str:
        """This lake path below ``base``, in the API form; raises ``ValueError`` outside it."""
        if self.names[: len(base.names)] != base.names:
            raise ValueError(f"{self} is not below {base}")
        return "/".join(self.names[len(base.names) :])

    def __str__(self) -> str:
        """The API form: the names joined with ``/``."""
        return "/".join(self.names)
