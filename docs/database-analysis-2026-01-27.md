# Analyse de la base de données Matometa — Janvier 2026

**Date d'analyse :** 27 janvier 2026
**Période couverte :** 7 janvier — 27 janvier 2026
**Analysé par :** Agent Claude (audit interne)

---

## Résumé exécutif

Cette analyse porte sur 130 conversations, 11 714 messages, 59 rapports, et 23 utilisateurs distincts. L'objectif est d'identifier :
- Les requêtes fréquentes qui devraient être documentées ou pré-calculées
- Les erreurs répétées qui nécessitent de la documentation
- Les données demandées mais introuvables
- Les outils manquants
- Les patterns problématiques

---

## 1. Requêtes fréquentes à documenter / pré-cacher

### 1.1 Requêtes Matomo répétées

| Requête | Occurrences | Recommandation |
|---------|-------------|----------------|
| `VisitsSummary.get` (tous sites) | 54 | Créer un script de baseline mensuel automatique |
| `Events.getName@site206` (Communauté) | 6 | Documenter les événements dans `knowledge/sites/communaute.md` |
| `Actions.getPageTitles@site206` | 6 | Ajouter la liste des pages populaires au fichier site |
| `Events.getCategory@site211` (Dora) | 3 | Documenter la taxonomie des événements Dora |

**Recommandation :** Créer un job automatique (cron ou hook post-déploiement) qui génère les baselines mensuelles pour tous les sites et les stocke dans un format facilement queryable.

### 1.2 Requêtes SQL répétées

| Pattern | Occurrences | Recommandation |
|---------|-------------|----------------|
| SELECT email FROM pdi_base_unique_tous_les_pros | 8 | Créer une view ou documenter cette requête |
| Analyses candidatures avec date_traitement | 6 | Créer un template de requête candidatures |
| Jointure orientations_orientation | 272 | Documenter le schéma Dora |

### 1.3 Questions posées par plusieurs utilisateurs

Ces questions reviennent de plusieurs utilisateurs différents :

| Sujet | Utilisateurs | Action |
|-------|--------------|--------|
| **Parcours utilisateur** | 5 users (eric, pierre, louis-jean, alexis, abdessamad) | Créer un rapport-type "parcours" avec méthodologie |
| **France Travail prescriptions** | 3 users | Créer un dashboard FT dédié |
| **Usage CCAS** | 3 users | Documenter les données CCAS disponibles |
| **Clustering/segmentation** | 3 users | Créer un guide méthodologique segmentation |
| **Dora par département** | 2 users | Créer template rapport Dora départemental |

---

## 2. Erreurs répétées à documenter

### 2.1 Erreurs techniques fréquentes

| Type d'erreur | Occurrences | Cause | Solution à documenter |
|---------------|-------------|-------|----------------------|
| **Timeout API** | 114 | Requêtes trop lourdes (segments sur longues périodes) | Déjà documenté dans AGENTS.md — renforcer |
| **ValueError** | 58 | Mauvais parsing de résultats | Ajouter validation dans lib.query |
| **Module `lib` not found** | 22 | Mauvais path dans scripts | Documenter le `sys.path.insert(0, '/app')` |
| **Module `lib.sources` not found** | 7 | API deprecated | Migrer vers `lib.query` |
| **Colonne SQL introuvable** | 15+ | Schéma pas à jour | Actualiser knowledge/stats/ |

### 2.2 Colonnes manquantes fréquemment recherchées

Ces colonnes sont régulièrement cherchées mais n'existent pas (ou pas avec ce nom) :

| Colonne cherchée | Occurrences | Table probable | Action |
|------------------|-------------|----------------|--------|
| `code_commune` | 102 | diverses | Documenter où trouver les codes communes |
| `department` | 14 | diverses | Utiliser `departement` (avec accent) |
| `departement` | 7 | diverses | Vérifier existence par instance |
| `etat_candidature` | 4 | candidatures | Vérifier nom exact dans schéma |
| `critère_n1_bénéficiaire_du_rsa` | 3 | candidatures | Vérifier colonnes critères |
| `orientations_orientation` | 3 | dora | C'est une table, pas une colonne |

**Recommandation :** Créer un fichier `knowledge/stats/schema-quick-ref.md` avec les colonnes les plus utilisées et leur nom exact.

### 2.3 Tables manquantes

| Table cherchée | Occurrences | Action |
|----------------|-------------|--------|
| `monrecap.contacts_v0` | 2 | Documenter tables Mon Récap disponibles |
| `job_applications_jobapplication` | 2 | Utiliser `candidatures` dans datalake |
| `approvals_approval` | 2 | Documenter équivalent datalake |

---

## 3. Données demandées mais introuvables

### 3.1 Données non trackées

| Donnée | Site | Recommandation |
|--------|------|----------------|
| **Barre de recherche** | RDV-Insertion | Implémenter le tracking Site Search |
| **Événements GPS** | Emplois | Compléter le tracking Matomo des parcours GPS |
| **Connexions utilisateurs** | Communauté | Ajouter tracking connexion |

### 3.2 Données inaccessibles

| Donnée | Raison | Alternative suggérée |
|--------|--------|---------------------|
| Emails utilisateurs | Protection données | Utiliser user_id anonymisés |
| Données géospatiales fines | Pas de coordonnées GPS | Utiliser code commune + population |
| Données handicap détaillées | Sensibles | Utiliser critères agrégés |

### 3.3 Limitations de capacité mentionnées

L'agent a explicitement dit ne pas pouvoir faire :

| Limitation | Occurrences | Solution |
|------------|-------------|----------|
| "Pas accès à..." | 22 | Clarifier ce qui est accessible dans AGENTS.md |
| "Pas de données sur..." | 22 | Documenter les sources par thème |
| "Pas trackée" | 7 | Liste des événements trackés par site |
| "Dépasse mes capacités" | 2 | scipy/sklearn maintenant installés |

---

## 4. Outils et capacités manquants

### 4.1 Modules Python demandés

| Module | Mentions | Statut | Priorité |
|--------|----------|--------|----------|
| **scikit-learn** | 32 | Wishlist | 🔴 Haute — installé depuis |
| **scipy** | 26 | Wishlist | 🔴 Haute — installé depuis |
| **Notion API** | 13 | Non prévu | 🟡 Moyenne |
| **Google Sheets** | 10 | Bloqué (auth) | 🟡 Moyenne |
| **matplotlib** | 2 | Présent | ✅ |

### 4.2 Capacités souhaitées (wishlist)

| Catégorie | Demande | Statut |
|-----------|---------|--------|
| skill | Analyse géospatiale SIAE-communes | Open |
| tool | scikit-learn | Résolu |
| tool | scipy | Résolu |

---

## 5. Patterns problématiques observés

### 5.1 Conversations "rabbit holes"

Conversations très longues qui auraient pu être plus efficaces :

| Conversation | Messages | Outils | Tokens | Problème |
|--------------|----------|--------|--------|----------|
| Explorateur d'orientations DORA | 823 | 304 | 134k | Scope trop large, itérations UX |
| Fonctionnement nouvelle recherche services | 722 | 353 | — | Exploration non structurée |
| Patterns temporels communauté | 516 | 196 | 1M | Analyse exploratoire sans limite |

**Recommandation :** Ajouter des checkpoints dans les conversations longues. Proposer de scoper le travail au départ.

### 5.2 Conversations avec beaucoup d'erreurs

| Conversation | Erreurs | Total msgs | Ratio |
|--------------|---------|------------|-------|
| Explorateur d'orientations DORA | 30 | 823 | 3.6% |
| ODC x PDI | 19 | 325 | 5.8% |
| Orientations FT sans thématique | 18 | 335 | 5.4% |
| Communes rurales proches SIAE | 17 | 407 | 4.2% |

Ces conversations ont un taux d'erreur élevé, souvent dû à des schémas SQL mal connus.

### 5.3 Signaux de frustration utilisateur

10 signaux de frustration détectés :
- "ça plante" (2x)
- "relance" (2x)
- "ne marche pas" / "toujours pas" (2x)
- "non, c'est une erreur" (1x)

**Recommandation :** Améliorer la gestion des erreurs et proposer des alternatives plus rapidement.

---

## 6. Répartition de l'usage

### 6.1 Par site

| Site | Requêtes Matomo | Couverture docs |
|------|-----------------|-----------------|
| Emplois (117) | 147 | ✅ Bonne |
| Dora (211) | 41 | 🟡 Partielle |
| Marché (136) | 33 | 🟡 Partielle |
| Communauté (206) | 32 | 🟡 Partielle |
| Plateforme (212) | 18 | ⚠️ Faible |
| Pilotage (146) | 4 | ⚠️ Faible |
| RDV-Insertion (214) | 2 | ✅ Bonne |

### 6.2 Par utilisateur

| Utilisateur | Conversations | Usage type |
|-------------|---------------|------------|
| matometa@inclusion.gouv.fr | 29 | Tests/Admin |
| louisjean.teitelbaum | 26 | Power user (analyses complexes) |
| pierre.putois | 9 | Analyses pénétration/parcours |
| yannick.passarelli | 8 | Analyses FT/Marché |
| eric.barthelemy | 8 | Analyses comparatives SIAE |
| arnaud.denoix | 8 | Analyses territoriales |
| alexis.akinyemi | 7 | Études d'impact |
| annie.rajaonarison | 6 | Analyses Dora/Mon Récap |

### 6.3 Par thème

| Thème | Conversations | À documenter |
|-------|---------------|--------------|
| Analyses géographiques | 15 | Template rapport territorial |
| Métriques/KPIs | 16 | Dictionnaire des métriques |
| Emplois/SIAE | 35 | ✅ Bien couvert |
| Dora/Orientations | 22 | Schéma orientations |
| Le Marché | 11 | Guide analyses Marché |

---

## 7. Recommandations prioritaires

### 🔴 Priorité haute (cette semaine)

1. **Créer `knowledge/stats/schema-quick-ref.md`**
   - Liste des colonnes par table avec types
   - Mapping entre noms "naturels" et noms techniques
   - Exemple : `code_commune` → n'existe pas, utiliser `code_insee` dans table X

2. **Documenter les événements Dora dans `knowledge/sites/dora.md`**
   - Taxonomie des événements
   - Schéma de la table orientations

3. **Ajouter validation dans `lib.query`**
   - Vérifier que les résultats sont du JSON avant de parser
   - Meilleur message d'erreur sur timeout Matomo

### 🟡 Priorité moyenne (ce mois)

4. **Créer templates de rapports**
   - Template "Analyse départementale" (Dora, Emplois, etc.)
   - Template "Étude comparative"
   - Template "Funnel de conversion"

5. **Automatiser les baselines**
   - Script mensuel `VisitsSummary.get` pour tous les sites
   - Stockage dans SQLite ou fichiers CSV datés

6. **Améliorer la wishlist**
   - Intégrer avec Notion (sync automatique)
   - Dashboard des demandes récurrentes

### 🟢 Priorité basse (ce trimestre)

7. **Documentation tracking manquant**
   - Inventaire du tracking par site
   - Recommandations pour tracking manquant

8. **Guide méthodologique segmentation/clustering**
   - Bonnes pratiques
   - Exemples de code réutilisables

---

## 8. Métriques de suivi suggérées

Pour suivre l'amélioration :

| Métrique | Valeur actuelle | Cible |
|----------|-----------------|-------|
| Taux d'erreur moyen par conversation | ~4% | < 2% |
| Conversations > 500 messages | 4 | < 2 |
| Signaux frustration / mois | 10 | < 5 |
| Questions sans réponse | ~49 | < 20 |
| Requêtes SQL "colonne introuvable" | 15+ | < 5 |

---

## Annexes

### A. Distribution des erreurs par type

```
Other error:                265
API timeout:                114
Python ValueError:           58
Module lib not found:        22
SQL column not found:        15+
Python TypeError:             9
Module lib.sources not found: 7
SQL syntax error:             6
API not found:                5
API unauthorized:             5
```

### B. Conversations les plus coûteuses (tokens output)

1. Analyse statistiques communauté — 1.7M tokens
2. Dora dans le 78 — 1.2M tokens
3. Analyser patterns communauté — 1M tokens
4. ODC x PDI — 572k tokens
5. Étude impact fonctionnalité — 347k tokens

### C. Fichiers d'analyse produits

- `data-remote/analyze_db.py` — Analyse générale
- `data-remote/deep_analysis.py` — Analyse approfondie
- `data-remote/error_analysis.py` — Catégorisation des erreurs
- `data-remote/deep_patterns.py` — Patterns et frustrations
