#!/usr/bin/env python3
"""
Migrate existing report files to the database.

This script:
1. Reads all .md files from ./reports/
2. Parses YAML front-matter for metadata
3. Creates a conversation and report record for each
4. Stores the report content as an assistant message

Usage:
    python -m scripts.migrate_reports
    python -m scripts.migrate_reports --dry-run
"""

import argparse
import re
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from web.database import store, init_db


def parse_front_matter(content: str) -> tuple[dict, str]:
    """Parse YAML front-matter from markdown content."""
    if not content.startswith("---\n"):
        return {}, content

    match = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
    if not match:
        return {}, content

    front_matter = match.group(1)
    body = content[match.end():]

    metadata = {}
    for line in front_matter.split("\n"):
        if ":" in line:
            key, value = line.split(":", 1)
            metadata[key.strip().lower()] = value.strip()

    return metadata, body


def migrate_reports(reports_dir: Path, dry_run: bool = False):
    """Migrate all reports from filesystem to database."""
    if not reports_dir.exists():
        print(f"Reports directory not found: {reports_dir}")
        return

    # Initialize database
    if not dry_run:
        init_db()

    md_files = list(reports_dir.glob("*.md"))
    print(f"Found {len(md_files)} markdown files in {reports_dir}")
    print("-" * 60)

    migrated = 0
    skipped = 0

    for md_file in sorted(md_files):
        content = md_file.read_text()
        metadata, body = parse_front_matter(content)

        # Skip if no front-matter (not a proper report)
        if not metadata:
            print(f"SKIP (no front-matter): {md_file.name}")
            skipped += 1
            continue

        # Extract metadata
        title = metadata.get("query category", md_file.stem)
        website = metadata.get("website")
        category = metadata.get("query category")
        date_str = metadata.get("date", "")

        print(f"MIGRATE: {md_file.name}")
        print(f"  Title: {title}")
        print(f"  Website: {website}")
        print(f"  Category: {category}")

        if dry_run:
            print(f"  [DRY RUN - would create conversation and report]")
        else:
            # Create conversation
            conv = store.create_conversation()

            # Add a synthetic user message (the original query if available)
            original_query = metadata.get("original query", f"Generate a report about {title}")
            store.add_message(conv.id, "user", original_query)

            # Add the report content as assistant message
            msg = store.add_message(conv.id, "assistant", content)

            # Create report record
            report = store.create_report(
                conv_id=conv.id,
                message_id=msg.id,
                title=title,
                website=website,
                category=category,
                original_query=original_query,
            )

            # Update conversation title
            store.update_conversation(conv.id, title=title)

            print(f"  Created: conversation={conv.id[:8]}..., report={report.id}")

        migrated += 1
        print()

    print("-" * 60)
    print(f"Migrated: {migrated}")
    print(f"Skipped: {skipped}")

    if dry_run:
        print("\nThis was a dry run. No changes were made.")
        print("Run without --dry-run to actually migrate.")


def main():
    parser = argparse.ArgumentParser(description="Migrate reports to database")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")
    parser.add_argument("--reports-dir", type=Path, default=project_root / "reports", help="Reports directory")
    args = parser.parse_args()

    migrate_reports(args.reports_dir, args.dry_run)


if __name__ == "__main__":
    main()
