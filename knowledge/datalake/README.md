# Datalake Metabase Instance

**URL:** https://datalake.inclusion.beta.gouv.fr
**Instance name:** `datalake`

Cross-product analytics for la Plateforme de l'inclusion. Contains aggregated user data across multiple services (Emplois, Pilotage, GPS, Dora, Mon Recap, etc.).

## Usage

```python
from lib.sources import get_metabase

api = get_metabase("datalake")
result = api.execute_sql("SELECT * FROM pdi_base_unique_tous_les_pros LIMIT 10", database_id=2)
```

## Databases

| ID | Name | Description |
|----|------|-------------|
| 2 | Datalake | Main data warehouse with cross-product analytics |
| 3 | Spock | Metabase internal + company scoring data |

## Dashboards

| ID | Name | Collection |
|----|------|------------|
| 20 | Suivi de la rétention et de la croissance par cible et par produit | Indicateurs de performance |
| 21 | Recherche de contacts et structures sur la base de données commune | Moteur de recherche de contacts |
| 24 | Utilisateurs Communs Emplois - Dora | Utilisateurs Communs Emplois - Dora |

## Key Tables (Database 2: Datalake)

### stats_pdi_data

**Volumétrie :** ~161 lignes  
**Mise à jour :** mensuelle via n8n  
**Clé commune :** `produit` + `mois` (identifiant avec les autres tables stats_pdi ou statsretention)

Indicateurs macro mensuels par produit. Chaque ligne = un produit pour un mois donné.

#### Colonnes principales

| Colonne | Description |
|---------|-------------|
| `produit` | Nom du service (Emplois, Dora, GPS, etc.) |
| `mois` | Mois de référence (format YYYY-MM) |
| `axe` | Axe stratégique : Expérience professionnelle, Accompagnement, Connaissance |
| `actifs_accompagnateurs` | Utilisateurs accompagnateurs ayant eu au moins une action dans le mois |
| `engages_accompagnateurs` | Accompagnateurs avec engagement significatif (critères spécifiques par produit) |
| `promoteurs_accompagnateurs` | Accompagnateurs ayant donné un NPS de 8 à 10 |
| `actifs_employeurs` | Employeurs actifs dans le mois |
| `engages_employeurs` | Employeurs engagés |
| `promoteurs_employeurs` | Employeurs NPS 8-10 |
| `actifs_beneficiaires` | Bénéficiaires (candidats) actifs |
| `engages_beneficiaires` | Bénéficiaires engagés |
| `satisfaits_beneficiaires` | Bénéficiaires satisfaits (mesure de satisfaction, pas NPS) |

**Note :** Pour les bénéficiaires, on utilise `satisfaits` au lieu de `promoteurs` car la mesure de satisfaction diffère du NPS utilisé pour les professionnels.

### stats_pdi_dedup

**Volumétrie :** ~50-100 lignes  
**Mise à jour :** mensuelle via n8n  
**Clé commune :** `mois`

Ratios de déduplication pour calculer le nombre d'utilisateurs uniques cross-produits.

#### Colonnes principales

| Colonne | Description |
|---------|-------------|
| `mois` | Mois de référence |
| `ratio_dedup_accompagnateurs` | Ratio de déduplication pour les accompagnateurs |
| `ratio_dedup_employeurs` | Ratio de déduplication pour les employeurs |
| `ratio_dedup_beneficiaires` | Ratio de déduplication pour les bénéficiaires |

#### Utilisation

Pour obtenir le nombre d'utilisateurs uniques sur l'ensemble des produits :

```sql
-- Exemple : utilisateurs uniques actifs tous produits confondus
SELECT 
    d.mois,
    SUM(s.actifs_accompagnateurs) * d.ratio_dedup_accompagnateurs as accompagnateurs_uniques,
    SUM(s.actifs_employeurs) * d.ratio_dedup_employeurs as employeurs_uniques,
    SUM(s.actifs_beneficiaires) * d.ratio_dedup_beneficiaires as beneficiaires_uniques
FROM stats_pdi_data s
JOIN stats_pdi_dedup d ON s.mois = d.mois
GROUP BY d.mois, d.ratio_dedup_accompagnateurs, d.ratio_dedup_employeurs, d.ratio_dedup_beneficiaires;

### stats_nps_gip
Regroupe les NPS (net promoteur score) de chaque produit, mois par mois

### statsgps_logs_groupes
Do not use this table, instead use the data in the **stats** database
### monrecap_barometre
Do not use this table, instead use the data in the **stats** database
### monrecap_contacts
Do not use this table, instead use the data in the **stats** database
### monrecap_commandes
Do not use this table, instead use the data in the **stats** database
### monrecap_starmetrics
Do not use this table, instead use the data in the **stats** database


### statsretention_cohortes_gip
**Volumétrie :** ~4 500 lignes  
**Mise à jour :** mensuelle via n8n  
**Clé commune :** produit + mois (identifiant avec les autres tables stats_pdi ou statsretention)

### statsretention_gip
**Volumétrie :** ~330 lignes  
**Mise à jour :** mensuelle via n8n  
**Clé commune :** produit + mois (identifiant avec les autres tables stats_pdi ou statsretention)


### pdi_base_unique_tous_les_pros

**Volumétrie :** ~225 000 lignes  
**Mise à jour :** Quotidienne via n8n  
**Clé commune :** `email` (identifiant unique cross-services)

Base unifiée des utilisateurs professionnels de tous les services de la Plateforme de l'inclusion.

#### Sources de données

Les données sont agrégées depuis :
- Les Emplois
- Mon Recap
- Pilotage
- GPS (Mon Suivi ou réseau d'intervenant)
- Le Marché
- Dora
- RDV-Insertion (rdv-i)

#### Colonnes principales

| Colonne | Description |
|---------|-------------|
| `email` | **Clé primaire cross-services.** Permet de relier un utilisateur entre différents services. |
| `source` | Service d'origine de l'enregistrement |
| `id_source` | ID de l'utilisateur dans la base source |
| `date_inscription` | Date d'inscription au service |
| `date_derniere_connexion` | Dernière activité |
| `type_utilisateur` | Type principal dans le service source (voir ci-dessous) |
| `type_utilisateur_detail` | Granularité plus fine du type (en cours d'enrichissement) |
| `nom_structure` | Organisation de rattachement (entreprise, service public, association...) |
| `type_structure` | Type de structure (voir acronymes ci-dessous) |
| `departement_structure` | Localisation — utile pour matcher des structures entre services |
| `admin` | `true` si l'utilisateur peut gérer sa structure (ajouter membres, modifier infos) |

#### Types d'utilisateurs

Les types ne sont **pas harmonisés entre services**. Concepts récurrents :
- **Prescripteur** : professionnel qui oriente des candidats (parfois avec habilitations légales)
- **Accompagnateur** : similaire au prescripteur, mais sans dimension légale/habilitation
- **Employeur** : représentant d'une structure qui embauche

#### Types de structures (acronymes)

**Structures IAE (employeurs) :**

| Acronyme | Signification | Description |
|----------|---------------|-------------|
| ACI | Atelier et Chantier d'Insertion | Production de biens/services |
| AI | Association Intermédiaire | Mise à disposition de personnel |
| EI | Entreprise d'Insertion | Entreprise classique avec mission sociale |
| ETTI | Entreprise de Travail Temporaire d'Insertion | Intérim d'insertion |
| EITI | Entreprise d'Insertion par le Travail Indépendant | Travail indépendant |
| GEIQ | Groupement d'Employeurs pour l'Insertion et la Qualification | Contrats en alternance |

**Prescripteurs / Accompagnateurs :**

| Acronyme | Signification | Description |
|----------|---------------|-------------|
| FT | France Travail | Ex Pôle Emploi, service public de l'emploi |
| PE | Pôle Emploi | Ancien nom de France Travail |
| ML | Mission Locale | Accompagnement des jeunes 16-25 ans |
| CAP EMPLOI | Cap Emploi | Service pour travailleurs handicapés |
| SPIP | Service Pénitentiaire d'Insertion et de Probation | Accompagnement des personnes sous main de justice |
| DEPT | Conseil Départemental | Services sociaux du département |
| ODC | Organisme Délégataire de Convention | Délégataire des conseils départementaux pour l'accompagnement des bénéficiaires du RSA |
| CCAS | Centre Communal d'Action Sociale | Action sociale municipale |
| CHRS | Centre d'Hébergement et de Réinsertion Sociale | Hébergement et accompagnement social |
| PLIE | Plan Local pour l'Insertion et l'Emploi | Dispositif territorial d'insertion |
| ASSO | Association | Structure associative (générique) |

#### Jointures

- **Pas de jointure directe** avec d'autres tables du Datalake
- **Jointure possible** via `email` si une autre table contient des adresses mail
- **Matching de structures** : utiliser `nom_structure` + `departement_structure` pour rapprocher des structures entre services (les noms peuvent différer légèrement)

#### Exemple de requête

```sql
-- Utilisateurs actifs sur plusieurs services
SELECT email, COUNT(DISTINCT source) as nb_services, 
       ARRAY_AGG(DISTINCT source) as services
FROM pdi_base_unique_tous_les_pros
WHERE date_derniere_connexion > CURRENT_DATE - INTERVAL '30 days'
GROUP BY email
HAVING COUNT(DISTINCT source) > 1
ORDER BY nb_services DESC;

### Product-Specific Data

| Table | Rows | Description |
|-------|------|-------------|
| `gps_log_data` | ~5.5k | GPS (Mon Suivi) application logs |
| `statsgps_logs_groupes` | ~3.2k | GPS logs grouped |
| `monrecap_barometre` | ~153k | Mon Recap barometer data |
| `monrecap_commandes` | ~4.5k | Mon Recap orders |
| `monrecap_contacts` | ~3.8k | Mon Recap contacts |
| `immersion_facile_stats_support` | ~29k | Immersion Facile support stats |
| `immersion_facile_email_agences` | ~3.5k | Immersion Facile agency emails |

### Webinaires (Matometa)

| Table | Description |
|-------|-------------|
| `matometa_webinaires` | Webinaires (Livestorm + Grist), synced by Matometa cron |
| `matometa_webinaire_sessions` | Sessions Livestorm |
| `matometa_webinaire_inscriptions` | Inscriptions et participations (~95k) |
| `matometa_webinaire_sync_meta` | Métadonnées de synchronisation |

See `knowledge/webinaires/_index.md` for schema details and query examples.

### Operational Data

| Table | Rows | Description |
|-------|------|-------------|
| `brevo_conso` | ~13 | Brevo email consumption |
| `webinaires_pilotage_participants` | ~3.7k | Pilotage webinar participants |
| `statsfile_active_gip` | ~65 | Active file stats |

### Reference Tables

| Table | Rows | Description |
|-------|------|-------------|
| `correspondance_cible_vers_cat_donnee` | ~16 | Target to data category mapping |
| `correspondance_produit_vers_axe` | ~8 | Product to axis mapping |
| `table_correspondance_domaines_pilotage` | ~2k | Pilotage domain mapping |

### Analysis Tables

| Table | Rows | Description |
|-------|------|-------------|
| `analyse_aigles` | ~483 | "Eagles" (super-users) analysis |
| `analyse_emails` | - | Email analysis |
| `analyse_event` | - | Event analysis |
| `datacube_score_v0` | ~87 | Data cube scoring |
| `stats_nps_gip` | ~261 | NPS scores |
| `stats_pdi_data` | ~161 | PDI statistics |

## Key Tables (Database 3: Spock)

Company scoring data from le Marche.

| Table | Rows | Description |
|-------|------|-------------|
| `company_score_scoredcompany` | ~15k | Scored companies with API Entreprise data |
| `company_score_ifrawconvention` | ~13k | Convention data by SIREN |
| `company_score_lemarcherawtender` | ~5.3k | Le Marche tender data |
| `company_score_domainsirenassociation` | ~1.5k | Domain to SIREN associations |

## Collections Structure

```
Root
├── Giulia (112)
│   └── Utilisateurs Communs Emplois - Dora (110) → Dashboard [24]
├── Nova (74)
│   ├── Indicateurs de performance (75) → Dashboard [20]
│   ├── Moteur de recherche de contacts (87) → Dashboard [21]
│   ├── Stats clés (117)
│   ├── Utilisateurs multiservices (95)
│   └── demandes_bizdev (94)
└── Pierre (4)
    ├── Aigles (30)
    └── Stages CIP (13)
```
