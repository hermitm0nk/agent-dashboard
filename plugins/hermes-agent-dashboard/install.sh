#!/usr/bin/env bash
set -euo pipefail

package_root=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
dashboard_url="${1:-${AGENT_DASHBOARD_URL:-http://127.0.0.1:8000}}"
hermes_executable=$(command -v hermes || true)
if [[ -z "$hermes_executable" ]]; then
  printf 'Hermes was not found in PATH. Install Hermes before this plugin.\n' >&2
  exit 1
fi
hermes_python="${HERMES_PYTHON:-}"
if [[ -z "$hermes_python" ]]; then
  hermes_script=$(readlink -f "$hermes_executable")
  hermes_bin=$(dirname "$hermes_script")
  # Current Hermes launchers are shell/Python polyglot scripts whose first
  # line is /bin/sh. Their actual interpreter is the sibling venv python3.
  if [[ -x "$hermes_bin/python3" ]]; then
    hermes_python="$hermes_bin/python3"
  elif [[ -x "$hermes_bin/python" ]]; then
    hermes_python="$hermes_bin/python"
  else
    hermes_python=$(head -n 1 "$hermes_script")
    hermes_python=${hermes_python#\#!}
    # A shell shebang is a launcher, not a Python interpreter.
    if [[ "$hermes_python" == */sh || "$hermes_python" == */bash ]]; then
      hermes_python=""
    fi
  fi
fi
if [[ ! -x "$hermes_python" ]]; then
  printf 'Could not determine the Python interpreter used by Hermes. Set HERMES_PYTHON.\n' >&2
  exit 1
fi
mkdir -p "${HOME}/.hermes"

# Entry-point metadata makes the plugin discoverable from every Hermes profile.
if command -v uv >/dev/null 2>&1; then
  uv pip install --python "$hermes_python" --no-deps --reinstall "$package_root"
elif "$hermes_python" -m pip --version >/dev/null 2>&1; then
  "$hermes_python" -m pip install --no-deps --force-reinstall "$package_root"
else
  printf 'Installing the plugin requires uv or pip in the Hermes environment.\n' >&2
  exit 1
fi
legacy_target="${HOME}/.hermes/plugins/agent-dashboard"
if [[ -L "$legacy_target" ]]; then
  unlink "$legacy_target"
fi

python3 - "${HOME}/.hermes/agent-dashboard.json" "$dashboard_url" <<'PY'
import json
import os
import sys

path, url = sys.argv[1:]
config = {"url": url}
for environment, key in (("AGENT_DASHBOARD_HOST_ID", "host_id"),):
    if os.environ.get(environment):
        config[key] = os.environ[environment]
with open(path, "w") as stream:
    json.dump(config, stream)
    stream.write("\n")
os.chmod(path, 0o600)
PY

printf 'Installed Hermes plugin package from %s\n' "$package_root"
printf 'Dashboard URL: %s\n' "$dashboard_url"
hermes plugins enable --no-allow-tool-override agent-dashboard
