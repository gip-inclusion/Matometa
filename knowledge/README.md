# Base de connaissances

Ces documents constituent la mémoire de l'agent Matometa. Ils sont lus avant chaque requête pour contextualiser les réponses.

## Quand sont-ils utilisés ?

1. **Avant chaque requête** : l'agent lit le fichier du site concerné (ex: `sites/emplois.md`) pour connaître les dimensions, segments et événements disponibles.

2. **Pour les requêtes API** : l'agent consulte `matomo/` ou `metabase/` pour la syntaxe exacte des méthodes.

3. **Pour les analyses thématiques** : l'agent lit `stats/` pour comprendre le contexte métier (candidats, prescripteurs, etc.).

## Structure des dossiers

### `sites/`
Un fichier par site web. Contient :
- ID du site et URL
- Dimensions personnalisées (UserKind, département, etc.)
- Segments sauvegardés (pré-archivés, rapides)
- Événements trackés
- Baselines de trafic

**Fichiers** : `emplois.md`, `dora.md`, `marche.md`, `communaute.md`, `pilotage.md`, `plateforme.md`, `rdv-insertion.md`, `mon-recap.md`

### `matomo/`
Documentation technique de l'API Matomo :
- `README.md` : vue d'ensemble et méthodes principales
- `core-modules.md` : VisitsSummary, Actions, Events, Referrers
- `heatmaps.md` : HeatmapSessionRecording (premium)
- `funnels.md` : Funnels (premium)
- `cohorts.md` : Cohorts (premium)

### `metabase/`
Documentation de l'API Metabase :
- `README.md` : authentification et endpoints
- `cards.db` : base SQLite des questions/dashboards disponibles

### `stats/`
Contexte métier et données Metabase :
- `_index.md` : vue d'ensemble des dashboards
- `candidats.md`, `prescribers.md`, `pass-iae.md` : thématiques IAE
- `cards/` : fiches par thème (topic-candidatures.md, etc.)
- `dashboards/` : documentation des tableaux de bord

## Règles d'édition

1. **Pas de prose** : phrases courtes, listes, tableaux. L'agent doit trouver l'info vite.

2. **Exemples concrets** : inclure des appels API testés avec leurs résultats.

3. **Dates de vérification** : indiquer quand une info a été testée (ex: "Testé 2026-01-11").

4. **Un sujet par fichier** : ne pas mélanger plusieurs sites ou modules.

5. **Markdown simple** : titres, listes, tableaux, blocs de code. Pas de HTML.

## Mise à jour

Les fichiers sont versionnés dans git. Pour proposer une modification :
1. Créer une branche
2. Modifier le fichier
3. Ouvrir une pull request

Ou utiliser le lien "Faire une pull-request" depuis l'interface Connaissances.
