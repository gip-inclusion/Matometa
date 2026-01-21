# Matometa

Assistant IA pour l'analyse des données métier de la Plateforme de l'inclusion.

Matometa combine les APIs **Matomo** (analytics web) et **Metabase** (données métier) pour répondre aux questions sur l'usage des services numériques de la Plateforme.

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
├── web/                 # Application web Flask
│   ├── agents/          # Backends CLI et SDK pour Claude
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
pip install -r requirements.txt

# Variables d'environnement
cp .env.example .env
# Éditer .env avec vos credentials

# Installer Claude Code CLI
npm install -g @anthropic-ai/claude-code

# Lancer l'application
python -m web.app
```

L'interface est accessible sur http://127.0.0.1:5000

### Configuration

Variables d'environnement principales :

| Variable | Description |
|----------|-------------|
| `MATOMO_TOKEN` | Token API Matomo |
| `METABASE_USER` | Email utilisateur Metabase |
| `METABASE_PASSWORD` | Mot de passe Metabase |
| `ANTHROPIC_API_KEY` | Clé API Anthropic (optionnel, OAuth par défaut) |
| `AGENT_BACKEND` | `cli` (défaut) ou `sdk` |
| `DB_BACKEND` | `sqlite` (défaut) ou `postgres` |
| `ADMIN_USERS` | Emails des admins (séparés par virgules) |

## Déploiement

### Docker (auto-hébergé)

```bash
# Build et run avec Docker
docker-compose up -d

# L'app écoute sur 127.0.0.1:5002
# Configurer un reverse proxy (nginx, Caddy) pour l'exposer
```

Le conteneur utilise OAuth2-Proxy pour l'authentification. L'email de l'utilisateur est passé via le header `X-Forwarded-Email`.

### Scalingo

L'application est prête pour un déploiement sur Scalingo avec PostgreSQL.

```bash
# Créer l'application
scalingo create matometa

# Ajouter PostgreSQL
scalingo addons-add postgresql postgresql-starter-512

# Configurer les variables d'environnement
scalingo env-set DB_BACKEND=postgres
scalingo env-set MATOMO_TOKEN=xxx
scalingo env-set METABASE_USER=xxx
scalingo env-set METABASE_PASSWORD=xxx
scalingo env-set ANTHROPIC_API_KEY=xxx
scalingo env-set ADMIN_USERS=user@example.com

# (Optionnel) Stockage S3 pour les fichiers interactifs
scalingo env-set S3_BUCKET=matometa-files
scalingo env-set S3_ENDPOINT=https://s3.fr-par.scw.cloud
scalingo env-set S3_ACCESS_KEY=xxx
scalingo env-set S3_SECRET_KEY=xxx

# Déployer
git push scalingo main
```

**Variables automatiques Scalingo :**
- `DATABASE_URL` : fournie automatiquement par l'addon PostgreSQL
- `PORT` : port d'écoute (utilisé par le Procfile)

**Fichiers de configuration :**
- `Procfile` : commande de démarrage gunicorn
- `runtime.txt` : version Python (3.11)

## Développement

```bash
# Tests
pytest

# Linter
ruff check .

# Synchroniser les données de référence
python -m skills.sync_sites.scripts.sync      # Sites Matomo
python -m skills.sync_metabase.scripts.sync   # Cartes Metabase
```

## Licence

Projet interne GIP Plateforme de l'inclusion.
