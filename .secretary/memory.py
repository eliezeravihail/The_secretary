#!/usr/bin/env python3
"""Thin shim so hooks can call: python .secretary/memory.py <cmd>"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from memory.cli import main

if __name__ == "__main__":
    main()
