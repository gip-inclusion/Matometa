#!/usr/bin/env python3
"""Sync Metabase cards inventory to Markdown files (and optionally SQLite)."""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# Load .env file
from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from skills.metabase_query.scripts.metabase import MetabaseError
from skills.metabase_query.scripts.cards_db import CardsDB, TOPICS, TABLE_TO_TOPIC, DB_PATH
from lib._sources import load_config, get_source_config, get_metabase, list_instances

def infer_topic_from_tables(tables: list[str]) -> str | None:
    for table in tables:
        table_lower = table.lower()
        for pattern, topic in TABLE_TO_TOPIC.items():
            if pattern in table_lower:
                return topic
    return None

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

def categorize_cards_with_llm(cards: list[dict]) -> dict[int, tuple[str, str]]:
    """
    Categorize cards using the configured LLM backend.

    Returns dict of card_id -> (topic, reason)
    """
    from web.llm import generate_text, LLMError

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

IMPORTANT:
- Use ONLY the topic slugs listed above
- Look at SQL table names and fields to determine the topic
- Every card MUST get a topic - pick the closest match
- For ESAT questionnaire tables, use "esat"
- If unsure, look at what data the card is measuring
"""

        try:
            result_text = generate_text(prompt, max_tokens=4000, timeout=120)

            # Extract JSON array from response (may be wrapped in text or code blocks)
            json_match = re.search(r'\[[\s\S]*\]', result_text)
            if not json_match:
                raise ValueError("No JSON array found in response")

            categorizations = json.loads(json_match.group())
            for item in categorizations:
                topic = item["topic"]
                # Validate topic and fallback if invalid
                if topic not in TOPICS:
                    # Try table-based inference
                    card_data = next((c for c in batch if c["id"] == item["id"]), None)
                    if card_data:
                        inferred = infer_topic_from_tables(card_data.get("tables_referenced", []))
                        topic = inferred if inferred else "candidatures"
                    else:
                        topic = "candidatures"
                results[item["id"]] = (topic, item.get("reason", ""))

        except Exception as e:
            print(f"\n   ⚠️  Batch error: {e}")
            # Fallback: use table-based inference for each card
            for card in batch:
                inferred = infer_topic_from_tables(card.get("tables_referenced", []))
                results[card["id"]] = (inferred if inferred else "candidatures", "inferred from tables")

    progress_bar(total_batches, total_batches, prefix="   Categorizing", suffix=f"batch {total_batches}/{total_batches}")
    return results

def generate_readme(db: CardsDB, last_sync: str):
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

def format_sql_for_markdown(sql: str) -> str:
    if not sql:
        return ""

    # Add line breaks after major SQL keywords for readability
    keywords = ['SELECT', 'FROM', 'WHERE', 'AND', 'OR', 'GROUP BY', 'ORDER BY',
                'HAVING', 'JOIN', 'LEFT JOIN', 'RIGHT JOIN', 'INNER JOIN',
                'UNION', 'LIMIT', 'OFFSET']

    formatted = sql
    for kw in keywords:
        # Add newline before keyword (case insensitive)
        import re
        formatted = re.sub(rf'(\s)({kw}\s)', rf'\1\n{kw} ', formatted, flags=re.IGNORECASE)

    # Clean up multiple newlines
    formatted = re.sub(r'\n\s*\n', '\n', formatted)

    return formatted.strip()

def generate_markdown(db: CardsDB, cards_dir: Path, dashboards_dir: Path, last_sync: str):
    cards_dir.mkdir(parents=True, exist_ok=True)
    dashboards_dir.mkdir(parents=True, exist_ok=True)

    # Clear existing markdown files
    for f in cards_dir.glob("*.md"):
        f.unlink()
    for f in dashboards_dir.glob("*.md"):
        f.unlink()

    all_cards = db.all()
    topics_summary = db.topics_summary()
    dashboards_summary = db.dashboards_summary()
    tables_summary = db.tables_summary()

    # --- Generate unified index.md in stats dir ---
    index_lines = [
        "# Inventaire Metabase",
        "",
        f"*Dernière synchronisation : {last_sync}*",
        f"*{len(all_cards)} cartes · {len(dashboards_summary)} dashboards*",
        "",
        "## Cartes par thème",
        "",
    ]

    for topic, count in sorted(topics_summary.items(), key=lambda x: -x[1]):
        if count > 0:
            desc = TOPICS.get(topic, "")
            index_lines.append(f"- [{topic}](cards/topic-{topic}.md) ({count}) — {desc}")

    index_lines.extend([
        "",
        "## Dashboards",
        "",
    ])

    for dash_id, count in list(dashboards_summary.items())[:30]:
        dash = db.get_dashboard(dash_id)
        dash_name = dash.name if dash else f"Dashboard {dash_id}"
        index_lines.append(f"- [{dash_name}](dashboards/dashboard-{dash_id}.md) ({count} cartes)")

    # Best of: most referenced tables
    index_lines.extend([
        "",
        "## Tables les plus utilisées",
        "",
        "| Table | Cartes |",
        "|-------|--------|",
    ])

    for table, count in list(tables_summary.items())[:15]:
        index_lines.append(f"| `{table}` | {count} |")

    # Write to stats/_index.md (parent of cards and dashboards)
    stats_dir = cards_dir.parent
    with open(stats_dir / "_index.md", "w") as f:
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
                # Format SQL for readability, truncate if very long
                sql = format_sql_for_markdown(card.sql_query)
                if len(sql) > 3000:
                    sql = sql[:3000] + "\n-- ... (truncated)"
                lines.extend([
                    "",
                    "```sql",
                    sql,
                    "```",
                ])

            lines.append("")

        with open(cards_dir / f"topic-{topic}.md", "w") as f:
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
                f"- **Thème:** {card.topic or 'candidatures'}",
            ])
            if card.description:
                lines.append(f"- **Description:** {card.description}")
            if card.tables_referenced:
                lines.append(f"- **Tables:** {', '.join(card.tables_referenced)}")

            if card.sql_query:
                # Format SQL for readability, truncate if very long
                sql = format_sql_for_markdown(card.sql_query)
                if len(sql) > 3000:
                    sql = sql[:3000] + "\n-- ... (truncated)"
                lines.extend([
                    "",
                    "```sql",
                    sql,
                    "```",
                ])

            lines.append("")

        with open(dashboards_dir / f"dashboard-{dash_id}.md", "w") as f:
            f.write("\n".join(lines))

    return cards_dir, dashboards_dir

def sync_instance(instance_name: str, args):
    """Sync a single Metabase instance."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # Load instance config
    instance_config = get_source_config("metabase", instance_name)
    public_dashboards = instance_config.get("dashboards", {})
    dashboard_ids = list(public_dashboards.keys())
    knowledge_path = instance_config.get("knowledge_path", f"knowledge/{instance_name}/")

    if not dashboard_ids:
        print(f"⚠️  No dashboards configured for instance '{instance_name}'")
        return

    # Output directories
    stats_dir = project_root / knowledge_path
    cards_dir = stats_dir / "cards"
    dashboards_dir = stats_dir / "dashboards"

    # Determine output modes
    generate_markdown_files = not args.sqlite_only
    generate_sqlite = args.sqlite or args.sqlite_only

    print("=" * 70)
    print(f"🚀 Metabase Cards Sync: {instance_name}")
    print("=" * 70)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Instance: {instance_name} ({instance_config['url']})")
    print(f"Dashboards: {len(dashboard_ids)}")
    print(f"Output: {knowledge_path}")
    print()

    # Initialize API and DB
    try:
        api = get_metabase(instance_name)
        print("✅ Metabase API connected")
    except Exception as e:
        print(f"❌ Failed to connect to Metabase: {e}")
        return

    # Always use in-memory db during sync, save to file at the end if needed
    db = CardsDB(in_memory=True)
    db.init_schema()

    # Step 1: Fetch dashboard metadata and cards
    print()
    print("📋 STEP 1: Fetching dashboards and cards...")
    print("-" * 70)

    all_cards = []
    seen_card_ids = set()
    dashboard_metadata = {}

    for dash_id in dashboard_ids:
        print(f"   Dashboard {dash_id}...", end=" ", flush=True)
        try:
            dashboard = api.get_dashboard(dash_id)
            dashboard_metadata[dash_id] = {
                "name": dashboard.get("name", f"Dashboard {dash_id}"),
                "description": dashboard.get("description"),
                "collection_id": dashboard.get("collection_id"),
                "pilotage_url": public_dashboards.get(dash_id),
            }

            # Extract cards from dashboard (skip unnamed/empty cards)
            dashcards = dashboard.get("dashcards", [])
            card_count = 0
            for dc in dashcards:
                card = dc.get("card")
                if not card or not card.get("id"):
                    continue
                if card["id"] in seen_card_ids:
                    continue
                # Skip unnamed cards (name is None, empty, or just "Card {id}")
                name = card.get("name", "").strip()
                if not name or name == f"Card {card['id']}" or re.match(r"^Card \d+$", name):
                    continue
                seen_card_ids.add(card["id"])
                all_cards.append({
                    "id": card["id"],
                    "name": name,
                    "description": card.get("description"),
                    "collection_id": card.get("collection_id"),
                    "dashboard_id": dash_id,
                })
                card_count += 1

            print(f"{card_count} cards")
        except MetabaseError as e:
            print(f"Error: {e}")

    print(f"   Total: {len(all_cards)} unique cards from {len(dashboard_ids)} dashboards")

    if not all_cards:
        print("⚠️  No cards found, skipping remaining steps")
        db.close()
        return

    # Store dashboard metadata in DB
    for dash_id, meta in dashboard_metadata.items():
        db.upsert_dashboard(
            dashboard_id=dash_id,
            name=meta["name"],
            description=meta["description"],
            topic=None,  # Will be inferred from cards
            pilotage_url=meta["pilotage_url"],
            collection_id=meta["collection_id"],
        )
    db.commit()

    # Step 2: Fetch SQL queries (parallel)
    print()
    print("🔍 STEP 2: Fetching SQL queries (parallel)...")
    print("-" * 70)

    def fetch_card_sql(card: dict) -> tuple[int, str, list[str]]:
        try:
            sql = api.get_card_sql(card["id"])
            tables = extract_table_references(sql)
            return (card["id"], sql, tables)
        except (MetabaseError, TimeoutError, OSError):
            return (card["id"], "", [])

    start = time.time()
    completed = 0

    # Use 10 parallel workers (balance between speed and not hammering the API)
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_card_sql, card): card for card in all_cards}

        for future in as_completed(futures):
            card_id, sql, tables = future.result()
            # Find and update the card
            for card in all_cards:
                if card["id"] == card_id:
                    card["sql_query"] = sql
                    card["tables_referenced"] = tables
                    break
            completed += 1
            progress_bar(completed, len(all_cards), prefix="   Progress", suffix=f"{completed}/{len(all_cards)}")

    progress_bar(len(all_cards), len(all_cards), prefix="   Progress", suffix=f"{len(all_cards)}/{len(all_cards)}")

    has_sql = sum(1 for c in all_cards if c.get("sql_query"))
    print(f"   Cards with SQL: {has_sql}/{len(all_cards)} ({100*has_sql/len(all_cards):.1f}%)")
    print(f"   Time: {time.time() - start:.1f}s")

    # Step 3: Categorize with AI (optional)
    if not args.skip_categorize:
        print()
        print("🤖 STEP 3: AI categorization...")
        print("-" * 70)

        start = time.time()
        categorizations = categorize_cards_with_llm(all_cards)

        for card in all_cards:
            topic, reason = categorizations.get(card["id"], (None, "not categorized"))
            if not topic or topic not in TOPICS:
                # Fallback to table-based inference
                topic = infer_topic_from_tables(card.get("tables_referenced", []))
                if not topic:
                    topic = "candidatures"  # Ultimate fallback
            card["topic"] = topic

        print(f"   Time: {time.time() - start:.1f}s")
    else:
        print()
        print("⏭️  STEP 3: Skipping AI categorization (--skip-categorize)")
        for card in all_cards:
            # Use table-based inference when skipping AI
            topic = infer_topic_from_tables(card.get("tables_referenced", []))
            card["topic"] = topic if topic else "candidatures"

    last_sync = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Step 4: Populate database (single pass)
    print()
    print("💾 STEP 4: Populating database...")
    print("-" * 70)

    for card in all_cards:
        db.upsert_card(
            card_id=card["id"],
            name=card["name"],
            description=card.get("description"),
            collection_id=card.get("collection_id"),
            dashboard_id=card.get("dashboard_id"),
            topic=card.get("topic", "candidatures"),
            sql_query=card.get("sql_query", ""),
            tables_referenced=card.get("tables_referenced", []),
        )

    db.commit()
    db.rebuild_fts()
    print(f"   ✅ {len(all_cards)} cards loaded")

    # Step 5: Generate outputs
    if generate_markdown_files:
        print()
        print("📄 STEP 5: Generating Markdown files...")
        print("-" * 70)

        generate_markdown(db, cards_dir, dashboards_dir, last_sync)

        cards_files = list(cards_dir.glob("*.md"))
        dash_files = list(dashboards_dir.glob("*.md"))
        print(f"   ✅ {len(cards_files)} card files written to {cards_dir}")
        print(f"   ✅ {len(dash_files)} dashboard files written to {dashboards_dir}")

    if generate_sqlite:
        print()
        print("💾 STEP 6: Saving SQLite database...")
        print("-" * 70)
        # Save to instance-specific path
        sqlite_path = stats_dir / "cards.db"
        db.save_to_file(sqlite_path)
        print(f"   ✅ Database saved to {sqlite_path}")

        # Generate SQLite README in the instance knowledge dir
        readme_path = stats_dir / "README.md"
        # Use generate_readme but with correct path
        # For now, skip the README generation for non-default instances

    db.close()

    print()
    print("=" * 70)
    print("✅ COMPLETE!")
    print("=" * 70)
    print(f"Instance: {instance_name}")
    print(f"Cards: {len(all_cards)}")
    if generate_markdown_files:
        print(f"Markdown: {cards_dir}")
        print(f"Dashboards: {dashboards_dir}")
    print()

def main():
    parser = argparse.ArgumentParser(description="Sync Metabase cards to markdown/SQLite")
    parser.add_argument("--instance", type=str, help="Metabase instance to sync (e.g., stats, datalake)")
    parser.add_argument("--all", action="store_true", help="Sync all configured instances")
    parser.add_argument("--skip-categorize", action="store_true", help="Skip AI categorization")
    parser.add_argument("--sqlite", action="store_true", help="Also generate SQLite database")
    parser.add_argument("--sqlite-only", action="store_true", help="Only generate SQLite, skip markdown")
    args = parser.parse_args()

    # Require explicit instance selection
    if not args.instance and not args.all:
        available = list_instances("metabase")
        print("Error: Please specify --instance <name> or --all")
        print(f"Available instances: {', '.join(available)}")
        sys.exit(1)

    # Determine which instances to sync
    if args.all:
        instances = list_instances("metabase")
    else:
        instances = [args.instance]

    for instance_name in instances:
        sync_instance(instance_name, args)

if __name__ == "__main__":
    main()
