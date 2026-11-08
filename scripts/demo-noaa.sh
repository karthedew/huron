#!/usr/bin/env bash
# Load the NOAA Planetary K-index demo into a running `make app` stack: `make demo-noaa`.
#
# It creates the catalog planetary in the organization noaa (declared in huron.dev.yaml) with
# examples/noaa/load.sh, from the raw NOAA SWPC files that examples/noaa/fetch.py downloads:
#
#   1. checks that the API answers http://127.0.0.1:8080/readyz;
#   2. gives the CLI a configuration and state of its own under
#      ${XDG_CACHE_HOME:-~/.cache}/huron/demo-noaa/{config,state}, so your own CLI configuration,
#      tokens and working copies are never read or changed;
#   3. signs that CLI in as the development platform admin admin/admin (scripts/dev-login.sh: the
#      Keycloak password grant of the development realm, then the token exchange);
#   4. downloads the raw files into ${XDG_CACHE_HOME:-~/.cache}/huron/demo-noaa/raw once (about
#      90 s; an interrupted download resumes, skipping the files already complete). Later runs reuse
#      that download, so they change nothing; NOAA_REFRESH=1 fetches again, which brings the
#      reissued current quarter and today's snapshot. NOAA_RAW=<dir> uses an existing fetch.py
#      output directory instead and downloads nothing;
#   5. runs `huron adm provision-orgs` (safe to re-run) and examples/noaa/load.sh;
#   6. prints `huron --catalog planetary tree` and the files under noaa's directory.
#
# Every step is idempotent: a second run reports every catalog entry as skipped and pushes nothing.
# After `make app-reset` the database is empty but /data1/huron is not: the directories and files
# of the earlier load are reused (the create commands accept an existing directory, a push replaces
# the file at the same path) and nothing on the share is deleted.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
api="http://127.0.0.1:8080"
issuer="http://127.0.0.1:8081/realms/company"
org="noaa"
catalog="planetary"
cache="${XDG_CACHE_HOME:-$HOME/.cache}/huron/demo-noaa"

say() { printf 'demo-noaa: %s\n' "$*" >&2; }
fail() { say "$1"; [[ $# -lt 2 ]] || say "hint: $2"; exit 1; }

# --- 1. the API -----------------------------------------------------------------------------------
if ! curl -fsS -o /dev/null --max-time 5 "$api/readyz"; then
  fail "the API at $api is not ready" "start it with: make app"
fi

# --- 2. a CLI of its own --------------------------------------------------------------------------
# The CLI from the project's environment, found before XDG_* change, so uv keeps its own
# configuration; load.sh runs this same executable.
huron_bin="$(uv run --quiet --project "$repo" python -I -c \
  'import os, sys; print(os.path.join(os.path.dirname(sys.executable), "huron"))')"
[[ -x "$huron_bin" ]] || fail "no huron command at $huron_bin" "run: uv sync"
export XDG_CONFIG_HOME="$cache/config" XDG_STATE_HOME="$cache/state"
# A HURON_* variable wins over the configuration (dev.env's HURON_ISSUER is the API's own issuer).
unset HURON_ISSUER HURON_API_URL HURON_CLIENT_ID HURON_MOUNT_PREFIX
huron() { "$huron_bin" "$@"; }
huron config set api_url "$api" >/dev/null
huron config set issuer "$issuer" >/dev/null
say "CLI configuration and state: $cache/{config,state}"

# --- 3. sign in -----------------------------------------------------------------------------------
# shellcheck source=scripts/dev-login.sh
source "$repo/scripts/dev-login.sh"
HURON_DEV_ISSUER="$issuer" dev_login admin admin "$api" \
  || fail "could not sign in as admin" "is Keycloak up at $issuer? (make app)"
say "signed in as admin"
# The organization: declared in huron.dev.yaml, so the API created it at startup.
work="$(mktemp -d "${TMPDIR:-/tmp}/demo-noaa.XXXXXX")"
trap 'rm -rf "$work"' EXIT
rc=0
huron -o json describe org "$org" >"$work/org.json" 2>"$work/org.err" || rc=$?
case "$rc" in
  0) ;;
  5) fail "the API has no organization $org" "declare it in huron.dev.yaml, then run: make app" ;;
  *) cat "$work/org.err" >&2; fail "could not read the organization $org" ;;
esac
# Its directory on this machine: root/name from the API, or the CLI's mount prefix without a root.
noaa_dir="$(python3 -I -c '
import json, sys
view = json.load(open(sys.argv[1]))
print(view.get("path") or "")' "$work/org.json")"
if [[ -z "$noaa_dir" ]]; then
  noaa_dir="$(huron -o json config show | python3 -I -c 'import json,sys; print(json.load(sys.stdin)["mount_prefix"])')/$org"
fi

# --- 4. the raw files -----------------------------------------------------------------------------
if [[ -n "${NOAA_RAW:-}" ]]; then
  raw="$NOAA_RAW"
  [[ -f "$raw/manifest.json" ]] || fail "NOAA_RAW=$raw holds no manifest.json" \
    "point it at a directory written by: python3 -I examples/noaa/fetch.py --out <dir>"
  say "raw files: $raw (NOAA_RAW; nothing downloaded)"
else
  raw="$cache/raw"
  if [[ ! -f "$raw/manifest.json" || "${NOAA_REFRESH:-0}" == 1 ]]; then
    say "downloading the NOAA SWPC files into $raw (about 90 s)"
    python3 -I "$repo/examples/noaa/fetch.py" --out "$raw" >&2 \
      || fail "the download failed" "run make demo-noaa again (it resumes), or set NOAA_RAW=<dir>"
  else
    say "raw files: $raw (downloaded earlier; NOAA_REFRESH=1 fetches again)"
  fi
fi

# --- 5. the organization directories and the catalog ---------------------------------------------
huron adm provision-orgs
ORG="$org" CATALOG="$catalog" HURON="$huron_bin" TREE=0 \
  "$repo/examples/noaa/load.sh" "$raw"

# --- 6. the result --------------------------------------------------------------------------------
echo
huron --catalog "$catalog" tree
echo
echo "files on disk, under $noaa_dir/$catalog:"
find "$noaa_dir/$catalog" -type f | sed "s|^$noaa_dir/$catalog/|  |" | sort
cat <<EOF

Browse it in the web at http://localhost:3000/catalogs/$catalog (sign in as admin, or as user,
a member of noaa-readers), or with this demo's CLI, from any directory:
  env -u HURON_ISSUER -u HURON_API_URL -u HURON_CLIENT_ID -u HURON_MOUNT_PREFIX \\
    XDG_CONFIG_HOME=$XDG_CONFIG_HOME XDG_STATE_HOME=$XDG_STATE_HOME $huron_bin --catalog $catalog get collections
EOF
