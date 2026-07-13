#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
target="${HOME}/.hermes/agent-hooks"
mkdir -p "$target"
ln -sfn "$root/hermes-dashboard-hook.py" "$target/agent-dashboard-hook.py"
chmod +x "$root/hermes-dashboard-hook.py"

printf 'Installed Hermes shell hook at %s\n\n' "$target/agent-dashboard-hook.py"
printf 'Add this block to ~/.hermes/config.yaml:\n\n'
printf 'hooks:\n'
printf '  on_session_start:\n    - command: %s\n' "$target/agent-dashboard-hook.py"
printf '  pre_llm_call:\n    - command: %s\n' "$target/agent-dashboard-hook.py"
printf '  post_llm_call:\n    - command: %s\n' "$target/agent-dashboard-hook.py"
printf '  on_session_end:\n    - command: %s\n' "$target/agent-dashboard-hook.py"
printf 'hooks_auto_accept: false\n'
