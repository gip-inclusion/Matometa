# Candidats (job seekers)

## Définitions

### Candidat autonome

**Définition :** Candidat qui **émet lui-même sa candidature** depuis son propre compte sur la plateforme Les Emplois de l'inclusion.

**Caractéristiques :**
- Le compte peut avoir été créé par un tiers (prescripteur, employeur)
- L'éligibilité (pass IAE) peut avoir été validée par un prescripteur habilité ou un employeur
- Ce qui compte : **l'acte de candidature est initié par le candidat lui-même**

**Dans Metabase :** `origine = 'Candidat'` dans la table `candidatures_echelle_locale`

**Dans Matomo :** Événement `candidature_candidat` (vs `candidature_prescripteur`)

**Objectif stratégique :** Augmenter le taux de candidats autonomes **avec diagnostic d'éligibilité** dans leurs candidatures.

### Diagnostic d'éligibilité (prescription vs autoprescription)

**Définition :** Validation de l'éligibilité IAE d'un candidat.

| Qui valide ? | Terme | Dans Metabase |
|--------------|-------|---------------|
| Prescripteur externe (France Travail, Mission Locale...) | **Prescription** | `auteur_diag_candidat = 'Prescripteur'` |
| L'employeur SIAE lui-même | **Autoprescription** | `auteur_diag_candidat = 'Employeur'` |

Voir aussi : [Emplois.md § Two Dimensions](../sites/Emplois.md#key-concepts-two-dimensions-of-the-iae-workflow)

**Taux en 2025 :** 75,6 % des candidatures autonomes disposent d'un diagnostic d'éligibilité.

**Impact :** Le diagnostic multiplie par 45 les chances d'embauche (5,9 % vs 0,1 % sans diagnostic).

## Indicateurs clés

### Volume et taux d'acceptation (2025)

| Origine | Candidatures | % | Taux d'acceptation |
|---------|--------------|---|-------------------|
| Prescripteur habilité | 517 389 | 71,9 % | 17,5 % |
| **Candidat autonome** | **106 266** | **14,8 %** | **4,5 %** |
| Employeur | 55 830 | 7,8 % | 93,9 % |
| Orienteur | 30 661 | 4,3 % | 10,3 % |

### Candidats autonomes : taux de diagnostic (2025)

| Statut | Candidatures | % | Taux d'acceptation |
|--------|--------------|---|-------------------|
| **Avec diagnostic** | **80 387** | **75,6 %** | **5,9 %** |
| Sans diagnostic | 25 879 | 24,4 % | 0,1 % |

**Auteur du diagnostic :**
- Prescription (prescripteur externe) : 64 358 (60,6 %)
  - France Travail : 42 692 (40,2 %)
  - Mission Locale : 8 463 (8,0 %)
- Autoprescription (employeur SIAE) : 16 029 (15,1 %)

### Évolution historique (volume)

| Année | Candidatures | Candidats uniques | Taux d'acceptation |
|-------|--------------|-------------------|-------------------|
| 2021 | 33 481 | 10 662 | 12,0 % |
| 2022 | 40 894 | 15 146 | 15,0 % |
| 2023 | 56 639 | 19 313 | 9,7 % |
| 2024 | 80 143 | 28 712 | 6,3 % |
| 2025 | 106 266 | 33 475 | 4,5 % |

**Tendance :** Volume en forte croissance (+217 % entre 2021 et 2025), mais taux d'acceptation en baisse (-70 %).

### Évolution historique (taux de diagnostic)

| Année | Taux de diagnostic | Évolution annuelle |
|-------|-------------------|-------------------|
| 2023 | 83,8 % | - |
| 2024 | 74,6 % | -9,2 points ⚠️ |
| 2025 | 75,6 % | +1,0 point ✅ |

**Tendance :** Baisse significative de 14 points entre 2023 et 2025 (83,8 % → 75,6 %), corrélée au doublement du volume. Stabilisation en 2025 après la chute de 2024. Point bas historique : décembre 2025 (69,7 %). Meilleur mois récent : septembre 2025 (80,1 %).

## Profil démographique

### Genre (candidatures autonomes 2025)

| Genre | Candidatures | % |
|-------|--------------|---|
| Homme | 68 347 | 64,3 % |
| Femme | 35 449 | 33,4 % |
| Non renseigné | 2 470 | 2,3 % |

### Tranches d'âge

| Tranche d'âge | Candidatures | % |
|---------------|--------------|---|
| Adulte (26-54 ans) | 73 778 | 69,4 % |
| Jeune (< 26 ans) | 19 311 | 18,2 % |
| Senior (55 ans +) | 10 707 | 10,1 % |

## Géographie

### Top 10 départements (candidatures autonomes 2025)

| Département | Candidatures | Taux de diagnostic | Taux d'acceptation |
|-------------|--------------|-------------------|-------------------|
| 59 - Nord | 12 998 | 83,7 % | 4,8 % |
| 75 - Paris | 5 449 | 77,3 % | 2,2 % |
| 62 - Pas-de-Calais | 4 629 | 77,9 % | 5,4 % |
| 13 - Bouches-du-Rhône | 4 374 | 73,1 % | 4,6 % |
| 93 - Seine-Saint-Denis | 4 267 | 76,4 % | 2,4 % |
| 974 - La Réunion | 3 794 | 68,1 % | 2,8 % |
| 69 - Rhône | 3 592 | 78,1 % | 5,3 % |
| 92 - Hauts-de-Seine | 2 935 | 77,8 % | 2,7 % |
| 67 - Bas-Rhin | 2 862 | 74,1 % | 2,5 % |
| 34 - Hérault | 2 844 | 70,2 % | 3,9 % |

**Observation :** Le Nord concentre 12 % des candidatures autonomes avec le meilleur taux de diagnostic (83,7 %).

## Types de SIAE ciblées

| Type SIAE | Candidatures | Taux de diagnostic | Taux d'acceptation |
|-----------|--------------|-------------------|-------------------|
| ACI | 41 263 | 78,2 % | 6,6 % |
| EI | 21 319 | 76,5 % | 4,3 % |
| ETTI | 16 786 | 74,4 % | 1,9 % |
| AI | 16 041 | 74,2 % | 4,5 % |
| EA | 5 555 | 67,8 % | 0,5 % |
| GEIQ | 3 242 | 70,8 % | 0,5 % |

**Observation :** Les ACI sont les plus ciblées (39 %) et offrent le meilleur taux d'acceptation (6,6 %).

## Comportement sur le site (Matomo)

### Visites des job_seekers (décembre 2025)

- **22 111 visites** (5,6 % du trafic total)
- **393 027 actions** (17,8 actions/visite)
- **78 % de visiteurs récurrents**

### Pages les plus visitées

| Page | Visites |
|------|---------|
| `/dashboard/` (tableau de bord) | 18 987 |
| `/apply/job_seeker/list` (mes candidatures) | 12 682 |
| `/search/employers/results` (recherche SIAE) | 9 267 |
| Fiche de poste | 7 394 |
| Détails candidature | 6 121 |

### Événements de candidature (décembre 2025)

| Événement | Volume |
|-----------|--------|
| `start_application` | 62 083 |
| `candidature_prescripteur` | 31 282 |
| **`candidature_candidat`** | **7 195** |
| `accept_application_confirmation` | 7 843 |
| `refuse_application` | 11 533 |

**Ratio :** 1 candidature autonome pour 4,3 candidatures de prescripteurs.

### Sources de trafic

| Source | Visites | % |
|--------|---------|---|
| Accès direct | 19 451 | 87,7 % |
| Moteurs de recherche | 1 254 | 5,7 % |
| Sites référents | 751 | 3,4 % |

**Observation :** Les candidats accèdent quasi exclusivement par accès direct (88 %), signe d'une population fidèle.

## Motifs de refus (candidatures autonomes 2025)

| Motif | Nombre | % |
|-------|--------|---|
| **Refus automatique** | 34 826 | 47,8 % |
| Autre | 10 834 | 14,9 % |
| Pas de recrutement en cours | 6 008 | 8,2 % |
| Candidat non éligible | 3 491 | 4,8 % |
| Candidature en doublon | 2 921 | 4,0 % |
| Manque de compétences | 2 657 | 3,6 % |

**Alerte :** 48 % des refus sont automatiques, suggérant un problème d'éligibilité ou de traitement.

## Pistes d'amélioration

### Objectif : Augmenter le taux de candidatures autonomes avec diagnostic

**Taux actuel :** 75,6 %
**Taux cible :** 85-90 %

**Actions prioritaires :**

1. **Bloquer la candidature sans diagnostic** (impact : +24 points, 100 % de diagnostic)
2. **Auto-diagnostic en ligne** (impact : +7-10 points)
3. **Renforcer la visibilité du diagnostic** dans le parcours (impact : +3-5 points)
4. **Cibler les départements en retard** (La Réunion : 68,1 %) (impact : +2-3 points localement)
5. **Intégrer le diagnostic dans le parcours employeur** (impact : +1-2 points)

## Rapports associés

- [Évolution du taux de candidats autonomes avec diagnostic (2023-2025)](../../reports/2026-01-evolution-taux-candidats-autonomes-diagnostic-2023-2025.md)
- [Taux de candidatures autonomes avec diagnostic d'éligibilité (2025)](../../reports/2026-01-taux-candidats-autonomes-avec-diagnostic.md)
- [Les candidats autonomes sur les Emplois de l'inclusion (2025)](../../reports/2026-01-candidats-autonomes.md)
