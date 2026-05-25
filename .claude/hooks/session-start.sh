#!/usr/bin/env bash
# SessionStart hook — loads relevant memory context.
#
# 1. Build query from active todo tasks
# 2. Retrieve top-5 related memories (synchronous)
# 3. Run incremental indexer in background (non-blocking)

set -u

SECRETARY_DIR="${SECRETARY_DIR:-.secretary}"
MEMORY_PY="$SECRETARY_DIR/memory.py"
WORK_DIR="${MEMORY_WORK_DIR:-$(pwd)}"

[ ! -f "$MEMORY_PY" ] && exit 0

TODO_FILE="$WORK_DIR/todo.md"
query_text="session start $(date +%Y-%m-%d)"

if [ -f "$TODO_FILE" ]; then
  active_tasks=$(grep -E '^\#\#\# ' "$TODO_FILE" 2>/dev/null \
    | grep -v '\[x\]' \
    | head -3 \
    | sed 's/^### //' \
    | tr '\n' ' ')
  [ -n "$active_tasks" ] && query_text="$active_tasks"
fi

memory_context=$(MEMORY_WORK_DIR="$WORK_DIR" \
  python3 "$MEMORY_PY" query \
  --text "$query_text" \
  --k 5 \
  --types "semantic,episodic" \
  2>/dev/null)

[ $? -eq 0 ] && [ -n "$memory_context" ] && printf '\n%s\n\n' "$memory_context"

MEMORY_WORK_DIR="$WORK_DIR" python3 "$MEMORY_PY" index \
  --work-dir "$WORK_DIR" >/dev/null 2>&1 &

exit 0
