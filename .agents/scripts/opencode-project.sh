#!/bin/sh
set -eu

# Optional argument-forwarding convenience. Normal root startup uses opencode directly.
exec opencode "$@"
