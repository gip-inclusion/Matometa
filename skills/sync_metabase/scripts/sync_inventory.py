#!/usr/bin/env python3
"""
Sync Metabase cards inventory to SQLite database.

Usage:
    python -m skills.sync_metabase.scripts.sync_inventory
    python -m skills.sync_metabase.scripts.sync_inventory --skip-categorize
    python -m skills.sync_metabase.scripts.sync_inventory --collections 453 452

This script:
1. Fetches cards metadata from Metabase collections
2. Extracts SQL queries (native or compiled from GUI queries)
3. Optionally categorizes with Claude AI
4. Writes to SQLite database
5. Regenerates the README.md index
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from skills.metabase_query.scripts.metabase import MetabaseAPI, MetabaseError
from skills.metabase_query.scripts.cards_db import CardsDB, TOPICS, DB_PATH


# Default collections to sync
DEFAULT_COLLECTIONS = [453]


def progress_bar(current: int, total: int, prefix: str = "", suffix: str = "", length: int = 40):
    """Simple progress bar."""
    if total == 0:
        return
    percent = 100 * current / total
    filled = int(length * current // total)
    bar = "█" * filled + "░" * (length - filled)
    print(f"\r{prefix} |{bar}| {percent:.1f}% {suffix}", end="", flush=True)
    if current == total:
        print()


def extract_table_references(sql: str) -> list[str]:
    """Extract table names from SQL query."""
    if not sql:
        return []

    tables = set()
    patterns = [
        r'FROM\s+"?(\w+)"?\."?(\w+)"?',  # schema.table
        r'FROM\s+"?(\w+)"?(?:\s|$|,)',   # simple table
        r'JOIN\s+"?(\w+)"?\."?(\w+)"?',   # schema.table in JOIN
        r'JOIN\s+"?(\w+)"?(?:\s|$)',      # simple table in JOIN
    ]

    skip_words = {'select', 'case', 'when', 'then', 'else', 'end', 'as', 'on', 'and', 'or'}

    for pattern in patterns:
        matches = re.findall(pattern, sql, re.IGNORECASE)
        for match in matches:
            if isinstance(match, tuple):
                # Take the last non-empty part (table name)
                table = [m for m in match if m][-1] if match else None
            else:
                table = match

            if table and table.lower() not in skip_words:
                tables.add(table)

    return sorted(tables)


def categorize_cards_with_claude(cards: list[dict], api_key: str) -> dict[int, tuple[str, str]]:
    """
    Categorize cards using Claude AI.

    Returns dict of card_id -> (topic, reason)
    """
    try:
        from anthropic import Anthropic
    except ImportError:
        print("   ⚠️  anthropic package not installed, skipping AI categorization")
        return {}

    client = Anthropic(api_key=api_key)

    topic_list = "\n".join(f"- {topic}: {desc}" for topic, desc in TOPICS.items())

    results = {}
    batch_size = 15
    total_batches = (len(cards) + batch_size - 1) // batch_size

    for i in range(0, len(cards), batch_size):
        batch_num = i // batch_size + 1
        progress_bar(batch_num - 1, total_batches, prefix="   Categorizing", suffix=f"batch {batch_num}/{total_batches}")

        batch = cards[i:i + batch_size]
        card_summaries = []
        for card in batch:
            sql = card.get("sql_query", "")[:800]
            card_summaries.append({
                "id": card["id"],
                "title": card["name"],
                "sql": sql,
            })

        prompt = f"""Categorize these Metabase cards about French IAE employment data.

Categories:
{topic_list}

Cards:
{json.dumps(card_summaries, indent=2, ensure_ascii=False)}

Return JSON array:
[{{"id": 7090, "topic": "candidatures", "reason": "queries candidature table"}}, ...]

Use ONLY the topic slugs listed. Look at SQL table names and fields.
"""

        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}]
            )
            result_text = response.content[0].text.strip()

            # Extract JSON from response
            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]

            categorizations = json.loads(result_text)
            for item in categorizations:
                results[item["id"]] = (item["topic"], item.get("reason", ""))

        except Exception as e:
            print(f"\n   ⚠️  Batch error: {e}")
            for card in batch:
                results[card["id"]] = ("autre", "error")

    progress_bar(total_batches, total_batches, prefix="   Categorizing", suffix=f"batch {total_batches}/{total_batches}")
    return results


def generate_readme(db: CardsDB, last_sync: str):
    """Generate README.md index file."""
    readme_path = DB_PATH.parent / "README.md"

    topics_summary = db.topics_summary()
    tables_summary = db.tables_summary()
    total_cards = db.count()

    lines = [
        "# Metabase Cards Inventory",
        "",
        f"**Database:** `knowledge/metabase/cards.db`",
        f"**Last synced:** {last_sync}",
        f"**Total cards:** {total_cards}",
        "",
        "## Database Schema",
        "",
        "```sql",
        "CREATE TABLE cards (",
        "    id INTEGER PRIMARY KEY,",
        "    name TEXT NOT NULL,",
        "    description TEXT,",
        "    collection_id INTEGER,",
        "    dashboard_id INTEGER,  -- Extracted from [XXX] prefix in name",
        "    topic TEXT,",
        "    sql_query TEXT,",
        "    tables_referenced TEXT,  -- JSON array",
        "    created_at TEXT,",
        "    updated_at TEXT",
        ");",
        "",
        "CREATE VIRTUAL TABLE cards_fts USING fts5(",
        "    name, description, sql_query",
        ");",
        "",
        "CREATE TABLE dashboards (",
        "    id INTEGER PRIMARY KEY,",
        "    name TEXT NOT NULL,",
        "    description TEXT,",
        "    pilotage_url TEXT,",
        "    collection_id INTEGER",
        ");",
        "",
        "CREATE TABLE dashboard_cards (",
        "    dashboard_id INTEGER,",
        "    card_id INTEGER,",
        "    position INTEGER,",
        "    tab_name TEXT",
        ");",
        "```",
        "",
        "## Topics",
        "",
        "| Topic | Count | Description |",
        "|-------|-------|-------------|",
    ]

    for topic in TOPICS:
        count = topics_summary.get(topic, 0)
        if count > 0:
            lines.append(f"| {topic} | {count} | {TOPICS[topic]} |")

    # Add dashboards summary
    dashboards_summary = db.dashboards_summary()
    lines.extend([
        "",
        "## Dashboards",
        "",
        "| Dashboard ID | Cards |",
        "|--------------|-------|",
    ])

    for dash_id, count in list(dashboards_summary.items())[:15]:
        lines.append(f"| {dash_id} | {count} |")

    lines.extend([
        "",
        "## Querying the Database",
        "",
        "```python",
        "from skills.metabase_query.scripts.cards_db import load_cards_db",
        "",
        "db = load_cards_db()",
        'cards = db.search("file active")  # Full-text search',
        'cards = db.by_topic("candidatures")  # Filter by topic',
        'cards = db.by_dashboard(408)  # Cards in a dashboard',
        'cards = db.by_table("candidats")  # Cards using a table',
        "card = db.get(7004)  # Get by ID",
        "```",
        "",
        "## Key Tables Referenced",
        "",
        "| Table | Cards Using It |",
        "|-------|----------------|",
    ])

    for table, count in list(tables_summary.items())[:15]:
        lines.append(f"| `{table}` | {count} |")

    lines.append("")

    with open(readme_path, "w") as f:
        f.write("\n".join(lines))

    return readme_path


def generate_markdown(db: CardsDB, output_dir: Path, last_sync: str):
    """Generate Markdown files for git tracking."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Clear existing markdown files
    for f in output_dir.glob("*.md"):
        f.unlink()

    all_cards = db.all()
    topics_summary = db.topics_summary()
    dashboards_summary = db.dashboards_summary()
    tables_summary = db.tables_summary()

    # --- Generate index.md ---
    index_lines = [
        "# Inventaire Metabase",
        "",
        f"*Dernière synchronisation : {last_sync}*",
        f"*Total : {len(all_cards)} cartes*",
        "",
        "## Table des matières",
        "",
        "### Par thème",
        "",
    ]

    for topic, count in sorted(topics_summary.items(), key=lambda x: -x[1]):
        if count > 0:
            desc = TOPICS.get(topic, "")
            index_lines.append(f"- [{topic}](topic-{topic}.md) ({count}) — {desc}")

    index_lines.extend([
        "",
        "### Par dashboard",
        "",
    ])

    for dash_id, count in list(dashboards_summary.items())[:20]:
        dash = db.get_dashboard(dash_id)
        dash_name = dash.name if dash else f"Dashboard {dash_id}"
        index_lines.append(f"- [{dash_name}](dashboard-{dash_id}.md) ({count} cartes)")

    # Best of: most referenced tables
    index_lines.extend([
        "",
        "## Best of — Tables les plus utilisées",
        "",
        "| Table | Cartes |",
        "|-------|--------|",
    ])

    for table, count in list(tables_summary.items())[:15]:
        index_lines.append(f"| `{table}` | {count} |")

    # Best of: cards with longest SQL (complex queries)
    cards_by_sql_len = sorted(
        [c for c in all_cards if c.sql_query],
        key=lambda c: len(c.sql_query or ""),
        reverse=True
    )[:10]

    index_lines.extend([
        "",
        "## Best of — Requêtes les plus complexes",
        "",
    ])

    for card in cards_by_sql_len:
        sql_len = len(card.sql_query or "")
        index_lines.append(f"- **{card.name}** (ID: {card.id}, {sql_len} chars)")

    with open(output_dir / "_index.md", "w") as f:
        f.write("\n".join(index_lines))

    # --- Generate topic files ---
    for topic in topics_summary:
        cards = db.by_topic(topic)
        if not cards:
            continue

        lines = [
            f"# Thème : {topic}",
            "",
            f"*{TOPICS.get(topic, '')}*",
            "",
            f"**{len(cards)} cartes**",
            "",
        ]

        for card in cards:
            lines.extend([
                f"## {card.name}",
                "",
                f"- **ID:** {card.id}",
            ])
            if card.description:
                lines.append(f"- **Description:** {card.description}")
            if card.dashboard_id:
                lines.append(f"- **Dashboard:** {card.dashboard_id}")
            if card.tables_referenced:
                lines.append(f"- **Tables:** {', '.join(card.tables_referenced)}")

            if card.sql_query:
                # Truncate very long SQL for readability
                sql = card.sql_query
                if len(sql) > 2000:
                    sql = sql[:2000] + "\n-- ... (truncated)"
                lines.extend([
                    "",
                    "```sql",
                    sql,
                    "```",
                ])

            lines.append("")

        with open(output_dir / f"topic-{topic}.md", "w") as f:
            f.write("\n".join(lines))

    # --- Generate dashboard files ---
    for dash_id in dashboards_summary:
        cards = db.by_dashboard(dash_id)
        if not cards:
            continue

        dash = db.get_dashboard(dash_id)
        dash_name = dash.name if dash else f"Dashboard {dash_id}"
        dash_desc = dash.description if dash else None

        lines = [
            f"# Dashboard : {dash_name}",
            "",
        ]

        if dash_desc:
            lines.extend([dash_desc, ""])

        if dash and dash.pilotage_url:
            lines.extend([f"**URL:** {dash.pilotage_url}", ""])

        lines.extend([f"**{len(cards)} cartes**", ""])

        for card in cards:
            lines.extend([
                f"## {card.name}",
                "",
                f"- **ID:** {card.id}",
                f"- **Thème:** {card.topic or 'autre'}",
            ])
            if card.description:
                lines.append(f"- **Description:** {card.description}")
            if card.tables_referenced:
                lines.append(f"- **Tables:** {', '.join(card.tables_referenced)}")

            if card.sql_query:
                sql = card.sql_query
                if len(sql) > 2000:
                    sql = sql[:2000] + "\n-- ... (truncated)"
                lines.extend([
                    "",
                    "```sql",
                    sql,
                    "```",
                ])

            lines.append("")

        with open(output_dir / f"dashboard-{dash_id}.md", "w") as f:
            f.write("\n".join(lines))

    return output_dir


def main():
    parser = argparse.ArgumentParser(description="Sync Metabase cards to SQLite")
    parser.add_argument("--skip-categorize", action="store_true", help="Skip AI categorization")
    parser.add_argument("--collections", type=int, nargs="+", default=DEFAULT_COLLECTIONS, help="Collection IDs to sync")
    parser.add_argument("--clear", action="store_true", help="Clear database before sync")
    parser.add_argument("--markdown", action="store_true", help="Generate Markdown files for git tracking")
    parser.add_argument("--markdown-only", action="store_true", help="Only regenerate Markdown from existing DB")
    args = parser.parse_args()

    # Handle --markdown-only mode
    if args.markdown_only:
        print("📄 Regenerating Markdown from existing database...")
        db = CardsDB()
        last_sync = datetime.now().strftime("%Y-%m-%d %H:%M")
        markdown_dir = DB_PATH.parent / "markdown"
        generate_markdown(db, markdown_dir, last_sync)
        md_files = list(markdown_dir.glob("*.md"))
        print(f"✅ {len(md_files)} files written to {markdown_dir}")
        db.close()
        return

    print("=" * 70)
    print("🚀 Metabase Cards Sync")
    print("=" * 70)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Collections: {args.collections}")
    print()

    # Initialize API and DB
    try:
        api = MetabaseAPI()
        print("✅ Metabase API connected")
    except Exception as e:
        print(f"❌ Failed to connect to Metabase: {e}")
        sys.exit(1)

    db = CardsDB()
    db.init_schema()
    if args.clear:
        db.clear()
        print("🗑️  Database cleared")

    # Step 1: Fetch cards metadata
    print()
    print("📋 STEP 1: Fetching cards metadata...")
    print("-" * 70)

    all_cards = []
    for coll_id in args.collections:
        print(f"   Collection {coll_id}...", end=" ")
        try:
            cards = api.list_cards(coll_id)
            for card in cards:
                all_cards.append({
                    "id": card["id"],
                    "name": card["name"],
                    "description": card.get("description"),
                    "collection_id": coll_id,
                })
            print(f"{len(cards)} cards")
        except MetabaseError as e:
            print(f"Error: {e}")

    print(f"   Total: {len(all_cards)} cards")

    # Step 2: Fetch SQL queries
    print()
    print("🔍 STEP 2: Fetching SQL queries...")
    print("-" * 70)

    start = time.time()
    for i, card in enumerate(all_cards):
        progress_bar(i, len(all_cards), prefix="   Progress", suffix=f"{i}/{len(all_cards)}")

        try:
            sql = api.get_card_sql(card["id"])
            card["sql_query"] = sql
            card["tables_referenced"] = extract_table_references(sql)
        except MetabaseError:
            card["sql_query"] = ""
            card["tables_referenced"] = []

        # Rate limiting
        if (i + 1) % 20 == 0:
            time.sleep(0.3)

    progress_bar(len(all_cards), len(all_cards), prefix="   Progress", suffix=f"{len(all_cards)}/{len(all_cards)}")

    has_sql = sum(1 for c in all_cards if c.get("sql_query"))
    print(f"   Cards with SQL: {has_sql}/{len(all_cards)} ({100*has_sql/len(all_cards):.1f}%)")
    print(f"   Time: {time.time() - start:.1f}s")

    # Step 3: Categorize with AI (optional)
    if not args.skip_categorize:
        anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        if anthropic_key:
            print()
            print("🤖 STEP 3: AI categorization...")
            print("-" * 70)

            start = time.time()
            categorizations = categorize_cards_with_claude(all_cards, anthropic_key)

            for card in all_cards:
                topic, reason = categorizations.get(card["id"], ("autre", "not categorized"))
                card["topic"] = topic

            print(f"   Time: {time.time() - start:.1f}s")
        else:
            print()
            print("⏭️  STEP 3: Skipping AI categorization (no ANTHROPIC_API_KEY)")
            for card in all_cards:
                card["topic"] = "autre"
    else:
        print()
        print("⏭️  STEP 3: Skipping AI categorization (--skip-categorize)")
        for card in all_cards:
            card["topic"] = "autre"

    # Step 4: Write to database
    print()
    print("💾 STEP 4: Writing to database...")
    print("-" * 70)

    for card in all_cards:
        db.upsert_card(
            card_id=card["id"],
            name=card["name"],
            description=card.get("description"),
            collection_id=card.get("collection_id"),
            topic=card.get("topic", "autre"),
            sql_query=card.get("sql_query", ""),
            tables_referenced=card.get("tables_referenced", []),
        )

    db.commit()
    db.rebuild_fts()
    print(f"   ✅ {len(all_cards)} cards written to {DB_PATH}")

    # Step 5: Generate README
    print()
    print("📝 STEP 5: Generating README...")
    print("-" * 70)

    last_sync = datetime.now().strftime("%Y-%m-%d %H:%M")
    readme_path = generate_readme(db, last_sync)
    print(f"   ✅ {readme_path}")

    # Step 6: Generate Markdown (optional)
    if args.markdown:
        print()
        print("📄 STEP 6: Generating Markdown files...")
        print("-" * 70)

        markdown_dir = DB_PATH.parent / "markdown"
        generate_markdown(db, markdown_dir, last_sync)

        # Count generated files
        md_files = list(markdown_dir.glob("*.md"))
        print(f"   ✅ {len(md_files)} files written to {markdown_dir}")

    db.close()

    print()
    print("=" * 70)
    print("✅ COMPLETE!")
    print("=" * 70)
    print(f"Database: {DB_PATH}")
    print(f"Cards: {len(all_cards)}")
    if args.markdown:
        print(f"Markdown: {DB_PATH.parent / 'markdown'}")


if __name__ == "__main__":
    main()
