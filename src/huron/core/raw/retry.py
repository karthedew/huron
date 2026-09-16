"""Manifest-bound upload retry identities."""

from uuid import UUID

from huron.core.foundation.retry import IdempotencyClaim, request_sha256

from .manifest import ManifestEntry, validate_manifest


def session_claim(
    principal: str, key: str, dataset_id: UUID, entries: tuple[ManifestEntry, ...]
) -> IdempotencyClaim:
    """Fingerprint a complete upload independently of submitted manifest order.

    Args:
        principal: Authenticated actor's subject.
        key: The actor's global retry key.
        dataset_id: Authoritative target dataset.
        entries: Complete submitted file manifest.

    Returns:
        The upload-opening claim using the stable request encoding.
    """
    manifest = validate_manifest(entries)
    return IdempotencyClaim(
        principal=principal,
        key=key,
        request_sha256=request_sha256("ingest_session", str(dataset_id), manifest.sha256),
    )
