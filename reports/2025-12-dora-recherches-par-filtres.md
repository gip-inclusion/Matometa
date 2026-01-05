---
date: 2026-01-03
website: dora
original_query: "How many searches per day in December, in DORA? Give me the breakdown of queries made (exclude textual queries for now), factoring: the category of the query, and whether a result was clicked or not after."
query_category: Analyse des recherches
indicator_type: [funnel, engagement, geographic]
---

# DORA : Recherches par filtres - Décembre 2025

## Résumé

Analyse des recherches effectuées via l'interface de filtres (hors recherche textuelle) sur DORA en décembre 2025.

| Métrique | Valeur |
|----------|--------|
| Visites page recherche | 71 038 |
| Clics sur résultats | 40 655 |
| **Taux de clic** | **57,2%** |
| Taux sans clic | 42,8% |

## Funnel de recherche

```
┌─────────────────────────────────────────────────────────────────────────┐
│  VISITES PAGE RECHERCHE                                       71 038   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
        ┌───────────────────────┐       ┌───────────────────────┐
        │  CLIC SUR SERVICE     │       │  SANS CLIC            │
        │       30 765          │       │       30 383          │
        │       (43,3%)         │       │       (42,8%)         │
        └───────────────────────┘       └───────────────────────┘
                    │
                    ▼
        ┌───────────────────────┐
        │  CLIC SUR STRUCTURE   │
        │        9 890          │
        │       (13,9%)         │
        └───────────────────────┘
```

**Lecture :** 57% des visites sur la page de recherche aboutissent à un clic sur un résultat (service ou structure).

## Répartition géographique des recherches

Les filtres géographiques (par ville) représentent 6 352 ajouts de filtres en décembre.

### Top 15 départements

```
   13 (Marseille       )  311 ██████████████████████████████
   75 (Paris           )  309 █████████████████████████████
   59 (Lille           )  280 ███████████████████████████
   31 (Toulouse        )  272 ██████████████████████████
   26 (Valence         )  247 ███████████████████████
   34 (Montpellier     )  225 █████████████████████
   80 (Amiens          )  224 █████████████████████
   93 (Saint-Denis     )  191 ██████████████████
   30 (Nîmes           )  184 █████████████████
   44 (Nantes          )  167 ████████████████
   78 (Mantes-la-Jolie )  144 █████████████
   81 (Albi            )  132 ████████████
   69 (Lyon            )  124 ███████████
   67 (Strasbourg      )  121 ███████████
  974 (Saint-Denis, RE )  118 ███████████
```

### Observations

- **Marseille** et **Paris** dominent avec ~310 filtres chacun
- Forte représentation du Sud (13, 31, 34, 30) et du Nord (59, 80)
- La Réunion (974) dans le top 15 avec 118 filtres

## Moyenne journalière

| Métrique | Décembre 2025 |
|----------|---------------|
| Visites recherche/jour | **2 292** |
| Clics résultats/jour | **1 312** |
| Filtres géo ajoutés/jour | **205** |

## Limitations

**Catégories thématiques non trackées.** Les catégories de recherche (emploi, logement, santé, etc.) présentes dans les paramètres URL (`cats=trouver-un-emploi`) ne sont pas capturées en événements Matomo. Seuls les filtres géographiques (ville/département) sont trackés via l'événement "Ajout d'un filtre".

**URLs anonymisées.** Matomo anonymise les URLs de services (`/services/slug`) ce qui empêche l'analyse des catégories de services consultés.

## Sources de données

**Funnel de recherche :**
- [View in Matomo](https://matomo.inclusion.beta.gouv.fr/index.php?module=CoreHome&action=index&idSite=211&period=month&date=2025-12-01#?category=General_Actions&subcategory=Transitions_Transitions) | `Transitions.getTransitionsForAction?idSite=211&period=month&date=2025-12-01&actionName=/recherche`

**Événements de filtres :**
- [View in Matomo](https://matomo.inclusion.beta.gouv.fr/index.php?module=CoreHome&action=index&idSite=211&period=month&date=2025-12-01#?category=General_Actions&subcategory=Events_Events) | `Events.getAction?idSite=211&period=month&date=2025-12-01`
