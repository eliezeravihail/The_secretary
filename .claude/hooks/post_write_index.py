#!/usr/bin/env python3
"""
PostToolUse hook — re-indexes a secretary file after Edit/Write.

Reads JSON payload from stdin (Claude Code format).
Runs the indexer in the background — never delays the response.
Only indexes known secretary file types.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

SECRETARY_DIR = os.environ.get("SECRETARY_DIR", ".secretary")
WORK_DIR = Path(os.environ.get("MEMORY_WORK_DIR", ".")).resolve()
MEMORY_PY = Path(SECRETARY_DIR) / "memory.py"

if not MEMORY_PY.exists():
    sys.exit(0)

# ── Read file path from hook payload ───────────────────────────────────────────
try:
    raw = sys.stdin.read()
    payload = json.loads(raw) if raw.strip() else {}
except (json.JSONDecodeError, OSError):
    sys.exit(0)

file_path = payload.get("tool_input", {}).get("file_path", "")
if not file_path:
    sys.exit(0)

# ── Gate: only index known secretary files ──────────────────────────────────────────
p = Path(file_path)
INDEXED_NAMES = {"log.md", "todo.md", "measures.md", "results.md"}

if p.name not in INDEXED_NAMES:
    parts = p.parts
    if "daily" not in parts:
        sys.exit(0)
    if p.suffix != ".md":
        sys.exit(0)

# ── Incremental index (background) ───────────────────────────────────────────────
subprocess.Popen(
    [sys.executable, str(MEMORY_PY), "index", "--file", str(file_path)],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    env={**os.environ, "MEMORY_WORK_DIR": str(WORK_DIR)},
    **( {"creationflags": 0x00000008} if sys.platform == "win32"
        else {"start_new_session": True} ),
)

sys.exit(0)
