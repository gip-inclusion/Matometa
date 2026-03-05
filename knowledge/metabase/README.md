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

### bac_a_sable.communes_pop_aav

Voir [documentation détaillée de la table](../stats/communes-pop-aav.md) pour le schéma et les bonnes pratiques.

Communes françaises avec population, classification d'urbanité (AAV INSEE) et coordonnées GPS.

| Colonne | Description |
|---------|-------------|
| code_commune | Code INSEE (clé primaire) |
| libelle_commune | Nom de la commune |
| dept, region | Codes département et région |
| code_aav, libelle_aav | Aire d'attraction des villes |
| cateaav, cateaav_label | Catégorie : Pôle principal/secondaire, Couronne, Hors attraction |
| taav, taav_label | Tranche : Paris, 700k+, 200-700k, 50-200k, <50k, Hors AAV |
| population | Population municipale 2021 |
| latitude, longitude | Centroïde GPS |

**Volumétrie:** 34 875 communes avec couverture complète.

**Classification urbain/rural simplifiée :**
```sql
SELECT
    CASE
        WHEN cateaav IN ('11', '12') THEN 'Urbain (pôle)'
        WHEN cateaav = '20' THEN 'Périurbain (couronne)'
        ELSE 'Rural (hors AAV)'
    END as urbanite
FROM bac_a_sable.communes_pop_aav;

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
SELECT c.code_commune, c.libelle_commune, c.population, c.taav_label, COUNT(s.id) as nb_siae
FROM bac_a_sable.communes_pop_aav c
JOIN data_inclusion.structures_v0 s
  ON s.latitude BETWEEN c.latitude - 0.1 AND c.latitude + 0.1
 AND s.longitude BETWEEN c.longitude - 0.15 AND c.longitude + 0.15
 AND earth_distance(
       ll_to_earth(c.latitude, c.longitude),
       ll_to_earth(s.latitude, s.longitude)
     ) <= 10000
WHERE c.population < 20000
  AND c.code_commune >= '35000' AND c.code_commune < '36000'
  AND s.latitude IS NOT NULL
GROUP BY c.code_commune, c.libelle_commune, c.population, c.taav_label
HAVING COUNT(s.id) >= 3
ORDER BY nb_siae DESC;
```

**Note:** Sans filtre par département, la requête timeout. Exécuter par région ou ajouter des index sur `latitude`/`longitude`.

### public.utilisateurs

Utilisateurs professionnels du service Emplois (employeurs, prescripteurs, inspecteurs).
**Préférer cette table à `utilisateurs_v0`** qui existe aussi mais contient moins de colonnes.

| Colonne | Description |
|---------|-------------|
| id | Identifiant unique |
| email | Email de l'utilisateur |
| type | Type: `employer`, `prescriber`, `labor_inspector` |
| prenom, nom | Prénom et nom |
| dernière_connexion | Dernière connexion |
| id_structure | FK vers `structures_v0` (pour les employeurs) |
| id_organisation | FK vers `organisations_v0` (pour les prescripteurs) |
| id_institution | FK vers `institutions` (pour certains prescripteurs institutionnels) |

**Volumétrie:** ~91 000 utilisateurs.

**⚠️ Utilisateurs pros uniquement.** Les candidats (demandeurs d'emploi) ne sont pas dans cette table — ils sont dans `public.candidats` (voir section dédiée).

**Note:** Pas de lien direct au département. Utiliser `tmp_utilisateurs_avec_departement` pour les analyses géographiques.

Voir aussi [knowledge/stats/users.md](../stats/users.md) pour les requêtes courantes.

#### Jointures selon le type d'utilisateur

Un utilisateur se joint à une table différente selon son type :

| Type utilisateur | Table à joindre | Clé de jointure |
|------------------|-----------------|-----------------|
| `employer` | `structures_v0` | `utilisateurs.id_structure = structures.ID` |
| `prescriber` | `organisations_v0` | `utilisateurs.id_organisation = organisations.id` |
| `prescriber` (institutionnel) | `institutions` | `utilisateurs.id_institution = institutions.id` |

```sql
-- Exemple : utilisateurs employeurs avec leur structure
SELECT u.*, s.nom as structure_nom, s.département
FROM public.utilisateurs u
LEFT JOIN public.structures_v0 s ON u.id_structure = s."ID"
WHERE u.type = 'employer';

-- Exemple : utilisateurs prescripteurs avec leur organisation
SELECT u.*, o.nom as organisation_nom
FROM public.utilisateurs u
LEFT JOIN public.organisations_v0 o ON u.id_organisation = o.id
WHERE u.type = 'prescriber';
```

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

Structures SIAE du service Emplois. Aussi accessible via `public.structures`.

| Colonne | Description |
|---------|-------------|
| ID | Identifiant unique |
| Siret | SIRET |
| Nom | Nom de la structure |
| type | Type SIAE : ACI, AI, EI, EITI, ETTI, GEIQ |
| source | Origine : Export ASP, Export EA+EATT, Export GEIQ, Utilisateur (OPCS), Staff Itou |
| date_inscription | Date d'inscription sur la plateforme |
| total_membres | Nombre de membres rattachés |
| adresse_ligne_1 | Adresse |
| ville | Ville |
| code_postal | Code postal |
| département | Code département |
| nom_département | Nom du département |
| région | Région |

**Volumétrie:** ~7 500 structures.

### public.organisations_v0

Organisations prescriptrices. Aussi accessible via `public.organisations`.

| Colonne | Description |
|---------|-------------|
| id | Identifiant unique |
| nom | Nom de l'organisation |
| type | Type court : FT, ML, CAP_EMPLOI, DEPT, PLIE, etc. |
| type_complet | Type détaillé |
| habilitée | Prescripteur habilité (peut valider l'éligibilité IAE) |
| date_inscription | Date d'inscription sur la plateforme |
| total_membres | Nombre de membres rattachés |
| adresse_ligne_1 | Adresse |
| ville | Ville |
| code_postal | Code postal |
| département | Code département |
| nom_département | Nom du département |
| région | Région |

**Volumétrie:** ~9 750 organisations.


### public.institutions

Institutions (prescripteurs institutionnels comme Pôle Emploi, conseils départementaux).

| Colonne | Description |
|---------|-------------|
| id | Identifiant unique |
| nom | Nom de l'institution |

**Volumétrie:** 345 institutions.

**Usage:** Les utilisateurs de type institutionnels (type inspection du travail, direction de l'emploi du travail et des solidarités, Direction générale de l'emploi et de la formation professionnelle...) sont rattachés à une institution plutôt qu'à une organisation. Vérifier `id_institution` dans `utilisateurs`.

### public.candidats

Candidats (demandeurs d'emploi) du service Emplois.

| Colonne | Description |
|---------|-------------|
| id | Identifiant unique |
| date_diagnostic | Date du diagnostic d'éligibilité IAE |
| total_embauches | Nombre total d'embauches |
| type_structure_dernière_embauche | Type SIAE de la dernière embauche (ACI, AI, EI, EITI, ETTI) |
| département | Département du candidat |
| critère_n1_bénéficiaire_du_rsa | Critère niveau 1 : bénéficiaire RSA |
| critère_n1_detld_plus_de_24_mois | Critère niveau 1 : DETLD +24 mois |
| critère_n2_deld_12_à_24_mois | Critère niveau 2 : DELD 12-24 mois |
| critère_n2_jeune_moins_de_26_ans | Critère niveau 2 : jeune <26 ans |
| critère_n2_résident_qpv | Critère niveau 2 : résident QPV |

**⚠️ Table séparée des utilisateurs pros.** Les candidats n'ont pas de compte utilisateur au sens classique, mais ils ont un compte candidat — ils sont dans cette table dédiée, pas dans `utilisateurs`.

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
| Orga | Identifiant de l'organisation/structure/institution. Correspond à `id` dans `organisations_v0` ou `ID` dans `structures_v0` ou `ID` dans `institutions`  selon le type d'utilisateur |
| User ID | Identifiant de l'utilisateur. **FK vers `utilisateurs.id`** — permet de joindre avec la table utilisateurs pour enrichir les analyses |
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

### Support Emplois (Zendesk)

Tickets du support utilisateurs des Emplois de l'Inclusion, alimentés depuis Zendesk
via webhooks n8n (mise à jour en temps réel).

| Table | Granularité | Description |
|-------|-------------|-------------|
| `public.support_emplois_tickets_metrics` | 1 ligne/ticket | Métriques de traitement (délais de réponse, résolution, réouvertures) |
| `public.support_emplois_tickets_infos` | 1 ligne/ticket | Contexte du ticket (demandeur, sujet, canal, horodatage) |
| `public.support_emplois_tickets_tags` | N lignes/ticket | Tags (automatiques ou manuels) — un tag par ligne |

**Clé de jointure :** `id_du_ticket` (integer) — commune aux trois tables.

**Délais disponibles :** `first_reply_time_minutes`, `first_resolution_time_minutes`, `full_resolution_time_minutes` (en minutes).

**Lien utilisateurs :** Joindre `support_emplois_tickets_infos.e_mail_du_demandeur` à `public.utilisateurs.email` pour identifier le type d'utilisateur.

Voir [documentation complète](../stats/support-emplois.md).

### public.ref_clpe_ft

Table de liaison commune → CLPE (Comité Local Pour l'Emploi). 357 CLPE, ~35 000 liaisons.

Voir [documentation détaillée des CLPE](../stats/clpe.md).

### public.offre_demande_clpe

Données offre/demande par CLPE. Voir [documentation CLPE](../stats/clpe.md).

### Nexus — Application Unifiée (DB 17)

Base dédiée à Nexus, fonctionnalité permettant aux utilisateurs de voir leur présence cross-services.
**⚠️ Base distincte : `database_id = 17`** (pas la même que Stats principal).

| Table | Volumétrie | Description |
|-------|------------|-------------|
| `public.structures` | 52 573 lignes | Structures par service (un SIRET peut apparaître N fois) |
| `public.users` | 139 186 lignes | Utilisateurs par service (un email peut apparaître N fois) |
| `public.memberships` | 136 428 lignes | Liens user ↔ structure avec rôle (`administrateur` / `collaborateur`) |

**Clé de jointure :** `id_unique` (format `{source}--{id_source}`) →
`memberships.user_id_unique` et `memberships.structure_id_unique`.

**Sources :** `emplois-de-linclusion`, `dora`, `le-marché`

Voir [documentation complète](../stats/nexus.md).

## Tables recommandées pour analyses détaillées (Emplois)

Pour des analyses qui dépassent les tables "courantes" (candidatures, structures), voici les tables de référence et leurs jointures :

### Schéma relationnel simplifié
candidats (demandeurs d'emploi)
↓ candidatures
utilisateurs (pros)
├── id_structure → structures_v0 (employeurs SIAE)
├── id_organisation → organisations_v0 (prescripteurs)
└── id_institution → institutions (prescripteurs institutionnels)

### Tables prioritaires

| Besoin | Table | Jointure depuis utilisateurs |
|--------|-------|------------------------------|
| Infos employeur SIAE | `structures_v0` | `ON u.id_structure = s."ID"` |
| Infos prescripteur | `organisations_v0` | `ON u.id_organisation = o.id` |
| Infos institution | `institutions` | `ON u.id_institution = i.id` |
| Infos candidat | `candidats` | Table séparée (pas de FK directe) |
| Logs GPS enrichis | `utilisateurs` | `ON gps.user_id = u.id` |

### Exemple : enrichir les logs GPS avec infos utilisateur

```sql
SELECT 
    gps.*,
    u.type as user_type,
    u.email,
    COALESCE(s.nom, o.nom) as entite_nom,
    COALESCE(s.département, 'N/A') as departement
FROM gps_logs gps
LEFT JOIN public.utilisateurs u ON gps."User ID" = u.id
LEFT JOIN public.structures_v0 s ON u.id_structure = s."ID"
LEFT JOIN public.organisations_v0 o ON u.id_organisation = o.id;
```

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
