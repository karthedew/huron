#!/usr/bin/env bash
# Prepare the Huron share root once. Run as a user that owns the prefix, or as root.
#
#   scripts/init-root.sh <prefix> <platform-admin-group> <api-url> <instance-id>
#
# Sets the group and mode 2771 (others may only traverse), gives the platform admin group rwx
# through an access and an inherited default ACL, and writes the .huron marker the CLI checks.
set -euo pipefail

if [[ $# -ne 4 ]]; then
  echo "usage: $0 <prefix> <platform-admin-group> <api-url> <instance-id>" >&2
  exit 2
fi
prefix="$1" group="$2" api_url="$3" instance_id="$4"

if [[ ! -d "$prefix" ]]; then
  echo "error: $prefix is not a directory" >&2
  exit 1
fi

if getent group "$group" >/dev/null 2>&1; then
  chgrp "$group" "$prefix"
  echo "group of $prefix: $group"
else
  echo "warning: group $group is unknown on this machine; group left unchanged" >&2
fi

chmod 2771 "$prefix"
echo "mode of $prefix: 2771"

if command -v setfacl >/dev/null 2>&1 && getent group "$group" >/dev/null 2>&1; then
  setfacl -m "g:${group}:rwx" -d -m "g:${group}:rwx" "$prefix"
  echo "ACL of $prefix: g:${group}:rwx (access and default)"
else
  echo "warning: ACLs not applied (setfacl missing or group unknown)" >&2
fi

printf '{"api_url": "%s", "huron": 1, "instance_id": "%s"}\n' "$api_url" "$instance_id" \
  > "$prefix/.huron"
chmod 0644 "$prefix/.huron"
echo "marker: $prefix/.huron"
