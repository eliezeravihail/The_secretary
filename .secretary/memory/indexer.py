"""
File indexer — orchestrates chunking -> embedding -> upsert.

Incremental: each chunk id = sha256(content)[:16].
Existing id in DB = content unchanged -> skip embedding.
"""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from typing import Iterator

from .chunker import Chunk, get_chunker
from .embed import BaseEmbedder
from .store import Memory, MemoryStore

log = logging.getLogger(__name__)

INDEXED_FILES = ["log.md", "todo.md", "measures.md", "results.md"]
DAILY_GLOB = "daily/**/*.md"
EMBED_BATCH = 32


class Indexer:
    def __init__(self, store: MemoryStore, embedder: BaseEmbedder) -> None:
        self._store = store
        self._embedder = embedder

    def index_file(self, path: Path) -> "IndexReport":
        if not path.exists():
            return IndexReport(path=path)

        try:
            chunker = get_chunker(path)
        except ValueError as exc:
            log.debug("No chunker for %s: %s", path, exc)
            return IndexReport(path=path)

        report = IndexReport(path=path)
        source = str(path)
        chunks = list(chunker.chunks(path))
        report.found = len(chunks)

        new_chunks: list[tuple[str, Chunk]] = []
        for chunk in chunks:
            cid = _chunk_id(chunk.content)
            if self._store.get(cid) is None:
                new_chunks.append((cid, chunk))
            else:
                report.skipped += 1

        for batch in _batched(new_chunks, EMBED_BATCH):
            texts = [c.content for _, c in batch]
            try:
                vectors = self._embedder.embed(texts)
            except Exception as exc:
                log.error("Embedding batch failed for %s: %s", path, exc)
                report.errors += len(batch)
                continue

            for (cid, chunk), vec in zip(batch, vectors):
                mem = Memory(
                    id=cid,
                    content=chunk.content,
                    embedding=vec,
                    memory_type=chunk.memory_type,
                    source=source,
                    tags=chunk.tags,
                    created_at=chunk.created_at,
                    importance=chunk.importance,
                )
                self._store.upsert(mem)
                report.indexed += 1

        return report

    def index_all(self, work_dir: Path) -> list["IndexReport"]:
        reports = []
        for name in INDEXED_FILES:
            reports.append(self.index_file(work_dir / name))
        for daily_file in sorted(work_dir.glob(DAILY_GLOB)):
            if daily_file.suffix == ".md":
                reports.append(self.index_file(daily_file))
        return reports

    def prune_deleted(self, work_dir: Path) -> int:
        all_mems = self._store.all_with_embeddings()
        sources = {m.source for m in all_mems}
        removed = 0
        for src in sources:
            if src and not Path(src).exists():
                removed += self._store.delete_by_source(src)
        return removed

    def rebuild(self, work_dir: Path) -> list["IndexReport"]:
        for name in INDEXED_FILES:
            self._store.delete_by_source(str(work_dir / name))
        for daily_file in work_dir.glob(DAILY_GLOB):
            self._store.delete_by_source(str(daily_file))
        return self.index_all(work_dir)


class IndexReport:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.found = 0
        self.indexed = 0
        self.skipped = 0
        self.errors = 0

    def __repr__(self) -> str:
        return (
            f"IndexReport({self.path.name}: "
            f"found={self.found} indexed={self.indexed} "
            f"skipped={self.skipped} errors={self.errors})"
        )


def _chunk_id(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _batched(items: list, size: int) -> Iterator[list]:
    for i in range(0, len(items), size):
        yield items[i : i + size]
