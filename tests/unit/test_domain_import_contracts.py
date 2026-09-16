"""The actual repository import contracts admit the target graph and reject forbidden changes."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).parents[2]
OWNERS = ("foundation", "security", "catalog", "raw", "integrity", "metastore", "rawstore")


def test_foundation_import_does_not_initialize_domains_or_adapters() -> None:
    """Importing Foundation contracts leaves Security, workflows and storage adapters unloaded."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
from huron.core.foundation import canonical, clock, errors, identifiers, names, retry
for owner in ('security', 'catalog', 'raw', 'integrity', 'metastore', 'rawstore'):
    assert 'huron.core.' + owner not in sys.modules, owner
assert 'huron.applications.api' not in sys.modules
""",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _sandbox(tmp_path: Path) -> Path:
    """Build a minimal package exercising the real configuration, including public reexports."""
    config = tmp_path / "pyproject.toml"
    config.write_text((ROOT / "pyproject.toml").read_text())
    packages = ["huron", "huron.core", "huron.schema", "huron.applications"]
    packages.extend(f"huron.core.{owner}" for owner in OWNERS)
    packages.extend(
        [
            "huron.applications.api",
            "huron.applications.lakectl",
            "huron.applications.api.authorization",
            "huron.applications.api.routes",
        ]
    )
    packages.extend(f"huron.core.{owner}._impl" for owner in ("security", "catalog", "raw", "integrity"))
    for name in packages:
        directory = tmp_path / name.replace(".", "/")
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "__init__.py").write_text("")
    for owner in OWNERS:
        (tmp_path / f"huron/core/{owner}/public.py").write_text("")
    for owner in ("security", "catalog", "raw", "integrity"):
        (tmp_path / f"huron/core/{owner}/_impl/operations.py").write_text("value = object()\n")
        (tmp_path / f"huron/core/{owner}/__init__.py").write_text(
            "from ._impl.operations import value\n"
        )
    (tmp_path / "huron/applications/api/app.py").write_text("")
    (tmp_path / "huron/applications/api/routes/example.py").write_text("")
    (tmp_path / "huron/applications/api/authorization/guards.py").write_text("")
    return config


def _check(tmp_path: Path, edits: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run import-linter against a fresh sandbox using the installed toolchain."""
    config = _sandbox(tmp_path)
    for relative, source in edits.items():
        (tmp_path / relative).write_text(source)
    executable = shutil.which("lint-imports")
    assert executable is not None
    return subprocess.run(
        [executable, "--config", str(config), "--no-cache"],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_declared_edges_and_owner_root_reexports_are_allowed(tmp_path: Path) -> None:
    """Every allowed direct edge and public-root import of its own implementation passes."""
    edges = {
        "foundation": (),
        "security": ("core.foundation",),
        "catalog": ("core.security", "core.foundation"),
        "raw": ("core.catalog", "core.security", "core.foundation", "schema"),
        "integrity": ("core.catalog", "core.raw", "core.foundation", "schema"),
        "metastore": ("core.catalog", "core.raw", "core.security", "core.foundation"),
        "rawstore": ("schema",),
    }
    edits = {
        f"huron/core/{owner}/public.py": "".join(f"import huron.{target}\n" for target in targets)
        for owner, targets in edges.items()
    }
    result = _check(tmp_path, edits)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    ("edits", "contract"),
    [
        (
            {"huron/core/metastore/public.py": "import huron.schema\n"},
            "metastore uses catalog raw security and foundation only",
        ),
        (
            {
                "huron/core/security/public.py": "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import huron.core.catalog\n"
            },
            "security uses foundation only",
        ),
        (
            {
                "huron/core/raw/public.py": "import huron.schema.bridge\n",
                "huron/schema/bridge.py": "import huron.core.metastore\n",
            },
            "domains never depend on adapters even indirectly",
        ),
        (
            {
                "huron/core/raw/public.py": "import huron.schema.bridge\n",
                "huron/schema/bridge.py": "import fastapi\n",
            },
            "domains exclude frameworks and infrastructure libraries even indirectly",
        ),
        (
            {"huron/applications/api/app.py": "import huron.core.raw._impl.operations\n"},
            "raw implementations are private to their owner",
        ),
        (
            {"huron/core/raw/public.py": "import huron.core.catalog._impl.operations\n"},
            "catalog implementations are private to their owner",
        ),
        (
            {"huron/core/catalog/public.py": "import huron.core.security._impl.operations\n"},
            "security implementations are private to their owner",
        ),
        (
            {"huron/applications/lakectl/__init__.py": "import huron.core.integrity._impl.operations\n"},
            "integrity implementations are private to their owner",
        ),
        ({"huron/core/unclassified.py": "value = 1\n"}, "every core sibling has an explicit owner"),
    ],
)
def test_forbidden_edges_and_unclassified_owners_fail(
    tmp_path: Path, edits: dict[str, str], contract: str
) -> None:
    """The configured gate rejects direct, type-only, indirect, private and unclassified edges."""
    result = _check(tmp_path, edits)
    assert result.returncode != 0
    assert f"{contract} BROKEN" in " ".join(result.stdout.split()), result.stdout + result.stderr
