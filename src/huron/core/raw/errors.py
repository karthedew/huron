"""Stable ingestion, manifest and revision failures."""

from huron.core.foundation.errors import DomainError


class DatasetLocked(DomainError):
    """Another nonterminal upload holds the dataset reservation."""

    code, status_code = "DATASET_LOCKED", 409


class IngestSessionExpired(DomainError):
    """The session's lease lapsed or its state cannot be renewed."""

    code, status_code = "INGEST_SESSION_EXPIRED", 409


class ManifestMismatch(DomainError):
    """Uploaded bytes disagree with their declared size or digest."""

    code, status_code = "MANIFEST_MISMATCH", 400


class PathCollision(DomainError):
    """Manifest paths collide after case folding and normalization."""

    code, status_code = "PATH_COLLISION", 409


class EmptyRevision(DomainError):
    """The submission declares no files."""

    code, status_code = "EMPTY_REVISION", 400


class FileTooLarge(DomainError):
    """A file exceeds the configured byte limit."""

    code, status_code = "FILE_TOO_LARGE", 413


class TooManyFiles(DomainError):
    """The submission exceeds the file-count limit."""

    code, status_code = "TOO_MANY_FILES", 413


class RevisionTooLarge(DomainError):
    """The submission exceeds the total byte limit."""

    code, status_code = "REVISION_TOO_LARGE", 413


class IllegalIngestTransition(DomainError):
    """The session or file state refuses the requested operation."""

    code, status_code = "ILLEGAL_INGEST_TRANSITION", 409


PATH_ERROR_CODES = frozenset(
    {
        "PATH_OUTSIDE_PAYLOAD",
        "PATH_NOT_NFC",
        "PATH_TOO_LONG",
        "PATH_TRAVERSAL",
        "PATH_CONTROL_CHARS",
        "PATH_SEPARATOR",
    }
)
ERROR_CODES = PATH_ERROR_CODES | frozenset(
    {
        "DATASET_LOCKED",
        "INGEST_SESSION_EXPIRED",
        "MANIFEST_MISMATCH",
        "PATH_COLLISION",
        "EMPTY_REVISION",
        "FILE_TOO_LARGE",
        "TOO_MANY_FILES",
        "REVISION_TOO_LARGE",
        "ILLEGAL_INGEST_TRANSITION",
    }
)
