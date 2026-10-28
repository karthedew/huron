"""Closed audit vocabulary, value invariants and canonical event details."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
import re
from uuid import UUID

import pytest

from huron.core.lake import audit
from huron.core.lake.types import CollectionState
from huron.core.security.broker import Role
from huron.schema.metadata import FieldChange

pytestmark = pytest.mark.unit
COLLECTION, CATALOG, COMMIT, SCHEMA = (UUID(int=i) for i in range(1, 5))
AT = datetime(2026, 10, 23, 14, 2, 11, 250000, tzinfo=UTC)
OFFSET = AT.astimezone(timezone(timedelta(hours=3)))
BASE = dict(collection=COLLECTION, catalog=CATALOG, version=1)
FILE = dict(
    **BASE, commit_id=COMMIT, host="lab", rel_path="data/file", size_bytes=42, sha256="a" * 64
)
FILE_DETAIL = dict(
    version=1,
    commit_id=str(COMMIT),
    host="lab",
    rel_path="data/file",
    size_bytes=42,
    sha256="a" * 64,
)
CHANGES = (FieldChange("/z", old=1, new=None), FieldChange("/a", new="new"))
CHANGE_DETAIL = [{"pointer": "/a", "new": "new"}, {"pointer": "/z", "old": 1, "new": None}]
CASES = [
    (
        audit.CollectionCreated(**BASE, config_version=1),
        "create",
        "collection",
        COLLECTION,
        CATALOG,
        dict(version=1, config_version=1),
    ),
    (
        audit.CollectionActivated(**BASE, identifier="helio.ns.data"),
        "activate",
        "collection",
        COLLECTION,
        CATALOG,
        dict(version=1, identifier="helio.ns.data"),
    ),
    (audit.FileAdded(**FILE), "add", "collection", COLLECTION, CATALOG, FILE_DETAIL),
    (
        audit.FileOverwritten(
            **FILE,
            old_size_bytes=21,
            old_sha256="b" * 64,
            old_uploaded_by="old",
            old_uploaded_at=OFFSET,
        ),
        "overwrite",
        "collection",
        COLLECTION,
        CATALOG,
        dict(
            **FILE_DETAIL,
            old_size_bytes=21,
            old_sha256="b" * 64,
            old_uploaded_by="old",
            old_uploaded_at=AT.isoformat(),
        ),
    ),
    (
        audit.FileRemoved(**FILE, uploaded_by="old", uploaded_at=OFFSET),
        "rm",
        "collection",
        COLLECTION,
        CATALOG,
        dict(**FILE_DETAIL, uploaded_by="old", uploaded_at=AT.isoformat()),
    ),
    (
        audit.MetadataPublished(**BASE, changes=CHANGES),
        "meta_publish",
        "collection",
        COLLECTION,
        CATALOG,
        dict(version=1, changes=CHANGE_DETAIL),
    ),
    (
        audit.CollectionMoved(
            **BASE, from_identifier="helio.ns.old", to_identifier="helio.ns.new", changes=CHANGES
        ),
        "mv",
        "collection",
        COLLECTION,
        CATALOG,
        dict(
            version=1,
            from_identifier="helio.ns.old",
            to_identifier="helio.ns.new",
            changes=CHANGE_DETAIL,
        ),
    ),
    (
        audit.CollectionDeleted(**BASE, state=CollectionState.DRAFT, identifier=None),
        "delete",
        "collection",
        COLLECTION,
        CATALOG,
        dict(version=1, state="draft", identifier=None),
    ),
    (
        audit.CatalogCreated(catalog=CATALOG, name="helio", config_version=1),
        "create",
        "catalog",
        CATALOG,
        CATALOG,
        dict(name="helio", config_version=1),
    ),
    (
        audit.CatalogConfigChanged(catalog=CATALOG, config_version=2, changes=CHANGES),
        "catalog_config",
        "catalog",
        CATALOG,
        CATALOG,
        dict(config_version=2, changes=CHANGE_DETAIL),
    ),
    (
        audit.SchemaPublished(schema=SCHEMA, name="base", version=1, extends_id=None),
        "schema_publish",
        "metadata_schema",
        SCHEMA,
        None,
        dict(name="base", version=1, extends_id=None),
    ),
    (
        audit.RoleMapped(
            ldap_group="readers",
            catalog=CATALOG,
            old_role=None,
            new_role=Role.CATALOG_READER,
            posix_gid=12,
        ),
        "role_map",
        "ldap_group",
        "readers",
        CATALOG,
        dict(old_role=None, new_role="catalog_reader", posix_gid=12),
    ),
    (
        audit.KeyRotated(kid="kid", alg="ES256", active_from=OFFSET, retired_kid=None),
        "key_rotate",
        "signing_key",
        "kid",
        None,
        dict(alg="ES256", active_from=AT.isoformat(), retired_kid=None),
    ),
    (
        audit.KeyWithdrawn(kid="kid", active_from=OFFSET),
        "key_withdraw",
        "signing_key",
        "kid",
        None,
        dict(active_from=AT.isoformat()),
    ),
]


@pytest.mark.parametrize("event,action,object_type,object_id,catalog,detail", CASES)
def test_every_event_has_exact_canonical_detail(
    event, action, object_type, object_id, catalog, detail
):
    """Each pair encodes only its required detail fields, retaining nulls and UTC instants."""
    entry = audit.AuditEntry(AT, "scientist", event)
    assert entry.detail() == detail
    assert entry.object_id == str(object_id)
    assert entry.catalog_id == catalog
    assert (event.ACTION, event.OBJECT) == (action, object_type)
    assert isinstance(entry.detail(), dict)
    with pytest.raises(FrozenInstanceError):
        setattr(event, event.KEY, "changed")
    with pytest.raises(TypeError):
        type(event)("positional")


def test_vocabulary_contains_exactly_the_fourteen_declared_pairs():
    """Vocabulary derives from the full event set, including key withdrawal."""
    assert audit.AUDIT_VOCABULARY == frozenset((case[1], case[2]) for case in CASES)
    assert len(audit.AUDIT_VOCABULARY) == 14


@pytest.mark.parametrize(
    "changes",
    [
        dict(at=AT.replace(tzinfo=None)),
        dict(actor=""),
        dict(actor="wrong user"),
        dict(reason=""),
        dict(reason=" "),
        dict(reason=" x"),
        dict(reason="x "),
        dict(reason="x" * 1001),
    ],
)
def test_entry_refuses_invalid_envelope(changes):
    """Naive instants, invalid actors and unnormalized or excessive reasons are rejected."""
    with pytest.raises(ValueError):
        audit.AuditEntry(**(dict(at=AT, actor="scientist", event=CASES[0][0]) | changes))


@pytest.mark.parametrize(
    "actor", ["scientist", "A.z_1@example.org", audit.SYSTEM_BOOTSTRAP, "system:maintenance"]
)
@pytest.mark.parametrize("reason", [None, "x", "x" * 1000])
def test_valid_actors_and_reason_boundaries(actor, reason):
    """Company subjects and explicit system actors accept optional stripped explanations."""
    assert audit.AuditEntry(AT, actor, CASES[0][0], reason).reason == reason


@pytest.mark.parametrize(
    "event",
    [
        replace(CASES[0][0], version=0),
        replace(CASES[10][0], version=-1),
        replace(CASES[5][0], changes=()),
        replace(CASES[6][0], changes=()),
        replace(CASES[9][0], changes=()),
    ],
)
def test_entry_refuses_nonpositive_versions_and_empty_changes(event):
    """Invalid versions and no-op diffs cannot produce audit entries."""
    with pytest.raises(ValueError):
        audit.AuditEntry(AT, "scientist", event)


@pytest.mark.parametrize("role", [None, *Role])
def test_role_event_refuses_equal_or_absent_roles(role):
    """A mapping event always describes an actual role transition."""
    with pytest.raises(ValueError):
        audit.RoleMapped(
            ldap_group="group", catalog=None, old_role=role, new_role=role, posix_gid=1
        )


@pytest.mark.parametrize("role", list(Role))
def test_role_removal_encodes_code_and_null(role):
    """Every supported role serializes by code, including organization administration."""
    event = audit.RoleMapped(
        ldap_group="group",
        catalog=CATALOG if role.catalog_scoped else None,
        old_role=role,
        new_role=None,
        posix_gid=1,
    )
    assert audit.AuditEntry(AT, "scientist", event).detail() == dict(
        old_role=role.code, new_role=None, posix_gid=1
    )


@pytest.mark.parametrize("state", list(CollectionState))
def test_collection_state_settled_and_deletion_encoding(state):
    """Draft is the only unsettled state and deletion preserves the exact state code."""
    assert state.settled == (state is not CollectionState.DRAFT)
    assert (
        audit.AuditEntry(AT, "scientist", replace(CASES[7][0], state=state)).detail()["state"]
        == state.value
    )


def test_detail_refuses_unsupported_event_field_types():
    """A malformed event cannot silently emit non-JSON data."""
    with pytest.raises(TypeError, match="Unsupported"):
        audit.AuditEntry(AT, "scientist", replace(CASES[8][0], name=object())).detail()


def test_no_audit_mutation_in_src():
    """Application source never updates, deletes or truncates persisted audit rows."""
    forbidden = re.compile(
        r"UPDATE\s+lake\.audit_log|DELETE\s+FROM\s+lake\.audit_log|TRUNCATE\s+lake\.audit_log",
        re.IGNORECASE,
    )
    for path in Path("src/huron").rglob("*.py"):
        assert not forbidden.search(path.read_text()), path
