# Webinaires — Données de participation

Base de données unifiée des webinaires et inscriptions, alimentée par deux sources :
**Livestorm** (historique 2022–2025) et **Grist** (système actuel, depuis janvier 2026).

## Volumes (février 2026)

| Source | Webinaires | Sessions | Inscriptions | Emails uniques |
|--------|-----------|----------|-------------|----------------|
| Livestorm | 401 | 1 026 | ~94 000 | ~56 000 |
| Grist | 24 | — | ~1 500 | ~1 400 |
| **Total** | **425** | **1 026** | **~95 500** | **~56 600** |

Période couverte : février 2022 → aujourd'hui.

## Stockage

**Datalake PostgreSQL** (via Metabase API, database 2).

| Table datalake | Contenu |
|---|---|
| `matometa_webinaires` | Webinaires (événements) |
| `matometa_webinaire_sessions` | Sessions Livestorm |
| `matometa_webinaire_inscriptions` | Inscriptions / participations |
| `matometa_webinaire_sync_meta` | Métadonnées de synchronisation |

Sync :
- **Grist** : quotidien via `cron/webinaires/` (2 appels API)
- **Livestorm** : manuel via `python scripts/sync_webinaires.py --livestorm-only` (~1 900 appels, budget 10 000/mois)

## Modèle de données

### webinars

| Colonne | Type | Description |
|---------|------|-------------|
| `id` | TEXT PK | `livestorm:{uuid}` ou `grist:{event_id}` |
| `source` | TEXT | `livestorm` \| `grist` |
| `source_id` | TEXT | ID original dans la source |
| `title` | TEXT | Titre du webinaire |
| `description` | TEXT | Description (HTML pour Livestorm, texte pour Grist) |
| `organizer_email` | TEXT | Email de l'organisateur |
| `product` | TEXT | Produit inféré : `emplois`, `dora`, `marche`, `pilotage`, `immersion`, `communaute`, `rdv-insertion` ou NULL |
| `status` | TEXT | Livestorm : `ended`, `on_demand`, `not_started`… / Grist : `active`, `inactive` |
| `started_at` | TEXT | ISO8601 (Grist uniquement — Livestorm : voir sessions) |
| `ended_at` | TEXT | ISO8601 |
| `duration_minutes` | INTEGER | Durée prévue |
| `capacity` | INTEGER | Capacité max (Grist) |
| `registrants_count` | INTEGER | Nombre d'inscrits (summary) |
| `attendees_count` | INTEGER | Nombre de participants (summary, Livestorm) |
| `registration_url` | TEXT | URL formulaire inscription |
| `webinar_url` | TEXT | Lien vers le webinaire |
| `raw_json` | TEXT | Payload complet (JSON) |
| `synced_at` | TEXT | Dernier sync ISO8601 |

### sessions (Livestorm uniquement)

Un webinaire Livestorm peut avoir plusieurs sessions (occurrences d'un même événement récurrent).

| Colonne | Type | Description |
|---------|------|-------------|
| `id` | TEXT PK | `livestorm:{uuid}` |
| `webinar_id` | TEXT FK | Référence vers webinars.id |
| `status` | TEXT | `past`, `upcoming`, `live`, `canceled` |
| `started_at` | TEXT | ISO8601 début réel |
| `ended_at` | TEXT | ISO8601 fin |
| `duration_seconds` | INTEGER | Durée effective |
| `registrants_count` | INTEGER | Inscrits à cette session |
| `attendees_count` | INTEGER | Participants effectifs |
| `room_link` | TEXT | Lien de la salle |

### registrations

| Colonne | Type | Description |
|---------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `source` | TEXT | `livestorm` \| `grist` |
| `webinar_id` | TEXT FK | Référence vers webinars.id |
| `session_id` | TEXT | Référence vers sessions.id (vide pour Grist) |
| `email` | TEXT | Email normalisé (lowercase, trimmed) |
| `first_name` | TEXT | Prénom |
| `last_name` | TEXT | Nom |
| `organisation` | TEXT | Structure / entreprise (voir « Extraction de l'organisation ») |
| `registered` | INTEGER | 1 (toujours) |
| `attended` | INTEGER | 0 ou 1 |
| `attendance_rate` | REAL | 0–100, % du webinaire vu (Livestorm) |
| `attendance_duration_seconds` | INTEGER | Durée de présence en secondes (Livestorm) |
| `has_viewed_replay` | INTEGER | 0 ou 1 (Livestorm) |
| `custom_fields` | JSONB | Champs personnalisés d'inscription (Livestorm) |
| `registered_at` | TEXT | ISO8601 date inscription |
| `synced_at` | TEXT | Dernier sync |

**Contrainte unique** : `(source, webinar_id, session_id, email)` — une personne ne peut être inscrite qu'une fois par session.

### sync_meta

Clé/valeur : `last_sync`, `total_webinars`, `total_registrations`, `unique_emails`, `sync_duration_seconds`.

## Index

```
idx_reg_email        → registrations(email)
idx_reg_org          → registrations(organisation)
idx_reg_webinar      → registrations(webinar_id)
idx_sessions_webinar → sessions(webinar_id)
```

## Modèle des sources

### Livestorm

```
Event (401)
  ├─ title, description, scheduling_status, fields[], owner
  ├─ Sessions (1–68 par event, 1 026 total)
  │    ├─ started_at, ended_at, duration, registrants_count, attendees_count
  │    └─ People (via /sessions/{id}/people)
  │         ├─ email, first_name, last_name, role
  │         └─ registrant_detail: attended, attendance_rate, attendance_duration,
  │            has_viewed_replay, fields[], utm_*, browser, ip_city, ip_country
  └─ API: https://api.livestorm.co/v1, auth = Authorization: {token}
```

Champs personnalisés d'inscription (varient selon l'événement) :

| Champ | Occurrences | Contenu |
|-------|-------------|---------|
| `votre_structure` | 12 326 | Nom de la structure |
| `quel_est_le_nom_de_votre_structure` | 5 803 | Idem (autre formulation) |
| `vous_etes_un_utilisateur` | 9 168 | Type d'utilisateur |
| `quel_type_de_prescripteur_etes-vous` | 9 282 | Sous-type prescripteur |
| `type_de_structure` | 7 157 | Type de structure |
| `votre_departement_...` | 7 845 | Département (2-3 chiffres) |
| `votre_role_au_sein_de_la_structure` | 8 758 | Rôle/fonction |
| `votre_poste` | 6 481 | Intitulé de poste |

Accessibles dans `matometa_webinaire_inscriptions.custom_fields` (JSONB) :

```sql
SELECT custom_fields->>'votre_structure' FROM matometa_webinaire_inscriptions
WHERE source='livestorm' AND custom_fields IS NOT NULL;
```

### Grist

```
Webinaires (24) — Table: Webinaires
  ├─ titre, description, organizer_email, duree, date_event, date_fin
  ├─ lien_webinaire, capacite, nb_inscrits, status, form_inscription_url
  └─ Inscriptions (1 540) — Table: Inscriptions
       ├─ email, nom, prenom, entreprise, date_inscription, a_participe
       └─ Lien vers Webinaires via event_id (soft FK)

API: https://grist.numerique.gouv.fr/api
Auth: Authorization: Bearer {api_key}
Document: GRIST_WEBINAIRES_DOC_ID
```

## Taggage produit

Inféré automatiquement depuis le titre du webinaire (`lib/webinaires.infer_product`).

| Produit | Patterns | Webinaires |
|---------|----------|-----------|
| `dora` | dora | 14 |
| `marche` | marché, achats | 81 |
| `pilotage` | pilotage | 58 |
| `immersion` | immersion | 49 |
| `communaute` | communauté | 24 |
| `rdv-insertion` | rdv-insertion | 8 |
| `emplois` | emplois, pass iae, candidature, prescri… | 63 |
| NULL | non reconnu | 128 |

128 webinaires non tagués — possibilité d'améliorer les patterns ou d'ajouter un mapping manuel.

## Extraction de l'organisation

Livestorm stocke l'organisation dans des champs personnalisés dont le nom varie selon l'événement. L'extraction tente ces champs dans l'ordre :

1. `company`
2. `votre_structure`
3. `quel_est_le_nom_de_votre_structure`
4. `nom_de_votre_structure`
5. `structure`
6. `organisation`
7. `entreprise`

Pour Grist : champ `entreprise` directement.

**Couverture** : ~12 000 / 95 000 inscriptions ont une organisation extraite (~13%).
Le champ `custom_fields` (JSON) contient l'intégralité des champs pour des extractions plus fines.

## Requêtes utiles

### Chercher les participants d'une structure

```sql
SELECT r.organisation, r.email, r.first_name, r.last_name,
       w.title, w.product, r.attended,
       COALESCE(s.started_at, w.started_at) as date
FROM matometa_webinaire_inscriptions r
JOIN matometa_webinaires w ON r.webinar_id = w.id
LEFT JOIN matometa_webinaire_sessions s ON r.session_id = s.id
WHERE LOWER(r.organisation) LIKE '%plie%'
ORDER BY date DESC;
```

### Chercher par email ou domaine

```sql
-- Par email exact
SELECT w.title, w.product, r.attended,
       COALESCE(s.started_at, w.started_at) as date
FROM matometa_webinaire_inscriptions r
JOIN matometa_webinaires w ON r.webinar_id = w.id
LEFT JOIN matometa_webinaire_sessions s ON r.session_id = s.id
WHERE r.email = 'jean.dupont@example.fr';

-- Par domaine
SELECT r.email, r.first_name, r.last_name, r.organisation,
       w.title, w.product, r.attended
FROM matometa_webinaire_inscriptions r
JOIN matometa_webinaires w ON r.webinar_id = w.id
WHERE r.email LIKE '%@mairie-paris.fr'
ORDER BY r.registered_at DESC;
```

### Webinaires par produit avec taux de participation

```sql
SELECT w.product,
       COUNT(DISTINCT w.id) as webinaires,
       COUNT(*) as inscriptions,
       SUM(r.attended) as participations,
       ROUND(SUM(r.attended) * 100.0 / COUNT(*), 1) as taux_participation
FROM matometa_webinaire_inscriptions r
JOIN matometa_webinaires w ON r.webinar_id = w.id
WHERE w.product IS NOT NULL
GROUP BY w.product
ORDER BY inscriptions DESC;
```

### Organisations les plus représentées

```sql
SELECT r.organisation, COUNT(*) as inscriptions,
       SUM(r.attended) as participations,
       COUNT(DISTINCT r.email) as personnes_uniques
FROM matometa_webinaire_inscriptions r
WHERE r.organisation IS NOT NULL AND r.organisation != ''
GROUP BY r.organisation
ORDER BY inscriptions DESC
LIMIT 20;
```

### Exploiter les champs personnalisés (Livestorm)

```sql
-- Département des inscrits
SELECT custom_fields->>'votre_departement_indiquez_les_2_ou_3_premiers_chiffres_de_votre_departement_ex_93_pour_la_seine_saint_denis_971_pour_la_guadeloupe' as dept,
       COUNT(*) as n
FROM matometa_webinaire_inscriptions
WHERE source='livestorm' AND custom_fields IS NOT NULL
GROUP BY dept HAVING dept IS NOT NULL
ORDER BY n DESC LIMIT 10;

-- Type de prescripteur
SELECT custom_fields->>'quel_type_de_prescripteur_etes-vous' as type_prescripteur,
       COUNT(*) as n
FROM matometa_webinaire_inscriptions
WHERE source='livestorm' AND custom_fields IS NOT NULL
GROUP BY type_prescripteur HAVING type_prescripteur IS NOT NULL
ORDER BY n DESC;
```

## Scripts et cron

| Fichier | Rôle |
|---------|------|
| `lib/webinaires.py` | Clients API (Livestorm, Grist), DatalakeWriter, logique de sync |
| `scripts/sync_webinaires.py` | CLI : `--grist-only`, `--livestorm-only` |
| `scripts/datalake_create_webinaires.py` | Création des tables + export initial SQLite → datalake |
| `cron/webinaires/cron.py` | Cron quotidien : Grist uniquement |
| `cron/webinaires/CRON.md` | Métadonnées cron (daily, timeout 600s) |
| `tests/test_webinaires.py` | 43 tests (helpers, schema, sync Grist mocké) |

## Limites

- **Organisation** : couverture faible (~13%) car champ libre non normalisé. Beaucoup de variantes pour une même structure (« Mission Locale », « MISSION LOCALE », « mission locale », « ML »).
- **Produit** : 128 webinaires non tagués. Patterns regex simples.
- **Livestorm** : 10 000 appels/mois. Un full sync consomme ~1 900 appels. Pas de sync incrémental des *personnes* (seulement skip des sessions déjà importées).
- **Grist** : accès viewer (lecture seule). Pas de SQL ni webhooks.
- **Pas de lien avec les comptes utilisateurs** des sites (Emplois, Dora…). Le rapprochement se fait uniquement par email.
