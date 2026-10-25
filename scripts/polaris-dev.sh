#!/usr/bin/env bash
# Run the checked-out Polaris server and Huron web against local development data.
set -euo pipefail
umask 077

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "${script_dir}/.." && pwd)"
state_dir="${repo_dir}/.local/polaris"
polaris_dir="${POLARIS_PROJECT:-${HOME}/repo/polaris}"
java_dir="${POLARIS_JAVA_HOME:-/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home}"
java_bin="${java_dir}/bin/java"
python_bin="${repo_dir}/.venv/bin/python"

if [[ ! -x "${python_bin}" ]]; then
  python_bin="$(command -v python3)"
fi

alive() {
  local pid
  local process_command
  [[ -f "$1" ]] || return 1
  read -r pid <"$1"
  [[ "${pid}" =~ ^[0-9]+$ ]] || return 1
  kill -0 "${pid}" 2>/dev/null || return 1
  process_command="$(ps -p "${pid}" -o command= 2>/dev/null)" || return 1
  [[ "${process_command}" == *"$2"* ]]
}

wait_url() {
  local url="$1"
  local label="$2"
  for _ in {1..120}; do
    if curl --silent --fail "${url}" >/dev/null; then
      return
    fi
    sleep 1
  done
  echo "${label} did not become ready. Inspect ${state_dir}/*.log." >&2
  return 1
}

package_polaris() {
  if [[ -f "${state_dir}/server/quarkus-run.jar" && -f "${state_dir}/admin/quarkus-run.jar" ]]; then
    return
  fi
  if [[ ! -x "${java_bin}" ]]; then
    echo "Set POLARIS_JAVA_HOME to a Java 21 installation." >&2
    exit 1
  fi
  if [[ ! -d "${polaris_dir}" ]]; then
    echo "Set POLARIS_PROJECT to your Polaris checkout." >&2
    exit 1
  fi
  if [[ ! -f "${polaris_dir}/runtime/server/build/quarkus-app/quarkus-run.jar" || ! -f "${polaris_dir}/runtime/admin/build/quarkus-app/quarkus-run.jar" ]]; then
    (cd "${polaris_dir}" && JAVA_HOME="${java_dir}" ./gradlew :polaris-server:assemble :polaris-admin:assemble -x test)
  fi
  # Keep the running application independent of subsequent Polaris builds.
  mkdir -p "${state_dir}/server" "${state_dir}/admin"
  cp -R "${polaris_dir}/runtime/server/build/quarkus-app/." "${state_dir}/server/"
  cp -R "${polaris_dir}/runtime/admin/build/quarkus-app/." "${state_dir}/admin/"
}

start() {
  for program in uv initdb pg_ctl pg_isready psql createdb curl node lsof; do
    command -v "${program}" >/dev/null || { echo "Missing required command: ${program}" >&2; exit 1; }
  done
  mkdir -p "${state_dir}"
  chmod 700 "${state_dir}"
  "${python_bin}" "${script_dir}/polaris_dev.py" configure "${state_dir}"
  package_polaris

  if [[ ! -x "${state_dir}/icechunk-venv/bin/python" ]]; then
    uv venv "${state_dir}/icechunk-venv" --python "${python_bin}"
  fi
  if ! "${state_dir}/icechunk-venv/bin/python" -c 'import icechunk, zarr, numpy' >/dev/null 2>&1; then
    uv pip install --python "${state_dir}/icechunk-venv/bin/python" icechunk==2.3.0 zarr==3.4.1 numpy==2.5.4
  fi

  mkdir -p "${state_dir}/socket"
  if [[ ! -f "${state_dir}/pgdata/PG_VERSION" ]]; then
    initdb -D "${state_dir}/pgdata" --username=polaris --pwfile="${state_dir}/db-password" --auth-local=trust --auth-host=scram-sha-256 >"${state_dir}/initdb.log"
  fi
  if ! pg_ctl -D "${state_dir}/pgdata" status >/dev/null 2>&1; then
    pg_ctl -D "${state_dir}/pgdata" -l "${state_dir}/postgres.log" -o "-h 127.0.0.1 -p 5439 -k ${state_dir}/socket" start
  fi
  if [[ "$(psql -h "${state_dir}/socket" -p 5439 -U polaris -d postgres -Atqc "SELECT 1 FROM pg_database WHERE datname = 'polaris'")" != 1 ]]; then
    createdb -h "${state_dir}/socket" -p 5439 -U polaris polaris
  fi
  psql -h "${state_dir}/socket" -p 5439 -U polaris -d polaris -qc 'CREATE SCHEMA IF NOT EXISTS polaris_schema'

  if ! alive "${state_dir}/polaris.pid" "${state_dir}/server/quarkus-run.jar"; then
    if lsof -iTCP:8181 -iTCP:8182 -sTCP:LISTEN -t >/dev/null 2>&1; then
      echo 'Polaris ports 8181/8182 are already in use by another process.' >&2
      return 1
    fi
    "${java_bin}" -Dquarkus.config.locations="${state_dir}/application.properties" -jar "${state_dir}/admin/quarkus-run.jar" bootstrap --credentials-file "${state_dir}/root-credentials.json" >"${state_dir}/bootstrap.log" 2>&1
    "${python_bin}" "${script_dir}/polaris_dev.py" launch "${state_dir}" polaris "${java_bin}" -Dquarkus.config.locations="${state_dir}/application.properties" -jar "${state_dir}/server/quarkus-run.jar"
  fi
  wait_url http://127.0.0.1:8182/q/health/ready Polaris

  if ! alive "${state_dir}/web.pid" "${repo_dir}/web/node_modules/vite/bin/vite.js"; then
    if lsof -iTCP:5173 -sTCP:LISTEN -t >/dev/null 2>&1; then
      echo 'Huron port 5173 is already in use by another process.' >&2
      return 1
    fi
    "${python_bin}" "${script_dir}/polaris_dev.py" launch "${state_dir}" web "$(command -v node)" "${repo_dir}/web/node_modules/vite/bin/vite.js" --host 127.0.0.1 --port 5173 --strictPort
  fi
  wait_url http://127.0.0.1:5173/login Huron
  status
}

status() {
  if alive "${state_dir}/polaris.pid" "${state_dir}/server/quarkus-run.jar"; then echo 'Polaris: http://127.0.0.1:8181'; else echo 'Polaris: stopped'; fi
  if alive "${state_dir}/web.pid" "${repo_dir}/web/node_modules/vite/bin/vite.js"; then echo 'Huron: http://127.0.0.1:5173/login'; else echo 'Huron: stopped'; fi
  if [[ -d "${state_dir}/pgdata" ]] && pg_ctl -D "${state_dir}/pgdata" status >/dev/null 2>&1; then echo 'PostgreSQL: 127.0.0.1:5439'; else echo 'PostgreSQL: stopped'; fi
  echo "Private Polaris bootstrap credentials: ${state_dir}/credentials.json"
  echo "Huron administrator password: ${repo_dir}/.local/huron/initial-admin.json"
  echo "Science import receipts: ${state_dir}/nasa-samples.json and mission-samples.json"
  echo "Topic demo passwords: ${repo_dir}/.local/huron/topic-demo-accounts.json"
  echo "Persistent Zarr repositories: ${state_dir}/nasa-storage"
  echo 'Science catalogs: geoscience; heliophysics; international_space_station'
  echo 'Run samples to download and initialize the real mission datasets.'
  echo 'FILE storage has no vended cloud credentials; filesystem access follows local OS permissions.'
}

stop() {
  for name in web polaris; do
    local expected_command="${state_dir}/server/quarkus-run.jar"
    if [[ "${name}" == web ]]; then expected_command="${repo_dir}/web/node_modules/vite/bin/vite.js"; fi
    if alive "${state_dir}/${name}.pid" "${expected_command}"; then
      kill "$(cat "${state_dir}/${name}.pid")"
      rm "${state_dir}/${name}.pid"
    fi
  done
  if [[ -d "${state_dir}/pgdata" ]] && pg_ctl -D "${state_dir}/pgdata" status >/dev/null 2>&1; then
    pg_ctl -D "${state_dir}/pgdata" stop -m fast
  fi
  echo 'Local services stopped. Development data is preserved.'
}

refresh() {
  stop
  (cd "${polaris_dir}" && JAVA_HOME="${java_dir}" ./gradlew :polaris-server:assemble :polaris-admin:assemble -x test)
  # These directories contain copied runtime packages; scientific data and PostgreSQL are separate.
  rm -rf "${state_dir}/server" "${state_dir}/admin"
  start
}

case "${1:-start}" in
  start) start ;;
  status) status ;;
  stop) stop ;;
  refresh) refresh ;;
  samples)
    "${state_dir}/icechunk-venv/bin/python" "${script_dir}/import_nasa_samples.py"
    "${state_dir}/icechunk-venv/bin/python" "${script_dir}/import_mission_samples.py"
    ;;
  *) echo "Usage: $0 [start|status|stop|refresh|samples]" >&2; exit 2 ;;
esac
