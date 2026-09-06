"""``load_schema``'s own guarantees, ahead of any particular document's content rules.

Every other schema test validates a document's fields against an
already-loaded schema; this one is about the loader itself, the one thing
every packaged document shares before its own rules ever apply: a name
that cannot escape the ``documents`` directory, and a document whose top
level is actually a JSON object.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import huron.schema as huron_schema
from huron.schema import load_schema

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("name", ["../escape.json", "sub/dir.json", "manifest-v1", r"a\b.json"])
def test_load_schema_refuses_a_name_with_a_path_separator_or_no_json_suffix(name: str) -> None:
    """A name that could escape the documents directory, or lacks .json, is refused."""
    with pytest.raises(ValueError, match="invalid schema name"):
        load_schema(name)


def test_load_schema_refuses_a_document_whose_top_level_is_not_an_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A packaged document whose top level is not a JSON object is refused."""
    load_schema.cache_clear()
    monkeypatch.setattr(huron_schema, "json", SimpleNamespace(loads=lambda _: []))
    with pytest.raises(ValueError, match="is not an object"):
        load_schema("manifest-v1.json")
