"""What a principal may discover: ``RoleBindingAuthorizer`` and its value types."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from huron.core.security.rules import (
    Binding,
    Classification,
    DatasetVisibility,
    Decision,
    Effect,
    Principal,
    ProjectVisibility,
    RoleBindingAuthorizer,
    Scope,
    ScopeType,
    Visibility,
    decide,
)

pytestmark = pytest.mark.unit


def test_visibility_all_is_unrestricted_and_the_default_construction_is_empty() -> None:
    """``Visibility.ALL`` is the unrestricted sentinel; a bare ``Visibility()`` admits nothing."""
    assert Visibility.ALL.unrestricted is True
    assert Visibility.ALL.organization_ids == frozenset()
    assert Visibility.ALL.project_ids == frozenset()
    assert Visibility.ALL.dataset_ids == frozenset()

    empty = Visibility()
    assert empty.unrestricted is False
    assert empty.organization_ids == frozenset()
    assert empty.project_ids == frozenset()
    assert empty.dataset_ids == frozenset()


def test_visibility_and_dataset_visibility_are_frozen() -> None:
    """Both value types reject attribute assignment after construction."""
    visibility = Visibility()
    with pytest.raises(FrozenInstanceError):
        visibility.unrestricted = True
    dataset_visibility = DatasetVisibility(uuid4(), uuid4())
    with pytest.raises(FrozenInstanceError):
        dataset_visibility.dataset_id = uuid4()


def test_a_system_scope_binding_makes_everything_unrestricted_and_nothing_else_populated() -> None:
    """A SYSTEM ``dataset.discover`` binding sets ``unrestricted`` and leaves every id set empty."""
    principal = Principal(subject="root")
    binding = Binding(
        principal="user:root",
        capabilities=frozenset({"dataset.discover"}),
        scope_type=ScopeType.SYSTEM,
        scope_id=None,
    )
    authorizer = RoleBindingAuthorizer()

    result = authorizer.visibility(principal, [binding], [], [])

    assert result.unrestricted is True
    assert result.organization_ids == frozenset()
    assert result.project_ids == frozenset()
    assert result.dataset_ids == frozenset()


def test_a_project_scope_binding_populates_project_ids_from_visible_project_ids() -> None:
    """A project binding's ``project_ids`` matches ``visible_project_ids``; org ids stay empty."""
    organization_id, project_id = uuid4(), uuid4()
    principal = Principal(subject="alice")
    binding = Binding(
        principal="user:alice",
        capabilities=frozenset({"dataset.discover"}),
        scope_type=ScopeType.PROJECT,
        scope_id=project_id,
    )
    project = ProjectVisibility(project_id, organization_id, "public")
    authorizer = RoleBindingAuthorizer(classifications=(Classification("public", 0, True),))

    result = authorizer.visibility(principal, [binding], [project], [])

    assert result.project_ids == frozenset(
        authorizer.visible_project_ids(principal, [project], [binding])
    )
    assert result.project_ids == frozenset({project_id})
    assert result.organization_ids == frozenset()
    assert result.unrestricted is False


def test_an_organization_scope_binding_admits_the_org_and_only_discoverable_projects() -> None:
    """An organization binding lists its id; ``project_ids`` still obeys classification.

    A second organization, bound to a different principal, proves the
    comprehension does not admit every organization-scope binding it sees.
    """
    organization_id, other_organization_id = uuid4(), uuid4()
    open_project_id, restricted_project_id = uuid4(), uuid4()
    principal = Principal(subject="alice")
    binding = Binding(
        principal="user:alice",
        capabilities=frozenset({"dataset.discover"}),
        scope_type=ScopeType.ORGANIZATION,
        scope_id=organization_id,
    )
    foreign_binding = Binding(
        principal="user:bob",
        capabilities=frozenset({"dataset.discover"}),
        scope_type=ScopeType.ORGANIZATION,
        scope_id=other_organization_id,
    )
    projects = [
        ProjectVisibility(open_project_id, organization_id, "public"),
        ProjectVisibility(restricted_project_id, organization_id, "restricted"),
    ]
    authorizer = RoleBindingAuthorizer(
        classifications=(
            Classification("public", 0, True),
            Classification("restricted", 1, False),
        )
    )

    result = authorizer.visibility(principal, [binding, foreign_binding], projects, [])

    assert result.organization_ids == frozenset({organization_id})
    assert result.project_ids == frozenset({open_project_id})


def test_a_malformed_organization_binding_with_no_scope_id_is_ignored() -> None:
    """An ORGANIZATION binding carrying no scope id contributes nothing, rather than crashing."""
    principal = Principal(subject="alice")
    malformed = Binding(
        principal="user:alice",
        capabilities=frozenset({"dataset.discover"}),
        scope_type=ScopeType.ORGANIZATION,
        scope_id=None,
    )
    authorizer = RoleBindingAuthorizer()

    result = authorizer.visibility(principal, [malformed], [], [])

    assert result.organization_ids == frozenset()


def test_a_dataset_scope_binding_admits_the_dataset_when_its_project_is_discoverable() -> None:
    """A dataset binding puts the dataset in ``dataset_ids`` when its project is discoverable."""
    organization_id, project_id, dataset_id = uuid4(), uuid4(), uuid4()
    principal = Principal(subject="alice")
    binding = Binding(
        principal="user:alice",
        capabilities=frozenset({"dataset.discover"}),
        scope_type=ScopeType.DATASET,
        scope_id=dataset_id,
    )
    project = ProjectVisibility(project_id, organization_id, "public")
    dataset = DatasetVisibility(dataset_id, project_id)
    authorizer = RoleBindingAuthorizer(classifications=(Classification("public", 0, True),))

    result = authorizer.visibility(principal, [binding], [project], [dataset])

    assert result.dataset_ids == frozenset({dataset_id})


def test_a_dataset_is_hidden_when_its_project_is_neither_discoverable_nor_cleared() -> None:
    """A dataset whose project's classification is restricted and uncleared stays invisible."""
    organization_id, project_id, dataset_id = uuid4(), uuid4(), uuid4()
    principal = Principal(subject="alice")
    binding = Binding(
        principal="user:alice",
        capabilities=frozenset({"dataset.discover"}),
        scope_type=ScopeType.DATASET,
        scope_id=dataset_id,
    )
    project = ProjectVisibility(project_id, organization_id, "restricted")
    dataset = DatasetVisibility(dataset_id, project_id)
    authorizer = RoleBindingAuthorizer(classifications=(Classification("restricted", 1, False),))

    result = authorizer.visibility(principal, [binding], [project], [dataset])

    assert result.dataset_ids == frozenset()


def test_a_dataset_is_admitted_through_project_clearance_even_when_not_discoverable() -> None:
    """A binding whose ``maximum_classification`` clears the project's level admits the dataset."""
    organization_id, project_id, dataset_id = uuid4(), uuid4(), uuid4()
    principal = Principal(subject="alice")
    discover_binding = Binding(
        principal="user:alice",
        capabilities=frozenset({"dataset.discover"}),
        scope_type=ScopeType.DATASET,
        scope_id=dataset_id,
    )
    clearance_binding = Binding(
        principal="user:alice",
        capabilities=frozenset(),
        scope_type=ScopeType.PROJECT,
        scope_id=project_id,
        maximum_classification="restricted",
    )
    project = ProjectVisibility(project_id, organization_id, "restricted")
    dataset = DatasetVisibility(dataset_id, project_id)
    authorizer = RoleBindingAuthorizer(classifications=(Classification("restricted", 1, False),))

    result = authorizer.visibility(
        principal, [discover_binding, clearance_binding], [project], [dataset]
    )

    assert result.dataset_ids == frozenset({dataset_id})


def test_a_dataset_is_invisible_when_no_binding_covers_its_own_scope() -> None:
    """A dataset with no covering discovery grant is excluded, even under an open project."""
    organization_id, project_id, dataset_id = uuid4(), uuid4(), uuid4()
    principal = Principal(subject="alice")
    project = ProjectVisibility(project_id, organization_id, "public")
    dataset = DatasetVisibility(dataset_id, project_id)
    authorizer = RoleBindingAuthorizer(classifications=(Classification("public", 0, True),))

    result = authorizer.visibility(principal, [], [project], [dataset])

    assert result.dataset_ids == frozenset()


def test_a_dataset_is_invisible_when_its_projects_classification_is_unknown() -> None:
    """A project classification outside the vocabulary hides its dataset - fail closed."""
    organization_id, project_id, dataset_id = uuid4(), uuid4(), uuid4()
    principal = Principal(subject="alice")
    binding = Binding(
        principal="user:alice",
        capabilities=frozenset({"dataset.discover"}),
        scope_type=ScopeType.DATASET,
        scope_id=dataset_id,
    )
    project = ProjectVisibility(project_id, organization_id, "unknown-code")
    dataset = DatasetVisibility(dataset_id, project_id)
    authorizer = RoleBindingAuthorizer(classifications=(Classification("public", 0, True),))

    result = authorizer.visibility(principal, [binding], [project], [dataset])

    assert result.dataset_ids == frozenset()


def test_a_dataset_is_never_visible_when_its_project_is_absent_from_projects() -> None:
    """A dataset whose project isn't in ``projects`` is excluded, even with an admitting binding."""
    project_id, dataset_id = uuid4(), uuid4()
    principal = Principal(subject="alice")
    binding = Binding(
        principal="user:alice",
        capabilities=frozenset({"dataset.discover"}),
        scope_type=ScopeType.DATASET,
        scope_id=dataset_id,
    )
    dataset = DatasetVisibility(dataset_id, project_id)
    authorizer = RoleBindingAuthorizer(classifications=(Classification("public", 0, True),))

    result = authorizer.visibility(principal, [binding], [], [dataset])

    assert result.dataset_ids == frozenset()


def test_an_expired_binding_contributes_to_no_set() -> None:
    """An expired binding is excluded from every one of the three id sets."""
    organization_id, project_id, dataset_id = uuid4(), uuid4(), uuid4()
    principal = Principal(subject="alice")
    expired_at = datetime(2020, 1, 1, tzinfo=UTC)
    now = datetime(2024, 1, 1, tzinfo=UTC)
    binding = Binding(
        principal="user:alice",
        capabilities=frozenset({"dataset.discover"}),
        scope_type=ScopeType.ORGANIZATION,
        scope_id=organization_id,
        expires_at=expired_at,
    )
    project = ProjectVisibility(project_id, organization_id, "public")
    dataset = DatasetVisibility(dataset_id, project_id)
    authorizer = RoleBindingAuthorizer(classifications=(Classification("public", 0, True),))

    result = authorizer.visibility(principal, [binding], [project], [dataset], now=now)

    assert result.unrestricted is False
    assert result.organization_ids == frozenset()
    assert result.project_ids == frozenset()
    assert result.dataset_ids == frozenset()


def test_a_deny_binding_at_the_organization_removes_it_from_organization_ids() -> None:
    """A DENY binding covering the organization's own scope excludes it from that id set."""
    organization_id = uuid4()
    principal = Principal(subject="alice")
    allow_binding = Binding(
        principal="user:alice",
        capabilities=frozenset({"dataset.discover"}),
        scope_type=ScopeType.ORGANIZATION,
        scope_id=organization_id,
    )
    deny_binding = Binding(
        principal="user:alice",
        capabilities=frozenset({"dataset.discover"}),
        scope_type=ScopeType.ORGANIZATION,
        scope_id=organization_id,
        effect=Effect.DENY,
    )
    authorizer = RoleBindingAuthorizer()

    result = authorizer.visibility(principal, [allow_binding, deny_binding], [], [])

    assert result.organization_ids == frozenset()


def test_visible_project_ids_skips_a_classification_outside_the_vocabulary() -> None:
    """A project classification the vocabulary doesn't name is never visible - fail closed."""
    organization_id, project_id = uuid4(), uuid4()
    principal = Principal(subject="alice")
    binding = Binding(
        principal="user:alice",
        capabilities=frozenset({"dataset.discover"}),
        scope_type=ScopeType.PROJECT,
        scope_id=project_id,
    )
    project = ProjectVisibility(project_id, organization_id, "unknown-code")
    authorizer = RoleBindingAuthorizer(classifications=(Classification("public", 0, True),))

    assert authorizer.visible_project_ids(principal, [project], [binding]) == []


def test_dataset_clearance_never_discovers_its_project_or_sibling() -> None:
    """Dataset-only clearance stays local even when discovery is granted to the whole project."""
    organization_id, project_id, dataset_id, sibling_id = (uuid4() for _ in range(4))
    principal = Principal(subject="alice")
    discover = Binding(
        principal="user:alice",
        capabilities=frozenset({"dataset.discover"}),
        scope_type=ScopeType.PROJECT,
        scope_id=project_id,
    )
    clearance = Binding(
        principal="user:alice",
        capabilities=frozenset(),
        scope_type=ScopeType.DATASET,
        scope_id=dataset_id,
        maximum_classification="restricted",
    )
    project = ProjectVisibility(project_id, organization_id, "restricted")
    authorizer = RoleBindingAuthorizer((Classification("restricted", 1, False),))

    visible = authorizer.visibility(
        principal,
        [discover, clearance],
        [project],
        [DatasetVisibility(dataset_id, project_id), DatasetVisibility(sibling_id, project_id)],
    )

    assert visible.dataset_ids == frozenset({dataset_id})
    assert visible.project_ids == frozenset()
    assert visible.organization_ids == frozenset()
    assert not visible.unrestricted
