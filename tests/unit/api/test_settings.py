"""Service settings: the YAML configuration file, its strictness and its precedence."""

import json
import os
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from huron.applications.api.settings import CONFIG_FILE_VARIABLE, Settings
from huron.core.lake.organizations.declarations import DeclaredOrganization
from huron.core.lake.organizations.models import OrganizationGroups
from huron.core.lake.uploads.models import ReceiptMode
from tests.support.api import INSTANCE_ID, settings

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


@pytest.fixture
def required(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """The required variables set; the test sets the lake and upload variables it needs."""
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)
    return monkeypatch


def test_the_lake_and_upload_settings_have_their_defaults(required: pytest.MonkeyPatch) -> None:
    settings = Settings()  # type: ignore[call-arg]
    assert (settings.lake_path, settings.uploads_url) == (None, None)
    assert settings.receipt_mode is ReceiptMode.OPTIONAL
    assert settings.upload_ttl == timedelta(hours=24)
    assert settings.upload_max_size == 0
    assert settings.upload_hook_timeout == timedelta(minutes=15)
    assert settings.removal_interval == timedelta(seconds=60)
    assert settings.sweep_interval == timedelta(minutes=10)
    assert settings.service_uid == os.getuid()
    assert settings.service_group is None


def test_the_lake_and_upload_settings_are_read(required: pytest.MonkeyPatch) -> None:
    values = {
        "HURON_LAKE_PATH": "/data1/huron",
        "HURON_UPLOADS_URL": "https://huron.example.org/files/",
        "HURON_UPLOAD_TTL": "PT12H",
        "HURON_UPLOAD_MAX_SIZE": "1073741824",
        "HURON_UPLOAD_HOOK_TIMEOUT": "1800",
        "HURON_REMOVAL_INTERVAL": "PT30S",
        "HURON_SWEEP_INTERVAL": "300",
        "HURON_SERVICE_UID": "1000700000",
        "HURON_SERVICE_GROUP": "huron-svc",
    }
    for name, value in values.items():
        required.setenv(name, value)
    settings = Settings()  # type: ignore[call-arg]
    assert settings.lake_path == Path("/data1/huron")
    assert settings.uploads_url == "https://huron.example.org/files/"
    assert settings.receipt_mode is ReceiptMode.REQUIRED
    assert settings.upload_ttl == timedelta(hours=12)
    assert settings.upload_max_size == 1 << 30
    assert settings.upload_hook_timeout == timedelta(minutes=30)
    assert settings.removal_interval == timedelta(seconds=30)
    assert settings.sweep_interval == timedelta(minutes=5)
    assert (settings.service_uid, settings.service_group) == (1000700000, "huron-svc")


def test_the_file_sets_the_lake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rooted_in_the_lake = FILE.replace("root: /data2/huron", "root: /data1/huron/geo")
    text = rooted_in_the_lake + "lake_path: /data1/huron\nupload_hook_timeout: PT55M\n"
    config(tmp_path, monkeypatch, text)
    settings = Settings()  # type: ignore[call-arg]
    assert settings.lake_path == Path("/data1/huron")
    assert settings.upload_hook_timeout == timedelta(minutes=55)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("HURON_UPLOAD_HOOK_TIMEOUT", "3301"),
        ("HURON_UPLOAD_HOOK_TIMEOUT", "PT1H"),
        ("HURON_UPLOAD_HOOK_TIMEOUT", "0"),
        ("HURON_UPLOAD_TTL", "0"),
        ("HURON_REMOVAL_INTERVAL", "-1"),
        ("HURON_SWEEP_INTERVAL", "0"),
        ("HURON_UPLOAD_MAX_SIZE", "-1"),
        ("HURON_SERVICE_UID", "-1"),
        ("HURON_LAKE_PATH", "data1/huron"),
        ("HURON_LAKE_PATH", "/data1/../huron"),
    ],
)
def test_an_out_of_range_lake_or_upload_setting_fails(
    required: pytest.MonkeyPatch, name: str, value: str
) -> None:
    required.setenv(name, value)
    with pytest.raises(ValidationError, match=name.removeprefix("HURON_").lower()):
        Settings()  # type: ignore[call-arg]


def test_uploads_url_without_lake_path_fails_startup(required: pytest.MonkeyPatch) -> None:
    required.setenv("HURON_UPLOADS_URL", "https://huron.example.org/files/")
    with pytest.raises(ValidationError, match="uploads_url needs lake_path"):
        Settings()  # type: ignore[call-arg]


def test_receipts_are_required_with_a_lake_and_optional_without(
    required: pytest.MonkeyPatch,
) -> None:
    assert Settings().receipt_mode is ReceiptMode.OPTIONAL  # type: ignore[call-arg]
    required.setenv("HURON_LAKE_PATH", "/data1/huron")
    assert Settings().receipt_mode is ReceiptMode.REQUIRED  # type: ignore[call-arg]


@pytest.mark.parametrize("root", ["/data1/huron", "/data1/huron/geo", "/data1/huron/a/b"])
def test_a_root_at_or_below_lake_path_loads(root: str) -> None:
    loaded = settings(lake_path="/data1/huron", organizations=[{"name": "geo", "root": root}])
    declared = loaded.declarations.get("geo")
    assert declared is not None and declared.root == root


def test_an_organization_without_a_root_loads_with_a_lake() -> None:
    loaded = settings(lake_path="/data1/huron", organizations=[{"name": "geo"}])
    assert loaded.declarations.share_root("geo") is None


@pytest.mark.parametrize("root", ["/data2/huron", "/data1/huron2", "/data1", "/"])
def test_a_root_outside_lake_path_fails_startup(root: str) -> None:
    organizations = [{"name": "helio", "root": "/data1/huron"}, {"name": "geo", "root": root}]
    message = f"The root {root} of organization geo is not below lake_path /data1/huron"
    with pytest.raises(ValidationError, match=message):
        settings(lake_path="/data1/huron", organizations=organizations)


def test_without_lake_path_a_root_can_be_anywhere() -> None:
    loaded = settings(organizations=[{"name": "geo", "root": "/data2/huron"}])
    assert loaded.declarations.share_root("geo") == "/data2/huron"


def test_mount_prefix_is_an_unknown_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config(tmp_path, monkeypatch, "mount_prefix: /projects/huron\n")
    with pytest.raises(ValueError, match="unknown settings: mount_prefix"):
        settings()
