# Nexus (Le portail de la Plateforme de l’inclusion)

## Description du service
Nexus est une fonctionnalité des Emplois de l'Inclusion qui permet aux utilisateurs
professionnels (prescripteurs, employeurs/SIAE, offreurs de service) de consulter
de manière centralisée leur présence sur l'ensemble des services de la Plateforme.
Le portail facilite l’accès aux services numériques de la Plateforme de l’inclusion pour les structures d’insertion et les accompagnateurs.
Il réunit toutes les données et actions métiers pertinentes dans un seul interface web et met fin à la multiplication des mots de passe et à la répétition d’informations.

## Publics cibles

- **Cible prioritaire :** gestionnaires de structure
- **Cible secondaire :** accompagnateurs (sens large)
- **Non ciblés :** usagers, pilotes institutionnels

**Base Metabase :** instance STATS, `database_id = 17` (base séparée de la base Stats principale)
**Mise à jour :** quotidienne

## Schéma relationnel

```
public.structures <── public.memberships ──> public.users
  (id_unique)          (structure_id_unique,    (id_unique)
                        user_id_unique, role)
```

La clé de jointure est `id_unique` (format `{source}--{id_source}`, ex: `dora--2`).

## Tables

### public.structures

Liste des structures présentes sur au moins un service de la Plateforme.

**Volumétrie :** 52 573 lignes · 30 142 SIRETs distincts · 21 835 doublons cross-services

| Colonne | Type | Description |
|---------|------|-------------|
| `source` | text | Service d'origine (`emplois-de-linclusion`, `dora`, `le-marché`) |
| `id_source` | text | ID de la structure dans le service source |
| `id_unique` | text | Clé primaire (`{source}--{id_source}`) |
| `siret` | text | SIRET (clé fonctionnelle pour regrouper cross-services) |
| `nom` | text | Nom tel que connu sur le service source |
| `type` | text | Type de structure (voir ci-dessous) |
| `code_insee` | text | Code INSEE de la commune |
| `adresse` | text | Adresse postale |
| `code_postal` | text | Code postal |
| `latitude` | float | Coordonnée GPS |
| `longitude` | float | Coordonnée GPS |
| `email` | text | Email de contact |
| `téléphone` | text | Téléphone de contact |
| `mise_à_jour` | timestamp | Date de dernière mise à jour |

#### Répartition par source

| Source | Nb structures |
|--------|---------------|
| `dora` | 23 883 |
| `emplois-de-linclusion` | 18 419 |
| `le-marché` | 10 271 |

#### Types de structures

Les types proviennent des services sources et ne sont pas harmonisés.
Un préfixe indique parfois la catégorie : `company--ACI`, `prescriber--FT`, etc.

| Type | Nb | Catégorie |
|------|----|-----------|
| `company--ACI` | 5 895 | SIAE (Emplois) |
| `company--EI` | 3 055 | SIAE (Emplois) |
| `company--AI` | 1 878 | SIAE (Emplois) |
| `company--ETTI` | 1 553 | SIAE (Emplois) |
| `company--GEIQ` | 777 | SIAE (Emplois) |
| `company--EA` | 3 173 | EA/ESAT (Emplois) |
| `company--ESAT` | 1 952 | ESAT (Emplois) |
| `prescriber--Autre` | 3 326 | Prescripteur (Emplois) |
| `prescriber--CCAS` | 1 132 | Prescripteur (Emplois) |
| `prescriber--FT` | 1 014 | Prescripteur (Emplois) |
| `prescriber--CHRS` | 614 | Prescripteur (Emplois) |
| `prescriber--ML` | 515 | Prescripteur (Emplois) |
| `prescriber--ODC` | 382 | Prescripteur (Emplois) |
| `prescriber--DEPT` | 279 | Prescripteur (Emplois) |
| `prescriber--PLIE` | 265 | Prescripteur (Emplois) |
| `prescriber--CHU` | 223 | Prescripteur (Emplois) |
| `ASSO` | 2 222 | Association (Dora/Marché) |
| `ACI` | 1 956 | SIAE (Dora/Marché) |
| `EI` | 1 267 | SIAE (Dora/Marché) |
| `FT` | 991 | France Travail (Dora) |
| `CCAS` | 843 | CCAS (Dora) |
| `AI` | 649 | SIAE (Dora/Marché) |
| `ETTI` | 623 | SIAE (Dora/Marché) |
| `OF` | 383 | Organisme de formation |
| `ML` | 435 | Mission Locale |
| `CHRS` | 356 | CHRS (Dora) |
| `AFPA` | 281 | AFPA |
| `Autre` | 1 893 | Autre |
| *(vide)* | 8 186 | Non renseigné |

**Note :** Un même SIRET peut apparaître plusieurs fois si la structure est présente
sur plusieurs services. C'est intentionnel — Nexus montre comment une structure est
représentée à travers les différents services.

```sql
-- Structures présentes sur plusieurs services (même SIRET)
SELECT siret, MIN(nom) as nom, COUNT(DISTINCT source) as nb_services,
       string_agg(DISTINCT source, ', ' ORDER BY source) as services
FROM public.structures
WHERE siret IS NOT NULL
GROUP BY siret
HAVING COUNT(DISTINCT source) > 1
ORDER BY nb_services DESC;
```

---

### public.users

Liste des utilisateurs professionnels présents sur au moins un service.

**Volumétrie :** 139 186 lignes · 110 760 emails distincts · 28 426 doublons cross-services

| Colonne | Type | Description |
|---------|------|-------------|
| `source` | text | Service d'origine (`emplois-de-linclusion`, `dora`, `le-marché`) |
| `id_source` | text | ID dans le service source |
| `id_unique` | text | Clé primaire (`{source}--{id_source}`) |
| `nom` | text | Nom de famille |
| `prénom` | text | Prénom |
| `email` | text | Email (clé fonctionnelle cross-services) |
| `téléphone` | text | Téléphone |
| `dernière_connexion` | timestamp | Dernière connexion sur ce service |
| `auth` | text | Mode d'authentification (ex: `ProConnect`) |
| `type` | text | Type d'utilisateur (voir ci-dessous) |
| `mise_à_jour` | timestamp | Date de dernière mise à jour |

#### Répartition par source

| Source | Nb utilisateurs |
|--------|-----------------|
| `emplois-de-linclusion` | 90 830 |
| `dora` | 39 892 |
| `le-marché` | 8 464 |

#### Types d'utilisateurs

| Type | Nb | Description |
|------|----|-------------|
| `prescripteur habilité` | 57 095 | Prescripteur avec habilitation légale (Emplois) |
| `orienteur` | 17 028 | Prescripteur sans habilitation (Emplois) |
| `employeur` | 16 707 | Employeur SIAE (Emplois) |
| `accompagnateur et offreur` | 15 680 | Double rôle (Dora) |
| `accompagnateur` | 15 639 | Accompagnateur seul (Dora) |
| `fournisseur` | 8 464 | Fournisseur (Marché) |
| `offreur` | 3 596 | Offreur de service (Dora) |
| `autre` | 4 733 | Autre |
| *(vide)* | 244 | Non renseigné |

```sql
-- Utilisateurs présents sur plusieurs services
SELECT email, COUNT(DISTINCT source) as nb_services,
       string_agg(DISTINCT source, ', ' ORDER BY source) as services
FROM public.users
WHERE email IS NOT NULL
GROUP BY email
HAVING COUNT(DISTINCT source) > 1
ORDER BY nb_services DESC;
```

---

### public.memberships

Table de liaison entre `structures` et `users`.

**Volumétrie :** 136 428 lignes

| Colonne | Type | Description |
|---------|------|-------------|
| `source` | text | Service d'origine |
| `user_id_unique` | text | FK vers `users.id_unique` |
| `structure_id_unique` | text | FK vers `structures.id_unique` |
| `role` | text | `administrateur` ou `collaborateur` |
| `mise_à_jour` | timestamp | Date de dernière mise à jour |

#### Répartition des rôles

| Rôle | Nb |
|------|----|
| `collaborateur` | 91 818 |
| `administrateur` | 44 610 |

**Note :** Un `administrateur` peut gérer la structure (ajouter membres, modifier infos).

## Jointures

```sql
-- Vue complète : utilisateurs, structures et rôles
SELECT
    u.email,
    u.type as type_utilisateur,
    u.source as source_user,
    s.siret,
    s.nom as structure_nom,
    s.type as type_structure,
    s.source as source_structure,
    m.role
FROM public.memberships m
JOIN public.users u ON m.user_id_unique = u.id_unique
JOIN public.structures s ON m.structure_id_unique = s.id_unique;

-- Membres d'une structure par SIRET (toutes sources)
SELECT u.email, u.nom, u.prénom, u.type, m.role, s.source
FROM public.structures s
JOIN public.memberships m ON m.structure_id_unique = s.id_unique
JOIN public.users u ON m.user_id_unique = u.id_unique
WHERE s.siret = '12345678901234';
```

## Lien avec les autres tables Stats

Pour croiser avec les tables Emplois (`public.utilisateurs`, `public.structures_v0`),
utiliser l'`email` (users) ou le `siret` (structures), **en filtrant sur `source = 'emplois-de-linclusion'`**.

```sql
-- Enrichir les users Nexus (Emplois) avec leur type Emplois
SELECT n.email, n.type as type_nexus, u.type as type_emplois
FROM public.users n
LEFT JOIN public.utilisateurs u ON n.email = u.email
WHERE n.source = 'emplois-de-linclusion';
```
