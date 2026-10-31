#!/usr/bin/env bash
# Manual pre-release check against the Docker stack (docker-compose.app.yml; Docker required).
#
# Starts the stack's backend (PostgreSQL, the migrations, Keycloak, the group directory and the
# API) as its own compose project with an empty database, logs in as the development users
# through the Keycloak realm's password grant (enabled on the development realm only), walks the
# user guide against a temporary directory standing in for the share, and removes the project
# with its volume and its API image. The web and the demo seed do not start. It needs the ports of
# `make app` and `make up`, so stop those first.
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

"${compose[@]}" up -d --build --wait api
api="http://127.0.0.1:8080"
instance="$(curl -fsS "$api/healthz" | python3 -c 'import json,sys; print(json.load(sys.stdin)["instance_id"])')"

share="$work/share"
mkdir -p "$share"
scripts/init-root.sh "$share" "$(id -gn)" "$api" "$instance"

export XDG_CONFIG_HOME="$work/config" XDG_STATE_HOME="$work/state"
huron() { uv run huron "$@"; }
huron config set api_url "$api"
huron config set mount_prefix "$share"
huron config set acl_backend none

login_as() {
  local token
  token="$(curl -fsS -d grant_type=password -d client_id=huron-cli -d scope=openid \
    -d username="$1" -d password=password \
    http://127.0.0.1:8081/realms/company/protocol/openid-connect/token \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["id_token"])')"
  curl -fsS -H 'Content-Type: application/json' -d "{\"company_token\": \"$token\"}" \
    "$api/api/v1/auth/exchange" | python3 -c '
import json, os, sys, datetime
answer = json.load(sys.stdin)
path = os.path.join(os.environ["XDG_STATE_HOME"], "huron", "tokens.json")
os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
expires = datetime.datetime.fromisoformat(answer["expires_at"]).timestamp()
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as handle:
    json.dump({"huron_token": answer["huron_token"], "expires_at": expires,
               "subject": answer["subject"], "refresh_token": None}, handle)
'
}

login_as alice
huron platform verify-root
huron org create helio
huron org grant helio helio-org-admins
login_as bob
huron catalog create helio heliophysics
huron catalog grant heliophysics catalog_admin helio-catalog-admins
login_as carol
huron catalog grant heliophysics contributor helio-contributors
huron catalog grant heliophysics reader helio-readers
huron namespace create heliophysics.solar-wind --allow-collections
login_as dave
huron catalog use heliophysics
printf '{"title": "Run 7", "description": "End-to-end check"}\n' > "$work/meta.json"
huron collection create solar-wind.run7 --metadata "$work/meta.json"
echo alpha > "$work/a.txt"
huron add "$work/a.txt"
huron push -m "e2e"
login_as erin
huron files solar-wind.run7
huron search -q run
huron check --catalog heliophysics || true
echo "e2e: ok"
