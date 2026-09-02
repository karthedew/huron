"""Stable domain errors shared by the catalog and its API adapters."""

from __future__ import annotations

from typing import ClassVar


class DomainError(Exception):
    """A failure whose stable code is part of Huron's public contract.

    Abstract: a subclass supplies ``code`` and ``status_code``, and the pair
    is one row of the error table. Raising this class directly would put a
    status on the wire with no code for a client to switch on.
    """

    #: Not a ``ClassVar``: ``PathRuleViolation`` below names a more specific
    #: code per instance for a handful of raise sites, so ``code`` has to
    #: stay writable on a subclass. ``status_code`` never varies within a
    #: subclass and stays a true class variable.
    code: str
    status_code: ClassVar[int]

    def __init__(self, detail: str | None = None, *, context: dict[str, object] | None = None):
        if type(self) is DomainError:
            raise TypeError("DomainError is abstract; raise a subclass with a stable code")
        self.detail = detail or self.code.replace("_", " ").lower()
        self.context = context or {}
        super().__init__(self.detail)

    def as_problem(self) -> dict[str, object]:
        """Return the RFC 9457-style body serialized by the API."""
        return {
            "type": f"urn:huron:error:{self.code.lower()}",
            "title": self.code.replace("_", " ").title(),
            "status": self.status_code,
            "code": self.code,
            "detail": self.detail,
            **({"context": self.context} if self.context else {}),
        }


class DatasetLocked(DomainError):
    code, status_code = "DATASET_LOCKED", 409


class IngestSessionExpired(DomainError):
    code, status_code = "INGEST_SESSION_EXPIRED", 409


class ManifestMismatch(DomainError):
    code, status_code = "MANIFEST_MISMATCH", 400


class TagExists(DomainError):
    code, status_code = "TAG_EXISTS", 409


class TagWithdrawn(DomainError):
    code, status_code = "TAG_WITHDRAWN", 410


class DuplicateContent(DomainError):
    code, status_code = "DUPLICATE_CONTENT", 409


class PathCollision(DomainError):
    code, status_code = "PATH_COLLISION", 409


class EmptyRevision(DomainError):
    code, status_code = "EMPTY_REVISION", 400


class FileTooLarge(DomainError):
    code, status_code = "FILE_TOO_LARGE", 413


class TooManyFiles(DomainError):
    code, status_code = "TOO_MANY_FILES", 413


class RevisionTooLarge(DomainError):
    code, status_code = "REVISION_TOO_LARGE", 413


class IdempotencyKeyReused(DomainError):
    code, status_code = "IDEMPOTENCY_KEY_REUSED", 409


class PreconditionFailed(DomainError):
    code, status_code = "PRECONDITION_FAILED", 412


class SlugImmutable(DomainError):
    code, status_code = "SLUG_IMMUTABLE", 409


class AmendmentFieldForbidden(DomainError):
    code, status_code = "AMENDMENT_FIELD_FORBIDDEN", 400


class ProjectionUnavailable(DomainError):
    code, status_code = "PROJECTION_UNAVAILABLE", 503


class GrantExpired(DomainError):
    code, status_code = "GRANT_EXPIRED", 401


class GrantScopeExceeded(DomainError):
    code, status_code = "GRANT_SCOPE_EXCEEDED", 403


class LayerNotMaterialized(DomainError):
    code, status_code = "LAYER_NOT_MATERIALIZED", 409


class SnapshotNotPublished(DomainError):
    code, status_code = "SNAPSHOT_NOT_PUBLISHED", 409


class ProductVersionExists(DomainError):
    code, status_code = "PRODUCT_VERSION_EXISTS", 409


class ValidationRequired(DomainError):
    code, status_code = "VALIDATION_REQUIRED", 409


class ValidationFailed(DomainError):
    code, status_code = "VALIDATION_FAILED", 422


class InputNotReadable(DomainError):
    code, status_code = "INPUT_NOT_READABLE", 403


class ClassificationExceeded(DomainError):
    code, status_code = "CLASSIFICATION_EXCEEDED", 403


class ProductStaleInput(DomainError):
    code, status_code = "PRODUCT_STALE_INPUT", 409


class QuotaExceeded(DomainError):
    code, status_code = "QUOTA_EXCEEDED", 413


class RetentionHoldPresent(DomainError):
    code, status_code = "RETENTION_HOLD_PRESENT", 409


class ProfileUnknown(DomainError):
    code, status_code = "PROFILE_UNKNOWN", 400


class ContractMismatch(DomainError):
    code, status_code = "CONTRACT_MISMATCH", 409


class ResourceNotFound(DomainError):
    code, status_code = "NOT_FOUND", 404


class ClassificationUnknown(DomainError):
    code, status_code = "CLASSIFICATION_UNKNOWN", 400


class InvalidCursor(DomainError):
    code, status_code = "INVALID_CURSOR", 400


class PathRuleViolation(DomainError):
    """A path fails one of the storage-layout or manifest rules.

    Most raise sites report the shared ``PATH_RULE_VIOLATION`` code; a few
    in ``manifest.py`` name a more specific code for a rule the path check
    alone can't describe (a byte length, a control character).
    """

    code = "PATH_RULE_VIOLATION"
    status_code = 400

    def __init__(self, code_or_detail: str, path: str | None = None):
        if path is None:
            detail = code_or_detail
            self.code = type(self).code
        else:
            detail = f"{code_or_detail}: {path!r}"
            self.code = code_or_detail
        super().__init__(detail, context={"path": path} if path is not None else None)


class IllegalIngestTransition(DomainError):
    code = "ILLEGAL_INGEST_TRANSITION"
    status_code = 409


__all__ = [
    "AmendmentFieldForbidden",
    "ClassificationExceeded",
    "ClassificationUnknown",
    "ContractMismatch",
    "DatasetLocked",
    "DomainError",
    "DuplicateContent",
    "EmptyRevision",
    "FileTooLarge",
    "GrantExpired",
    "GrantScopeExceeded",
    "IdempotencyKeyReused",
    "IllegalIngestTransition",
    "IngestSessionExpired",
    "InputNotReadable",
    "InvalidCursor",
    "LayerNotMaterialized",
    "ManifestMismatch",
    "PathCollision",
    "PathRuleViolation",
    "PreconditionFailed",
    "ProductStaleInput",
    "ProductVersionExists",
    "ProfileUnknown",
    "ProjectionUnavailable",
    "QuotaExceeded",
    "ResourceNotFound",
    "RetentionHoldPresent",
    "RevisionTooLarge",
    "SlugImmutable",
    "SnapshotNotPublished",
    "TagExists",
    "TagWithdrawn",
    "TooManyFiles",
    "ValidationFailed",
    "ValidationRequired",
]
