"""Documentation links resolve, and the link checker finds broken ones."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def checker():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(
        "check_links", ROOT / "scripts" / "check_links.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repository_docs_have_no_broken_links() -> None:
    assert (
        checker().main(
            [str(ROOT / "README.md"), str(ROOT / "docs"), str(ROOT / "deploy" / "README.md")]
        )
        == 0
    )


def test_broken_links_are_reported(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "a.md").write_text("[ok](b.md) [web](https://x) [anchor](#y) [bad](missing.md#z)")
    (tmp_path / "b.md").write_text("")
    assert checker().main([str(tmp_path)]) == 1
    assert "missing.md#z" in capsys.readouterr().out
