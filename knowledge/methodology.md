# Méthodologie d'analyse

Principes à respecter pour toutes les analyses de données, quelle que soit la source
(Metabase Stats, Metabase Datalake, Matomo, etc.).

## Données temporelles

### Choix de la date de référence

Les événements métier ont souvent plusieurs dates associées. **Toujours clarifier 
avec l'utilisateur quelle date utiliser** car les résultats peuvent différer significativement.

| Service | Dates possibles | Écart typique |
|---------|-----------------|---------------|
| Emplois (candidatures) | Date candidature vs date embauche | 30+ jours |
| RDV-Insertion | Date prise de RDV vs date du RDV vs date de présence | Variable |
| Marché | Date demande vs date mise en relation | Variable |

**Action :** Poser la question systématiquement avant toute analyse temporelle.

### Comparabilité des taux dans le temps

Les taux basés sur des événements différés (réponse, embauche, conversion) sont **biaisés 
par l'ancienneté** : les données anciennes ont eu plus de temps pour atteindre l'état final.

**Bonne pratique :** Utiliser une **fenêtre fixe** pour rendre les taux comparables.

Exemple : "Taux de candidatures validées **en moins de 30 jours**"
- ✅ Exclure les candidatures de moins de 30 jours (pas encore comparables)
- ✅ Appliquer la même fenêtre à toutes les périodes

```sql
-- Taux de validation à 30 jours (comparable dans le temps)
SELECT 
    DATE_TRUNC('month', date_candidature) as mois,
    COUNT(*) FILTER (WHERE statut = 'validée' 
                     AND date_validation - date_candidature <= 30) * 100.0 
    / COUNT(*) as taux_validation_30j
FROM candidatures
WHERE date_candidature < CURRENT_DATE - INTERVAL '30 days'
GROUP BY 1
```

## Jointures et filtres multiples

### Risque de confusion linguistique

Quand un utilisateur formule une requête avec des critères multiples, la formulation naturelle peut induire en erreur :

| Formulation utilisateur | Interprétation probable | Risque |
|------------------------|------------------------|--------|
| "Les candidats qui ont X **et** Y" | INNER JOIN (intersection) | L'utilisateur voulait peut-être une union |
| "Les candidats de X **et** de Y" | Ambigu | Clarifier avant d'exécuter |
| "Les candidats avec X, Y, Z" | Liste = souvent union | Mais syntaxe SQL = intersection |

### Règles à suivre

1. **Alerter en cas d'ambiguïté** — Quand une requête implique plusieurs critères de filtrage ou des jointures, signaler le risque :
   > "Votre demande mentionne plusieurs critères. Pour être sûr de bien répondre : voulez-vous les éléments qui correspondent à **tous** ces critères (intersection), ou ceux qui correspondent à **au moins un** (union) ?"

2. **Expliciter les jointures** — Après chaque requête impliquant des jointures, expliquer en langage clair :
   > "J'ai utilisé une jointure qui **conserve uniquement** les candidats présents dans les deux tables (INNER JOIN). Les candidats présents dans une seule table sont exclus."
   
   Ou :
   > "J'ai utilisé une jointure qui **conserve tous** les candidats de la table principale, même s'ils n'ont pas de correspondance dans l'autre table (LEFT JOIN)."

3. **Privilégier LEFT JOIN par défaut** — Sauf indication contraire explicite, préférer LEFT JOIN pour éviter de perdre des données silencieusement. Un INNER JOIN qui exclut des lignes doit être un choix conscient, pas un effet de bord.

### Formulation type pour les résultats

Après une requête avec jointures, inclure systématiquement :
> "Note sur les données : Cette analyse utilise une jointure [INNER/LEFT] entre [table A] et [table B].
> - Lignes dans A : X
> - Lignes dans B : Y
> - Lignes après jointure : Z
> [Si Z < X ou Z < Y] → Certaines lignes ont été exclues car elles n'avaient pas de correspondance."
