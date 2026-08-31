#!/usr/bin/env bash
# Vendor Mermaid so the docs render diagrams without reaching the public internet.
#
# Material for MkDocs loads Mermaid from https://unpkg.com at runtime. On a network
# that blocks it, two things break:
#
#   1. Diagrams render as raw code blocks.
#   2. Search stops working ON PAGES THAT CONTAIN A DIAGRAM — the failing script
#      aborts Material's JavaScript before the search handler is wired up.
#
# The second one is the reason this script exists. It looks like a search bug and
# it is not.
#
# After running this, add the following to mkdocs.yml (order matters — the local
# copy must define window.mermaid before Material looks for it):
#
#   extra_javascript:
#     - javascripts/mermaid.min.js
#
# Usage:  ./scripts/vendor-mermaid.sh [version]

set -euo pipefail

VERSION="${1:-11}"
DEST="docs/javascripts/mermaid.min.js"
URL="https://unpkg.com/mermaid@${VERSION}/dist/mermaid.min.js"

if [[ ! -f mkdocs.yml ]]; then
  echo "error: run this from the repository root (mkdocs.yml not found)" >&2
  exit 1
fi

mkdir -p "$(dirname "$DEST")"

echo "fetching mermaid@${VERSION} …"
if ! curl -fsSL -o "$DEST.tmp" "$URL"; then
  cat >&2 <<'MSG'
error: could not fetch Mermaid.

On an air-gapped network, obtain mermaid.min.js from your internal mirror or a
machine with egress and place it at docs/javascripts/mermaid.min.js by hand.
MSG
  rm -f "$DEST.tmp"
  exit 1
fi

# Sanity check: a proxy error page is also a successful HTTP response.
if ! head -c 2000 "$DEST.tmp" | grep -q "mermaid"; then
  echo "error: downloaded file does not look like Mermaid (captive portal or proxy?)" >&2
  rm -f "$DEST.tmp"
  exit 1
fi

mv "$DEST.tmp" "$DEST"
echo "wrote $DEST ($(du -h "$DEST" | cut -f1))"
echo
echo "Now add to mkdocs.yml:"
echo
echo "  extra_javascript:"
echo "    - javascripts/mermaid.min.js"
