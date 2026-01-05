---
date: 2026-01-05
website: Emplois
original_query: "Breakdown of candidats autonomes: candidates who apply without prescriber or pass IAE"
query_category: Analyse de population (candidats autonomes)
indicator_type:
  - candidatures
  - segmentation
  - comportement
  - tendances
---

# Les candidats autonomes sur les Emplois de l'inclusion

*Rapport généré le 5 janvier 2026*

## Résumé exécutif

Les **candidats autonomes** sont les demandeurs d'emploi qui postulent directement aux offres des SIAE, sans passer par un prescripteur. Cette population représente une part croissante des candidatures mais avec un taux d'acceptation en chute libre.

### Chiffres clés (2025)

| Indicateur | Valeur |
|------------|--------|
| Candidatures autonomes | 106 266 |
| Candidats uniques | 33 475 |
| Part du total des candidatures | 14,8 % |
| Taux d'acceptation | **4,5 %** |
| Taux de refus | 68,5 % |

**Alerte** : Le taux d'acceptation des candidatures autonomes est passé de 15 % en 2022 à 4,5 % en 2025, soit une division par 3 en 3 ans.

---

## 1. Vue d'ensemble : qui sont les candidats autonomes ?

### 1.1 Définition

Un **candidat autonome** est un demandeur d'emploi qui :
- Crée lui-même son compte sur Les Emplois
- Postule directement à une offre d'une SIAE
- N'est pas accompagné par un prescripteur habilité

Dans Metabase, ils sont identifiés par `origine = 'Candidat'` dans la table `candidatures_echelle_locale`.

### 1.2 Typologie des candidatures par origine (2025)

| Origine | Candidatures | % | Taux d'acceptation |
|---------|--------------|---|-------------------|
| Prescripteur habilité | 517 391 | 71,9 % | 17,4 % |
| **Candidat (autonome)** | **106 266** | **14,8 %** | **4,5 %** |
| Employeur | 55 830 | 7,8 % | 93,9 % |
| Orienteur | 30 661 | 4,3 % | 10,3 % |
| Employeur orienteur | 9 430 | 1,3 % | 16,8 % |

**Data source:** [View in Metabase](https://stats.inclusion.beta.gouv.fr/question/7008) | `SELECT origine, COUNT(*) FROM candidatures_echelle_locale WHERE date_candidature >= '2025-01-01' GROUP BY origine`

---

## 2. Évolution historique

### 2.1 Volume et taux d'acceptation (2021-2025)

| Année | Candidatures | Candidats uniques | Candidatures/candidat | Acceptées | Taux d'acceptation |
|-------|--------------|-------------------|----------------------|-----------|-------------------|
| 2021 | 33 481 | 10 662 | 3,1 | 4 016 | 12,0 % |
| 2022 | 40 894 | 15 146 | 2,7 | 6 149 | **15,0 %** |
| 2023 | 56 639 | 19 313 | 2,9 | 5 497 | 9,7 % |
| 2024 | 80 153 | 28 712 | 2,8 | 5 019 | 6,3 % |
| 2025 | 106 266 | 33 475 | 3,2 | 4 757 | **4,5 %** |

**Tendance** : Le nombre de candidatures autonomes a triplé entre 2021 et 2025 (+217 %), mais le nombre d'embauches est resté quasi stable (~5 000/an), d'où l'effondrement du taux d'acceptation.

### 2.2 Évolution mensuelle (2024-2025)

| Mois | 2024 | 2025 | Évolution |
|------|------|------|-----------|
| Janvier | 8 033 | 9 635 | +20 % |
| Février | 7 264 | 8 539 | +18 % |
| Mars | 7 331 | 9 861 | +35 % |
| Avril | 6 461 | 9 511 | +47 % |
| Mai | 6 064 | 8 847 | +46 % |
| Juin | 5 787 | 7 404 | +28 % |
| Juillet | 6 244 | 7 468 | +20 % |
| Août | 5 130 | 6 658 | +30 % |
| Septembre | 6 741 | 10 008 | +48 % |
| Octobre | 7 627 | 10 103 | +32 % |
| Novembre | 7 396 | 9 879 | +34 % |
| Décembre | 6 075 | 8 353 | +37 % |

**Data source:** `SELECT DATE_TRUNC('month', date_candidature), COUNT(*) FROM candidatures_echelle_locale WHERE origine = 'Candidat' GROUP BY 1`

---

## 3. Profil démographique

### 3.1 Genre

| Genre | Candidatures | % |
|-------|--------------|---|
| Homme | 68 347 | 64,3 % |
| Femme | 35 449 | 33,4 % |
| Non renseigné | 2 470 | 2,3 % |

Les candidats autonomes sont majoritairement masculins (64 %), ce qui reflète probablement le type de postes proposés par les SIAE (ACI, chantiers d'insertion).

### 3.2 Tranches d'âge

| Tranche d'âge | Candidatures | % |
|---------------|--------------|---|
| Adulte (26-54 ans) | 73 778 | 69,4 % |
| Jeune (< 26 ans) | 19 311 | 18,2 % |
| Senior (55 ans +) | 10 707 | 10,1 % |
| Non renseigné | 2 470 | 2,3 % |

### 3.3 Éligibilité aux dispositifs

| Dispositif | Candidatures | % |
|------------|--------------|---|
| Non renseigné | 62 304 | 58,6 % |
| Éligible CEJ | 19 050 | 17,9 % |
| Éligible CEJ si RQTH | 16 821 | 15,8 % |
| Éligible CDI inclusion | 8 091 | 7,6 % |

**Observation** : Plus de la moitié des candidats autonomes n'ont pas d'éligibilité renseignée, ce qui suggère une méconnaissance des dispositifs IAE ou une absence de diagnostic préalable.

---

## 4. Répartition géographique

### 4.1 Top 15 départements

| Département | Candidatures | Acceptées | Taux |
|-------------|--------------|-----------|------|
| 59 - Nord | 12 998 | 623 | 4,8 % |
| 75 - Paris | 5 450 | 120 | 2,2 % |
| 62 - Pas-de-Calais | 4 629 | 251 | 5,4 % |
| 13 - Bouches-du-Rhône | 4 374 | 202 | 4,6 % |
| 93 - Seine-Saint-Denis | 4 264 | 103 | 2,4 % |
| 974 - La Réunion | 3 794 | 107 | 2,8 % |
| 69 - Rhône | 3 592 | 189 | 5,3 % |
| 92 - Hauts-de-Seine | 2 935 | 78 | 2,7 % |
| 67 - Bas-Rhin | 2 862 | 72 | 2,5 % |
| 34 - Hérault | 2 844 | 111 | 3,9 % |
| 76 - Seine-Maritime | 2 733 | 120 | 4,4 % |
| 30 - Gard | 2 624 | 149 | 5,7 % |
| 31 - Haute-Garonne | 2 470 | 100 | 4,0 % |
| 68 - Haut-Rhin | 2 104 | 77 | 3,7 % |
| 94 - Val-de-Marne | 2 098 | 54 | 2,6 % |

**Observation** : Le Nord concentre à lui seul 12 % des candidatures autonomes. Les départements franciliens (75, 93, 92, 94) ont des taux d'acceptation particulièrement bas (2-3 %).

---

## 5. Types de structures ciblées

| Type SIAE | Candidatures | Acceptées | Taux |
|-----------|--------------|-----------|------|
| ACI | 41 263 | 2 721 | 6,6 % |
| EI | 21 320 | 912 | 4,3 % |
| ETTI | 16 785 | 322 | 1,9 % |
| AI | 16 042 | 726 | 4,5 % |
| EA | 5 554 | 30 | 0,5 % |
| GEIQ | 3 242 | 15 | 0,5 % |
| OPCS | 870 | 14 | 1,6 % |
| EATT | 717 | 1 | 0,1 % |
| EITI | 473 | 16 | 3,4 % |

**Analyse** : Les candidats autonomes ciblent principalement les ACI (39 %) et les EI (20 %). Les taux d'acceptation sont meilleurs en ACI (6,6 %) qu'en ETTI (1,9 %) ou EA (0,5 %).

---

## 6. Motifs de refus

| Motif | Nombre | % |
|-------|--------|---|
| **Refus automatique** | 34 826 | 47,8 % |
| Autre | 10 834 | 14,9 % |
| Pas de recrutement en cours | 6 008 | 8,2 % |
| Candidat non éligible | 3 491 | 4,8 % |
| Candidature en doublon | 2 921 | 4,0 % |
| Manque de compétences | 2 657 | 3,6 % |
| Candidat non joignable | 2 570 | 3,5 % |
| Absence à l'entretien | 2 411 | 3,3 % |
| Frein incompatible | 1 970 | 2,7 % |
| Objectifs dialogue de gestion | 1 828 | 2,5 % |
| Candidat non intéressé | 1 389 | 1,9 % |
| Candidat en emploi | 1 196 | 1,6 % |

**Point critique** : Près de la moitié des refus (48 %) sont des "refus automatiques", ce qui suggère un mécanisme de purge des candidatures non traitées ou une non-éligibilité systématique.

---

## 7. Comportement sur le site (Matomo)

### 7.1 Visites des job_seekers

En décembre 2025, les job_seekers (candidats connectés) représentent :
- **22 111 visites** (5,6 % du trafic)
- **393 027 actions** (17,8 actions/visite en moyenne)
- 78 % de visiteurs récurrents

### 7.2 Pages les plus visitées

| Visites | Page |
|---------|------|
| 18 987 | `/dashboard/` (tableau de bord) |
| 12 682 | `/apply/job_seeker/list` (mes candidatures) |
| 9 267 | `/search/employers/results` (recherche SIAE) |
| 7 394 | Fiche de poste |
| 6 121 | Détails candidature |
| 5 160 | Fiche entreprise |
| 5 073 | Tour de bienvenue |
| 4 882 | Page de recherche |
| 4 843 | Résultats recherche postes |
| 4 389 | Sélection des postes |

**Data source:** [View in Matomo](https://matomo.inclusion.beta.gouv.fr/index.php?module=CoreHome&action=index&idSite=117&period=month&date=2025-12-01#?category=General_Actions&subcategory=General_Pages&segment=dimension1==job_seeker) | `Actions.getPageUrls&segment=dimension1==job_seeker`

### 7.3 Événements de candidature

| Événement | Décembre 2025 |
|-----------|---------------|
| `start_application` (début candidature) | 62 083 |
| `candidature_prescripteur` | 31 282 |
| `candidature_candidat` | 7 195 |
| `accept_application_confirmation` | 7 843 |
| `refuse_application` | 11 533 |

**Ratio** : Pour 1 candidature autonome soumise, il y a 4,3 candidatures de prescripteurs.

### 7.4 Évolution mensuelle des candidatures (Matomo)

| Mois 2025 | Candidat | Prescripteur | Ratio |
|-----------|----------|--------------|-------|
| Janvier | 9 032 | 39 749 | 1:4,4 |
| Février | 8 018 | 37 279 | 1:4,6 |
| Mars | 9 392 | 38 466 | 1:4,1 |
| Avril | 8 987 | 38 403 | 1:4,3 |
| Mai | 7 958 | 31 163 | 1:3,9 |
| Juin | 6 538 | 35 006 | 1:5,4 |
| Juillet | 6 598 | 35 478 | 1:5,4 |
| Août | 6 025 | 23 586 | 1:3,9 |
| Septembre | 9 183 | 37 900 | 1:4,1 |
| Octobre | 9 300 | 42 046 | 1:4,5 |
| Novembre | 9 252 | 33 948 | 1:3,7 |
| Décembre | 7 195 | 31 282 | 1:4,3 |

**Data source:** [View in Matomo](https://matomo.inclusion.beta.gouv.fr/index.php?module=CoreHome&action=index&idSite=117&period=month&date=2025-12-01#?category=General_Actions&subcategory=Events_Events) | `Events.getName&period=month`

### 7.5 Sources de trafic des job_seekers

| Source | Visites | % |
|--------|---------|---|
| Accès direct | 19 451 | 87,7 % |
| Moteurs de recherche | 1 254 | 5,7 % |
| Sites référents | 751 | 3,4 % |
| Réseaux sociaux | 30 | 0,1 % |
| Campagnes | 15 | 0,1 % |

Les job_seekers accèdent quasi exclusivement par accès direct (88 %), signe d'une population fidèle qui revient consulter ses candidatures.

---

## 8. Conclusions et recommandations

### 8.1 Constats

1. **Volume croissant, succès décroissant** : Les candidatures autonomes triplent en 4 ans, mais le nombre d'embauches stagne, ce qui fait chuter le taux d'acceptation de 15 % à 4,5 %.

2. **Refus automatiques massifs** : 48 % des refus sont automatiques, suggérant un problème d'éligibilité ou de qualité des candidatures.

3. **Inadéquation profil/offre** : Les candidats autonomes n'ont souvent pas de diagnostic (59 % sans éligibilité renseignée), ce qui les rend non éligibles de facto.

4. **Concentration géographique** : Le Nord (59) concentre 12 % des candidatures autonomes. Les départements franciliens ont les pires taux d'acceptation.

5. **Cible préférentielle : ACI** : Les ACI reçoivent 39 % des candidatures autonomes et offrent le meilleur taux d'acceptation (6,6 %).

### 8.2 Hypothèses

- Les candidats autonomes postulent "à l'aveugle" sans comprendre les critères d'éligibilité IAE
- Les SIAE n'ont pas la capacité de traiter ce volume de candidatures non qualifiées
- Le mécanisme de refus automatique masque peut-être un problème de paramétrage des offres

### 8.3 Pistes d'action

1. **Améliorer l'orientation en amont** : Avant de postuler, proposer un auto-diagnostic d'éligibilité
2. **Mieux expliquer le dispositif** : Les candidats autonomes ne semblent pas comprendre que l'IAE nécessite un accompagnement
3. **Qualifier les candidatures** : Ajouter des questions de pré-sélection pour éviter les candidatures non éligibles
4. **Analyser les refus automatiques** : Comprendre les règles qui déclenchent ces refus et leur pertinence

---

## Sources des données

**Période d'analyse :** 2021-2025 (historique), focus sur 2025

### Metabase

| Donnée | Table | Requête |
|--------|-------|---------|
| Candidatures par origine | `candidatures_echelle_locale` | `WHERE origine = 'Candidat'` |
| Démographie | `candidatures_echelle_locale` | `genre_candidat`, `tranche_age` |
| Géographie | `candidatures_echelle_locale` | `département_structure` |
| Motifs de refus | `candidatures_echelle_locale` | `motif_de_refus` |

### Matomo

| Donnée | Méthode API | Segment |
|--------|-------------|---------|
| Visites job_seekers | `CustomDimensions.getCustomDimension` | `dimension1==job_seeker` |
| Pages visitées | `Actions.getPageUrls` | `dimension1==job_seeker` |
| Événements candidature | `Events.getName` | - |
| Sources de trafic | `Referrers.getReferrerType` | `dimension1==job_seeker` |

---

*Rapport généré par Matometa*
