"""``LakePath`` and the rule ``lake_name``."""

import pytest

from huron.core.storage import LakePath
from huron.pkg.errors import HuronError
from huron.schema.naming import check_lake_name

LONG = "a" * 256


@pytest.mark.parametrize(
    "text", ["", ".", "..", "a//b", "/a", "a/", "a/\0b", f"a/{LONG}", "a/../b"]
)
def test_parse_refuses_a_path_that_is_not_a_lake_path(text: str) -> None:
    with pytest.raises(HuronError) as refused:
        LakePath.parse(text)
    assert (refused.value.code, refused.value.status) == ("NAME_INVALID", 422)
    assert refused.value.context["rule"] == "lake_name"


@pytest.mark.parametrize("name", ["", ".", "..", "a/b", "\0", LONG, "\ud800"])
def test_of_refuses_a_name_that_is_not_a_lake_name(name: str) -> None:
    with pytest.raises(HuronError) as refused:
        LakePath.of("ok", name)
    assert (refused.value.code, refused.value.status) == ("NAME_INVALID", 422)


def test_a_name_of_255_bytes_is_a_lake_name() -> None:
    assert check_lake_name("é" * 127 + "a") == "é" * 127 + "a"
    assert LakePath.of("a" * 255).name == "a" * 255


def test_joinpath_checks_each_name() -> None:
    with pytest.raises(HuronError):
        LakePath.of("a").joinpath("..")
    assert LakePath.of("a").joinpath("b", "c") == LakePath.parse("a/b/c")


def test_parent_name_and_the_root() -> None:
    path = LakePath.parse("helio/sun/run7")
    assert (path.parent, path.name) == (LakePath.of("helio", "sun"), "run7")
    assert (LakePath().parent, LakePath().name) == (LakePath(), "")


def test_relative_to_and_str_give_the_api_form() -> None:
    path = LakePath.parse("data/helio/sun")
    assert str(path) == "data/helio/sun"
    assert str(LakePath()) == ""
    assert path.relative_to(LakePath.of("data")) == "helio/sun"
    assert path.relative_to(path) == ""
    with pytest.raises(ValueError, match="not below"):
        path.relative_to(LakePath.of("geo"))
