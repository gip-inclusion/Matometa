# Structures d'insertion

Documentation des structures d'insertion par l'activité économique (SIAE) et autres structures.

## Source de données

Table Metabase : `data_inclusion.structures_v0`

## Typologies SIAE

Les SIAE (Structures d'Insertion par l'Activité Économique) sont identifiées par leur `typologie`. Voici les types reconnus :

| Typologie | Nom complet | Description | Effectif |
|-----------|-------------|-------------|----------|
| ACI | Atelier Chantier d'Insertion | Structures portant des activités d'utilité sociale | ~936 |
| EI | Entreprise d'Insertion | Entreprises produisant des biens/services marchands | ~414 |
| AI | Association Intermédiaire | Mise à disposition de personnel auprès d'utilisateurs | ~343 |
| ETTI | Entreprise de Travail Temporaire d'Insertion | Intérim d'insertion | ~282 |
| GEIQ | Groupement d'Employeurs pour l'Insertion et la Qualification | Mutualisation RH entre employeurs | ~84 |
| EITI | Entreprise d'Insertion par le Travail Indépendant | Accompagnement vers le travail indépendant | ~37 |

**Total SIAE géolocalisées : ~2 096**

## Requête SQL

```sql
-- Toutes les SIAE géolocalisées
SELECT id, nom, siret, code_insee, latitude, longitude, typologie
FROM data_inclusion.structures_v0
WHERE typologie IN ('ACI', 'EI', 'AI', 'ETTI', 'GEIQ', 'EITI')
  AND latitude IS NOT NULL;
```

## Autres structures

La table `data_inclusion.structures_v0` contient également d'autres types de structures (~73 000 au total) :
- Structures France Travail
- Missions locales
- Structures d'accompagnement social
- etc.

Ces structures ont `typologie = 'Autre'` ou d'autres valeurs.

## Coordonnées GPS

- **Couverture :** 96.4% des structures ont des coordonnées GPS
- **Source :** Géocodage des adresses ou API Le Marché
- **Colonnes :** `latitude`, `longitude`

## Liens

- [Table Metabase](../metabase/README.md#data_inclusionstructures_v0)
- [Analyse géospatiale](../metabase/README.md#analyses-géospatiales-lourdes)
