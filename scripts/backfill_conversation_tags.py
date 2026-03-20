#!/usr/bin/env python3
"""
Backfill script to auto-tag existing conversations using the configured LLM backend.

Usage:
    python scripts/backfill_conversation_tags.py [--dry-run] [--limit N]

Run with --dry-run to see what would be tagged without making changes.
"""

import argparse
import os
import sys
import time

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web import config, llm
from web.database import get_db, init_db, store

# Tag taxonomy (must match database _seed_tags)
TAG_TAXONOMY = """
## Produits (choisir 1 seul, obligatoire)
- emplois: Les Emplois de l'inclusion
- dora: Dora (annuaire de services)
- marche: Le Marché de l'inclusion
- communaute: La Communauté de l'inclusion
- pilotage: Pilotage de l'inclusion
- plateforme: inclusion.gouv.fr (site vitrine)
- rdv-insertion: RDV-Insertion
- mon-recap: Mon Récap
- multi: Multi-produits (concerne plusieurs produits)

## Thèmes - Acteurs (0 à 2)
- candidats: Candidats / demandeurs d'emploi
- prescripteurs: Prescripteurs
- employeurs: Employeurs / SIAE
- structures: Structures / SIAE (angle organisation)
- acheteurs: Acheteurs (Marché)
- fournisseurs: Fournisseurs (Marché)

## Thèmes - Concepts métier (0 à 2)
- iae: IAE en général
- orientation: Orientation
- depot-de-besoin: Dépôt de besoin (Marché)
- demande-de-devis: Demande de devis (Marché)
- commandes: Commandes (Mon Récap)

## Thèmes - Métriques (0 à 2)
- trafic: Analyse de trafic
- conversions: Conversions / funnel
- retention: Rétention / fidélisation
- geographique: Analyse géographique

## Type de demande (choisir 1 seul, obligatoire)
- extraction: Extraction de données brutes
- analyse: Analyse / rapport
- appli: Application interactive
- meta: Question sur Autometa lui-même
"""

VALID_TAGS = {
    "emplois",
    "dora",
    "marche",
    "communaute",
    "pilotage",
    "plateforme",
    "rdv-insertion",
    "mon-recap",
    "multi",
    "matomo",
    "stats",
    "datalake",
    "candidats",
    "prescripteurs",
    "employeurs",
    "structures",
    "acheteurs",
    "fournisseurs",
    "iae",
    "orientation",
    "depot-de-besoin",
    "demande-de-devis",
    "commandes",
    "trafic",
    "conversions",
    "retention",
    "geographique",
    "extraction",
    "analyse",
    "appli",
    "meta",
}


def get_untagged_conversations(limit: int = 100):
    """Get conversations that have no tags."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT c.id, c.title, c.created_at
            FROM conversations c
            WHERE (c.conv_type = 'exploration' OR c.conv_type IS NULL)
            AND NOT EXISTS (
                SELECT 1 FROM conversation_tags ct WHERE ct.conversation_id = c.id
            )
            ORDER BY c.created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_first_user_message(conv_id: str) -> str | None:
    """Get the first user message from a conversation."""
    messages = store.get_messages(conv_id, types=["user"], limit=1)
    if messages:
        return messages[0].content
    return None


def _parse_tags(response: str) -> list[str]:
    """Extract valid tag names from response."""
    # Handle potential explanation text - take just the tag line
    if "\n" in response:
        for line in response.split("\n"):
            if "," in line and not line.startswith("#"):
                response = line
                break

    tag_names = []
    for part in response.replace("\n", ",").split(","):
        tag = part.strip().lower().strip(".-*")
        if tag in VALID_TAGS:
            tag_names.append(tag)
    return tag_names


def _build_prompt(message: str) -> str:
    """Build the tagging prompt."""
    return f"""Analyse cette demande utilisateur et attribue des tags parmi la taxonomie suivante.

{TAG_TAXONOMY}

Règles:
- OBLIGATOIRE: exactement 1 tag produit
- OBLIGATOIRE: exactement 1 tag type_demande
- OPTIONNEL: 0 à 2 tags thème (acteurs, concepts, métriques)
- Si la demande mentionne plusieurs produits, utilise "multi"
- Si c'est une question sur l'outil Autometa, utilise "meta"

Demande: {message[:1000]}

Réponds UNIQUEMENT avec les noms des tags séparés par des virgules, rien d'autre.
Exemple: emplois, candidats, trafic, analyse"""


def generate_tags_for_message(message: str) -> list[str]:
    """Generate tags using the configured LLM backend."""
    prompt = _build_prompt(message)
    model = config.OLLAMA_TAG_MODEL if config.LLM_BACKEND == "ollama" else config.CLAUDE_MODEL

    try:
        response = llm.generate_text(prompt, model=model, max_tokens=100)
        return _parse_tags(response)
    except Exception as exc:
        print(f"    Error: {exc}")
        return []


def backfill_tags(dry_run: bool = False, limit: int = 100, delay: float = 1.0):
    """Tag untagged conversations using the configured AGENT_BACKEND."""
    init_db()

    print(f"{'DRY RUN - ' if dry_run else ''}Backfilling conversation tags...")
    print(f"Backend: {config.LLM_BACKEND}, Limit: {limit}, Delay: {delay}s")
    print()

    conversations = get_untagged_conversations(limit=limit)
    print(f"Found {len(conversations)} untagged conversations")
    print()

    tagged_count = 0
    skipped_count = 0
    failed_count = 0

    for i, conv in enumerate(conversations, 1):
        conv_id = conv["id"]
        title = conv["title"] or "(no title)"

        print(f"[{i}/{len(conversations)}] {conv_id[:8]}... {title[:50]}")

        # Get first user message
        message = get_first_user_message(conv_id)
        if not message:
            print("    Skipped: no user message")
            skipped_count += 1
            continue

        print(f"    Message: {message[:60]}...")

        # Generate tags
        tags = generate_tags_for_message(message)
        if not tags:
            print("    Failed: no tags generated")
            failed_count += 1
            continue

        print(f"    Tags: {', '.join(tags)}")

        if not dry_run:
            store.set_conversation_tags(conv_id, tags, update_timestamp=False)
            print("    Saved!")

        tagged_count += 1

        # Rate limiting to avoid overwhelming the CLI
        if i < len(conversations) and not dry_run:
            time.sleep(delay)

    print()
    print("=" * 60)
    print(f"{'Would tag' if dry_run else 'Tagged'}: {tagged_count} conversations")
    print(f"Skipped (no message): {skipped_count}")
    print(f"Failed: {failed_count}")

    if dry_run:
        print()
        print("Run without --dry-run to apply changes.")


def list_untagged():
    """List conversations that don't have tags."""
    init_db()

    conversations = get_untagged_conversations(limit=200)

    print(f"Untagged conversations: {len(conversations)}")
    print()
    for conv in conversations:
        print(f"  {conv['id'][:8]}... {conv['title'] or '(no title)'}")
        message = get_first_user_message(conv["id"])
        if message:
            print(f"    First message: {message[:80]}...")
        print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill conversation tags")
    parser.add_argument("--dry-run", action="store_true", help="Preview without making changes")
    parser.add_argument("--list", action="store_true", help="List untagged conversations")
    parser.add_argument("--limit", type=int, default=100, help="Max conversations to process")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between API calls (seconds)")

    args = parser.parse_args()

    if args.list:
        list_untagged()
    else:
        backfill_tags(dry_run=args.dry_run, limit=args.limit, delay=args.delay)
