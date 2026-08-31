#!/usr/bin/env bash
# Bootstraps and verifies the object-storage buckets against a running
# MinIO instance. Delegates to bootstrap_buckets.py, which talks to the
# store directly through botocore rather than shelling out to a client
# binary — nothing beyond the project's own dependencies is required.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec uv run python "${script_dir}/bootstrap_buckets.py"
