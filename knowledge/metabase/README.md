# Metabase Cards Inventory

**Database:** `knowledge/metabase/cards.db`
**Last synced:** 2026-01-14 22:12
**Total cards:** 359

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

Structures d'insertion avec coordonnées GPS. Inclut SIAE et autres structures.

| Colonne | Description |
|---------|-------------|
| id | Identifiant unique |
| siret | SIRET de la structure |
| nom | Nom de la structure |
| code_insee | Code INSEE de la commune |
| longitude, latitude | Coordonnées GPS (96.4% de couverture) |
| typologie | Type de structure (voir ci-dessous) |
| source | Source des données |

**Volumétrie:** ~73 000 structures, dont ~71 000 géolocalisées.

**Filtrer les SIAE uniquement :** La table contient toutes les structures (~73k), pas seulement les SIAE (~2 096). Filtrer par `typologie IN ('ACI', 'EI', 'AI', 'ETTI', 'GEIQ', 'EITI')`.

Voir [documentation détaillée des structures](../stats/structures.md) pour les typologies et effectifs.

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

### public.utilisateurs_v0

Utilisateurs du service Emplois.

| Colonne | Description |
|---------|-------------|
| id | Identifiant unique |
| email | Email de l'utilisateur |
| type | Type: `employer`, `prescriber`, `labor_inspector` |
| prenom, nom | Prénom et nom |
| dernière_connexion | Dernière connexion |
| id_structure | FK vers structures (employeurs) |
| id_organisation | FK vers organisations (prescripteurs) |

**Volumétrie:** ~91 000 utilisateurs (aucun candidat, ils n'ont pas de compte).

**Note:** Pas de lien direct au département. Utiliser `tmp_utilisateurs_avec_departement` pour les analyses géographiques.

### public.tmp_utilisateurs_avec_departement

Table enrichie liant les utilisateurs Emplois à leur département via leur structure/organisation.

| Colonne | Description |
|---------|-------------|
| email | Email de l'utilisateur |
| type | Type d'utilisateur |
| prenom, nom | Prénom et nom |
| entite | Nom de la structure/organisation |
| departement | Département (format: "31 - Haute-Garonne") |

**Volumétrie:** ~105 000 lignes (un utilisateur peut appartenir à plusieurs structures).

**Usage:** Filtrer par département avec `WHERE departement LIKE '31 -%'`.

### public.structures_v0

Structures SIAE du service Emplois.

| Colonne | Description |
|---------|-------------|
| ID | Identifiant unique |
| Siret | SIRET |
| Nom | Nom de la structure |
| département | Code département |

**Volumétrie:** ~7 500 structures.

### public.organisations_v0

Organisations prescriptrices.

**Volumétrie:** ~9 750 organisations.

### suivi_utilisateurs_tb_prive_semaine

Utilisateurs du service Pilotage (tableaux de bord privés).

| Colonne | Description |
|---------|-------------|
| email_utilisateur | Email de l'utilisateur |
| semaine | Semaine de la visite |

**Volumétrie:** ~15 400 utilisateurs uniques.

**Note:** 100% des utilisateurs Pilotage sont aussi utilisateurs Emplois (service complémentaire).

### GPS Logs (Mon Suivi / GPS)

Logs d'activité de l'application GPS (Mon Suivi), importés depuis Datadog.

| Colonne | Description |
|---------|-------------|
| Orga | Identifiant de l'organisation ou structure à laquelle appartient l'utilisateur, correspond à l'organisation ID ou structure ID dans les tables "Emploi" (= c2-itou-metabase-db/public/Utilisateurs ou encore c2-itou-metabase-db/public/Organisations et c2-itou-metabase-db/public/Structures |
| User ID | Identifiant de l'utilisateur, correspond à l'ID dans la table c2-itou-metabase-db/public/Utilisateurs |
| Path | L'URL où a été enregistré le log - est traduit en action (List, membership...) |
| Message | Tout le message du log, pourra contenir des infos supplémentaires interessantes en cas d'exploration |
| Current User Type | desc |
| Membership | desc |
| Target Participant | desc |
| Target Participant Type | desc |
| Content | desc |
| Imer Mode | le type de  |
| Message | desc |
| Message | desc |
| Message | desc |


**Source des données:**
- **Origine :** Logs applicatifs Datadog
- **Import :** Quotidien via n8n vers une table ad hoc Metabase
- **Actions trackées :**
  - Vue d'un groupe d'accompagnateurs
  - Ajout d'un accompagnateur
  - Ajout d'un bénéficiaire (= création de groupe)

**Note :** Contrairement à Matomo (comportement web), ces logs capturent les actions métier côté serveur.

### public.ref_clpe_ft

Table de liaison commune → CLPE (Comité Local Pour l'Emploi). 357 CLPE, ~35 000 liaisons.

Voir [documentation détaillée des CLPE](../stats/clpe.md).

### public.offre_demande_clpe

Données offre/demande par CLPE. Voir [documentation CLPE](../stats/clpe.md).

## Limites de l'API Metabase

### Limite de 2000 lignes

Par défaut, Metabase limite les résultats à 2000 lignes. Pour récupérer plus de données, paginer avec `LIMIT` et `OFFSET` :

```python
all_data = []
offset = 0
batch_size = 2000

while True:
    result = api.execute_sql(f'''
        SELECT * FROM ma_table
        ORDER BY id
        LIMIT {batch_size} OFFSET {offset}
    ''')
    if not result.rows:
        break
    all_data.extend(result.rows)
    offset += batch_size
```

### Analyses géospatiales lourdes

Pour les analyses croisant beaucoup de données (ex: 35k communes × 70k structures), les requêtes SQL timeout. **Approche recommandée :**

1. **Télécharger les données** via l'API Metabase (avec pagination)
2. **Charger en local** (SQLite, pandas, ou en mémoire)
3. **Calculer en Python** avec formule Haversine + optimisations (grille spatiale, bounding box)

Exemple : voir `scripts/calculate_siae_proximity.py` (calcul en ~6s pour 35k communes × 2k SIAE).

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
| pass-iae | Stats PASS IAE |

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

## Requêtes SQLite

```python
from skills.metabase_query.scripts.cards_db import load_cards_db

db = load_cards_db()
cards = db.search("file active")  # Full-text search
cards = db.by_topic("candidatures")  # Filter by topic
cards = db.by_dashboard(408)  # Cards in a dashboard
cards = db.by_table("candidats")  # Cards using a table
card = db.get(7004)  # Get by ID
```
