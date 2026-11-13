"""Uploads through the real upload proxy and tusd, on the real application.

The API runs in a child process over PostgreSQL and a temporary lake, with ``uploads_url`` set
to the proxy. nginx and tusd run in Docker containers from ``docker-compose.uploads.yml`` and the
nginx template, with host networking, over the same lake as the user of the test. Each tus request
of a test goes through nginx, which asks the API before it passes the request to tusd.

The collection ``run7`` of the seeded catalog starts active and empty.
"""

import base64
import json
import os
import socket
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest

from huron.applications.cli.uploads import CHUNK_SIZE
from huron.core.storage import UPLOAD_DIR
from huron.schema.naming import PART_SUFFIX
from tests.support.api import active_collection, mark_lake, seed_service
from tests.support.crash import ChildApi, read_facts, until
from tests.support.hostcli import HostCli
from tests.support.postgres import truncate
from tests.support.publication import sha256
from tests.support.uploadstack import HOOK_TIMEOUT, UploadStack

pytestmark = pytest.mark.integration

TUS = {"Tus-Resumable": "1.0.0"}
OFFSET_STREAM = {"Content-Type": "application/offset+octet-stream"}
MIB = 1024 * 1024


@dataclass(frozen=True)
class Site:
    """The child API, the upload stack in front of it, and the empty collection ``run7``."""

    api: ChildApi
    stack: UploadStack
    collection_id: str
    version: int
    directory: Path
    tus: httpx.AsyncClient

    @property
    def uploads(self) -> Path:
        """tusd's ``.tus-uploads`` on the lake."""
        return self.api.lake / UPLOAD_DIR

    async def auth(self, user: str | None) -> dict[str, str]:
        """The ``Authorization`` header of ``user``, none for ``None``."""
        if user is None:
            return {}
        headers = await self.api.headers(user)
        return {"Authorization": headers["Authorization"]}

    async def create(
        self, user: str, rel_path: str, size: int, attempt_id: str | None = None
    ) -> tuple[str, str]:
        """Create an upload of ``size`` bytes to ``rel_path``; its attempt ID and upload ID."""
        attempt_id = attempt_id or str(uuid.uuid4())
        answer = await self.post(user, rel_path, size, attempt_id)
        assert answer.status_code == 201, answer.text
        return attempt_id, urlsplit(answer.headers["Location"]).path.rsplit("/", 1)[1]

    async def post(
        self, user: str, rel_path: str, size: int, attempt_id: str, **headers: str
    ) -> httpx.Response:
        """The creating ``POST /files/`` of an upload, with ``headers``."""
        metadata = {
            "attempt_id": attempt_id,
            "collection": self.collection_id,
            "rel_path": rel_path,
        }
        sent = {
            **TUS,
            **await self.auth(user),
            "Upload-Length": str(size),
            "Upload-Metadata": _metadata(metadata),
            **headers,
        }
        return await self.tus.post("/files/", headers=sent)

    async def patch(
        self, user: str | None, upload_id: str, offset: int, data: bytes
    ) -> httpx.Response:
        """A ``PATCH`` of ``data`` at ``offset``."""
        headers = {**TUS, **OFFSET_STREAM, **await self.auth(user), "Upload-Offset": str(offset)}
        return await self.tus.patch(f"/files/{upload_id}", headers=headers, content=data)

    async def head(self, user: str | None, upload_id: str) -> httpx.Response:
        """A ``HEAD`` of the upload."""
        return await self.tus.head(f"/files/{upload_id}", headers={**TUS, **await self.auth(user)})

    async def attempt(self, attempt_id: str) -> dict[str, Any]:
        """dave's read of his attempt, which runs the API's own seal check."""
        answer = await self.api.client.get(
            f"/api/v1/upload-attempts/{attempt_id}", headers=await self.api.headers("dave")
        )
        assert answer.status_code == 200, answer.text
        found: dict[str, Any] = answer.json()
        return found

    async def commit(
        self,
        base_version: int,
        adds: list[tuple[str, bytes, str]],
        removes: list[str] | None = None,
    ) -> httpx.Response:
        """dave's commit; each add is a path, its bytes and its upload ID."""
        body = {
            "request_id": str(uuid.uuid4()),
            "base_version": base_version,
            "adds": [
                {"rel_path": path, "size": len(data), "sha256": sha256(data), "upload_id": upload}
                for path, data, upload in adds
            ],
            "removes": removes or [],
            "host": "ws1",
            "message": "an upload test commit",
        }
        return await self.api.client.post(
            f"/api/v1/collections/{self.collection_id}/commits",
            json=body,
            headers=await self.api.headers("dave"),
        )

    def data_size(self, upload_id: str) -> int:
        """The size of tusd's data file of the upload."""
        return (self.uploads / upload_id).stat().st_size


@pytest.fixture
async def site(database_url: str, tmp_path: Path) -> AsyncIterator[Site]:
    """The child API with uploads, the upload stack, and the empty active collection ``run7``."""
    await truncate(database_url)
    lake = mark_lake(tmp_path / "lake")
    stack = UploadStack(lake, tmp_path)
    api = ChildApi(
        database_url,
        lake,
        tmp_path / "child",
        uploads_url=stack.url,
        upload_hook_timeout=HOOK_TIMEOUT,
    )
    tus = httpx.AsyncClient(base_url=f"http://127.0.0.1:{stack.proxy_port}", timeout=120)
    try:
        await api.start()
        port = api.client.base_url.port
        assert port is not None
        stack.start(port)
        await seed_service(api)
        collection = await active_collection(api)
        directory = lake.joinpath(*collection["path"].split("/"))
        yield Site(api, stack, collection["id"], collection["version"], directory, tus)
    finally:
        await tus.aclose()
        stack.close()
        await api.close()


@pytest.fixture
def cli(site: Site, tmp_path: Path) -> Iterator[HostCli]:
    """The CLI on the host for the child API, with the lake as its mount prefix."""
    home = tmp_path / "home"
    home.mkdir()
    running = HostCli(home, str(site.api.client.base_url), site.api.lake)
    yield running
    running.close()


async def test_the_rendered_proxy_configuration_passes_nginx_test(site: Site) -> None:
    tested = site.stack.nginx_test()
    assert tested.returncode == 0, tested.stderr
    assert "test is successful" in tested.stderr


async def test_a_push_publishes_new_overwritten_removed_and_empty_files(
    site: Site, cli: HostCli, tmp_path: Path
) -> None:
    await login(site, cli, "dave")
    cli.huron("--catalog", "heliophysics", "checkout", "solar-wind.run7")
    data = tmp_path / "data"
    data.mkdir()
    (data / "a.txt").write_bytes(b"a, first version")
    (data / "b.txt").write_bytes(b"b, first version")
    (data / "c.txt").write_bytes(b"c in a directory that the commit makes")
    cli.huron("add", str(data / "a.txt"), str(data / "b.txt"))
    cli.huron("add", str(data / "c.txt"), "--as", "made/deep/c.txt")
    cli.huron("push", "-m", "three new files")
    assert files_of(site.directory) == {
        "a.txt": b"a, first version",
        "b.txt": b"b, first version",
        "made/deep/c.txt": b"c in a directory that the commit makes",
    }

    (data / "a.txt").write_bytes(b"a, second version with more bytes")
    (data / "empty.txt").write_bytes(b"")
    cli.huron("add", str(data / "a.txt"), str(data / "empty.txt"))
    cli.huron("rm", "b.txt", "made/deep/c.txt")
    cli.huron("push", "-m", "an overwrite, an empty file and two removals")

    assert files_of(site.directory) == {
        "a.txt": b"a, second version with more bytes",
        "empty.txt": b"",
    }
    assert not (site.directory / "made").exists()
    facts = await read_facts(site.api.database_url, site.collection_id)
    assert (facts.version, facts.file_count) == (site.version + 2, 2)
    assert facts.files["empty.txt"][0] == sha256(b"")
    listed = json.loads(cli.huron("-o", "json", "get", "files", "heliophysics.solar-wind.run7"))
    assert [entry["rel_path"] for entry in listed] == ["a.txt", "empty.txt"]


async def test_an_overwrite_beside_a_part_file_of_an_earlier_attempt_leaves_that_file(
    site: Site, cli: HostCli, tmp_path: Path
) -> None:
    await login(site, cli, "dave")
    cli.huron("--catalog", "heliophysics", "checkout", "solar-wind.run7")
    source = tmp_path / "a.txt"
    source.write_bytes(b"a, first version")
    cli.huron("add", str(source))
    cli.huron("push", "-m", "the first version")
    # The temporary name that a stopped publication of an earlier upload leaves beside a.txt.
    part = site.directory / f".a.txt.{uuid.uuid4()}{PART_SUFFIX}"
    part.write_bytes(b"bytes of an earlier attempt")

    source.write_bytes(b"a, second version")
    cli.huron("add", str(source))
    cli.huron("push", "-m", "an overwrite")

    assert (site.directory / "a.txt").read_bytes() == b"a, second version"
    assert part.read_bytes() == b"bytes of an earlier attempt"
    facts = await read_facts(site.api.database_url, site.collection_id)
    assert (facts.version, facts.files["a.txt"][0]) == (
        site.version + 2,
        sha256(b"a, second version"),
    )
    assert sorted(facts.files) == ["a.txt"]


async def test_a_chunk_of_64_mib_passes_the_proxy(site: Site) -> None:
    data = os.urandom(CHUNK_SIZE)
    attempt_id, upload_id = await site.create("dave", "large.bin", len(data))
    answer = await site.patch("dave", upload_id, 0, data)
    assert answer.status_code == 204, answer.text
    assert answer.headers["Upload-Offset"] == str(64 * MIB)
    attempt = await site.attempt(attempt_id)
    assert (attempt["state"], attempt["upload_id"]) == ("ready", upload_id)
    committed = await site.commit(site.version, [("large.bin", data, upload_id)])
    assert committed.status_code == 200, committed.text
    assert sha256((site.directory / "large.bin").read_bytes()) == sha256(data)


async def test_a_chunk_above_65_mib_is_refused_by_the_proxy(site: Site) -> None:
    _, upload_id = await site.create("dave", "large.bin", 66 * MIB)
    answer = await site.patch("dave", upload_id, 0, bytes(66 * MIB))
    assert answer.status_code == 413
    assert site.data_size(upload_id) == 0


async def test_a_patch_of_2_mib_passes_the_authorization_location(site: Site) -> None:
    attempt_id, upload_id = await site.create("dave", "two.bin", 4 * MIB)
    answer = await site.patch("dave", upload_id, 0, bytes(2 * MIB))
    assert answer.status_code == 204, answer.text
    assert answer.headers["Upload-Offset"] == str(2 * MIB)
    assert (await site.attempt(attempt_id))["state"] == "receiving"


async def test_an_upload_resumes_after_an_interrupted_patch(site: Site) -> None:
    data = os.urandom(3 * MIB)
    attempt_id, upload_id = await site.create("dave", "resumed.bin", len(data))
    sent = MIB
    await interrupted_patch(site, upload_id, data, sent)

    offset = await settled_offset(site, upload_id)
    assert 0 < offset <= sent
    assert site.data_size(upload_id) == offset
    answer = await site.patch("dave", upload_id, offset, data[offset:])
    assert answer.status_code == 204, answer.text
    assert (await site.attempt(attempt_id))["state"] == "ready"
    committed = await site.commit(site.version, [("resumed.bin", data, upload_id)])
    assert committed.status_code == 200, committed.text
    assert (site.directory / "resumed.bin").read_bytes() == data


async def test_a_final_patch_without_an_answer_is_sealed_and_committed(site: Site) -> None:
    data = b"bytes of a final PATCH whose answer the client never reads"
    attempt_id, upload_id = await site.create("dave", "unanswered.txt", len(data))
    request = await patch_request(site, upload_id, 0, len(data))
    with socket.create_connection(("127.0.0.1", site.stack.proxy_port)) as connection:
        connection.sendall(request + data)

        async def received() -> bool:
            lock = site.uploads / f"{upload_id}.lock"
            return site.data_size(upload_id) == len(data) and not lock.exists()

        await until(received, "tusd holds every byte and released the upload")
    attempt = await site.attempt(attempt_id)
    assert (attempt["state"], attempt["upload_id"]) == ("ready", upload_id)
    committed = await site.commit(site.version, [("unanswered.txt", data, upload_id)])
    assert committed.status_code == 200, committed.text
    assert (site.directory / "unanswered.txt").read_bytes() == data


async def test_a_late_completion_after_a_newer_commit_stays_private(site: Site) -> None:
    late = b"L" * 2000
    newer = b"the newer bytes of a.txt"
    late_attempt, late_upload = await site.create("dave", "a.txt", len(late))
    assert (await site.patch("dave", late_upload, 0, late[:1000])).status_code == 204
    newer_attempt, newer_upload = await site.create("dave", "a.txt", len(newer))
    assert (await site.patch("dave", newer_upload, 0, newer)).status_code == 204
    assert (await site.attempt(newer_attempt))["state"] == "ready"
    committed = await site.commit(site.version, [("a.txt", newer, newer_upload)])
    assert committed.status_code == 200, committed.text

    finished = await site.patch("dave", late_upload, 1000, late[1000:])
    assert finished.status_code == 204, finished.text
    assert (await site.attempt(late_attempt))["state"] == "ready"
    stale = await site.commit(site.version, [("a.txt", late, late_upload)])
    assert (stale.status_code, stale.json()["code"]) == (409, "BASE_VERSION_CONFLICT"), stale.text
    assert (site.directory / "a.txt").read_bytes() == newer
    facts = await read_facts(site.api.database_url, site.collection_id)
    assert (facts.version, facts.files["a.txt"][0]) == (site.version + 1, sha256(newer))


async def test_another_users_token_is_refused_on_head_and_patch_before_any_byte(
    site: Site,
) -> None:
    _, upload_id = await site.create("dave", "owned.txt", MIB)
    assert (await site.head("frank", upload_id)).status_code == 403
    assert (await site.patch("frank", upload_id, 0, bytes(MIB))).status_code == 403
    assert site.data_size(upload_id) == 0
    head = await site.head("dave", upload_id)
    assert (head.status_code, head.headers["Upload-Offset"]) == (200, "0")


async def test_a_request_without_a_token_is_refused_also_after_options(site: Site) -> None:
    _, upload_id = await site.create("dave", "owned.txt", 10)
    options = await site.tus.options(f"/files/{upload_id}", headers=TUS)
    assert options.status_code in {200, 204}
    assert "Tus-Version" in options.headers
    assert (await site.patch(None, upload_id, 0, b"0123456789")).status_code == 401
    assert (await site.patch("frank", upload_id, 0, b"0123456789")).status_code == 403
    assert (await site.head(None, upload_id)).status_code == 401
    assert site.data_size(upload_id) == 0


async def test_a_client_forwarded_header_does_not_change_the_location(site: Site) -> None:
    answer = await site.post(
        "dave",
        "forwarded.txt",
        10,
        str(uuid.uuid4()),
        **{
            "Host": "evil.example:8443",
            "X-Forwarded-Host": "evil.example",
            "X-Forwarded-Proto": "https",
            "Forwarded": "host=evil.example;proto=https",
        },
    )
    assert answer.status_code == 201, answer.text
    assert answer.headers["Location"].startswith(site.stack.url)


async def test_a_stale_lock_is_removed_before_tusd_starts(site: Site) -> None:
    _, upload_id = await site.create("dave", "locked.txt", 10)
    assert (await site.patch("dave", upload_id, 0, b"01234")).status_code == 204
    site.stack.kill_tusd()
    # After a kill, the lock file holds the process ID of the old tusd, which was 1.
    stale = [f"{upload_id}.lock", f"{upload_id}.lock.1234", f"{upload_id}.stop"]
    for name in stale:
        (site.uploads / name).write_text("1")
    site.stack.start_tusd()
    site.stack.wait_ready()
    assert [name for name in stale if (site.uploads / name).exists()] == []
    head = await site.head("dave", upload_id)
    assert (head.status_code, head.headers["Upload-Offset"]) == (200, "5")


async def test_a_commit_that_names_an_upload_that_is_not_ready_is_refused(site: Site) -> None:
    data = b"0123456789"
    _, upload_id = await site.create("dave", "partial.txt", len(data))
    assert (await site.patch("dave", upload_id, 0, data[:4])).status_code == 204
    refused = await site.commit(site.version, [("partial.txt", data, upload_id)])
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "UPLOAD_INELIGIBLE"
    assert not (site.directory / "partial.txt").exists()


async def test_a_link_in_place_of_a_namespace_directory_blocks_the_commit_in_the_lake(
    site: Site, tmp_path: Path
) -> None:
    data = b"bytes that must not leave the lake"
    attempt_id, upload_id = await site.create("dave", "a.txt", len(data))
    assert (await site.patch("dave", upload_id, 0, data)).status_code == 204
    assert (await site.attempt(attempt_id))["state"] == "ready"
    namespace = site.directory.parent
    outside = tmp_path / "outside"
    namespace.rename(outside)
    namespace.symlink_to(outside, target_is_directory=True)

    answer = await site.commit(site.version, [("a.txt", data, upload_id)])
    assert answer.status_code == 202, answer.text
    outcome = answer.json()
    assert (outcome["state"], outcome["refusal"]["code"]) == ("blocked", "PUBLICATION_BLOCKED")
    assert outcome["refusal"]["context"]["reason"] == "symbolic_link"
    assert outcome["refusal"]["context"]["path"] == "helio/heliophysics/solar-wind"
    assert list(outside.rglob("a.txt")) == []
    facts = await read_facts(site.api.database_url, site.collection_id)
    assert (facts.version, facts.files) == (site.version, {})


async def login(site: Site, cli: HostCli, user: str) -> None:
    """Store a token of ``user`` for the CLI."""
    token = (await site.api.headers(user))["Authorization"].removeprefix("Bearer ")
    cli.login(user, token, time.time() + 8 * 3600)


def files_of(directory: Path) -> dict[str, bytes]:
    """Each file below ``directory`` but ``metadata.json``, by its path, with its bytes."""
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path.name != "metadata.json"
    }


async def patch_request(site: Site, upload_id: str, offset: int, length: int) -> bytes:
    """The head of a raw ``PATCH`` of ``length`` bytes at ``offset``, as dave."""
    headers = {
        "Host": f"127.0.0.1:{site.stack.proxy_port}",
        **TUS,
        **OFFSET_STREAM,
        **await site.auth("dave"),
        "Upload-Offset": str(offset),
        "Content-Length": str(length),
    }
    lines = [f"PATCH /files/{upload_id} HTTP/1.1", *(f"{k}: {v}" for k, v in headers.items())]
    return ("\r\n".join(lines) + "\r\n\r\n").encode()


async def interrupted_patch(site: Site, upload_id: str, data: bytes, sent: int) -> None:
    """A ``PATCH`` that declares all of ``data`` and sends only ``sent`` bytes, then closes."""
    request = await patch_request(site, upload_id, 0, len(data))
    with socket.create_connection(("127.0.0.1", site.stack.proxy_port)) as connection:
        connection.sendall(request + data[:sent])

        async def arrived() -> bool:
            return site.data_size(upload_id) > 0

        await until(arrived, "tusd wrote bytes of the interrupted PATCH")


async def settled_offset(site: Site, upload_id: str) -> int:
    """The offset that tusd reports once it gave up the interrupted ``PATCH``."""
    offset = 0

    async def answered() -> bool:
        nonlocal offset
        head = await site.head("dave", upload_id)
        if head.status_code != 200:
            return False
        offset = int(head.headers["Upload-Offset"])
        return not (site.uploads / f"{upload_id}.lock").exists()

    await until(answered, "tusd released the interrupted upload")
    return offset


def _metadata(values: dict[str, str]) -> str:
    """The ``Upload-Metadata`` header: each key with its value in base64."""
    return ",".join(f"{k} {base64.b64encode(v.encode()).decode()}" for k, v in values.items())
