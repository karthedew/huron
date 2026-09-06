"""Stable domain errors shared by the catalog and its API adapters.

Every class here is one row of the public error table: a stable ``code`` a
client can switch on, and the HTTP status the API answers with. The class
names mirror their codes on purpose, so a raise site, a handler and the
documented contract all read the same. The API adapter turns any
:class:`DomainError` into an RFC 9457 problem document through
:meth:`DomainError.as_problem`; the catalog itself never imports the
framework that does so.
"""

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
        """Record the human-readable detail and any structured context.

        Args:
            detail: The message a client sees; defaults to the code spelled
                out in lower case with spaces (``"dataset locked"``).
            context: Extra structured facts about the failure, published
                verbatim in the problem document's ``context`` member when
                present.

        Raises:
            TypeError: If :class:`DomainError` itself is instantiated rather
                than a subclass carrying a code.
        """
        if type(self) is DomainError:
            raise TypeError("DomainError is abstract; raise a subclass with a stable code")
        self.detail = detail or self.code.replace("_", " ").lower()
        self.context = context or {}
        super().__init__(self.detail)

    def as_problem(self) -> dict[str, object]:
        """Return the RFC 9457-style body serialized by the API.

        Returns:
            The problem document: a ``urn:huron:error:{code}`` type, a title
            derived from the code, the HTTP status, the code itself, the
            detail message, and ``context`` only when there is any.
        """
        return {
            "type": f"urn:huron:error:{self.code.lower()}",
            "title": self.code.replace("_", " ").title(),
            "status": self.status_code,
            "code": self.code,
            "detail": self.detail,
            **({"context": self.context} if self.context else {}),
        }


class DatasetLocked(DomainError):
    """The dataset is locked against concurrent ingest; the caller must wait for the holder."""

    code, status_code = "DATASET_LOCKED", 409


class IngestSessionExpired(DomainError):
    """The ingest session's lease has lapsed, or it is in a state that cannot be renewed."""

    code, status_code = "INGEST_SESSION_EXPIRED", 409


class ManifestMismatch(DomainError):
    """The uploaded content does not match the manifest the ingest session declared.

    Raised when a file's whole-file observation does not match the size or
    digest the manifest declared for it; ``context`` then carries that
    file's ``path``, ``expected_size``, ``observed_size``,
    ``expected_sha256`` and ``observed_sha256``.
    """

    code, status_code = "MANIFEST_MISMATCH", 400


class TagExists(DomainError):
    """The release tag already resolves; a tag is written once and never moved."""

    code, status_code = "TAG_EXISTS", 409


class TagWithdrawn(DomainError):
    """The release tag existed but was withdrawn; it no longer resolves to a revision."""

    code, status_code = "TAG_WITHDRAWN", 410


class DuplicateContent(DomainError):
    """Content with the same identity has already been ingested into the dataset."""

    code, status_code = "DUPLICATE_CONTENT", 409


class PathCollision(DomainError):
    """Two manifest entries claim the same path, ignoring case and Unicode normalization."""

    code, status_code = "PATH_COLLISION", 409


class EmptyRevision(DomainError):
    """The manifest declares no files; a revision must carry at least one."""

    code, status_code = "EMPTY_REVISION", 400


class FileTooLarge(DomainError):
    """A single manifest entry exceeds the configured per-file byte limit."""

    code, status_code = "FILE_TOO_LARGE", 413


class TooManyFiles(DomainError):
    """The manifest lists more files than the configured per-revision limit."""

    code, status_code = "TOO_MANY_FILES", 413


class RevisionTooLarge(DomainError):
    """The manifest's files together exceed the configured per-revision byte limit."""

    code, status_code = "REVISION_TOO_LARGE", 413


class IdempotencyKeyReused(DomainError):
    """The same ``Idempotency-Key`` was replayed with a different request body."""

    code, status_code = "IDEMPOTENCY_KEY_REUSED", 409


class PreconditionFailed(DomainError):
    """The ``If-Match`` version is not an integer, or the resource has moved past it."""

    code, status_code = "PRECONDITION_FAILED", 412


class SlugImmutable(DomainError):
    """An update tried to change a slug; slugs are fixed because storage paths embed them."""

    code, status_code = "SLUG_IMMUTABLE", 409


class AmendmentFieldForbidden(DomainError):
    """An amendment touched a field outside the allow-list, or one the caller may not change."""

    code, status_code = "AMENDMENT_FIELD_FORBIDDEN", 400


class ProjectionUnavailable(DomainError):
    """The search projection is not configured or not answering; there is no fallback."""

    code, status_code = "PROJECTION_UNAVAILABLE", 503


class GrantExpired(DomainError):
    """The data-access grant presented has passed its expiry."""

    code, status_code = "GRANT_EXPIRED", 401


class GrantScopeExceeded(DomainError):
    """The access requested lies outside what the data-access grant covers."""

    code, status_code = "GRANT_SCOPE_EXCEEDED", 403


class LayerNotMaterialized(DomainError):
    """The referenced layer of the dataset has not been materialized yet."""

    code, status_code = "LAYER_NOT_MATERIALIZED", 409


class SnapshotNotPublished(DomainError):
    """The referenced snapshot exists but has not been published."""

    code, status_code = "SNAPSHOT_NOT_PUBLISHED", 409


class ProductVersionExists(DomainError):
    """The product version has already been published; published versions are immutable."""

    code, status_code = "PRODUCT_VERSION_EXISTS", 409


class ValidationRequired(DomainError):
    """Publishing needs validation evidence that has not been recorded."""

    code, status_code = "VALIDATION_REQUIRED", 409


class ValidationFailed(DomainError):
    """The recorded validation evidence did not pass."""

    code, status_code = "VALIDATION_FAILED", 422


class InputNotReadable(DomainError):
    """The principal may not read one of the inputs the operation references."""

    code, status_code = "INPUT_NOT_READABLE", 403


class ClassificationExceeded(DomainError):
    """The data's classification is higher than the data-access grant allows."""

    code, status_code = "CLASSIFICATION_EXCEEDED", 403


class ProductStaleInput(DomainError):
    """A product input has moved on from the source version it was pinned to."""

    code, status_code = "PRODUCT_STALE_INPUT", 409


class QuotaExceeded(DomainError):
    """The write would take the project past its storage quota."""

    code, status_code = "QUOTA_EXCEEDED", 413


class RetentionHoldPresent(DomainError):
    """A retention hold or legal hold pins the data the operation would remove."""

    code, status_code = "RETENTION_HOLD_PRESENT", 409


class ProfileUnknown(DomainError):
    """The dataset profile named does not exist."""

    code, status_code = "PROFILE_UNKNOWN", 400


class ContractMismatch(DomainError):
    """The payload violates the schema contract registered for it."""

    code, status_code = "CONTRACT_MISMATCH", 409


class ResourceNotFound(DomainError):
    """No resource exists at the identity the caller named."""

    code, status_code = "NOT_FOUND", 404


class ClassificationUnknown(DomainError):
    """The ``data_classification`` is outside the project's configured vocabulary."""

    code, status_code = "CLASSIFICATION_UNKNOWN", 400


class InvalidCursor(DomainError):
    """The ``after`` cursor is not a keyset position this service issued."""

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
        """Build the violation under either the shared code or a path-specific one.

        The first argument is read two ways, chosen by whether ``path`` is
        given. Without a path it is the detail message and the instance
        keeps the shared ``PATH_RULE_VIOLATION`` code. With a path it is the
        specific code to report (``PATH_TOO_LONG``, ``PATH_NOT_NFC``, ...):
        that code replaces the instance's ``code``, the detail becomes
        ``"{code}: {path!r}"`` and the offending path travels in
        ``context["path"]`` so a client can point at it without parsing the
        message.

        Args:
            code_or_detail: The detail message, or, when ``path`` is given,
                the specific error code for the rule the path broke.
            path: The path that broke a rule, when the rule is path-specific.
        """
        if path is None:
            detail = code_or_detail
            self.code = type(self).code
        else:
            detail = f"{code_or_detail}: {path!r}"
            self.code = code_or_detail
        super().__init__(detail, context={"path": path} if path is not None else None)


class IllegalIngestTransition(DomainError):
    """The session, or one of its files, is not in a state that permits the operation.

    ``context`` carries ``state`` (the current state that refused the
    operation) and ``operation`` (the name of the operation attempted).
    """

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
