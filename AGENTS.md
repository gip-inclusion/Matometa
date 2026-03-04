# Matometa

A suite of tools to leverage the Matomo and Metabase APIs for web analytics.

## Quick Start

**Query APIs using lib.query (all queries are logged):**
```python
from lib.query import execute_query, execute_metabase_query, execute_matomo_query, CallerType

# Metabase SQL query
result = execute_metabase_query(
    instance="stats",
    caller=CallerType.AGENT,
    sql="SELECT 1",
    database_id=2,
)
print(result.data)  # {"columns": [...], "rows": [...], "row_count": N}

# Matomo API query
result = execute_matomo_query(
    instance="inclusion",
    caller=CallerType.AGENT,
    method="VisitsSummary.get",
    params={"idSite": 117, "period": "month", "date": "2025-12-01"},
)
print(result.data)  # API response dict

# Generic query (auto-detects source)
result = execute_query(
    source="metabase",
    instance="datalake",
    caller=CallerType.AGENT,
    sql="SELECT * FROM table LIMIT 10",
    database_id=2,
)
```

**Key paths:**
| Path | Purpose |
|------|---------|
| `./config/sources.yaml` | Data source configuration (URLs, instances) |
| `./knowledge/sites/` | Site-specific context — read before querying |
| `./knowledge/stats/` | Stats Metabase instance (IAE dashboards) |
| `./knowledge/datalake/` | Datalake Metabase instance |
| `./knowledge/dora/` | Dora Metabase instance (services directory) |
| `./knowledge/matomo/README.md` | Matomo API reference |
| `./reports/` | Output reports |
| `./skills/` | Reusable agent skills |

**Data directory** (`DATA_DIR`, default `./data/`):
| Path | Purpose |
|------|---------|
| `$DATA_DIR/scripts/` | One-off query scripts (produced by agent) |
| `$DATA_DIR/interactive/` | User-downloadable files (CSV exports, dashboards) |
| `$DATA_DIR/matometa.db` | SQLite database (conversations, reports) |
| `$DATA_DIR/notion_research.db` | Research corpus (interviews, verbatims, observations) |

**Sync commands:**
```bash
python -m skills.sync_metabase.scripts.sync_inventory --instance stats
python -m skills.sync_metabase.scripts.sync_inventory --instance datalake
python -m skills.sync_metabase.scripts.sync_inventory --all
```

## Language

French by default. Always use "vous", never "tu", even if addressed informally.

## Available Commands

| Command | Purpose |
|---------|---------|
| `python <script>` | Run Python scripts (in container: `/app`) |
| `curl` | API calls (but prefer Python clients) |
| `jq` | Parse JSON |
| `sqlite3` | Database queries |

**DO NOT use heredocs.** Write scripts to files instead.

## Mermaid Visualizations

Use Mermaid for charts. Don't use pie charts, use XY / bar graphs instead.

**Rules:**
- Quote all labels: `"Label text"`
- ONLY in mermaid [axis labels], don't use accents (use `e` not `e`)
- No `<br/>` tags or slashes
- No ASCII art or inline HTML
- Use DSFR colors: `#006ADC` (blue), `#000638` (navy), `#ADB6FF` (periwinkle), `#E57200` (orange), `#FFA347` (light orange)

## Container Environment (Web Deployment)

When running in Docker (web UI mode):
- **Working directory:** `/app`
- **Data directory:** `/app/data/` (DATA_DIR)
- **Python:** `python` (no venv needed, deps pre-installed)
- **Credentials:** `/app/.env` (auto-loaded by Python clients)
- **Skills:** `/app/skills/<name>/skill.md`
- **Scripts:** Write to `/app/data/scripts/` for one-off query scripts
- **Temp files:** Write to `/tmp/` for scratch work
- **Public files:** Write to `/app/data/interactive/` for user-downloadable files

### Container File Persistence

Only bind-mounted directories persist across container restarts:

| Path | Writable | Persists |
|------|----------|----------|
| `/app/data/` | yes | yes |
| `/app/knowledge/` | no (read-only mount) | yes |
| `/app/skills/` | no (read-only mount) | yes |
| `/app/web/`, `/app/lib/` | overlay only | **no** |
| `/tmp/` | yes | **no** |

**NEVER create or modify files under `/app/web/` or `/app/lib/`.** These directories
are baked into the Docker image. The overlay filesystem lets writes appear to succeed,
but everything is lost on the next restart or deploy.

### Downloadable Files

Files in `/app/data/interactive/` are publicly served at `/interactive/`.

**IMPORTANT: Always use relative URLs** (starting with `/`) when linking to files
or interactive apps. Never invent or guess absolute URLs.

### Presenting Options

When you want the user to choose between actions, use an options code block.
Buttons are rendered in the web UI; falls back to a code block elsewhere.

~~~markdown
```options
Voir le trafic mensuel
Analyser les conversions | Analyser les conversions sur les Emplois en decembre 2025
Comparer deux mois | Comparer le trafic de decembre 2025 avec novembre 2025
```
~~~

- Text before `|` = short button label
- Text after `|` = full request (pre-filled in input, user can edit)
- If no `|`, the label is used as-is
- Last option is the primary/recommended action
