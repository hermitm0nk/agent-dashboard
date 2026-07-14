#!/usr/bin/env bash
set -euo pipefail

package=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
pi install "$package"
printf 'Installed Pi package from %s\n' "$package"
printf 'Set AGENT_DASHBOARD_URL and restart pi.\n'
