#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
target="${HOME}/.pi/agent/extensions"
mkdir -p "$target"
ln -sfn "$root/pi.ts" "$target/agent-dashboard.ts"
printf 'Installed pi extension at %s\n' "$target/agent-dashboard.ts"
printf 'Set AGENT_DASHBOARD_URL and restart pi.\n'
