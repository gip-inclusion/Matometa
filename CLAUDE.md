# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Read AGENTS.md for the agent system prompt (domain context, query workflow, behavioral guidelines). If AGENTS.local.md exists, read it too (local overrides).

## Commands

```bash
# Local development
make dev              # Flask on http://127.0.0.1:5000 (cli backend)
make dev-ollama       # Flask with Ollama backend

# Docker
make up               # Production (cli backend, port 5002)
make up-ollama        # Production with Ollama
make down             # Stop all

# Tests
make test             # Run all tests
.venv/bin/pytest tests/test_matomo.py           # Single test file
.venv/bin/pytest tests/test_matomo.py -k "test_name"  # Single test
.venv/bin/pytest -m integration                 # Integration tests (need .env)

# Sync reference data
python -m skills.sync_metabase.scripts.sync_inventory --instance stats
python -m skills.sync_sites.scripts.sync
```

## Architecture

**Flask web app** serving a conversational AI assistant that queries Matomo (web analytics) and Metabase (business data) APIs.

```
User → Flask routes (web/routes/) → Agent backend (web/agents/) → Claude CLI or Ollama
                                         ↓
                                   lib/query.py → lib/_matomo.py / lib/_metabase.py
                                         ↓
                                   query_log (audit)
```

### Key layers

- **`web/`** — Flask app with Jinja2 templates and SSE streaming. Routes are Blueprints in `web/routes/`. Agent backends in `web/agents/` implement a pluggable interface (`base.py`); selected by `AGENT_BACKEND` config.
- **`lib/`** — Shared Python libraries. `lib/query.py` is the unified query interface; all Matomo/Metabase calls go through `execute_matomo_query()` / `execute_metabase_query()` for automatic logging and error handling. `CallerType.AGENT` vs `CallerType.APP` distinguishes who made the call.
- **`skills/`** — Reusable agent capabilities. Each has `SKILL.md` (instructions) + optional `scripts/` (Python). Registered via `.claude/skills` symlink.
- **`knowledge/`** — Markdown knowledge base read by the agent. `sites/` has per-website docs, `matomo/` and `metabase/` have API references.
- **`config/sources.yaml`** — Data source registry (Matomo/Metabase instance URLs, credentials via env vars).

### Database

SQLite locally (`data/matometa.db`), PostgreSQL in production (auto-detected from `DATABASE_URL`). `web/database.py` abstracts both behind `ConnectionWrapper`. Tables: conversations, messages, reports, query_log.

### Storage

Interactive files served at `/interactive/`. Local filesystem by default (`data/interactive/`), S3-compatible in production (configured via `S3_*` env vars). See `web/s3.py` and `web/storage.py`.

## Testing

Tests in `tests/` use pytest. The `app` fixture creates a temp SQLite database; `client` gives a Flask test client. Integration tests (`@pytest.mark.integration`) hit real APIs and need `.env` credentials. Matomo test params are configurable via env vars (`MATOMO_TEST_SITE_ID`, `MATOMO_TEST_DATE`, etc.).

## Configuration

All config in `web/config.py`, loaded from `.env`. Key variables:
- `AGENT_BACKEND` — `cli` (Claude Code CLI) or `cli-ollama`
- `DATABASE_URL` — PostgreSQL connection string (omit for SQLite)
- `MATOMO_API_KEY`, `METABASE_*_API_KEY` — API credentials
- `ALLOWED_TOOLS` — Tool whitelist for Claude CLI agent (security boundary is the container)

## Conventions

- Language: French in user-facing content (AGENTS.md, knowledge files, reports). Code and comments in English.
- All API queries must go through `lib.query` — never call Matomo/Metabase directly.
- Reports are stored in the database via the `save_report` skill, not as files in `reports/`.
- Frontend uses DSFR (French government design system) CSS. No React/Vue — vanilla JS + Jinja2 templates.
- Agent skills follow the pattern: `skills/<name>/SKILL.md` + `skills/<name>/scripts/*.py`.
