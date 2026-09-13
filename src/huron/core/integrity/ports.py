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
    """Mint, observe, end and admit the controller epoch that excludes application writers."""

    async def establish(self, grant: MaintenanceGrant, run_id: UUID) -> FenceEvidence:
        """Begin a new exclusion epoch, terminating every application writer.

        Refuses with ``PermissionError`` if the authority refuses the operator or its
        identity changed. Propagates ``OSError`` if the authority could not be reached
        or replied incompletely.

        Args:
            grant: Authenticated authority accepted by the workflow.
            run_id: Audit and database-idempotence identity of this cutover attempt.

        Returns:
            Receipt naming the live generation, root, operator, terminated writers,
            excluded roles and the maintenance database identity captured before any
            role was fenced.
        """
        ...

    async def check(self, evidence: FenceEvidence) -> None:
        """Require a fresh proof that the receipt still names the live, intact epoch.

        Refuses with ``PermissionError`` if the epoch ended, a writer appeared or the
        receipt differs. Propagates ``OSError`` if the authority could not be observed;
        the caller treats this as loss.

        Args:
            evidence: Receipt returned by ``establish``; compared whole, ``database`` included.
        """
        ...

    async def abandon(self, evidence: FenceEvidence) -> None:
        """Declare that this receipt's run did not complete, ending its epoch.

        A receipt that no longer names the live epoch is ignored, so a stale or foreign
        receipt cannot end a newer epoch. Writers stay terminated and restart stays
        excluded; only admissibility of records under this generation ends. Refuses
        with ``PermissionError`` if the authority refuses the operator. Propagates
        ``OSError`` if the authority could not be reached; the epoch then ends at the
        authority's next observation or restart.

        Args:
            evidence: Receipt whose continuous observation failed or whose run did not return.
        """
        ...

    async def validate(self, transition: ProtocolTransition) -> None:
        """Admit a record only while its fence names the live epoch and every observation passes.

        The authority keeps no per-call state: a lost reply is resolved by calling again
        under the same generation, and every failed observation ends the epoch before the
        refusal is reported. Refuses with ``PermissionError`` if the record, its report,
        the fence or any live observation is refused. Propagates ``OSError`` if the reply
        was lost; call again.

        Args:
            transition: Exact record as stored under ``protocol/{sequence:06d}.json``.
        """
        ...


class DatabaseExclusion(Protocol):
    """Identify the maintenance database and hold its application roles excluded."""

    async def identify(self) -> str:
        """Observe the live primary's identity without asserting any role fence.

        A connected standby refuses this call with ``ValueError``.

        Returns:
            ``<system_identifier>/<database_oid>/<datname>`` of the connected database.
        """
        ...

    async def exclude(self, fence: FenceEvidence) -> None:
        """Disable the fenced roles, revoke legacy access and terminate their sessions.

        Refuses with ``ValueError`` if the live identity differs from ``fence.database``,
        a role is unsafe, a session survived, or the fence does not hold afterwards.

        Args:
            fence: Receipt naming the database whose ``old_roles`` and ``new_role`` to fence.
        """
        ...

    async def check(self, fence: FenceEvidence) -> None:
        """Verify identity, login, session, ownership and effective access under the fence.

        Refuses with ``ValueError`` if the live identity differs from ``fence.database`` or
        any application identity has escaped its fence.

        Args:
            fence: Receipt naming the database and roles that must remain excluded.
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
