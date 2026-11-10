"""Repair bodies."""

from __future__ import annotations

from pydantic import BaseModel, Field

from huron.applications.api.routes.v1.schema.catalogs import ShareWarningOut
from huron.core.storage import FailureReason

__all__ = ["RepairFailureOut", "RepairIn", "RepairOut"]


class RepairIn(BaseModel):
    """What a catalog repair covers."""

    target: str = Field(
        min_length=1,
        description="The catalog's name, or the identifier of one of its namespaces or settled"
        " collections.",
    )
    recursive: bool = Field(
        default=False,
        description="Also repair every namespace and settled collection below the target.",
    )


# The Field descriptions of RepairFailureOut are the one statement of the rules for path, reason
# and detail. docs/api-errors.md links to this schema in the OpenAPI reference.
class RepairFailureOut(BaseModel):
    """A place that the repair could not fix."""

    path: str = Field(
        description="The place where the repair failed, in the form of a view's path. For"
        " mode_drift, path is the directory of the step. For symbolic_link, path is the link."
        " The link can be at the directory of the step or at a directory above it. It can also"
        " be at the metadata.json of the step or at its part file (metadata.json.huron-part)."
        " Or it can be at the .huron marker that guards the organization. For an organization"
        " with its own root, this marker is in the directory of the organization (path"
        " <organization>/.huron). For any other organization, it is the marker at the root of"
        " the lake (path .huron). For storage_failed, path is the place that"
        " the storage error names. This place is the directory of the step, the catalog"
        " directory, the metadata.json of the step or its part file. When the directory refuses"
        " to make or to delete the part file, or the rename of the part file fails, path is"
        " metadata.json. A place at or above the root of the organization keeps its path in the"
        " lake, for example roots."
    )
    reason: FailureReason = Field(
        description="mode_drift: only the storage administrator can set the mode or the group"
        " of the directory. The catalog directory or a directory below it does not have the"
        " setgid bit. Or a directory below the catalog directory does not have the group of the"
        " catalog directory. Or the permission bits are wrong, and the API is not in the group"
        " of the directory. Or the mode is still wrong after the API changed it. Or a new"
        " directory did not get the setgid bit and the group of its parent, or the mode 2750."
        " The API deleted that directory again. The storage administrator runs huron adm"
        " provision-catalogs."
        " symbolic_link: path is a symbolic link. The repair does not change the link. The"
        " storage administrator deletes it. storage_failed: a different storage error occurred."
        " For example, the path of the step is not a directory. Or a directory is at"
        " metadata.json or at its part file. Or the API cannot read or write path."
    )
    detail: str = Field(
        description="Why the repair failed, as text for people. It names the same place as path."
    )


class RepairOut(BaseModel):
    """What a repair changed, the share groups still pending, and what it could not fix."""

    changed: list[str] = Field(description="The paths that the repair made or changed.")
    warnings: list[ShareWarningOut]
    failed: list[RepairFailureOut]
