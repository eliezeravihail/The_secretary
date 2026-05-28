#!/usr/bin/env python3
"""
SessionStart hook — loads relevant memory context.

1. Build query from active todo tasks (open ### headers)
2. Retrieve top-5 related memories (synchronous, bounded by budget)
3. Run incremental indexer in the background (non-blocking)
"""

import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

SECRETARY_DIR = os.environ.get("SECRETARY_DIR", ".secretary")
WORK_DIR = Path(os.environ.get("MEMORY_WORK_DIR", ".")).resolve()
MEMORY_PY = Path(SECRETARY_DIR) / "memory.py"

if not MEMORY_PY.exists():
    sys.exit(0)


def _active_tasks(todo_path: Path) -> str:
    try:
        lines = todo_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    headers = [
        re.sub(r"^### ", "", ln).strip()
        for ln in lines
        if ln.startswith("### ") and "[x]" not in ln.lower()
    ]
    return " ".join(headers[:3])


todo_file = WORK_DIR / "todo.md"
query_text = _active_tasks(todo_file) or f"session start {date.today()}"

# ── Retrieve memories (synchronous) ─────────────────────────────────────────────
result = subprocess.run(
    [sys.executable, str(MEMORY_PY), "query", "--text", query_text, "--k", "5",
     "--types", "semantic,episodic"],
    capture_output=True,
    text=True,
    env={**os.environ, "MEMORY_WORK_DIR": str(WORK_DIR)},
)

if result.returncode == 0 and result.stdout.strip():
    print(f"\n{result.stdout.strip()}\n")

# ── Incremental index in background (non-blocking) ─────────────────────────────
subprocess.Popen(
    [sys.executable, str(MEMORY_PY), "index", "--work-dir", str(WORK_DIR)],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    env={**os.environ, "MEMORY_WORK_DIR": str(WORK_DIR)},
    # Detach cleanly on both Windows and Unix
    **( {"creationflags": 0x00000008} if sys.platform == "win32"   # DETACHED_PROCESS
        else {"start_new_session": True} ),
)

sys.exit(0)
