---
name: metabase_query
description: Query Metabase for IAE employment data (project)
---

# Metabase Query Skill

Query the Metabase instance at stats.inclusion.beta.gouv.fr for IAE (Insertion par l'Activité Économique) employment data.

## Documentation

Before querying, read the relevant documentation:
- `knowledge/metabase/` — Tables, schemas, data dictionary
- `knowledge/stats/dashboards/` — Dashboard cards with IDs and SQL
- `knowledge/stats/cards/` — Cards grouped by topic

## Usage

```python
from skills.metabase_query.scripts.metabase import MetabaseAPI

api = MetabaseAPI()

# Execute a saved card/question (preferred)
result = api.execute_card(7073)  # Find card IDs in knowledge/stats/dashboards/
print(result.to_markdown())

# Execute raw SQL
result = api.execute_sql("""
    SELECT COUNT(*) as total
    FROM candidatures
    WHERE état = 'Candidature acceptée'
""")
print(result.to_dicts())

# Get card SQL to understand/modify it
sql = api.get_card_sql(7073)
print(sql)
```

## Available Methods

- `execute_card(card_id)` — Run a saved question (preferred)
- `execute_sql(sql)` — Run raw SQL query
- `get_card(card_id)` — Get card metadata
- `get_card_sql(card_id)` — Get SQL for any card (native or compiled)
- `search_cards(query)` — Search cards by name/description
