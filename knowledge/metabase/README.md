# Metabase Cards Inventory

**Database:** `knowledge/metabase/cards.db`
**Last synced:** 2026-01-03 21:33
**Total cards:** 334
**Dashboards:** 16

## Database Schema

```sql
CREATE TABLE cards (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    collection_id INTEGER,
    dashboard_id INTEGER,
    topic TEXT,
    sql_query TEXT,
    tables_referenced TEXT,  -- JSON array
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE dashboards (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,  -- From virtual text cards
    topic TEXT,
    pilotage_url TEXT,
    collection_id INTEGER
);
```

## Topics

| Topic | Cards | Description |
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

| ID | Name | Topic | Pilotage URL |
|----|------|-------|--------------|
| 52 | Candidatures - Zoom sur les prescripteurs | etp-effectifs |  |
| 54 | Offre - Zoom sur les employeurs | etp-effectifs |  |
| 116 | Candidatures - Traitement et résultats des ca... | candidatures |  |
| 136 | Candidatures - L'accompagnement des prescript... | demographie |  |
| 150 | Offre - Postes en tension | employeurs |  |
| 185 | SIAE - Analyse des candidatures reçues et de ... | candidatures |  |
| 216 | Publics - Représentation des femmes dans les ... | esat |  |
| 217 | Pilotage dispositif - Suivi des PASS IAE | candidatures |  |
| 265 | DDETS/DREETS- Suivi du contrôle a posteriori | controles | [link](/tableaux-de-bord/auto-prescription/) |
| 267 | DDETS/DREETS - Les auto-prescription et suivi... | auto-prescription | [link](/tableaux-de-bord/auto-prescription/) |
| 287 | Pilotage dispositif - Conventionnements IAE | prescripteurs | [link](/tableaux-de-bord/zoom-prescripteurs/) |
| 325 | Pilotage dispositif - Analyses autour des con... | etp-effectifs |  |
| 336 | Pilotage dispositif - Demandes de prolongatio... | prolongations | [link](/tableaux-de-bord/suivi-demandes-prolongation/) |
| 337 | Candidatures - Bilan annuel des candidatures ... | candidatures | [link](/tableaux-de-bord/etat-suivi-candidatures/) |
| 408 | Publics - Candidats dans la file active IAE d... | file-active | [link](/tableaux-de-bord/candidat-file-active-IAE/) |
| 471 | ESAT - Tableau de bord 2024 | esat | [link](/tableaux-de-bord/zoom-esat-2025/) |

## Querying the Database

```python
from skills.metabase_query.scripts.cards_db import load_cards_db

db = load_cards_db()

# Cards
cards = db.search("file active")  # Full-text search
cards = db.by_topic("candidatures")  # Filter by topic
cards = db.by_dashboard(408)  # Cards in a dashboard
card = db.get(7004)  # Get by ID

# Dashboards
dash = db.get_dashboard(408)
dashboards = db.dashboards_by_topic("esat")
```

## Key Tables Referenced

| Table | Cards |
|-------|-------|
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
