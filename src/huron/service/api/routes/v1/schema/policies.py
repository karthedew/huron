"""Request bodies owned by ``endpoints/policies.py``."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CreatePolicy(BaseModel):
    policy_type: str = Field(pattern=r"^[a-z][a-z0-9_]{1,62}$")
    name: str = Field(min_length=1)
    spec: dict[str, object]


class AttachPolicy(BaseModel):
    policy_id: str
