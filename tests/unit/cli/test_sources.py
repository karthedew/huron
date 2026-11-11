"""``huron add`` records each source file, and ``huron push`` opens it again only when unchanged."""

import errno
import hashlib
import os
import unicodedata
from collections.abc import Callable
from pathlib import Path

import pytest

from huron.applications.cli.errors import CliError, ExitCode, UsageError
from huron.applications.cli.sources import SkippedEntry, collect_sources, open_source
from huron.schema.naming import REL_PATH_SEGMENT_MAX_BYTES
from tests.support.cli import Cli

COLLISION_HINT = (
    "paths that differ only in the case of letters are the same path in a collection."
    " To give one file a different path, run `huron add <file> --as <path>`"
)
PERMISSION_DENIED = os.strerror(errno.EACCES)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def source(tmp_path: Path) -> Path:
    """An empty directory for the local files to stage."""
    directory = tmp_path / "source"
    directory.mkdir()
    return directory


def write(path: Path, data: bytes = b"data") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def deny(monkeypatch: pytest.MonkeyPatch, name: str, denied: Path) -> None:
    """Make the ``os`` function ``name`` refuse ``denied`` as mode 000 refuses its user."""
    real = getattr(os, name)

    def refuse(path: str | Path, *args: object) -> object:
        if Path(path) == denied:
            raise PermissionError(errno.EACCES, PERMISSION_DENIED, str(path))
        return real(path, *args)

    monkeypatch.setattr(os, name, refuse)


def test_a_named_file_is_recorded_with_its_size_modification_time_and_hash(source: Path) -> None:
    path = write(source / "a.txt", b"alpha")
    os.utime(path, ns=(1_700_000_000_123_456_789, 1_700_000_000_123_456_789))
    (add,), skipped = collect_sources([path], None, recursive=False)
    assert (add.rel_path, add.source, add.size) == ("a.txt", str(path.resolve()), 5)
    assert (add.mtime_ns, add.sha256) == (1_700_000_000_123_456_789, sha(b"alpha"))
    assert (add.attempt_id, add.upload_id, add.attempt_state) == (None, None, None)
    assert skipped == []


def test_an_empty_file_is_recorded_with_the_hash_of_no_bytes(source: Path) -> None:
    (add,), _ = collect_sources([write(source / "empty", b"")], "docs/empty", recursive=False)
    assert (add.rel_path, add.size, add.sha256) == ("docs/empty", 0, sha(b""))


def test_a_file_in_a_linked_directory_is_recorded_at_its_real_location(
    source: Path, tmp_path: Path
) -> None:
    write(source / "a.txt")
    (tmp_path / "linked").symlink_to(source)
    (add,), _ = collect_sources([tmp_path / "linked" / "a.txt"], None, recursive=False)
    assert add.source == str(source.resolve() / "a.txt")


def test_a_walk_records_each_regular_file_at_its_relative_path_in_name_order(
    source: Path,
) -> None:
    for name in ("b.txt", "a.txt", "deep/c.txt", "deep/deeper/d.txt"):
        write(source / name, name.encode())
    staged, skipped = collect_sources([source], None, recursive=True)
    assert [(add.rel_path, add.sha256) for add in staged] == [
        ("a.txt", sha(b"a.txt")),
        ("b.txt", sha(b"b.txt")),
        ("deep/c.txt", sha(b"deep/c.txt")),
        ("deep/deeper/d.txt", sha(b"deep/deeper/d.txt")),
    ]
    assert skipped == []


def test_a_walk_skips_and_reports_links_special_files_and_unreadable_entries(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = write(tmp_path / "outside" / "secret.txt").parent
    write(source / "kept.txt")
    (source / "file-link").symlink_to(source / "kept.txt")
    (source / "directory-link").symlink_to(outside, target_is_directory=True)
    os.mkfifo(source / "pipe")
    unreadable = write(source / "unreadable.txt")
    closed = write(source / "closed" / "inside.txt").parent
    deny(monkeypatch, "open", unreadable)
    deny(monkeypatch, "scandir", closed)
    staged, skipped = collect_sources([source], None, recursive=True)
    assert [add.rel_path for add in staged] == ["kept.txt"]
    assert skipped == [
        SkippedEntry(closed, PERMISSION_DENIED),
        SkippedEntry(source / "directory-link", "it is a symbolic link"),
        SkippedEntry(source / "file-link", "it is a symbolic link"),
        SkippedEntry(source / "pipe", "it is not a regular file"),
        SkippedEntry(unreadable, PERMISSION_DENIED),
    ]


def test_a_named_directory_that_cannot_be_listed_is_reported(
    source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(source / "a.txt")
    deny(monkeypatch, "scandir", source)
    assert collect_sources([source], None, recursive=True) == (
        [],
        [SkippedEntry(source, PERMISSION_DENIED)],
    )


def link(path: Path) -> Path:
    path.symlink_to(write(path.with_name("target.txt")))
    return path


def fifo(path: Path) -> Path:
    os.mkfifo(path)
    return path


@pytest.mark.parametrize(
    ("make", "reason"),
    [
        (link, "it is a symbolic link"),
        (fifo, "it is not a regular file"),
        (lambda path: path, "No such file or directory"),
    ],
    ids=["link", "fifo", "missing"],
)
def test_a_named_entry_that_is_not_a_regular_file_is_refused(
    source: Path, make: Callable[[Path], Path], reason: str
) -> None:
    path = make(source / "entry")
    with pytest.raises(UsageError) as raised:
        collect_sources([path], None, recursive=False)
    assert raised.value.message == f"the CLI cannot stage {path}: {reason}"


def test_a_named_file_that_cannot_be_read_is_refused(
    source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write(source / "a.txt")
    deny(monkeypatch, "open", path)
    with pytest.raises(UsageError) as raised:
        collect_sources([write(source / "b.txt"), path], None, recursive=False)
    assert raised.value.message == f"the CLI cannot stage {path}: {PERMISSION_DENIED}"


def test_a_named_directory_needs_recursive(source: Path) -> None:
    with pytest.raises(UsageError) as raised:
        collect_sources([source], None, recursive=False)
    assert (raised.value.message, raised.value.hint) == (
        f"{source} is a directory",
        "use `--recursive`",
    )


def test_a_rename_needs_exactly_one_path(source: Path) -> None:
    with pytest.raises(UsageError, match="`--as` needs exactly one file"):
        collect_sources([write(source / "a"), write(source / "b")], "x", recursive=False)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Data.csv", "data.csv"),
        (unicodedata.normalize("NFC", "Café.txt"), unicodedata.normalize("NFC", "CAFÉ.txt")),
        ("STRASSE.txt", "straße.txt"),
    ],
    ids=["case", "accented case", "case folding"],
)
def test_two_files_equal_after_nfc_and_case_folding_refuse_the_add(
    source: Path, first: str, second: str
) -> None:
    write(source / first)
    write(source / second)
    with pytest.raises(UsageError) as raised:
        collect_sources([source], None, recursive=True)
    paths = sorted([source / first, source / second], key=lambda path: path.name)
    assert raised.value.message == (f"{paths[0]} and {paths[1]} have the same path in a collection")
    assert raised.value.hint == COLLISION_HINT


def test_a_name_that_is_not_nfc_is_refused_beside_its_nfc_twin(source: Path) -> None:
    composed = write(source / unicodedata.normalize("NFC", "é.txt"))
    decomposed = write(source / unicodedata.normalize("NFD", "é.txt"))
    assert composed != decomposed
    with pytest.raises(UsageError) as raised:
        collect_sources([source], None, recursive=True)
    assert raised.value.message == (
        f"{decomposed.name!r} is not a valid path in a collection (rel_path_nfc)"
    )


def test_two_named_files_with_one_path_in_a_collection_refuse_the_add(source: Path) -> None:
    first, second = write(source / "one" / "a.txt"), write(source / "two" / "A.TXT")
    with pytest.raises(UsageError) as raised:
        collect_sources([first, second], None, recursive=False)
    assert raised.value.message == f"{first} and {second} have the same path in a collection"


def test_a_refused_path_reads_no_file(source: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    unreadable = write(source / "a.txt")
    write(source / "A.txt")
    deny(monkeypatch, "open", unreadable)
    with pytest.raises(UsageError, match="have the same path in a collection"):
        collect_sources([source], None, recursive=True)


def component(bytes_: int) -> str:
    """A file name of ``bytes_`` UTF-8 bytes, 200 of them in two-byte characters."""
    return "é" * 100 + "x" * (bytes_ - 200)


def test_a_path_component_of_206_bytes_is_staged(source: Path) -> None:
    name = component(REL_PATH_SEGMENT_MAX_BYTES)
    assert len(name.encode()) == 206
    write(source / "deep" / name)
    (add,), _ = collect_sources([source], None, recursive=True)
    assert add.rel_path == f"deep/{name}"


def test_a_path_component_of_207_bytes_refuses_the_add(source: Path) -> None:
    rel_path = f"deep/{component(207)}"
    write(source / rel_path)
    with pytest.raises(UsageError) as raised:
        collect_sources([source], None, recursive=True)
    assert raised.value.message == (
        f"{rel_path!r} is not a valid path in a collection (rel_path_segment)"
    )


def test_an_unchanged_source_opens_at_its_first_byte(source: Path) -> None:
    (add,), _ = collect_sources([write(source / "a.txt", b"alpha")], None, recursive=False)
    with open_source(add) as handle:
        assert handle.read() == b"alpha"


def test_a_source_replaced_by_a_fifo_is_refused_as_changed(source: Path) -> None:
    path = write(source / "a.txt", b"")
    (add,), _ = collect_sources([path], None, recursive=False)
    path.unlink()
    os.mkfifo(path)
    os.utime(path, ns=(add.mtime_ns, add.mtime_ns))
    with pytest.raises(CliError) as raised:
        open_source(add)
    assert raised.value.exit_code == ExitCode.USAGE
    assert raised.value.message == f"{add.source} changed after you staged it as a.txt"


def test_a_source_that_cannot_be_read_is_refused_with_the_reason(
    source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write(source / "my data.txt")
    (add,), _ = collect_sources([path], "a b.txt", recursive=False)
    deny(monkeypatch, "open", path.resolve())
    with pytest.raises(CliError) as raised:
        open_source(add)
    assert raised.value.message == (
        f"the CLI cannot read {add.source}, which you staged as a b.txt: {PERMISSION_DENIED}"
    )
    assert raised.value.hint == (
        f"to stage the file again, run `huron add '{add.source}' --as 'a b.txt'`."
        " To unstage it, run `huron rm 'a b.txt'`"
    )


def test_add_warns_for_each_skipped_entry_and_stages_the_rest(ready: Cli, source: Path) -> None:
    write(source / "a.txt", b"alpha")
    (source / "link").symlink_to(source / "a.txt")
    os.mkfifo(source / "pipe")
    added = ready.ok("add", str(source), "--recursive")
    assert added.stdout.splitlines() == ["staged a.txt (5 bytes)"]
    assert added.stderr.splitlines() == [
        f"warning: the CLI did not stage {source / 'link'}: it is a symbolic link",
        f"warning: the CLI did not stage {source / 'pipe'}: it is not a regular file",
    ]
    (add,) = ready.working().adds
    assert (add.size, add.sha256) == (5, sha(b"alpha"))
    assert add.mtime_ns == (source / "a.txt").stat().st_mtime_ns


def test_a_refused_add_leaves_the_stage_unchanged(ready: Cli, source: Path) -> None:
    write(source / "a.txt")
    ready.ok("add", str(source / "a.txt"))
    before = ready.working()
    write(source / "Data.csv")
    write(source / "data.csv")
    refused = ready.run("add", str(source), "--recursive")
    assert refused.exit_code == ExitCode.USAGE
    assert "have the same path in a collection" in refused.stderr
    assert ready.working() == before
