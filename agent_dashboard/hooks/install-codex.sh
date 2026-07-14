#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
target="${HOME}/.codex"
bin_target="${HOME}/.local/bin"
dashboard_url="${1:-${AGENT_DASHBOARD_URL:-http://127.0.0.1:8000}}"
real_codex="${AGENT_DASHBOARD_CODEX_REAL:-$(command -v codex || true)}"
if [[ -x /usr/bin/codex ]]; then
  real_codex=/usr/bin/codex
fi
if [[ -z "$real_codex" ]]; then
  printf 'Could not locate the real codex executable.\n' >&2
  exit 1
fi
mkdir -p "$target" "$bin_target"
ln -sfn "$root/codex-dashboard-hook.py" "$target/agent-dashboard-hook.py"
ln -sfn "$root/codex-dashboard-wrapper.py" "$bin_target/codex"
chmod +x "$root/codex-dashboard-hook.py" "$root/codex-dashboard-wrapper.py"
python3 - "$target/agent-dashboard.json" "$dashboard_url" "$real_codex" "$target/agent-dashboard-hook.py" <<'PY'
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
cat <<EOF > "$target/hooks.json"
{"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"$target/agent-dashboard-hook.py"}]}],"UserPromptSubmit":[{"hooks":[{"type":"command","command":"$target/agent-dashboard-hook.py"}]}],"Stop":[{"hooks":[{"type":"command","command":"$target/agent-dashboard-hook.py"}]}]}}
EOF

cat <<EOF
Installed Codex hook at $target/agent-dashboard-hook.py
Installed Codex lifecycle wrapper at $bin_target/codex
Dashboard URL: $dashboard_url

Codex discovers $target/hooks.json automatically. Ensure hooks are enabled in
$target/config.toml:

[features]
hooks = true

Restart Codex, open /hooks, and trust the three agent-dashboard commands.
EOF
