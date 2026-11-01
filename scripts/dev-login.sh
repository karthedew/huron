#!/usr/bin/env bash
# Sign the CLI in to the development stack without a browser: the Keycloak password grant of the
# development realm (enabled there only), then POST /api/v1/auth/exchange, whose Huron token is
# written to $XDG_STATE_HOME/huron/tokens.json as `huron login` would.
#
#   source scripts/dev-login.sh; dev_login USER PASSWORD [API_URL]
#   scripts/dev-login.sh USER PASSWORD [API_URL]
#
# XDG_STATE_HOME must be set: the callers (scripts/e2e.sh, scripts/demo-noaa.sh) give the CLI a
# state directory of their own, so this never overwrites your own CLI's tokens by falling back to
# ~/.local/state. API_URL defaults to http://127.0.0.1:8080 and the realm to
# HURON_DEV_ISSUER (http://127.0.0.1:8081/realms/company).

# dev_login USER PASSWORD [API_URL]
dev_login() {
  local user="$1" password="$2" api="${3:-http://127.0.0.1:8080}"
  local issuer="${HURON_DEV_ISSUER:-http://127.0.0.1:8081/realms/company}"
  local token
  if [[ -z "${XDG_STATE_HOME:-}" ]]; then
    echo "dev_login: set XDG_STATE_HOME to the CLI state directory to write" >&2
    return 2
  fi
  token="$(curl -fsS -d grant_type=password -d client_id=huron-cli -d scope=openid \
    -d username="$user" -d password="$password" \
    "$issuer/protocol/openid-connect/token" \
    | python3 -I -c 'import json,sys; print(json.load(sys.stdin)["id_token"])')" || {
    echo "dev_login: the password grant for $user failed at $issuer" >&2
    return 1
  }
  curl -fsS -H 'Content-Type: application/json' -d "{\"company_token\": \"$token\"}" \
    "$api/api/v1/auth/exchange" | python3 -I -c '
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

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  set -euo pipefail
  if [[ $# -lt 2 || $# -gt 3 ]]; then
    echo "usage: $0 USER PASSWORD [API_URL]   (with XDG_STATE_HOME set)" >&2
    exit 2
  fi
  dev_login "$@"
fi
