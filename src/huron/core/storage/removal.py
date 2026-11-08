"""Removals on the lake: the clean-up of the empty directories a removal leaves."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.storage.ports import Outcome

if TYPE_CHECKING:
    from collections.abc import Sequence

    from huron.core.storage.lakepath import LakePath
    from huron.core.storage.ports import Storage

__all__ = ["prune"]


def prune(storage: Storage, directories: Sequence[LakePath]) -> None:
    """Remove the empty ``directories``, innermost first, and stop at the first that is not.

    ``directories`` are outermost first and all lie below a collection directory, which this
    never removes: that directory belongs to the delete verb. A directory that is already gone
    is passed over.
    """
    for directory in reversed(directories):
        if storage.remove_directory(directory) is Outcome.KEPT:
            return
