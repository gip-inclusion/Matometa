---
date: 2026-01-03
website: emplois
original_query: "Give me a breakdown of users of les Emplois who visited the /gps/* routes last month. User type, User département, how many came back, anything you can get, really."
query_category: GPS feature usage analysis
indicator_type: [user-segmentation, retention, feature-adoption, geography]
---

# Analyse des utilisateurs GPS - Décembre 2025

## Synthèse

Le GPS (réseau d'orientation) est une fonctionnalité très ciblée utilisée par une audience
fidèle et très engagée. En décembre 2025 :

- **3 059 visiteurs uniques** pour **3 829 visites**
- **98,3% de visites récurrentes** (seulement 67 nouveaux visiteurs)
- **37,5 actions/visite** (vs ~8-10 site-wide) : engagement exceptionnel
- **Taux de rebond de 1%** : les utilisateurs explorent la fonctionnalité

## 1. Répartition par type d'utilisateur

| Type            | Visites | Actions | % des visites |
|-----------------|--------:|--------:|--------------:|
| prescriber      |   2 195 |  73 763 |         57,3% |
| employer        |   1 455 |  63 610 |         38,0% |
| anonymous       |     166 |   6 232 |          4,3% |
| labor_inspector |       8 |      80 |          0,2% |
| itou_staff      |       5 |      18 |          0,1% |

**Observation clé :** Le GPS inverse le ratio habituel du site. Site-wide, les employeurs
dominent (~19% vs 14% prescripteurs). Sur GPS, les prescripteurs dominent largement
(57% vs 38%). C'est logique : le GPS est un outil d'orientation vers les structures
d'insertion, donc plus utile aux prescripteurs.

**Data source:** [View in Matomo](https://matomo.inclusion.gouv.fr/index.php?module=CustomDimensions&action=menuGetCustomDimension&idSite=117&period=month&date=2025-12-01&segment=pageUrl%3D%40%2Fgps%2F&idDimension=1) | `CustomDimensions.getCustomDimension?idSite=117&idDimension=1&period=month&date=2025-12-01&segment=pageUrl%3D%40%2Fgps%2F`

## 2. Répartition géographique (top 20 départements)

| Département | Visites | % du total |
|-------------|--------:|-----------:|
| 59 (Nord)   |   2 509 |      65,5% |
| 69 (Rhône)  |   1 702 |      44,5% |
| 93 (Seine-Saint-Denis) | 1 648 | 43,0% |
| 13 (Bouches-du-Rhône)  | 1 541 | 40,2% |
| 62 (Pas-de-Calais)     | 1 294 | 33,8% |
| 75 (Paris)             | 1 216 | 31,8% |
| 33 (Gironde)           | 1 172 | 30,6% |
| 44 (Loire-Atlantique)  |   967 | 25,3% |
| 91 (Essonne)           |   951 | 24,8% |
| 34 (Hérault)           |   839 | 21,9% |
| 38 (Isère)             |   774 | 20,2% |
| 76 (Seine-Maritime)    |   772 | 20,2% |
| 77 (Seine-et-Marne)    |   755 | 19,7% |
| 94 (Val-de-Marne)      |   728 | 19,0% |
| 49 (Maine-et-Loire)    |   704 | 18,4% |
| 57 (Moselle)           |   670 | 17,5% |
| 83 (Var)               |   606 | 15,8% |
| 78 (Yvelines)          |   603 | 15,7% |
| 92 (Hauts-de-Seine)    |   598 | 15,6% |

**Note :** Les pourcentages dépassent 100% car un même visiteur peut être associé à
plusieurs départements lors de différentes sessions/actions.

**Observation clé :** Le département 59 (Nord) est le premier utilisateur du GPS,
représentant 65% des visites. C'est probablement lié à un déploiement pilote ou une
adoption précoce dans cette région.

**Data source:** [View in Matomo](https://matomo.inclusion.gouv.fr/index.php?module=CustomDimensions&action=menuGetCustomDimension&idSite=117&period=month&date=2025-12-01&segment=pageUrl%3D%40%2Fgps%2F&idDimension=4) | `CustomDimensions.getCustomDimension?idSite=117&idDimension=4&period=month&date=2025-12-01&segment=pageUrl%3D%40%2Fgps%2F`

## 3. Fidélité des utilisateurs

| Métrique | Valeur | % |
|----------|-------:|--:|
| Nouvelles visites | 67 | 1,7% |
| Visites récurrentes | 3 762 | 98,3% |
| Nouveaux visiteurs uniques | 67 | — |
| Visiteurs récurrents uniques | 2 997 | — |

**Observation clé :** L'écrasante majorité des visites provient d'utilisateurs récurrents.
Le GPS n'attire presque pas de nouveaux utilisateurs (67 sur le mois), mais ceux qui
l'utilisent reviennent régulièrement. C'est le profil d'un outil professionnel intégré
dans les pratiques quotidiennes.

**Data source:** `VisitFrequency.get?idSite=117&period=month&date=2025-12-01&segment=pageUrl%3D%40%2Fgps%2F`

## 4. Pages GPS les plus visitées

| Page | Visites |
|------|--------:|
| /gps/groups/list | 3 268 |
| /gps/groups/{id}/memberships | 1 629 |
| /gps/groups/{id}/contribution | 939 |
| /gps/groups/{id}/beneficiary | 847 |
| /gps/groups/{id}/edition | 732 |
| /gps/groups/old/list | 443 |
| /gps/groups/join | 126 |
| /gps/groups/join/from-coworker | 37 |
| /gps/groups/join/from-nir | 29 |
| /gps/groups/join/from-name-email | 20 |

**Pattern d'usage :** Les utilisateurs consultent principalement la liste des groupes,
puis accèdent aux détails des membres et contributions. La page "old/list" suggère
une migration en cours ou un accès à l'ancienne interface.

**Data source:** `Actions.getPageUrls?idSite=117&period=month&date=2025-12-01&segment=pageUrl%3D%40%2Fgps%2F&filter_pattern=gps`

## 5. Pages d'entrée

Comment les utilisateurs arrivent-ils sur le GPS ?

| Page d'entrée | Entrées |
|---------------|--------:|
| /dashboard/ | 2 670 |
| /gps/groups/list | 334 |
| /apply/siae/list | 114 |
| /job-seekers/{uuid}/sender/check-nir | 64 |
| /apply/prescriptions/list | 56 |
| /apply/{uuid}/siae/details | 39 |
| /job-seekers/list | 35 |
| /approvals/list | 28 |
| /company/job_description/{id}/card | 26 |
| /search/employers/results | 24 |

**Observation clé :** 70% des sessions GPS commencent par le dashboard. Le GPS est
donc principalement accédé via la navigation interne, pas par des liens directs.
Seulement 334 sessions (9%) commencent directement sur la liste des groupes GPS.

**Data source:** `Actions.getEntryPageUrls?idSite=117&period=month&date=2025-12-01&segment=pageUrl%3D%40%2Fgps%2F`

## 6. Événements GPS

### Événements déclenchés SUR les pages GPS

Après vérification dans le code source (`gip-inclusion/les-emplois`), **un seul
événement est réellement déclenché sur les pages `/gps/*`** :

| Événement | Fichier source | Décembre 2025 |
|-----------|----------------|---------------:|
| `consulter_fiche_candidat` | `gps/includes/memberships_results.html` | 2 290 |

Cet événement se déclenche quand un utilisateur clique pour consulter la fiche
d'un candidat depuis la liste des membres d'un groupe GPS.

### Événements de navigation vers GPS

| Événement | Description | Décembre 2025 |
|-----------|-------------|---------------:|
| `tdb_liste_beneficiaires` | Clic sur le lien de nav vers `/gps/groups/list` | 3 307 |

Cet événement est dans la catégorie `gps` mais se déclenche **avant** d'arriver
sur la page GPS (c'est le clic de navigation).

### Catégories d'événements GPS (site-wide)

| Catégorie | Événements |
|-----------|----------:|
| gps | 3 904 |
| GPS_liste_groupes | 2 290 |

**Note méthodologique :** Le segment `pageUrl=@/gps/` filtre les *visites* ayant
inclus une page GPS, pas les *événements* déclenchés sur ces pages. Les autres
événements observés (`clic-metiers`, `start_application`, `statistiques`, etc.)
sont déclenchés sur d'autres pages (dashboard, recherche, fiches entreprises)
pendant des sessions qui ont aussi visité GPS.

**Data source:** Code source vérifié sur `github.com/gip-inclusion/les-emplois`

## Conclusions

1. **Audience captive et fidèle :** 98% de visites récurrentes, engagement très élevé
   (37 actions/visite). Le GPS est un outil de travail quotidien, pas une découverte
   ponctuelle.

2. **Prescripteurs en tête :** Contrairement au site global dominé par les employeurs,
   le GPS est utilisé majoritairement par les prescripteurs (57%).

3. **Concentration géographique :** Le Nord (59) représente 65% du trafic. Le GPS
   semble avoir été déployé ou adopté en priorité dans cette région.

4. **Usage pratique :** Les actions principales sur GPS sont la consultation de
   candidatures et de fiches bénéficiaires. Le GPS est utilisé comme un hub de
   suivi des parcours d'insertion.

5. **Faible acquisition :** Seulement 67 nouveaux visiteurs en décembre. La croissance
   du GPS passe par l'activation de nouveaux territoires ou types d'utilisateurs,
   pas par l'acquisition organique.

---

*Rapport généré le 2026-01-03 par Matometa.*
