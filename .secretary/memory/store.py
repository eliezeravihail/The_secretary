"""
SQLite-backed memory store.

Schema
------
memories       — one row per memory chunk
memory_links   — co-access associations between chunks (associative recall)
"""

from __future__ import annotations

import json
import sqlite3
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

DB_VERSION = 1


@dataclass
class Memory:
    id: str                          # sha256(content)[:16]
    content: str
    embedding: Optional[list[float]] = None
    memory_type: str = "episodic"    # 'episodic' | 'semantic'
    source: str = ""                 # relative path of origin file
    tags: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    importance: float = 1.0
    access_count: int = 0
    last_accessed: Optional[float] = None

    # Transient — set by retriever, never stored
    score: float = 0.0

    def to_context_line(self) -> str:
        src = self.source.split("/")[-1] if self.source else "?"
        score_str = f"{self.score:.2f}" if self.score else ""
        tag_str = ", ".join(self.tags[:3]) if self.tags else ""
        parts = [f"[{src}]"]
        if tag_str:
            parts.append(f"[{tag_str}]")
        if score_str:
            parts.append(f"[score={score_str}]")
        parts.append(self.content[:300])
        return " ".join(parts)


class MemoryStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._con = sqlite3.connect(str(db_path), check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._con.executescript("""
            PRAGMA journal_mode=WAL;

            CREATE TABLE IF NOT EXISTS _meta (
                key   TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS memories (
                id           TEXT PRIMARY KEY,
                content      TEXT NOT NULL,
                embedding    BLOB,
                memory_type  TEXT NOT NULL DEFAULT 'episodic',
                source       TEXT NOT NULL DEFAULT '',
                tags         TEXT NOT NULL DEFAULT '[]',
                created_at   REAL NOT NULL,
                importance   REAL NOT NULL DEFAULT 1.0,
                access_count INTEGER NOT NULL DEFAULT 0,
                last_accessed REAL
            );

            CREATE INDEX IF NOT EXISTS idx_memories_source
                ON memories(source);
            CREATE INDEX IF NOT EXISTS idx_memories_type
                ON memories(memory_type);
            CREATE INDEX IF NOT EXISTS idx_memories_created
                ON memories(created_at);

            CREATE TABLE IF NOT EXISTS memory_links (
                a_id     TEXT NOT NULL,
                b_id     TEXT NOT NULL,
                strength REAL NOT NULL DEFAULT 1.0,
                PRIMARY KEY (a_id, b_id),
                FOREIGN KEY (a_id) REFERENCES memories(id) ON DELETE CASCADE,
                FOREIGN KEY (b_id) REFERENCES memories(id) ON DELETE CASCADE
            );
        """)
        self._con.execute(
            "INSERT OR IGNORE INTO _meta VALUES ('db_version', ?)", (str(DB_VERSION),)
        )
        self._con.commit()

    @staticmethod
    def _pack_embedding(vec: list[float]) -> bytes:
        return struct.pack(f"{len(vec)}f", *vec)

    @staticmethod
    def _unpack_embedding(blob: bytes) -> list[float]:
        n = len(blob) // 4
        return list(struct.unpack(f"{n}f", blob))

    def upsert(self, mem: Memory) -> None:
        emb_blob = self._pack_embedding(mem.embedding) if mem.embedding else None
        self._con.execute(
            """
            INSERT INTO memories
                (id, content, embedding, memory_type, source, tags,
                 created_at, importance, access_count, last_accessed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                content      = excluded.content,
                embedding    = excluded.embedding,
                memory_type  = excluded.memory_type,
                source       = excluded.source,
                tags         = excluded.tags,
                importance   = excluded.importance
            """,
            (
                mem.id,
                mem.content,
                emb_blob,
                mem.memory_type,
                mem.source,
                json.dumps(mem.tags),
                mem.created_at,
                mem.importance,
                mem.access_count,
                mem.last_accessed,
            ),
        )
        self._con.commit()

    def get(self, mem_id: str) -> Optional[Memory]:
        row = self._con.execute(
            "SELECT * FROM memories WHERE id = ?", (mem_id,)
        ).fetchone()
        return self._row_to_memory(row) if row else None

    def delete_by_source(self, source: str) -> int:
        cur = self._con.execute(
            "DELETE FROM memories WHERE source = ?", (source,)
        )
        self._con.commit()
        return cur.rowcount

    def all_with_embeddings(self) -> list[Memory]:
        rows = self._con.execute(
            "SELECT * FROM memories WHERE embedding IS NOT NULL"
        ).fetchall()
        return [self._row_to_memory(r) for r in rows]

    def all_without_embeddings(self) -> list[Memory]:
        rows = self._con.execute(
            "SELECT * FROM memories WHERE embedding IS NULL"
        ).fetchall()
        return [self._row_to_memory(r) for r in rows]

    def record_access(self, mem_ids: list[str]) -> None:
        now = time.time()
        self._con.executemany(
            "UPDATE memories SET access_count = access_count + 1, last_accessed = ? WHERE id = ?",
            [(now, mid) for mid in mem_ids],
        )
        for i, a in enumerate(mem_ids):
            for b in mem_ids[i + 1 :]:
                self._con.execute(
                    """
                    INSERT INTO memory_links (a_id, b_id, strength)
                    VALUES (?, ?, 1.0)
                    ON CONFLICT(a_id, b_id) DO UPDATE SET
                        strength = MIN(strength + 0.2, 5.0)
                    """,
                    (a, b),
                )
        self._con.commit()

    def stats(self) -> dict:
        row = self._con.execute(
            "SELECT COUNT(*) as total, "
            "SUM(CASE WHEN embedding IS NOT NULL THEN 1 ELSE 0 END) as indexed, "
            "SUM(CASE WHEN memory_type='semantic' THEN 1 ELSE 0 END) as semantic, "
            "SUM(CASE WHEN memory_type='episodic' THEN 1 ELSE 0 END) as episodic "
            "FROM memories"
        ).fetchone()
        return dict(row)

    def _row_to_memory(self, row: sqlite3.Row) -> Memory:
        emb = self._unpack_embedding(row["embedding"]) if row["embedding"] else None
        return Memory(
            id=row["id"],
            content=row["content"],
            embedding=emb,
            memory_type=row["memory_type"],
            source=row["source"],
            tags=json.loads(row["tags"]),
            created_at=row["created_at"],
            importance=row["importance"],
            access_count=row["access_count"],
            last_accessed=row["last_accessed"],
        )

    def close(self) -> None:
        self._con.close()
