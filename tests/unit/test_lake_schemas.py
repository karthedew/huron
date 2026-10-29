"""The metadata schema registry: publish preconditions, reads, resolution and the row cache."""

from __future__ import annotations

import inspect
import json
from typing import TYPE_CHECKING, Any
from uuid import UUID

import pytest

from huron.core.foundation.canonical import content_identity
from huron.core.foundation.errors import Forbidden, IdempotencyKeyReused, ResourceNotFound
from huron.core.foundation.retry import IdempotencyClaim, Replay, request_sha256
from huron.core.lake import MetadataSchemaRecord, MetadataSchemas, Published, SchemaParts
from huron.core.lake.errors import PROBLEMS_SHOWN, SchemaInvalid, SchemaVersionExists
from huron.core.lake.ports import SchemaResolver
from huron.core.lake.types import is_segment
from huron.core.metastore.lake import InMemoryLakeStore
from huron.core.metastore.lake.memory import IntegrityViolation
from huron.core.security.broker import CatalogRef, Grant, Role
from huron.schema import load_schema
from huron.schema.catalog_config import SchemaRef
from huron.schema.metadata import DRAFT_2020_12
from tests.lake_store_contract import insert_schemas, schema_record
from tests.unit.support import lake_actor

if TYPE_CHECKING:
    from tests.unit.support import FakeClock

pytestmark = pytest.mark.unit
ADMIN = lake_actor(Grant(Role.ADMINISTRATOR, None), subject="admin")
BASE = load_schema("org-base-v1.json")
ORG_1 = SchemaRef("org", 1)
CATALOG = CatalogRef(UUID(int=1), "heliophysics")


def claim_for(
    name: str, version: Any, extends: SchemaRef | None, document: Any, *, key: str | None = None
) -> IdempotencyClaim:
    """Fingerprint a publish body under a key derived from it unless one is given."""
    body = json.dumps([name, version, repr(extends), document], sort_keys=True)
    fingerprint = request_sha256("metadata_schema", body)
    return IdempotencyClaim(ADMIN.subject, key or fingerprint[:32], fingerprint)


async def publish(
    registry: MetadataSchemas,
    name: str,
    version: Any,
    extends: SchemaRef | None,
    document: Any,
    *,
    key: str | None = None,
) -> Published:
    """Publish as the Administrator with a claim fingerprinting the body."""
    claim = claim_for(name, version, extends, document, key=key)
    return await registry.publish(ADMIN, name, version, extends, document, claim=claim)


async def refusal(registry: MetadataSchemas, *request: Any) -> list[tuple[str, str]]:
    """Publish an invalid request and return its problems as `(where, rule)` pairs."""
    with pytest.raises(SchemaInvalid) as caught:
        await publish(registry, *request)
    assert caught.value.status_code == 422
    return [(p["where"], p["rule"]) for p in caught.value.context["problems"]]


@pytest.fixture
def store(clock: FakeClock) -> InMemoryLakeStore:
    """An empty, seeded in-memory lake store on the shared clock."""
    return InMemoryLakeStore(clock=clock)


@pytest.fixture
def registry(store: InMemoryLakeStore, clock: FakeClock) -> MetadataSchemas:
    """A registry over the test store, reading instants from the shared clock."""
    return MetadataSchemas(store, clock)


@pytest.fixture
async def base(registry: MetadataSchemas) -> MetadataSchemaRecord:
    """The packaged org base, published as `org` version 1."""
    return (await publish(registry, "org", 1, None, BASE)).record


async def test_publishes_the_base_then_an_extension_with_entries_and_receipts(
    registry: MetadataSchemas,
    store: InMemoryLakeStore,
    clock: FakeClock,
    metadata_extension_document: dict[str, Any],
) -> None:
    """Each publish stores its row as submitted, one audit entry and its retry receipt."""
    first = await publish(registry, "org", 1, None, BASE)
    extension = await publish(
        registry, "heliophysics", 1, ORG_1, metadata_extension_document, key="helio"
    )
    assert first.created and extension.created
    base = first.record
    assert (base.name, base.version, base.extends_id) == ("org", 1, None)
    assert base.document == BASE
    assert base.sha256 == content_identity(BASE)
    assert (base.created_at, base.created_by) == (clock.now(), "admin")
    assert base.id.version == 7
    assert extension.record.extends_id == base.id
    assert extension.record.document == metadata_extension_document
    assert await store.by_ref("heliophysics", 1) == extension.record
    records = [store.tables.audit_log[key] for key in sorted(store.tables.audit_log)]
    assert [(r.action, r.object_type, r.object_id, r.catalog_id) for r in records] == [
        ("schema_publish", "metadata_schema", str(base.id), None),
        ("schema_publish", "metadata_schema", str(extension.record.id), None),
    ]
    assert [r.detail for r in records] == [
        {"name": "org", "version": 1, "extends_id": None},
        {"name": "heliophysics", "version": 1, "extends_id": str(base.id)},
    ]
    receipt = store.tables.idempotency_records[("admin", "helio")].replay
    assert receipt == Replay("metadata_schema", extension.record.id)


@pytest.mark.parametrize(
    "grants",
    [
        (),
        (Grant(Role.CATALOG_READER, CATALOG),),
        (Grant(Role.CATALOG_CONTRIBUTOR, CATALOG),),
        (Grant(Role.CATALOG_OWNER, CATALOG),),
    ],
)
async def test_only_an_administrator_publishes(
    registry: MetadataSchemas, store: InMemoryLakeStore, grants: tuple[Grant, ...]
) -> None:
    """Every role below the organization Administrator is refused before anything is read."""
    actor = lake_actor(*grants, subject="admin")
    with pytest.raises(Forbidden) as caught:
        await registry.publish(actor, "org", 1, None, BASE, claim=claim_for("org", 1, None, BASE))
    assert caught.value.status_code == 403
    assert not store.tables.metadata_schemas


async def test_a_claim_must_belong_to_the_publisher(
    registry: MetadataSchemas, store: InMemoryLakeStore
) -> None:
    """An Administrator cannot publish under another principal's retry key."""
    claim = IdempotencyClaim("colleague", "key", request_sha256("metadata_schema", "org"))
    with pytest.raises(Forbidden, match="claim"):
        await registry.publish(ADMIN, "org", 1, None, BASE, claim=claim)
    assert not store.tables.idempotency_records


async def test_a_replay_answers_the_first_result_and_another_body_is_refused(
    registry: MetadataSchemas, store: InMemoryLakeStore, base: MetadataSchemaRecord
) -> None:
    """The same key and body replays the created version; another body under it is 409."""
    document = {"$schema": DRAFT_2020_12, "type": "object", "title": "second"}
    first = await publish(registry, "org", 2, None, document, key="retry")
    assert await publish(registry, "org", 2, None, document, key="retry") == first
    assert first == Published(await store.by_ref("org", 2), created=True)
    with pytest.raises(IdempotencyKeyReused) as caught:
        await publish(registry, "org", 3, None, document, key="retry")
    assert caught.value.status_code == 409
    assert len(store.tables.metadata_schemas) == 2
    assert len(store.tables.audit_log) == 2


@pytest.mark.parametrize(
    ("name", "version", "expected"),
    [
        ("Org", 1, [("/extends", "extends"), ("/name", "name")]),
        ("", 1, [("/extends", "extends"), ("/name", "name")]),
        ("a" * 65, 1, [("/extends", "extends"), ("/name", "name")]),
        ("org", 0, [("/version", "version")]),
        ("org", -1, [("/version", "version")]),
        ("org", True, [("/version", "version")]),
    ],
)
async def test_names_and_versions_are_strict(
    registry: MetadataSchemas, name: str, version: Any, expected: list[tuple[str, str]]
) -> None:
    """A name must be a segment, unchanged, and a version a positive integer."""
    assert await refusal(registry, name, version, None, BASE) == expected


async def test_the_base_extends_nothing_and_an_extension_extends_a_published_base(
    registry: MetadataSchemas,
    base: MetadataSchemaRecord,
    metadata_extension_document: dict[str, Any],
) -> None:
    """`org` names no base; any other series names a published org version, never an extension."""
    await publish(registry, "heliophysics", 1, ORG_1, metadata_extension_document)
    part = metadata_extension_document
    for request in [
        ("org", 2, ORG_1, BASE),
        ("geology", 1, None, part),
        ("geology", 1, SchemaRef("org", 2), part),
        ("geology", 1, SchemaRef("heliophysics", 1), part),
    ]:
        assert await refusal(registry, *request) == [("/extends", "extends")]


@pytest.mark.parametrize(
    ("patch", "expected"),
    [
        (
            {"$schema": "https://json-schema.org/draft-07/schema"},
            ("/json_schema/$schema", "dialect"),
        ),
        ({"type": "array"}, ("/json_schema/type", "root_type")),
        ({"unevaluatedProperties": False}, ("/json_schema/unevaluatedProperties", "closed")),
        ({"properties": {"Bad": {}}}, ("/json_schema/properties/Bad", "field_name")),
        ({"$ref": "other.json#/x"}, ("/json_schema/$ref", "ref")),
        (
            {"properties": {"x": {"pattern": "(?=a)b"}}},
            ("/json_schema/properties/x/pattern", "regex"),
        ),
        ({"minProperties": -1}, ("/json_schema/minProperties", "metaschema")),
        ({"description": "x" * 262_144}, ("/json_schema", "size")),
        ({"examples": [2**53]}, ("/json_schema", "size")),
        ({"examples": [float("nan")]}, ("/json_schema", "size")),
    ],
)
async def test_each_publication_rule_points_into_the_document(
    registry: MetadataSchemas,
    metadata_schema_document: dict[str, Any],
    patch: dict[str, Any],
    expected: tuple[str, str],
) -> None:
    """A document breaking one publication rule is refused with that rule under `json_schema`."""
    assert expected in await refusal(registry, "org", 1, None, metadata_schema_document | patch)


async def test_request_and_document_problems_are_reported_together_and_capped(
    registry: MetadataSchemas, metadata_schema_document: dict[str, Any]
) -> None:
    """Every failure is counted; the first fifty are reported in pointer order."""
    fields = [f"F{index:02}" for index in range(60)]
    document = metadata_schema_document | {"properties": {name: {} for name in fields}}
    with pytest.raises(SchemaInvalid) as caught:
        await publish(registry, "Bad", 0, None, document)
    context = caught.value.context
    assert context["total"] == 63
    assert [(p["where"], p["rule"]) for p in context["problems"]] == [
        ("/extends", "extends"),
        *(
            ("/json_schema/properties/" + name, "field_name")
            for name in fields[: PROBLEMS_SHOWN - 1]
        ),
    ]


async def test_an_extension_that_does_not_compose_with_its_base_is_refused(
    registry: MetadataSchemas, store: InMemoryLakeStore, metadata_schema_document: dict[str, Any]
) -> None:
    """A part meeting every document rule still needs a base it composes with."""
    unusable = schema_record(document={"type": "object"})
    await insert_schemas(store, unusable)
    request = ("geology", 1, ORG_1, metadata_schema_document)
    assert await refusal(registry, *request) == [("/json_schema", "composition")]


async def test_republishing_the_latest_version_unchanged_writes_nothing(
    registry: MetadataSchemas, store: InMemoryLakeStore, base: MetadataSchemaRecord
) -> None:
    """An identical republish answers the latest version without a row, an entry or a receipt."""
    replayed = await publish(registry, "org", 1, None, dict(BASE), key="again")
    assert replayed == Published(base, created=False)
    assert len(store.tables.metadata_schemas) == 1
    assert len(store.tables.audit_log) == 1
    assert store.tables.idempotency_records[("admin", "again")].replay is None


async def test_a_taken_version_is_refused_with_the_latest_version(
    registry: MetadataSchemas, base: MetadataSchemaRecord, metadata_schema_document: dict[str, Any]
) -> None:
    """Changed content at a published version, or any earlier version, is 409."""
    await publish(registry, "org", 2, None, metadata_schema_document)
    taken = [(2, BASE), (1, BASE), (1, metadata_schema_document)]
    for index, (version, document) in enumerate(taken):
        with pytest.raises(SchemaVersionExists) as caught:
            await publish(registry, "org", version, None, document, key=f"taken-{index}")
        assert caught.value.status_code == 409
        assert caught.value.context == {"name": "org", "version": version, "latest_version": 2}


async def test_a_skipped_version_is_refused_as_a_gap(
    registry: MetadataSchemas,
    base: MetadataSchemaRecord,
    metadata_extension_document: dict[str, Any],
) -> None:
    """A version must directly follow its series' latest, starting at 1 for a new name."""
    assert await refusal(registry, "org", 3, None, BASE) == [("/version", "version_gap")]
    request = ("heliophysics", 2, ORG_1, metadata_extension_document)
    assert await refusal(registry, *request) == [("/version", "version_gap")]


async def test_the_audit_entry_rolls_back_with_its_row(clock: FakeClock) -> None:
    """When the entry cannot be appended, neither the version nor its claim remains."""
    store = InMemoryLakeStore(clock=clock, seed=False)
    with pytest.raises(IntegrityViolation, match="audit_log_vocabulary"):
        await publish(MetadataSchemas(store, clock), "org", 1, None, BASE)
    assert not store.tables.metadata_schemas
    assert not store.tables.audit_log
    assert not store.tables.idempotency_records


async def test_get_reads_one_version_for_any_actor(
    registry: MetadataSchemas, base: MetadataSchemaRecord
) -> None:
    """Schemas are organization-wide; an unknown version is not found."""
    assert await registry.get(lake_actor(), "org", 1) == base
    for name, version in [("org", 2), ("geology", 1)]:
        with pytest.raises(ResourceNotFound) as caught:
            await registry.get(lake_actor(), name, version)
        assert caught.value.status_code == 404


async def test_list_pages_by_name_then_version(
    registry: MetadataSchemas,
    base: MetadataSchemaRecord,
    metadata_extension_document: dict[str, Any],
) -> None:
    """Pages follow the `(name, version)` key for any actor."""
    await publish(registry, "org", 2, None, metadata_extension_document)
    await publish(registry, "heliophysics", 1, ORG_1, metadata_extension_document)
    first = await registry.list(lake_actor(), None, 2)
    assert [(r.name, r.version) for r in first.items] == [("heliophysics", 1), ("org", 1)]
    assert first.has_more
    rest = await registry.list(lake_actor(), ("org", 1), 2)
    assert [(r.name, r.version) for r in rest.items] == [("org", 2)]
    assert not rest.has_more


async def test_resolve_pairs_a_reference_with_its_base_and_never_caches(
    registry: MetadataSchemas,
    store: InMemoryLakeStore,
    base: MetadataSchemaRecord,
    metadata_extension_document: dict[str, Any],
) -> None:
    """The base resolves alone and an extension with its base; references are always read."""
    extension = (
        await publish(registry, "heliophysics", 1, ORG_1, metadata_extension_document)
    ).record
    assert await registry.resolve(ORG_1) == SchemaParts(base, None)
    assert await registry.resolve(SchemaRef("heliophysics", 1)) == SchemaParts(base, extension)
    assert await registry.resolve(SchemaRef("geology", 1)) is None
    del store.tables.metadata_schema_refs[("org", 1)]
    assert await registry.resolve(ORG_1) is None


async def test_parts_answers_from_the_row_cache_after_the_first_read(
    store: InMemoryLakeStore,
    clock: FakeClock,
    metadata_extension_document: dict[str, Any],
) -> None:
    """Rows read by id stay cached up to the limit, least recently used first out."""
    registry = MetadataSchemas(store, clock, row_cache=2)
    base = (await publish(registry, "org", 1, None, BASE)).record
    extension = (
        await publish(registry, "heliophysics", 1, ORG_1, metadata_extension_document)
    ).record
    expected = SchemaParts(base, extension)
    assert await registry.parts(extension.id) == expected
    store.tables.metadata_schemas.clear()
    assert await registry.parts(extension.id) == expected
    assert await registry.parts(base.id) == SchemaParts(base, None)
    with pytest.raises(ResourceNotFound):
        await registry.parts(UUID(int=9))


@pytest.mark.parametrize(("size", "cached"), [(0, False), (1, True)])
async def test_the_row_cache_evicts_the_least_recently_used_row(
    store: InMemoryLakeStore, clock: FakeClock, size: int, cached: bool
) -> None:
    """A full cache drops its oldest row, and a cache of size 0 keeps none."""
    registry = MetadataSchemas(store, clock, row_cache=size)
    first = (await publish(registry, "org", 1, None, BASE)).record
    second = schema_record(version=2)
    await insert_schemas(store, second)
    await registry.parts(second.id)
    await registry.parts(first.id)
    store.tables.metadata_schemas.clear()
    if cached:
        assert await registry.parts(first.id) == SchemaParts(first, None)
    with pytest.raises(ResourceNotFound):
        await registry.parts(second.id)


def test_the_registry_resolves_schema_references_for_catalogs() -> None:
    """`MetadataSchemas` structurally satisfies the catalog consumer's resolver port."""
    expected = inspect.signature(SchemaResolver.resolve).parameters
    actual = inspect.signature(MetadataSchemas.resolve).parameters
    assert list(expected) == list(actual)


@pytest.mark.parametrize(
    ("value", "valid"),
    [
        ("heliophysics", True),
        ("a-b_9", True),
        ("a" * 64, True),
        ("a" * 65, False),
        ("Ext", False),
        ("", False),
        ("-a", False),
    ],
)
def test_is_segment_applies_the_shared_naming_rule(value: str, valid: bool) -> None:
    """The persistence-facing segment check accepts exactly the strict names."""
    assert is_segment(value) is valid


def test_a_record_owns_its_document_and_names_its_reference() -> None:
    """Changing the submitted document later cannot change the stored version."""
    document: dict[str, Any] = {"type": "object", "properties": {"x": {"type": "string"}}}
    record = schema_record("heliophysics", 3, document=document)
    document["properties"]["x"]["type"] = "integer"
    assert record.document["properties"] == {"x": {"type": "string"}}
    assert record.ref == SchemaRef("heliophysics", 3)


def test_parts_pair_one_base_with_its_own_extension() -> None:
    """The referenced part is the extension, or the base selected alone; mismatches are refused."""
    base = schema_record()
    extension = schema_record("heliophysics", extends=base)
    assert SchemaParts(base, extension).referenced == extension
    assert SchemaParts(base, None).referenced == base
    with pytest.raises(ValueError, match="extend nothing"):
        SchemaParts(extension, None)
    with pytest.raises(ValueError, match="paired"):
        SchemaParts(schema_record(version=2), extension)


def test_an_invalid_schema_needs_a_problem() -> None:
    """A schema refusal always names at least one problem."""
    with pytest.raises(ValueError, match="at least one problem"):
        SchemaInvalid([])
