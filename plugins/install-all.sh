#!/usr/bin/env bash
set -uo pipefail

plugin_root=$(cd "${BASH_SOURCE[0]%/*}" && pwd)
dashboard_url="${1:-${AGENT_DASHBOARD_URL:-}}"

harnesses=(Codex Pi OpenCode Hermes)
commands=(codex pi opencode hermes)
directories=(codex-agent-dashboard pi-agent-dashboard opencode-agent-dashboard hermes-agent-dashboard)
installed=()
skipped=()
failed=()

for index in "${!harnesses[@]}"; do
  harness=${harnesses[$index]}
  command=${commands[$index]}
  installer="$plugin_root/${directories[$index]}/install.sh"

  if ! command -v "$command" >/dev/null 2>&1; then
    printf 'Skipping %s: %s was not found in PATH.\n' "$harness" "$command"
    skipped+=("$harness")
    continue
  fi

  printf '\nInstalling %s plugin...\n' "$harness"
  if [[ -n "$dashboard_url" ]]; then
    "$installer" "$dashboard_url"
  else
    "$installer"
  fi
  if [[ $? -eq 0 ]]; then
    installed+=("$harness")
  else
    printf 'Failed to install %s plugin; continuing.\n' "$harness" >&2
    failed+=("$harness")
  fi
done

join_or_none() {
  if [[ $# -eq 0 ]]; then
    printf 'none'
  else
    local separator=''
    local item
    for item in "$@"; do
      printf '%s%s' "$separator" "$item"
      separator=', '
    done
  fi
}

printf '\nPlugin installation summary\n'
printf '  Installed: '; join_or_none "${installed[@]}"; printf '\n'
printf '  Skipped:   '; join_or_none "${skipped[@]}"; printf '\n'
printf '  Failed:    '; join_or_none "${failed[@]}"; printf '\n'

[[ ${#failed[@]} -eq 0 ]]
