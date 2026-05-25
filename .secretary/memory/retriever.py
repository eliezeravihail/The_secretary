"""
Composite-score retrieval.

Score = w_sem  * cosine_similarity(q, mem)
      + w_time * temporal_recency(mem.created_at)
      + w_imp  * normalized_importance(mem.importance)
      + w_acc  * access_popularity(mem.access_count)

Threshold filtering (default 0.42) prevents injecting noise when the
query has no relevant past context.
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass
from typing import Optional

from .embed import BaseEmbedder
from .store import Memory, MemoryStore


@dataclass
class RetrievalConfig:
    k: int = 5
    threshold: float = 0.42
    max_tokens: int = 500
    memory_types: Optional[list[str]] = None

    w_semantic: float = 0.70
    w_temporal: float = 0.15
    w_importance: float = 0.10
    w_popularity: float = 0.05

    temporal_half_life_days: float = 180.0

    @classmethod
    def from_env(cls) -> "RetrievalConfig":
        return cls(
            k=int(os.environ.get("MEMORY_K", 5)),
            threshold=float(os.environ.get("MEMORY_THRESHOLD", 0.42)),
            max_tokens=int(os.environ.get("MEMORY_MAX_TOKENS", 500)),
            temporal_half_life_days=float(
                os.environ.get("MEMORY_HALF_LIFE_DAYS", 180)
            ),
        )


class Retriever:
    def __init__(
        self,
        store: MemoryStore,
        embedder: BaseEmbedder,
        config: Optional[RetrievalConfig] = None,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._cfg = config or RetrievalConfig.from_env()

    def query(self, text: str) -> list[Memory]:
        if not text.strip():
            return []

        query_vec = self._embedder.embed_one(text)
        candidates = self._store.all_with_embeddings()

        if self._cfg.memory_types:
            candidates = [
                m for m in candidates
                if m.memory_type in self._cfg.memory_types
            ]

        if not candidates:
            return []

        max_importance = max((m.importance for m in candidates), default=1.0)
        max_access = max((m.access_count for m in candidates), default=1)

        scored: list[tuple[float, Memory]] = []
        for mem in candidates:
            score = self._score(query_vec, mem, max_importance, max_access)
            if score >= self._cfg.threshold:
                scored.append((score, mem))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[: self._cfg.k]

        results: list[Memory] = []
        budget = self._cfg.max_tokens * 4
        for score, mem in top:
            if budget <= 0:
                break
            mem.score = score
            results.append(mem)
            budget -= len(mem.content)

        if results:
            self._store.record_access([m.id for m in results])

        return results

    def format_for_context(self, memories: list[Memory]) -> str:
        if not memories:
            return ""
        lines = ["[memory-context] Relevant past context:"]
        for mem in memories:
            lines.append(f"  • {mem.to_context_line()}")
        return "\n".join(lines)

    def _score(
        self,
        query_vec: list[float],
        mem: Memory,
        max_importance: float,
        max_access: int,
    ) -> float:
        cfg = self._cfg
        sem = self._cosine(query_vec, mem.embedding or [])
        age_days = max((time.time() - mem.created_at) / 86400, 0.0)
        temporal = math.exp(-age_days * math.log(2) / cfg.temporal_half_life_days)
        imp = mem.importance / max_importance if max_importance else 0.0
        pop = math.log1p(mem.access_count) / math.log1p(max_access) \
            if max_access > 0 else 0.0
        return (
            cfg.w_semantic * sem
            + cfg.w_temporal * temporal
            + cfg.w_importance * imp
            + cfg.w_popularity * pop
        )

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return max(-1.0, min(1.0, dot / (norm_a * norm_b)))
