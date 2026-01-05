---
date: 2026-01-03
website: [Emplois]
original query: "Give me a breakdown of users of les Emplois who visited the /gps/* routes last month. User type, User département, how many came back, anything you can get, really."
query category: Analyse d'usage d'une fonctionnalité spécifique (GPS)
indicator type: [utilisateurs, segmentation, fidélité, géographie]
---

# Analyse des utilisateurs de la fonctionnalité GPS — Décembre 2025

Ce rapport présente une analyse détaillée de l'usage de la fonctionnalité **GPS** sur la plateforme **Les Emplois** durant le mois de décembre 2025. Le périmètre d'analyse est restreint aux visites ayant consulté au moins une page dont l'URL contient `/gps/`.

## Résumé des indicateurs clés

En décembre 2025, la fonctionnalité GPS a attiré une audience très ciblée et extrêmement fidèle.

- **Visites totales :** 3 829
- **Visiteurs uniques :** 3 059
- **Actions par visite :** 37,5 (Engagement très élevé)
- **Taux de rebond :** 1 % (Signe d'une navigation profonde)
- **Fidélité :** 98,3 % des visites proviennent d'utilisateurs connus.

**Data source:** [View in Matomo](https://matomo.inclusion.beta.gouv.fr/index.php?module=CoreHome&action=index&idSite=117&period=month&date=2025-12-01#?category=General_Visitors&subcategory=General_Overview&segment=pageUrl%3D%40%2Fgps%2F) | `VisitsSummary.get?idSite=117&period=month&date=2025-12-01&segment=pageUrl=@/gps/`

## Typologie des utilisateurs

La fonctionnalité est majoritairement utilisée par les prescripteurs, suivis des employeurs.

| Type d'utilisateur | Visites | Proportion |
| :--- | :--- | :--- |
| **Prescripteur** | **2 195** | **57,3 %** |
| **Employeur** | **1 455** | **38,0 %** |
| Anonyme | 166 | 4,3 % |
| Inspecteur du travail | 8 | 0,2 % |
| Staff ITOU | 5 | 0,1 % |

**Data source:** [View in Matomo](https://matomo.inclusion.beta.gouv.fr/index.php?module=CoreHome&action=index&idSite=117&period=month&date=2025-12-01#?category=General_Visitors&subcategory=customdimension1&segment=pageUrl%3D%40%2Fgps%2F) | `CustomDimensions.getCustomDimension?idSite=117&period=month&date=2025-12-01&segment=pageUrl=@/gps/&idDimension=1`

## Répartition géographique (Top 10 Départements)

Le département du Nord (59) domine largement l'usage de la fonctionnalité.

| Département | Visites |
| :--- | :--- |
| **59 - Nord** | **2 509** |
| 69 - Rhône | 1 702 |
| 93 - Seine-Saint-Denis | 1 648 |
| 13 - Bouches-du-Rhône | 1 541 |
| 62 - Pas-de-Calais | 1 294 |
| 75 - Paris | 1 216 |
| 33 - Gironde | 1 172 |
| 44 - Loire-Atlantique | 967 |
| 91 - Essonne | 951 |
| 34 - Hérault | 839 |

*Note : Une visite peut être comptabilisée dans plusieurs départements si l'utilisateur change de contexte ou si le département est défini au niveau de l'action.*

**Data source:** [View in Matomo](https://matomo.inclusion.beta.gouv.fr/index.php?module=CoreHome&action=index&idSite=117&period=month&date=2025-12-01#?category=General_Visitors&subcategory=customdimension4&segment=pageUrl%3D%40%2Fgps%2F) | `CustomDimensions.getCustomDimension?idSite=117&period=month&date=2025-12-01&segment=pageUrl=@/gps/&idDimension=4`

## Fidélisation et Acquisition

La fonctionnalité GPS repose presque exclusivement sur un noyau d'utilisateurs récurrents.

| Type de visiteur | Visiteurs uniques | Visites | Actions par visite |
| :--- | :--- | :--- | :--- |
| **Anciens (Returning)** | **2 997** | **3 762** | **37,6** |
| Nouveaux (New) | 67 | 67 | 34,8 |

**Data source:** [View in Matomo](https://matomo.inclusion.beta.gouv.fr/index.php?module=CoreHome&action=index&idSite=117&period=month&date=2025-12-01#?category=General_Visitors&subcategory=VisitFrequency_SubmenuFrequency&segment=pageUrl%3D%40%2Fgps%2F) | `VisitFrequency.get?idSite=117&period=month&date=2025-12-01&segment=pageUrl=@/gps/`

## Top 5 des pages les plus consultées (Segment GPS)

L'usage se concentre sur la liste des groupes et les tableaux de bord.

1. `/dashboard/` : 3 510 visites
2. `/gps/groups/list` : 3 268 visites
3. `/apply/prescriptions/list` : 1 847 visites
4. `/gps/groups/<id>/memberships` : 1 629 visites
5. `/search/employers/results` : 1 548 visites

**Data source:** [View in Matomo](https://matomo.inclusion.beta.gouv.fr/index.php?module=CoreHome&action=index&idSite=117&period=month&date=2025-12-01#?category=General_Actions&subcategory=General_Pages&segment=pageUrl%3D%40%2Fgps%2F) | `Actions.getPageUrls?idSite=117&period=month&date=2025-12-01&segment=pageUrl=@/gps/`