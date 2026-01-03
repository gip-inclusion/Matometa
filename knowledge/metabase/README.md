# Metabase Cards Inventory

**Database:** `knowledge/metabase/cards.db`
**Last synced:** 2026-01-03 21:11
**Total cards:** 334

## Database Schema

```sql
CREATE TABLE cards (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    collection_id INTEGER,
    topic TEXT,
    sql_query TEXT,
    tables_referenced TEXT,  -- JSON array
    created_at TEXT,
    updated_at TEXT
);

CREATE VIRTUAL TABLE cards_fts USING fts5(
    name, description, sql_query
);

CREATE TABLE dashboards (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    pilotage_url TEXT,
    collection_id INTEGER
);

CREATE TABLE dashboard_cards (
    dashboard_id INTEGER,
    card_id INTEGER,
    position INTEGER,
    tab_name TEXT
);
```

## Topics

| Topic | Count | Description |
|-------|-------|-------------|
| autre | 334 | Uncategorized |

## Querying the Database

```python
from skills.metabase_query.scripts.cards_db import load_cards_db

db = load_cards_db()
cards = db.search("file active")  # Full-text search
cards = db.by_topic("candidatures")  # Filter by topic
cards = db.by_table("candidats")  # Cards using a table
card = db.get(4413)  # Get by ID
```

## Key Tables Referenced

| Table | Cards Using It |
|-------|----------------|
| `candidatures_echelle_locale` | 72 |
| `Esat` | 55 |
| `ESAT` | 42 |
| `suivi_demandes_prolongations` | 21 |
| `candidats_recherche_active` | 19 |
| `candidatures_candidats_recherche_active` | 19 |
| `questionnaire_2025` | 18 |
| `structures` | 13 |
| `fiches_deposte_en_tension_recrutement` | 13 |
| `suivi_realisation_convention_mensuelle` | 12 |
| `organisations` | 10 |
| `suivi_auto_prescription` | 9 |
| `taux_transformation_prescripteurs` | 9 |
| `fiches_de_poste` | 7 |
| `candidats_auto_prescription` | 6 |
