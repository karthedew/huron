"""Stable request fingerprints for retry identities."""

import hashlib
from uuid import UUID

from huron.pkg.catalog import ManifestEntry, validate_manifest
from huron.pkg.catalog.persistence import IdempotencyClaim

_ABSENT_FIELD = "\x01"


def request_sha256(operation: str, *parts: str | None) -> str:
    """Digest the identifying fields of a request, for idempotency-claim comparison.

    The operation name and every part are joined with a NUL byte before
    hashing, so adjacent parts cannot run together (``("ab", "c")`` and
    ``("a", "bc")`` digest differently) and a request naming a field
    ``None`` never collides with one naming it the empty string.

    Args:
        operation: The resource kind and action the request performs, kept
            first so requests of different kinds never collide even with
            identical field values.
        *parts: The request's settable fields, in a fixed order, as
            strings; ``None`` for a field the request omits.

    Returns:
        The SHA-256 hex digest of the joined operation and fields.
    """
    fields = (operation, *(_ABSENT_FIELD if part is None else part for part in parts))
    return hashlib.sha256("\x00".join(fields).encode()).hexdigest()


def session_claim(
    principal: str, key: str, dataset_id: UUID, entries: tuple[ManifestEntry, ...]
) -> IdempotencyClaim:
    """Build the idempotency claim a session's opening stakes.

    The claim's digest is the validated manifest's content identity, not
    the raw declared order, so two requests differing only in the order
    they list the same files replay as one session rather than two.

    Args:
        principal: The caller's subject, the claim's principal.
        key: The caller's ``Idempotency-Key`` header.
        dataset_id: The dataset the session is opening against.
        entries: The declared files, to be validated for their identity.

    Returns:
        The claim ``IngestService.create`` stakes in its own transaction.
    """
    manifest = validate_manifest(entries)
    return IdempotencyClaim(
        principal=principal,
        key=key,
        request_sha256=request_sha256("ingest_session", str(dataset_id), manifest.sha256),
    )
