#!/usr/bin/env bash
# Load the raw NOAA SWPC K-index files fetched by fetch.py into Huron, as raw files (no conversion).
#
#   examples/noaa/load.sh RAW_DIR
#
# RAW_DIR is fetch.py's --out directory (its manifest.json lists every file with its sha256). The
# caller logs in first (huron login, or a token in $XDG_STATE_HOME/huron/tokens.json) as someone
# who may create catalogs in the organization: a platform admin or one of its org admins.
#
# Access: the script grants nothing. Every catalog of the organization inherits the organization's
# groups (groups.reader and the other roles of its entry in the service configuration, such as
# noaa-readers in huron.dev.yaml); when the organization has no reader group the script says so.
#
# Layout (CATALOG.k-index...): k-index (no collections) holds k-index.quarterly, one collection
# per quarter (2025-q4, 2026-q1, ...) with that quarter's raw DGD file, and k-index.snapshots,
# whose collection 3-hour holds the dated noaa-planetary-k-index-<date>.json snapshots.
#
# Idempotent: the catalog, the namespaces and the collections are created only when
# missing; a file is pushed only when the collection does not record it with the same sha256; the
# metadata is republished (huron edit meta --file, then huron publish meta) only when it differs
# from what the collection holds. A second run with the same RAW_DIR changes nothing.
#
# Directories left on the share by an earlier load whose records are gone (after `make app-reset`,
# which deletes the database but not the lake) stop the load: a create command accepts an existing
# directory only when it is empty. Nothing on the share is deleted.
#
# Environment: ORG (noaa), CATALOG (planetary), HURON (the command that runs the CLI; default
# `uv run --quiet --project <repo> huron`), TREE (1; 0 skips the closing `huron tree`).
set -euo pipefail

if [[ $# -ne 1 || ! -f "$1/manifest.json" ]]; then
  echo "usage: $0 RAW_DIR   (RAW_DIR holds fetch.py's manifest.json)" >&2
  exit 2
fi
raw="$(cd "$1" && pwd)"
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
org="${ORG:-noaa}"
catalog="${CATALOG:-planetary}"
read -r -a huron_cmd <<<"${HURON:-uv run --quiet --project $repo huron}"

# Identifiers are resolved against $catalog (huron --catalog) once it exists, never against the
# caller's current catalog.
in_catalog=()
huron() { "${huron_cmd[@]}" "${in_catalog[@]}" "$@"; }
log() { printf 'load: %s\n' "$*" >&2; }

work="$(mktemp -d "${TMPDIR:-/tmp}/noaa-load.XXXXXX")"
trap 'rm -rf "$work"' EXIT

# exists KIND ARGS...: 0 when `huron describe KIND ARGS` finds it, 1 when not found (exit 5),
# any other failure stops the script. The JSON lands in $work/describe.json.
exists() {
  local rc=0
  huron -o json describe "$@" >"$work/describe.json" 2>"$work/describe.err" || rc=$?
  case "$rc" in
    0) return 0 ;;
    5) return 1 ;;
    *) cat "$work/describe.err" >&2; exit "$rc" ;;
  esac
}

huron whoami >/dev/null || { log "log in first (huron login)"; exit 3; }

# --- catalog and access ---------------------------------------------------------------------------
if exists catalog "$catalog"; then
  log "catalog $catalog exists; skipped"
else
  huron create catalog "$catalog" --org "$org" \
    --display-name "Planetary K-index" \
    --description "Raw NOAA SWPC Planetary K-index data: quarterly Daily Geomagnetic Data files (Fredericksburg, College and estimated planetary K and A indices) and dated snapshots of the 3-hourly planetary K-index product."
fi

# Readers come from the organization: report its organization-wide reader groups, grant nothing.
readers="$(huron -o json get grants --catalog "$catalog" | python3 -I -c '
import json, sys
print(" ".join(sorted({s["group"] for s in json.load(sys.stdin)
                       if s["role"] == "reader" and s["scope"] == "organization"})))')"
if [[ -n "$readers" ]]; then
  log "$catalog is read by $org's readers: $readers"
else
  log "$org has no organization-wide reader group; set groups.reader in its service configuration entry"
fi
in_catalog=(--catalog "$catalog")

# --- namespaces -----------------------------------------------------------------------------------
# ensure_namespace PATH ALLOW: create catalog.PATH when missing, check collections_allowed otherwise.
ensure_namespace() {
  local identifier="$catalog.$1" allow="$2"
  if exists namespace "$identifier"; then
    python3 -I -c '
import json, sys
view = json.load(open(sys.argv[1]))
want = sys.argv[2] == "true"
have, identifier = view["collections_allowed"], view["identifier"]
if bool(have) != want:
    sys.exit(f"load: {identifier} has collections_allowed={have}, expected {want}")
' "$work/describe.json" "$allow"
    log "namespace $identifier exists; skipped"
  elif [[ "$allow" == true ]]; then
    huron create namespace "$identifier" --allow-collections
  else
    huron create namespace "$identifier"
  fi
}
ensure_namespace k-index false
ensure_namespace k-index.quarterly true
ensure_namespace k-index.snapshots true

# --- collections ----------------------------------------------------------------------------------
# The plan: one line per collection, "<namespace path>\t<name>\t<push message>". It also checks
# every local file against the manifest's sha256 before anything is sent.
python3 -I - "$raw" "$work/plan.tsv" <<'PY'
import hashlib, json, pathlib, sys

raw, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
manifest = json.loads((raw / "manifest.json").read_text())
lines = []
for entry in manifest:
    path = raw / entry["file"]
    if entry["kind"] == "documentation" or not path.is_file():
        continue
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != entry["sha256"] or path.stat().st_size != entry["size"]:
        sys.exit(f"load: {path} does not match its manifest entry (sha256 or size); fetch again")
    if entry["kind"] in ("dgd-quarter", "dgd-current-quarter"):
        year, quarter = entry["file"][:4], entry["file"][5]
        lines.append(f"k-index.quarterly\t{year}-q{quarter}\t{entry['url']}")
    elif entry["kind"] == "kp-3hour-snapshot":
        lines.append(f"k-index.snapshots\t3-hour\t{entry['url']}")
out.write_text("".join(f"{line}\n" for line in dict.fromkeys(lines)))
PY

# build_metadata NAMESPACE NAME EXISTING_JSON OUT_JSON FILES_TXT: the collection's metadata from the
# manifest, keeping retrieved_at of files the collection already holds with the same sha256, and
# the files that belong in the collection (one name per line).
build_metadata() {
  python3 -I - "$raw" "$@" <<'PY'
import datetime as dt, json, pathlib, sys

raw = pathlib.Path(sys.argv[1])
namespace, name, existing_path, out, files_out = sys.argv[2:7]
manifest = json.loads((raw / "manifest.json").read_text())
existing = json.loads(pathlib.Path(existing_path).read_text()) if existing_path != "-" else {}
before = {f["name"]: f for f in existing.get("metadata", {}).get("files", [])}
docs = next((e["url"] for e in manifest if e["kind"] == "documentation"), None)
present = [e for e in manifest if e["kind"] != "documentation" and (raw / e["file"]).is_file()]


def file_entry(e):
    kept = before.get(e["file"])
    retrieved = kept["retrieved_at"] if kept and kept.get("sha256") == e["sha256"] else e["retrieved_at"]
    entry = {"name": e["file"], "url": e["url"], "sha256": e["sha256"], "size": e["size"],
             "retrieved_at": retrieved, "covers": e["covers"]}
    if e.get("issued"):
        entry["issued"] = e["issued"]
    return entry


def instant(text, step):
    """The start of a day or 3-hour slot, or with step the end of it (exclusive), as UTC."""
    if "T" in text:
        start = dt.datetime.fromisoformat(text).replace(tzinfo=dt.timezone.utc)
        delta = dt.timedelta(hours=3)
    else:
        start = dt.datetime.combine(dt.date.fromisoformat(text), dt.time(), dt.timezone.utc)
        delta = dt.timedelta(days=1)
    return (start + delta if step else start).strftime("%Y-%m-%dT%H:%M:%SZ")


keywords = ["geomagnetic activity", "K index", "Kp", "A index", "space weather"]
source = {"publisher": "NOAA Space Weather Prediction Center (SWPC)"}
if namespace == "k-index.quarterly":
    year, quarter = name.split("-q")
    entries = [e for e in present if e["kind"].startswith("dgd") and e["file"] == f"{year}Q{quarter}_DGD.txt"]
    (e,) = entries
    current = e["kind"] == "dgd-current-quarter"
    start, end = e["covers"]["start"], e["covers"]["end"]
    description = (
        f"Raw NOAA SWPC Daily Geomagnetic Data (DGD) file for {year} Q{quarter}, {start} to {end}:"
        " one row per UT day with the daily A index and the eight 3-hourly K indices of three sets,"
        " Fredericksburg, College and the estimated planetary index (Kp). Missing values are -1."
        " These are SWPC's preliminary values, not the definitive GFZ Kp."
    )
    if current:
        description += (
            f" This is the current quarter: SWPC reissues it daily (this copy issued {e.get('issued')})"
            " and its last day may be incomplete."
        )
    document = {
        "title": f"NOAA SWPC Daily Geomagnetic Data, {year} Q{quarter}",
        "description": description,
        "instrument": "Ground magnetometers: Fredericksburg and College observatories, SWPC planetary estimate",
        "keywords": keywords,
        "start_time": instant(start, False),
        "end_time": instant(end, True),
        "labels": {
            "source": "noaa-swpc", "product": "daily-geomagnetic-data", "quarter": name,
            "year": year, "cadence": "3-hour", "format": "text",
            "status": "in-progress" if current else "complete",
        },
    }
    source["url"] = e["url"]
else:
    entries = [e for e in present if e["kind"] == "kp-3hour-snapshot"]
    files = {f["name"]: f for f in before.values()}  # snapshots pushed earlier stay listed
    for e in entries:
        files[e["file"]] = file_entry(e)
    ordered = [files[k] for k in sorted(files)]
    start = min(f["covers"]["start"] for f in ordered)
    end = max(f["covers"]["end"] for f in ordered)
    document = {
        "title": "NOAA SWPC planetary K-index, 3-hourly snapshots",
        "description": (
            "Dated snapshots of SWPC's noaa-planetary-k-index.json product, as fetched: about the"
            " last seven days of 3-hourly estimated planetary K index (Kp) with the running a index"
            " and the number of contributing stations, one file per retrieval date. time_tag is the"
            " start of each 3-hour interval (UT). Preliminary values, not the definitive GFZ Kp."
        ),
        "instrument": "SWPC estimated planetary K index from real-time ground magnetometers",
        "keywords": keywords,
        "start_time": instant(start, False),
        "end_time": instant(end, True),
        "labels": {
            "source": "noaa-swpc", "product": "planetary-k-index", "cadence": "3-hour",
            "format": "json", "status": "rolling", "snapshots": str(len(ordered)),
        },
    }
    source["url"] = entries[0]["url"] if entries else ordered[0]["url"]
if docs and namespace == "k-index.quarterly":
    source["documentation"] = docs
document["source"] = source
document["files"] = [file_entry(e) for e in entries] if namespace == "k-index.quarterly" else ordered
pathlib.Path(out).write_text(json.dumps(document, indent=2) + "\n")
pathlib.Path(files_out).write_text("".join(f"{e['file']}\n" for e in entries))
PY
}

while IFS=$'\t' read -r -u 3 namespace name message; do
  identifier="$catalog.$namespace.$name"
  meta="$work/$name.metadata.json"
  if exists collection "$identifier"; then
    cp "$work/describe.json" "$work/existing.json"
    build_metadata "$namespace" "$name" "$work/existing.json" "$meta" "$work/files.txt"
    created=false
  else
    build_metadata "$namespace" "$name" - "$meta" "$work/files.txt"
    huron create collection "$identifier" --metadata "$meta"
    created=true
  fi
  huron checkout "$identifier" >/dev/null

  # Stage only the files the collection does not record with the same sha256.
  huron -o json get files "$identifier" >"$work/recorded.json"
  mapfile -t changed < <(python3 -I - "$raw" "$work/files.txt" "$work/recorded.json" <<'PY'
import json, pathlib, sys
raw = pathlib.Path(sys.argv[1])
recorded = {f["rel_path"]: f["sha256"] for f in json.loads(pathlib.Path(sys.argv[3]).read_text())}
manifest = {e["file"]: e for e in json.loads((raw / "manifest.json").read_text())}
for name in pathlib.Path(sys.argv[2]).read_text().split():
    if recorded.get(name) != manifest[name]["sha256"]:
        print(raw / name)
PY
  )
  if ((${#changed[@]})); then
    huron add "${changed[@]}"
    huron push -m "$message"
  else
    log "$identifier: every file is recorded with the same sha256; nothing to push"
  fi

  # Republish the metadata when it differs (a new current-quarter issue, a new snapshot).
  if [[ "$created" == false ]]; then
    if python3 -I -c '
import json, sys
held = json.load(open(sys.argv[1]))["metadata"]
sys.exit(0 if held == json.load(open(sys.argv[2])) else 1)' "$work/existing.json" "$meta"; then
      log "$identifier: metadata unchanged"
    else
      huron edit meta "$identifier" --file "$meta"
      huron validate meta "$identifier"
      huron publish meta "$identifier"
    fi
  fi
done 3<"$work/plan.tsv"

if [[ "${TREE:-1}" != 0 ]]; then
  huron tree
fi
