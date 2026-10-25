"""Hierarchy failures, including the reserved publication vocabulary."""

from huron.core.foundation.errors import DomainError


class SlugImmutable(DomainError):
    """An update attempts to change a stable slug."""

    code, status_code = "SLUG_IMMUTABLE", 409


class SlugExists(DomainError):
    """A sibling already holds the requested slug."""

    code, status_code = "SLUG_EXISTS", 409


class ProjectionUnavailable(DomainError):
    """The search projection is unavailable."""

    code, status_code = "PROJECTION_UNAVAILABLE", 503


class LayerNotMaterialized(DomainError):
    """The referenced layer has not been materialized."""

    code, status_code = "LAYER_NOT_MATERIALIZED", 409


class SnapshotNotPublished(DomainError):
    """The snapshot has not been published."""

    code, status_code = "SNAPSHOT_NOT_PUBLISHED", 409


class ProductVersionExists(DomainError):
    """The immutable product version already exists."""

    code, status_code = "PRODUCT_VERSION_EXISTS", 409


class ValidationRequired(DomainError):
    """Publication requires validation evidence."""

    code, status_code = "VALIDATION_REQUIRED", 409


class ValidationFailed(DomainError):
    """The validation evidence did not pass."""

    code, status_code = "VALIDATION_FAILED", 422


class ProductStaleInput(DomainError):
    """An input advanced past the product's pinned version."""

    code, status_code = "PRODUCT_STALE_INPUT", 409


class QuotaExceeded(DomainError):
    """A write would exceed the project's storage quota."""

    code, status_code = "QUOTA_EXCEEDED", 413


class RetentionHoldPresent(DomainError):
    """A retention hold prevents removal."""

    code, status_code = "RETENTION_HOLD_PRESENT", 409


class ProfileUnknown(DomainError):
    """The named science profile does not exist."""

    code, status_code = "PROFILE_UNKNOWN", 400


class ClassificationUnknown(DomainError):
    """The classification is outside the deployment vocabulary."""

    code, status_code = "CLASSIFICATION_UNKNOWN", 400


ERROR_CODES = frozenset(
    {
        "SLUG_IMMUTABLE",
        "SLUG_EXISTS",
        "PROJECTION_UNAVAILABLE",
        "LAYER_NOT_MATERIALIZED",
        "SNAPSHOT_NOT_PUBLISHED",
        "PRODUCT_VERSION_EXISTS",
        "VALIDATION_REQUIRED",
        "VALIDATION_FAILED",
        "PRODUCT_STALE_INPUT",
        "QUOTA_EXCEEDED",
        "RETENTION_HOLD_PRESENT",
        "PROFILE_UNKNOWN",
        "CLASSIFICATION_UNKNOWN",
        "LAYER_WORKFLOW_VIOLATION",
        "LAYER_WRITE_FORBIDDEN",
    }
)
