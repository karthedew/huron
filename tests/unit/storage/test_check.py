"""Drift findings, one case per finding code."""

import hashlib
from datetime import timedelta
from pathlib import Path

from huron.core.storage import DIRECTORY_MODE, LakePath
from huron.core.storage.check import ExpectedCollection, ExpectedDirectory, Severity, check
from huron.core.storage.memory import MemoryStorage
from tests.support.clock import START

ROOT = Path("/share")
SIDECAR = b'{"huron":1}\n'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(*names: str) -> LakePath:
    return LakePath.of("o", "c", "ns", "run", *names)


def tree() -> MemoryStorage:
    storage = MemoryStorage(ROOT)
    for size in range(1, 5):
        storage.make_directory(LakePath(run().names[:size]), DIRECTORY_MODE)
    storage.write_bytes(run("a.txt"), b"alpha", 0o644)
    storage.write_bytes(run("metadata.json"), SIDECAR, 0o644)
    storage.make_directory(run("empty"), DIRECTORY_MODE)
    return storage


def expected(**overrides: object) -> tuple[list[ExpectedDirectory], list[ExpectedCollection]]:
    collection = {
        "identifier": "c.ns.run",
        "state": "active",
        "created_at": START,
        "disk_path": "o/c/ns/run",
        "files": {"a.txt": {"rel_path": "a.txt", "size": 5, "sha256": sha(b"alpha")}},
        "sidecar": SIDECAR,
        **overrides,
    }
    return (
        [ExpectedDirectory("c", "o/c"), ExpectedDirectory("c.ns", "o/c/ns")],
        [ExpectedCollection(**collection)],  # type: ignore[arg-type]
    )


def codes(
    storage: MemoryStorage, *, hash_files: bool = False, now=START, **overrides: object
) -> list[str]:  # type: ignore[no-untyped-def]
    namespaces, collections = expected(**overrides)
    return [f.code for f in check(storage, namespaces, collections, now, hash_files=hash_files)]


def test_a_clean_tree_has_no_findings() -> None:
    assert codes(tree()) == []


def test_missing_directories_and_files() -> None:
    storage = tree()
    storage.remove_file(run("a.txt"))
    assert codes(storage) == ["file_missing"]
    assert codes(tree(), disk_path="o/c/ns/other") == ["collection_dir_missing", "dir_unrecorded"]
    namespaces = [ExpectedDirectory("c.gone", "o/c/gone")]
    findings = check(tree(), namespaces, [], START)
    assert [(f.code, f.severity) for f in findings] == [("namespace_dir_missing", Severity.ERROR)]


def test_changed_and_unrecorded_files() -> None:
    storage = tree()
    storage.write_bytes(run("a.txt"), b"ALPHA", 0o644)
    assert codes(storage) == []
    assert codes(storage, hash_files=True) == ["file_changed"]
    storage.write_bytes(run("a.txt"), b"longer", 0o644)
    storage.write_bytes(run("stray"), b"x", 0o644)
    assert codes(storage) == ["file_changed", "file_unrecorded"]


def test_unrecorded_directories_and_stale_sidecars() -> None:
    storage = tree()
    storage.make_directory(LakePath.of("o", "c", "ns", "mystery"), DIRECTORY_MODE)
    assert codes(storage, sidecar=b"other") == ["dir_unrecorded", "sidecar_stale"]


def test_informational_findings() -> None:
    storage = tree()
    storage.write_bytes(run("b.huron-part"), b"x", 0o644)
    later = START + timedelta(days=40)
    assert codes(storage, now=later, state="incomplete") == ["incomplete", "stale_part"]
    draft = {"state": "draft", "disk_path": None}
    assert codes(tree(), **draft) == ["dir_unrecorded"]
    assert codes(tree(), now=later, **draft) == ["dir_unrecorded", "stale_draft"]


def test_findings_render_for_output() -> None:
    finding = check(tree(), [], expected(files={})[1], START)[0]
    assert finding.as_dict() == {
        "code": "file_unrecorded",
        "severity": "warning",
        "identifier": "c.ns.run",
        "path": "o/c/ns/run/a.txt",
        "detail": "",
    }


def test_findings_name_lake_paths() -> None:
    storage = tree()
    storage.remove_file(run("a.txt"))
    storage.make_directory(LakePath.of("o", "c", "ns", "mystery"), DIRECTORY_MODE)
    namespaces, collections = expected(sidecar=b"other")
    found = {(f.code, f.path) for f in check(storage, namespaces, collections, START)}
    assert found == {
        ("file_missing", "o/c/ns/run/a.txt"),
        ("dir_unrecorded", "o/c/ns/mystery"),
        ("sidecar_stale", "o/c/ns/run/metadata.json"),
    }


class VanishingFiles(MemoryStorage):
    """A lake whose files are gone by the time the check opens them."""

    def open_file(self, location: LakePath) -> None:
        return None


def test_a_hash_of_a_file_gone_since_the_walk_is_a_change() -> None:
    storage = VanishingFiles(ROOT)
    storage.nodes = tree().nodes
    assert codes(storage, hash_files=True) == ["file_changed"]
