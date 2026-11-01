#!/usr/bin/env bash
# Manual pre-release check against the Docker stack (docker-compose.app.yml; Docker required).
#
# Starts the stack's backend (PostgreSQL, the migrations, Keycloak, the group directory and the
# API) as its own compose project with an empty database, logs in as the development users
# through the Keycloak realm's password grant (enabled on the development realm only), walks the
# user guide against a temporary directory standing in for the shares, and removes the project
# with its volume and its API image. The web and the demo seed do not start. It needs the ports of
# `make app` and `make up`, so stop those first.
#
# The API runs in managed mode with a configuration of its own in place of huron.dev.yaml: the
# organizations of huron.dev.yaml (helio, geo and noaa) with their organization-wide role groups
# unchanged and their roots under the temporary directory (<tmp>/data1/huron) instead of /data1.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
engine=docker
compose=(docker compose)
command -v docker >/dev/null 2>&1 || { engine=podman; compose=(podman-compose); }
compose+=(-f docker-compose.app.yml -p huron-e2e)
# An API image of its own: huron-app-api:dev of `make app` keeps its tag and its image.
export HURON_API_IMAGE=huron-e2e-api:dev

for port in 3000 5432 8080 8081 8082; do
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
# huron.dev.yaml with each root moved under the temporary directory: the same settings,
# organizations and `groups`, so this check follows any edit of that file. The roots are created here, before
# provisioning: provision-orgs creates <root>/<org>, never a root.
uv run python - huron.dev.yaml "$work" > "$HURON_DEV_CONFIG" <<'PY'
import os
import sys

import yaml

with open(sys.argv[1], encoding="utf-8") as stream:
    config = yaml.safe_load(stream)
for organization in config["organizations"]:
    if organization.get("root"):
        organization["root"] = sys.argv[2] + organization["root"]
        os.makedirs(organization["root"], exist_ok=True)
yaml.safe_dump(config, sys.stdout, sort_keys=False)
PY
# The API in its container runs as another user and reads the file through a bind mount.
chmod 0644 "$HURON_DEV_CONFIG"

"${compose[@]}" up -d --build --wait api
api="http://127.0.0.1:8080"

# The mount prefix is only for organizations without a root; there is none here, so it stays
# unmarked: every disk operation below must go through the organization roots.
share="$work/share"
mkdir -p "$share"

export XDG_CONFIG_HOME="$work/config" XDG_STATE_HOME="$work/state"
huron() { uv run huron "$@"; }
huron config set api_url "$api"
huron config set mount_prefix "$share"
huron config set acl_backend none

# The development users' password grant and token exchange (scripts/dev-login.sh).
source "$root/scripts/dev-login.sh"
login_as() { dev_login "$1" password "$api"; }

login_as alice
# The declared organizations exist from the start, with their org admins; none can be created.
if huron create org astro; then
  echo "e2e: create org succeeded although the organizations are declared" >&2
  exit 1
fi
huron adm verify-mounts && { echo "e2e: verify-mounts passed before provisioning" >&2; exit 1; }
huron adm provision-orgs --dry-run
huron adm provision-orgs
huron adm provision-orgs # again: nothing to do
huron adm verify-mounts
test -f "$work/data1/huron/helio/.huron" && test -f "$work/data1/huron/geo/.huron"
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
echo alpha > "$work/a.txt"
huron add "$work/a.txt"
huron push -m "e2e"
# The collection lives below helio's root, not below the mount prefix.
test -f "$work/data1/huron/helio/heliophysics/solar-wind/run7/a.txt"
test -z "$(ls -A "$share")"
login_as erin
huron get files solar-wind.run7
huron search -q run
huron adm check --catalog heliophysics || true
echo "e2e: ok"
