"""Canonical cutover evidence with exact legacy membership."""

import hashlib
from datetime import datetime
from pathlib import PurePosixPath
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from huron.pkg.catalog.manifest import canonical_bytes
from huron.pkg.catalog.paths import parse_revision_dir

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class EvidenceDocument(BaseModel):
    """Immutable, strictly decoded fields shared by protocol evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    @property
    def canonical(self) -> bytes:
        """Return the exact canonical bytes used for durable evidence.

        Returns:
            RFC 8785 serialization of the complete document.
        """
        return canonical_bytes(self.model_dump(mode="json", by_alias=True))

    @property
    def sha256(self) -> str:
        """Return the digest of the canonical evidence.

        Returns:
            Lowercase SHA-256 hexadecimal digest.
        """
        return hashlib.sha256(self.canonical).hexdigest()

    @classmethod
    def decode(cls, payload: bytes) -> Self:
        """Decode evidence without accepting alternative byte representations.

        Args:
            payload: Complete stored document bytes.

        Returns:
            Validated immutable evidence.

        Raises:
            ValueError: If validation fails or the bytes are noncanonical.
        """
        document = cls.model_validate_json(payload)
        if document.canonical != payload:
            raise ValueError("protocol evidence is not canonical")
        return document


class DocumentObservation(EvidenceDocument):
    """Document bytes or explicit absence, without an invented content identity."""

    model_config = ConfigDict(
        json_schema_extra={
            "if": {"properties": {"state": {"const": "PRESENT"}}},
            "then": {
                "required": ["sha256_digest"],
                "properties": {"sha256_digest": {"type": "string"}},
            },
            "else": {"properties": {"sha256_digest": {"type": "null"}}},
        }
    )

    state: Literal["PRESENT", "ABSENT", "ERROR"]
    sha256_digest: Digest | None = None

    @model_validator(mode="after")
    def consistent_digest(self) -> Self:
        """Require a digest precisely when bytes were observed successfully.

        Returns:
            The validated observation.

        Raises:
            ValueError: If digest presence disagrees with observation state.
        """
        if (self.state == "PRESENT") != (self.sha256_digest is not None):
            raise ValueError("document observation and digest disagree")
        return self


class LegacyRevision(EvidenceDocument):
    """One trustworthy revision identity and its observed integrity outcome."""

    model_config = ConfigDict(
        json_schema_extra={
            "if": {"properties": {"outcome": {"const": "VERIFIED"}}},
            "then": {
                "properties": {
                    "findings": {"maxItems": 0},
                    "committed": {"properties": {"state": {"const": "PRESENT"}}},
                    "manifest": {"properties": {"state": {"const": "PRESENT"}}},
                    "metadata": {"properties": {"state": {"const": "PRESENT"}}},
                }
            },
            "else": {"properties": {"findings": {"minItems": 1}}},
        }
    )

    revision_id: UUID
    dataset_id: UUID
    number: Annotated[int, Field(ge=1, le=999_999)]
    path: Annotated[str, Field(min_length=1)]
    committed: DocumentObservation
    manifest: DocumentObservation
    metadata: DocumentObservation
    outcome: Literal["VERIFIED", "DEGRADED"]
    findings: tuple[str, ...]
    total_bytes: Annotated[int, Field(ge=0, le=2**53 - 1)]

    @model_validator(mode="after")
    def consistent_outcome(self) -> Self:
        """Require complete document evidence and no findings for certification.

        Returns:
            The validated inventory entry.

        Raises:
            ValueError: If outcome disagrees with findings or document evidence.
        """
        if (self.outcome == "VERIFIED") != (not self.findings):
            raise ValueError("revision outcome and findings disagree")
        if self.outcome == "VERIFIED" and any(
            item.state != "PRESENT" for item in (self.committed, self.manifest, self.metadata)
        ):
            raise ValueError("verified revision requires all document digests")
        identity = parse_revision_dir(PurePosixPath("/"), PurePosixPath("/") / self.path)
        if self.path.startswith("/") or (
            identity.revision_id,
            identity.dataset_id,
            identity.revision_number,
        ) != (self.revision_id, self.dataset_id, self.number):
            raise ValueError("inventory path and revision identity disagree")
        return self


class FenceEvidence(EvidenceDocument):
    """Controller and database identities whose enforced exclusion protects a scan."""

    controller_id: UUID
    generation: Annotated[int, Field(ge=1)]
    root_id: UUID
    operator: Annotated[str, Field(min_length=1)]
    terminated_writers: tuple[str, ...]
    old_roles: tuple[str, ...]
    new_role: Annotated[str, Field(min_length=1)]


class MaintenanceGrant(EvidenceDocument):
    """An external authority's authenticated operator and permitted maintenance scope."""

    root_id: UUID
    operator: Annotated[str, Field(min_length=1)]
    operations: frozenset[Literal["cutover"]]


class GenerationObservation(EvidenceDocument):
    """Exact structural control bytes checked against the authoritative hierarchy."""

    path: Annotated[str, Field(min_length=1)]
    sha256_digest: Digest


class ProtocolInventory(EvidenceDocument):
    """The complete legacy population observed under one uninterrupted fence."""

    schema_id: Literal["urn:huron:protocol-inventory:1"] = Field(
        default="urn:huron:protocol-inventory:1", alias="schema"
    )
    run_id: UUID
    root_id: UUID
    fence: FenceEvidence
    revisions: tuple[LegacyRevision, ...]
    generations: tuple[GenerationObservation, ...] = ()

    @model_validator(mode="after")
    def unique_membership(self) -> Self:
        """Reject mixed roots and duplicate identity, number or path claims.

        Returns:
            The validated complete inventory.

        Raises:
            ValueError: If identities or the fence disagree.
        """
        if self.root_id != self.fence.root_id:
            raise ValueError("inventory and fence roots disagree")
        identities = {entry.revision_id for entry in self.revisions}
        numbers = {(entry.dataset_id, entry.number) for entry in self.revisions}
        paths = {entry.path for entry in self.revisions}
        if {len(identities), len(numbers), len(paths)} != {len(self.revisions)}:
            raise ValueError("legacy inventory contains ambiguous identities")
        if len({item.path for item in self.generations}) != len(self.generations):
            raise ValueError("legacy inventory contains ambiguous generation paths")
        return self

    def certifies(self, revision: LegacyRevision) -> bool:
        """Check exact verified membership, including every observed document digest.

        Args:
            revision: Current revision evidence to compare against the inventory.

        Returns:
            Whether the exact revision was certified by this inventory.
        """
        return revision.outcome == "VERIFIED" and revision in self.revisions


class ProtocolTransition(EvidenceDocument):
    """A numbered immutable record binding a durable inventory to its root."""

    schema_id: Literal["urn:huron:protocol-transition:1"] = Field(
        default="urn:huron:protocol-transition:1", alias="schema"
    )
    sequence: Annotated[int, Field(ge=1, le=999_999)]
    root_id: UUID
    run_id: UUID
    before: Literal[1]
    after: Literal[2]
    instant: AwareDatetime
    actor: Annotated[str, Field(min_length=1)]
    code_digest: Digest
    report_path: str
    report_digest: Digest
    verified_count: Annotated[int, Field(ge=0)]
    verified_bytes: Annotated[int, Field(ge=0)]
    degraded_revision_ids: tuple[UUID, ...]
    fence: FenceEvidence

    @classmethod
    def bind(
        cls,
        inventory: ProtocolInventory,
        *,
        sequence: int,
        instant: datetime,
        code_digest: str,
    ) -> Self:
        """Bind a complete report without deriving membership from timestamps.

        Args:
            inventory: Durable report to bind into the protocol history.
            sequence: Next immutable record number.
            instant: Audit instant, never a legacy-membership criterion.
            code_digest: Immutable identity of the verification implementation.

        Returns:
            A validated transition referencing the exact inventory bytes.
        """
        verified = tuple(item for item in inventory.revisions if item.outcome == "VERIFIED")
        return cls(
            sequence=sequence,
            root_id=inventory.root_id,
            run_id=inventory.run_id,
            before=1,
            after=2,
            instant=instant,
            actor=inventory.fence.operator,
            code_digest=code_digest,
            report_path=f"reports/{inventory.run_id}.json",
            report_digest=inventory.sha256,
            verified_count=len(verified),
            verified_bytes=sum(item.total_bytes for item in verified),
            degraded_revision_ids=tuple(
                item.revision_id for item in inventory.revisions if item.outcome == "DEGRADED"
            ),
            fence=inventory.fence,
        )

    def validate_inventory(self, inventory: ProtocolInventory) -> None:
        """Require every record field to agree with the bound report.

        Args:
            inventory: Canonically decoded report referenced by this record.

        Raises:
            ValueError: If any binding, identity, count or outcome differs.
        """
        expected = self.bind(
            inventory, sequence=self.sequence, instant=self.instant, code_digest=self.code_digest
        )
        if self != expected:
            raise ValueError("protocol record disagrees with its inventory")


class CertificationIndeterminateError(RuntimeError):
    """The authority may have endorsed complete evidence, but its acknowledgement was lost."""
