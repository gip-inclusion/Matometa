# Metabase Cards Inventory

**Database:** `knowledge/metabase/cards.db`
**Last synced:** 2026-01-03 21:23
**Total cards:** 334

## Database Schema

```sql
CREATE TABLE cards (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    collection_id INTEGER,
    dashboard_id INTEGER,  -- Extracted from [XXX] prefix in name
    topic TEXT,
    sql_query TEXT,
    tables_referenced TEXT,  -- JSON array
    created_at TEXT,
    updated_at TEXT
);

CREATE VIRTUAL TABLE cards_fts USING fts5(
    name, description, sql_query
);
```

## Topics

| Topic | Count | Description |
|-------|-------|-------------|
| file-active | 11 | Candidats dans la file active (30+ days waiting) |
| postes-tension | 14 | Postes en tension (difficult to recruit) |
| demographie | 35 | Age, gender, geographic breakdowns |
| candidatures | 49 | Candidature metrics, states, flows |
| employeurs | 14 | SIAE and employer information |
| prescripteurs | 23 | Prescripteur and orientation data |
| auto-prescription | 17 | Auto-prescription metrics |
| controles | 6 | Control and compliance |
| prolongations | 21 | PASS extensions |
| etp-effectifs | 17 | ETP and workforce metrics |
| esat | 116 | ESAT-specific data |
| generalites-iae | 10 | General IAE statistics |
| autre | 1 | Uncategorized |

## Dashboards

| Dashboard ID | Cards |
|--------------|-------|
| 471 | 54 |
| 216 | 33 |
| 336 | 21 |
| 408 | 21 |
| 116 | 16 |
| 287 | 16 |
| 267 | 15 |
| 136 | 8 |
| 150 | 8 |
| 265 | 6 |
| 337 | 5 |
| 52 | 4 |
| 217 | 4 |
| 325 | 2 |
| 54 | 1 |

## Querying the Database

```python
from skills.metabase_query.scripts.cards_db import load_cards_db

db = load_cards_db()
cards = db.search("file active")  # Full-text search
cards = db.by_topic("candidatures")  # Filter by topic
cards = db.by_dashboard(408)  # Cards in a dashboard
cards = db.by_table("candidats")  # Cards using a table
card = db.get(7004)  # Get by ID
```

## Key Tables Referenced

| Table | Cards Using It |
|-------|----------------|
| `public` | 312 |
| `candidatures_echelle_locale` | 72 |
| `Esat` | 55 |
| `ESAT` | 42 |
| `suivi_demandes_prolongations` | 21 |
| `candidatures_candidats_recherche_active` | 19 |
| `candidats_recherche_active` | 19 |
| `esat` | 18 |
| `questionnaire_2025` | 18 |
| `structures` | 13 |
| `fiches_deposte_en_tension_recrutement` | 13 |
| `suivi_realisation_convention_mensuelle` | 12 |
| `organisations` | 10 |
| `suivi_auto_prescription` | 9 |
| `taux_transformation_prescripteurs` | 9 |
