"""The migrations build exactly the tables the code describes, and downgrade cleanly."""

import asyncio
import importlib.util
import uuid
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import pytest
from alembic import command

from tests.support.postgres import alembic_config, migrated_database, with_database

pytestmark = pytest.mark.contract

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_schema_map.py"


def test_schema_map_check_passes() -> None:
    spec = importlib.util.spec_from_file_location("check_schema_map", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main() == 0


def test_catalog_roles_at_organization_scope_arrive_with_revision_0002(database_url: str) -> None:
    organization = uuid.uuid4()
    with migrated_database(with_database(database_url, "postgres")) as url:
        asyncio.run(_grant(url, "organization", organization, "org_admin", "admins"))
        asyncio.run(_grant(url, "organization", organization, "reader", "everyone"))
        with pytest.raises(asyncpg.CheckViolationError):
            asyncio.run(_grant(url, "platform", None, "reader", "everyone"))
        command.downgrade(alembic_config(url), "0001_huron")
        assert asyncio.run(_roles(url)) == [("org_admin", "admins")]
        with pytest.raises(asyncpg.CheckViolationError):
            asyncio.run(_grant(url, "organization", organization, "reader", "everyone"))
        command.upgrade(alembic_config(url), "head")
        asyncio.run(_grant(url, "organization", organization, "contributor", "writers"))
        assert asyncio.run(_roles(url)) == [("contributor", "writers"), ("org_admin", "admins")]


def test_uploads_inodes_and_share_groups_arrive_with_revision_0003(database_url: str) -> None:
    with migrated_database(with_database(database_url, "postgres")) as url:
        assert asyncio.run(_revision_0003_objects(url)) == REVISION_0003
        command.downgrade(alembic_config(url), "0002_organization_catalog_roles")
        assert asyncio.run(_revision_0003_objects(url)) == set()
        command.upgrade(alembic_config(url), "head")
        assert asyncio.run(_revision_0003_objects(url)) == REVISION_0003


REVISION_0003 = {
    "table uploads",
    "table removals",
    "column uploads.inode bigint null",
    "column removals.inode bigint null",
    "column files.inode bigint null",
    "column catalogs.share_group text null",
    "constraint ck_uploads_inode",
}
"""What revision 0003 makes: its tables, the inode and share group columns, the inode check."""


def test_publication_tables_arrive_with_revision_0004(database_url: str) -> None:
    with migrated_database(with_database(database_url, "postgres")) as url:
        assert asyncio.run(_revision_0004_objects(url)) == REVISION_0004
        command.downgrade(alembic_config(url), "0003_uploads")
        assert asyncio.run(_revision_0004_objects(url)) == set()
        assert asyncio.run(_revision_0003_objects(url)) == REVISION_0003
        command.upgrade(alembic_config(url), "head")
        assert asyncio.run(_revision_0004_objects(url)) == REVISION_0004


REVISION_0004 = {
    "table objects",
    "table staged_uploads",
    "table staged_upload_ids",
    "table commit_requests",
    "table commit_entries",
    "column files.object_id uuid null",
    "column collections.pending_request_id uuid null",
    "constraint uq_staged_uploads_subject_attempt_id",
    "constraint pk_staged_upload_ids",
    "constraint fk_staged_uploads_current_upload_id deferred",
    "constraint uq_commit_requests_subject_request_id",
    "constraint uq_files_object_id",
    "constraint uq_collections_pending_request_id",
}
"""What revision 0004 makes: its tables, the two columns and the keys that the design names."""


async def _revision_0004_objects(url: str) -> set[str]:
    connection = await asyncpg.connect(url)
    try:
        rows = await connection.fetch(
            "select 'table ' || table_name as name from information_schema.tables"
            " where table_schema = 'huron' and table_name in ('objects', 'staged_uploads',"
            " 'staged_upload_ids', 'commit_requests', 'commit_entries')"
            " union all select 'column ' || table_name || '.' || column_name || ' ' || data_type"
            " || case is_nullable when 'YES' then ' null' else ' not null' end"
            " from information_schema.columns where table_schema = 'huron'"
            " and column_name in ('object_id', 'pending_request_id')"
            " and table_name in ('files', 'collections')"
            " union all select 'constraint ' || conname"
            " || case when condeferred then ' deferred' else '' end from pg_constraint"
            " where conname in ('uq_staged_uploads_subject_attempt_id', 'pk_staged_upload_ids',"
            " 'fk_staged_uploads_current_upload_id', 'uq_commit_requests_subject_request_id',"
            " 'uq_files_object_id', 'uq_collections_pending_request_id')"
        )
    finally:
        await connection.close()
    return {row["name"] for row in rows}


async def _revision_0003_objects(url: str) -> set[str]:
    connection = await asyncpg.connect(url)
    try:
        rows = await connection.fetch(
            "select 'table ' || table_name as name from information_schema.tables"
            " where table_schema = 'huron' and table_name in ('uploads', 'removals')"
            " union all select 'column ' || table_name || '.' || column_name || ' ' || data_type"
            " || case is_nullable when 'YES' then ' null' else ' not null' end"
            " from information_schema.columns where table_schema = 'huron'"
            " and column_name in ('inode', 'share_group')"
            " and table_name in ('uploads', 'removals', 'files', 'catalogs')"
            " union all select 'constraint ' || conname from pg_constraint"
            " where conname = 'ck_uploads_inode'"
        )
    finally:
        await connection.close()
    return {row["name"] for row in rows}


async def _grant(
    url: str, scope_type: str, scope_id: uuid.UUID | None, role: str, group: str
) -> None:
    connection = await asyncpg.connect(url)
    try:
        await connection.execute(
            "insert into huron.grants (id, scope_type, scope_id, role, ldap_group, created_at,"
            " created_by) values ($1, $2, $3, $4, $5, $6, 't')",
            uuid.uuid4(),
            scope_type,
            scope_id,
            role,
            group,
            datetime.now(UTC),
        )
    finally:
        await connection.close()


async def _roles(url: str) -> list[tuple[str, str]]:
    connection = await asyncpg.connect(url)
    try:
        rows = await connection.fetch("select role, ldap_group from huron.grants order by role")
    finally:
        await connection.close()
    return [(row["role"], row["ldap_group"]) for row in rows]
