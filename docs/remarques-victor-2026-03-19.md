# Revue d'architecture Matometa — 19 mars 2026

## Vue d'ensemble

Matometa est un assistant analytics interne propulsé par Claude, conçu pour le GIP de l'Inclusion. Application web permettant à des utilisateurs non-techniques de poser des questions en français sur les données web (Matomo) et métier (Metabase), et d'obtenir des réponses sourcées en langage naturel.

L'agent Claude est le cerveau : il reçoit un prompt système de ~830 lignes (`AGENTS.md`), dispose de skills et d'une base de connaissances documentaire, et peut exécuter du code Python pour interroger les APIs.

**Taille du codebase** : ~27 400 lignes Python, 109 fichiers.

---

## Architecture globale

```
Utilisateur (navigateur)
    │
    ▼
FastAPI (single worker, uvicorn)
    ├── Routes HTML (Jinja2 SSR)
    ├── Routes API REST (/api/conversations, /api/reports, /api/research...)
    ├── SSE streaming (réponse agent → navigateur en temps réel)
    │
    ├── ProcessManager (asyncio task in-process)
    │       ├── Lit pm_commands (table DB, file d'attente)
    │       ├── Spawne un AgentBackend (CLI subprocess ou SDK)
    │       ├── Parse les événements stream-json du CLI
    │       ├── Persiste messages, tool_use, tool_result en DB
    │       └── Notifie le SSE via SignalRegistry (dict in-memory)
    │
    └── Lifespan: S3 sync watcher, PM task
```

Parti pris fondamental : tout tourne dans un seul worker. Le ProcessManager et le SSE handler partagent un `SignalRegistry` en mémoire (dict Python). Choix conscient et documenté (`signals.py:8-9`), mais qui impose une limite dure de scalabilité horizontale.

---

## Technologies

| Couche | Stack |
|---|---|
| Web | FastAPI + Jinja2 + SSE |
| Agent | Claude Code CLI (subprocess) ou claude-agent-sdk |
| DB principale | SQLite (dev) / PostgreSQL (prod), dual-backend via `ConnectionWrapper` |
| DB recherche | SQLite séparé (`notion_research.db`) avec embeddings |
| Embeddings | Qwen3-Embedding-0.6B via DeepInfra, similarité via simsimd |
| Stockage fichiers | S3 (MinIO local / Scalingo) avec fallback filesystem |
| APIs externes | Matomo, Metabase (3 instances), Notion, Slack, GitHub, Livestorm, Grist |
| Déploiement | Docker / Scalingo PaaS |
| Python | 3.11, géré par uv |

---

## Flux de données principaux

### 1. Conversation utilisateur → Agent → Réponse

```
POST /api/conversations/{id}/messages
  → store.add_message() (DB)
  → store.enqueue_pm_command("run") (DB: pm_commands)
  → PM poll (0.5s) → claim_pending → _run_agent()
  → CLIBackend: spawne `claude --output-format stream-json -p <prompt>`
  → Parse ligne par ligne (JSON streaming)
  → Pour chaque event: store.add_message() + signals.notify_message()
  → SSE handler: await signals.wait_for_message() → DB read → yield SSE event
  → Navigateur: EventSource reconstitue la réponse
```

### 2. Agent → APIs analytics

```
Agent (dans le subprocess claude) exécute du Python:
  from lib.query import execute_matomo_query, execute_metabase_query

  → _sources.py charge config/sources.yaml + env vars
  → MatomoAPI / MetabaseAPI (requests.Session avec retry)
  → emit_api_signal() (print JSON sur stdout)
  → PM parse les signaux depuis tool_result content
  → Stockés en DB pour la sidebar d'observabilité
```

### 3. Recherche sémantique (corpus terrain)

```
Notion → sync_notion_research.py → embed_notion_research.py
  → notion_research.db (pages, blocks, chunks, embeddings BLOB float32)

GET /api/research/search?q=...
  → DeepInfra encode la query → array.array('f')
  → Charge ~1700 embeddings en mémoire (cache thread-safe)
  → simsimd.cosine() pour chaque chunk (<1ms total)
  → Dedup par page, top-K → JSON
```

---

## Bases de données

| BD | Usage | Backend |
|---|---|---|
| `data/matometa.db` / PostgreSQL | Conversations, messages, rapports, tags, uploads, cron_runs, pm_commands | SQLite (dev) / PG (prod) |
| `data/notion_research.db` | Corpus recherche terrain, embeddings | SQLite only (read-only) |
| `data/metabase_cards.db` | Inventaire des questions Metabase | SQLite only (synced) |

---

## Ce qui fonctionne bien

1. **Abstraction DB dual-backend** (`db.py`) — Le `ConnectionWrapper` permet de développer en SQLite et déployer sur PostgreSQL avec le même code. La conversion `?` → `%s`, le `insert_and_get_id` avec `RETURNING`, c'est propre et pragmatique.

2. **Signal registry** (`signals.py`) — Élégant pour éviter le polling DB sur le SSE. Le mécanisme de counter monotone comme safety net est bien pensé. L'eviction des signaux stale toutes les 5s évite les fuites mémoire.

3. **Observabilité** — Le système de `api_signals` (émission structurée sur stdout, parsing côté PM) donne une traçabilité complète des appels API, avec liens cliquables vers Matomo/Metabase dans la sidebar UI.

4. **Résilience du CLI backend** — La détection de session corrompue avec retry automatique sans session (`cli.py:69-95`) est un bon pattern défensif.

5. **Knowledge base documentaire** — L'approche fichiers markdown dans `knowledge/` avec sync automatisé (sites, metabase cards) est pragmatique et maintenable par des humains.

---

## Points potentiellement problématiques

### Architecture

- **Single-worker = point de fragilité.** Tout le processus (web, PM, SSE, S3 sync) tourne dans un seul process Python. Si le PM bloque ou si un agent consomme beaucoup de mémoire, tout l'applicatif est impacté. Le commentaire le reconnaît, mais ça reste un SPOF.

- **Couplage PM ↔ SSE via in-memory signals.** Performant mais empêche structurellement de scaler. Une migration vers Redis pub/sub ou PostgreSQL `LISTEN/NOTIFY` permettrait du multi-worker sans réécrire le modèle.

### Base de données

- **Migrations manuelles** (`schema.py`) — Le système fonctionne mais c'est du code bespoke qui reproduit ce que font Alembic, django-migrate, etc. La cascade de `if current_version < N: _migrate_to_vN()` plus le "safety" de `_migrate_to_v15/17/18/19/20()` appelé systématiquement en dehors des conditions (lignes 88-92) sent le patch défensif. Avec 20 versions, ça tient, mais à 50+ ça sera fragile.

- **Pas de `ON DELETE CASCADE` partout** — `messages` a une FK sans CASCADE, `reports` n'a pas de FK du tout vers `conversations`. Les contraintes d'intégrité sont inégales.

- **Dates en TEXT** — Toutes les colonnes temporelles (`created_at`, `updated_at`, `pinned_at`) sont des `TEXT`. Fonctionnel, mais ça empêche les comparaisons natives et les index temporels efficaces côté PostgreSQL (qui a `TIMESTAMPTZ`).

### Réinvention de la roue

- Il semblerait que les dépendances soient parfois dupliquées, souvent pas à jour et vraiment pas minimales...

- Mettre en place un packaging Python propre, une base de tests clean...

- **`ConnectionWrapper`** reproduit une sous-partie de ce que fait SQLAlchemy Core (sans l'ORM). Léger et contrôlé, mais le coût : pas de migration tooling, pas de type safety sur les requêtes, SQL brut partout dans `database.py` (1613 lignes de SQL à la main).

- **`lib/readers.py`** (305 lignes) — Lecture Excel/Word/PDF. Honnête, mais des libs comme `textract` ou `unstructured` font ça mieux. Marginal si c'est stable.

- **Le client Matomo** (`_matomo.py`, 491 lignes) — Beaucoup de méthodes boilerplate (`get_pages`, `get_event_categories`, `get_event_actions`, `get_event_names`...) qui ne sont que des variantes de `_request(method_name, params)`. Le pattern est toujours le même : construire un dict params, ajouter optionnellement `segment`, appeler `_request`. Ça pourrait être factorisé en ~50 lignes avec un `__getattr__` dynamique ou simplement supprimé au profit de `api.request("Events.getCategory", **params)` qui existe déjà.

- **Duplication `search_corpus` / route `search`** — Dans `research.py`, les fonctions helper `search_corpus()` et `find_similar_pages()` dupliquent quasi-identiquement le code des routes `/search` et `/similar/{chunk_id}`. Les routes devraient simplement appeler les helpers.

### Sécurité

- **`--dangerously-skip-permissions`** en container (`cli.py:133`). Documenté comme intentionnel (le container est la frontière de sécurité), mais ça donne à l'agent un accès shell complet. Un agent compromis par injection de prompt pourrait exfiltrer des secrets d'environnement.

- **`sql.replace("?", "%s")`** (`db.py:100`) — Simple mais fragile : si une valeur contient littéralement `?`, la substitution casse. En pratique rare avec du SQL paramétré, mais un vrai ORM ou driver évite ce piège.

### Qualité du code

- **`database.py` à 1613 lignes** — God-object. `ConversationStore` fait tout : CRUD conversations, messages, rapports, tags, uploads, cron, pm_commands, heartbeat. Un découpage par domaine (conversations, reports, cron, pm) serait bienvenu.

- **Threads daemon pour les side-effects** — Titre generation (`conversations.py:50`), tag generation, failure notification (`pm.py:232`). Pas de gestion d'erreur visible côté appelant, pas de backpressure. Si le LLM est lent, les threads s'accumulent silencieusement.

---

## Migrations recommandées

1. **Adopter Alembic** pour les migrations SQL. Le système actuel fonctionne mais ne scale pas bien : pas de rollback, pas de génération automatique depuis un modèle, les "safety" post-migration (`schema.py:88-92`) indiquent que la confiance dans l'état de la DB est fragile.

2. **Normaliser les types temporels** : passer de `TEXT` à `TIMESTAMP` en PostgreSQL (tout en gardant `TEXT` côté SQLite) simplifierait les requêtes de tri/filtrage.

3. **Séparer `ConversationStore`** en modules plus petits. C'est la migration architecturale la plus utile à court terme.

---

## Isolation entre couches

```
web/               → Application layer (routes, templates, SSE)
web/agents/        → Agent abstraction (CLI/SDK backends)
web/db.py          → Infrastructure DB (connection pool)
web/database.py    → Business logic DB (models + queries) ← trop gros
web/signals.py     → In-process communication (PM → SSE)
lib/               → Data layer (API clients, query execution)
skills/            → Agent capabilities (instructions + scripts)
knowledge/         → Domain knowledge (markdown files)
config/            → External service configuration
```

L'isolation est correcte en intention. `lib/` est bien séparé de `web/` : les clients API ne connaissent pas FastAPI. Les skills sont des unités autonomes. Le point faible c'est `web/database.py` qui mélange domaines (conversations, rapports, cron, PM) et `web/storage.py` qui n'est qu'un re-export de `database.py`.

---

## Résumé

Matometa est un projet impressionnant par sa portée (agent IA + analytics + recherche sémantique + observabilité), pragmatique dans ses choix (SQLite dual-backend, single-worker, CLI subprocess), mais qui accumule de la dette technique dans sa couche DB/storage et pourrait bénéficier d'un découpage du god-object `database.py` et d'un outil de migration standard.

---

## Remarques complémentaires (Makefile, PM, S3)

- **Makefile vs `.env`** — Probablement trop de cibles dans le Makefile alors qu'en réalité on ne devrait avoir qu'à changer des variables d'environnement pour basculer de backend ou activer Ollama (Docker inclus).

- **Process Manager lancé deux fois** — Le Makefile peut lancer plusieurs processus (`python -m web.pm` en arrière-plan + `python -m web.app`) alors que toute l'app est faite pour tout lancer dans le **lifespan** FastAPI. Risque de PM dupliqué (deux boucles qui polluent `pm_commands`).

- **`sync_to_s3` vs asyncio** — On lance un **thread** dédié pour le watcher S3 (`sync_to_s3`) en parallèle des boucles **async** du reste de l'app → mélange thread / asyncio, code smell (shutdown, tests, raisonnement sur l'état).

- **`USE_S3`** — Aujourd'hui S3 est optionnel si les credentials manquent. En prod (filesystem éphémère), ne devrait-on pas exiger S3 configuré (ou **fail-fast**) plutôt que de continuer en fichiers locaux par défaut ?

- **`config.DEBUG` / `WEB_DEBUG`** — Doit absolument être à `False` partout par défaut, et ne passer à `True` que si on le configure **explicitement** en variable d'environnement (éviter tout défaut ou gabarit — ex. `.env.example` — qui laisserait le debug activé sans intention claire).

---

## Workflow & contribution

### PR template

Ajouter un **template de Pull Request** au repo (`.github/pull_request_template.md`). S'inspirer du format par défaut fourni par `httpx` (checklist intégrée). Rédiger en **français**, cohérent avec le reste du projet. Le template doit inclure au minimum :

- Description du changement
- Checklist :
  - [ ] J'ai lancé l'application en local
  - [ ] Je me suis relu
  - [ ] Les tests passent (`make test`)
  - [ ] Le lint passe (`make lint`)

### Conventions de nommage des branches

Définir et documenter une convention de nommage des branches. Proposition :

```
<pseudo>/<type>/<description-courte>
```

Types : `feat`, `fix`, `chore`, `docs`, `refactor`. Exemples : `vperron/feat/pr-template`, `vperron/fix/pm-duplicate-loop`.

### Pre-commit hooks

Mettre en place **pre-commit** (https://pre-commit.com) avec a minima :

- `ruff check` + `ruff format` (déjà dans `make lint`, mais pas bloquant au commit)
- Détection de secrets (`detect-secrets` ou `gitleaks`)
- Vérification des fichiers YAML/JSON

Objectif : empêcher les commits cassés d'arriver sur la branche, plutôt que de corriger après coup en CI.

### Commits atomiques

Adopter une discipline de **commits atomiques** : chaque commit doit être auto-suffisant, compilable, et ne porter que sur un seul changement logique. Pas de commits `__wip` qui mélangent code, config et docs. Squasher avant merge si nécessaire.

---

## Architecture — compléments

### Séparation server / client

Aujourd'hui `web/` mélange la webapp (FastAPI, routes, templates, SSE) avec la logique métier DB (`database.py`) et les agents (`agents/`). Toutes les couches qui manipulent du SQL devraient vivre dans un package séparé — appelons-le `server` ou `core` — indépendant du framework web. La webapp ne ferait qu'importer et appeler.

Côté client (`lib/`), l'isolation est déjà meilleure mais la frontière est floue : `lib/query.py` fait du logging en DB, `lib/_sources.py` lit la config. Clarifier : `lib/` = clients d'API externes purs (Matomo, Metabase), `core/` ou `server/` = logique métier et persistance, `web/` = HTTP/SSE/templates.

### Process Manager — questions ouvertes

Le PM est déjà identifié comme fragile (cf. supra), mais des questions restent :

- **Combien de workers/serveurs sont nécessaires ?** Aujourd'hui un seul worker. Si on veut de la concurrence (plusieurs agents en parallèle, ou simplement du SSE qui ne bloque pas les routes), il faut soit multi-worker (mais ça casse les signals in-memory), soit externaliser la coordination (Redis, PG LISTEN/NOTIFY).
- **La boucle en mémoire n'est pas viable.** Le `SignalRegistry` en dict Python empêche tout déploiement multi-process. C'est un plafond dur, pas juste un inconvénient. La migration vers un broker externe devrait être planifiée avant toute mise à l'échelle.

### SQLAlchemy + Alembic

La recommandation Alembic existe déjà (cf. « Migrations recommandées ») mais il faut aller plus loin : adopter **SQLAlchemy Core** (pas nécessairement l'ORM complet) pour :

- Avoir un schéma déclaratif (les `CREATE TABLE` aujourd'hui sont dans des chaînes SQL brutes)
- Générer les migrations automatiquement via Alembic `--autogenerate`
- Supprimer le `ConnectionWrapper` bespoke et le `sql.replace("?", "%s")`
- Bénéficier du type-checking sur les requêtes

Ce chantier est un prérequis pour découper proprement `database.py` (1614 lignes) : on ne peut pas refactorer sereinement 1600 lignes de SQL brut sans filet.

---

## Hygiène technique

### Audit des dépendances

Faire un audit des dépendances (`uv pip list` vs imports réels). Suspicion de dépendances inutilisées ou redondantes. Objectifs :

- Supprimer ce qui n'est pas importé
- Identifier les doublons fonctionnels (ex. `requests` vs `httpx` si les deux sont présents)
- Vérifier les versions : pas de pinning trop ancien, pas de ranges trop larges
- Documenter pourquoi chaque dépendance non-évidente est là

