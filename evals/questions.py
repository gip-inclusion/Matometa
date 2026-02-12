"""Eval question bank — factual questions with verifiable API answers."""

PROMPT_TEMPLATE = """\
MODE ÉVALUATION — réponds directement, sans poser de questions ni proposer d'options.

{question}

IMPORTANT: Structure ta réponse exactement ainsi:

## Données brutes
Un bloc ```json contenant un tableau d'objets, chacun représentant un appel API:
[{{"source": "matomo"|"metabase", "method_or_sql": "...", "params": {{}}, "result": {{}}}}]
Copie EXACTE des réponses API, sans modification ni arrondi.

## Analyse
3-5 phrases d'interprétation basées uniquement sur les données ci-dessus.\
"""


QUESTIONS = [
    {
        "id": "emplois_jan26",
        "description": "Traffic Emplois janvier 2026 (single Matomo call)",
        "question": (
            "Quelles sont les statistiques de visites du site Emplois "
            "(idSite=117) pour le mois de janvier 2026 ? "
            "Utilise la méthode VisitsSummary.get avec period=month et date=2026-01-01."
        ),
    },
    {
        "id": "emplois_vs_marche",
        "description": "Compare Emplois vs Marché janvier 2026 (two Matomo calls)",
        "question": (
            "Compare les statistiques de visites de janvier 2026 entre "
            "le site Emplois (idSite=117) et le site le Marché de l'inclusion (idSite=136). "
            "Utilise VisitsSummary.get pour chaque site avec period=month et date=2026-01-01."
        ),
    },
    {
        "id": "monrecap_yoy",
        "description": "Mon Recap year-over-year (hallucination scenario)",
        "question": (
            "Compare les statistiques de visites du site Mon Recap (idSite=217) "
            "entre janvier 2025 (date=2025-01-01) et janvier 2026 (date=2026-01-01). "
            "Utilise VisitsSummary.get pour chaque période avec period=month."
        ),
    },
    {
        "id": "candidatures_jan26",
        "description": "Candidatures acceptées janvier 2026 (Metabase SQL)",
        "question": (
            "Combien de candidatures ont été acceptées en janvier 2026 ? "
            "Interroge la base Metabase stats (database_id=2) avec cette requête SQL : "
            "SELECT COUNT(*) AS total FROM candidatures_echelle_locale "
            "WHERE etat = 'Candidature acceptée' "
            "AND date_debut_contrat >= '2026-01-01' AND date_debut_contrat < '2026-02-01'"
        ),
    },
    {
        "id": "emplois_cross_source",
        "description": "Emplois traffic + candidatures cross-check (Matomo + Metabase)",
        "question": (
            "Pour le site Emplois en janvier 2026, donne : "
            "1) les stats de visites Matomo (VisitsSummary.get, idSite=117, period=month, date=2026-01-01) "
            "2) le nombre total de candidatures créées sur la même période via Metabase stats "
            "(database_id=2, SQL: SELECT COUNT(*) AS total FROM candidatures_echelle_locale "
            "WHERE date_candidature >= '2026-01-01' AND date_candidature < '2026-02-01')"
        ),
    },
]


BACKENDS = ["cli", "ollama", "cli-ollama"]
