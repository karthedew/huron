"""Directory document validation and one-request HTTP failure contracts."""

from __future__ import annotations

from dataclasses import replace

import httpx
import pytest

from huron.core.foundation.errors import DependencyUnavailable
from huron.core.security.broker import HttpGroupDirectory, parse_groups_response
from tests.fakes.ldap_groups import FakeGroupDirectory, Identities

pytestmark = pytest.mark.unit
TEMPLATE = "https://groups.test/users/{username}/groups"


@pytest.mark.parametrize("groups", [[], ["one", "one", "two"], ["x" * 256, "科学", " Group "]])
def test_valid_groups_remain_verbatim(groups: list[str]) -> None:
    """Valid names, empty membership and duplicate collapse ignore unrelated keys."""
    assert parse_groups_response({"groups": groups, "extra": True}) == frozenset(groups)


@pytest.mark.parametrize("body", [None, [], "groups", {}, {"groups": None}, {"groups": "one"}])
def test_invalid_document(body: object) -> None:
    """Only an object containing a groups array can describe membership."""
    with pytest.raises(ValueError, match="groups"):
        parse_groups_response(body)


@pytest.mark.parametrize(
    "group", [None, 1, False, {}, [], "", "x" * 257, "a\x00", "a\x7f", "a\x85"]
)
def test_invalid_element_names_its_index(group: object) -> None:
    """Type, length and Unicode control boundaries identify the offending element."""
    with pytest.raises(ValueError, match=r"groups\[1\]"):
        parse_groups_response({"groups": ["valid", group]})


@pytest.mark.parametrize("username", ["karl", "absent"])
async def test_known_and_unknown_users(
    fake_groups: FakeGroupDirectory,
    fake_groups_transport: httpx.ASGITransport,
    identities: Identities,
    username: str,
) -> None:
    """The adapter preserves known membership and distinguishes an unknown user."""
    async with httpx.AsyncClient(transport=fake_groups_transport) as http:
        result = await HttpGroupDirectory(http, url_template=TEMPLATE).groups_for(username)
        assert not http.is_closed
    assert result == (frozenset(identities.user(username).groups) if username == "karl" else None)
    assert fake_groups.requests == (username,)


@pytest.mark.parametrize(
    "failure,reason",
    [
        (500, "status"),
        (401, "status"),
        (302, "status"),
        (204, "status"),
        ("timeout", "timeout"),
        ("unreachable", "unreachable"),
        ("malformed", "malformed"),
    ],
)
async def test_failures_are_not_membership(
    fake_groups: FakeGroupDirectory,
    fake_groups_transport: httpx.ASGITransport,
    failure: str | int,
    reason: str,
) -> None:
    """Every failed lookup preserves its classification and makes exactly one attempt."""
    fake_groups.inject(failure)
    async with httpx.AsyncClient(transport=fake_groups_transport, follow_redirects=True) as http:
        with pytest.raises(DependencyUnavailable) as caught:
            await HttpGroupDirectory(http, url_template=TEMPLATE).groups_for("karl")
    expected = {"dependency": "group_directory", "reason": reason}
    if isinstance(failure, int):
        expected["status"] = failure
    assert caught.value.context == expected
    assert caught.value.retry_after == 30
    assert fake_groups.requests == ("karl",)


async def test_username_is_url_encoded(identities: Identities) -> None:
    """UPNs arrive decoded at the directory while the wire request encodes the at sign."""
    person = replace(
        identities.user("karl"), id="00000000-0000-4000-8000-000000000000", username="karl@corp"
    )
    directory = FakeGroupDirectory(identities.with_user(person))
    requests = []

    async def observe(request: httpx.Request) -> None:
        requests.append(request)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=directory.app), event_hooks={"request": [observe]}
    ) as http:
        assert await HttpGroupDirectory(http, url_template=TEMPLATE).groups_for(
            person.username
        ) == frozenset(person.groups)
    assert directory.requests == ("karl@corp",)
    assert requests[0].url.raw_path == b"/users/karl%40corp/groups"
    assert requests[0].headers["accept"] == "application/json"


@pytest.mark.parametrize(
    "template",
    [
        "https://host/path#{username}",
        "relative/{username}",
        "ftp://host/{username}",
        "https://host/no-placeholder",
        "https://host/{username}/{username}",
        "https://{username}/groups",
        "https://user:{username}@host/groups",
        "https://host:notaport/{username}",
        "https://host:0/{username}",
        "https://host:99999/{username}",
        "https:///users/{username}",
        "https://[broken/{username}",
        "https://host/\x00/{username}",
        "http://user@/{username}",
    ],
)
async def test_bad_templates_fail_before_io(
    fake_groups: FakeGroupDirectory, fake_groups_transport: httpx.ASGITransport, template: str
) -> None:
    """Unusable URL forms and misplaced placeholders fail at construction."""
    async with httpx.AsyncClient(transport=fake_groups_transport) as http:
        with pytest.raises(ValueError):
            HttpGroupDirectory(http, url_template=template)
    assert fake_groups.requests == ()


@pytest.mark.parametrize("content", [b"not json", b"\xff", b'{"groups":[null]}'])
async def test_invalid_json_is_a_dependency_failure(
    fake_groups: FakeGroupDirectory,
    fake_groups_transport: httpx.ASGITransport,
    content: bytes,
) -> None:
    """Wire-level JSON failures share the malformed-body contract."""
    fake_groups.inject(content)
    async with httpx.AsyncClient(transport=fake_groups_transport) as http:
        with pytest.raises(DependencyUnavailable) as caught:
            await HttpGroupDirectory(http, url_template=TEMPLATE).groups_for("karl")
    assert caught.value.context == {"dependency": "group_directory", "reason": "malformed"}
    assert caught.value.retry_after == 30
    assert fake_groups.requests == ("karl",)
