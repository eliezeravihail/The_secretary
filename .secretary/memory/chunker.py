"""
File-to-chunk strategies per secretary file type.

Chunk design principles
-----------------------
- Minimum ~50 chars — sub-sentence fragments embed poorly
- Maximum ~600 chars — stay within embedding model context limit
- Each chunk maps to exactly one logical unit
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass
class Chunk:
    content: str
    memory_type: str
    tags: list[str]
    importance: float
    created_at: float


class BaseChunker:
    MEMORY_TYPE: str = "episodic"
    IMPORTANCE: float = 1.0
    MIN_LEN: int = 40

    def chunks(self, path: Path) -> Iterator[Chunk]:
        raise NotImplementedError

    def _parse_date(self, date_str: str) -> float:
        import datetime
        for fmt in ("%Y-%m-%d", "%Y-%m"):
            try:
                dt = datetime.datetime.strptime(date_str.strip(), fmt)
                return dt.timestamp()
            except ValueError:
                pass
        return time.time()


class LogChunker(BaseChunker):
    """
    log.md: [YYYY-MM-DD] one-line summary — one chunk per line.
    """
    MEMORY_TYPE = "episodic"
    IMPORTANCE = 0.8
    LINE_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2})\]\s+(.+)$")

    def chunks(self, path: Path) -> Iterator[Chunk]:
        for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if not line or len(line) < self.MIN_LEN:
                continue
            m = self.LINE_RE.match(line)
            date_str, content_text = (m.group(1), m.group(2)) if m else ("", line)
            tags = ["source:log"]
            first_word = content_text.split(":")[0].strip().lower()
            if first_word in ("result", "insight", "todo", "calendar"):
                tags.append(f"type:{first_word}")
            yield Chunk(
                content=line,
                memory_type=self.MEMORY_TYPE,
                tags=tags,
                importance=self.IMPORTANCE,
                created_at=self._parse_date(date_str) if date_str else time.time(),
            )


class TodoChunker(BaseChunker):
    """
    todo.md: one chunk per main-task block (header + subtasks).
    Semantic because active tasks are high-signal background context.
    """
    MEMORY_TYPE = "semantic"
    IMPORTANCE = 1.3
    SECTION_RE = re.compile(r"^### (.+)$")
    PRIORITY_RE = re.compile(r"\[P([123])\]")

    def chunks(self, path: Path) -> Iterator[Chunk]:
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        current_block: list[str] = []
        current_tags: list[str] = []
        current_importance = self.IMPORTANCE

        def flush(block: list[str], tags: list[str], imp: float) -> Iterator[Chunk]:
            joined = "\n".join(block).strip()
            if len(joined) >= self.MIN_LEN:
                yield Chunk(
                    content=joined[:600],
                    memory_type=self.MEMORY_TYPE,
                    tags=tags,
                    importance=imp,
                    created_at=time.time(),
                )

        for line in lines:
            m = self.SECTION_RE.match(line)
            if m:
                if current_block:
                    yield from flush(current_block, current_tags, current_importance)
                header = m.group(1)
                current_block = [line]
                pm = self.PRIORITY_RE.search(header)
                priority = int(pm.group(1)) if pm else 2
                current_importance = self.IMPORTANCE + (3 - priority) * 0.1
                current_tags = ["source:todo", f"priority:P{priority}"]
                if "[x]" in header.lower():
                    current_importance *= 0.5
            elif current_block:
                current_block.append(line)

        if current_block:
            yield from flush(current_block, current_tags, current_importance)


class MeasuresChunker(BaseChunker):
    """
    measures.md: one chunk per run entry (### YYYY-MM-DD), tagged with experiment.
    """
    MEMORY_TYPE = "episodic"
    IMPORTANCE = 1.2
    EXPERIMENT_RE = re.compile(r"^## (.+)$")
    ENTRY_RE = re.compile(r"^### (\d{4}-\d{2}-\d{2})\s*[·⋅]\s*(.+)$")

    def chunks(self, path: Path) -> Iterator[Chunk]:
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        current_experiment = ""
        current_entry_lines: list[str] = []
        current_date = ""

        def flush(exp: str, date: str, entry_lines: list[str]) -> Iterator[Chunk]:
            content = "\n".join(entry_lines).strip()
            if len(content) < self.MIN_LEN:
                return
            full = f"[{exp}] {content}"[:600]
            yield Chunk(
                content=full,
                memory_type=self.MEMORY_TYPE,
                tags=["source:measures", f"experiment:{exp.split('—')[0].strip()[:30]}"],
                importance=self.IMPORTANCE,
                created_at=self._parse_date(date) if date else time.time(),
            )

        for line in lines:
            em = self.EXPERIMENT_RE.match(line)
            if em:
                if current_entry_lines:
                    yield from flush(current_experiment, current_date, current_entry_lines)
                    current_entry_lines = []
                current_experiment = em.group(1).strip()
                continue
            nm = self.ENTRY_RE.match(line)
            if nm:
                if current_entry_lines:
                    yield from flush(current_experiment, current_date, current_entry_lines)
                current_date = nm.group(1)
                current_entry_lines = [line]
            elif current_entry_lines:
                current_entry_lines.append(line)

        if current_entry_lines:
            yield from flush(current_experiment, current_date, current_entry_lines)


class ResultsChunker(BaseChunker):
    """
    results.md: one chunk per ## section. Semantic — conclusions have highest reuse.
    """
    MEMORY_TYPE = "semantic"
    IMPORTANCE = 1.6
    SECTION_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2})\s*[·⋅]\s*(.+)$")

    def chunks(self, path: Path) -> Iterator[Chunk]:
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        current_lines: list[str] = []
        current_date = ""
        current_topic = ""

        def flush(date: str, topic: str, block: list[str]) -> Iterator[Chunk]:
            content = "\n".join(block).strip()
            if len(content) < self.MIN_LEN:
                return
            yield Chunk(
                content=content[:600],
                memory_type="semantic",
                tags=["source:results", f"topic:{topic[:30]}"],
                importance=self.IMPORTANCE,
                created_at=self._parse_date(date) if date else time.time(),
            )

        for line in lines:
            m = self.SECTION_RE.match(line)
            if m:
                if current_lines:
                    yield from flush(current_date, current_topic, current_lines)
                current_date, current_topic = m.group(1), m.group(2)
                current_lines = [line]
            elif current_lines:
                current_lines.append(line)

        if current_lines:
            yield from flush(current_date, current_topic, current_lines)


class DailyLogChunker(BaseChunker):
    """
    daily/YYYY-MM/YYYY-MM-DD.md: one chunk per ### activity block.
    """
    MEMORY_TYPE = "episodic"
    IMPORTANCE = 1.0
    DATE_RE = re.compile(r"# Journal (\d{4}-\d{2}-\d{2})")
    ACTIVITY_BLOCK_RE = re.compile(r"^### (.+)$")

    def chunks(self, path: Path) -> Iterator[Chunk]:
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        date_str = ""
        dm = self.DATE_RE.search(text)
        if dm:
            date_str = dm.group(1)

        in_activity = False
        current_lines: list[str] = []

        def flush(date: str, block: list[str]) -> Iterator[Chunk]:
            content = "\n".join(block).strip()
            if len(content) < self.MIN_LEN:
                return
            yield Chunk(
                content=content[:600],
                memory_type=self.MEMORY_TYPE,
                tags=["source:daily", f"date:{date}"],
                importance=self.IMPORTANCE,
                created_at=self._parse_date(date) if date else time.time(),
            )

        for line in lines:
            if line.strip() == "## Activity":
                in_activity = True
                continue
            if line.startswith("## ") and in_activity:
                if current_lines:
                    yield from flush(date_str, current_lines)
                    current_lines = []
                in_activity = False
                continue
            if in_activity:
                if self.ACTIVITY_BLOCK_RE.match(line):
                    if current_lines:
                        yield from flush(date_str, current_lines)
                    current_lines = [line]
                elif current_lines:
                    current_lines.append(line)

        if current_lines:
            yield from flush(date_str, current_lines)


_CHUNKER_MAP: dict[str, type[BaseChunker]] = {
    "log.md": LogChunker,
    "todo.md": TodoChunker,
    "measures.md": MeasuresChunker,
    "results.md": ResultsChunker,
}


def get_chunker(path: Path) -> BaseChunker:
    name = path.name
    if name in _CHUNKER_MAP:
        return _CHUNKER_MAP[name]()
    if "daily" in str(path):
        return DailyLogChunker()
    raise ValueError(f"No chunker registered for: {path}")
