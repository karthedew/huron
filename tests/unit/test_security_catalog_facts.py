"""Narrow Security facts preserve memory-adapter discovery and ancestry semantics."""

import pytest

from huron.core.metastore import InMemoryHierarchyStore
from tests.security_fact_contract import security_fact_projection_contract

pytestmark = pytest.mark.unit


async def test_security_fact_projections_preserve_discovery() -> None:
    """The memory adapter obeys the same visibility and ancestry contract as PostgreSQL."""
    await security_fact_projection_contract(InMemoryHierarchyStore())
