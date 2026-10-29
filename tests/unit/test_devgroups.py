"""The development group directory answers like the real one."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "devgroups.py"


def load_module():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("devgroups", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_answers_groups_unknown_users_and_bad_paths(tmp_path: Path) -> None:
    devgroups = load_module()
    mapping = tmp_path / "groups.yaml"
    mapping.write_text("dave: [helio-contributors]\nnobody:\n")
    groups = devgroups.load(mapping)
    assert devgroups.answer(groups, "/users/dave/groups") == (
        200,
        {"groups": ["helio-contributors"]},
    )
    assert devgroups.answer(groups, "/users/nobody/groups") == (200, {"groups": []})
    assert devgroups.answer(groups, "/users/zed/groups") == (404, None)
    assert devgroups.answer(groups, "/other")[0] == 400


def test_the_shipped_mapping_covers_the_realm_users() -> None:
    devgroups = load_module()
    groups = devgroups.load(SCRIPT.parent / "dev-groups.yaml")
    assert set(groups) == {"alice", "bob", "carol", "dave", "erin"}
