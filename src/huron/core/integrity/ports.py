"""Consumer-owned capabilities for externally authorized legacy maintenance."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from contextlib import AbstractContextManager
    from uuid import UUID

    from huron.pkg.catalog.models import RevisionRecord
    from huron.pkg.catalog.paths import RevisionPath
    from huron.pkg.catalog.records import Dataset, Organization, Project

    from .models import FenceEvidence, MaintenanceGrant, ProtocolTransition


@runtime_checkable
class LegacyStorage(Protocol):
    """Complete revision observation and immutable protocol evidence storage."""

    def generation_paths(self) -> Iterator[str]:
        """Enumerate all hierarchy control files without omitting incomplete entities.

        Returns:
            Every CURRENT pointer and generation document path relative to the root.
        """
        ...

    def read_generation(self, path: str) -> bytes:
        """Read one sealed independent hierarchy document with the required owner.

        Args:
            path: Root-relative generation or CURRENT document path.

        Returns:
            Exact bytes after filesystem identity and attribute validation.
        """
        ...

    def revision_paths(self) -> Iterator[str]:
        """Enumerate every relative Raw revision path.

        Returns:
            An iterator over each revision path under this root.
        """
        ...

    def read_control(self, revision_path: str, name: str) -> bytes:
        """Read one control document without following links.

        Args:
            revision_path: Relative revision directory.
            name: Single control-document name.

        Returns:
            Exact stored bytes.
        """
        ...

    def inspect_revision(
        self, revision_path: str, expected: Mapping[str, tuple[int, str]] | None
    ) -> tuple[str, ...]:
        """Fully hash a revision and report structural or content findings.

        Args:
            revision_path: Relative revision directory.
            expected: Exact expected inventory, or None if documents are corrupt.

        Returns:
            Finding codes without payload content.
        """
        ...

    def write_evidence(self, relative_path: str, payload: bytes) -> None:
        """Durably install a complete immutable report or protocol record.

        Args:
            relative_path: Protocol-relative destination.
            payload: Complete canonical evidence bytes.
        """
        ...

    def claim(self) -> AbstractContextManager[None]:
        """Acquire exclusive local process ownership, refusing an already-owned root.

        Returns:
            A claim held through all settled I/O; only process death permits abandoned recovery.
        """
        ...


class MaintenanceAuthority(Protocol):
    """Authenticate the caller through the deployment's external trust boundary."""

    async def authenticate(self) -> MaintenanceGrant:
        """Resolve live external operator credentials.

        Returns:
            The externally authenticated root and operation grant.
        """
        ...


class WriterExclusion(Protocol):
    """Terminate every inventoried writer and continuously exclude application restarts."""

    async def establish(self, grant: MaintenanceGrant, run_id: UUID) -> FenceEvidence:
        """Establish enforced exclusion before returning a writer inventory receipt.

        Args:
            grant: Authenticated authority accepted by the workflow.
            run_id: Immutable cutover run identity.

        Returns:
            Controller identity, generation, complete writer inventory and role names.
        """
        ...

    async def check(self, evidence: FenceEvidence) -> None:
        """Refuse if the continuously enforced exclusion no longer matches its receipt.

        Args:
            evidence: Original controller and inventory evidence.
        """
        ...

    async def certify(self, transition: ProtocolTransition) -> None:
        """Endorse prepared evidence after exclusive validation of storage and both live fences.

        Args:
            transition: Exact durable record proposed for current-controller endorsement.
        """
        ...

    async def validate_certificate(self, transition: ProtocolTransition) -> None:
        """Require current endorsement, exact durable evidence and both live exclusion proofs.

        Args:
            transition: Receipt presented by a consumer; document presence alone is insufficient.
        """
        ...


class DatabaseExclusion(Protocol):
    """Permanent old-role and temporary new-role database access exclusion."""

    async def exclude(self, old_roles: tuple[str, ...], new_role: str) -> None:
        """Disable dedicated application logins and terminate surviving sessions.

        Args:
            old_roles: Dedicated legacy application role names.
            new_role: Replacement role excluded throughout verification.
        """
        ...

    async def check(self, old_roles: tuple[str, ...], new_role: str) -> None:
        """Verify role ownership, effective access and absence of application sessions.

        Args:
            old_roles: Permanently excluded legacy application roles.
            new_role: Replacement role excluded throughout verification.
        """
        ...


class LegacyMaintenance(Protocol):
    """Narrow schema-0010 trusted inventory and audited legacy-session resolution."""

    async def generation_records(self) -> tuple[Organization | Project | Dataset, ...]:
        """Inventory every authoritative hierarchy entity and its acknowledged generation.

        Returns:
            Exact catalog records for complete structural verification.
        """
        ...

    async def revision_paths(self) -> tuple[str, ...]:
        """Inventory known catalog revisions, including physically missing envelopes.

        Returns:
            Exact logical storage paths recorded in the legacy database.
        """
        ...

    async def lookup(self, identity: RevisionPath) -> RevisionRecord | None:
        """Validate exact existing parents and resolve a known revision if present.

        Args:
            identity: Full ancestry recovered from the physical revision path.

        Returns:
            Trusted existing revision or None for an unrecorded final envelope.
        """
        ...

    async def resolve(
        self,
        actor: str,
        root_id: UUID,
        run_id: UUID,
        revisions: tuple[tuple[RevisionRecord, tuple[str, ...]], ...],
    ) -> None:
        """Import trusted records and terminalize legacy sessions with audit and findings.

        Args:
            actor: Authenticated maintenance actor.
            root_id: Authenticated storage root.
            run_id: Idempotent operation identity.
            revisions: Complete scanned population with trustworthy records.
        """
        ...
