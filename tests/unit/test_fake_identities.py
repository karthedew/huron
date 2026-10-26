"""Identity fixture validation and production/test isolation contracts."""

from __future__ import annotations

import ast
import sys
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml

from tests.fakes.ldap_groups import COMPANY_USERNAME, DEFAULT_IDENTITIES, FakeUser, Identities
from tests.lake_tokens import TEST_EPOCH

if TYPE_CHECKING:
    from tests.unit.support import FakeClock

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[2]


def test_shared_people_and_clock(identities: Identities, clock: FakeClock) -> None:
    """The fixture fixes IdP subjects, distinct usernames and the common epoch."""
    assert identities.organization == "Huron Development"
    assert tuple(identities.users) == ("karl", "sam", "rita")
    assert identities.user("karl").groups == ("huron-administrators", "helio-developers")
    assert identities.user("sam").groups == ("helio-developers",)
    assert identities.user("rita").groups == ("helio-readers",)
    for index, user in enumerate(identities.users.values(), start=1):
        assert user.id == f"6f1c1a3e-0000-4000-8000-{index:012}"
        assert user.email == f"{user.username}@company.test"
    assert clock.now() == TEST_EPOCH
    assert COMPANY_USERNAME.pattern == r"[A-Za-z0-9][A-Za-z0-9._@-]{0,127}"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", 2),
        ("version", True),
        ("version", "1"),
        ("version", 1.0),
        ("organization", None),
        ("organization", []),
        ("users", {}),
        ("users", None),
    ],
)
def test_invalid_document_fields_name_the_field(tmp_path: Path, field: str, value: object) -> None:
    """Root fields reject wrong versions and types with useful diagnostics."""
    document = yaml.safe_load(DEFAULT_IDENTITIES.read_text())
    document[field] = value
    path = tmp_path / "identities.yaml"
    path.write_text(yaml.safe_dump(document))
    with pytest.raises(ValueError, match=field):
        Identities.load(path)


@pytest.mark.parametrize("scope", ["root", "user"])
@pytest.mark.parametrize("change", ["missing", "unknown", "non_mapping"])
def test_exact_document_and_user_keys(tmp_path: Path, scope: str, change: str) -> None:
    """Both levels refuse missing, extra and structurally invalid fields."""
    document = yaml.safe_load(DEFAULT_IDENTITIES.read_text())
    target = document if scope == "root" else document["users"][0]
    if change == "missing":
        target.pop("version" if scope == "root" else "email")
    elif change == "unknown":
        target["unexpected"] = "value"
    elif scope == "root":
        document = []
    else:
        document["users"][0] = []
    path = tmp_path / "identities.yaml"
    path.write_text(yaml.safe_dump(document))
    with pytest.raises(ValueError, match="root" if scope == "root" else r"users\[0\]"):
        Identities.load(path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", "not-a-uuid"),
        ("id", 12),
        ("username", 12),
        ("given_name", None),
        ("family_name", False),
        ("email", []),
        ("groups", "readers"),
        ("groups", None),
        ("groups", [12]),
        ("groups", [""]),
        ("groups", ["a" * 257]),
        ("groups", ["a\x00b"]),
        ("groups", ["a\x7fb"]),
        ("groups", ["a\x85b"]),
        ("username", ""),
        ("username", "a" * 129),
        ("username", "_karl"),
        ("username", "a/b"),
        ("username", "a b"),
        ("username", "a%40b"),
        ("username", "a\nb"),
        ("username", "é"),
    ],
)
def test_invalid_user_fields_name_the_entry(tmp_path: Path, field: str, value: object) -> None:
    """Wrong types and invalid identifier or membership boundaries fail closed."""
    document = yaml.safe_load(DEFAULT_IDENTITIES.read_text())
    document["users"][0][field] = value
    path = tmp_path / "identities.yaml"
    path.write_text(yaml.safe_dump(document))
    with pytest.raises(ValueError, match=r"users\[0\]"):
        Identities.load(path)


@pytest.mark.parametrize("field", ["id", "username"])
def test_duplicate_subject_or_username_is_refused(tmp_path: Path, field: str) -> None:
    """A directory cannot contain two people with the same lookup identity."""
    document = yaml.safe_load(DEFAULT_IDENTITIES.read_text())
    document["users"][1][field] = document["users"][0][field]
    path = tmp_path / "identities.yaml"
    path.write_text(yaml.safe_dump(document))
    with pytest.raises(ValueError, match=f"duplicate {field}"):
        Identities.load(path)


@pytest.mark.parametrize("username", ["a", "A" * 128, "karl.schmidt@corp", "a._@-Z9"])
@pytest.mark.parametrize("groups", [[], ["x" * 256], ["scientists", "scientists"], ["科学"]])
def test_username_and_group_boundaries_are_accepted(
    identities: Identities, username: str, groups: list[str]
) -> None:
    """Valid boundary values and empty membership survive immutable construction."""
    user = replace(identities.user("karl"), username=username, groups=groups)
    assert user.username == username
    assert user.groups == tuple(groups)


def test_empty_directory_loads(tmp_path: Path) -> None:
    """An empty directory is a useful explicit mock state."""
    path = tmp_path / "identities.yaml"
    path.write_text("version: 1\norganization: Example\nusers: []\n")
    assert not Identities.load(path).users


def test_values_copy_inputs_and_replacement_preserves_original(identities: Identities) -> None:
    """Directory and membership inputs cannot mutate a published snapshot."""
    groups = ["one"]
    user = replace(identities.user("karl"), groups=groups)
    mapping = {user.username: user}
    snapshot = Identities("Example", mapping)
    mapping.clear()
    groups.append("two")
    assert snapshot.user("karl").groups == ("one",)
    changed = identities.with_user(user)
    assert changed.user("karl") == user
    assert identities.user("karl") != user
    with pytest.raises(TypeError):
        snapshot.users["sam"] = user
    with pytest.raises(FrozenInstanceError):
        user.email = "other@company.test"
    with pytest.raises(FrozenInstanceError):
        snapshot.organization = "Other"
    with pytest.raises(KeyError):
        snapshot.user("absent")
    with pytest.raises(ValueError, match="key differs"):
        Identities("Example", {"sam": user})
    with pytest.raises(ValueError, match="duplicate id"):
        identities.with_user(replace(user, username="another"))


def test_with_user_adds_a_distinct_identity(identities: Identities) -> None:
    """Additional people leave the original fixture untouched."""
    user = FakeUser("00000000-0000-4000-8000-000000000000", "karl@corp", "K", "S", "", ())
    changed = identities.with_user(user)
    assert changed.user("karl@corp") == user
    assert "karl@corp" not in identities.users


def test_src_never_imports_tests() -> None:
    """Production modules never select or import test implementations."""
    for path in (ROOT / "src/huron").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                assert all(alias.name.split(".")[0] != "tests" for alias in node.names), path
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] != "tests", path


def test_groups_fake_has_only_standalone_dependencies() -> None:
    """The compose-loadable module needs neither Huron nor test infrastructure."""
    allowed = sys.stdlib_module_names | {"starlette", "yaml", "httpx"}
    path = ROOT / "tests/fakes/ldap_groups.py"
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            assert all(alias.name.split(".")[0] in allowed for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            assert (node.module or "").split(".")[0] in allowed


def test_user_refuses_non_sequence_membership(identities: Identities) -> None:
    """Direct fixture construction cannot mistake a string for group membership."""
    with pytest.raises(ValueError, match="groups must be a list or tuple"):
        replace(identities.user("karl"), groups="readers")
