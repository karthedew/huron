"""Security's narrow ancestry and naming contract over real adapter discovery predicates."""

from uuid import uuid4

import pytest

from huron.core.foundation.errors import ResourceNotFound
from huron.core.security.rules import Scope, ScopeType, Visibility
from tests.hierarchy_contract import seed_hierarchy


async def security_fact_projection_contract(store) -> None:
    """Dataset-only discovery admits ancestors but neither hidden siblings nor unknown targets."""
    tree = await seed_hierarchy(
        store,
        {
            "org-a": {"project-a": ("a-hidden", "z-visible")},
            "org-b": {"project-b": ("other-dataset",)},
        },
    )
    organization = tree.organizations["org-a"]
    project = tree.projects["project-a"]
    dataset = tree.datasets["z-visible"]
    visibility = Visibility(dataset_ids=frozenset({dataset}))
    assert await store.resource_scope(ScopeType.DATASET, dataset, visibility) == Scope(
        ScopeType.DATASET,
        dataset,
        organization_id=organization,
        project_id=project,
        dataset_id=dataset,
    )
    assert await store.resource_scope(ScopeType.PROJECT, project, visibility) == Scope(
        ScopeType.PROJECT, project, organization_id=organization, project_id=project
    )
    assert await store.resource_scope(ScopeType.ORGANIZATION, organization, visibility) == Scope(
        ScopeType.ORGANIZATION, organization, organization_id=organization
    )
    for kind, identity in (
        (ScopeType.DATASET, tree.datasets["a-hidden"]),
        (ScopeType.DATASET, tree.datasets["other-dataset"]),
        (ScopeType.PROJECT, tree.projects["project-b"]),
        (ScopeType.ORGANIZATION, tree.organizations["org-b"]),
        (ScopeType.DATASET, uuid4()),
    ):
        with pytest.raises(ResourceNotFound):
            await store.resource_scope(kind, identity, visibility)
    with pytest.raises(ResourceNotFound):
        await store.resource_scope(ScopeType.DATASET, dataset, Visibility())
    with pytest.raises(ValueError, match="system scope"):
        await store.resource_scope(ScopeType.SYSTEM, uuid4(), Visibility.ALL)
    assert await store.organization_slug(organization) == "org-a"
    with pytest.raises(ResourceNotFound):
        await store.organization_slug(uuid4())
    assert await store.dataset_parents(frozenset({dataset, uuid4()})) == {dataset: project}
    assert await store.dataset_parents(frozenset()) == {}
    facts = await store.project_visibilities()
    assert {fact.project_id for fact in facts} == set(tree.projects.values())
    page = await store.datasets.browse(project, visibility, limit=1, after=None)
    assert [item.id for item in page.items] == [dataset]
    assert page.has_more is False
