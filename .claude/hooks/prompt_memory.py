#!/usr/bin/env python3
"""
UserPromptSubmit hook — injects relevant memory as additionalContext.

Reads JSON payload from stdin (Claude Code format).
Suppressed when:
  - prompt starts with /  (slash command)
  - prompt shorter than 30 chars
  - memory DB does not exist yet
  - query returns exit 2 (no results above threshold)
"""

import json
import os
import subprocess
import sys
from pathlib import Path

SECRETARY_DIR = os.environ.get("SECRETARY_DIR", ".secretary")
WORK_DIR = Path(os.environ.get("MEMORY_WORK_DIR", ".")).resolve()
MEMORY_PY = Path(SECRETARY_DIR) / "memory.py"

# ── Read prompt from stdin ──────────────────────────────────────────────────
try:
    raw = sys.stdin.read()
    payload = json.loads(raw) if raw.strip() else {}
except (json.JSONDecodeError, OSError):
    payload = {}

prompt = payload.get("prompt", "")

# ── Suppression rules ────────────────────────────────────────────────────────
if not prompt:
    sys.exit(0)
if prompt.startswith("/"):
    sys.exit(0)
if len(prompt) < 30:
    sys.exit(0)
if not MEMORY_PY.exists():
    sys.exit(0)

db_path = Path(
    os.environ.get("MEMORY_DB_PATH", str(WORK_DIR / ".secretary" / "memory.db"))
)
if not db_path.exists():
    sys.exit(0)

# ── Retrieve top-3 memories ─────────────────────────────────────────────────
result = subprocess.run(
    [sys.executable, str(MEMORY_PY), "query", "--text", prompt, "--k", "3"],
    capture_output=True,
    text=True,
    env={**os.environ,
         "MEMORY_WORK_DIR": str(WORK_DIR),
         "MEMORY_DB_PATH": str(db_path)},
)

# exit 2 = no results above threshold
if result.returncode == 2 or not result.stdout.strip():
    sys.exit(0)

# ── Emit additionalContext JSON ───────────────────────────────────────────────
output = {
    "hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": result.stdout.strip(),
    }
}
print(json.dumps(output, ensure_ascii=False))
sys.exit(0)
