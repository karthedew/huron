"""Drift findings, one case per finding code."""

import hashlib
from datetime import timedelta
from pathlib import Path

from huron.core.storage import DirectoryKind, EffectiveGroups, plan
from huron.core.storage.check import ExpectedCollection, ExpectedDirectory, Severity, check
from huron.core.storage.memory import MemoryStorage
from huron.pkg.fs.acl import Acl
from tests.support.clock import START

ROOT = Path("/share")
GROUPS = EffectiveGroups(contributor=("contrib",))
NS_PLAN = plan(DirectoryKind.NAMESPACE_WITH_COLLECTIONS, GROUPS)
COL_PLAN = plan(DirectoryKind.COLLECTION, GROUPS)
SIDECAR = b'{"huron":1}\n'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tree() -> MemoryStorage:
    storage = MemoryStorage(ROOT)
    storage.ensure_directory(ROOT / "o", NS_PLAN)
    storage.ensure_directory(ROOT / "o" / "c", NS_PLAN)
    storage.ensure_directory(ROOT / "o" / "c" / "ns", NS_PLAN)
    storage.ensure_directory(ROOT / "o" / "c" / "ns" / "run", COL_PLAN)
    storage.write_bytes(ROOT / "o" / "c" / "ns" / "run" / "a.txt", b"alpha")
    storage.write_bytes(ROOT / "o" / "c" / "ns" / "run" / "metadata.json", SIDECAR)
    storage.ensure_directory(ROOT / "o" / "c" / "ns" / "run" / "empty", COL_PLAN)
    return storage


def expected(**overrides: object) -> tuple[list[ExpectedDirectory], list[ExpectedCollection]]:
    collection = {
        "identifier": "c.ns.run",
        "state": "active",
        "created_at": START,
        "disk_path": "o/c/ns/run",
        "plan": COL_PLAN,
        "files": {"a.txt": {"rel_path": "a.txt", "size": 5, "sha256": sha(b"alpha")}},
        "sidecar": SIDECAR,
        **overrides,
    }
    return (
        [ExpectedDirectory("c", "o/c", NS_PLAN), ExpectedDirectory("c.ns", "o/c/ns", NS_PLAN)],
        [ExpectedCollection(**collection)],  # type: ignore[arg-type]
    )


def codes(
    storage: MemoryStorage, *, hash_files: bool = False, now=START, **overrides: object
) -> list[str]:  # type: ignore[no-untyped-def]
    namespaces, collections = expected(**overrides)
    return [
        f.code for f in check(storage, ROOT, namespaces, collections, now, hash_files=hash_files)
    ]


def test_a_clean_tree_has_no_findings() -> None:
    assert codes(tree()) == []


def test_missing_directories_and_files() -> None:
    storage = tree()
    storage.remove_file(ROOT / "o" / "c" / "ns" / "run" / "a.txt")
    assert codes(storage) == ["file_missing"]
    assert codes(tree(), disk_path="o/c/ns/other") == ["collection_dir_missing", "dir_unrecorded"]
    namespaces = [ExpectedDirectory("c.gone", "o/c/gone", NS_PLAN)]
    findings = check(tree(), ROOT, namespaces, [], START)
    assert [(f.code, f.severity) for f in findings] == [("namespace_dir_missing", Severity.ERROR)]


def test_changed_and_unrecorded_files() -> None:
    storage = tree()
    storage.write_bytes(ROOT / "o" / "c" / "ns" / "run" / "a.txt", b"ALPHA")
    assert codes(storage) == []
    assert codes(storage, hash_files=True) == ["file_changed"]
    storage.write_bytes(ROOT / "o" / "c" / "ns" / "run" / "a.txt", b"longer")
    storage.write_bytes(ROOT / "o" / "c" / "ns" / "run" / "stray", b"x")
    assert codes(storage) == ["file_changed", "file_unrecorded"]


def test_unrecorded_directories_stale_sidecars_and_acl_drift() -> None:
    storage = tree()
    storage.ensure_directory(ROOT / "o" / "c" / "ns" / "mystery", COL_PLAN)
    storage.nodes[ROOT / "o" / "c" / "ns"].acl = Acl()
    assert codes(storage, sidecar=b"other") == ["acl_drift", "dir_unrecorded", "sidecar_stale"]


def test_informational_findings() -> None:
    storage = tree()
    storage.write_bytes(ROOT / "o" / "c" / "ns" / "run" / "b.huron-part", b"x")
    later = START + timedelta(days=40)
    assert codes(storage, now=later, state="incomplete") == ["incomplete", "stale_part"]
    draft = {"state": "draft", "disk_path": None}
    assert codes(tree(), **draft) == ["dir_unrecorded"]
    assert codes(tree(), now=later, **draft) == ["dir_unrecorded", "stale_draft"]


def test_unreadable_acls_are_skipped_and_plans_are_optional() -> None:
    storage = tree()

    def refuse(path: Path) -> Acl:
        from huron.core.storage import StorageError

        raise StorageError("no", {})

    storage.read_acl = refuse  # type: ignore[method-assign]
    namespaces = [ExpectedDirectory("c", "o/c"), ExpectedDirectory("c.ns", "o/c/ns")]
    assert check(storage, ROOT, namespaces, expected()[1], START) == []
    finding = check(tree(), ROOT, [], expected(files={})[1], START)[0]
    assert finding.as_dict()["code"] == "file_unrecorded"
