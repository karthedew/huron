"""Upload bodies: tusd's v2 hook request and response, and an upload attempt."""

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
    "UploadAttemptOut",
]


class HookType(StrEnum):
    """The blocking hooks tusd sends to the API."""

    PRE_CREATE = "pre-create"
    PRE_FINISH = "pre-finish"


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
    """The client's request that made tusd send the hook.

    ``uri`` names the tus resource. ``header`` holds the client's headers, each name with its
    values.
    """

    method: str = Field(default="", alias="Method")
    uri: str = Field(default="", alias="URI")
    header: dict[str, list[str]] = Field(default_factory=dict, alias="Header")

    def first(self, name: str) -> str | None:
        """The first value of the header ``name`` in any case, ``None`` when it is absent."""
        for key, values in self.header.items():
            if key.lower() == name.lower() and values:
                return values[0]
        return None


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
    finished upload adds the header ``Huron-Upload-State`` and keeps tusd's status.
    """

    status_code: int | None = Field(default=None, alias="StatusCode")
    header: dict[str, str] | None = Field(default=None, alias="Header")
    body: str | None = Field(default=None, alias="Body")


class ChangeFileInfo(TusdBody):
    """The id tusd gives the new upload: the upload ID that Huron issued for the attempt."""

    id: str = Field(alias="ID")


class HookResponse(TusdBody):
    """The API's answer to a hook.

    ``RejectUpload`` refuses a creation. A refused ``pre-finish`` has only ``HTTPResponse``:
    tusd still counts that upload as finished.
    """

    http_response: HTTPResponse | None = Field(default=None, alias="HTTPResponse")
    reject_upload: bool | None = Field(default=None, alias="RejectUpload")
    change_file_info: ChangeFileInfo | None = Field(default=None, alias="ChangeFileInfo")


class FailureOut(BaseModel):
    """Why an upload attempt failed."""

    code: str
    message: str


class UploadAttemptOut(BaseModel):
    """An upload attempt and its current upload ID, for its owner."""

    attempt_id: str
    collection_id: str | None = Field(description="null when the collection is deleted.")
    rel_path: str
    size: int
    state: str = Field(
        description="receiving, sealing, ready, consumed, failed, cancelled or expired."
    )
    upload_id: str = Field(
        description="The current upload ID: the only ID that tusd takes bytes for."
    )
    failure: FailureOut | None
