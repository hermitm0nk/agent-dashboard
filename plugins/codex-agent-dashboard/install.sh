#!/usr/bin/env bash
set -euo pipefail

source_root=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
plugin_name=agent-dashboard
plugin_target="${HOME}/.codex/plugins/${plugin_name}"
marketplace_path="${HOME}/.agents/plugins/marketplace.json"
codex_target="${HOME}/.codex"
bin_target="${HOME}/.local/bin"
dashboard_url="${1:-${AGENT_DASHBOARD_URL:-http://127.0.0.1:8000}}"
real_codex="${AGENT_DASHBOARD_CODEX_REAL:-$(command -v codex || true)}"
if [[ -x /usr/bin/codex && -z "${AGENT_DASHBOARD_CODEX_REAL:-}" ]]; then
  real_codex=/usr/bin/codex
fi
if [[ -z "$real_codex" ]]; then
  printf 'Could not locate the real codex executable.\n' >&2
  exit 1
fi

mkdir -p "$plugin_target" "$(dirname "$marketplace_path")" "$codex_target" "$bin_target"
if [[ "$source_root" != "$plugin_target" ]]; then
  cp -R "$source_root/." "$plugin_target/"
fi
chmod +x "$plugin_target/scripts/codex-dashboard-hook.py" \
  "$plugin_target/scripts/codex-dashboard-wrapper.py"
ln -sfn "$plugin_target/scripts/codex-dashboard-wrapper.py" "$bin_target/codex"

marketplace_name=$(python3 - "$marketplace_path" "$plugin_name" <<'PY'
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
plugin_name = sys.argv[2]
if path.exists():
    try:
        marketplace = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot merge invalid marketplace {path}: {exc}")
    if not isinstance(marketplace, dict):
        raise SystemExit(f"Cannot merge marketplace {path}: root must be an object")
else:
    marketplace = {
        "name": "personal",
        "interface": {"displayName": "Personal Plugins"},
        "plugins": [],
    }

marketplace.setdefault("name", "personal")
marketplace.setdefault("interface", {"displayName": "Personal Plugins"})
plugins = marketplace.setdefault("plugins", [])
if not isinstance(plugins, list):
    raise SystemExit(f"Cannot merge marketplace {path}: plugins must be an array")
entry = {
    "name": plugin_name,
    "source": {"source": "local", "path": f"./.codex/plugins/{plugin_name}"},
    "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
    "category": "DeveloperTools",
}
for index, current in enumerate(plugins):
    if isinstance(current, dict) and current.get("name") == plugin_name:
        plugins[index] = {**current, **entry}
        break
else:
    plugins.append(entry)

temporary = path.with_suffix(path.suffix + ".tmp")
temporary.write_text(json.dumps(marketplace, indent=2) + "\n")
os.replace(temporary, path)
print(marketplace["name"])
PY
)

python3 - "$codex_target/agent-dashboard.json" "$dashboard_url" "$real_codex" "$plugin_target/scripts/codex-dashboard-hook.py" <<'PY'
import json
import os
import sys

path, url, real_codex, hook = sys.argv[1:]
config = {"url": url, "real_codex": real_codex, "hook": hook}
for environment, key in (("AGENT_DASHBOARD_TOKEN", "token"),
                         ("AGENT_DASHBOARD_HOST_ID", "host_id")):
    if os.environ.get(environment):
        config[key] = os.environ[environment]
with open(path, "w") as stream:
    json.dump(config, stream)
    stream.write("\n")
os.chmod(path, 0o600)
PY

codex plugin add "$plugin_name" --marketplace "$marketplace_name"

cat <<EOF
Copied Codex plugin to $plugin_target
Merged plugin entry into $marketplace_path
Installed Codex lifecycle wrapper at $bin_target/codex
Dashboard URL: $dashboard_url

Ensure hooks are enabled in $codex_target/config.toml, restart Codex, then
trust the Agent Dashboard plugin hooks in /hooks. Keep $bin_target before the
real Codex binary in PATH so process exit is reported as well.
EOF
