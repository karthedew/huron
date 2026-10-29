"""Check ignored text and repository byte preservation without writing artifacts."""

import hashlib
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit


def main():
    """Compare the read-only repository inventory to the recorded pre-probe digest."""
    root = Path(__file__).resolve().parents[3]
    owned = Path(__file__).resolve().parent
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0")
    names += subprocess.check_output(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=root
    ).decode().split("\0")
    combined = hashlib.sha256()
    count = 0
    for name in sorted(set(names)):
        path = root / name
        if name and path.is_file():
            combined.update(name.encode() + b"\0" + path.read_bytes())
            count += 1
    assert combined.hexdigest() == "f1759128374aebe2282850cc4fd2428fd35805db80cdacfeb50933c2cf6469c5"
    index = hashlib.sha256((root / ".git/index").read_bytes()).hexdigest()
    assert index == "53998d200d18ee33dbebebc0aef391c4a4972ed0c8ba6afc23d052846c1283f8"
    print(f"Preserved {count} existing Git-visible files: {combined.hexdigest()}")
    print("Preserved index bytes:", index)
    files = sorted(p for p in owned.rglob("*") if p.is_file())
    links = 0
    for path in files:
        text = path.read_text()
        assert text.endswith("\n"), (path, "missing final newline")
        assert all(line.rstrip() == line for line in text.splitlines()), (path, "trailing whitespace")
        if path.suffix == ".md":
            for link in re.findall(r"\[[^\]\n]*\]\(([^\s)]+)\)", text):
                parsed = urlsplit(link)
                if not parsed.scheme and not parsed.netloc:
                    assert not parsed.fragment, (path, "fragment requires explicit check", link)
                    assert (path.parent / parsed.path).exists(), (path, "missing link", link)
                    links += 1
    print(f"Checked {len(files)} ignored text files and {links} local links; no whitespace defects")


if __name__ == "__main__":
    main()
