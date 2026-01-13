# CLPE - Comités Locaux Pour l'Emploi

Documentation des données CLPE disponibles dans Metabase.

## Définition

Les CLPE (Comités Locaux Pour l'Emploi) sont des territoires de référence pour l'analyse de l'offre et de la demande d'emploi dans l'IAE.

**Volumétrie :** 357 CLPE couvrant l'ensemble du territoire français.

## Tables disponibles

### public.ref_clpe_ft

Table de liaison entre communes et CLPE.

| Colonne | Type | Description |
|---------|------|-------------|
| code_commune | VARCHAR | Code INSEE de la commune |
| code_clpe | VARCHAR | Code du CLPE |
| nom_clpe | TEXT | Nom du CLPE |

```sql
-- Exemple : communes d'un CLPE
SELECT code_commune, nom_clpe
FROM public.ref_clpe_ft
WHERE code_clpe = 'CLPE_001';

-- Nombre de communes par CLPE
SELECT code_clpe, nom_clpe, COUNT(*) as nb_communes
FROM public.ref_clpe_ft
GROUP BY code_clpe, nom_clpe
ORDER BY nb_communes DESC;
```

### public.offre_demande_clpe

Données d'offre et demande d'emploi agrégées par CLPE.

## Cartographie

**Attention :** Les tables CLPE ne contiennent pas de géométrie (polygones).

Pour cartographier les CLPE :
1. Récupérer les communes de chaque CLPE via `ref_clpe_ft`
2. Obtenir les géométries des communes (API geo.api.gouv.fr ou GeoJSON France)
3. Fusionner les polygones des communes par CLPE, ou calculer un centroïde

```python
# Exemple : centroïde d'un CLPE à partir des communes
from statistics import mean

communes_du_clpe = [...]  # liste avec lat/lon
centroid_lat = mean(c['latitude'] for c in communes_du_clpe)
centroid_lon = mean(c['longitude'] for c in communes_du_clpe)
```

## Liens

- [Table Metabase ref_clpe_ft](../metabase/README.md#publicref_clpe_ft)
- [Table Metabase offre_demande_clpe](../metabase/README.md#publicoffre_demande_clpe)
