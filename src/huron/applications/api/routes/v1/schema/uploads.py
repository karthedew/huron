"""Upload bodies: tusd's v2 hook request and response, and an upload's state."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ChangeFileInfo",
    "FailureOut",
    "HTTPResponse",
    "HookEvent",
    "HookHTTPRequest",
    "HookRequest",
    "HookResponse",
    "HookType",
    "HookUpload",
    "TusdBody",
    "UploadOut",
]


class HookType(StrEnum):
    """The blocking hooks tusd sends to the API."""

    PRE_CREATE = "pre-create"
    PRE_FINISH = "pre-finish"
    PRE_TERMINATE = "pre-terminate"


class TusdBody(BaseModel):
    """A body in tusd's format: Go-style names on the wire, Python names in code."""

    model_config = ConfigDict(validate_by_name=True, validate_by_alias=True)


class HookUpload(TusdBody):
    """The upload a hook is about. ``id`` is empty before ``pre-create`` names it."""

    id: str = Field(default="", alias="ID")
    size: int = Field(default=0, alias="Size")
    size_is_deferred: bool = Field(default=False, alias="SizeIsDeferred")
    metadata: dict[str, str] | None = Field(default=None, alias="MetaData")
    is_partial: bool = Field(default=False, alias="IsPartial")
    is_final: bool = Field(default=False, alias="IsFinal")


class HookHTTPRequest(TusdBody):
    """The client's request that made tusd send the hook; ``uri`` names the tus resource."""

    uri: str = Field(default="", alias="URI")


class HookEvent(TusdBody):
    """What happened: the upload and the client's request."""

    upload: HookUpload = Field(alias="Upload")
    http_request: HookHTTPRequest = Field(default_factory=HookHTTPRequest, alias="HTTPRequest")


class HookRequest(TusdBody):
    """A hook call from tusd."""

    type: HookType = Field(alias="Type")
    event: HookEvent = Field(alias="Event")


class HTTPResponse(TusdBody):
    """What tusd merges into its response to the client.

    A refusal sets the status, the problem media type and the problem document as text. A
    finished upload adds the receipt headers and keeps tusd's status.
    """

    status_code: int | None = Field(default=None, alias="StatusCode")
    header: dict[str, str] | None = Field(default=None, alias="Header")
    body: str | None = Field(default=None, alias="Body")


class ChangeFileInfo(TusdBody):
    """The id tusd gives the new upload: the id of the API's upload row."""

    id: str = Field(alias="ID")


class HookResponse(TusdBody):
    """The API's answer to a hook.

    ``RejectUpload`` refuses a creation and ``RejectTermination`` a termination. A refused
    ``pre-finish`` has only ``HTTPResponse``: tusd still counts that upload as finished.
    """

    http_response: HTTPResponse | None = Field(default=None, alias="HTTPResponse")
    reject_upload: bool | None = Field(default=None, alias="RejectUpload")
    reject_termination: bool | None = Field(default=None, alias="RejectTermination")
    change_file_info: ChangeFileInfo | None = Field(default=None, alias="ChangeFileInfo")


class FailureOut(BaseModel):
    """Why the API could not place an upload."""

    code: str
    message: str


class UploadOut(BaseModel):
    """An upload and its receipt, for its creator."""

    id: str
    collection_id: str
    rel_path: str
    size: int
    state: str = Field(description="pending, placed, failed, terminated or committed.")
    sha256: str | None
    failure: FailureOut | None
