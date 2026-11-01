"""Service settings: the YAML configuration file, its strictness and its precedence."""

import json
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from huron.applications.api.settings import CONFIG_FILE_VARIABLE, Settings
from huron.core.lake.organizations.declarations import DeclaredOrganization
from huron.core.lake.organizations.models import OrganizationGroups
from tests.support.api import INSTANCE_ID

REQUIRED = {
    "HURON_INSTANCE_ID": str(INSTANCE_ID),
    "HURON_ISSUER": "https://huron.test",
    "HURON_COMPANY_ISSUER": "https://company.test",
    "HURON_COMPANY_AUDIENCE": "huron",
    "HURON_GROUP_DIRECTORY_URL": "https://groups.test",
    "HURON_PLATFORM_ADMIN_GROUP": "admins",
}

FILE = """\
instance_id: 0192b6a0-0000-7000-8000-0000000000ff
issuer: https://file.test
company_issuer: https://company.test
company_audience: huron
group_directory_url: https://groups.test
platform_admin_group: file-admins
pool_size: 3
organizations:
  - name: helio
    display_name: Heliophysics
    groups:
      org_admin: [helio-org-admins]
      catalog_admin: [helio-catalog-admins]
      contributor: [helio-contributors, helio-contributors]
      reader: [helio-readers, helio-guests]
    root: /data1/huron
  - {name: geo, display_name: Geoscience, groups: {org_admin: [geo-org-admins]}, root: /data2/huron,
     export: "nfs2:/export/geo"}
"""


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """No ``HURON_*`` variable leaks into these tests."""
    import os

    for name in list(os.environ):
        if name.startswith("HURON_"):
            monkeypatch.delenv(name)


def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str) -> Path:
    path = tmp_path / "huron.yaml"
    path.write_text(text)
    monkeypatch.setenv(CONFIG_FILE_VARIABLE, str(path))
    return path


def test_the_file_supplies_settings_and_declares_organizations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config(tmp_path, monkeypatch, FILE)
    settings = Settings()  # type: ignore[call-arg]
    assert settings.instance_id == uuid.UUID("0192b6a0-0000-7000-8000-0000000000ff")
    assert (settings.pool_size, settings.platform_admin_group) == (3, "file-admins")
    declarations = settings.declarations
    assert declarations.managed
    groups = OrganizationGroups(
        org_admin=("helio-org-admins",),
        catalog_admin=("helio-catalog-admins",),
        contributor=("helio-contributors",),
        reader=("helio-guests", "helio-readers"),
    )
    assert declarations.get("helio") == DeclaredOrganization(
        "helio", "Heliophysics", "", groups, "/data1/huron"
    )
    geo = declarations.get("geo")
    assert geo is not None and geo.path == "/data2/huron/geo" and geo.export == "nfs2:/export/geo"
    assert geo.groups == OrganizationGroups(org_admin=("geo-org-admins",))


def test_an_organization_without_groups_declares_none(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("HURON_ORGANIZATIONS", json.dumps([{"name": "bare", "groups": {}}]))
    declared = Settings().declarations.get("bare")  # type: ignore[call-arg]
    assert declared is not None and declared.groups == OrganizationGroups()


def test_the_removed_admin_groups_key_names_its_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)
    config(tmp_path, monkeypatch, "organizations:\n  - {name: helio, admin_groups: [a]}\n")
    with pytest.raises(ValidationError, match=r"admin_groups.*groups\.org_admin"):
        Settings()  # type: ignore[call-arg]


def test_environment_variables_win_over_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config(tmp_path, monkeypatch, FILE)
    monkeypatch.setenv("HURON_POOL_SIZE", "7")
    monkeypatch.setenv("HURON_DATABASE_URL", "postgresql://secret")
    monkeypatch.setenv("HURON_ORGANIZATIONS", json.dumps([{"name": "only"}]))
    settings = Settings()  # type: ignore[call-arg]
    assert (settings.pool_size, settings.database_url) == (7, "postgresql://secret")
    assert [d.name for d in settings.declarations] == ["only"]
    assert settings.issuer == "https://file.test"


def test_defaults_apply_below_the_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config(tmp_path, monkeypatch, FILE)
    settings = Settings()  # type: ignore[call-arg]
    assert (settings.store, settings.audience, settings.log_level) == ("postgres", "huron", "INFO")


def test_without_a_file_or_list_the_service_is_unmanaged(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)
    settings = Settings()  # type: ignore[call-arg]
    assert settings.organizations is None
    assert not settings.declarations.managed


def test_an_empty_list_is_managed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)
    config(tmp_path, monkeypatch, "organizations: []\n")
    settings = Settings()  # type: ignore[call-arg]
    assert settings.declarations.managed
    assert list(settings.declarations) == []


def test_an_empty_file_sets_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)
    config(tmp_path, monkeypatch, "")
    assert not Settings().declarations.managed  # type: ignore[call-arg]


def test_an_unknown_top_level_key_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)
    config(tmp_path, monkeypatch, "organisations: []\n")
    with pytest.raises(ValueError, match="organisations"):
        Settings()  # type: ignore[call-arg]


def test_an_organizations_key_without_a_list_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)
    config(tmp_path, monkeypatch, "organizations:\n#  - {name: helio, root: /data1/huron}\n")
    with pytest.raises(ValueError, match="organizations has no list"):
        Settings()  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "text",
    [
        "organizations: [{name: helio}]\norganizations: [{name: geo}]\n",
        "organizations:\n  - {name: helio, root: /data1/huron, root: /data2/huron}\n",
    ],
)
def test_a_key_given_twice_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str
) -> None:
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)
    config(tmp_path, monkeypatch, text)
    with pytest.raises(ValueError, match="twice"):
        Settings()  # type: ignore[call-arg]


def test_a_missing_file_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CONFIG_FILE_VARIABLE, str(tmp_path / "absent.yaml"))
    with pytest.raises(ValueError, match="not a file"):
        Settings()  # type: ignore[call-arg]


def test_a_file_that_is_not_a_mapping_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config(tmp_path, monkeypatch, "- just\n- a list\n")
    with pytest.raises(ValueError, match="mapping"):
        Settings()  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("organizations", "message"),
    [
        ([{"name": "helio"}, {"name": "helio"}], "declares organization .helio. twice"),
        ([{"name": "Bad Name"}], "naming rule"),
        ([{"name": "helio", "root": "data1"}], "absolute"),
        ([{"name": "helio", "groups": {"org_admin": [" x"]}}], "groups.org_admin.*white space"),
        ([{"name": "helio", "groups": {"reader": [""]}}], "groups.reader.*white space"),
        ([{"name": "helio", "groups": {"readers": ["x"]}}], "unknown roles: readers"),
        ([{"name": "helio", "groups": {"platform_admin": ["x"]}}], "unknown roles"),
        ([{"name": "helio", "groups": ["x"]}], "groups"),
        ([{"name": "helio", "groups": {"reader": "x"}}], "groups.reader"),
        ([{"name": "helio", "rooot": "/data1"}], "rooot"),
    ],
)
def test_invalid_organizations_fail(
    monkeypatch: pytest.MonkeyPatch, organizations: list[dict[str, object]], message: str
) -> None:
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("HURON_ORGANIZATIONS", json.dumps(organizations))
    with pytest.raises(ValidationError, match=message):
        Settings()  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("given", "kept"),
    [("debug", "DEBUG"), ("Info", "INFO"), ("WARNING", "WARNING"), ("error", "ERROR")],
)
def test_the_log_level_is_read_in_any_case(
    monkeypatch: pytest.MonkeyPatch, given: str, kept: str
) -> None:
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("HURON_LOG_LEVEL", given)
    assert Settings().log_level == kept  # type: ignore[call-arg]


def test_the_file_sets_the_log_level(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config(tmp_path, monkeypatch, FILE + "log_level: critical\n")
    assert Settings().log_level == "CRITICAL"  # type: ignore[call-arg]


@pytest.mark.parametrize("level", ["verbose", "WARN", "", "info "])
def test_an_unknown_log_level_fails(monkeypatch: pytest.MonkeyPatch, level: str) -> None:
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("HURON_LOG_LEVEL", level)
    with pytest.raises(ValidationError, match="log_level"):
        Settings()  # type: ignore[call-arg]
