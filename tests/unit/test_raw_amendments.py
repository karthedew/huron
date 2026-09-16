"""Retained metadata rules preserve identity, authority and complete amendment history."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from huron.core.raw.amendments import Amendment, fold_amendments, validate_amendment
from huron.core.raw.errors import AmendmentFieldForbidden

pytestmark = pytest.mark.unit


def test_amendment_validation_protects_identity_and_reclassification() -> None:
    """Identity fields and unapproved reclassification fail, while descriptions are copied."""
    with pytest.raises(AmendmentFieldForbidden, match="id, slug"):
        validate_amendment({"slug": "renamed", "id": "other"})
    with pytest.raises(AmendmentFieldForbidden, match="metadata.reclassify"):
        validate_amendment({"data_classification": "restricted"})
    with pytest.raises(ValueError, match="at least one field"):
        validate_amendment({})
    changes = {"title": "New title"}
    validated = validate_amendment(changes)
    assert validated == changes
    assert validated is not changes
    assert validate_amendment({"data_classification": "restricted"}, may_reclassify=True) == {
        "data_classification": "restricted"
    }


def test_fold_uses_complete_sequence_not_timestamp_and_preserves_base() -> None:
    """Later sequence wins even with older timestamps, and stored reclassification folds."""
    now = datetime(2026, 1, 1, tzinfo=UTC)
    base = {"title": "Original", "description": "Preserved"}
    first = Amendment(uuid4(), 1, "alice", now, {"title": "First"})
    second = Amendment(
        uuid4(),
        2,
        "bob",
        now - timedelta(days=1),
        {"title": "Second", "data_classification": "restricted"},
    )
    assert fold_amendments(base, [second, first]) == {
        "title": "Second",
        "description": "Preserved",
        "data_classification": "restricted",
    }
    assert base == {"title": "Original", "description": "Preserved"}
    assert fold_amendments(base, []) == base
    with pytest.raises(ValueError, match="expected 1, got 2"):
        fold_amendments(base, [second])
    with pytest.raises(ValueError, match="expected 2, got 1"):
        fold_amendments(base, [first, first])
    with pytest.raises(AmendmentFieldForbidden):
        fold_amendments(base, [Amendment(uuid4(), 1, "alice", now, {"id": "changed"})])
