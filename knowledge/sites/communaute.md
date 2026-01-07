# Communauté

- URL : https://communaute.inclusion.gouv.fr
- Matomo site ID : 206
- GitHub : https://github.com/gip-inclusion/la-communaute

## Références de trafic (2025)

Données récupérées le 06/01/2026 via l'API Matomo.

### Statistiques mensuelles des visiteurs

| Mois    | Visiteurs uniques | Visites | Moyenne quotidienne visiteurs | Moyenne quotidienne visites |
|---------|-------------------|---------|-------------------------------|-----------------------------|
| 2025-01 |            30 643 |  41 836 |                           988 |                       1 350 |
| 2025-02 |            25 553 |  34 110 |                           913 |                       1 218 |
| 2025-03 |            27 469 |  36 687 |                           886 |                       1 183 |
| 2025-04 |            27 557 |  36 246 |                           919 |                       1 208 |
| 2025-05 |            25 716 |  33 818 |                           830 |                       1 091 |
| 2025-06 |            24 370 |  32 152 |                           812 |                       1 072 |
| 2025-07 |            22 334 |  28 912 |                           720 |                         933 |
| 2025-08 |            17 051 |  21 623 |                           550 |                         698 |
| 2025-09 |            27 707 |  34 910 |                           924 |                       1 164 |
| 2025-10 |            33 324 |  44 914 |                         1 075 |                       1 449 |
| 2025-11 |            25 444 |  32 056 |                           848 |                       1 069 |
| 2025-12 |            21 643 |  27 109 |                           698 |                         874 |

**Fourchette typique :** 550-1 075 visiteurs uniques/jour, 698-1 449 visites/jour.

### Indicateurs d'engagement

| Mois    | Taux de rebond | Actions/Visite | Temps moyen sur le site |
|---------|----------------|----------------|-------------------------|
| 2025-01 |            62% |            3,3 |                  2m 40s |
| 2025-02 |            62% |            3,3 |                  2m 44s |
| 2025-03 |            62% |            3,3 |                  2m 43s |
| 2025-04 |            61% |            3,1 |                  2m 44s |
| 2025-05 |            60% |            3,2 |                  2m 30s |
| 2025-06 |            61% |              3 |                  2m 28s |
| 2025-07 |            59% |              3 |                  2m 21s |
| 2025-08 |            62% |            2,9 |                  2m 14s |
| 2025-09 |            64% |            2,7 |                  2m 04s |
| 2025-10 |            67% |            2,6 |                  1m 59s |
| 2025-11 |            67% |            2,4 |                  2m 02s |
| 2025-12 |            67% |            2,5 |                  2m 09s |

## Dimensions personnalisées

Aucune dimension personnalisée n'est configurée pour ce site.

## Segments enregistrés

*Récupéré le 06/01/2026 via l'API Matomo.*

| Nom | Définition |
|-----|------------|
| ACQUISITION - jour de l'événement | `visitorFirstVisitTime>2024-02-01%252000%253A00%253A01;vis...` |
| Action - Créer un événement | `pageUrl==https%253A%252F%252Fcommunaute.inclusion.beta.go...` |
| Création de topic | `pageUrl=@create` |
| DEVICE - Smartphone | `deviceType==smartphone` |
| PROFILE - connecté | `pageUrl=@https%253A%252F%252Fcommunaute.inclusion.gouv.fr...` |
| Première visite | `visitCount<2` |
| RETENTION - dernière visite 30j | `daysSinceLastVisit>=1;daysSinceLastVisit<32` |
| RETENTION - dernière visite 30j - Engagés | `daysSinceLastVisit>=1;eventAction==contribute,eventAction...` |
| STATS GIP - engagés | `eventAction==Poser%2520une%2520question,eventAction==cont...` |
| Visite de Topic | `pageUrl=@topic` |
| Visites Forums | `pageUrl=@https%253A%252F%252Fcommunaute-experimentation.i...` |
| Visites avec Action | `actions>=1` |
| visites de la home | `pageTitle=@Accueil` |

## Événements Matomo

Récupérés depuis le code source et l'API Matomo le 03/01/2026. ~60 événements distincts suivis.

### Implémentation

- **Pattern HTML :** Éléments avec `class="matomo-event"` et attributs `data-matomo-*`
- **Gestionnaire JS :** `/lacommunaute/static/javascripts/matomo.js` - capture les clics sur les éléments `.matomo-event`
- **Consentement :** Utilise Tarteaucitron pour la gestion du consentement RGPD
- **URL personnalisée :** Variable côté serveur `matomo_custom_url` pour le suivi des pages

### Catégories d'événements

Tous les événements utilisent le pattern : `category` / `action` / `name` (stocké dans `data-matomo-option`)

#### engagement (catégorie principale, ~11k événements/mois)

Suivi principal de l'engagement utilisateur. Principaux événements par volume (déc. 2025) :

| Action | Nom | Événements | Description |
|--------|-----|------------|-------------|
| view | fiches_techniques | 2 132 | Consultation des fiches techniques |
| showmore | topic | 1 231 | Expansion du contenu d'un topic |
| showmore | post | 1 276 | Expansion du contenu d'un post |
| view | documentation_header | 682 | Clic sur docs dans le menu d'en-tête |
| view | topic | 668 | Consultation du détail d'un topic |
| search | submit_query_header | 535 | Soumission de recherche depuis l'en-tête |
| search | submit_query | 693 | Soumission du formulaire de recherche |
| view | forum | 447 | Consultation de la liste des forums |
| view | dsp | 307 | Consultation du diagnostic DSP |
| view | topics | 320 | Consultation de la liste des topics |
| filter | forum | 271 | Filtrage du forum |
| view | events | 240 | Consultation de la liste des événements |
| view | documentation_breadcrumb | 226 | Navigation par fil d'Ariane vers docs |
| view | member | 162 | Consultation du profil d'un membre |
| rate | post | 117 | Évaluation d'un post |
| filter | topics | 126 | Filtrage des topics |
| view | topics_breadcrumb | 81 | Navigation par fil d'Ariane vers topics |
| contribute | new_topic | 69 | Création d'un nouveau topic |
| loadmore | topic | 64 | Chargement de plus de topics |
| contribute | post | 359 | Création d'un post de forum |
| view | event | 36 | Consultation d'un événement unique |
| contribute | new_topic_on_docs | 36 | Création d'un topic depuis la page docs |
| view | upvotes | 26 | Consultation de la page des votes positifs |
| view | documentation | 23 | Consultation de la section documentation |
| contribute | new_topic_after_search | 22 | Création d'un topic après une recherche |
| upvote | post | 6 | Vote positif pour un post |
| show | fichestechniques | 1 105 | Affichage de la liste des fiches techniques |
| emplois | search-prescriber | 132 | Liens vers recherche prescripteur Emplois |
| emplois | search-company-header | 43 | Liens vers recherche entreprise Emplois |
| emplois | search-company | 21 | Liens vers recherche entreprise Emplois |
| emplois | search-prescriber-header | 13 | Liens vers recherche prescripteur Emplois |
| topic-create-check | itou-jobseeker | 12 | Validation topic demandeur d'emploi |
| landing | devenircip | 18 | Page d'atterrissage CIP |

#### support (22 événements/mois)

Liens vers ressources externes.

| Action | Nom | Description |
|--------|-----|-------------|
| site_emplois | footer | Lien footer vers support Emplois |

#### promotion-partenaires (14 événements/mois)

Clics sur promotions partenaires.

| Action | Nom | Description |
|--------|-----|-------------|
| clic | inclusion-demain | Lien partenaire : inclusion-demain.fr |

#### landing (26 événements/mois)

Navigation sur pages d'atterrissage.

| Action | Nom | Description |
|--------|-----|-------------|
| glossaire | footer | Lien footer vers glossaire |
| devenircip | (depuis engagement) | Page d'atterrissage CIP |

### Événements du diagnostic DSP

La fonctionnalité DSP (Diagnostic Socio-Professionnel) génère des événements dynamiques basés sur les résultats du diagnostic.

| Action | Pattern de nom | Description |
|--------|----------------|-------------|
| dsp | submit-dsp | Soumission du diagnostic (341 événements) |
| dsp | submit-an-other-dsp | Soumission d'un autre diagnostic (15 événements) |
| dsp | visit-{theme}--{subtheme} | Clics pour consulter les ressources pour des besoins spécifiques |

**Thèmes DSP observés (déc. 2025) :**
- `visit-trouver-un-emploi` (18)
- `visit-apprendre-francais--accompagnement-insertion-pro` (15)
- `visit-apprendre-francais--communiquer-vie-tous-les-jours` (8)
- `visit-handicap--adaptation-au-poste-de-travail` (7)
- `visit-logement-hebergement` (7)
- `visit-acces-aux-droits-et-citoyennete--connaitre-ses-droits` (6)
- `visit-mobilite` (6)
- Plus de 10 combinaisons thème/sous-thème additionnelles

### Résumé des principaux événements (déc. 2025)

| Rang | Catégorie | Action | Nom | Événements |
|------|-----------|--------|-----|------------|
| 1 | engagement | view | fiches_techniques | 2 132 |
| 2 | engagement | showmore | post | 1 276 |
| 3 | engagement | showmore | topic | 1 231 |
| 4 | engagement | show | fichestechniques | 1 105 |
| 5 | engagement | search | submit_query | 693 |
| 6 | engagement | view | documentation_header | 682 |
| 7 | engagement | view | topic | 668 |
| 8 | engagement | search | submit_query_header | 535 |

### Notes d'implémentation

**Emplacements dans le code source avec suivi :**
- `lacommunaute/templates/layouts/base.html` - Initialisation Matomo
- `lacommunaute/templates/pages/home.html` - Engagement page d'accueil
- `lacommunaute/templates/forum/index.html` - Navigation forum
- `lacommunaute/templates/forum/forum_detail.html` - Vues détail forum
- `lacommunaute/templates/forum_conversation/topic_list.html` - Interactions liste topics
- `lacommunaute/templates/forum/partials/rating.html` - Évaluation de post
- `lacommunaute/templates/surveys/dsp_form.html` - Soumission DSP
- `lacommunaute/templates/surveys/dsp_detail.html` - Actions résultat DSP
- `lacommunaute/templates/partials/header.html` - Navigation en-tête
- `lacommunaute/templates/partials/footer.html` - Liens footer
- `lacommunaute/templates/partials/upvotes.html` - Suivi votes positifs
- `lacommunaute/templates/search/search_form.html` - Suivi recherche
- `lacommunaute/templates/forum_conversation/partials/topic_filter.html` - Suivi filtres

**Scripts de collecte de données :**
- `lacommunaute/utils/matomo.py` - Utilitaires API Matomo
- `lacommunaute/stats/management/commands/collect_matomo_stats.py` - Collecte stats visites
- `lacommunaute/stats/management/commands/collect_matomo_forum_stats.py` - Collecte stats forum

## Contexte du site

La Communauté est un forum communautaire basé sur Django pour les professionnels du secteur de l'inclusion sociale en France.

**Fonctionnalités principales :**
- Discussions de forum (topics, posts)
- Documentation/fiches techniques
- Outil de diagnostic DSP (Diagnostic Socio-Professionnel)
- Calendrier d'événements
- Profils utilisateurs avec votes positifs
- Liens d'intégration vers la plateforme Emplois

**Stack technologique :**
- Django (Python)
- machina (bibliothèque forum Django)
- Tarteaucitron (consentement RGPD)
- HTMX (interactions dynamiques)

---
