#!/usr/bin/env bash
set -euo pipefail
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$script_dir/../.." && pwd)"
exec "$script_dir/invoke-project-workflow.sh" validate --root "$root" --strict "$@"
