#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
target="${HOME}/.hermes/plugins/agent-dashboard"
dashboard_url="${1:-${AGENT_DASHBOARD_URL:-http://127.0.0.1:8000}}"
mkdir -p "$(dirname "$target")" "${HOME}/.hermes"
ln -sfn "$root/hermes_plugin" "$target"

python3 - "${HOME}/.hermes/agent-dashboard.json" "$dashboard_url" <<'PY'
import json
import os
import sys

path, url = sys.argv[1:]
config = {"url": url}
for environment, key in (("AGENT_DASHBOARD_TOKEN", "token"),
                         ("AGENT_DASHBOARD_HOST_ID", "host_id")):
    if os.environ.get(environment):
        config[key] = os.environ[environment]
with open(path, "w") as stream:
    json.dump(config, stream)
    stream.write("\n")
os.chmod(path, 0o600)
PY

printf 'Installed Hermes plugin at %s\n' "$target"
printf 'Dashboard URL: %s\n' "$dashboard_url"
if command -v hermes >/dev/null 2>&1; then
  hermes plugins enable --no-allow-tool-override agent-dashboard
else
  printf 'Hermes was not found in PATH. Run: hermes plugins enable agent-dashboard\n'
fi
printf 'Remove any legacy agent-dashboard entries from the hooks: section of ~/.hermes/config.yaml.\n'
