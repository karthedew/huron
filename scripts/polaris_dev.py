"""Bootstrap and verify the private, local Polaris development sandbox."""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

BASE_URL = "http://127.0.0.1:8181"
REALM = "POLARIS"


def save(path: Path, value: object) -> None:
    """Write a private JSON file without exposing credentials in terminal output."""
    path.write_text(json.dumps(value, indent=2) + "\n")
    path.chmod(0o600)


def configure(state: Path) -> None:
    """Create reusable local credentials and runtime configuration."""
    credentials_path = state / "credentials.json"
    if not credentials_path.exists():
        save(
            credentials_path,
            {
                "url": BASE_URL,
                "realm": REALM,
                "admin": {
                    "principal": "root",
                    "clientId": "huron-local-root",
                    "clientSecret": secrets.token_urlsafe(32),
                },
            },
        )
    credentials = json.loads(credentials_path.read_text())
    admin = credentials["admin"]
    save(
        state / "root-credentials.json",
        {REALM: {"client-id": admin["clientId"], "client-secret": admin["clientSecret"]}},
    )
    password_path = state / "db-password"
    if not password_path.exists():
        password_path.write_text(secrets.token_urlsafe(32) + "\n")
        password_path.chmod(0o600)
    properties = {
        "quarkus.http.host": "127.0.0.1",
        "quarkus.http.port": "8181",
        "quarkus.management.host": "127.0.0.1",
        "quarkus.management.port": "8182",
        "quarkus.otel.sdk.disabled": "true",
        "quarkus.log.file.enabled": "false",
        "quarkus.datasource.jdbc.url": "jdbc:postgresql://127.0.0.1:5439/polaris?currentSchema=polaris_schema",
        "quarkus.datasource.username": "polaris",
        "quarkus.datasource.password": password_path.read_text().strip(),
        "polaris.realm-context.realms": REALM,
        "polaris.persistence.type": "relational-jdbc",
        'polaris.features."ENABLE_ICECHUNK_TABLES"': "true",
        'polaris.features."ALLOW_INSECURE_STORAGE_TYPES"': "true",
        'polaris.features."SUPPORTED_CATALOG_STORAGE_TYPES"': '["FILE","S3"]',
        "polaris.readiness.ignore-severe-issues": "true",
    }
    config_path = state / "application.properties"
    config_path.write_text("\n".join(f"{key}={value}" for key, value in properties.items()) + "\n")
    config_path.chmod(0o600)
    bridge_secret(state)
    raw_postgres_env = state.parent / "huron" / "raw-postgres.env"
    raw_postgres_env.write_text(
        "POSTGRES_USER=huron\nPOSTGRES_DB=huron_raw\n"
        f"POSTGRES_PASSWORD={password_path.read_text().strip()}\n"
    )
    raw_postgres_env.chmod(0o600)


def bridge_secret(state: Path) -> str:
    """Reuse the private key shared by the local web and Raw services."""
    directory = state.parent / "huron"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = directory / "raw-bridge-key"
    try:
        with key.open("x") as stream:
            key.chmod(0o600)
            stream.write(secrets.token_urlsafe(48) + "\n")
    except FileExistsError:
        pass
    return key.read_text().strip()


def raw_environment(state: Path) -> dict[str, str]:
    """Configure an isolated Raw database and storage without exposing secrets."""
    environment = os.environ.copy()
    password = quote((state / "db-password").read_text().strip(), safe="")
    defaults = {
        "HURON_ENV": "development",
        "HURON_AUTH_MODE": "credentials",
        "HURON_DATABASE_URL": f"postgresql://huron:{password}@127.0.0.1:5440/huron_raw",
        "HURON_DATA_ROOT": str(state.parent / "huron" / "raw"),
        "HURON_CLASSIFICATION_VOCABULARY": json.dumps(
            [{"code": "open", "order": 0, "discoverable": True}]
        ),
        "HURON_WEB_APP_URL": "http://127.0.0.1:5173",
        "HURON_RAW_API_URL": "http://127.0.0.1:8080",
        "HURON_RAW_POLARIS_AUTHORIZATION": "rbac",
        "HURON_RAW_BRIDGE_SECRET": bridge_secret(state),
    }
    for key, value in defaults.items():
        environment.setdefault(key, value)
    return environment


def request(
    path: str,
    *,
    token: str | None = None,
    method: str = "GET",
    data: object | None = None,
    form: dict[str, str] | None = None,
    expected: int | None = None,
) -> object:
    """Call Polaris and surface only errors, never successful credential payloads."""
    headers = {"Polaris-Realm": REALM}
    body = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    elif form is not None:
        body = urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    try:
        with urlopen(
            Request(BASE_URL + path, body, headers, method=method), timeout=15
        ) as response:
            raw = response.read()
            if expected is not None and response.status != expected:
                raise RuntimeError(
                    f"{method} {path}: expected HTTP {expected}, got {response.status}"
                )
            return json.loads(raw) if raw else None
    except HTTPError as exc:
        if expected is not None and exc.code == expected:
            return None
        raise RuntimeError(f"{method} {path}: HTTP {exc.code}: {exc.read().decode()}") from exc


def obtain_token(credentials: dict[str, str]) -> str:
    """Activate the authenticated principal's assigned roles."""
    result = request(
        "/api/catalog/v1/oauth/tokens",
        method="POST",
        form={
            "grant_type": "client_credentials",
            "client_id": credentials["clientId"],
            "client_secret": credentials["clientSecret"],
            "scope": "PRINCIPAL_ROLE:ALL",
        },
    )
    return result["access_token"]


def exists(path: str, token: str) -> bool:
    """Distinguish a missing seed entity from other API failures."""
    try:
        request(path, token=token)
        return True
    except RuntimeError as exc:
        if ": HTTP 404:" in str(exc):
            return False
        raise


def launch(state: Path, name: str, command: list[str]) -> None:
    """Detach an owned service from the invoking terminal and record its PID."""
    environment = os.environ.copy()
    if name == "web":
        working_directory = state.parents[1] / "web"
        raw_settings = raw_environment(state)
        for key in ("HURON_RAW_API_URL", "HURON_RAW_POLARIS_AUTHORIZATION", "HURON_RAW_BRIDGE_SECRET"):
            environment[key] = raw_settings[key]
    elif name == "raw-api":
        working_directory = state.parents[1]
        environment = raw_environment(state)
    elif name == "polaris":
        working_directory = state
    else:
        raise ValueError(f"Unknown local service: {name}")
    with (state / f"{name}.log").open("a") as log:
        process = subprocess.Popen(
            command,
            cwd=working_directory,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    pid_path = state / f"{name}.pid"
    pid_path.write_text(f"{process.pid}\n")
    pid_path.chmod(0o600)


if __name__ == "__main__":
    operation, directory, *arguments = sys.argv[1:]
    state_directory = Path(directory).resolve()
    if operation == "launch":
        launch(state_directory, arguments[0], arguments[1:])
    elif operation == "raw-command":
        subprocess.run(
            arguments,
            cwd=state_directory.parents[1],
            env=raw_environment(state_directory),
            check=True,
        )
    else:
        {"configure": configure}[operation](state_directory)
