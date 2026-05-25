"""
CLI entry point for shell hooks.

Commands: index, query, rebuild, stats

Exit codes:
  0  success
  1  error
  2  query returned no results (hook skips injection)

Environment variables:
  MEMORY_DB_PATH, MEMORY_WORK_DIR, VOYAGE_API_KEY, OPENAI_API_KEY,
  MEMORY_K, MEMORY_THRESHOLD, MEMORY_MAX_TOKENS, MEMORY_HALF_LIFE_DAYS
"""

from __future__ import annotations

import argparse
import json as _json_mod
import logging
import os
import sys
from pathlib import Path


def _resolve_paths() -> tuple[Path, Path]:
    work_dir = Path(os.environ.get("MEMORY_WORK_DIR", ".")).resolve()
    db_path = Path(
        os.environ.get("MEMORY_DB_PATH", str(work_dir / ".secretary" / "memory.db"))
    ).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return work_dir, db_path


def _build_engine(db_path: Path):
    from .embed import get_embedder
    from .indexer import Indexer
    from .retriever import Retriever, RetrievalConfig
    from .store import MemoryStore

    store = MemoryStore(db_path)
    cache_dir = db_path.parent / "embed_cache"
    embedder = get_embedder(cache_dir=cache_dir)
    indexer = Indexer(store, embedder)
    retriever = Retriever(store, embedder, RetrievalConfig.from_env())
    return store, embedder, indexer, retriever


def cmd_index(args: argparse.Namespace) -> int:
    work_dir, db_path = _resolve_paths()
    if args.work_dir:
        work_dir = Path(args.work_dir).resolve()
    store, _, indexer, _ = _build_engine(db_path)
    try:
        if args.file:
            reports = [indexer.index_file(Path(args.file).resolve())]
        else:
            reports = indexer.index_all(work_dir)
        total_indexed = sum(r.indexed for r in reports)
        total_skipped = sum(r.skipped for r in reports)
        total_errors = sum(r.errors for r in reports)
        print(
            f"[memory:index] indexed={total_indexed} skipped={total_skipped} errors={total_errors}",
            file=sys.stderr,
        )
        return 0 if total_errors == 0 else 1
    finally:
        store.close()


def cmd_query(args: argparse.Namespace) -> int:
    _, db_path = _resolve_paths()
    store, _, _, retriever = _build_engine(db_path)

    if args.types or args.k:
        from .retriever import RetrievalConfig, Retriever
        from .embed import get_embedder
        cfg = RetrievalConfig.from_env()
        if args.k:
            cfg.k = args.k
        if args.types:
            cfg.memory_types = args.types.split(",")
        cache_dir = db_path.parent / "embed_cache"
        retriever = Retriever(store, get_embedder(cache_dir=cache_dir), cfg)

    try:
        memories = retriever.query(args.text)
        if not memories:
            return 2
        if args.json:
            out = [
                {
                    "id": m.id,
                    "content": m.content,
                    "score": round(m.score, 4),
                    "source": m.source,
                    "tags": m.tags,
                    "memory_type": m.memory_type,
                }
                for m in memories
            ]
            print(_json_mod.dumps(out, ensure_ascii=False))
        else:
            print(retriever.format_for_context(memories))
        return 0
    finally:
        store.close()


def cmd_rebuild(args: argparse.Namespace) -> int:
    work_dir, db_path = _resolve_paths()
    if args.work_dir:
        work_dir = Path(args.work_dir).resolve()
    store, _, indexer, _ = _build_engine(db_path)
    try:
        reports = indexer.rebuild(work_dir)
        total = sum(r.indexed for r in reports)
        print(f"[memory:rebuild] complete. indexed={total}", file=sys.stderr)
        return 0
    finally:
        store.close()


def cmd_stats(args: argparse.Namespace) -> int:
    _, db_path = _resolve_paths()
    store, _, _, _ = _build_engine(db_path)
    try:
        s = store.stats()
        print(
            f"[memory:stats] total={s['total']} indexed={s['indexed']} "
            f"semantic={s['semantic']} episodic={s['episodic']}"
        )
        return 0
    finally:
        store.close()


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("MEMORY_LOG_LEVEL", "WARNING"),
        format="[memory] %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    parser = argparse.ArgumentParser(prog="memory.py")
    sub = parser.add_subparsers(dest="command")

    p_idx = sub.add_parser("index")
    p_idx.add_argument("--file")
    p_idx.add_argument("--all", action="store_true")
    p_idx.add_argument("--work-dir")

    p_qry = sub.add_parser("query")
    p_qry.add_argument("--text", required=True)
    p_qry.add_argument("--k", type=int)
    p_qry.add_argument("--types")
    p_qry.add_argument("--json", action="store_true")

    p_reb = sub.add_parser("rebuild")
    p_reb.add_argument("--work-dir")

    sub.add_parser("stats")

    args = parser.parse_args()
    dispatch = {"index": cmd_index, "query": cmd_query, "rebuild": cmd_rebuild, "stats": cmd_stats}
    handler = dispatch.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)
    sys.exit(handler(args))


if __name__ == "__main__":
    main()
