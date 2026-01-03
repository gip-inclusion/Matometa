#!/usr/bin/env python3
"""
Sync Metabase dashboards to SQLite database.

Usage:
    python -m skills.metabase_sync.scripts.sync_dashboards

This script:
1. Fetches dashboards from Metabase (based on cards' dashboard_ids)
2. Extracts descriptions from virtual text cards
3. Maps to pilotage.inclusion.beta.gouv.fr URLs
4. Assigns topics based on content
5. Writes to SQLite database
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from skills.metabase_query.scripts.metabase import MetabaseAPI, MetabaseError
from skills.metabase_query.scripts.cards_db import CardsDB, TOPICS


# Mapping from pilotage URLs to Metabase dashboard IDs and topics
# Based on https://pilotage.inclusion.beta.gouv.fr/tableaux-de-bord/
PILOTAGE_DASHBOARDS = {
    # L'offre d'insertion par l'activité économique (IAE)
    "/tableaux-de-bord/metiers/": {
        "name": "Métiers recherchés et proposés",
        "topic": "candidatures",
    },
    "/tableaux-de-bord/postes-en-tension/": {
        "name": "Postes en tension",
        "topic": "postes-tension",
    },
    "/tableaux-de-bord/zoom-employeurs/": {
        "name": "Zoom sur les employeurs",
        "topic": "employeurs",
    },
    # Les publics dans l'IAE
    "/tableaux-de-bord/candidat-file-active-IAE/": {
        "name": "Candidats dans la file active IAE depuis plus de 30 jours",
        "topic": "file-active",
        "dashboard_id": 408,
    },
    "/tableaux-de-bord/femmes-iae/": {
        "name": "Représentation des femmes dans les candidatures vers l'IAE",
        "topic": "demographie",
    },
    # Les candidatures vers l'IAE
    "/tableaux-de-bord/bilan-candidatures-iae/": {
        "name": "Bilan annuel des candidatures émises vers les SIAE",
        "topic": "candidatures",
    },
    "/tableaux-de-bord/cartographies-iae/": {
        "name": "Cartographies des orientations vers les SIAE",
        "topic": "candidatures",
    },
    "/tableaux-de-bord/etat-suivi-candidatures/": {
        "name": "Traitement et résultats des candidatures émises",
        "topic": "candidatures",
        "dashboard_id": 337,
    },
    "/tableaux-de-bord/auto-prescription/": {
        "name": "Activité d'auto-prescription et de contrôle à posteriori",
        "topic": "auto-prescription",
        "dashboard_id": 267,
    },
    "/tableaux-de-bord/zoom-prescripteurs/": {
        "name": "Zoom sur les prescripteurs",
        "topic": "prescripteurs",
        "dashboard_id": 287,
    },
    "/tableaux-de-bord/prescripteurs-habilites/": {
        "name": "L'accompagnement des prescripteurs habilités",
        "topic": "prescripteurs",
    },
    # Le pilotage du dispositif IAE
    "/tableaux-de-bord/conventionnements-iae/": {
        "name": "Conventionnements IAE",
        "topic": "generalites-iae",
    },
    "/tableaux-de-bord/analyses-conventionnements-iae/": {
        "name": "Analyse autour des conventionnements IAE",
        "topic": "generalites-iae",
    },
    "/tableaux-de-bord/suivi-demandes-prolongation/": {
        "name": "Demandes de prolongation",
        "topic": "prolongations",
        "dashboard_id": 336,
    },
    "/tableaux-de-bord/suivi-pass-iae/": {
        "name": "Suivi des Pass IAE",
        "topic": "generalites-iae",
    },
    # ESAT
    "/tableaux-de-bord/zoom-esat-2025/": {
        "name": "Zoom sur les ESAT (2025)",
        "topic": "esat",
        "dashboard_id": 471,
    },
    "/tableaux-de-bord/zoom-esat-2024/": {
        "name": "Zoom sur les ESAT (2024)",
        "topic": "esat",
    },
    "/tableaux-de-bord/zoom-esat/": {
        "name": "Zoom sur les ESAT (2023)",
        "topic": "esat",
    },
    # L'offre d'insertion sur le territoire
    "/tableaux-de-bord/analyse-offre-insertion-sur-le-territoire/": {
        "name": "Analyse de l'offre d'insertion sur le territoire",
        "topic": "generalites-iae",
    },
}

# Additional known dashboard IDs with their topics (from card analysis)
KNOWN_DASHBOARDS = {
    52: ("etp-effectifs", None),
    54: ("etp-effectifs", None),
    116: ("candidatures", None),
    136: ("demographie", None),
    150: ("employeurs", None),
    216: ("esat", None),
    217: ("candidatures", None),
    265: ("controles", "/tableaux-de-bord/auto-prescription/"),
    267: ("auto-prescription", "/tableaux-de-bord/auto-prescription/"),
    287: ("prescripteurs", "/tableaux-de-bord/zoom-prescripteurs/"),
    325: ("etp-effectifs", None),
    336: ("prolongations", "/tableaux-de-bord/suivi-demandes-prolongation/"),
    337: ("candidatures", "/tableaux-de-bord/etat-suivi-candidatures/"),
    408: ("file-active", "/tableaux-de-bord/candidat-file-active-IAE/"),
    471: ("esat", "/tableaux-de-bord/zoom-esat-2025/"),
}


def extract_dashboard_text(dashboard_data: dict) -> str:
    """Extract text from virtual text cards in a dashboard."""
    texts = []
    dashcards = dashboard_data.get('dashcards', [])

    for dc in dashcards:
        viz = dc.get('visualization_settings', {})
        text = viz.get('text', '')
        card = dc.get('card')
        # Virtual cards have no card or card with no id
        if text and (card is None or card.get('id') is None):
            texts.append(text)

    return "\n\n".join(texts)


def infer_topic_from_name(name: str) -> str:
    """Infer topic from dashboard name."""
    name_lower = name.lower()

    if "esat" in name_lower:
        return "esat"
    if "file active" in name_lower or "recherche active" in name_lower:
        return "file-active"
    if "tension" in name_lower:
        return "postes-tension"
    if "femme" in name_lower or "genre" in name_lower or "âge" in name_lower:
        return "demographie"
    if "prescripteur" in name_lower:
        return "prescripteurs"
    if "auto-prescription" in name_lower or "autoprescription" in name_lower:
        return "auto-prescription"
    if "prolongation" in name_lower:
        return "prolongations"
    if "candidature" in name_lower:
        return "candidatures"
    if "employeur" in name_lower or "siae" in name_lower:
        return "employeurs"
    if "contrôle" in name_lower or "cap " in name_lower:
        return "controles"
    if "etp" in name_lower or "effectif" in name_lower:
        return "etp-effectifs"
    if "convention" in name_lower or "pass iae" in name_lower:
        return "generalites-iae"

    return "autre"


def main():
    print("=" * 70)
    print("Metabase Dashboards Sync")
    print("=" * 70)
    print()

    # Initialize API and DB
    try:
        api = MetabaseAPI()
        print("✅ Metabase API connected")
    except Exception as e:
        print(f"❌ Failed to connect to Metabase: {e}")
        sys.exit(1)

    db = CardsDB()
    db.init_schema()  # Ensure schema is up to date
    db.clear_dashboards()
    print("🗑️  Cleared existing dashboards")

    # Get unique dashboard IDs from cards
    dashboard_ids = set(db.dashboards_summary().keys())
    print(f"\n📋 Found {len(dashboard_ids)} unique dashboards from cards")

    # Fetch and store each dashboard
    print("\n🔍 Fetching dashboard details...")
    print("-" * 70)

    for dash_id in sorted(dashboard_ids):
        try:
            dashboard_data = api.get_dashboard(dash_id)
            name = dashboard_data.get('name', f'Dashboard {dash_id}')
            metabase_desc = dashboard_data.get('description', '')
            collection_id = dashboard_data.get('collection_id')

            # Extract text from virtual cards
            text_content = extract_dashboard_text(dashboard_data)

            # Combine descriptions
            description = metabase_desc or ""
            if text_content:
                if description:
                    description += "\n\n"
                description += text_content[:1000]  # Limit length

            # Get topic and pilotage URL from known mappings
            if dash_id in KNOWN_DASHBOARDS:
                topic, pilotage_url = KNOWN_DASHBOARDS[dash_id]
            else:
                topic = infer_topic_from_name(name)
                pilotage_url = None

            db.upsert_dashboard(
                dashboard_id=dash_id,
                name=name,
                description=description if description else None,
                topic=topic,
                pilotage_url=pilotage_url,
                collection_id=collection_id,
            )

            url_info = f" → {pilotage_url}" if pilotage_url else ""
            print(f"  [{dash_id}] {name[:50]}... ({topic}){url_info}")

        except MetabaseError as e:
            print(f"  [{dash_id}] Error: {e}")

    db.commit()
    print()
    print(f"✅ {len(dashboard_ids)} dashboards synced")

    # Summary
    print("\n" + "=" * 70)
    print("Summary by topic:")
    print("-" * 70)

    dashboards = db.all_dashboards()
    topic_counts = {}
    for d in dashboards:
        topic_counts[d.topic] = topic_counts.get(d.topic, 0) + 1

    for topic, count in sorted(topic_counts.items(), key=lambda x: -x[1]):
        print(f"  {topic}: {count}")

    db.close()


if __name__ == "__main__":
    main()
