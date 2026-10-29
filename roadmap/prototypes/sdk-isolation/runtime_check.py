"""Exercise installed artifacts in isolated interpreters outside the repository cwd."""

import argparse
import csv
import hashlib
import importlib
import importlib.abc
import importlib.metadata
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
from uuid import UUID


FORBIDDEN = (
    "huron.core", "huron.schema", "huron.applications", "fastapi", "uvicorn",
    "starlette", "pydantic", "pydantic_settings", "sqlalchemy", "asyncpg", "alembic",
    "aiobotocore", "botocore", "boto3", "s3fs", "fsspec", "icechunk", "zarr",
    "numpy", "xarray", "h5py", "pyarrow",
)


class ForbiddenImportError(ImportError):
    """An SDK import tried to cross a deliberately closed boundary."""


class ImportGuard(importlib.abc.MetaPathFinder):
    """Actively reject forbidden imports, including when server files are installed."""

    def __init__(self):
        self.attempts = []

    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == name or fullname.startswith(name + ".") for name in FORBIDDEN):
            self.attempts.append(fullname)
            raise ForbiddenImportError(fullname)
        return None


def install_guards():
    """Prove the import guard rejects imports and deny actual network/credential I/O."""
    guard = ImportGuard()
    sys.meta_path.insert(0, guard)
    assert not any(name in sys.modules for name in FORBIDDEN)
    for name in FORBIDDEN:
        try:
            importlib.import_module(name)
        except ForbiddenImportError as error:
            assert str(error) == name
        else:
            raise AssertionError(f"guard did not reject {name}")
    assert guard.attempts == list(FORBIDDEN)
    guard.attempts.clear()
    denied = []
    home = Path(os.environ["HOME"])

    def audit(event, args):
        if event.startswith("socket.") or event in {"subprocess.Popen", "os.system"}:
            denied.append(event)
            raise AssertionError(f"unexpected external I/O: {event}")
        if event == "open" and isinstance(args[0], (str, bytes)):
            path = Path(os.fsdecode(args[0]))
            if path.is_relative_to(home) or path.name in {".netrc", "_netrc"}:
                denied.append("credential-file-read")
                raise AssertionError("unexpected credential discovery")

    sys.addaudithook(audit)
    return guard, denied


def exercise_sdk(sdk_root):
    """Prove construction, typed values, HTTP errors, validation and resource lifetime."""
    guard, denied = install_guards()
    import httpx
    from dataclasses import FrozenInstanceError
    from huron.client import Client
    from huron.catalog import Dataset, DatasetNotFoundError, InvalidResponseError

    for public in (Client, Dataset):
        module = sys.modules[public.__module__]
        assert Path(module.__file__).is_relative_to(sdk_root / "huron")
        assert ".interface." in public.__module__
    identity = UUID("00000000-0000-0000-0000-000000000001")
    value = {"id": str(identity), "title": "PACKAGING FIXTURE, not authoritative API"}
    cases = []

    class Body(httpx.SyncByteStream):
        def __init__(self, data):
            self.data = data
            self.closed = False

        def __iter__(self):
            yield self.data

        def close(self):
            self.closed = True

    class Transport(httpx.MockTransport):
        def __init__(self, handler):
            super().__init__(handler)
            self.close_count = 0

        def close(self):
            self.close_count += 1

    def exchange_case(label, status, raw, expected=None):
        requests = []
        body = Body(raw)

        def exchange(request):
            requests.append(request)
            assert request.method == "GET"
            assert str(request.url) == (
                "https://packaging-fixture.invalid/packaging-fixture/datasets/" + str(identity)
            )
            assert "authorization" not in request.headers
            assert "cookie" not in request.headers
            return httpx.Response(status, stream=body)

        transport = Transport(exchange)
        client = Client(transport=transport)
        assert requests == [] and not client.is_closed
        if expected is None:
            with client:
                dataset = client.datasets.get(identity)
                assert type(dataset) is Dataset
                assert dataset == Dataset(identity, value["title"])
                try:
                    dataset.title = "mutation"
                except FrozenInstanceError:
                    pass
                else:
                    raise AssertionError("dataset is mutable")
        else:
            try:
                with client:
                    client.datasets.get(identity)
            except expected as error:
                if status == 404:
                    assert str(error) == str(identity)
                if isinstance(error, httpx.HTTPStatusError):
                    assert error.response.status_code == status
            else:
                raise AssertionError(f"{label} did not raise {expected}")
        assert len(requests) == 1
        assert body.closed and client.is_closed and transport.close_count == 1
        client.close()
        assert transport.close_count == 1
        try:
            client.datasets.get(identity)
        except RuntimeError:
            pass
        else:
            raise AssertionError("closed client accepted a request")
        assert len(requests) == 1
        cases.append(label)

    with Client() as default:
        assert not default.is_closed
    assert default.is_closed
    default.close()
    cases.append("default-construction-no-network-or-credential-effects")
    exchange_case("http-success-sdk-owned-immutable-value", 200, json.dumps(value).encode())
    exchange_case("http-404-cleanup", 404, b"{}", DatasetNotFoundError)
    exchange_case("http-500-cleanup", 500, b"{}", httpx.HTTPStatusError)
    malformed = {
        "invalid-json": b"not JSON",
        "json-null": b"null",
        "json-array": b"[]",
        "missing-title": json.dumps({"id": str(identity)}).encode(),
        "extra-field": json.dumps({**value, "extra": True}).encode(),
        "nonstring-id": json.dumps({**value, "id": 3}).encode(),
        "invalid-uuid": json.dumps({**value, "id": "not-a-uuid"}).encode(),
        "wrong-identity": json.dumps({**value, "id": str(UUID(int=2))}).encode(),
        "nonstring-title": json.dumps({**value, "title": 3}).encode(),
        "empty-title": json.dumps({**value, "title": ""}).encode(),
    }
    for label, raw in malformed.items():
        exchange_case(label, 200, raw, InvalidResponseError)

    def connection_error(request):
        raise httpx.ConnectError("packaging fixture outage", request=request)

    transport = Transport(connection_error)
    client = Client(transport=transport)
    try:
        with client:
            client.datasets.get(identity)
    except httpx.ConnectError:
        pass
    else:
        raise AssertionError("transport error was suppressed")
    assert client.is_closed and transport.close_count == 1
    cases.append("transport-exception-cleanup")

    class CallerError(Exception):
        """A failure unrelated to HTTP still closes client resources."""

    transport = Transport(connection_error)
    client = Client(transport=transport)
    try:
        with client:
            raise CallerError("fixture caller failure")
    except CallerError:
        pass
    else:
        raise AssertionError("caller error was suppressed")
    assert client.is_closed and transport.close_count == 1
    cases.append("caller-exception-cleanup")

    with Client(transport=Transport(connection_error)) as client:
        try:
            client.datasets.get("../not-a-uuid")
        except ValueError:
            pass
        else:
            raise AssertionError("invalid identity was admitted")
    cases.append("invalid-request-identity-before-http")
    assert guard.attempts == [] and denied == []
    assert not any(name in sys.modules for name in FORBIDDEN)
    return {
        "cases": cases, "case_count": len(cases), "guard_selftests": len(FORBIDDEN),
        "forbidden_import_attempts": guard.attempts, "external_io_attempts": denied,
        "client_module": sys.modules[Client.__module__].__file__,
        "dataset_module": sys.modules[Dataset.__module__].__file__,
    }


def hidden_sdk(server_root):
    """Require the exact regular-package namespace-hiding counterexample."""
    guard, denied = install_guards()
    import huron

    assert Path(huron.__file__) == server_root / "huron/__init__.py"
    assert list(huron.__path__) == [str(server_root / "huron")]
    failures = []
    for name in ("huron.client", "huron.catalog"):
        try:
            importlib.import_module(name)
        except ModuleNotFoundError as error:
            assert error.name == name
            failures.append({"name": error.name, "message": str(error)})
        else:
            raise AssertionError(f"expected namespace hiding did not occur: {name}")
    assert guard.attempts == [] and denied == []
    return {"expected_failures": failures, "huron_file": huron.__file__}


def server_resolution(server_root, sdk_absent):
    """Resolve representative server packages without claiming dependency health."""
    import huron.core
    import huron.applications

    origins = {}
    for name in ("huron.core", "huron.applications", "huron.core.catalog", "huron.core.rawstore"):
        specification = importlib.util.find_spec(name)
        assert specification is not None
        expected = server_root / Path(*name.split(".")) / "__init__.py"
        assert Path(specification.origin) == expected
        origins[name] = specification.origin
    if sdk_absent:
        assert importlib.util.find_spec("huron.client") is None
        assert importlib.util.find_spec("huron.catalog") is None
    return {"origins": origins, "server_dependency_health": "not-tested-no-deps-install"}


def installed_records(names):
    """Hash every owned RECORD path, including metadata and generated entry points."""
    result = {}
    for name in names:
        distribution = importlib.metadata.distribution(name)
        rows = list(csv.reader(io.StringIO(distribution.read_text("RECORD"))))
        paths = {}
        for relative, recorded_hash, size in rows:
            path = Path(os.path.abspath(distribution.locate_file(relative)))
            assert not path.is_symlink(), f"unexpected installed symlink: {path}"
            assert path.is_file(), f"missing installed RECORD path: {path}"
            data = path.read_bytes()
            paths[str(path)] = hashlib.sha256(data).hexdigest()
            if recorded_hash:
                import base64
                expected = "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")
                assert recorded_hash == expected
                assert int(size) == len(data)
        assert len(paths) == len(rows)
        result[name] = paths
    return result


def main():
    """Expose narrowly scoped subprocess checks to the stdlib probe harness."""
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("sdk", "hidden", "server", "records", "inventory"))
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--extra-path", action="append", default=[])
    parser.add_argument("--sdk-root", type=Path)
    parser.add_argument("--server-root", type=Path)
    parser.add_argument("--sdk-absent", action="store_true")
    parser.add_argument("--distribution", action="append", default=[])
    args = parser.parse_args()
    assert sys.flags.isolated and sys.flags.dont_write_bytecode
    assert not Path.cwd().is_relative_to(args.repo)
    sys.path[0:0] = args.extra_path
    if args.mode == "sdk":
        result = exercise_sdk(args.sdk_root)
    elif args.mode == "hidden":
        result = hidden_sdk(args.server_root)
    elif args.mode == "server":
        result = server_resolution(args.server_root, args.sdk_absent)
    elif args.mode == "records":
        result = installed_records(args.distribution)
    else:
        result = {
            "distributions": {
                item.metadata["Name"].lower().replace("_", "-"): item.version
                for item in importlib.metadata.distributions()
            },
            "python": sys.version,
            "executable": sys.executable,
            "site_packages": next(path for path in sys.path if path.endswith("/site-packages")),
        }
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
