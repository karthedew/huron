"""The input of the provision commands from the service configuration file."""

from pathlib import Path

import pytest

from huron.applications.cli.errors import UsageError
from huron.applications.cli.mount import Site
from huron.applications.cli.provisioning import Provisioning, below_lake_path, from_file
from huron.core.storage import LakePath, Marker, OrganizationPlace
from huron.core.storage.provision import OrganizationTarget, Owner

LAKE = Path("/data1/huron")
INSTANCE = "0192b6a0-0000-7000-8000-000000000001"
GROUPS = {"huron": 4242}
VALID = f"""\
store: postgres
instance_id: {INSTANCE}
lake_path: /data1/huron
service_uid: 1000700000
service_group: huron
organizations:
  - name: helio
    display_name: Heliophysics
    groups: {{org_admin: [helio-org-admins]}}
    root: /data1/huron/roots
  - name: noaa
"""


def written(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "huron.yaml"
    path.write_text(text)
    return path


def test_the_file_gives_the_instance_the_organizations_and_the_owner(tmp_path: Path) -> None:
    found = from_file(written(tmp_path, VALID), LAKE, GROUPS.get)
    assert found == Provisioning(
        INSTANCE,
        (
            Site("helio", Path("/data1/huron/roots"), rooted=True, declared=True),
            Site("noaa", LAKE, rooted=False, declared=True),
        ),
        1000700000,
        4242,
    )
    assert found.owner(None, None) == Owner(1000700000, 4242)


def test_a_file_without_organizations_or_owner_gives_none(tmp_path: Path) -> None:
    found = from_file(written(tmp_path, f"instance_id: {INSTANCE}\n"), LAKE, GROUPS.get)
    assert (found.sites, found.uid, found.gid) == ((), None, None)


def test_a_null_lake_path_service_group_or_root_is_the_same_as_no_value(tmp_path: Path) -> None:
    text = (
        f"instance_id: {INSTANCE}\nlake_path: null\nservice_group: null\n"
        "organizations: [{name: noaa, root: null}]\n"
    )
    found = from_file(written(tmp_path, text), LAKE, GROUPS.get)
    assert (found.sites, found.uid, found.gid) == (
        (Site("noaa", LAKE, rooted=False, declared=True),),
        None,
        None,
    )


def test_a_service_group_that_this_machine_does_not_know_gives_no_gid(tmp_path: Path) -> None:
    found = from_file(written(tmp_path, VALID), LAKE, {}.get)
    assert found.gid is None
    assert found.owner(None, 4343) == Owner(1000700000, 4343)


def test_a_service_group_of_digits_in_quotes_is_a_group_name(tmp_path: Path) -> None:
    text = f"instance_id: {INSTANCE}\nservice_group: '1234'\n"
    assert from_file(written(tmp_path, text), LAKE, {"1234": 77}.get).gid == 77


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("- a list\n", "{path} does not contain a YAML mapping"),
        ("instance_id: [1\n", "{path} is not valid YAML"),
        ("instance_id: not-a-uuid\n", "{path}: instance_id must be a UUID"),
        ("store: memory\n", "{path}: instance_id must be a UUID"),
        (
            f"instance_id: {INSTANCE}\nlake_path: /elsewhere\n",
            "{path} sets lake_path /elsewhere, but the lake path on this machine is /data1/huron",
        ),
        (
            f"instance_id: {INSTANCE}\norganizations: helio\n",
            "{path}: organizations must be a list of mappings",
        ),
        (
            f"instance_id: {INSTANCE}\norganizations: [helio]\n",
            "{path}: organizations must be a list of mappings",
        ),
        (
            f"instance_id: {INSTANCE}\norganizations: [{{name: Bad Name}}]\n",
            "{path}: 'Bad Name' breaks the naming rule segment",
        ),
        (
            f"instance_id: {INSTANCE}\norganizations: [{{name: geo, root: data}}]\n",
            "{path}: organization 'geo': root must be an absolute, normalized path",
        ),
        (
            f"instance_id: {INSTANCE}\norganizations: [{{name: geo}}, {{name: geo}}]\n",
            "{path}: the service configuration declares organization 'geo' twice",
        ),
        (
            f"instance_id: {INSTANCE}\nservice_uid: -1\n",
            "{path}: service_uid must be a number of 0 or more",
        ),
        (
            f"instance_id: {INSTANCE}\nservice_uid: root\n",
            "{path}: service_uid must be a number of 0 or more",
        ),
        (
            f"instance_id: {INSTANCE}\nservice_uid: true\n",
            "{path}: service_uid must be a number of 0 or more",
        ),
        (
            f"instance_id: {INSTANCE}\nservice_uid: '1000'\n",
            "{path}: service_uid must be a number of 0 or more",
        ),
        ("instance_id: null\n", "{path}: instance_id must be a UUID"),
        (
            f"instance_id: {INSTANCE}\norganizations: null\n",
            "{path}: organizations must be a list of mappings",
        ),
        (
            f"instance_id: {INSTANCE}\norganizations: [{{name: null}}]\n",
            "{path}: the name of each organization must be a string",
        ),
        (
            f"instance_id: {INSTANCE}\nservice_uid: null\n",
            "{path}: service_uid must be a number of 0 or more",
        ),
        (
            "instance_id: 12345678123456781234567812345678\n",
            "{path}: instance_id must be a UUID",
        ),
        (
            f"instance_id: {INSTANCE}\nlake_path: 5\n",
            "{path}: lake_path must be a string",
        ),
        (
            f"instance_id: {INSTANCE}\nservice_group: 1234\n",
            "{path}: service_group must be a string",
        ),
        (
            f"instance_id: {INSTANCE}\norganizations: [{{name: 2024}}]\n",
            "{path}: the name of each organization must be a string",
        ),
        (
            f"instance_id: {INSTANCE}\norganizations: [{{name: geo, root: 5}}]\n",
            "{path}: the root of each organization must be a string",
        ),
    ],
)
def test_a_file_that_breaks_a_rule_is_refused(tmp_path: Path, text: str, message: str) -> None:
    path = written(tmp_path, text)
    with pytest.raises(UsageError) as refused:
        from_file(path, LAKE, GROUPS.get)
    assert refused.value.message.startswith(message.format(path=path))


def test_a_file_that_cannot_be_read_is_refused(tmp_path: Path) -> None:
    with pytest.raises(UsageError) as refused:
        from_file(tmp_path / "missing.yaml", LAKE, GROUPS.get)
    assert refused.value.message == (
        f"the CLI cannot read {tmp_path / 'missing.yaml'}: No such file or directory"
    )


def test_the_owner_needs_a_uid_and_a_gid() -> None:
    known = Provisioning(INSTANCE, (), 1000, None)
    with pytest.raises(UsageError) as refused:
        known.owner(None, None)
    assert (refused.value.message, refused.value.hint) == (
        "the CLI does not know the service user and group",
        "use `--uid <uid>` and `--gid <gid>`",
    )
    assert known.owner(7, 8) == Owner(7, 8)


def test_the_targets_name_each_chosen_organization_below_the_lake_path() -> None:
    sites = (
        Site("helio", LAKE / "roots", rooted=True, declared=True),
        Site("noaa", LAKE, rooted=False, declared=True),
    )
    source = Provisioning(INSTANCE, sites, None, None, hint="run `huron get orgs`")
    owner = Owner(1, 2)
    lake, targets = source.targets(LAKE, "http://api", owner, None)
    assert lake == Marker(1, "http://api", INSTANCE)
    assert targets == [
        OrganizationTarget(
            OrganizationPlace("helio", LakePath.of("roots"), own_marker=True),
            Marker(1, "http://api", INSTANCE, "helio"),
            owner,
        ),
        OrganizationTarget(
            OrganizationPlace("noaa", LakePath(), own_marker=True),
            Marker(1, "http://api", INSTANCE, "noaa"),
            owner,
        ),
    ]
    assert [t.place.name for t in source.targets(LAKE, "http://api", owner, "noaa")[1]] == ["noaa"]
    with pytest.raises(UsageError) as refused:
        source.chosen("geo")
    assert (refused.value.message, refused.value.hint) == (
        "the service configuration does not declare organization geo",
        "run `huron get orgs`",
    )


def test_a_root_outside_the_lake_path_is_refused() -> None:
    assert below_lake_path(LAKE, Site("helio", LAKE / "a" / "b", rooted=True)) == LakePath.of(
        "a", "b"
    )
    with pytest.raises(UsageError) as refused:
        below_lake_path(LAKE, Site("helio", Path("/elsewhere"), rooted=True))
    assert refused.value.message == (
        "the root /elsewhere of organization helio is not below the lake path /data1/huron"
    )
    assert refused.value.hint == (
        "set `mount_prefix` to the directory where this machine mounts `lake_path`"
    )
