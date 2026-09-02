#!/usr/bin/env bash
# Probe the local stack from the host and fail when a service is not actually
# usable, printing one line per check.
#
# `make up` runs this after `compose up --wait` because the wait alone is not
# trustworthy: docker compose fails when a container exits before its
# healthcheck passes, but podman-compose does not. Podman's remote API (the
# path `podman machine` on macOS always takes) answers "0" for a container
# that stopped before becoming healthy, so podman-compose prints a bare "0"
# in its --wait output and exits successfully - which is exactly what a failed
# Keycloak realm import looks like.
#
# Usage: scripts/check-stack.sh [postgres|minio|keycloak|hosts|api ...]
#        With no arguments: postgres minio keycloak hosts (what `make up` starts).
#        Tunables: HURON_CHECK_TIMEOUT (seconds per probe, default 30).
set -u

POSTGRES_PORT=5433
MINIO_URL=http://localhost:9000
KEYCLOAK_URL=http://localhost:8081
API_URL=http://localhost:8080
# The one issuer string every consumer of the realm must see; see
# docker-compose.yml (KC_HOSTNAME) and docs/getting-started/local-development.md.
ISSUER=http://keycloak:8081/realms/huron
TIMEOUT="${HURON_CHECK_TIMEOUT:-30}"

failed=0
ok()   { printf '[OK  ] %s\n' "$*"; }
bad()  { printf '[FAIL] %s\n' "$*"; failed=1; }
hint() { printf '       %s\n' "$*"; }

# retry <command...>: succeed as soon as the command does, within $TIMEOUT.
retry() {
  local deadline=$(( $(date +%s) + TIMEOUT ))
  until "$@" >/dev/null 2>&1; do
    [ "$(date +%s)" -ge "$deadline" ] && return 1
    sleep 2
  done
}

# A PostgreSQL SSLRequest (length 8, code 80877103): a live server answers
# with a single byte, 'S' or 'N'. An open port alone would also be true of a
# container that is still initializing.
postgres_answers() {
  bash -c "exec 3<>/dev/tcp/127.0.0.1/$POSTGRES_PORT \
    && printf '\\000\\000\\000\\010\\004\\322\\026\\057' >&3 \
    && IFS= read -r -n1 byte <&3 && [ \"\$byte\" = S -o \"\$byte\" = N ]"
}

check_postgres() {
  if retry postgres_answers; then
    ok "postgres   answers on :$POSTGRES_PORT"
  else
    bad "postgres   nothing answers on :$POSTGRES_PORT within ${TIMEOUT}s"
    hint "make logs SERVICE=postgres"
  fi
}

check_minio() {
  if retry curl -fsS --max-time 3 "$MINIO_URL/minio/health/live"; then
    ok "minio      live at $MINIO_URL"
  else
    bad "minio      $MINIO_URL/minio/health/live not answering within ${TIMEOUT}s"
    hint "make logs SERVICE=minio"
  fi
}

check_keycloak() {
  local discovery="$KEYCLOAK_URL/realms/huron/.well-known/openid-configuration"
  if ! retry curl -fsS --max-time 3 "$KEYCLOAK_URL/realms/master"; then
    bad "keycloak   $KEYCLOAK_URL not answering within ${TIMEOUT}s"
    hint "The container has probably exited: make logs SERVICE=keycloak"
    hint "(podman-compose --wait prints a bare 0 for a container that died before its healthcheck)"
    return
  fi
  local doc
  if ! doc="$(curl -fsS --max-time 3 "$discovery" 2>/dev/null)"; then
    bad "keycloak   realm 'huron' is missing - the import of scripts/keycloak/huron-realm.json failed"
    hint "make logs SERVICE=keycloak, fix the realm file, then make keycloak-reset"
    return
  fi
  case "$doc" in
    *"\"issuer\":\"$ISSUER\""*) ok "keycloak   realm 'huron' imported; issuer is $ISSUER" ;;
    *) bad "keycloak   realm 'huron' answers but its issuer is not $ISSUER (KC_HOSTNAME changed?)" ;;
  esac
}

check_hosts() {
  # Discovery hands every client keycloak:8081 URLs, so the host itself must
  # resolve "keycloak" - for the browser and for `make api` alike.
  if curl -fsS --max-time 3 "http://keycloak:8081/realms/huron" >/dev/null 2>&1; then
    ok "hosts      'keycloak' resolves on this host"
  elif grep -Eq '^[[:space:]]*127\.0\.0\.1[[:space:]]+keycloak([[:space:]]|$)' /etc/hosts; then
    bad "hosts      /etc/hosts maps keycloak but http://keycloak:8081 is not reachable"
  else
    bad "hosts      'keycloak' does not resolve on this host - run: make hosts"
    hint "Without it the browser is redirected to keycloak:8081 at login and cannot get there."
  fi
}

check_api() {
  if retry curl -fsS --max-time 3 "$API_URL/healthz"; then
    ok "api        live at $API_URL"
  else
    bad "api        $API_URL/healthz not answering within ${TIMEOUT}s"
    hint "make logs SERVICE=api"
    return
  fi
  if curl -fsS --max-time 5 "$API_URL/readyz" >/dev/null 2>&1; then
    ok "api        ready (database and raw store reachable)"
  else
    bad "api        $API_URL/readyz reports a dependency unavailable"
    hint "curl -s $API_URL/readyz"
  fi
}

targets=("$@")
[ ${#targets[@]} -eq 0 ] && targets=(postgres minio keycloak hosts)
for target in "${targets[@]}"; do
  case "$target" in
    postgres) check_postgres ;;
    minio)    check_minio ;;
    keycloak) check_keycloak ;;
    hosts)    check_hosts ;;
    api)      check_api ;;
    *) echo "unknown target: $target (postgres|minio|keycloak|hosts|api)" >&2; exit 2 ;;
  esac
done

if [ "$failed" -ne 0 ]; then
  echo "Stack check FAILED - see the [FAIL] lines above."
  exit 1
fi
echo "Stack check passed."
