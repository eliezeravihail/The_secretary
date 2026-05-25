#!/usr/bin/env bash
# PostToolUse hook — re-indexes a secretary file after Edit/Write.
# Runs in background so it never delays the response.

set -u

SECRETARY_DIR="${SECRETARY_DIR:-.secretary}"
MEMORY_PY="$SECRETARY_DIR/memory.py"
WORK_DIR="${MEMORY_WORK_DIR:-$(pwd)}"

[ ! -f "$MEMORY_PY" ] && exit 0

payload=$(cat || true)
if command -v jq >/dev/null 2>&1; then
  file_path=$(printf '%s' "$payload" | jq -r '.tool_input.file_path // empty' 2>/dev/null || true)
else
  file_path=""
fi

[ -z "$file_path" ] && exit 0

basename=$(basename "$file_path")
case "$basename" in
  log.md|todo.md|measures.md|results.md) ;;
  *.md)
    [[ "$file_path" != *"/daily/"* ]] && exit 0
    ;;
  *) exit 0 ;;
esac

MEMORY_WORK_DIR="$WORK_DIR" python3 "$MEMORY_PY" index \
  --file "$file_path" >/dev/null 2>&1 &

exit 0
