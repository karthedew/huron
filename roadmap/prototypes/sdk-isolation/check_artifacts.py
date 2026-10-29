"""Check owned text, evidence reproducibility, repository preservation and Git hygiene."""

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import tomllib


SUBJECT = Path(__file__).resolve().parent


def main():
    """Write one fresh, owned gate receipt without running shared documentation checks."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="append", required=True)
    parser.add_argument("--receipt", required=True)
    args = parser.parse_args()
    assert sys.flags.isolated and sys.flags.dont_write_bytecode
    assert re.fullmatch(r"[a-z0-9-]+\.json", args.receipt)
    output = SUBJECT / args.receipt
    assert not output.exists(), "refuse to overwrite a gate receipt"
    inventory_path = output.with_name(output.stem + "-files.json")
    assert not inventory_path.exists(), "refuse to overwrite an artifact inventory"
    helpers = runpy.run_path(str(SUBJECT / "probe.py"))
    repo = SUBJECT.parents[2]
    before = helpers["snapshot"](repo)
    assert before["manifest_sha256"] == helpers["INITIAL_MANIFEST"]
    assert before["index_sha256"] == helpers["INITIAL_INDEX"]
    authored = sorted(
        [path for path in SUBJECT.iterdir() if path.is_file() and path.suffix in {".py", ".md", ".json"}]
        + [path for path in (SUBJECT / "sdk").rglob("*") if path.is_file()]
    )
    text_hashes = {}
    links = []
    for path in authored:
        assert not path.is_symlink()
        text = path.read_text(encoding="utf-8")
        assert text.endswith("\n"), f"missing final newline: {path}"
        for number, line in enumerate(text.splitlines(), 1):
            assert line == line.rstrip(), f"trailing whitespace: {path}:{number}"
            assert "\x00" not in line
        if path.suffix == ".py":
            ast.parse(text, filename=str(path))
        elif path.suffix == ".toml":
            tomllib.loads(text)
        elif path.suffix == ".json":
            json.loads(text)
        elif path.suffix == ".md":
            for destination in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
                if "://" not in destination:
                    target = (path.parent / destination).resolve(strict=True)
                    assert target.is_relative_to(repo), destination
                    links.append(str(target.relative_to(repo)))
        text_hashes[str(path.relative_to(SUBJECT))] = hashlib.sha256(path.read_bytes()).hexdigest()

    runs = []
    for name in args.run:
        assert re.fullmatch(r"[a-z0-9-]+", name)
        run = SUBJECT / "runs" / name
        result = json.loads((run / "result.json").read_text())
        assert result["result"] == "bounded-assertions-satisfied-self-check-only"
        assert result["preservation_identical"]
        assert result["residual_process_groups"] == []
        assert result["check_count"] == 59 and result["runtime_behavior_outcomes"] == 595
        assert all(command["exit"] == 0 and not command["timed_out"] for command in result["commands"])
        assert result["command_count"] == 340
        driver_hashes = json.loads((run / "driver-hashes.json").read_text())
        for path, expected in driver_hashes.items():
            assert hashlib.sha256((run / "driver-inputs" / path).read_bytes()).hexdigest() == expected
            assert hashlib.sha256((SUBJECT / path).read_bytes()).hexdigest() == expected
        for command in result["commands"]:
            assert (run / command["log"]).is_file()
        runs.append({
            "run": name, "wheel_inventories": json.loads((run / "wheel-inventories.json").read_text()),
            "dependency_lock": json.loads((run / "dependency-lock.json").read_text()),
            "source_inputs": json.loads((run / "source-inputs.json").read_text()),
            "driver_hashes": driver_hashes, "check_count": result["check_count"],
            "runtime_behavior_outcomes": result["runtime_behavior_outcomes"],
            "command_count": result["command_count"],
        })
    assert len(runs) == 2 and runs[0]["run"] != runs[1]["run"]
    for field in ("wheel_inventories", "dependency_lock", "source_inputs", "driver_hashes"):
        assert runs[0][field] == runs[1][field], f"independent-run drift: {field}"

    commands = []
    for argv in (
        ["git", "diff", "--check"],
        ["git", "status", "--short", "--untracked-files=all"],
        ["git", "check-ignore", "roadmap/prototypes/sdk-isolation",
         *["roadmap/prototypes/sdk-isolation/runs/" + name for name in args.run]],
        ["git", "ls-files", "roadmap"],
    ):
        completed = subprocess.run(argv, cwd=repo, env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
                                   capture_output=True, text=True, check=True)
        if argv[1] == "ls-files":
            assert completed.stdout == ""
        commands.append({"argv": argv, "cwd": str(repo), "exit": completed.returncode,
                         "stdout": completed.stdout, "stderr": completed.stderr})
    after = helpers["snapshot"](repo)
    assert before == after
    files = {}
    for path in sorted(SUBJECT.rglob("*")):
        if path.is_symlink():
            files[str(path.relative_to(SUBJECT))] = {"symlink_target": os.readlink(path)}
        elif path.is_file():
            files[str(path.relative_to(SUBJECT))] = {
                "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()
            }
    helpers["write_json"](inventory_path, {"files": files, "excludes": [output.name, inventory_path.name]})
    receipt = {
        "result": "self-check-partial-pending-deferred-gates-and-independent-review",
        "commands": commands, "authored_text_hashes": text_hashes, "verified_local_links": links,
        "runs": [{key: value for key, value in run.items() if key not in {"wheel_inventories", "source_inputs"}}
                 for run in runs],
        "byte_identical_wheels": {name: data["sha256"] for name, data in runs[0]["wheel_inventories"].items()},
        "preservation": {key: value for key, value in after.items() if key != "entries"},
        "existing_files": sum(entry[1] != "missing" for entry in after["entries"]),
        "deleted_paths_preserved": sum(entry[1] == "missing" for entry in after["entries"]),
        "artifact_inventory": inventory_path.name,
        "artifact_paths": len(files),
        "deferred_commands": ["UV_CACHE_DIR=/tmp/opencode/huron-effort-uv-cache make docs",
                              "python roadmap/check_docs.py"],
    }
    helpers["write_json"](output, receipt)
    print(json.dumps({"result": receipt["result"], "receipt": str(output), "authored_text_files": len(authored),
                      "local_links": len(links), "artifact_paths": len(files),
                      "source_manifest_sha256": after["manifest_sha256"],
                      "index_sha256": after["index_sha256"]}, indent=2))


if __name__ == "__main__":
    main()
