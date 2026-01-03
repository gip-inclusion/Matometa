---
name: metabase-sync
description: Sync Metabase cards inventory to SQLite database
---

# Metabase Sync Skill

Synchronize Metabase cards from specified collections to a local SQLite database for fast querying.

## Usage

```bash
# Full sync with AI categorization
python -m skills.metabase_sync.scripts.sync_inventory

# Quick sync without AI categorization
python -m skills.metabase_sync.scripts.sync_inventory --skip-categorize

# Sync specific collections
python -m skills.metabase_sync.scripts.sync_inventory --collections 453 452

# Clear and resync
python -m skills.metabase_sync.scripts.sync_inventory --clear
```

## What it does

1. **Fetches card metadata** from Metabase collections
2. **Extracts SQL queries** (native SQL or compiled from GUI queries)
3. **AI categorization** (optional) - uses Claude to assign topic categories
4. **Writes to SQLite** at `knowledge/metabase/cards.db`
5. **Generates README** at `knowledge/metabase/README.md`

## Output

- **SQLite database** with full-text search capabilities
- **README.md** with schema documentation and topic summary

## Prerequisites

- `METABASE_BASE_URL` and `METABASE_API_KEY` in `.env`
- `ANTHROPIC_API_KEY` in `.env` (for AI categorization)

## Topics

Cards are categorized into these topics:

| Topic | Description |
|-------|-------------|
| file-active | Candidates waiting 30+ days |
| postes-tension | Hard to fill positions |
| candidatures | Application flows |
| demographie | Age/gender breakdowns |
| employeurs | SIAE/employer data |
| prescripteurs | Prescriber data |
| auto-prescription | Auto-prescription metrics |
| controles | Compliance data |
| prolongations | PASS extensions |
| etp-effectifs | Workforce metrics |
| esat | ESAT-specific |
| generalites-iae | General IAE stats |
| autre | Uncategorized |
