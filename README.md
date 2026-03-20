# Autometa

Assistant IA pour l'analyse des données métier de la Plateforme de l'inclusion.

Autometa combine les APIs **Matomo** (analytics web) et **Metabase** (données métier) pour répondre aux questions sur l'usage des services numériques de la Plateforme.

## Fonctionnalités

- **Conversations en langage naturel** — Posez des questions sur le trafic, les candidatures, les utilisateurs
- **Requêtes automatisées** — L'agent écrit et exécute des scripts Python pour interroger les APIs
- **Rapports structurés** — Génération de rapports Markdown avec graphiques Mermaid
- **Base de connaissances** — Documentation des sites, métriques et tables de données

## Structure du projet

```
.
├── knowledge/           # Base de connaissances (Markdown)
│   ├── sites/           # Documentation par site (emplois.md, pilotage.md, etc.)
│   ├── matomo/          # Référence API Matomo
│   ├── metabase/        # Référence API et tables Metabase
│   └── stats/           # Métriques et indicateurs dans Metabase
│
├── skills/              # Compétences de l'agent (skills Claude Code)
│   ├── matomo_query/    # Interrogation API Matomo
│   ├── metabase_query/  # Interrogation API Metabase
│   ├── save_report/     # Sauvegarde de rapports
│   └── sync_*/          # Synchronisation des données de référence
│
├── web/                 # Application web FastAPI
│   ├── agents/          # Backends agent (cli, cli-ollama)
│   ├── routes/          # Endpoints API et pages HTML
│   ├── templates/       # Templates Jinja2
│   └── static/          # CSS, JS, assets
│
├── data/                # Données runtime (gitignored)
│   ├── matometa.db      # Base SQLite des conversations
│   ├── scripts/         # Scripts one-off générés par l'agent
│   └── interactive/     # Fichiers téléchargeables (servis à /interactive/)
│
├── reports/             # Rapports générés
│
├── AGENTS.md            # Instructions système pour l'agent
└── docker-compose.yml   # Déploiement production
```

## Extensibilité

### Ajouter des connaissances

Les fichiers Markdown dans `knowledge/` sont lus par l'agent en fonction de la requête.
L'agent utilisera automatiquement ces informations pour contextualiser ses réponses.

### Créer un skill

Les skills sont des instructions réutilisables pour l'agent. La structure reprend [la spécification officielle](https://agentskills.io/) :

```
skills/mon_skill/
├── SKILL.md             # Instructions (lu par l'agent)
└── scripts/
    └── mon_script.py    # Code Python appelable
```

### Modifier le comportement de l'agent

Le fichier `AGENTS.md` contient le system prompt. Sections clés :

- **Domain Context** — Vocabulaire métier (IAE, SIAE, prescripteurs, etc.)
- **Query Workflow** — Processus de réponse aux questions
- **Presenting Options** — Format des boutons d'action
- **Container Environment** — Chemins et restrictions en production

## Installation locale

### Prérequis

- Python 3.11+
- Node.js 20+ (pour Claude Code CLI)
- Clés API : `MATOMO_TOKEN`, `METABASE_USER`, `METABASE_PASSWORD`

### Setup

```bash
# Cloner le repo
git clone https://github.com/gip-inclusion/Matometa.git
cd Matometa

# Environnement Python
python -m venv .venv
source .venv/bin/activate
uv sync

# Variables d'environnement
cp .env.example .env
# Éditer .env avec vos credentials

# Installer Claude Code CLI
npm install -g @anthropic-ai/claude-code

# Lancer l'application
make dev
```

L'interface est accessible sur http://127.0.0.1:5000

### Backends

Deux backends disponibles :

| Backend | Description | Prérequis |
|---------|-------------|-----------|
| `cli` (défaut) | Claude Code CLI avec OAuth Anthropic | Claude CLI installé |
| `cli-ollama` | Claude Code CLI pointé vers Ollama | Ollama en local ou en conteneur |

```bash
make dev           # Backend cli (défaut)
make dev-ollama    # Backend cli-ollama (ollama doit tourner)
```

### Configuration

Toutes les variables sont documentées dans `.env.example`. Voici les groupes principaux :

| Groupe | Variables | Requis |
|--------|-----------|--------|
| **Agent** | `AGENT_BACKEND`, `CLAUDE_CODE_OAUTH_TOKEN` | Oui |
| **Web** | `ADMIN_USERS`, `BASE_URL` | Oui |
| **Base de données** | `DATABASE_URL` | Non (SQLite par défaut) |
| **S3** | `S3_BUCKET`, `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` | Non (fichiers locaux) |
| **Sources de données** | `MATOMO_API_KEY`, `METABASE_*_API_KEY`, `NOTION_TOKEN`, `GRIST_API_KEY` | Selon `config/sources.yaml` |
| **Claude CLI** | `CLAUDE_CLI`, `CLAUDE_CODE_OAUTH_TOKEN`, `CLAUDE_CODE_DISABLE_AUTO_MEMORY` | Quand `AGENT_BACKEND=cli` |
| **Conteneur** | `CONTAINER_ENV` | Scalingo / PaaS |
| **OAuth2-Proxy** | `OAUTH2_PROXY_*` | Quand on utilise le buildpack oauth2-proxy |

## Déploiement

### Docker (auto-hébergé)

```bash
make up             # Backend cli (défaut)
make up-ollama      # Backend cli-ollama + conteneur Ollama
make up-eval        # Backend cli + Ollama disponible pour les evals
make down           # Tout arrêter

# L'app écoute sur 127.0.0.1:5002
# Configurer un reverse proxy (nginx, Caddy) pour l'exposer
```

Le conteneur Ollama est géré via un profil Docker Compose. Il ne démarre que lorsqu'il est explicitement demandé (`make up-ollama` ou `COMPOSE_PROFILES=ollama`).

### Scalingo

L'application tourne sur Scalingo dans un seul conteneur web (le process manager tourne en background dans le même process).

```bash
# Créer l'application
scalingo create matometa

# Ajouter PostgreSQL
scalingo addons-add postgresql postgresql-starter-512

# Variables obligatoires
scalingo env-set AGENT_BACKEND=cli
scalingo env-set CLAUDE_CODE_OAUTH_TOKEN=xxx
scalingo env-set ADMIN_USERS=user@example.com
scalingo env-set CONTAINER_ENV=1

# Sources de données (selon config/sources.yaml)
scalingo env-set MATOMO_API_KEY=xxx
scalingo env-set METABASE_STATS_API_KEY=xxx
scalingo env-set METABASE_DATALAKE_API_KEY=xxx

# Stockage S3 (recommandé — le filesystem Scalingo est éphémère)
scalingo env-set S3_BUCKET=matometa
scalingo env-set S3_ENDPOINT=https://s3.fr-par.scw.cloud
scalingo env-set S3_ACCESS_KEY=xxx
scalingo env-set S3_SECRET_KEY=xxx

# OAuth2-Proxy (optionnel — auth Google)
scalingo env-set OAUTH2_PROXY_PROVIDER=google
scalingo env-set OAUTH2_PROXY_CLIENT_ID=xxx
scalingo env-set OAUTH2_PROXY_CLIENT_SECRET=xxx
# ... voir .env.example pour la liste complète

# Déployer
git push scalingo main
```

**Variables automatiques Scalingo :**
- `DATABASE_URL` : fournie par l'addon PostgreSQL
- `PORT` : port d'écoute (utilisé par oauth2-proxy)

**Fichiers de configuration :**
- `Procfile` : uvicorn derrière oauth2-proxy
- `.buildpacks` : Python + oauth2-proxy
- `.python-version` : version Python
- `pyproject.toml` / `uv.lock` : dépendances (uv)

## Développement

```bash
# Tests
make test

# Evals (comparer les backends)
make up-eval                                   # Démarrer Ollama pour les evals
.venv/bin/python evals/run_eval.py             # Lancer les evals

# Synchroniser les données de référence
python -m skills.sync_sites.scripts.sync       # Sites Matomo
python -m skills.sync_metabase.scripts.sync    # Cartes Metabase
```

## Licence

Projet interne GIP Plateforme de l'inclusion.
