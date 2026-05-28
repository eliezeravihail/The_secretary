# The Secretary

A Claude Code slash command (`/secretary`) that acts as your personal work journal — tracking tasks, logging daily activity, and keeping you oriented across sessions.

---

## What it does

- Maintains a **two-level task list** (`todo.md`): main tasks → subtasks, with priorities and optional deadlines
- Keeps a **daily log** (`daily/YYYY-MM/YYYY-MM-DD.md`) with full activity detail
- Logs **conclusions and insights** (`results.md`)
- Answers queries: "what did I do this week?", "what's urgent?", "what's stuck?"
- Detects **drift** when new input doesn't belong to any active task
- Integrates with **Slack** (reading and summarising conversations)
- Optionally tracks **experiment results** (`measures.md`) — stripped at setup if not needed
- Optionally enforces **team-lead coordination** before executing any new task — stripped at setup if not needed

---

## Requirements

- [Claude Code](https://claude.ai/code) (CLI, desktop app, or web)
- No Python dependencies, no server, no API keys required for core functionality

---

## Installation

### Option A — Global (available in every project)

```bash
git clone https://github.com/eliezeravihail/the_secretary.git
cp the_secretary/.claude/commands/secretary.md ~/.claude/commands/secretary.md
```

The command becomes available as `/secretary` in any Claude Code session.

### Option B — Per-project

```bash
git clone https://github.com/eliezeravihail/the_secretary.git
cp the_secretary/.claude/commands/secretary.md <your-project>/.claude/commands/secretary.md
```

The command is available only when Claude Code runs inside `<your-project>`.

---

## First run

Type `/secretary` in Claude Code. On the first run it will ask three questions one at a time:

| # | Question | Notes |
|---|----------|-------|
| 1 | Which directory should hold the work state? | Full path; will be created if it doesn't exist |
| 2 | Who is the team lead / coordinator? | Type `none` to disable the coordination workflow entirely |
| 3 | Do you track experiments / metrics? | Type `no` to remove the experiment module entirely |

After answering, Secretary will:
- Create the work-state directory and `daily/YYYY-MM/` for the current month
- Create empty `todo.md` and `results.md` (and `measures.md` if experiments = yes)
- Edit its own command file to save your config and strip any disabled modules
- Present the opening questions to seed your initial task list

From that point on, `/secretary` goes straight to work — no re-initialization.

---

## Optional modules

Two sections of the command file are gated behind init-time questions. If you answer `none` / `no`, the corresponding lines are permanently deleted from the file. You can also remove them manually at any time.

### Team-lead coordination

When enabled, every new **task** (main task or subtask) triggers a coordination check — Secretary asks whether the task was aligned with the team lead before allowing execution.

To remove it after the fact, delete every line between `<!-- TEAM-LEAD-ONLY START -->` and `<!-- TEAM-LEAD-ONLY END -->` (inclusive) in `secretary.md`.

### Experiment tracking

When enabled, adds `measures.md` (grouped experiment results with Reported / Context / Meaning fields), the "Logging a run result" workflow, and attachment storage under `measures/<experiment-name>/`.

To remove it after the fact, delete every line between `<!-- EXPERIMENT-MODULE START -->` and `<!-- EXPERIMENT-MODULE END -->` (inclusive) in `secretary.md`.

---

## File structure created by Secretary

```
<work-state-dir>/
├── todo.md                        # main tasks + subtasks + open questions
├── results.md                     # conclusions and insights (append-only)
├── measures.md                    # experiment results (if module enabled)
├── measures/
│   └── <experiment-name>/         # attached artifacts (images, charts)
└── daily/
    └── YYYY-MM/
        └── YYYY-MM-DD.md          # full daily log
```

---

## Updating

1. Pull the latest version:
   ```bash
   cd the_secretary && git pull
   ```
   Or download the repo as a ZIP and extract it.

2. Open Claude Code and type:
   ```
   /secretary update
   ```
   Secretary will ask where the new file is, then handle everything automatically — preserving your config and re-stripping any modules you had disabled.

---

## Daily log — lifecycle and timing

Every workday gets a file at `daily/YYYY-MM/YYYY-MM-DD.md`. Secretary manages it automatically:

### When is it created?

At **session open** — the first thing Secretary does (after reading `todo.md`) is check whether today's log file exists.

- **New day (file missing):**
  1. Checks the most recent previous log. If it has no `## Day summary` section, writes one now (appended without re-reading the file).
  2. Creates the month directory `daily/YYYY-MM/` if it doesn't exist yet.
  3. Creates today's file with just the date header — ready to receive entries.
- **Same day (file exists):** continues appending to it as usual.

### What is written to it and when?

| Event | What is appended |
|-------|------------------|
| Any activity report from the user | A `### [context]` block with What / Data / Observations / Decisions |
| Routine request (no todo change) | A one-line activity entry |
| Session open on a new day | Day summary block appended to *yesterday's* file |

Secretary appends **only** — it never reads the daily log before writing to it.

### Where is the day summary written?

To **yesterday's file**, at the start of the next workday's session open. There is no explicit "session close" step — the summary is triggered by the next session opening on a new date.

If multiple days pass without a session (e.g. over a weekend), the summary is written for the most recent previous log that is missing one, the first time a new session opens.

---

## Key workflows at a glance

| Trigger | What Secretary does |
|---------|---------------------|
| New task from user | Asks which main task it belongs to (or creates a new main task); runs coordination check |
| Status update / close | Reads `todo.md`, applies the change, writes back |
| Run result reported | Matches to an experiment in `measures.md`, appends entry with Reported/Context/Meaning |
| Conclusion / insight | Appends to `results.md` |
| "What did I do this week?" | Summarises by main task + subtask status; reads daily logs for detail |
| "What's urgent?" | Shows tasks by time-to-deadline in three bands |
| "What's stuck?" | Lists blocked subtasks, stale main tasks, overdue deadlines, open questions |
| External input (Slack thread, screenshot) | Summarises to daily log; alerts if new activity doesn't match any active task |
| `/secretary update` | Reads new file path, preserves config, re-strips disabled modules |

---

## Boundaries

Secretary will not do the following:
- Write to Slack or take any other external action without an explicit request
- Delete or edit historical log entries (this is always forbidden)
- Fabricate data — "not recorded" is a valid answer
