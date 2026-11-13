#!/usr/bin/env bash
# The local cluster: the kustomize overlay deploy/local on the kind cluster huron-local of the
# development machine. The Makefile targets call this script.
#
#   scripts/k8s-local.sh cluster      make k8s-local-cluster: make the kind cluster huron-local
#                                     from deploy/local/kind.yaml.template, then install
#                                     ingress-nginx
#   scripts/k8s-local.sh kind-config  print the kind configuration of the cluster
#   scripts/k8s-local.sh settings     print the settings of the script and the names of the
#                                     objects that it makes, one `name=value` line each
#   scripts/k8s-local.sh up           make k8s-local: build the API image, import the images into
#                                     the node, apply the overlay and wait for the Jobs and the
#                                     rollouts
#   scripts/k8s-local.sh smoke        make k8s-local-smoke: log in on the host, push files through
#                                     the Ingress and check the lake from the host
#   scripts/k8s-local.sh down         make k8s-local-down: delete the namespace huron and the
#                                     PersistentVolume huron-local-lake
#
# Variables:
#   K8S_LOCAL_KUBECONFIG  the kubeconfig file of the cluster (default
#                         $HOME/.kube/huron-local.config). The script gives it to each kubectl
#                         and kind command, so it never reads or changes your default kubeconfig.
#   K8S_LOCAL_CONTEXT     the kubectl context of the cluster (default kind-huron-local). The
#                         script refuses to start when the current context of
#                         K8S_LOCAL_KUBECONFIG is another one.
#   K8S_LOCAL_LAKE        the host directory of the lake (default
#                         $HOME/.local/share/huron-k8s-local/lake)
#   K8S_LOCAL_PURGE=1     `down` also deletes the content of K8S_LOCAL_LAKE, the API image
#                         huron:local and the images that `up` imported into the node. Only the
#                         value 1 purges: another value, or none, keeps them. A purge
#                         refuses a lake that is your home directory or a directory above it,
#                         such as /, and it refuses a user other than the service user.
#
# The cluster must have one node, and that node must show K8S_LOCAL_LAKE at /huron-lake. ingress-
# nginx of the cluster takes https on 127.0.0.1:18444 of the host. A kind node gets its mounts and
# its ports only when the cluster is made: `cluster` makes it so.
#
# The pods run as the service user of deploy/local (UID 1000, GID 1000), so run the script as the
# host user with that UID and GID: the lake files then belong to you, and the CLI on the host
# reads them all. `up` and `smoke` use the images of the local cache and pull no image. `cluster`
# pulls the node image of kind and the images of ingress-nginx when they are not in the cache.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

kubeconfig="${K8S_LOCAL_KUBECONFIG:-$HOME/.kube/huron-local.config}"
context="${K8S_LOCAL_CONTEXT:-kind-huron-local}"
lake="${K8S_LOCAL_LAKE:-$HOME/.local/share/huron-k8s-local/lake}"
node_lake=/huron-lake
namespace=huron
volume=huron-local-lake
api_url=https://localhost:18444
tls="$root/.k8s-local"
tls_secret=huron-local-tls
realm_configmap=huron-keycloak-realm
realm_file=company-realm.json
groups_configmap=huron-dev-groups
groups_file=dev-groups.yaml
# The first apply of `up`: each object but the API pod and the upload pod.
before_pods='app.kubernetes.io/component notin (api,uploads)'
images=(huron:local tusproject/tusd:v2.10.1 nginx:1.31.8 postgres:16 quay.io/keycloak/keycloak:26.0)
# The manifest of ingress-nginx for kind, at the version that the cluster runs.
ingress_nginx=https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.15.1/deploy/static/provider/kind/deploy.yaml

say() { echo "k8s-local: $*"; }
fail() {
  echo "k8s-local: $*" >&2
  exit 1
}
k() { kubectl --kubeconfig "$kubeconfig" --context "$context" "$@"; }

preflight() {
  command -v kubectl >/dev/null 2>&1 || fail "kubectl is not installed"
  command -v docker >/dev/null 2>&1 || fail "docker is not installed"
  [[ -f "$kubeconfig" ]] || fail "the kubeconfig $kubeconfig does not exist. Set K8S_LOCAL_KUBECONFIG"
  local current
  current="$(kubectl --kubeconfig "$kubeconfig" config current-context 2>/dev/null || true)"
  [[ "$current" == "$context" ]] ||
    fail "the current context of $kubeconfig is '$current', not '$context'. Set K8S_LOCAL_KUBECONFIG to the kubeconfig of the local cluster, or K8S_LOCAL_CONTEXT to its context"
  local nodes
  nodes="$(k get nodes -o jsonpath='{.items[*].metadata.name}')"
  [[ -n "$nodes" && "$nodes" != *" "* ]] || fail "the cluster must have one node, not '$nodes'"
  node="$nodes"
  docker inspect --type container "$node" >/dev/null 2>&1 ||
    fail "the node $node is not a container of this Docker engine"
  # Only the cluster of the local overlay binds the lake directory at /huron-lake. This check
  # reads the configuration of the node container, so it holds also when the directory is gone.
  docker inspect --format '{{range .Mounts}}{{.Source}}={{.Destination}}{{"\n"}}{{end}}' "$node" |
    grep -Fqx -- "$lake=$node_lake" ||
    fail "the node $node does not bind $lake at $node_lake, so it is not the local cluster. Set K8S_LOCAL_KUBECONFIG and K8S_LOCAL_LAKE"
}

# A lake path that kind can take and that a purge can empty: absolute, with no line break or
# carriage return, which YAML folds, and not your home directory or a directory above it.
check_lake_path() {
  [[ "$lake" == /* ]] || fail "K8S_LOCAL_LAKE must be an absolute path, not '$lake'"
  [[ "$lake" != *[$'\n\r']* ]] || fail "K8S_LOCAL_LAKE must not hold a line break or a carriage return"
  # On resolved paths, so that /., .. and a symbolic link count as the directory that they name.
  local real home
  real="$(realpath -m -- "$lake")"
  home="$(realpath -m -- "$HOME")"
  [[ "$home/" != "${real%/}/"* ]] ||
    fail "K8S_LOCAL_LAKE must not be your home directory or a directory above it, such as /, because a purge empties the lake directory"
}

# The UID and the GID of the pods of deploy/local.
service_uid() { sed -n 's/^service_uid: *//p' deploy/local/huron.yaml; }
service_gid() { sed -n 's/^ *runAsGroup: *//p' deploy/local/api-patch.yaml; }

# The pods run as the service user of deploy/local, which must be the host user.
check_user() {
  local uid gid
  uid="$(service_uid)"
  gid="$(service_gid)"
  [[ "$(id -u):$(id -g)" == "$uid:$gid" ]] ||
    fail "the pods run as $uid:$gid. Run this script as the host user with that UID and GID"
}

# The node shows the host directory of the lake at /huron-lake now: the same device, inode and
# modification time on both sides. A directory that was removed and made again fails here.
check_lake() {
  [[ -d "$lake" ]] ||
    fail "the lake directory $lake does not exist. Delete the cluster (kind delete cluster --name huron-local --kubeconfig $kubeconfig) and make it again with make k8s-local-cluster"
  local here there
  here="$(stat -c '%d %i %Y' "$lake")"
  there="$(docker exec "$node" stat -c '%d %i %Y' "$node_lake" 2>/dev/null || true)"
  [[ "$here" == "$there" ]] ||
    fail "the node $node does not show $lake at $node_lake. Delete the cluster (kind delete cluster --name huron-local --kubeconfig $kubeconfig) and make it again with make k8s-local-cluster"
}

# A local certificate authority and a certificate for localhost and 127.0.0.1, for both
# Ingresses. The files stay in .k8s-local/, which git ignores.
make_certificate() {
  [[ -f "$tls/ca.crt" && -f "$tls/tls.crt" && -f "$tls/tls.key" ]] && return 0
  mkdir -p "$tls"
  openssl req -x509 -newkey rsa:2048 -nodes -days 825 -subj "/CN=huron k8s-local CA" \
    -keyout "$tls/ca.key" -out "$tls/ca.crt" 2>/dev/null
  openssl req -newkey rsa:2048 -nodes -subj "/CN=localhost" \
    -keyout "$tls/tls.key" -out "$tls/tls.csr" 2>/dev/null
  printf 'subjectAltName=DNS:localhost,IP:127.0.0.1\n' >"$tls/san.ext"
  openssl x509 -req -in "$tls/tls.csr" -CA "$tls/ca.crt" -CAkey "$tls/ca.key" \
    -CAcreateserial -days 825 -extfile "$tls/san.ext" -out "$tls/tls.crt" 2>/dev/null
}

# Apply a ConfigMap or a Secret that kubectl makes from files, so a second run changes it.
apply_made() {
  k -n "$namespace" create "$@" --dry-run=client -o yaml | k apply -f -
}

# The kind configuration: deploy/local/kind.yaml.template with the lake directory in the line
# `hostPath: @K8S_LOCAL_LAKE@`, as a quoted YAML string. kind needs an absolute path.
kind_config() {
  check_lake_path
  local quoted="'" rest="$lake" line
  # A single-quoted YAML string writes each ' as ''. No pattern replacement touches the path.
  while [[ "$rest" == *"'"* ]]; do
    quoted+="${rest%%"'"*}''"
    rest="${rest#*"'"}"
  done
  quoted+="$rest'"
  while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ "$line" == *"hostPath: @K8S_LOCAL_LAKE@" ]]; then
      printf '%s%s\n' "${line%@K8S_LOCAL_LAKE@}" "$quoted"
    else
      printf '%s\n' "$line"
    fi
  done <deploy/local/kind.yaml.template
}

settings() {
  printf '%s=%s\n' kubeconfig "$kubeconfig" context "$context" lake "$lake" \
    node_lake "$node_lake" namespace "$namespace" volume "$volume" api_url "$api_url" \
    tls_secret "$tls_secret" realm_configmap "$realm_configmap" realm_file "$realm_file" \
    groups_configmap "$groups_configmap" groups_file "$groups_file" images "${images[*]}" \
    before_pods "$before_pods" service_uid "$(service_uid)" service_gid "$(service_gid)"
}

cluster() {
  check_lake_path
  command -v kind >/dev/null 2>&1 || fail "kind is not installed"
  command -v kubectl >/dev/null 2>&1 || fail "kubectl is not installed"
  if kind get clusters 2>/dev/null | grep -qx huron-local; then
    fail "the kind cluster huron-local exists. Use it, or delete it with: kind delete cluster --name huron-local --kubeconfig $kubeconfig"
  fi
  mkdir -p "$tls"
  kind_config >"$tls/kind.yaml"
  mkdir -p "$lake"
  kind create cluster --config "$tls/kind.yaml" --kubeconfig "$kubeconfig"
  k apply -f "$ingress_nginx"
  k -n ingress-nginx rollout status deployment/ingress-nginx-controller --timeout=5m
  say "cluster huron-local: context $context in $kubeconfig, https on 127.0.0.1:18444"
}

up() {
  preflight
  check_user
  check_lake
  make_certificate
  say "build the API image huron:local"
  docker build --pull=false -t huron:local -f Containerfile "$root"
  say "import ${images[*]} into the node $node"
  docker save "${images[@]}" | docker exec -i "$node" ctr -n k8s.io images import -
  k apply -f deploy/local/namespace.yaml
  apply_made secret tls "$tls_secret" --cert "$tls/tls.crt" --key "$tls/tls.key"
  apply_made configmap "$realm_configmap" \
    --from-file="$realm_file=scripts/keycloak/company-realm.json"
  apply_made configmap "$groups_configmap" --from-file="$groups_file=scripts/dev-groups.yaml"
  local again=""
  k -n "$namespace" get deployment huron >/dev/null 2>&1 && again=1
  # A Job does not run again when it is applied again, so the migration and the lake
  # preparation of an earlier run go first.
  k -n "$namespace" delete job huron-migrate huron-lake-init --ignore-not-found
  # First everything but the API pod and the upload pod, then wait for the Jobs: the API needs
  # the migrated database and the prepared lake, and the upload pod needs .tus-uploads.
  k apply -k deploy/local -l "$before_pods"
  say "wait for the migration and the lake preparation"
  k -n "$namespace" wait --for=condition=complete --timeout=10m job/huron-migrate job/huron-lake-init
  k apply -k deploy/local
  # On a deploy again the pod template of the API does not change when only the image huron:local
  # changed, so the API pod starts again to run the image that this run imported.
  if [[ -n "$again" ]]; then
    k -n "$namespace" rollout restart deployment/huron
  fi
  for workload in statefulset/huron-postgres deployment/huron deployment/huron-uploads; do
    k -n "$namespace" rollout status "$workload" --timeout=10m
  done
  say "API $api_url, uploads $api_url/files/, lake $lake"
}

smoke() {
  preflight
  check_user
  if (exec 3<>/dev/tcp/127.0.0.1/8081) 2>/dev/null; then
    fail "127.0.0.1:8081 is in use. Stop make app (make app-down) or make up (make down)"
  fi
  [[ -f "$lake/.huron" ]] || fail "$lake has no marker. Run make k8s-local first"
  [[ -f "$tls/ca.crt" ]] || fail "$tls/ca.crt does not exist. Run make k8s-local first"
  # httpx reads SSL_CERT_FILE and curl reads CURL_CA_BUNDLE.
  export SSL_CERT_FILE="$tls/ca.crt" CURL_CA_BUNDLE="$tls/ca.crt"
  # The CLI reads HURON_* variables as its own settings.
  unset HURON_ISSUER HURON_API_URL HURON_CLIENT_ID HURON_MOUNT_PREFIX

  work="$(mktemp -d)"
  forward=""
  trap 'if [[ -n "$forward" ]]; then kill "$forward" 2>/dev/null || true; fi; rm -rf "$work"' EXIT
  # Keycloak runs in the API pod. The host reaches it at the issuer URL of the realm.
  # kubectl itself runs in the background, not a function, so that $! is its process ID and
  # the trap stops it.
  kubectl --kubeconfig "$kubeconfig" --context "$context" -n "$namespace" \
    port-forward deployment/huron 8081:8081 >"$work/port-forward.log" 2>&1 &
  forward=$!
  local tries=0
  until curl -fs -o /dev/null http://127.0.0.1:8081/realms/company; do
    tries=$((tries + 1))
    [[ $tries -lt 60 ]] || fail "Keycloak does not answer on 127.0.0.1:8081: $(cat "$work/port-forward.log")"
    sleep 1
  done

  # The CLI keeps its configuration and its token in the temporary directory, on the host only.
  export XDG_CONFIG_HOME="$work/config" XDG_STATE_HOME="$work/state"
  huron() { uv run huron "$@"; }
  huron config set api_url "$api_url"
  huron config set mount_prefix "$lake"
  # shellcheck source=scripts/dev-login.sh
  source "$root/scripts/dev-login.sh"
  dev_login alice password "$api_url"

  huron adm verify-mounts
  huron create catalog smoke --org helio
  huron create namespace smoke.checks --allow-collections
  huron catalog smoke
  printf '{"title": "Smoke", "description": "The check of the local cluster"}\n' >"$work/meta.json"
  huron create collection checks.run --metadata "$work/meta.json"
  local files="$lake/helio/smoke/checks/run"
  # A new file, then an overwrite and an empty file, each through the Ingress, the upload proxy
  # and tusd.
  echo alpha >"$work/a.txt"
  huron add "$work/a.txt"
  huron push -m "smoke: a new file"
  [[ "$(cat "$files/a.txt")" == alpha ]] || fail "the host does not read the new file at $files/a.txt"
  echo "alpha, second version" >"$work/a.txt"
  : >"$work/empty.txt"
  huron add "$work/a.txt" "$work/empty.txt"
  huron push -m "smoke: an overwrite and an empty file"
  [[ "$(cat "$files/a.txt")" == "alpha, second version" ]] ||
    fail "the host does not read the new version of $files/a.txt"
  [[ -f "$files/empty.txt" && ! -s "$files/empty.txt" ]] ||
    fail "the host does not read the empty file at $files/empty.txt"
  # The check reads the lake through the host directory, with the token of the host. Its exit
  # code is 1 when it reports a finding.
  huron adm check --hash || fail "huron adm check --hash reported findings"
  huron delete collection checks.run --yes
  huron delete namespace smoke.checks
  huron delete catalog smoke
  say "smoke: ok"
}

down() {
  # preflight refuses a cluster whose node does not bind the lake directory, before any delete.
  preflight
  # Only the value 1 purges. The checks and the delete below read this one decision.
  local purge=no
  if [[ "${K8S_LOCAL_PURGE:-}" == 1 ]]; then purge=yes; fi
  if [[ "$purge" == yes ]]; then
    # Only the directory that the node shows at /huron-lake now, as the service user.
    check_lake_path
    check_user
    check_lake
  fi
  k delete namespace "$namespace" --ignore-not-found --wait
  k delete persistentvolume "$volume" --ignore-not-found
  if [[ "$purge" == yes ]]; then
    say "delete the content of $lake, huron:local and the imported images"
    find "$lake" -mindepth 1 -delete
    docker image rm huron:local >/dev/null 2>&1 || true
    local image
    for image in "${images[@]}"; do
      docker exec "$node" crictl rmi "$image" >/dev/null 2>&1 || true
    done
  else
    say "the lake $lake stays. K8S_LOCAL_PURGE=1 deletes its content"
  fi
}

case "${1:-}" in
  cluster) cluster ;;
  kind-config) kind_config ;;
  settings) settings ;;
  up) up ;;
  smoke) smoke ;;
  down) down ;;
  *)
    echo "usage: $0 cluster|kind-config|settings|up|smoke|down" >&2
    exit 2
    ;;
esac
