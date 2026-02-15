# Recherche terrain — Corpus ethnographique

Workspace Notion « Connaissance du terrain ». Entretiens, observations, verbatims, hypothèses et conclusions issus de la recherche ethno-terrain sur l'IAE.

## Bases Notion

| Clé | Nom | Pages (~) | Contenu |
|-----|-----|-----------|---------|
| `entretiens` | Entretiens et actions de recherche | 570 | Verbatims, observations, entretiens, notes, retex |
| `thematiques` | Thématiques de recherche | 97 | Thèmes transversaux (autonomie, mobilité, numérique…) |
| `segments` | Segments | 8 | Catégories d'usagers (prescripteurs, employeurs, candidats…) |
| `profils` | Profils (Cibles précises) | 58 | Personas détaillés (coach emploi, directeur d'agence…) |
| `hypotheses` | Hypothèses et questions qu'on se pose | 25 | Questions de recherche à valider |
| `conclusions` | Conclusions | 4 | Apprentissages validés |

## Hiérarchie et relations

```
                  thematiques
                      ↕ (Thématiques / Recherches liées)
segments ← Cible générale ← ENTRETIENS → Cibles précises → profils
                                ↓                              ↓
                           hypotheses                     Segment ↔ profils
                                ↓
                           conclusions
```

Relations principales :

| De | Propriété | Vers | Description |
|----|-----------|------|-------------|
| entretiens | Thématiques | thematiques | Tags thématiques (n:n) |
| entretiens | Cible générale | segments | Segment d'usager concerné |
| entretiens | Cibles précises | profils | Personas spécifiques |
| entretiens | Hypothèses | hypotheses | Hypothèses que l'entretien éclaire |
| entretiens | Conclusions | conclusions | Apprentissages liés |
| entretiens | Contexte de l'observation | entretiens | Lien parent (observation → entretien source) |
| profils | Segment | segments | Rattachement au segment parent |
| hypotheses | Conclusions | conclusions | Hypothèse → conclusion validée |
| thematiques | Conclusions | conclusions | Thème → conclusions associées |

## Types d'entrées (entretiens)

| Valeur Notion | Icône | Description |
|---------------|-------|-------------|
| ❝ Verbatim | ❝ | Citation directe d'un usager |
| 👀 Observation | 👀 | Observation terrain |
| 🗣 Entretien | 🗣 | Entretien semi-directif |
| 📂 Terrain | 📂 | Action de terrain (visite, immersion) |
| 🤼 Open Lab | 🤼 | Atelier collectif |
| 🧮 Questionnaire / quanti | 🧮 | Données quantitatives terrain |
| 📂 Événement | 📅 | Événement observé |
| 🗒️ Note | 🗒️ | Note de recherche |
| 🎤 Retex | 🎤 | Retour d'expérience |
| 📖 Lecture | 📖 | Référence bibliographique |

## Propriétés des entretiens

- **Type** (select) : voir table ci-dessus
- **Date** (date) : date de l'entretien/observation
- **Métier** (texte) : fonction de l'interviewé
- **Structure** (texte) : organisation de l'interviewé
- **Auteurs** (people) : chercheurs ayant réalisé l'entretien

## Base SQLite

Fichier : `data/notion_research.db`
Sync : hebdomadaire via `cron/research-corpus/` (voir [knowledge/notion/_index.md](../notion/_index.md))

### Tables

**pages**
```
id (TEXT PK)              — UUID Notion
database_key (TEXT)       — entretiens, thematiques, segments, profils, hypotheses, conclusions
database_name (TEXT)      — Nom complet de la base
title (TEXT)              — Titre de la page
properties_json (TEXT)    — Propriétés JSON (Type, Date, Métier, relations…)
url (TEXT)                — Lien Notion
last_edited_time (TEXT)   — Timestamp ISO (pour sync incrémentale)
```

**blocks**
```
id (TEXT PK)              — UUID du bloc
page_id (TEXT FK)         — Référence vers pages.id
type (TEXT)               — paragraph, heading_1, quote, bulleted_list_item…
text_content (TEXT)       — Texte extrait
position (INTEGER)        — Ordre dans la page
```

**relations**
```
source_page_id (TEXT)     — Page source
property_name (TEXT)      — Nom de la relation (Thématiques, Cible générale…)
target_page_id (TEXT)     — Page cible
```

**chunks** (pour la recherche sémantique)
```
id (INTEGER PK)           — Auto-increment
page_id (TEXT FK)          — Référence vers pages.id
chunk_index (INTEGER)      — Numéro du chunk dans la page (0, 1, 2…)
text (TEXT)                — Header + body du chunk
text_hash (TEXT)           — SHA-256 tronqué (16 car.) — pour réutiliser les embeddings
database_key (TEXT)        — Clé de la base (cache)
embedding (BLOB)           — Vecteur float32 (Qwen3-Embedding-0.6B, 1024 dims)
```

**sync_meta** : clé/valeur (last_sync, total_pages, embedding_model…)

**Tables FTS** : `pages_fts`, `blocks_fts` (FTS5, standalone)

## Requêtes utiles

### Lister les thématiques avec nombre d'entretiens

```sql
SELECT p.title, COUNT(r.source_page_id) AS nb_entretiens
FROM pages p
LEFT JOIN relations r ON r.target_page_id = p.id AND r.property_name = 'Thématiques'
WHERE p.database_key = 'thematiques'
GROUP BY p.id
ORDER BY nb_entretiens DESC;
```

### Lister les segments

```sql
SELECT title FROM pages WHERE database_key = 'segments' ORDER BY title;
```

### Profils d'un segment

```sql
SELECT p.title AS profil, s.title AS segment
FROM pages p
JOIN relations r ON r.source_page_id = p.id AND r.property_name = 'Segment'
JOIN pages s ON s.id = r.target_page_id
WHERE p.database_key = 'profils'
ORDER BY s.title, p.title;
```

### Entretiens par type

```sql
SELECT json_extract(properties_json, '$.Type') AS type, COUNT(*) AS n
FROM pages
WHERE database_key = 'entretiens'
GROUP BY type
ORDER BY n DESC;
```

### Conclusions et leurs hypothèses

```sql
SELECT c.title AS conclusion, h.title AS hypothese
FROM pages c
JOIN relations r ON r.source_page_id = c.id AND r.property_name = 'Hypothèses'
JOIN pages h ON h.id = r.target_page_id
WHERE c.database_key = 'conclusions';
```

## Recherche sémantique (vecteurs)

**Skill** : invoquer `research_corpus` avant toute recherche.

**CLI** :
```bash
python scripts/search_research.py "mobilité zones rurales"
python scripts/search_research.py "freins numériques" --db entretiens --limit 3
python scripts/search_research.py "prescripteurs" --type "❝ Verbatim" --json
```

**Pipeline** :
1. Requête texte → embedding via DeepInfra API (Qwen3-Embedding-0.6B)
2. Cosine similarity contre la matrice des chunks (pré-normalisée)
3. Dédoublonnage par page_id (meilleur score conservé)

**Web UI** : `/recherche` — recherche + filtres par base et type.

**API** :
- `GET /api/research/search?q=...&db=entretiens&type=❝ Verbatim&limit=20`
- `GET /api/research/similar/{chunk_id}`
- `GET /api/research/pages/{page_id}`
- `GET /api/research/stats`

## Segments (8)

| Segment | Profils (exemples) |
|---------|-------------------|
| Accompagnateur opérationnel | CIP, coach emploi, AS, conseillers FT/ML/Cap Emploi, éducateur spécialisé, médiateur, référent IAE |
| Acheteur | Acheteur public, acheteur privé, facilitateur clauses sociales, responsable commercial |
| Coordinateur administratif | Directeur d'agence, directeur de territoire, encadrant technique, personnel admin SIAE, chargé de com |
| Entreprises | SIAE, entreprise ordinaire |
| Gestionnaire de structure | Directeur d'agence, gérant, recruteur/RH |
| Partenaire | Tête de réseau insertion, éditeur de logiciels |
| Pilote institutionnel | Agent DDETS, agent DREETS |
| Usager | Demandeur d'emploi, salarié en SIAE, aidant, particulier acheteur, employé tuteur |

## Correspondance segments → sites

Mapping approximatif entre les segments recherche et les types d'usagers Matomo.

| Segment recherche | Sites principaux | UserKind Matomo |
|-------------------|------------------|-----------------|
| Accompagnateur opérationnel | Emplois, RDV-Insertion, Dora | `prescriber` |
| Acheteur | Le Marché | (anonymous — pas de UserKind) |
| Coordinateur administratif | Emplois | `employer`, `prescriber` |
| Entreprises | Emplois, Le Marché | `employer` |
| Gestionnaire de structure | Emplois | `employer` |
| Partenaire | La Communauté | (anonymous) |
| Pilote institutionnel | Emplois, Pilotage | `labor_inspector` |
| Usager | Emplois, RDV-Insertion, Mon Recap | `job_seeker` |

Notes :
- Un même profil peut apparaître dans plusieurs segments (ex. "Directeur d'agence" est à la fois Coordinateur administratif et Gestionnaire de structure)
- `anonymous` sur Emplois = ~60% du trafic, mélange de candidats non connectés et visiteurs ponctuels
- Dora et Le Marché n'ont pas de dimension UserKind
