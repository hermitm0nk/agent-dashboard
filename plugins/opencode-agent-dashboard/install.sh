#!/usr/bin/env bash
set -euo pipefail

package=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
opencode plugin "$package" --global --force
printf 'Installed OpenCode npm plugin from %s\n' "$package"
printf 'Set AGENT_DASHBOARD_URL and restart opencode.\n'
