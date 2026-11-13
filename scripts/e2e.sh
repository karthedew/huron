#!/usr/bin/env bash
# Manual pre-release check against the Docker stack (docker-compose.app.yml; Docker required).
#
# Starts the stack's backend (PostgreSQL, the migrations, Keycloak, the group directory, the lake
# preparation, the API, tusd and the upload proxy) as its own compose project with an empty
# database and an empty temporary lake. Then it logs in as the development users through the
# Keycloak realm's password grant (enabled on the development realm only), walks the user guide,
# pushes files through the upload proxy and tusd, and removes the project with its volume and its
# API image. The web and the demo seed do not start. It needs the ports of `make app` and
# `make up`, so stop those first.
#
# The API runs in managed mode with a configuration of its own in place of huron.dev.yaml: the
# organizations of huron.dev.yaml (helio, geo and noaa) with their organization-wide role groups
# unchanged, and the lake path and the roots moved under the temporary directory
# (<tmp>/data1/huron). The lake has the same path on the host and in the containers, and the
# containers run as you.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
engine=docker
compose=(docker compose)
command -v docker >/dev/null 2>&1 || { engine=podman; compose=(podman-compose); }
compose+=(-f docker-compose.app.yml -p huron-e2e)
# An API image of its own: huron-app-api:dev of `make app` keeps its tag and its image.
export HURON_API_IMAGE=huron-e2e-api:dev

for port in 1080 3000 5432 8080 8081 8082; do
  if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
    echo "e2e: 127.0.0.1:$port is in use; stop make app (make app-down) or make up (make down)" >&2
    exit 1
  fi
done

# The CLI reads HURON_ISSUER as the company IdP; in dev.env it is the API's own token issuer.
unset HURON_ISSUER HURON_API_URL HURON_CLIENT_ID HURON_MOUNT_PREFIX

work="$(mktemp -d)"
cleanup() {
  "${compose[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  "$engine" image rm "$HURON_API_IMAGE" >/dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT

export HURON_DEV_CONFIG="$work/huron.yaml"
# huron.dev.yaml with lake_path and each root moved under the temporary directory: the same
# settings, organizations and `groups`, so this check follows any edit of that file. The script
# prints the lake path. The lake and the roots are created here: the containers bind the lake, and
# provision-orgs creates <root>/<org>, never a root.
lake="$(uv run python - huron.dev.yaml "$work" "$HURON_DEV_CONFIG" <<'PY'
import os
import sys

import yaml

with open(sys.argv[1], encoding="utf-8") as stream:
    config = yaml.safe_load(stream)
config["lake_path"] = sys.argv[2] + config["lake_path"]
os.makedirs(config["lake_path"], exist_ok=True)
for organization in config["organizations"]:
    if organization.get("root"):
        organization["root"] = sys.argv[2] + organization["root"]
        os.makedirs(organization["root"], exist_ok=True)
with open(sys.argv[3], "w", encoding="utf-8") as stream:
    yaml.safe_dump(config, stream, sort_keys=False)
print(config["lake_path"])
PY
)"
# The API in its container reads the file through a bind mount.
chmod 0644 "$HURON_DEV_CONFIG"
export HURON_LAKE_SOURCE="$lake" HURON_LAKE_PATH="$lake"
HURON_UID="$(id -u)" HURON_GID="$(id -g)" HURON_GROUP="$(id -gn)"
export HURON_UID HURON_GID HURON_GROUP

"${compose[@]}" up -d --build --wait api uploads uploads-proxy
api="http://127.0.0.1:8080"

export XDG_CONFIG_HOME="$work/config" XDG_STATE_HOME="$work/state"
huron() { uv run huron "$@"; }
huron config set api_url "$api"
# The lake path on this machine, which provision-orgs prepares.
huron config set mount_prefix "$lake"

# The development users' password grant and token exchange (scripts/dev-login.sh).
source "$root/scripts/dev-login.sh"
login_as() { dev_login "$1" password "$api"; }

login_as alice
# The declared organizations exist from the start, with their org admins; none can be created.
if huron create org astro; then
  echo "e2e: create org succeeded although the organizations are declared" >&2
  exit 1
fi
# lake-init prepared the lake before the API started, so provision-orgs has nothing to do.
huron adm verify-mounts
huron adm provision-orgs --dry-run
huron adm provision-orgs
test -f "$lake/.huron" && test -d "$lake/.tus-uploads"
test -f "$lake/helio/.huron" && test -d "$lake/helio/.huron-objects" && test -f "$lake/geo/.huron"
huron get orgs
login_as bob
huron create catalog heliophysics --org helio
huron adm grant catalog_admin helio-catalog-admins --catalog heliophysics
login_as carol
huron adm grant contributor helio-contributors --catalog heliophysics
huron adm grant reader helio-readers --catalog heliophysics
huron create namespace heliophysics.solar-wind --allow-collections
login_as dave
huron catalog heliophysics
printf '{"title": "Run 7", "description": "End-to-end check"}\n' > "$work/meta.json"
huron create collection solar-wind.run7 --metadata "$work/meta.json"
run7="$lake/helio/heliophysics/solar-wind/run7"
# A new file, then an overwrite, an empty file and a removal, each through the upload proxy.
echo alpha > "$work/a.txt"
echo beta > "$work/b.txt"
huron add "$work/a.txt" "$work/b.txt"
huron push -m "e2e: two new files"
test "$(cat "$run7/a.txt")" = alpha && test "$(cat "$run7/b.txt")" = beta
echo "alpha, second version" > "$work/a.txt"
: > "$work/empty.txt"
huron add "$work/a.txt" "$work/empty.txt"
huron rm b.txt
huron push -m "e2e: an overwrite, an empty file and a removal"
test "$(cat "$run7/a.txt")" = "alpha, second version"
test -f "$run7/empty.txt" && test ! -s "$run7/empty.txt" && test ! -e "$run7/b.txt"
login_as erin
huron get files solar-wind.run7
huron search -q run
huron adm check --catalog heliophysics || true
echo "e2e: ok"
