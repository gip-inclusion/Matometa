#!/usr/bin/env python3
"""Backfill script to add tags to existing reports."""

import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.database import init_db, store

# Manual tag mappings based on our earlier analysis
# Format: report_id -> list of tag names
REPORT_TAGS = {
    43: ["marche", "acheteurs", "analyse"],
    42: ["multi", "structures", "trafic", "iae", "analyse"],
    41: ["emplois", "candidats", "iae", "analyse"],
    40: ["multi", "prescripteurs", "trafic", "analyse"],
    39: ["emplois", "prescripteurs", "analyse"],
    38: ["rdv-insertion", "trafic", "meta"],
    37: ["emplois", "iae", "analyse"],
    36: ["pilotage", "structures", "iae", "analyse"],
    35: ["emplois", "structures", "geographique", "iae", "analyse"],
    34: ["emplois", "structures", "geographique", "appli"],
    33: ["emplois", "structures", "geographique", "iae", "analyse"],
    32: ["emplois", "trafic", "analyse"],
    31: ["multi", "trafic", "analyse"],
    30: ["plateforme", "trafic", "analyse"],
    29: ["marche", "acheteurs", "fournisseurs", "trafic", "analyse"],
    28: ["marche", "acheteurs", "fournisseurs", "analyse"],
    26: ["mon-recap", "commandes", "conversions", "analyse"],
    25: ["marche", "meta"],
    24: ["marche", "acheteurs", "depot-de-besoin", "extraction"],
    23: ["multi", "geographique", "analyse"],
}


def backfill_tags(dry_run: bool = False):
    """Apply tag mappings to reports."""
    init_db()

    print(f"{'DRY RUN - ' if dry_run else ''}Backfilling report tags...")
    print()

    # Get all reports
    reports = store.list_reports(include_archived=True, limit=200)

    tagged_count = 0
    skipped_count = 0

    for report in reports:
        if report.id in REPORT_TAGS:
            tags = REPORT_TAGS[report.id]
            existing_tags = store.get_report_tags(report.id)
            existing_tag_names = [t.name for t in existing_tags]

            if set(existing_tag_names) == set(tags):
                print(f"  [{report.id}] {report.title[:50]}... - already tagged")
                skipped_count += 1
                continue

            print(f"  [{report.id}] {report.title[:50]}...")
            print(f"       Tags: {', '.join(tags)}")

            if not dry_run:
                store.set_report_tags(report.id, tags, update_timestamp=False)

            tagged_count += 1
        else:
            print(f"  [{report.id}] {report.title[:50]}... - NO MAPPING")
            skipped_count += 1

    print()
    print(f"{'Would tag' if dry_run else 'Tagged'}: {tagged_count} reports")
    print(f"Skipped: {skipped_count} reports")

    if dry_run:
        print()
        print("Run without --dry-run to apply changes.")


def list_untagged():
    init_db()

    reports = store.list_reports(include_archived=True, limit=200)

    print("Reports without tag mappings:")
    print()
    for report in reports:
        if report.id not in REPORT_TAGS:
            print(f"  {report.id}: {report.title}")
            if report.website:
                print(f"       website: {report.website}")
            if report.category:
                print(f"       category: {report.category}")
            print()


def suggest_tags():
    """
    Suggest new tags based on report metadata that don't exist yet.
    Outputs suggestions that can be added to the taxonomy.
    """
    init_db()

    # Get all existing tags
    existing_tags = {t.name for t in store.get_all_tags()}

    # Collect potential new tags from reports
    wishlist = {}

    reports = store.list_reports(include_archived=True, limit=200)
    for report in reports:
        # Check website field
        if report.website:
            normalized = report.website.lower().strip().strip("[]")
            if normalized and normalized not in existing_tags:
                if normalized not in wishlist:
                    wishlist[normalized] = {"type": "product", "sources": []}
                wishlist[normalized]["sources"].append(f"report {report.id}: {report.title[:40]}")

        # Check category field
        if report.category:
            normalized = report.category.lower().strip().replace(" ", "-")
            if normalized and normalized not in existing_tags:
                if normalized not in wishlist:
                    wishlist[normalized] = {"type": "theme", "sources": []}
                wishlist[normalized]["sources"].append(f"report {report.id}: {report.title[:40]}")

        # Check existing tags field (JSON array)
        if report.tags:
            for tag in report.tags:
                normalized = tag.lower().strip().replace(" ", "-")
                if normalized and normalized not in existing_tags:
                    if normalized not in wishlist:
                        wishlist[normalized] = {"type": "theme", "sources": []}
                    wishlist[normalized]["sources"].append(f"report {report.id}: {report.title[:40]}")

    if not wishlist:
        print("No new tags to suggest - all existing metadata maps to known tags.")
        return

    print("Suggested new tags (wishlist):")
    print()
    for tag_name, info in sorted(wishlist.items()):
        print(f"  {tag_name}")
        print(f"    suggested type: {info['type']}")
        print("    found in:")
        for source in info["sources"][:3]:  # Limit to 3 examples
            print(f"      - {source}")
        if len(info["sources"]) > 3:
            print(f"      ... and {len(info['sources']) - 3} more")
        print()

    print("To request new tags, use the /wishlist skill to notify admins.")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    list_only = "--list" in sys.argv
    suggest_only = "--suggest" in sys.argv

    if list_only:
        list_untagged()
    elif suggest_only:
        suggest_tags()
    else:
        backfill_tags(dry_run=dry_run)
