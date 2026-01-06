---
name: metabase_query
description: Query Metabase for IAE employment data (project)
---

# Metabase Query Skill

Query the Metabase instance at stats.inclusion.beta.gouv.fr for IAE (Insertion par l'Activité Économique) employment data.

## Usage

```python
from skills.metabase_query.scripts.metabase import MetabaseAPI

api = MetabaseAPI()

# Execute raw SQL
result = api.execute_sql("""
    SELECT COUNT(*) as total
    FROM candidatures_recues_par_fiche_de_poste
    WHERE état_candidature = 'Candidature acceptée'
""")
print(result.to_markdown())

# Execute a saved card/question
result = api.execute_card(4413)  # File active count
print(result.to_dicts())

# Search for cards
cards = api.search_cards("file active")
for card in cards:
    print(f"{card['id']}: {card['name']}")

# Get card SQL
sql = api.get_card_sql(4413)
print(sql)
```

## Available Methods

- `execute_sql(sql)` - Run raw SQL query
- `execute_card(card_id)` - Run a saved question
- `get_card(card_id)` - Get card metadata
- `get_card_sql(card_id)` - Get SQL for any card (native or compiled)
- `list_cards(collection_id)` - List cards in a collection
- `search_cards(query)` - Search cards by name/description
- `get_dashboard(dashboard_id)` - Get dashboard with its cards
- `list_dashboards(collection_id)` - List dashboards in a collection

## Cards Database

See `knowledge/metabase/README.md` for the cards inventory database.

```python
from skills.metabase_query.scripts.cards_db import load_cards_db

db = load_cards_db()
cards = db.search("candidature")  # Full-text search
cards = db.by_topic("file-active")  # Filter by topic
```
