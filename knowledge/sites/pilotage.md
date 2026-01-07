# Pilotage

- URL : https://pilotage.inclusion.gouv.fr
- ID site Matomo : 146
- GitHub : https://github.com/gip-inclusion/pilotage

## Description

Pilotage de l'inclusion est une plateforme de tableaux de bord interne destinée aux professionnels de l'inclusion. Elle fournit :
- Des statistiques publiques sur l'inclusion par l'emploi (tableaux de bord publics)
- Des tableaux de bord privés spécifiques aux organisations
- Des données provenant d'iframes Metabase intégrées
- Un abonnement à l'infolettre

Il s'agit d'un outil interne à faible trafic utilisé par les professionnels de l'écosystème de l'inclusion, et non d'un site web grand public.

## Trafic de référence (2025)

Données récupérées le 6 janvier 2026 via l'API Matomo.

### Statistiques mensuelles de visiteurs

| Mois    | Visiteurs uniques | Visites | Moy. quotidienne visiteurs | Moy. quotidienne visites |
|---------|-------------------|---------|----------------------------|--------------------------|
| 2025-01 |             1 177 |   1 529 |                         38 |                       49 |
| 2025-02 |             2 218 |   2 800 |                         79 |                      100 |
| 2025-03 |             1 010 |   1 363 |                         33 |                       44 |
| 2025-04 |                 - |       - |                          - |                        - |
| 2025-05 |               288 |     346 |                          9 |                       11 |
| 2025-06 |             5 731 |   6 460 |                        191 |                      215 |
| 2025-07 |             1 239 |   1 572 |                         40 |                       51 |
| 2025-08 |               710 |     876 |                         23 |                       28 |
| 2025-09 |             3 226 |   3 958 |                        108 |                      132 |
| 2025-10 |             1 462 |   1 905 |                         47 |                       61 |
| 2025-11 |               975 |   1 266 |                         32 |                       42 |
| 2025-12 |               686 |     921 |                         22 |                       30 |

**Fourchette typique :** 9-191 visiteurs uniques/jour, 11-215 visites/jour.

### Métriques d'engagement

| Mois    | Taux de rebond | Actions/visite | Temps moyen sur le site |
|---------|----------------|----------------|-------------------------|
| 2025-01 |            45% |              3 |                  3m 02s |
| 2025-02 |            59% |            2,3 |                  2m 25s |
| 2025-03 |            43% |              3 |                  3m 13s |
| 2025-04 |              - |              - |                       - |
| 2025-05 |            46% |            3,1 |                  2m 36s |
| 2025-06 |            43% |            2,1 |                  2m 09s |
| 2025-07 |            51% |            2,5 |                  1m 53s |
| 2025-08 |            53% |            2,5 |                  2m 09s |
| 2025-09 |            38% |            2,4 |                  2m 09s |
| 2025-10 |            53% |            2,8 |                  2m 14s |
| 2025-11 |            52% |            2,7 |                  2m 27s |
| 2025-12 |            42% |            3,3 |                  5m 38s |

## Dimensions personnalisées

**Aucune dimension personnalisée configurée** pour ce site.

Le site ne suit pas les types d'utilisateurs ni les informations d'organisation via les dimensions personnalisées Matomo.

## Segments enregistrés

*Récupérés le 6 janvier 2026 via l'API Matomo.*

| Nom | Définition |
|-----|------------|
| ACQUISITION - jour de l'événement | `visitorFirstVisitTime>2024-02-01%252000%253A00%253A01;vis...` |
| CONTENT - Page tdb privés | `pageUrl=@https%253A%252F%252Fpilotage.inclusion.beta.gouv...` |
| CONTENT- ANALYSE DE LOFFRE DINSERTION | `pageUrl==https%253A%252F%252Fpilotage.inclusion.beta.gouv...` |
| RETENTION - 15/75 | `daysSinceLastVisit<75;daysSinceLastVisit>15` |
| RETENTION - 30/75 | `daysSinceLastVisit>30;daysSinceLastVisit<75` |
| RETENTION - derniere visite <45j | `daysSinceLastVisit<45` |
| RETENTION - test 1-30j | `daysSinceLastVisit>=1;daysSinceLastVisit<32` |
| RETENTION - user retenus 30j - visite tdb public | `pageTitle=@Tableaux%2520de%2520bord%2520publics;daysSince...` |
| VISITS - Visites du post du 25/06 | `pageUrl=@%253Futm_name%253DC0-post-25-06-2023` |

## Événements Matomo

### Implémentation

Pilotage utilise **Matomo Tag Manager** (conteneur `czDcW7tH`) pour le suivi des événements, et non du code inline.

Le conteneur Tag Manager (version 20251208.04) est chargé via :
```html
<script src="{{ MATOMO_BASE_URL }}/js/container_czDcW7tH.js"></script>
```

### Configuration

Fonctionnalités activées via Tag Manager :
- Link tracking
- Form analytics
- Media analytics
- JS error tracking
- Heartbeat timer

### Catégories d'événements

Seulement 2 catégories d'événements intentionnels suivies (en date de décembre 2025) :

#### Bouton (10 événements en 2025)

| Action | Nom | Description |
|--------|-----|-------------|
| Bouton infolettre | `{PagePath}` | Clic sur le bouton d'infolettre. Le nom est dynamique, contient le chemin de la page où le clic a eu lieu. |

Trigger : Clic sur un élément avec le texte "Infolettre"

#### Navigation (configuré mais pas encore déclenché dans les données)

| Action | Nom | Description |
|--------|-----|-------------|
| Clic Tableaux de bord prives | Clic navigation Tableaux de bord prives | Clic de navigation vers les tableaux de bord privés |

Trigger : Clic sur un élément avec le texte "Tableaux de bord prives"

#### Erreurs JavaScript (automatique)

Les erreurs JS sont automatiquement capturées par Matomo. En décembre 2025 :
- `https://tally.so/widgets/embed.js:0` - Erreur de script provenant de l'intégration du formulaire Tally
- Erreurs de script inline occasionnelles sur `/tableaux-de-bord/zoom-esat/`

### Événements du code source (pas encore actifs)

Le code source contient des attributs `data-matomo-*` pour un suivi futur :

```html
<!-- Dans home_section_accompagne.html -->
<a href="..." data-matomo-category="statistiques" data-matomo-action="click" data-matomo-option="simplifier">
<a href="..." data-matomo-category="statistiques" data-matomo-action="click" data-matomo-option="enrichir">
<a href="..." data-matomo-category="statistiques" data-matomo-action="click" data-matomo-option="objectiver">
<a href="..." data-matomo-category="statistiques" data-matomo-action="click" data-matomo-option="faciliter">
```

Ces attributs nécessitent un handler JS pour déclencher les événements, qui n'est pas actuellement implémenté. Envisagez d'ajouter un listener pour les attributs `data-matomo-*`.

### Notes

- Volume d'événements très faible (~10 événements intentionnels par an)
- Le tracking repose principalement sur les pageviews, pas les événements
- Le site intègre des iframes Metabase qui ont leur propre analytics
- Des popups de formulaires Tally sont utilisées pour la collecte de feedback (affichées après 45s, max une fois par 14 jours)
- Consentement aux cookies via tarteaucitron.js

## Stack technique

- Django templates
- Iframes Metabase intégrées pour les dashboards
- Tally.so pour les formulaires de feedback
- Livestorm pour l'intégration de webinaires
- tarteaucitron.js pour le cookie consent
- iframe-resizer pour les iframes responsive
