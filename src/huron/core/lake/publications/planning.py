"""The entries that publish a commit request, in the one order that every run follows."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from huron.core.lake.files.errors import CommitInvalid, FileNotRecorded
from huron.core.lake.publications.models import CommitEntry, EntryAction
from huron.schema.naming import rel_path_key

if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterable, Mapping

    from huron.core.lake.publications.models import CommitAdd, CommitDraft, CommitRequest, DraftAdd

    type Changes = CommitRequest | CommitDraft
    type Added = CommitAdd | DraftAdd

__all__ = ["plan_entries"]


def plan_entries(current: Iterable[str], request: Changes) -> tuple[CommitEntry, ...]:
    """The entries that change the files ``current`` into the files after ``request``.

    ``current`` holds the paths of the recorded files of the collection, and the directories of
    the collection are the directories above them. ``request`` is a commit request, or the draft
    of a dry run, whose add entries name no upload when the draft names none. Directories
    compare by exact spelling: on a case-sensitive filesystem ``Dir`` and ``dir`` are two
    directories.

    - A remove names a recorded file by its key, and the entry uses the recorded spelling.
    - An add whose key is recorded with a different spelling removes that file, then adds the
      new spelling. An add with the recorded spelling replaces the file in one entry.
    - An add at the path of a directory removes that directory and each directory below it.
      Every recorded file below it must be removed by the request. This removal blocks on a
      foreign file.
    - Each other directory that no kept file and no added file needs is pruned. A prune keeps a
      directory that holds a foreign file. The collection directory itself is never pruned.
    - An add makes each directory above it that does not exist.

    The order: first every removal of a file or a directory and every prune, the deepest path
    first. Then every new directory and every add, a parent directory before its children. Thus
    a directory is empty when it is removed or pruned, a path is free when an add or a new
    directory takes it, and the parent of each new path exists. No directory that an add needs
    is removed or pruned.

    Raises :class:`FileNotRecorded` for a remove that names no recorded file, and
    :class:`CommitInvalid` for an add inside an added file, inside a recorded file that stays, or
    over a directory that keeps a recorded file.
    """
    files = {rel_path_key(path): path for path in current}
    removed = _recorded(files, request.removes)
    _check_adds(request.adds)
    kept = _kept(files, removed, request.adds)
    _check_tree(request.adds, kept)
    directories = _directories(files.values())
    needed = _directories([*kept, *(add.rel_path for add in request.adds)])
    removals = _removals([*removed, *_respelled(files, request)], directories - needed, request)
    additions = _additions(needed - directories, request)
    return tuple(
        replace(entry, ordinal=ordinal) for ordinal, entry in enumerate([*removals, *additions])
    )


def _recorded(files: Mapping[str, str], removes: Iterable[str]) -> list[str]:
    """The recorded spelling of each removed path."""
    missing = [path for path in removes if rel_path_key(path) not in files]
    if missing:
        raise FileNotRecorded(
            "the commit removes files that are not recorded", {"rel_paths": missing[:20]}
        )
    return [files[rel_path_key(path)] for path in removes]


def _check_adds(adds: Iterable[Added]) -> None:
    added = {_key(add): add.rel_path for add in adds}
    for key, path in added.items():
        outer = _enclosing(key, added)
        if outer is not None:
            raise CommitInvalid(
                f"{path!r} lies inside {outer!r}, which the commit adds as a file",
                {"rel_path": path, "other": outer},
            )


def _check_tree(adds: Iterable[Added], kept: Iterable[str]) -> None:
    """Refuse an add inside a kept file, or over a directory that holds a kept file."""
    kept_files: dict[str, str] = {}
    kept_below: dict[str, str] = {}
    for path in kept:
        kept_files[rel_path_key(path)] = path
        for directory in _parents(rel_path_key(path)):
            kept_below.setdefault(directory, path)
    for add in adds:
        outer = _enclosing(_key(add), kept_files)
        if outer is not None:
            raise CommitInvalid(
                f"{add.rel_path!r} lies inside {outer!r}, which is a recorded file",
                {"rel_path": add.rel_path, "other": outer},
            )
        child = kept_below.get(_key(add))
        if child is not None:
            raise CommitInvalid(
                f"{add.rel_path!r} is a directory that contains the recorded file {child!r}",
                {"rel_path": add.rel_path, "other": child},
            )


def _enclosing(key: str, files: Mapping[str, str]) -> str | None:
    """The path in ``files`` whose key is a directory above ``key``, if there is one."""
    return next((files[each] for each in _parents(key) if each in files), None)


def _respelled(files: Mapping[str, str], request: Changes) -> list[str]:
    """The recorded spelling of each file that an add gives a new spelling."""
    return [
        files[_key(add)]
        for add in request.adds
        if files.get(_key(add), add.rel_path) != add.rel_path
    ]


def _directories(paths: Iterable[str]) -> set[str]:
    """The spelling of each directory above ``paths``."""
    return {parent for path in paths for parent in _parents(path)}


def _taken(directory: str, added: Iterable[str]) -> bool:
    """Whether an added file takes the path of ``directory`` or of a directory above it."""
    paths = {directory, *_parents(directory)}
    return any(path in paths for path in added)


def _kept(files: Mapping[str, str], removed: Iterable[str], adds: Iterable[Added]) -> list[str]:
    """The recorded files that the request neither removes nor replaces, sorted."""
    gone = {rel_path_key(path) for path in removed} | {_key(add) for add in adds}
    return sorted(path for key, path in files.items() if key not in gone)


def _removals(files: Iterable[str], unneeded: Iterable[str], request: Changes) -> list[CommitEntry]:
    """The removed files, then the removed and the pruned directories, the deepest path first.

    An unneeded directory at an added path or below one is removed. Each other one is pruned.
    """
    added = [add.rel_path for add in request.adds]
    entries = [_entry(EntryAction.REMOVE_FILE, path) for path in files]
    entries += [
        _entry(
            EntryAction.REMOVE_DIRECTORY if _taken(path, added) else EntryAction.PRUNE_DIRECTORY,
            path,
        )
        for path in unneeded
    ]
    return sorted(entries, key=lambda entry: (-_depth(entry.rel_path), entry.rel_path))


def _additions(new: Iterable[str], request: Changes) -> list[CommitEntry]:
    """The new directories and the adds, a parent directory before its children."""
    entries = [_entry(EntryAction.MAKE_DIRECTORY, path) for path in new]
    entries += [_entry(EntryAction.ADD_FILE, add.rel_path, add.upload_id) for add in request.adds]
    return sorted(entries, key=lambda entry: (_depth(entry.rel_path), entry.rel_path))


def _entry(action: EntryAction, rel_path: str, upload_id: uuid.UUID | None = None) -> CommitEntry:
    """An entry whose ordinal the plan sets when it knows the order."""
    return CommitEntry(0, action, rel_path, upload_id)


def _key(add: Added) -> str:
    return rel_path_key(add.rel_path)


def _parents(path: str) -> list[str]:
    parts = path.split("/")
    return ["/".join(parts[:end]) for end in range(1, len(parts))]


def _depth(path: str) -> int:
    return path.count("/") + 1
