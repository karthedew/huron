"""Repairs of the directories of catalogs and organizations."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter

from huron.applications.api.authorization import ActorDep
from huron.applications.api.dependencies import LakeDep, RuntimeDep
from huron.applications.api.disk import LakeRepair
from huron.applications.api.routes.v1.schema.repairs import RepairIn, RepairOut
from huron.core.storage import LakeUnavailable, RepairResult

__all__ = ["router"]

router = APIRouter(tags=["repairs"])


@router.post("/catalogs/{catalog}/repair")
async def catalog_repair(
    catalog: str, body: RepairIn, actor: ActorDep, lake: LakeDep, runtime: RuntimeDep
) -> RepairOut:
    """Repair the directories of the target, from the catalog's down to the target's.

    The API makes each missing directory, sets wrong permission bits, tries the catalog
    directory's share group and writes each settled collection's ``metadata.json`` that
    differs. With ``recursive`` it also repairs every namespace and settled collection below
    the target. It acts only on the directories that the rows plan and lists no directory. Of
    the directories, it deletes only a new directory that it made without the mode 2750 or
    without the group of its parent. Before it writes ``metadata.json``, it deletes the part
    file ``metadata.json.huron-part`` that an earlier write left. When the write fails, it
    tries to delete its own part file.
    """
    plan = await lake.repairs.plan(actor, catalog, body.target, body.recursive)
    return _out(await _require_lake(runtime.repair).repair(lake.repairs, plan))


@router.post("/organizations/{organization}/repair")
async def organization_repair(
    organization: str, actor: ActorDep, lake: LakeDep, runtime: RuntimeDep
) -> RepairOut:
    """Repair the mode of the organization's directory, or make the directory when it is missing."""
    plan = await lake.repairs.organization(actor, organization)
    return _out(await _require_lake(runtime.repair).repair(lake.repairs, plan))


def _require_lake(repair: LakeRepair | None) -> LakeRepair:
    """The repair on the lake; ``LAKE_UNAVAILABLE`` for a service without ``lake_path``."""
    if repair is None:
        raise LakeUnavailable("lake_path is not set. The API cannot repair directories.", {})
    return repair


def _out(result: RepairResult) -> RepairOut:
    return RepairOut.model_validate(
        {
            "changed": list(result.changed),
            "warnings": [asdict(warning) for warning in result.warnings],
            "failed": [asdict(failure) for failure in result.failed],
        }
    )
