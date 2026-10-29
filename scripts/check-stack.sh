#!/usr/bin/env bash
# Probe the development stack started by `make up`: PostgreSQL and the Keycloak company realm.
set -euo pipefail

pg_url="${HURON_DATABASE_URL:-postgresql://huron:huron@127.0.0.1:5432/huron}"
realm="${HURON_COMPANY_ISSUER_LOCAL:-http://127.0.0.1:8081/realms/company}"

if command -v pg_isready >/dev/null 2>&1; then
  pg_isready -d "$pg_url" >/dev/null && echo "postgres: ok" || { echo "postgres: unreachable"; exit 1; }
else
  echo "postgres: pg_isready not installed, skipped"
fi

if curl -fsS "$realm/.well-known/openid-configuration" >/dev/null; then
  echo "keycloak: ok ($realm)"
else
  echo "keycloak: realm not reachable at $realm"
  exit 1
fi
