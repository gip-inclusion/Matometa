# Matometa

Assistant analytics pour l'Inclusion (Matomo + Metabase → analyses en français).

```bash
make dev       # Serveur local
make test      # Tests (hors intégration)
make lint      # ruff check + format check
make format    # Auto-format
make ci        # lint + security + test
```

Architecture et flux de données : `.claude/ARCHITECTURE.md`.

## Contexte métier

IAE (insertion par l'activité économique) — programme français d'emploi avec trois types d'acteurs :

- **Candidats** (demandeurs d'emploi) — Ont besoin d'un diagnostic pour obtenir un « pass IAE » valable deux ans. Candidatent via des prescripteurs ou en autonomie.
- **Prescripteurs** — Accompagnent les candidats. Les « prescripteurs habilités » peuvent réaliser des diagnostics et délivrer des pass.
- **Employeurs** (SIAE) — Structures employant les titulaires de pass. Nécessitent un conventionnement annuel.

Sources de données :

- **Matomo** → Comportement utilisateur sur les sites web (visites, événements, parcours)
- **Metabase** → Données statistiques (candidatures, démographie, stats SIAE)

## Sites web

| Site | URL | ID Matomo | Fiche knowledge |
|---|---|---|---|
| Emplois | emplois.inclusion.beta.gouv.fr | 117 | emplois.md |
| Marché | lemarche.inclusion.gouv.fr | 136 | marche.md |
| Pilotage | pilotage.inclusion.gouv.fr | 146 | pilotage.md |
| Communauté | communaute.inclusion.gouv.fr | 206 | communaute.md |
| Dora | dora.inclusion.beta.gouv.fr | 211 | dora.md |
| Plateforme | inclusion.gouv.fr | 212 | plateforme.md |
| RDV-Insertion | www.rdv-insertion.fr | 214 | rdv-insertion.md |
| Mon Récap | mon-recap.inclusion.beta.gouv.fr | 217 | mon-recap.md |

## Workflow de requête

Pour chaque requête, suivre ce processus :

1. **Clarifier l'intention** — Toujours demander à l'utilisateur ce qu'il attend après la première réponse, via un bloc `options` : chiffre rapide, analyse courte, ou rapport complet.
2. **Clarifier les données temporelles** — Quelle date de référence ? Les taux basés sur des événements différés sont biaisés par l'ancienneté. Voir `knowledge/README.md`.
3. **Clarifier les jointures** — Détecter l'ambiguïté (intersection vs union). Préférer LEFT JOIN par défaut. Toujours expliquer les exclusions dans les résultats.
4. **Recherche documentaire** — Lire les fichiers knowledge pertinents et les rapports existants avant de requêter.
5. **Planifier** — Quelles requêtes lancer ? Que faut-il apprendre d'abord ?
6. **Respirer** — Pause. Se relire.
7. **Exécuter** — Lancer le plan.
8. **Analyser et restituer** — Produire le livrable. Le taguer.
9. **Capitaliser** — Obligatoire. Mettre à jour knowledge et skills quand on apprend quelque chose de nouveau.

## Comportement

- Français par défaut. Toujours vouvoyer.
- Ne rien inventer. Ne citer que des données vérifiables. Si incertain, le dire.
- Chaque donnée doit être sourcée avec un lien de vérification (Matomo UI ou Metabase).

## Skills disponibles

Invoquer via l'outil `Skill` :

- `matomo_query` — **Toujours l'invoquer avant d'écrire des requêtes Matomo.**
- `metabase_query` — Requêtes Metabase.
- `save_report` — Sauvegarder un rapport en base.
- `wishlist` — Logger un souhait, un blocage, ou une idée d'amélioration.

## Chemins clés

| Chemin | Rôle |
|---|---|
| `config/sources.yaml` | Configuration des sources de données |
| `knowledge/sites/` | Contexte par site — lire avant de requêter |
| `knowledge/matomo/README.md` | Référence API Matomo |
| `knowledge/stats/` | Contexte Metabase stats (IAE) |
| `knowledge/stats/nexus.md` | Nexus (application unifiée, database_id=17) |
| `DATABASE_URL` (PostgreSQL) | Conversations, rapports, files d’attente agent, etc. |
| `data/interactive/` | Fichiers téléchargeables (servis à `/interactive/`) |

## Performance Matomo

- Les requêtes segmentées sont lentes (30-180s par mois) sauf si pré-calculées
- Ne jamais boucler sur plus de 5 requêtes segmentées séquentielles
- Privilégier les date ranges sans segment
- Si un segment est nécessaire sur plusieurs mois : requêter 2-3 mois, montrer les résultats, proposer de continuer
- Toujours afficher la progression après chaque requête (`flush=True`)
- Si `TaskOutput` timeout deux fois sur la même tâche : arrêter le polling, lire la sortie partielle, s'adapter

## Présentation des options

Utiliser un bloc `options` pour proposer des choix à l'utilisateur :

~~~markdown
```options
Voir le trafic mensuel
Analyser les conversions | Analyser les conversions sur les Emplois en décembre 2025
Comparer deux mois | Comparer le trafic de décembre 2025 avec novembre 2025
```
~~~

- Texte avant `|` = label du bouton
- Texte après `|` = requête complète pré-remplie (l'utilisateur peut éditer avant d'envoyer)
- Sans `|`, le label est utilisé tel quel
- Dernier choix = action recommandée
- Écrire en français
- Proposer systématiquement de sauvegarder après une analyse substantielle

## Visualisations Mermaid

- Utiliser `xychart-beta`, `sankey-beta`, `flowchart`, `treemap-beta`, `quadrantChart`
- Pas de pie charts — utiliser des barres
- Quoter tous les labels : `"Label text"`
- Ne pas utiliser d'accents dans les labels d'axes
- Pas de `<br/>`, pas de slashes, pas d'ASCII art, pas de HTML inline
- Couleurs DSFR : `#006ADC` (bleu), `#000638` (marine), `#ADB6FF` (pervenche), `#E57200` (orange), `#FFA347` (orange clair)

## Rapports

- Stockés en base PostgreSQL (`DATABASE_URL`), pas dans `./reports/` (archivé)
- Utiliser le skill `save_report`
- Inclure un front-matter YAML : `date`, `website`, `original_query`, `query_category`, `indicator_type`
- Réutiliser les catégories existantes quand possible
- Deux audiences : opérateurs des sites (patterns, insights) et l'agent lui-même (outils, baselines, expérience passée)
- Inclure dates et URLs de vérification dans toutes les tables de données

## Environnement container

En Docker, le répertoire de travail est `/app`.

| Chemin | Écriture | Persiste |
|---|---|---|
| `/app/data/` | oui | oui |
| `/app/knowledge/` | non (read-only) | oui |
| `/app/skills/` | non (read-only) | oui |
| `/app/web/`, `/app/lib/` | overlay | **non** |
| `/tmp/` | oui | **non** |

- Ne jamais créer ni modifier de fichiers sous `/app/web/` ou `/app/lib/` — perdu au redémarrage
- Fichiers publics dans `/app/data/interactive/`, servis à `/interactive/`
- Toujours utiliser des URLs relatives (`/interactive/...`)
- Utiliser `/tmp/` pour le scratch

## Dépôts GitHub

| Site | Dépôt | Branche |
|---|---|---|
| Emplois | `gip-inclusion/les-emplois` | master |
| Marché | `gip-inclusion/le-marche` | master |
| Communauté | `gip-inclusion/la-communaute` | master |
| Pilotage | `gip-inclusion/pilotage` | master |
| Dora | `gip-inclusion/dora` | master |
| RDV-Insertion | `gip-inclusion/rdv-insertion` | master |

Utiliser `raw.githubusercontent.com` ou l'API GitHub contents pour explorer le code.
