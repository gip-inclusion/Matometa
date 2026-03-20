# Notion API

Toutes les requêtes Notion du projet utilisent `urllib.request` directement (pas de SDK).

## Configuration

| Variable | Requis pour | Exemple |
|----------|-------------|---------|
| `NOTION_TOKEN` | Tout | `secret_abc...` |
| `NOTION_REPORTS_DB` | Publish | UUID de la base "Rapports publics" |
| `NOTION_WISHLIST_DB` | Wishlist | UUID de la base wishlist |

Les database IDs du corpus sont codés en dur dans `scripts/refresh_research.py`.

## Requêtes API

- Base URL : `https://api.notion.com/v1/`
- Version : `Notion-Version: 2022-06-28`
- Auth : `Authorization: Bearer {NOTION_TOKEN}`
- Content-Type : `application/json`
- Timeout : 30s (publish, corpus), 10s (wishlist)

### Endpoints utilisés

| Endpoint | Méthode | Utilisé par |
|----------|---------|-------------|
| `/pages` | POST | Publish, Wishlist (créer une page) |
| `/blocks/{page_id}/children` | PATCH | Publish (ajouter des blocs de contenu) |
| `/databases/{db_id}/query` | POST | Corpus (lister les pages d'une base) |
| `/blocks/{block_id}/children` | GET | Corpus (récupérer le contenu des pages) |

### Pagination

```python
payload = {"page_size": 100}
if cursor:
    payload["start_cursor"] = cursor
# ...
if not data.get("has_more"):
    break
cursor = data.get("next_cursor")
```

### Rate limiting (corpus)

`REQUEST_INTERVAL = 0.34` (~3 req/s). Retry automatique sur HTTP 429 avec `Retry-After`.

## Fonctionnalités

### 1. Publish — Publier des rapports

**Fichier** : `web/notion.py`
**Route** : `POST /api/reports/{id}/publish-notion`

Crée une page dans la base "Rapports publics" et y ajoute le contenu markdown converti en blocs Notion.

Propriétés créées :
- `Titre` (title)
- `Date de publication` (date, optionnel)
- `Produits concernés` (multi-select, optionnel)
- `Requête initiale` (rich_text, optionnel)

Blocs supportés : headings, paragraphs, code, tables, listes, dividers.
Inline : **bold**, *italic*, `code`, [liens](url).

### 2. Wishlist — Demandes de fonctionnalités

**Fichier** : `skills/wishlist/scripts/wishlist.py`

Crée une page dans la base wishlist. Stockage local en parallèle dans `data/matometa.db` table `wishlist`.

Propriétés :
- `Fonction` (title)
- `Catégorie` (select) : permission, tool, knowledge, skill, workflow, other
- `Statut` (status) : "En attente" par défaut
- `Source` (rich_text) : "Autometa"
- `Description` (rich_text, optionnel)

### 3. Corpus — Synchronisation de la recherche terrain

**Fichier** : `scripts/refresh_research.py`
**Cron** : `cron/research-corpus/` (hebdomadaire, timeout 1200s)
**Base locale** : `data/notion_research.db`

Synchronise 6 bases Notion du workspace "Connaissance du terrain".
Voir [knowledge/research/_index.md](../research/_index.md) pour le modèle de données complet.

Pipeline :
1. Query chaque base Notion → compare `last_edited_time`
2. Re-fetch les blocs des pages modifiées uniquement
3. Rebuild les chunks (~400 car.), conserve les embeddings si le texte n'a pas changé (hash SHA-256)
4. Embed les nouveaux chunks avec `sentence-transformers` (Qwen3-Embedding-0.6B, local)

Les 6 database IDs sont définis dans `scripts/refresh_research.py` (dict `DATABASES`).
