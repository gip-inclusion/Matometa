# Inventaire Metabase

Documentation des cartes et dashboards Metabase pour les données IAE.

## Sources de données

### Markdown (recommandé)

Les cartes sont documentées dans `knowledge/stats/` :
- `_index.md` : vue d'ensemble
- `cards/topic-*.md` : cartes groupées par thème
- `dashboards/dashboard-*.md` : cartes par tableau de bord

Ces fichiers sont versionnés dans git et mis à jour via le skill `sync_metabase`.

### SQLite (optionnel)

Si besoin de requêtes complexes, générer la base SQLite :

```bash
python -m skills.sync_metabase.scripts.sync_inventory --sqlite
```

Crée `knowledge/metabase/cards.db` avec recherche full-text.

## Tables de référence

### data_inclusion.structures_v0

Structures d'insertion (SIAE, etc.) avec coordonnées GPS.

| Colonne | Description |
|---------|-------------|
| id | Identifiant unique |
| siret | SIRET de la structure |
| nom | Nom de la structure |
| code_insee | Code INSEE de la commune |
| longitude, latitude | Coordonnées GPS (96.4% de couverture) |
| typologie | Type de structure |
| source | Source des données |

**Volumétrie:** ~73 000 structures, dont ~71 000 géolocalisées.

### public.communes

Communes françaises avec coordonnées GPS (centroïdes).

| Colonne | Description |
|---------|-------------|
| code_insee | Code INSEE |
| nom | Nom de la commune |
| latitude, longitude | Centroïde GPS |
| statut_zrr | Zone de Revitalisation Rurale |

**Volumétrie:** 35 014 communes.

**Note:** Cette table ne contient pas la population. Utiliser `bac_a_sable.communes_population_2021` pour les analyses nécessitant la population.

### bac_a_sable.communes_population_2021

Communes françaises avec population (données INSEE 2021, via geo.api.gouv.fr).

| Colonne | Description |
|---------|-------------|
| code_insee | Code INSEE (clé primaire) |
| nom | Nom de la commune |
| population | Population municipale |
| longitude, latitude | Centroïde GPS |

**Volumétrie:** 34,969 communes dont 34,953 avec population.

**Communes < 20k habitants:** 34,464 (98.6%)

### Extensions PostgreSQL

- `earthdistance` : calcul de distances sur la sphère terrestre
- `cube` : support pour earthdistance

```sql
-- Distance entre deux points (en mètres)
SELECT earth_distance(
    ll_to_earth(lat1, lon1),
    ll_to_earth(lat2, lon2)
) as distance_m;
```

### Requête géospatiale : SIAE par commune

Exemple : communes < 20k habitants avec au moins N SIAE dans un rayon de X km.

```sql
-- IMPORTANT: utiliser un bounding box pour éviter les timeouts
SELECT c.code_insee, c.nom, c.population, COUNT(s.id) as nb_siae
FROM bac_a_sable.communes_population_2021 c
JOIN data_inclusion.structures_v0 s
  ON s.latitude BETWEEN c.latitude - 0.1 AND c.latitude + 0.1
 AND s.longitude BETWEEN c.longitude - 0.15 AND c.longitude + 0.15
 AND earth_distance(
       ll_to_earth(c.latitude, c.longitude),
       ll_to_earth(s.latitude, s.longitude)
     ) <= 10000  -- 10km en mètres
WHERE c.population < 20000
  AND c.code_insee >= '35000' AND c.code_insee < '36000'  -- filtrer par dept
  AND s.latitude IS NOT NULL
GROUP BY c.code_insee, c.nom, c.population
HAVING COUNT(s.id) >= 3
ORDER BY nb_siae DESC;
```

**Note:** Sans filtre par département, la requête timeout. Exécuter par région ou ajouter des index sur `latitude`/`longitude`.

## Thèmes

| Thème | Description |
|-------|-------------|
| file-active | Candidats en attente 30+ jours |
| postes-tension | Postes difficiles à pourvoir |
| candidatures | Flux de candidatures |
| demographie | Répartitions âge/genre |
| employeurs | Données SIAE/employeurs |
| prescripteurs | Données prescripteurs |
| auto-prescription | Métriques auto-prescription |
| controles | Données conformité |
| prolongations | Extensions PASS |
| etp-effectifs | Métriques effectifs |
| esat | Données ESAT |
| generalites-iae | Stats générales IAE |

## Synchronisation

```bash
# Sync complet avec catégorisation IA (génère markdown)
python -m skills.sync_metabase.scripts.sync_inventory

# Sans catégorisation IA
python -m skills.sync_metabase.scripts.sync_inventory --skip-categorize

# Générer aussi la base SQLite
python -m skills.sync_metabase.scripts.sync_inventory --sqlite
```

## Schéma SQLite (si utilisé)

```sql
CREATE TABLE cards (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    collection_id INTEGER,
    dashboard_id INTEGER,
    topic TEXT,
    sql_query TEXT,
    tables_referenced TEXT  -- JSON array
);

CREATE TABLE dashboards (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    pilotage_url TEXT,
    collection_id INTEGER
);
```

## Requêtes SQLite

```python
from skills.metabase_query.scripts.cards_db import load_cards_db

db = load_cards_db()
cards = db.search("file active")      # Recherche full-text
cards = db.by_topic("candidatures")   # Par thème
cards = db.by_dashboard(408)          # Par dashboard
card = db.get(7004)                   # Par ID
```
