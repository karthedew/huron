"""The metadata walkthrough and merge diffs."""

from huron.applications.cli.walkthrough import fill, merge_diff, review
from huron.schema.loader import load_document
from tests.fakes.prompter import ScriptedPrompter

SCHEMA = {
    "type": "object",
    "required": ["title", "runs", "kind"],
    "properties": {
        "title": {"type": "string", "minLength": 2, "description": "Short name"},
        "runs": {"type": "integer", "minimum": 1},
        "kind": {"type": "string", "enum": ["a", "b"]},
        "ratio": {"type": "number", "default": 0.5},
        "public": {"type": "boolean"},
        "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 2},
        "sizes": {"type": "array", "items": {"type": "integer"}},
        "contacts": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name"],
                "properties": {"name": {"type": "string"}},
            },
        },
        "site": {
            "type": "object",
            "required": ["code"],
            "properties": {"code": {"type": "string", "pattern": "^[A-Z]{3}$"}},
        },
        "labels": {"type": "object", "additionalProperties": {"type": "string"}},
        "extra": {"type": "array", "items": {"type": "object"}},
        "blob": {"type": "array", "items": {"type": "boolean"}},
    },
}


def test_required_fields_are_asked_and_bad_answers_rejected() -> None:
    prompter = ScriptedPrompter(
        [
            "x",
            "Run 7",  # title: too short, then accepted
            "many",
            "0",
            "3",  # runs: not an integer, below minimum, then 3
            "b",  # kind
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            False,  # optionals skipped
        ]
    )
    document = fill(prompter, SCHEMA, {"keep": 1})
    assert document == {"keep": 1, "title": "Run 7", "runs": 3, "kind": "b"}
    assert [value for value, _ in prompter.rejected] == ["x", "many", "0"]
    assert "Short name" in prompter.asked[0]


def test_optional_fields_of_every_shape() -> None:
    prompter = ScriptedPrompter(
        [
            None,
            None,
            None,  # required: keep current defaults
            True,
            "maybe",
            "true, false",  # blob: JSON booleans
            True,
            True,
            True,
            "Ada",
            False,  # contacts: keep existing, add Ada, stop
            False,  # extra
            True,
            "bad",
            "k=v, z=w",  # labels: key=value
            True,
            True,  # public: yes
            True,
            None,  # ratio: default 0.5
            True,
            "abc",
            "ABC",  # site.code: pattern
            True,
            "1, x",
            "1, 2",  # sizes: bad integer, then two
            True,
            "a, b, c",
            "a, b",  # tags: too many, then two
        ]
    )
    current = {"title": "Old title", "runs": 2, "kind": "a", "contacts": [{"name": "Bo"}]}
    document = fill(prompter, SCHEMA, current)
    assert document["ratio"] == 0.5 and document["public"] is True
    assert document["tags"] == ["a", "b"] and document["sizes"] == [1, 2]
    assert document["contacts"] == [{"name": "Bo"}, {"name": "Ada"}]
    assert document["site"] == {"code": "ABC"} and document["labels"] == {"k": "v", "z": "w"}
    assert document["blob"] == [True, False]
    assert review(SCHEMA, document) == []


def test_review_reports_problems_against_the_base_schema() -> None:
    problems = review(load_document("huron-base-v1"), {"title": ""})
    assert {p.rule for p in problems} == {"required", "minLength"}


def test_merge_diff_produces_an_rfc_7396_patch() -> None:
    before = {"a": 1, "b": {"c": 1, "d": 2}, "e": 1, "same": {"x": 1}}
    after = {"a": 2, "b": {"c": 1}, "f": [1], "same": {"x": 1}}
    assert merge_diff(before, after) == {"a": 2, "b": {"d": None}, "e": None, "f": [1]}
    assert merge_diff({"x": {"y": 1}}, {"x": 5}) == {"x": 5}
