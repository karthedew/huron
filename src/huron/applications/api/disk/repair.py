"""Repair on the lake: one step per planned directory, each under that directory's lock."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.storage import FailureReason, RepairFailure, RepairResult, RepairStep, SymlinkInLake

if TYPE_CHECKING:
    from huron.applications.api.disk.lake import LakeDisk, Located, Run
    from huron.core.lake.repairs import PlannedDirectory, RepairPlan, Repairs
    from huron.core.storage import LakePath, Repairer

__all__ = ["LakeRepair"]


class LakeRepair:
    """Repairs the directories that a :class:`RepairPlan` holds, on the lake of ``disk``."""

    def __init__(self, disk: LakeDisk, repairer: Repairer) -> None:
        self._disk = disk
        self._repairer = repairer

    async def repair(self, repairs: Repairs, plan: RepairPlan) -> RepairResult:
        """Run one step per planned directory, parents first, and combine their results.

        Every directory is located before any disk work. Each step holds its directory's lock
        (:meth:`LakeDisk.hold`), reads the directory's rows again (:meth:`Repairs.expected`)
        and then runs the :class:`~huron.core.storage.Repairer` in the disk pool. A directory
        whose row is gone gets no step. A symbolic link that the marker check meets is the
        step's failure. Only ``LAKE_UNAVAILABLE`` ends the repair.
        """
        located = [(planned, self._disk.locate(planned.path)) for planned in plan.directories]
        catalog = None if plan.catalog is None else self._disk.locate(plan.catalog.path).location
        results = [
            await self._step(repairs, planned, where, catalog, plan.share_group)
            for planned, where in located
        ]
        return RepairResult.combine(results)

    async def _step(
        self,
        repairs: Repairs,
        planned: PlannedDirectory,
        where: Located,
        catalog: LakePath | None,
        share_group: str | None,
    ) -> RepairResult:
        async def unit(run: Run) -> RepairResult:
            row = await repairs.expected(planned)
            if row is None:
                return RepairResult()
            step = RepairStep(where.place, where.location, catalog, share_group, row.metadata)
            return await run(lambda: self._repairer.repair(step))

        try:
            return await self._disk.hold(where, unit)
        except SymlinkInLake as error:
            # The marker check before the unit met a link: the organization's own directory or
            # its marker, or a directory above it.
            failure = RepairFailure.of(
                where.place, FailureReason.SYMBOLIC_LINK, error, where.location
            )
            return RepairResult(failed=(failure,))
