"""
Embedding provider abstraction.

Priority order (first available wins):
  1. Voyage AI  — voyageai SDK, VOYAGE_API_KEY env var   (Anthropic-recommended)
  2. OpenAI     — openai SDK,   OPENAI_API_KEY env var
  3. Local TF-IDF — zero-dep fallback; lower quality but always works

All providers return float32 vectors of a fixed dimension.
The CachedEmbedder wraps any provider to skip re-embedding unchanged text.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class BaseEmbedder(ABC):
    DIM: int = 0

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input text."""

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]


class VoyageEmbedder(BaseEmbedder):
    """voyage-3-lite: 512-dim, cheap, fast."""
    DIM = 512
    MODEL = "voyage-3-lite"

    def __init__(self) -> None:
        import voyageai  # type: ignore
        self._client = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])

    def embed(self, texts: list[str]) -> list[list[float]]:
        result = self._client.embed(texts, model=self.MODEL, input_type="document")
        return result.embeddings


class OpenAIEmbedder(BaseEmbedder):
    """text-embedding-3-small: 1536-dim."""
    DIM = 1536
    MODEL = "text-embedding-3-small"

    def __init__(self) -> None:
        from openai import OpenAI  # type: ignore
        self._client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    def embed(self, texts: list[str]) -> list[list[float]]:
        resp = self._client.embeddings.create(
            model=self.MODEL,
            input=texts,
            encoding_format="float",
        )
        return [item.embedding for item in resp.data]


class TFIDFEmbedder(BaseEmbedder):
    """
    Deterministic sparse-to-dense projection.
    No external deps, no API calls.
    Quality is low — similarity scores will be rough approximations.
    """
    DIM = 256

    def __init__(self, vocab_path: Optional[Path] = None) -> None:
        self._vocab: dict[str, int] = {}
        self._idf: dict[str, float] = {}
        if vocab_path and vocab_path.exists():
            data = json.loads(vocab_path.read_text())
            self._vocab = data.get("vocab", {})
            self._idf = data.get("idf", {})

    def _tokenize(self, text: str) -> list[str]:
        import re
        return re.findall(r"[a-zA-Zא-ת]{2,}", text.lower())

    def _sparse(self, tokens: list[str]) -> dict[int, float]:
        counts: dict[int, float] = {}
        for tok in tokens:
            idx = self._vocab.get(tok)
            if idx is not None:
                counts[idx] = counts.get(idx, 0.0) + 1.0
        total = sum(counts.values()) or 1.0
        return {i: v / total * self._idf.get(t, 1.0)
                for t, i in self._vocab.items()
                if i in counts
                for v in [counts[i]]}

    def _project(self, sparse: dict[int, float]) -> list[float]:
        import math
        vec = [0.0] * self.DIM
        for vocab_idx, weight in sparse.items():
            h1 = (vocab_idx * 2654435761) & 0xFFFFFFFF
            h2 = (vocab_idx * 2246822519) & 0xFFFFFFFF
            vec[h1 % self.DIM] += weight
            vec[h2 % self.DIM] -= weight
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed(self, texts: list[str]) -> list[list[float]]:
        result = []
        for text in texts:
            tokens = self._tokenize(text)
            if not tokens:
                result.append([0.0] * self.DIM)
                continue
            for tok in tokens:
                if tok not in self._vocab:
                    self._vocab[tok] = len(self._vocab)
            sparse = self._sparse(tokens)
            result.append(self._project(sparse))
        return result

    def fit(self, texts: list[str], vocab_path: Optional[Path] = None) -> None:
        import math
        from collections import Counter
        doc_counts: Counter = Counter()
        N = len(texts)
        for text in texts:
            seen = set(self._tokenize(text))
            doc_counts.update(seen)
        self._idf = {
            tok: math.log((N + 1) / (cnt + 1)) + 1.0
            for tok, cnt in doc_counts.items()
        }
        if vocab_path:
            vocab_path.write_text(
                json.dumps({"vocab": self._vocab, "idf": self._idf})
            )


class CachedEmbedder(BaseEmbedder):
    """
    Wraps any embedder. Skips API calls for texts whose sha256 is already cached.
    """

    def __init__(self, inner: BaseEmbedder, cache_path: Path) -> None:
        self._inner = inner
        self.DIM = inner.DIM
        self._cache_path = cache_path
        self._cache: dict[str, list[float]] = {}
        if cache_path.exists():
            self._load()

    def embed(self, texts: list[str]) -> list[list[float]]:
        keys = [self._key(t) for t in texts]
        missing_indices = [i for i, k in enumerate(keys) if k not in self._cache]

        if missing_indices:
            missing_texts = [texts[i] for i in missing_indices]
            new_vecs = self._inner.embed(missing_texts)
            for i, vec in zip(missing_indices, new_vecs):
                self._cache[keys[i]] = vec
            self._save()

        return [self._cache[k] for k in keys]

    @staticmethod
    def _key(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:24]

    def _load(self) -> None:
        try:
            raw = self._cache_path.read_bytes()
            n = len(raw) // (24 + self.DIM * 4)
            for i in range(n):
                offset = i * (24 + self.DIM * 4)
                key = raw[offset : offset + 24].decode(errors="ignore").rstrip("\x00")
                vec = list(struct.unpack(f"{self.DIM}f", raw[offset + 24 : offset + 24 + self.DIM * 4]))
                self._cache[key] = vec
        except Exception:
            self._cache = {}

    def _save(self) -> None:
        parts = []
        for key, vec in self._cache.items():
            parts.append(key.encode().ljust(24, b"\x00")[:24])
            parts.append(struct.pack(f"{self.DIM}f", *vec))
        self._cache_path.write_bytes(b"".join(parts))


def get_embedder(cache_dir: Optional[Path] = None) -> BaseEmbedder:
    """
    Return the best available embedder, wrapped in a cache.
    Tries Voyage -> OpenAI -> TF-IDF.
    """
    inner: BaseEmbedder = None  # type: ignore

    if os.environ.get("VOYAGE_API_KEY"):
        try:
            inner = VoyageEmbedder()
        except ImportError:
            pass

    if inner is None and os.environ.get("OPENAI_API_KEY"):
        try:
            inner = OpenAIEmbedder()
        except ImportError:
            pass

    if inner is None:
        vocab_path = (cache_dir / "tfidf_vocab.json") if cache_dir else None
        inner = TFIDFEmbedder(vocab_path=vocab_path)

    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"embed_cache_{inner.__class__.__name__}.bin"
        return CachedEmbedder(inner, cache_file)

    return inner
