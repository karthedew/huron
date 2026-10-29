"""The closed audit vocabulary, entry invariants and the canonical `detail` encoding."""

from __future__ import annotations

import re
from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import pytest

from huron.core.lake import (
    AUDIT_REASON_MAX,
    AUDIT_VOCABULARY,
    SYSTEM_BOOTSTRAP,
    AuditAction,
    AuditEntry,
    AuditObject,
    CatalogConfigChanged,
    CatalogCreated,
    CollectionActivated,
    CollectionCreated,
    CollectionDeleted,
    CollectionMoved,
    CollectionState,
    FileAdded,
    FileOverwritten,
    FileRemoved,
    KeyRotated,
    KeyWithdrawn,
    MetadataPublished,
    RoleMapped,
    SchemaPublished,
)
from huron.core.security.broker import Role
from huron.schema.metadata import FieldChange

if TYPE_CHECKING:
    from huron.core.lake import AuditEvent
    from huron.schema.metadata import JsonValue

pytestmark = pytest.mark.unit

COLLECTION, CATALOG, COMMIT, SCHEMA, BASE_SCHEMA = (UUID(int=i) for i in range(1, 6))
AT = datetime(2026, 10, 23, 14, 2, 11, 250000, tzinfo=UTC)
AT_ELSEWHERE = AT.astimezone(timezone(timedelta(hours=3)))
SHA_NEW, SHA_OLD = "a" * 64, "b" * 64
IN_COLLECTION: dict[str, Any] = {"collection": COLLECTION, "catalog": CATALOG, "version": 3}
FILE: dict[str, Any] = IN_COLLECTION | {
    "commit_id": COMMIT,
    "host": "lab-07",
    "rel_path": "raw/run042.dat",
    "size_bytes": 42,
    "sha256": SHA_NEW,
}
FILE_DETAIL: dict[str, JsonValue] = {
    "version": 3,
    "commit_id": "00000000-0000-0000-0000-000000000003",
    "host": "lab-07",
    "rel_path": "raw/run042.dat",
    "size_bytes": 42,
    "sha256": SHA_NEW,
}
CHANGES = (FieldChange("/z", old=1, new=None), FieldChange("/a/~1b", new="added"))
CHANGES_DETAIL: list[JsonValue] = [
    {"pointer": "/a/~1b", "new": "added"},
    {"pointer": "/z", "old": 1, "new": None},
]
COLLECTION_ID = "00000000-0000-0000-0000-000000000001"
CATALOG_ID = "00000000-0000-0000-0000-000000000002"

# event, action, object type, object id, catalog id, detail
VOCABULARY_ROWS: list[tuple[AuditEvent, str, str, str, UUID | None, dict[str, JsonValue]]] = [
    (
        CollectionCreated(**IN_COLLECTION | {"version": 1}, config_version=2),
        "create",
        "collection",
        COLLECTION_ID,
        CATALOG,
        {"version": 1, "config_version": 2},
    ),
    (
        CollectionActivated(**IN_COLLECTION, identifier="helio.psp.run042"),
        "activate",
        "collection",
        COLLECTION_ID,
        CATALOG,
        {"version": 3, "identifier": "helio.psp.run042"},
    ),
    (FileAdded(**FILE), "add", "collection", COLLECTION_ID, CATALOG, FILE_DETAIL),
    (
        FileOverwritten(
            **FILE,
            old_size_bytes=21,
            old_sha256=SHA_OLD,
            old_uploaded_by="alice",
            old_uploaded_at=AT_ELSEWHERE,
        ),
        "overwrite",
        "collection",
        COLLECTION_ID,
        CATALOG,
        FILE_DETAIL
        | {
            "old_size_bytes": 21,
            "old_sha256": SHA_OLD,
            "old_uploaded_by": "alice",
            "old_uploaded_at": "2026-10-23T14:02:11.250000+00:00",
        },
    ),
    (
        FileRemoved(**FILE, uploaded_by="alice", uploaded_at=AT_ELSEWHERE),
        "rm",
        "collection",
        COLLECTION_ID,
        CATALOG,
        FILE_DETAIL | {"uploaded_by": "alice", "uploaded_at": "2026-10-23T14:02:11.250000+00:00"},
    ),
    (
        MetadataPublished(**IN_COLLECTION, changes=CHANGES),
        "meta_publish",
        "collection",
        COLLECTION_ID,
        CATALOG,
        {"version": 3, "changes": CHANGES_DETAIL},
    ),
    (
        CollectionMoved(
            **IN_COLLECTION, from_identifier="helio.psp.run042", to_identifier="helio.psp.run043"
        ),
        "mv",
        "collection",
        COLLECTION_ID,
        CATALOG,
        {"version": 3, "from_identifier": "helio.psp.run042", "to_identifier": "helio.psp.run043"},
    ),
    (
        CollectionDeleted(
            **IN_COLLECTION, state=CollectionState.DRAFT, identifier="helio.psp.run042"
        ),
        "delete",
        "collection",
        COLLECTION_ID,
        CATALOG,
        {"version": 3, "state": "draft", "identifier": "helio.psp.run042"},
    ),
    (
        CatalogCreated(catalog=CATALOG, name="helio", config_version=1),
        "create",
        "catalog",
        CATALOG_ID,
        CATALOG,
        {"name": "helio", "config_version": 1},
    ),
    (
        CatalogConfigChanged(catalog=CATALOG, config_version=2, changes=CHANGES),
        "catalog_config",
        "catalog",
        CATALOG_ID,
        CATALOG,
        {"config_version": 2, "changes": CHANGES_DETAIL},
    ),
    (
        SchemaPublished(schema=SCHEMA, name="helio", version=1, extends_id=BASE_SCHEMA),
        "schema_publish",
        "metadata_schema",
        "00000000-0000-0000-0000-000000000004",
        None,
        {"name": "helio", "version": 1, "extends_id": "00000000-0000-0000-0000-000000000005"},
    ),
    (
        RoleMapped(
            ldap_group="helio-readers",
            catalog=CATALOG,
            old_role=None,
            new_role=Role.CATALOG_READER,
            posix_gid=70100,
        ),
        "role_map",
        "ldap_group",
        "helio-readers",
        CATALOG,
        {"old_role": None, "new_role": "catalog_reader", "posix_gid": 70100},
    ),
    (
        KeyRotated(kid="2026-10-23-a", alg="ES256", active_from=AT_ELSEWHERE, retired_kid=None),
        "key_rotate",
        "signing_key",
        "2026-10-23-a",
        None,
        {
            "alg": "ES256",
            "active_from": "2026-10-23T14:02:11.250000+00:00",
            "retired_kid": None,
        },
    ),
    (
        KeyWithdrawn(kid="2026-10-23-a", active_from=AT_ELSEWHERE),
        "key_withdraw",
        "signing_key",
        "2026-10-23-a",
        None,
        {"active_from": "2026-10-23T14:02:11.250000+00:00"},
    ),
]
COLLECTION_EVENTS = [row[0] for row in VOCABULARY_ROWS if row[2] == "collection"]
CREATED = VOCABULARY_ROWS[0][0]
NAIVE_EVENT_INSTANTS = [
    pytest.param(
        {"event": replace(event, **{field.name: AT.replace(tzinfo=None)})},
        id=f"{type(event).__name__}.{field.name}",
    )
    for event, *_ in VOCABULARY_ROWS
    for field in fields(event)
    if isinstance(getattr(event, field.name), datetime)
]


def entry(event: AuditEvent = CREATED, **envelope: Any) -> AuditEntry:
    """Build an entry by a company user at a fixed instant, overriding any envelope field."""
    return AuditEntry(**({"at": AT, "actor": "scientist", "event": event} | envelope))


@pytest.mark.parametrize(
    ("event", "action", "object_type", "object_id", "catalog_id", "detail"), VOCABULARY_ROWS
)
def test_each_event_renders_its_vocabulary_row(
    event: AuditEvent,
    action: str,
    object_type: str,
    object_id: str,
    catalog_id: UUID | None,
    detail: dict[str, JsonValue],
) -> None:
    """Pair, object id, catalog and detail keys, with canonical UUIDs, UTC instants and nulls."""
    recorded = entry(event)
    assert (action, object_type) == (type(event).ACTION, type(event).OBJECT)
    assert recorded.object_id == object_id
    assert recorded.catalog_id == catalog_id
    assert recorded.detail() == detail


def test_vocabulary_is_exactly_the_fourteen_pairs_of_the_event_classes() -> None:
    """The pair set derives from the events, key withdrawal included, and nothing else."""
    pairs = {(row[1], row[2]) for row in VOCABULARY_ROWS}
    assert len(VOCABULARY_ROWS) == len(pairs) == 14
    assert pairs == AUDIT_VOCABULARY
    assert ("key_withdraw", "signing_key") in AUDIT_VOCABULARY
    assert all(
        isinstance(a, AuditAction) and isinstance(o, AuditObject) for a, o in AUDIT_VOCABULARY
    )
    assert {action for action, _ in AUDIT_VOCABULARY} == set(AuditAction)
    assert {object_type for _, object_type in AUDIT_VOCABULARY} == set(AuditObject)


@pytest.mark.parametrize("event", [row[0] for row in VOCABULARY_ROWS])
def test_events_are_frozen_and_keyword_only(event: AuditEvent) -> None:
    """An event cannot change after construction or be built from positional values."""
    with pytest.raises(FrozenInstanceError):
        setattr(event, type(event).KEY, "changed")
    with pytest.raises(TypeError):
        type(event)(*(getattr(event, field.name) for field in fields(event)))


@pytest.mark.parametrize("state", list(CollectionState))
def test_deletion_records_the_exact_state_code(state: CollectionState) -> None:
    """Every lifecycle state is recorded by its code, and only a draft is unsettled."""
    deleted = replace(VOCABULARY_ROWS[7][0], state=state)
    assert entry(deleted).detail()["state"] == state.value
    assert type(entry(deleted).detail()["state"]) is str
    assert state.settled is (state is not CollectionState.DRAFT)


@pytest.mark.parametrize(
    "envelope",
    [
        {"at": AT.replace(tzinfo=None)},
        {"actor": ""},
        {"actor": "two words"},
        {"actor": "-leading-dash"},
        {"actor": "slash/name"},
        {"reason": ""},
        {"reason": "   "},
        {"reason": " padded"},
        {"reason": "padded\n"},
        {"reason": "x" * (AUDIT_REASON_MAX + 1)},
        *NAIVE_EVENT_INSTANTS,
    ],
)
def test_entry_refuses_an_invalid_instant_actor_or_reason(envelope: dict[str, Any]) -> None:
    """Naive entry or event instants, unknown actors and malformed reasons are bugs."""
    with pytest.raises(ValueError, match="audit"):
        entry(**envelope)


@pytest.mark.parametrize(
    "actor", ["scientist", "A.z_1@example.org", "u" * 128, SYSTEM_BOOTSTRAP, "system:reconciler"]
)
@pytest.mark.parametrize("reason", [None, "x", "x" * AUDIT_REASON_MAX])
def test_entry_accepts_company_and_system_actors_with_bounded_reasons(
    actor: str, reason: str | None
) -> None:
    """A company username or `system:` actor and a 1 to 1,000 character reason are kept."""
    accepted = entry(actor=actor, reason=reason)
    assert (accepted.actor, accepted.reason) == (actor, reason)


@pytest.mark.parametrize(
    "event",
    [
        *(replace(event, version=0) for event in COLLECTION_EVENTS),
        replace(VOCABULARY_ROWS[10][0], version=0),
        replace(VOCABULARY_ROWS[10][0], version=-1),
    ],
)
def test_entry_refuses_a_version_below_one(event: AuditEvent) -> None:
    """Collection versions and schema versions start at 1."""
    with pytest.raises(ValueError, match="version"):
        entry(event)


@pytest.mark.parametrize(
    "event",
    [
        replace(VOCABULARY_ROWS[5][0], changes=()),
        replace(VOCABULARY_ROWS[9][0], changes=()),
    ],
)
def test_entry_refuses_an_empty_change_list(event: AuditEvent) -> None:
    """A publish whose diff is empty is a no-op and records nothing."""
    with pytest.raises(ValueError, match="change list"):
        entry(event)


@pytest.mark.parametrize("role", [None, *Role])
def test_role_change_refuses_equal_roles(role: Role | None) -> None:
    """A mapping event always changes the role; both absent is no change."""
    catalog = None if role is None or not role.catalog_scoped else CATALOG
    with pytest.raises(ValueError, match="must change"):
        RoleMapped(ldap_group="g", catalog=catalog, old_role=role, new_role=role, posix_gid=1)


@pytest.mark.parametrize(
    ("catalog", "old_role", "new_role"),
    [
        (None, None, Role.CATALOG_READER),
        (None, Role.CATALOG_OWNER, None),
        (None, Role.ADMINISTRATOR, Role.CATALOG_CONTRIBUTOR),
        (CATALOG, None, Role.ADMINISTRATOR),
        (CATALOG, Role.ADMINISTRATOR, Role.CATALOG_OWNER),
    ],
)
def test_role_change_refuses_a_role_outside_its_scope(
    catalog: UUID | None, old_role: Role | None, new_role: Role | None
) -> None:
    """Catalog roles need a catalog, and the organization Administrator role takes none."""
    with pytest.raises(ValueError, match="scope"):
        RoleMapped(
            ldap_group="g", catalog=catalog, old_role=old_role, new_role=new_role, posix_gid=1
        )


@pytest.mark.parametrize(
    ("catalog", "old_role", "new_role"),
    [
        (CATALOG, Role.CATALOG_READER, Role.CATALOG_OWNER),
        (CATALOG, Role.CATALOG_CONTRIBUTOR, None),
        (None, None, Role.ADMINISTRATOR),
        (None, Role.ADMINISTRATOR, None),
    ],
)
def test_role_change_records_codes_and_nulls_in_its_scope(
    catalog: UUID | None, old_role: Role | None, new_role: Role | None
) -> None:
    """Grants, changes and removals encode role codes and the organization scope has no catalog."""
    event = RoleMapped(
        ldap_group="g", catalog=catalog, old_role=old_role, new_role=new_role, posix_gid=70001
    )
    recorded = entry(event)
    assert recorded.catalog_id == catalog
    assert recorded.detail() == {
        "old_role": old_role.code if old_role else None,
        "new_role": new_role.code if new_role else None,
        "posix_gid": 70001,
    }


def test_detail_refuses_a_value_it_cannot_encode() -> None:
    """A field outside the encoding rules raises rather than emitting non-JSON detail."""
    malformed = replace(VOCABULARY_ROWS[8][0], name=1.5)
    with pytest.raises(TypeError, match="float"):
        entry(malformed).detail()


def test_no_audit_mutation_in_src() -> None:
    """No application source updates, deletes or truncates the append-only audit log."""
    mutation = re.compile(
        r"UPDATE\s+lake\.audit_log|DELETE\s+FROM\s+lake\.audit_log|TRUNCATE\s+lake\.audit_log",
        re.IGNORECASE,
    )
    sources = sorted((Path(__file__).parents[2] / "src" / "huron").rglob("*.py"))
    assert sources
    assert [path for path in sources if mutation.search(path.read_text(encoding="utf-8"))] == []
