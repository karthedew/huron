"""The service runtime over PostgreSQL."""

import pytest

from huron.applications.api.runtime import build_runtime
from tests.support.api import settings

pytestmark = pytest.mark.contract


async def test_runtime_connects_bootstraps_and_reports_ready(database_url: str) -> None:
    runtime = await build_runtime(settings(store="postgres", database_url=database_url))
    try:
        assert await runtime.ready() == {"database": True, "signing_keys": True}
    finally:
        await runtime.close()
