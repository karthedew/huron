#!/bin/sh
set -eu

export OPENCODE_DISABLE_EXTERNAL_SKILLS=1
exec opencode "$@"
