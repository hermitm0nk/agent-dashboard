#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
target="${HOME}/.config/opencode/plugins"
mkdir -p "$target"
ln -sfn "$root/opencode.ts" "$target/agent-dashboard.ts"
printf 'Installed OpenCode plugin at %s\n' "$target/agent-dashboard.ts"
printf 'Set AGENT_DASHBOARD_URL and restart opencode.\n'
