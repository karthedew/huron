"""Download NOAA SWPC's raw Planetary K-index files, unchanged, with a manifest.

Usage::

    python examples/noaa/fetch.py --out DIR [--months 12] [--today YYYY-MM-DD] [--force]

The window is the last ``--months`` calendar months up to ``--today`` (default: today, UTC).
Every quarter that overlaps it is fetched as SWPC's quarterly *Daily Geomagnetic Data* file
(``<YYYY>Q<n>_DGD.txt``: per day, the Fredericksburg, College and estimated planetary A index
and eight 3-hourly K indices). The current quarter's file is still growing, so it is always
fetched again, as is a dated snapshot of the 3-hourly ``noaa-planetary-k-index.json`` product
(the last seven days, with station counts). SWPC's description of the DGD columns is saved as
``old_indices_README.txt``.

Completed files already in ``DIR`` with the same size as the remote copy are skipped unless
``--force`` is given. Each file is tried over HTTPS first and then anonymous FTP from the same
NOAA host; a host that fails to connect is not tried again in the same run. ``DIR/manifest.json``
lists every file with its source URL, SHA-256, size, retrieval time and the period it covers,
read from the file itself (the dated rows of a DGD file, the ``time_tag`` values of the JSON).
"""

from __future__ import annotations

import argparse
import contextlib
import ftplib
import hashlib
import json
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

USER_AGENT = (
    "huron-example-noaa-kp/1.0 (+https://github.com/karthedew/huron; "
    "raw Planetary K-index fetch for a data catalog example)"
)
FTP_HOST = "ftp.swpc.noaa.gov"
SERVICES_HOST = "services.swpc.noaa.gov"
MANIFEST = "manifest.json"
ATTEMPTS = 4
TIMEOUT_SECONDS = 60.0
RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})


@dataclass(frozen=True)
class Source:
    """One raw file to fetch: where it goes in ``DIR`` and the URLs to try, in order."""

    file: str
    urls: tuple[str, ...]
    kind: str
    refresh: bool = False
    """Always download again, even when a same-sized copy exists (a still-growing product)."""
    quarter: tuple[int, int] | None = None
    """The ``(year, quarter)`` a DGD file must start in; guards the ``quar_DGD.txt`` fallback."""


@dataclass(frozen=True)
class Fetched:
    """A file now present in ``DIR`` and the URL it came from."""

    source: Source
    url: str
    retrieved_at: str


class FetchError(Exception):
    """A file could not be downloaded from any of its URLs."""


class WrongContent(ValueError):
    """A downloaded file is not the one its name promises."""


def plan(today: date, months: int, retrieved_on: date) -> list[Source]:
    """The files covering the ``months`` calendar months that end with ``today``'s month."""
    start = _months_before(today.replace(day=1), months - 1)
    sources = [
        Source(
            file="old_indices_README.txt",
            urls=_ftp_host_urls("pub/indices/old_indices/README"),
            kind="documentation",
        )
    ]
    current = _quarter(today)
    for year, quarter in _quarters(_quarter(start), current):
        is_current = (year, quarter) == current
        paths = [f"pub/indices/old_indices/{year}Q{quarter}_DGD.txt"]
        if is_current:
            paths.append("pub/indices/quar_DGD.txt")
        sources.append(
            Source(
                file=f"{year}Q{quarter}_DGD.txt",
                urls=tuple(url for path in paths for url in _ftp_host_urls(path)),
                kind="dgd-current-quarter" if is_current else "dgd-quarter",
                refresh=is_current,
                quarter=(year, quarter),
            )
        )
    sources.append(
        Source(
            file=f"noaa-planetary-k-index-{retrieved_on.isoformat()}.json",
            urls=(f"https://{SERVICES_HOST}/products/noaa-planetary-k-index.json",),
            kind="kp-3hour-snapshot",
            refresh=True,
        )
    )
    return sources


def fetch(sources: list[Source], out: Path, *, force: bool, delay: float) -> list[Fetched]:
    """Download each source into ``out``; raise ``FetchError`` naming the ones that failed."""
    out.mkdir(parents=True, exist_ok=True)
    previous = {entry["file"]: entry for entry in read_manifest(out)}
    dead_hosts: set[str] = set()
    fetched: list[Fetched] = []
    failures: list[str] = []
    for source in sources:
        try:
            fetched.append(_fetch_one(source, out, previous, dead_hosts, force=force))
        except FetchError as error:
            failures.append(f"{source.file}: {error}")
        time.sleep(delay)
    if failures:
        write_manifest(out, fetched, previous)
        raise FetchError("; ".join(failures))
    return fetched


def write_manifest(out: Path, fetched: list[Fetched], previous: dict[str, Any]) -> list[Any]:
    """Write ``out/manifest.json``: this run's files, then earlier entries whose file remains."""
    entries = [_entry(out, item) for item in fetched]
    listed = {entry["file"] for entry in entries}
    entries += [
        entry
        for name, entry in sorted(previous.items())
        if name not in listed and (out / name).is_file()
    ]
    (out / MANIFEST).write_text(json.dumps(entries, indent=2) + "\n")
    return entries


def read_manifest(out: Path) -> list[Any]:
    """The entries of an existing ``out/manifest.json``, or none."""
    path = out / MANIFEST
    if not path.is_file():
        return []
    entries = json.loads(path.read_text())
    return entries if isinstance(entries, list) else []


def coverage(path: Path, kind: str) -> dict[str, str] | None:
    """The first and last period a raw file reports (inclusive), or ``None`` for documentation.

    DGD rows start with ``YYYY MM DD``, so the dates are whole UTC days. The JSON product's
    ``time_tag`` values are the starts of 3-hour intervals.
    """
    if kind.startswith("dgd"):
        days = [
            date(int(m[1]), int(m[2]), int(m[3])).isoformat()
            for m in re.finditer(r"^(\d{4}) (\d{2}) (\d{2})\s", path.read_text(), re.MULTILINE)
        ]
        return {"start": days[0], "end": days[-1]} if days else None
    if kind == "kp-3hour-snapshot":
        tags = _time_tags(json.loads(path.read_text()))
        return {"start": tags[0], "end": tags[-1]} if tags else None
    return None


def issued(path: Path, kind: str) -> str | None:
    """When SWPC issued a DGD file, from its ``:Issued: HHMM UT DD Mon YYYY`` header line."""
    if not kind.startswith("dgd"):
        return None
    found = re.search(r"^:Issued:\s*(\d{4}) UT (\d{1,2} \w{3} \d{4})", path.read_text(), re.M)
    if found is None:
        return None
    stamp = datetime.strptime(f"{found[2]} {found[1]}", "%d %b %Y %H%M").replace(tzinfo=UTC)
    return _iso(stamp)


def main(argv: list[str] | None = None) -> int:
    """Fetch the files, write the manifest and print one line per file."""
    args = _parser().parse_args(argv)
    if args.months < 1:
        print("--months must be at least 1", file=sys.stderr)
        return 2
    now = datetime.now(UTC)
    today = date.fromisoformat(args.today) if args.today else now.date()
    sources = plan(today, args.months, retrieved_on=now.date())
    try:
        fetched = fetch(sources, args.out, force=args.force, delay=args.delay)
    except FetchError as error:
        print(f"fetch failed: {error}", file=sys.stderr)
        return 1
    previous = {entry["file"]: entry for entry in read_manifest(args.out)}
    for entry in write_manifest(args.out, fetched, previous):
        covers = entry["covers"]
        span = f"{covers['start']} .. {covers['end']}" if covers else "-"
        print(f"{entry['file']:<44} {entry['size']:>8}  {span}")
    return 0


def _fetch_one(
    source: Source,
    out: Path,
    previous: dict[str, Any],
    dead_hosts: set[str],
    *,
    force: bool,
) -> Fetched:
    target = out / source.file
    errors: list[str] = []
    for url in source.urls:
        origin = _origin(url)
        if origin in dead_hosts:
            continue
        try:
            if not (force or source.refresh) and target.is_file():
                size = _remote_size(url)
                if size == target.stat().st_size:
                    return Fetched(source, url, _retrieved_at(target, previous))
            _download(url, target, source)
            return Fetched(source, url, _iso(datetime.now(UTC)))
        except urllib.error.HTTPError as error:
            errors.append(f"{url}: HTTP {error.code}")
        except WrongContent as error:
            errors.append(f"{url}: {error}")
        except (OSError, ftplib.Error) as error:
            if _is_unreachable(error):
                dead_hosts.add(origin)
            errors.append(f"{url}: {error}")
    raise FetchError(", ".join(errors) or "no reachable URL")


def _download(url: str, target: Path, source: Source) -> None:
    partial = target.with_name(target.name + ".part")
    for attempt in range(1, ATTEMPTS + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                expected = response.headers.get("Content-Length")
                with partial.open("wb") as sink:
                    while chunk := response.read(64 * 1024):
                        sink.write(chunk)
            if expected is not None and partial.stat().st_size != int(expected):
                raise OSError(f"short read: {partial.stat().st_size} of {expected} bytes")
            _check(partial, source)
            partial.replace(target)
            return
        except urllib.error.HTTPError as error:
            if error.code not in RETRYABLE_STATUS or attempt == ATTEMPTS:
                raise
            _back_off(attempt, error.headers.get("Retry-After"))
        except (OSError, ftplib.Error) as error:
            if not _is_transient(error) or attempt == ATTEMPTS:
                raise
            _back_off(attempt, None)
        finally:
            partial.unlink(missing_ok=True)


def _remote_size(url: str) -> int | None:
    parts = urlsplit(url)
    if parts.scheme == "ftp":
        with ftplib.FTP(parts.hostname or "", timeout=TIMEOUT_SECONDS) as client:
            client.login()
            client.voidcmd("TYPE I")
            return client.size(parts.path)
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        length = response.headers.get("Content-Length")
        return int(length) if length is not None else None


def _check(path: Path, source: Source) -> None:
    if source.quarter is None:
        return
    covers = coverage(path, source.kind)
    if covers is None or _quarter(date.fromisoformat(covers["start"])) != source.quarter:
        year, quarter = source.quarter
        found = covers["start"] if covers else "no dated rows"
        raise WrongContent(f"expected {year}Q{quarter} data, found {found}")


def _entry(out: Path, item: Fetched) -> dict[str, Any]:
    path = out / item.source.file
    return {
        "file": item.source.file,
        "url": item.url,
        "sha256": _sha256(path),
        "size": path.stat().st_size,
        "retrieved_at": item.retrieved_at,
        "covers": coverage(path, item.source.kind),
        "kind": item.source.kind,
        "issued": issued(path, item.source.kind),
    }


def _retrieved_at(target: Path, previous: dict[str, Any]) -> str:
    entry = previous.get(target.name)
    if entry and entry.get("size") == target.stat().st_size and entry.get("retrieved_at"):
        return str(entry["retrieved_at"])
    return _iso(datetime.fromtimestamp(target.stat().st_mtime, UTC))


def _time_tags(document: Any) -> list[str]:
    if not isinstance(document, list) or not document:
        return []
    if isinstance(document[0], list):  # older layout: a header row, then value rows
        column = document[0].index("time_tag")
        return sorted(str(row[column]) for row in document[1:])
    return sorted(str(row["time_tag"]) for row in document if "time_tag" in row)


def _ftp_host_urls(path: str) -> tuple[str, ...]:
    return (f"https://{FTP_HOST}/{path}", f"ftp://{FTP_HOST}/{path}")


def _quarter(day: date) -> tuple[int, int]:
    return day.year, (day.month - 1) // 3 + 1


def _quarters(first: tuple[int, int], last: tuple[int, int]) -> list[tuple[int, int]]:
    year, quarter = first
    found = []
    while (year, quarter) <= last:
        found.append((year, quarter))
        year, quarter = (year + 1, 1) if quarter == 4 else (year, quarter + 1)
    return found


def _months_before(first_of_month: date, months: int) -> date:
    index = first_of_month.year * 12 + first_of_month.month - 1 - months
    return date(index // 12, index % 12 + 1, 1)


def _back_off(attempt: int, retry_after: str | None) -> None:
    wait = 2.0**attempt
    if retry_after is not None:
        with contextlib.suppress(ValueError):
            wait = max(wait, float(retry_after))
    time.sleep(min(wait, 120.0))


def _is_unreachable(error: BaseException) -> bool:
    """The host refused or broke the connection, so its other files will fail the same way."""
    reason = error.reason if isinstance(error, urllib.error.URLError) else error
    return isinstance(reason, ssl.SSLError | ConnectionError | TimeoutError | socket.gaierror)


def _is_transient(error: BaseException) -> bool:
    """Worth retrying: not a TLS failure and not a missing file (FTP ``550``)."""
    if isinstance(error.__cause__, ftplib.error_perm) or isinstance(error, ftplib.error_perm):
        return False
    reason = error.reason if isinstance(error, urllib.error.URLError) else error
    return not isinstance(reason, ssl.SSLError)


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--out", type=Path, required=True, help="directory for the raw files")
    parser.add_argument("--months", type=int, default=12, help="calendar months to cover")
    parser.add_argument("--today", help="last day of the window, YYYY-MM-DD (default: UTC today)")
    parser.add_argument("--force", action="store_true", help="download even same-sized files")
    parser.add_argument(
        "--delay", type=float, default=1.0, help="seconds to wait between files (default 1)"
    )
    return parser


if __name__ == "__main__":
    sys.exit(main())
