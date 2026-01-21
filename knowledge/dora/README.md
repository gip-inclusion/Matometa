# Dora Metabase

- **URL:** https://metabase.dora.inclusion.gouv.fr
- **Database:** `dora-analytics` (PostgreSQL)
- **Instance name:** `dora`

## Related Knowledge

Dora has two knowledge files:

| File | Content |
|------|---------|
| **This file** (`knowledge/dora/README.md`) | Metabase database: structures, services, orientations, search data, SQL queries |
| `knowledge/sites/dora.md` | Matomo web analytics: traffic baselines, events, funnels, segments |

**Use this file** for: querying the database, understanding the domain model, search analytics by organization, content freshness.

**Use `knowledge/sites/dora.md`** for: visitor counts, bounce rates, event tracking, user journeys, Matomo segments.

## Access

The API key (`METABASE_DORA_API_KEY`) has database query access but limited collection permissions:
- Can execute SQL queries on all tables
- Cannot view dashboards or cards (18 dashboards, 163+ cards exist but return 403)

To get full access, the API key needs to be added to a group with collection permissions in Metabase admin.

## Querying Dora Metabase

### IMPORTANT: Always specify database_id=2

When using `execute_metabase_query()`, you MUST include `database_id=2`:

```python
from lib.query import execute_metabase_query, CallerType

# CORRECT
result = execute_metabase_query(
    instance='dora',
    caller=CallerType.AGENT,
    sql="SELECT COUNT(*) FROM structures_structure",
    database_id=2,  # REQUIRED!
)

# WRONG - will error "Either sql+database_id or card_id must be provided"
result = execute_metabase_query(
    instance='dora',
    caller=CallerType.AGENT,
    sql="SELECT COUNT(*) FROM structures_structure",
    # missing database_id!
)
```

### Simpler: Use get_metabase() helper

The helper handles database_id automatically:

```python
from lib.query import get_metabase

api = get_metabase(instance='dora')
result = api.execute_sql("SELECT COUNT(*) FROM structures_structure")
print(result.rows[0][0])
```

### Case-sensitive table names

The `int_iMER` table name is case-sensitive in PostgreSQL. Use quotes:

```sql
-- CORRECT
SELECT * FROM public_intermediate."int_iMER" LIMIT 10

-- WRONG - will error "relation does not exist"
SELECT * FROM public_intermediate.int_imer LIMIT 10
```

## Domain Model

Dora is a directory of social services (services d'insertion) that connects professionals (prescribers) with services for their beneficiaries.

### Core Entities

```
Structure (25,298)
    └── Service (37,514)
            └── Orientation (11,220)
                    └── Beneficiary (usager)

User (50,947)
    ├── Prescriber (accompagnateur) - orients beneficiaries to services
    └── Provider (offreur) - manages structures/services
```

**Structure:** An organization (association, public service, company) that provides social services. Has a typology (ASSO, ACI, EI, CCAS, etc.) and location.

**Service:** A specific offering from a structure. Has categories/themes, location, criteria, and can accept orientations. Services are searchable by location + theme + subtheme.

**Orientation:** The main conversion event. A prescriber orients a beneficiary towards a service. Statuses:
- `VALIDEE` (5,020) - Accepted
- `EXPIREE` (4,907) - Expired without response
- `REFUSEE` (709) - Rejected
- `OUVERTE` (367) - Open/pending
- `MODERATION_*` - In moderation

**User:** Platform users with main activities:
- `accompagnateur` (17,407) - Prescribers who orient beneficiaries
- `accompagnateur_offreur` (17,260) - Both prescriber and provider
- `offreur` (3,841) - Service providers only
- `autre` (5,517) - Other roles

### Key Metrics

**iMER (Intention de Mise en Relation):** A strong engagement signal when a user shows interest in a service or structure. Tracked in `int_iMER` table.

iMER kinds:
- `mobilisation` (52,692) - Interest shown (weaker signal)
- `orientation` (10,636) - Actual orientation sent (strongest signal)

**Conversion funnel:**
1. Search (634,827 search views)
2. Service view (1,767,429 service views)
3. Mobilisation/iMER (71,128 events)
4. Orientation (11,220 total, ~700/month in 2025)

### Content Freshness

Whether a service or structure has been recently updated is an important quality metric.

**Service freshness (as of Jan 2025):**
| Last updated | Services |
|--------------|----------|
| Last 30 days | 2,606 |
| 30-90 days | 4,557 |
| 90-180 days | 7,546 |
| 6-12 months | 7,281 |
| Over 1 year | 15,524 |

**Structure freshness:**
| Last updated | Structures |
|--------------|------------|
| Last 30 days | 432 |
| 30-90 days | 1,353 |
| 90-180 days | 2,368 |
| 6-12 months | 3,592 |
| Over 1 year | 17,553 |

Key date fields on `services_service`: `creation_date`, `modification_date`, `publication_date`, `suspension_date`, `update_frequency`.

## Database Schema

### Schemas

| Schema | Purpose |
|--------|---------|
| `public` | Core application tables |
| `public_intermediate` | Pre-computed analytics (dbt models) |
| `matomo` | Matomo tracking data |

### Core Tables (public)

| Table | Records | Description |
|-------|---------|-------------|
| `structures_structure` | 25,298 | Organizations providing services |
| `services_service` | 37,514 | Service offerings |
| `users_user` | 50,947 | Platform users |
| `orientations_orientation` | 11,220 | Orientation requests |
| `services_servicecategory` | 23 | Service themes/categories |
| `stats_mobilisationevent` | 71,128 | Mobilisation/interest events |
| `stats_serviceview` | 1,767,429 | Service page views |
| `stats_searchview` | 634,827 | Search events |
| `stats_pageview` | 6,858,377 | General page views |

### Analytics Tables (public_intermediate)

Pre-computed tables for dashboards:

| Table | Description |
|-------|-------------|
| `int_iMER` | All iMER events (63,328 records, 2023-06 to present) |
| `int_monthly_user_iMER` | Monthly iMER aggregations per user |
| `int_monthly_user_orientations` | Monthly orientations per user |
| `int_monthly_user_mobilisations` | Monthly mobilisations per user |
| `int_monthly_user_service_views` | Monthly service views per user |
| `int_orientation_user_service` | Orientation details with user/service data (132 fields) |
| `int_orientations_following_mobilisation` | Conversion tracking |
| `int_prescribers` | Prescriber profiles (38,480 records, 54 fields) |
| `int_service_structure` | Service with structure data |
| `int_service_categories` | Services with category data |
| `int_structure_*` | Structure aggregations |

### Matomo Tables

| Table | Description |
|-------|-------------|
| `mtm_share_service_tracking` | Service share tracking from Matomo |

## Service Categories

| ID | Slug | Label |
|----|------|-------|
| 15 | acces-aux-droits-et-citoyennete | Acces aux droits & citoyennete |
| 7 | accompagnement-social-et-professionnel-personnalise | Accompagnement social et professionnel personnalise |
| 5 | apprendre-francais | Apprendre le Francais |
| 34 | choisir-un-metier | Choisir un metier |
| 1 | creation-activite | Creation d'activite |
| 6 | gestion-financiere | Gestion financiere |
| 8 | handicap | Handicap |
| 11 | illettrisme | Illettrisme |
| 10 | logement-hebergement | Logement et hebergement |
| 13 | mobilite | Mobilite |
| 2 | numerique | Numerique |
| 35 | preparer-sa-candidature | Preparer sa candidature |
| 14 | remobilisation | Remobilisation |
| 9 | sante | Sante |

## Structure Typologies

| Code | Count | Description |
|------|-------|-------------|
| ASSO | 2,228 | Association |
| ACI | 1,985 | Atelier et Chantier d'Insertion |
| EI | 1,291 | Entreprise d'Insertion |
| FT | 1,023 | France Travail (ex-Pole Emploi) |
| CCAS | 876 | Centre Communal d'Action Sociale |
| EA | 811 | Entreprise Adaptee |
| AI | 648 | Association Intermediaire |
| ETTI | 638 | Entreprise de Travail Temporaire d'Insertion |
| ML | 458 | Mission Locale |
| OF | 406 | Organisme de Formation |

## Search Data

Search is the main entry point: users search by location + theme (category) + optional subtheme.

### Tables

| Table | Description |
|-------|-------------|
| `stats_searchview` | Raw search events (634,827 total) |
| `stats_searchview_categories` | Join table linking searches to categories |
| `public_intermediate.int_searchview_user` | Enriched view with user details |

### stats_searchview Columns

| Column | Description |
|--------|-------------|
| `date` | Search timestamp |
| `city_code`, `department` | Location searched |
| `num_results` | Total results returned |
| `num_di_results` | Results from Data Inclusion (national registry) |
| `num_di_results_top10` | DI results in top 10 |
| `results_slugs_top10` | Service slugs of top 10 results |
| `is_logged`, `user_kind` | User context |
| `user_id` | Links to `users_user` (NULL if anonymous) |

### Linking Searches to Users and Organizations

Searches can be linked to specific users and their structures. About 30% of searches come from logged-in users.

**Key join path:**
```
stats_searchview.user_id
  → structures_structuremember.user_id
    → structures_structure.id
```

**Basic search with user's organization:**
```sql
SELECT
    sv.date,
    sv.department,
    sv.num_results,
    u.email,
    s.name as structure_name,
    s.typology
FROM stats_searchview sv
JOIN structures_structuremember sm ON sv.user_id = sm.user_id
JOIN structures_structure s ON sm.structure_id = s.id
JOIN users_user u ON sv.user_id = u.id
WHERE sv.date >= '2025-01-01'
ORDER BY sv.date DESC
```

**Top organizations by search volume:**
```sql
SELECT
    s.name as structure_name,
    s.typology,
    s.department,
    COUNT(*) as searches
FROM stats_searchview sv
JOIN structures_structuremember sm ON sv.user_id = sm.user_id
JOIN structures_structure s ON sm.structure_id = s.id
WHERE sv.date >= '2025-01-01'
GROUP BY s.id, s.name, s.typology, s.department
ORDER BY searches DESC
LIMIT 25
```

**Searches aggregated by organization type:**
```sql
SELECT
    COALESCE(NULLIF(s.typology, ''), '(non renseigne)') as typology,
    COUNT(DISTINCT s.id) as orgs,
    COUNT(*) as searches
FROM stats_searchview sv
JOIN structures_structuremember sm ON sv.user_id = sm.user_id
JOIN structures_structure s ON sm.structure_id = s.id
WHERE sv.date >= '2025-01-01'
GROUP BY 1
ORDER BY searches DESC
```

**Or use the pre-joined intermediate table (for user details only, no structure):**
```sql
SELECT
    event_date,
    event_num_results,
    user_email,
    user_main_activity
FROM public_intermediate.int_searchview_user
WHERE user_id IS NOT NULL
ORDER BY event_date DESC
```

### Top Searching Organizations (2025)

**By individual organization:**
| Structure | Type | Dept | Searches |
|-----------|------|------|----------|
| Departement de la Drome | CD | 26 | 2,634 |
| Conseil Departemental de la Somme | CD | 80 | 1,734 |
| DGAS Direction Generale Adjointe (Vienne) | CD | 86 | 1,486 |
| Departement du Loiret | CD | 45 | 1,081 |
| Departement de la Vienne | CD | 86 | 1,066 |

**By organization type:**
| Type | Orgs | Searches |
|------|------|----------|
| France Travail (FT) | 938 | 65,369 |
| (non renseigne) | 825 | 27,660 |
| Conseil Departemental (CD) | 51 | 16,103 |
| Association (ASSO) | 665 | 15,631 |
| Autre | 448 | 15,198 |
| ACI | 359 | 7,152 |
| MDS | 15 | 6,917 |
| DEPT | 57 | 4,398 |
| Cap Emploi | 90 | 3,111 |
| CCAS | 157 | 2,754 |
| Mission Locale (ML) | 197 | 2,433 |

France Travail dominates (65k searches from 938 agencies). Conseils Departementaux are heavy users relative to their count (16k from 51 orgs).

### 2025 Search Statistics

**Monthly volume:**
| Month | Searches |
|-------|----------|
| 2025-01 | 32,669 |
| 2025-02 | 32,943 |
| 2025-03 | 32,631 |
| 2025-04 | 31,422 |
| 2025-05 | 25,738 |
| 2025-06 | 30,678 |
| 2025-07 | 29,257 |
| 2025-08 | 22,170 |
| 2025-09 | 30,733 |
| 2025-10 | 36,196 |
| 2025-11 | 32,169 |
| 2025-12 | 30,220 |

**Top searched categories (2025):**
| Category | Searches |
|----------|----------|
| Apprendre le Francais | 51,395 |
| Mobilite | 38,250 |
| Accompagnement social et professionnel | 27,728 |
| Logement et hebergement | 26,921 |
| Trouver un emploi | 26,278 |
| Numerique | 21,373 |
| Acces aux droits & citoyennete | 17,885 |
| Choisir un metier | 16,525 |
| Famille | 16,403 |
| Sante | 15,138 |

**Top departments (2025):**
| Dept | Searches |
|------|----------|
| 59 (Nord) | 19,893 |
| 75 (Paris) | 15,022 |
| 26 (Drome) | 14,070 |
| 13 (Bouches-du-Rhone) | 13,907 |
| 93 (Seine-Saint-Denis) | 12,594 |

**User breakdown (2025):**
| User type | Searches | % |
|-----------|----------|---|
| Anonymous | 271,992 | 70% |
| Accompagnateur | 52,282 | 13% |
| Accompagnateur_offreur | 40,435 | 10% |
| Autre | 18,965 | 5% |
| Offreur | 6,733 | 2% |

**Results distribution (2025):**
| Bucket | Searches |
|--------|----------|
| 0 results | 1,354 (0.3%) |
| 1-10 | 34,056 |
| 11-50 | 133,345 |
| 51-100 | 93,764 |
| 101-500 | 85,706 |
| 500+ | 42,182 |

**Zero-result searches** are rare (0.3%), mostly in "Equipement et alimentation" category (731 cases) - potential coverage gap.

**Data Inclusion integration:** 83% of searches return DI results (324,071 vs 66,336 without).

## Sample Queries

### Monthly orientations
```sql
SELECT TO_CHAR(creation_date, 'YYYY-MM') as month,
       COUNT(*) as orientations
FROM orientations_orientation
WHERE creation_date >= '2025-01-01'
GROUP BY 1
ORDER BY 1
```

### iMER by kind
```sql
SELECT kind, COUNT(*) as count
FROM public_intermediate."int_iMER"
GROUP BY kind
ORDER BY count DESC
```

### Active prescribers (with orientations)
```sql
SELECT COUNT(DISTINCT prescriber_id)
FROM orientations_orientation
WHERE creation_date >= '2025-01-01'
```

### Services by category
```sql
SELECT sc.value as category, COUNT(*) as services
FROM services_service s
JOIN services_service_categories ssc ON s.id = ssc.service_id
JOIN services_servicecategory sc ON ssc.servicecategory_id = sc.id
GROUP BY sc.value
ORDER BY services DESC
```

### Monthly searches
```sql
SELECT TO_CHAR(date, 'YYYY-MM') as month, COUNT(*) as searches
FROM stats_searchview
WHERE date >= '2025-01-01'
GROUP BY 1
ORDER BY 1
```

### Searches by category
```sql
SELECT sc.label, COUNT(*) as searches
FROM stats_searchview_categories svc
JOIN services_servicecategory sc ON svc.servicecategory_id = sc.id
JOIN stats_searchview sv ON svc.searchview_id = sv.id
WHERE sv.date >= '2025-01-01'
GROUP BY sc.label
ORDER BY searches DESC
```

### Zero-result searches by category
```sql
SELECT sc.label, COUNT(*) as zero_result_searches
FROM stats_searchview_categories svc
JOIN services_servicecategory sc ON svc.servicecategory_id = sc.id
JOIN stats_searchview sv ON svc.searchview_id = sv.id
WHERE sv.date >= '2025-01-01' AND sv.num_results = 0
GROUP BY sc.label
ORDER BY zero_result_searches DESC
```

### Service/structure freshness
```sql
SELECT
    CASE
        WHEN modification_date >= NOW() - INTERVAL '30 days' THEN 'Last 30 days'
        WHEN modification_date >= NOW() - INTERVAL '90 days' THEN '30-90 days'
        WHEN modification_date >= NOW() - INTERVAL '180 days' THEN '90-180 days'
        WHEN modification_date >= NOW() - INTERVAL '365 days' THEN '6-12 months'
        ELSE 'Over 1 year'
    END as freshness,
    COUNT(*) as count
FROM services_service
GROUP BY 1
ORDER BY 2 DESC
```

### iMER and orientations by organization type
```sql
-- Compare mobilisations and orientations by organization cluster
WITH imer_by_org AS (
    SELECT
        CASE
            WHEN s.typology = 'FT' THEN 'France Travail'
            WHEN s.typology IN ('CD', 'MDS', 'CCAS', 'DEPT') THEN 'Services publics generalistes'
            WHEN s.typology IN ('ML', 'CAP_EMPLOI') THEN 'Operateurs emploi'
            ELSE 'Autres'
        END as cluster,
        i.kind,
        COUNT(*) as count
    FROM public_intermediate."int_iMER" i
    JOIN structures_structuremember sm ON i.user_id = sm.user_id
    JOIN structures_structure s ON sm.structure_id = s.id
    WHERE i.date >= '2025-01-01'
    GROUP BY 1, 2
)
SELECT cluster, kind, count
FROM imer_by_org
ORDER BY cluster, kind
```

### Conversion rates by category (mobilisation → orientation)
```sql
-- Calculate conversion rate from mobilisation to orientation by service category
WITH mobs AS (
    SELECT
        i.service_categories,  -- comma-separated list
        COUNT(*) as mobilisations
    FROM public_intermediate."int_iMER" i
    WHERE i.kind = 'mobilisation' AND i.date >= '2025-01-01'
    GROUP BY 1
),
orients AS (
    SELECT
        i.service_categories,
        COUNT(*) as orientations
    FROM public_intermediate."int_iMER" i
    WHERE i.kind = 'orientation' AND i.date >= '2025-01-01'
    GROUP BY 1
)
SELECT
    COALESCE(m.service_categories, o.service_categories) as categories,
    COALESCE(m.mobilisations, 0) as mobilisations,
    COALESCE(o.orientations, 0) as orientations,
    ROUND(100.0 * COALESCE(o.orientations, 0) / NULLIF(COALESCE(m.mobilisations, 0), 0), 1) as conversion_rate
FROM mobs m
FULL OUTER JOIN orients o ON m.service_categories = o.service_categories
ORDER BY mobilisations DESC
```

### Orientation validation rate by organization type
```sql
-- Validation rate (VALIDEE / total) by organization cluster
SELECT
    CASE
        WHEN s.typology = 'FT' THEN 'France Travail'
        WHEN s.typology IN ('CD', 'MDS', 'CCAS', 'DEPT') THEN 'Services publics'
        WHEN s.typology IN ('ML', 'CAP_EMPLOI') THEN 'Operateurs emploi'
        ELSE 'Autres'
    END as cluster,
    COUNT(*) as total_orientations,
    COUNT(*) FILTER (WHERE o.status = 'VALIDEE') as validated,
    ROUND(100.0 * COUNT(*) FILTER (WHERE o.status = 'VALIDEE') / COUNT(*), 1) as validation_rate
FROM orientations_orientation o
JOIN structures_structuremember sm ON o.prescriber_id = sm.user_id
JOIN structures_structure s ON sm.structure_id = s.id
WHERE o.creation_date >= '2025-01-01'
GROUP BY 1
ORDER BY total_orientations DESC
```

## Related Resources

- Site knowledge: `knowledge/sites/dora.md` (Matomo tracking, events, funnels)
- Dora website: https://dora.inclusion.beta.gouv.fr
- GitHub: https://github.com/gip-inclusion/dora
