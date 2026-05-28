# The Secretary

A research-journal agent for Claude Code. Tracks tasks, experiment results, conclusions, and daily activity across sessions — with a persistent memory engine that surfaces relevant past context automatically.

## What it does

| Need | How it's handled |
|------|------------------|
| Track tasks and priorities | `todo.md` — living document, read/write |
| Log every request | `log.md` — append-only, one line per event |
| Record experiment results | `measures.md` — grouped by experiment |
| Store conclusions | `results.md` — append-only insights |
| Daily activity | `daily/YYYY-MM/YYYY-MM-DD.md` |
| Remember past context | Memory engine — embedding similarity search |

## Setup

### 1. Configure the secretary

Open Claude Code in this repo and run `/secretary`. On first run it asks:

1. Work-state directory (where `log.md`, `todo.md`, etc. will live)
2. Team lead name (for coordination checks — type `none` to skip)
3. Optional: path to Google Drive journal directory
4. Optional: path to Google Drive metrics directory

### 2. Install the memory engine (optional but recommended)

The memory engine indexes your work files and injects relevant past context at session start and per-prompt.

```sh
# Choose one embedder (or skip both for zero-dep TF-IDF fallback)
pip install voyageai        # recommended — set VOYAGE_API_KEY
# pip install openai        # alternative  — set OPENAI_API_KEY
```

No embedder installed = TF-IDF fallback activates automatically. Quality is lower but it always works with no API keys.

### 3. Set environment variables

```sh
export MEMORY_WORK_DIR=/path/to/your/work-state-dir
export VOYAGE_API_KEY=...   # or OPENAI_API_KEY
```

Add these to your shell profile or Claude Code's env config.

## Memory engine

Located in `.secretary/memory/`. Runs automatically via Claude Code hooks — no manual steps needed after setup.

### How it works

```
file write       →  post_write_index.py  →  chunk → embed → SQLite
session start    →  session_start.py     →  query active tasks → inject top-5
user prompt      →  prompt_memory.py     →  query prompt text  → inject top-3
```

### Scoring formula

Each candidate memory is ranked by a composite score:

```
score = 0.70 × cosine_similarity(query, chunk)
      + 0.15 × exp(-age_days × ln2 / 180)    ← 6-month half-life
      + 0.10 × importance / max_importance
      + 0.05 × log(1 + access_count) / log(1 + max_access)
```

Threshold: **0.42** — below this, nothing is injected (avoids hallucination from weak matches).

### Memory types

| Type | Source files | Importance |
|------|-------------|------------|
| `semantic` | `todo.md`, `results.md` | 1.3 – 1.6 (durable signal) |
| `episodic` | `log.md`, `measures.md`, `daily/` | 0.8 – 1.2 |

### Embedder priority

1. **Voyage AI** (`voyage-3-lite`, 512-dim) — if `VOYAGE_API_KEY` is set and `voyageai` is installed
2. **OpenAI** (`text-embedding-3-small`, 1536-dim) — if `OPENAI_API_KEY` is set and `openai` is installed
3. **TF-IDF** (256-dim, local) — zero-dep fallback, always available

Embeddings are cached on disk by `sha256(content)` — unchanged chunks are never re-embedded.

### CLI commands

```sh
# Run from the repo root (MEMORY_WORK_DIR must be set)
python .secretary/memory.py stats
python .secretary/memory.py index --work-dir /path/to/workdir
python .secretary/memory.py query --text "bert baseline accuracy"
python .secretary/memory.py rebuild --work-dir /path/to/workdir
```

### Tuning via environment variables

| Variable | Default | Effect |
|----------|---------|--------|
| `MEMORY_K` | `5` | Results returned per query |
| `MEMORY_THRESHOLD` | `0.42` | Minimum score to inject |
| `MEMORY_MAX_TOKENS` | `500` | Context budget per injection |
| `MEMORY_HALF_LIFE_DAYS` | `180` | Temporal decay half-life |
| `MEMORY_DB_PATH` | `<work_dir>/.secretary/memory.db` | SQLite DB location |
| `MEMORY_LOG_LEVEL` | `WARNING` | Python logging level |

## File layout

```
the_secretary/
├── .claude/
│   ├── commands/
│   │   └── secretary.md          ← /secretary slash command
│   ├── hooks/
│   │   ├── session_start.py      ← SessionStart: load memory context
│   │   ├── prompt_memory.py      ← UserPromptSubmit: per-prompt retrieval
│   │   └── post_write_index.py   ← PostToolUse: re-index after writes
│   └── settings.json             ← wires the hooks
└── .secretary/
    ├── memory.py                 ← CLI entry point
    ├── requirements.txt
    └── memory/
        ├── store.py              ← SQLite storage + memory_links
        ├── embed.py              ← Voyage / OpenAI / TF-IDF + cache
        ├── chunker.py            ← per-file chunking strategies
        ├── retriever.py          ← composite scoring + retrieval
        ├── indexer.py            ← incremental indexer
        └── cli.py                ← argparse entry point
```

## Requirements

- Python 3.9+
- Claude Code
- `voyageai` or `openai` (optional — TF-IDF fallback requires neither)
