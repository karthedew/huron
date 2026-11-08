"""A read-only view of an in-memory share, which fails the test on any write call."""

from collections.abc import Callable
from typing import Any

from huron.core.storage.memory import MemoryStorage

#: The methods of the ``Storage`` port that change the share.
WRITES = frozenset(
    {
        "apply_plan",
        "ensure_directory",
        "link",
        "make_directory",
        "make_inheriting_dir",
        "remove_directory",
        "remove_file",
        "rename",
        "set_group",
        "set_mode",
        "write_bytes",
    }
)


class ReadOnlyShare:
    """Reads go to ``share``; a call of a write method raises :class:`AssertionError`."""

    def __init__(self, share: MemoryStorage) -> None:
        self.share = share

    def __getattr__(self, name: str) -> Any:
        if name in WRITES:
            return _refuse(name)
        return getattr(self.share, name)


def _refuse(name: str) -> Callable[..., None]:
    def write(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"a write to the read-only share: {name}{args}")

    return write
