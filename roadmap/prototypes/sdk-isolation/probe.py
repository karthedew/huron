"""Build and qualify isolated, non-production SDK/server namespace packaging candidates."""

import argparse
import ast
import base64
import csv
from email.parser import BytesParser
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import time
import tomllib
import traceback
import urllib.request
from zipfile import ZipFile


SUBJECT = Path(__file__).resolve().parent
RUNTIME = {
    "httpx": "0.28.1", "anyio": "4.14.2", "certifi": "2026.7.22",
    "httpcore": "1.0.9", "h11": "0.16.0", "idna": "3.18", "typing-extensions": "4.16.0",
}
BUILD_FROM_ROOT = {"packaging": "26.3", "pathspec": "1.1.1", "pluggy": "1.6.0"}
INITIAL_MANIFEST = "3fa5b12a659f6b671aa543af89f5f46de61d7d2d3df48dd9a0c867bfcff37e56"
INITIAL_INDEX = "a966503715762ae180e3a8b1d9634fd1f9fd0e8a6f945d4bffc75aed062dc706"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode()


def write_json(path, value):
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(value, indent=2, sort_keys=True) + "\n")


def git(repo, *args):
    return subprocess.check_output(
        ["git", "-C", str(repo), *args], env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    )


def snapshot(repo):
    """Hash every Git-visible file, deletion and mode, plus the exact index bytes."""
    names = sorted(set(os.fsdecode(name) for name in git(
        repo, "ls-files", "--cached", "--others", "--exclude-standard", "-z"
    ).split(b"\0") if name))
    entries = []
    for name in names:
        path = repo / name
        if not path.exists() and not path.is_symlink():
            entries.append([name, "missing"])
            continue
        details = path.lstat()
        data = os.fsencode(os.readlink(path)) if path.is_symlink() else path.read_bytes()
        entries.append([
            name, stat.S_IMODE(details.st_mode), "link" if path.is_symlink() else "file", digest(data)
        ])
    index = Path(os.fsdecode(git(repo, "rev-parse", "--git-path", "index")).strip())
    if not index.is_absolute():
        index = repo / index
    return {
        "git_visible_paths": len(entries), "entries": entries,
        "manifest_sha256": digest(encoded(entries)), "index_sha256": digest(index.read_bytes()),
        "status": git(repo, "status", "--short", "--untracked-files=all").decode(),
        "diff_sha256": digest(git(repo, "diff", "--binary")),
        "cached_diff_sha256": digest(git(repo, "diff", "--cached", "--binary")),
        "head": git(repo, "rev-parse", "HEAD").decode().strip(),
    }


def safe_files(root):
    """Reject symlinks/special files and omit interpreter bytecode from pure input copies."""
    assert root.is_dir() and not root.is_symlink(), root
    result = {}
    for path in sorted(root.rglob("*")):
        assert not path.is_symlink(), f"unexpected input symlink: {path}"
        assert path.is_dir() or path.is_file(), f"unexpected special input: {path}"
        relative = path.relative_to(root)
        if "__pycache__" in relative.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        if path.is_file():
            result[str(relative)] = digest(path.read_bytes())
    return result


def copy_tree(source, target):
    files = safe_files(source)
    target.mkdir(parents=True, exist_ok=False)
    for name in files:
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, destination)
    assert safe_files(target) == files
    return files


def wheel_inventory(path):
    """Validate every wheel RECORD entry and retain hashes for all wheel paths."""
    with ZipFile(path) as archive:
        names = archive.namelist()
        assert len(names) == len(set(names))
        for name in names:
            relative = PurePosixPath(name)
            assert not relative.is_absolute() and ".." not in relative.parts and "\\" not in name
            assert not stat.S_ISLNK(archive.getinfo(name).external_attr >> 16)
        records = [name for name in names if name.endswith(".dist-info/RECORD")]
        assert len(records) == 1
        rows = list(csv.reader(io.StringIO(archive.read(records[0]).decode())))
        assert set(names) == {row[0] for row in rows}
        for name, recorded_hash, size in rows:
            data = archive.read(name)
            if name == records[0]:
                assert recorded_hash == size == ""
            else:
                expected = "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")
                assert expected == recorded_hash and int(size) == len(data)
        metadata = BytesParser().parsebytes(archive.read(next(
            name for name in names if name.endswith(".dist-info/METADATA")
        )))
        return {
            "sha256": digest(path.read_bytes()), "bytes": path.stat().st_size,
            "files": {name: digest(archive.read(name)) for name in sorted(names)},
            "requires_dist": metadata.get_all("Requires-Dist", []),
            "name": metadata["Name"], "version": metadata["Version"],
            "requires_python": metadata["Requires-Python"],
        }


class Probe:
    """Own one fresh run's environments, artifacts, bounded subprocesses and evidence."""

    def __init__(self, repo, run_id, python, outside, uv):
        self.repo = repo
        self.python = python
        self.outside = outside
        self.uv = uv
        assert SUBJECT == repo / "roadmap/prototypes/sdk-isolation"
        for parent in (SUBJECT, SUBJECT.parent, SUBJECT.parent.parent):
            assert parent.is_dir() and not parent.is_symlink()
        assert json.loads((SUBJECT / "OWNER.json").read_text())["resource"] == "prototype:sdk"
        assert not outside.is_relative_to(repo) and outside.is_dir()
        assert re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", run_id), "unsafe run ID"
        runs = SUBJECT / "runs"
        assert not runs.is_symlink()
        runs.mkdir(exist_ok=True)
        self.run = runs / run_id
        self.run.mkdir(exist_ok=False)
        for name in ("logs", "tmp", "cache", "home", "envs", "build-inputs", "wheels", "downloads"):
            (self.run / name).mkdir()
        self.env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8",
            "HOME": str(self.run / "home"), "TMPDIR": str(self.run / "tmp"),
            "XDG_CACHE_HOME": str(self.run / "cache/xdg"),
            "XDG_CONFIG_HOME": str(self.run / "home/config"),
            "XDG_DATA_HOME": str(self.run / "home/data"),
            "UV_CACHE_DIR": str(self.run / "cache/uv"), "UV_NO_CONFIG": "1",
            "UV_PYTHON_DOWNLOADS": "never", "UV_NO_MANAGED_PYTHON": "1",
            "UV_LINK_MODE": "copy", "UV_NO_PROGRESS": "1",
            "PYTHONDONTWRITEBYTECODE": "1", "SOURCE_DATE_EPOCH": "1700000000",
            "GIT_OPTIONAL_LOCKS": "0",
        }
        self.commands = []
        self.checks = []
        self.residual_process_groups = []
        self.runtime_outcomes = 0
        write_json(self.run / "isolation.json", self.env)
        self.driver = self.run / "driver-inputs"
        self.driver.mkdir()
        driver_hashes = {}
        for name in ("probe.py", "runtime_check.py", "closure_check.py", "build-extras.json", "OWNER.json"):
            source = SUBJECT / name
            assert not source.is_symlink()
            shutil.copyfile(source, self.driver / name)
            driver_hashes[name] = digest(source.read_bytes())
        write_json(self.run / "driver-hashes.json", driver_hashes)

    def check(self, name, **evidence):
        row = {"name": name, "result": "observed", **evidence}
        self.checks.append(row)
        with (self.run / "observations.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
        print(f"OBSERVED {name}", flush=True)

    def command(self, label, args, cwd=None, parse=False):
        """Run one owned process group, log exact inputs/output, and fail on nonzero exit."""
        args = [str(arg) for arg in args]
        cwd = cwd or self.outside
        number = len(self.commands) + 1
        path = self.run / "logs" / f"{number:03d}-{label}.log"
        start = time.monotonic()
        process = subprocess.Popen(
            args, cwd=cwd, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, start_new_session=True,
        )
        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=180)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
        row = {
            "label": label, "argv": args, "cwd": str(cwd), "exit": process.returncode,
            "seconds": round(time.monotonic() - start, 3), "log": str(path.relative_to(self.run)),
            "pid": process.pid, "timed_out": timed_out,
        }
        self.commands.append(row)
        with path.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
            handle.write("$ " + shlex.join(args) + "\nSTDOUT:\n" + stdout + "\nSTDERR:\n" + stderr)
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            pass
        else:
            self.residual_process_groups.append(process.pid)
            raise RuntimeError(f"owned command left process group {process.pid}: {path}")
        if process.returncode or timed_out:
            raise RuntimeError(f"{label}: exit={process.returncode}, timeout={timed_out}, log={path}")
        return json.loads(stdout) if parse else stdout.strip()

    def uv_command(self, label, *args, cwd=None):
        return self.command(label, [self.uv, "--no-config", "--no-python-downloads", *args], cwd=cwd)

    def runtime(self, env, mode, **options):
        args = [env / "bin/python", "-I", "-B", self.driver / "runtime_check.py", mode, "--repo", self.repo]
        for key, value in options.items():
            flag = "--" + key.replace("_", "-")
            if value is True:
                args.append(flag)
            elif isinstance(value, list):
                for item in value:
                    args.extend([flag, str(item)])
            elif value is not None:
                args.extend([flag, str(value)])
        result = self.command(f"{env.name}-{mode}", args, parse=True)
        if mode == "sdk":
            self.runtime_outcomes += result["case_count"]
        return result

    def venv(self, name):
        env = self.run / "envs" / name
        assert not env.exists()
        self.uv_command(name + "-create", "venv", "--no-project", "--python", self.python, env)
        info = self.runtime(env, "inventory")
        assert info["distributions"] == {}, "fresh venv was not empty"
        return env, Path(info["site_packages"])

    def sdk_install(self, env, reinstall=False):
        args = ["pip", "install", "--python", env / "bin/python", self.sdk_wheel,
                "--no-index", "--find-links", self.runtime_wheels,
                "--constraints", self.run / "runtime-requirements.txt"]
        if reinstall:
            args.extend(["--reinstall-package", "huron-sdk"])
        self.uv_command(env.name + "-install-sdk", *args)

    def server_install(self, env, variant, editable=False, reinstall=False):
        args = ["pip", "install", "--python", env / "bin/python", "--no-deps", "--no-index"]
        if editable:
            args.extend(["--editable", self.run / "build-inputs" / variant,
                         "--find-links", self.build_wheels,
                         "--build-constraints", self.run / "build-requirements.txt"])
        else:
            args.append(self.server_wheels[variant])
        if reinstall:
            args.extend(["--reinstall-package", "huron"])
        self.uv_command(env.name + "-install-server", *args)

    def uninstall(self, env, name):
        self.uv_command(env.name + "-uninstall-" + name, "pip", "uninstall",
                        "--python", env / "bin/python", name)

    def records(self, env, *names):
        return self.runtime(env, "records", distribution=list(names))

    def paired(self, env, site, variant, editable, label):
        records = self.records(env, "huron", "huron-sdk")
        overlap = set(records["huron"]) & set(records["huron-sdk"])
        assert not overlap, overlap
        server_root = self.run / "build-inputs" / variant / "src" if editable else site
        hidden = editable and variant == "current"
        result = self.runtime(env, "hidden" if hidden else "sdk", sdk_root=site, server_root=server_root)
        self.runtime(env, "server", server_root=server_root)
        self.check(label, record_intersection=[], server_record_paths=len(records["huron"]),
                   sdk_record_paths=len(records["huron-sdk"]), sdk_behavior=result)

    def order_case(self, variant, order, editable=False):
        kind = "editable" if editable else "wheel"
        label = f"{kind}-{variant}-{order}"
        env, site = self.venv(label)
        first = "huron" if order == "server-sdk" else "huron-sdk"
        second = "huron-sdk" if first == "huron" else "huron"

        def install(name, reinstall=False):
            if name == "huron":
                self.server_install(env, variant, editable, reinstall)
            else:
                self.sdk_install(env, reinstall)

        install(first)
        original = self.records(env, first)
        install(second)
        assert self.records(env, first) == original
        self.paired(env, site, variant, editable, label + "-installed")

        for removed, survivor in (("huron", "huron-sdk"), ("huron-sdk", "huron")):
            before = self.records(env, survivor)
            removed_paths = self.records(env, removed)[removed]
            self.uninstall(env, removed)
            assert self.records(env, survivor) == before
            assert all(not Path(path).exists() for path in removed_paths)
            if survivor == "huron-sdk":
                behavior = self.runtime(env, "sdk", sdk_root=site)
            else:
                server_root = self.run / "build-inputs" / variant / "src" if editable else site
                behavior = self.runtime(env, "server", server_root=server_root, sdk_absent=True)
            self.check(label + "-remove-" + removed, survivor_hashes_preserved=len(before[survivor]),
                       removed_record_paths=len(removed_paths), survivor_behavior=behavior)
            install(removed)
            assert self.records(env, survivor) == before
            self.paired(env, site, variant, editable, label + "-restore-" + removed)

        for name, other in ((first, second), (second, first)):
            before = self.records(env, other)
            install(name, reinstall=True)
            assert self.records(env, other) == before
        self.paired(env, site, variant, editable, label + "-reinstall-original-order")

    def download_inputs(self):
        lock_path = self.repo / "uv.lock"
        assert not lock_path.is_symlink()
        shutil.copyfile(lock_path, self.run / "input-uv.lock")
        lock = tomllib.loads(lock_path.read_text())
        entries = {item["name"]: item for item in lock["package"]}
        inputs = {}
        for name, version in (RUNTIME | BUILD_FROM_ROOT).items():
            package = entries[name]
            assert package["version"] == version
            wheels = [wheel for wheel in package["wheels"] if wheel["url"].endswith("-py3-none-any.whl")]
            assert len(wheels) == 1
            inputs[name] = {"version": version, "url": wheels[0]["url"],
                            "sha256": wheels[0]["hash"].removeprefix("sha256:")}
        extras = json.loads((self.driver / "build-extras.json").read_text())
        for name, package in extras.items():
            url = f"https://pypi.org/pypi/{name}/{package['version']}/json"
            with urllib.request.urlopen(url, timeout=30) as response:
                metadata = json.load(response)
            write_json(self.run / "downloads" / f"{name}-release.json", metadata)
            assert not metadata["info"]["yanked"], f"yanked build input: {name}"
            assert any(wheel["url"] == package["url"] and
                       wheel["digests"]["sha256"] == package["sha256"] and not wheel["yanked"]
                       for wheel in metadata["urls"])
        inputs.update(extras)
        write_json(self.run / "dependency-lock.json", inputs)
        self.runtime_wheels = self.run / "downloads/runtime"
        self.build_wheels = self.run / "downloads/build"
        self.runtime_wheels.mkdir()
        self.build_wheels.mkdir()
        for name, package in inputs.items():
            parent = self.runtime_wheels if name in RUNTIME else self.build_wheels
            path = parent / package["url"].rsplit("/", 1)[1]
            assert path.name.endswith(".whl")
            with urllib.request.urlopen(package["url"], timeout=30) as response:
                data = response.read()
            assert digest(data) == package["sha256"], f"hash mismatch: {name}"
            with path.open("xb") as handle:
                handle.write(data)
        for group, selected in (("runtime", RUNTIME), ("build", BUILD_FROM_ROOT | extras)):
            with (self.run / f"{group}-requirements.txt").open("x") as handle:
                for name in sorted(selected):
                    package = inputs[name]
                    handle.write(f"{name}=={package['version']} --hash=sha256:{package['sha256']}\n")
        self.check("complete-input-pins", versions={name: value["version"] for name, value in inputs.items()},
                   root_lock_sha256=digest(lock_path.read_bytes()), input_wheels=len(inputs))

    def prepare_sources(self):
        originals = {}
        current = self.run / "build-inputs/current"
        current.mkdir()
        for name in ("pyproject.toml", "README.md"):
            source = self.repo / name
            assert source.is_file() and not source.is_symlink()
            shutil.copyfile(source, current / name)
            originals[name] = digest(source.read_bytes())
        originals["src/huron"] = copy_tree(self.repo / "src/huron", current / "src/huron")
        current_files = safe_files(current)
        native = self.run / "build-inputs/native"
        copy_tree(current, native)
        initializer = native / "src/huron/__init__.py"
        assert initializer.is_relative_to(self.run) and not initializer.is_symlink()
        initializer.unlink()
        native_files = safe_files(native)
        assert set(current_files) - set(native_files) == {"src/huron/__init__.py"}
        assert native_files == {name: value for name, value in current_files.items()
                                if name != "src/huron/__init__.py"}
        sdk_files = copy_tree(SUBJECT / "sdk", self.run / "build-inputs/sdk")
        assert "src/huron/__init__.py" not in sdk_files
        imports = []
        for name in sdk_files:
            if not name.endswith(".py"):
                continue
            tree = ast.parse((SUBJECT / "sdk" / name).read_text(), filename=name)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    assert node.level == 0, "use explicit auditable imports in the experiment"
                    modules = [node.module]
                else:
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                        assert node.func.id not in {"__import__", "exec", "eval"}
                    continue
                for module in modules:
                    assert (module.split(".")[0] in sys.stdlib_module_names or module == "httpx" or
                            module.startswith(("huron.client", "huron.catalog"))), module
                    imports.append([name, node.lineno, module])
        self.source_inputs = {"current": current_files, "native": native_files, "sdk": sdk_files}
        write_json(self.run / "source-inputs.json", self.source_inputs)
        write_json(self.run / "static-imports.json", imports)
        self.check("pure-server-copies-and-static-sdk-isolation", sdk_imports=len(imports),
                   server_source_files=len(originals["src/huron"]),
                   native_only_removed_path="src/huron/__init__.py", config_changed=False)

    def build(self):
        build_env, _ = self.venv("build-tools")
        self.uv_command("install-pinned-build-tools", "pip", "install", "--python", build_env / "bin/python",
                        "--no-index", "--find-links", self.build_wheels, "--require-hashes",
                        "--requirements", self.run / "build-requirements.txt")
        expected_build = BUILD_FROM_ROOT | {name: info["version"] for name, info in
                                            json.loads((self.driver / "build-extras.json").read_text()).items()}
        assert self.runtime(build_env, "inventory")["distributions"] == expected_build
        self.uv_command("check-build-environment", "pip", "check", "--python", build_env / "bin/python")
        self.command("installed-hatchling-apis", [build_env / "bin/python", "-I", "-B", "-c",
                     "import hatchling.build as b, inspect, importlib.metadata as m; "
                     "print(m.version('hatchling')); "
                     "print(inspect.signature(b.build_wheel)); "
                     "print(inspect.signature(b.build_editable)); "
                     "print(inspect.getsource(b.get_requires_for_build_editable))"])
        editable_requirements = self.command("actual-editable-build-requirements", [
            build_env / "bin/python", "-I", "-B", "-c",
            "import hatchling.build as b, json; print(json.dumps(b.get_requires_for_build_editable()))"
        ], cwd=self.run / "build-inputs/current", parse=True)
        assert editable_requirements == ["editables~=0.3"]
        inventories = {}
        self.server_wheels = {}
        for name in ("sdk", "current", "native"):
            output = self.run / "wheels" / name
            output.mkdir()
            source = self.run / "build-inputs" / name
            self.uv_command("build-" + name, "build", source, "--wheel", "--out-dir", output,
                            "--python", self.python, "--no-index", "--find-links", self.build_wheels,
                            "--build-constraints", self.run / "build-requirements.txt", "--require-hashes",
                            "--no-sources", "--no-create-gitignore")
            wheels = list(output.glob("*.whl"))
            assert len(wheels) == 1
            inventories[name] = wheel_inventory(wheels[0])
            actual_sources = {key: value for key, value in inventories[name]["files"].items()
                              if key.startswith("huron/")}
            expected_sources = {key.removeprefix("src/"): value for key, value in self.source_inputs[name].items()
                                if key.startswith("src/huron/")}
            assert actual_sources == expected_sources, f"wheel omitted or altered {name} input"
            if name == "sdk":
                self.sdk_wheel = wheels[0]
            else:
                self.server_wheels[name] = wheels[0]
        assert inventories["sdk"]["requires_dist"] == ["httpx==0.28.1"]
        assert inventories["sdk"]["requires_python"] == ">=3.12"
        for variant in ("current", "native"):
            assert not set(inventories[variant]["files"]) & set(inventories["sdk"]["files"])
        current = inventories["current"]["files"]
        native = inventories["native"]["files"]
        assert set(current) - set(native) == {"huron/__init__.py"}
        assert [name for name in native if native[name] != current[name]] == ["huron-0.1.0.dist-info/RECORD"]
        self.wheel_results = inventories
        write_json(self.run / "wheel-inventories.json", inventories)
        for root, paths in (
            ("hatchling", sorted(self.build_wheels.glob("*.whl"))),
            ("huron-sdk", [self.sdk_wheel, *sorted(self.runtime_wheels.glob("*.whl"))]),
        ):
            args = [build_env / "bin/python", "-I", "-B", self.driver / "closure_check.py", "--root", root]
            if root == "hatchling":
                args.extend(["--root", "editables"])
            for path in paths:
                args.extend(["--wheel", path])
            closure = self.command("closure-" + root, args, parse=True)
            write_json(self.run / (root + "-closure.json"), closure)
            self.check(root + "-metadata-closure", package_count=len(closure["packages"]),
                       active_edges=closure["active_edges"])
        self.check("built-wheels-disjoint-and-complete", wheel_record_intersections={"current": [], "native": []},
                   wheels={key: {name: item[name] for name in ("sha256", "bytes")}
                           for key, item in inventories.items()})

    def qualify(self):
        sdk_env, sdk_site = self.venv("sdk-only")
        self.sdk_install(sdk_env)
        inventory = self.runtime(sdk_env, "inventory")
        assert inventory["distributions"] == {**RUNTIME, "huron-sdk": "0.0.0"}
        self.uv_command("check-sdk-environment", "pip", "check", "--python", sdk_env / "bin/python")
        self.check("normal-resolved-sdk-only-install", distributions=inventory["distributions"],
                   behavior=self.runtime(sdk_env, "sdk", sdk_root=sdk_site))
        for variant in ("current", "native"):
            for order in ("server-sdk", "sdk-server"):
                self.order_case(variant, order)
        split_env, _ = self.venv("split-path-interpreter")
        for variant in ("current", "native"):
            server_env, server_site = self.venv("split-" + variant)
            self.server_install(server_env, variant)
            for order, paths in (("server-sdk", [server_site, sdk_site]), ("sdk-server", [sdk_site, server_site])):
                result = self.runtime(split_env, "hidden" if variant == "current" else "sdk",
                                      extra_path=paths, sdk_root=sdk_site, server_root=server_site)
                self.runtime(split_env, "server", extra_path=paths, server_root=server_site)
                self.check(f"split-{variant}-{order}", behavior=result)
        for variant in ("current", "native"):
            for order in ("server-sdk", "sdk-server"):
                self.order_case(variant, order, editable=True)
        for name, original in self.source_inputs.items():
            assert safe_files(self.run / "build-inputs" / name) == original, "build/editable altered an input copy"
        self.check("all-build-input-copies-preserved-after-installers")

    def execute(self):
        before = snapshot(self.repo)
        write_json(self.run / "preservation-before.json", before)
        assert before["manifest_sha256"] == INITIAL_MANIFEST, "source drift since assignment preflight"
        assert before["index_sha256"] == INITIAL_INDEX, "index drift since assignment preflight"
        result = {"result": "incomplete", "product_pass": False,
                  "configured_profile": "maximum", "provider_acceptance": "not-proven",
                  "deferred": ["make docs with assigned cache", "python roadmap/check_docs.py",
                               "independent maximum review"], "outside_cwd": str(self.outside)}
        try:
            # Downloads also use the private HOME/TMPDIR, never inherited credentials/config.
            os.environ.clear()
            os.environ.update(self.env)
            version = self.command("python-version", [self.python, "-I", "-B", "-c",
                "import json,sys; print(json.dumps({'version': sys.version, 'minor': list(sys.version_info[:2]), "
                "'prefix': sys.prefix, 'base_prefix': sys.base_prefix, 'executable': sys.executable}))"], parse=True)
            assert version["minor"] == [3, 12], "minimum-version probe requires independent CPython 3.12"
            assert version["prefix"] == version["base_prefix"]
            assert not Path(version["executable"]).is_relative_to(self.repo)
            uv_version = self.uv_command("uv-version", "--version")
            assert uv_version.startswith("uv 0.12.19 "), uv_version
            result["python"] = version
            result["uv"] = uv_version
            self.download_inputs()
            self.prepare_sources()
            self.build()
            self.qualify()
            result["result"] = "bounded-assertions-satisfied-self-check-only"
        except BaseException as error:
            result["result"] = "blocked-or-failed"
            result["error"] = str(error)
            with (self.run / "failure.txt").open("x") as handle:
                handle.write(traceback.format_exc())
            raise
        finally:
            after = snapshot(self.repo)
            write_json(self.run / "preservation-after.json", after)
            result.update({"checks": self.checks, "check_count": len(self.checks),
                           "runtime_behavior_outcomes": self.runtime_outcomes,
                           "commands": self.commands, "command_count": len(self.commands),
                           "preservation_identical": before == after,
                           "source_manifest_sha256": after["manifest_sha256"],
                           "index_sha256": after["index_sha256"],
                           "residual_process_groups": self.residual_process_groups})
            write_json(self.run / "result.json", result)
            assert before == after, "source/index changed; preserve evidence and reconcile with parent"
            assert not self.residual_process_groups
            print(f"RESULT {result['result']}; {len(self.checks)} observations; "
                  f"{self.runtime_outcomes} SDK behavior outcomes; {len(self.commands)} commands", flush=True)


def main():
    """Refuse old run IDs and operate only on owned ignored throwaway artifacts."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--python", type=Path, default=Path("/usr/local/bin/python3.12"))
    parser.add_argument("--outside-cwd", type=Path, default=Path("/tmp/opencode"))
    args = parser.parse_args()
    assert sys.flags.isolated and sys.flags.dont_write_bytecode, "invoke with -I -B"
    repo = args.repo.resolve(strict=True)
    assert git(repo, "check-ignore", str(SUBJECT)).strip()
    assert not git(repo, "ls-files", "roadmap").strip()
    uv = shutil.which("uv")
    assert uv, "uv 0.12.19 is required"
    probe = Probe(repo, args.run_id, args.python, args.outside_cwd.resolve(strict=True), uv)
    probe.execute()


if __name__ == "__main__":
    main()
