"""The dataset lifecycle vocabulary and its one live consumer."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from huron.pkg.catalog.lifecycle import DatasetLifecycle
from huron.pkg.rawstore import PosixRawStore
from huron.pkg.rbac import Visibility
from huron.service.api.repository import HierarchyRepository, request_sha256
from huron.service.api.stores import IdempotencyClaim, InMemoryHierarchyStore, InMemoryRbacStore

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


def _claim(operation: str, *parts: str | None, key: str) -> IdempotencyClaim:
    """Build an idempotency claim staked by ``tester`` over one operation's digest parts."""
    return IdempotencyClaim(
        principal="tester", key=key, request_sha256=request_sha256(operation, *parts)
    )


async def test_created_dataset_is_active(tmp_path: Path) -> None:
    """A freshly created dataset's lifecycle state is ACTIVE, both as enum member and as string."""
    repository = HierarchyRepository(
        PosixRawStore(str(tmp_path / "raw")),
        InMemoryHierarchyStore(),
        classification_vocabulary=("internal",),
        rbac_store=InMemoryRbacStore(),
    )
    organization = await repository.create_organization(
        slug="acme",
        title="Acme",
        description="",
        claim=_claim("organization", "acme", "Acme", "", key="org-1"),
    )
    project = await repository.create_project(
        organization.id,
        Visibility.ALL,
        slug="widgets",
        title="Widgets",
        description="",
        data_classification="internal",
        claim=_claim(
            "project", str(organization.id), "widgets", "Widgets", "", "internal", key="proj-1"
        ),
    )
    dataset = await repository.create_dataset(
        project.id,
        Visibility.ALL,
        slug="orders",
        title="Orders",
        description="",
        profile_name="tabular",
        profile_version="1",
        claim=_claim(
            "dataset",
            str(project.id),
            "orders",
            "Orders",
            "",
            "tabular",
            "1",
            "raw",
            key="ds-1",
        ),
    )
    assert dataset.lifecycle_state is DatasetLifecycle.ACTIVE
    assert dataset.lifecycle_state == "ACTIVE"
