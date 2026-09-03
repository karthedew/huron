"""The dataset lifecycle vocabulary and its one live consumer."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from huron.pkg.catalog.lifecycle import DatasetLifecycle
from huron.pkg.rawstore import PosixRawStore
from huron.service.api.repository import HierarchyRepository

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def test_member_set_is_exactly_active_retired_superseded() -> None:
    """``DatasetLifecycle`` has exactly three members: ACTIVE, RETIRED and SUPERSEDED."""
    assert {member.name for member in DatasetLifecycle} == {"ACTIVE", "RETIRED", "SUPERSEDED"}


def test_each_member_value_equals_its_name() -> None:
    """Every ``DatasetLifecycle`` member's value equals its own name."""
    for member in DatasetLifecycle:
        assert member.value == member.name


def test_created_dataset_is_active(tmp_path: Path) -> None:
    """A freshly created dataset's lifecycle state is ACTIVE, both as enum member and as string."""
    repository = HierarchyRepository(
        PosixRawStore(str(tmp_path / "raw")), classification_vocabulary=("internal",)
    )
    organization = repository.create_organization(
        slug="acme",
        title="Acme",
        description="",
        idempotency_key="org-1",
    )
    project = repository.create_project(
        organization.id,
        slug="widgets",
        title="Widgets",
        description="",
        data_classification="internal",
        idempotency_key="proj-1",
    )
    dataset = repository.create_dataset(
        project.id,
        slug="orders",
        title="Orders",
        description="",
        profile_name="tabular",
        profile_version="1",
        idempotency_key="ds-1",
    )
    assert dataset.lifecycle_state is DatasetLifecycle.ACTIVE
    assert dataset.lifecycle_state == "ACTIVE"
