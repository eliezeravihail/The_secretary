#!/usr/bin/env bash
# UserPromptSubmit hook — injects relevant memory as additionalContext.
#
# Suppressed when:
#   - prompt starts with /  (slash command)
#   - prompt shorter than 30 chars
#   - memory DB does not exist yet
#   - query returns exit code 2 (no results above threshold)

set -u

SECRETARY_DIR="${SECRETARY_DIR:-.secretary}"
MEMORY_PY="$SECRETARY_DIR/memory.py"
WORK_DIR="${MEMORY_WORK_DIR:-$(pwd)}"

payload=$(cat || true)
if command -v jq >/dev/null 2>&1; then
  prompt=$(printf '%s' "$payload" | jq -r '.prompt // empty' 2>/dev/null || true)
else
  prompt=$(printf '%s' "$payload")
fi

[ -z "$prompt" ] && exit 0
case "$prompt" in /*) exit 0 ;; esac
[ "${#prompt}" -lt 30 ] && exit 0
[ ! -f "$MEMORY_PY" ] && exit 0

DB_PATH="${MEMORY_DB_PATH:-$WORK_DIR/.secretary/memory.db}"
[ ! -f "$DB_PATH" ] && exit 0

memory_context=$(MEMORY_WORK_DIR="$WORK_DIR" MEMORY_DB_PATH="$DB_PATH" \
  python3 "$MEMORY_PY" query --text "$prompt" --k 3 2>/dev/null)

query_exit=$?
[ "$query_exit" -eq 2 ] && exit 0
[ -z "$memory_context" ] && exit 0

if command -v jq >/dev/null 2>&1; then
  jq -nc --arg ctx "$memory_context" \
    '{hookSpecificOutput: {hookEventName: "UserPromptSubmit", additionalContext: $ctx}}'
else
  esc=$(printf '%s' "$memory_context" \
    | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' \
    | awk 'BEGIN{ORS="\\n"} {print}')
  printf '{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":"%s"}}\n' "$esc"
fi

exit 0
