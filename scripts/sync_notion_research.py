#!/usr/bin/env python3
"""Index Notion 'Connaissance du terrain' databases into SQLite for full-text search.

Databases indexed:
- Entretiens et actions de recherche
- Thématiques de recherche
- Segments
- Profils (Cibles précises)
- Hypothèses et questions qu'on se pose
- Conclusions

Usage:
    python scripts/sync_notion_research.py
    python scripts/sync_notion_research.py --db /path/to/output.db
"""

import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "notion_research.db"

DATABASES = {
    "entretiens": {
        "id": "28d5f321-b604-8101-a7e9-f2f705cbb2c3",
        "name": "Entretiens et actions de recherche",
    },
    "thematiques": {
        "id": "28d5f321-b604-80dc-923a-dfad38e4592c",
        "name": "Thématiques de recherche",
    },
    "segments": {
        "id": "28d5f321-b604-8094-8a13-cbe09f2810bf",
        "name": "Segments",
    },
    "profils": {
        "id": "1885f321-b604-817a-ad43-d8ea18689279",
        "name": "Profils (Cibles précises)",
    },
    "hypotheses": {
        "id": "28d5f321-b604-81de-86db-eaf2ee71e29d",
        "name": "Hypothèses et questions qu'on se pose",
    },
    "conclusions": {
        "id": "28d5f321-b604-80fb-aa4b-f92b13dd0993",
        "name": "Conclusions",
    },
}

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

# Rate limiting
REQUEST_INTERVAL = 0.34  # ~3 req/s
_last_request_time = 0.0
_request_count = 0


def _rate_limited_request(url, data=None, method="GET", max_retries=5):
    """Make a rate-limited request to Notion API with retry on 429."""
    global _last_request_time, _request_count

    for attempt in range(max_retries):
        # Throttle
        elapsed = time.time() - _last_request_time
        if elapsed < REQUEST_INTERVAL:
            time.sleep(REQUEST_INTERVAL - elapsed)

        req = urllib.request.Request(url, headers=HEADERS, method=method)
        if data:
            req.data = json.dumps(data).encode("utf-8")

        _last_request_time = time.time()
        _request_count += 1

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                retry_after = int(e.headers.get("Retry-After", 1))
                print(f"  Rate limited, waiting {retry_after}s...")
                time.sleep(retry_after)
                continue
            body = e.read().decode("utf-8")[:200]
            print(f"  HTTP {e.code}: {body}")
            raise
    raise RuntimeError(f"Max retries exceeded for {url}")


def query_database(db_id):
    """Fetch all pages from a Notion database."""
    pages = []
    cursor = None
    while True:
        payload = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        data = _rate_limited_request(
            f"https://api.notion.com/v1/databases/{db_id}/query",
            data=payload,
            method="POST",
        )
        pages.extend(data["results"])
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return pages


def get_block_children(block_id):
    """Recursively fetch all block children of a page/block."""
    blocks = []
    cursor = None
    while True:
        url = f"https://api.notion.com/v1/blocks/{block_id}/children?page_size=100"
        if cursor:
            url += f"&start_cursor={cursor}"
        data = _rate_limited_request(url)
        for block in data["results"]:
            blocks.append(block)
            if block.get("has_children"):
                blocks.extend(get_block_children(block["id"]))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return blocks


def extract_text_from_rich_text(rich_text_list):
    """Extract plain text from Notion rich_text array."""
    return "".join(t.get("plain_text", "") for t in rich_text_list)


def extract_block_text(block):
    """Extract text content from a single block."""
    btype = block["type"]
    bdata = block.get(btype, {})
    if "rich_text" in bdata:
        return extract_text_from_rich_text(bdata["rich_text"])
    if "text" in bdata:
        return extract_text_from_rich_text(bdata["text"])
    if btype == "child_page":
        return bdata.get("title", "")
    if btype == "child_database":
        return bdata.get("title", "")
    return ""


def extract_page_title(page):
    """Extract title from page properties."""
    for _name, val in page["properties"].items():
        if val["type"] == "title":
            return extract_text_from_rich_text(val.get("title", []))
    return ""


def extract_page_properties(page):
    """Extract all properties as a flat dict of {name: text_value}."""
    props = {}
    for name, val in page["properties"].items():
        ptype = val["type"]
        if ptype == "title":
            props[name] = extract_text_from_rich_text(val.get("title", []))
        elif ptype == "rich_text":
            props[name] = extract_text_from_rich_text(val.get("rich_text", []))
        elif ptype == "select":
            sel = val.get("select")
            props[name] = sel["name"] if sel else None
        elif ptype == "multi_select":
            props[name] = [o["name"] for o in val.get("multi_select", [])]
        elif ptype == "date":
            d = val.get("date")
            props[name] = d["start"] if d else None
        elif ptype == "relation":
            props[name] = [r["id"] for r in val.get("relation", [])]
        elif ptype == "people":
            props[name] = [
                p.get("name", p.get("id", "")) for p in val.get("people", [])
            ]
        elif ptype == "formula":
            f = val.get("formula", {})
            ftype = f.get("type")
            props[name] = f.get(ftype) if ftype else None
        elif ptype == "rollup":
            props[name] = None  # Skip rollups
        else:
            props[name] = None
    return props


def init_db(db_path):
    """Create SQLite schema."""
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        DROP TABLE IF EXISTS pages;
        DROP TABLE IF EXISTS blocks;
        DROP TABLE IF EXISTS relations;
        DROP TABLE IF EXISTS sync_meta;

        CREATE TABLE pages (
            id TEXT PRIMARY KEY,
            database_key TEXT NOT NULL,
            database_name TEXT NOT NULL,
            title TEXT,
            properties_json TEXT,
            url TEXT,
            created_time TEXT,
            last_edited_time TEXT
        );

        CREATE TABLE blocks (
            id TEXT PRIMARY KEY,
            page_id TEXT NOT NULL REFERENCES pages(id),
            type TEXT NOT NULL,
            text_content TEXT,
            position INTEGER,
            parent_block_id TEXT,
            FOREIGN KEY (page_id) REFERENCES pages(id)
        );

        CREATE TABLE relations (
            source_page_id TEXT NOT NULL,
            property_name TEXT NOT NULL,
            target_page_id TEXT NOT NULL,
            FOREIGN KEY (source_page_id) REFERENCES pages(id)
        );

        CREATE TABLE sync_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
            title, properties_text, content='pages', content_rowid='rowid'
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS blocks_fts USING fts5(
            text_content, content='blocks', content_rowid='rowid'
        );
    """)
    conn.commit()
    return conn


def index_database(conn, db_key, db_info, fetch_blocks=True):
    """Index all pages (and optionally blocks) from one Notion database."""
    db_id = db_info["id"]
    db_name = db_info["name"]
    print(f"\n--- {db_name} ---")

    pages = query_database(db_id)
    print(f"  {len(pages)} pages fetched")

    block_count = 0
    for i, page in enumerate(pages):
        page_id = page["id"]
        title = extract_page_title(page)
        props = extract_page_properties(page)

        # Store relations separately
        for prop_name, prop_val in props.items():
            if isinstance(prop_val, list) and prop_val and all(
                isinstance(v, str) and len(v) == 36 for v in prop_val
            ):
                for target_id in prop_val:
                    conn.execute(
                        "INSERT INTO relations (source_page_id, property_name, target_page_id) VALUES (?, ?, ?)",
                        (page_id, prop_name, target_id),
                    )

        # Properties as searchable text (exclude relation IDs)
        props_text_parts = []
        for k, v in props.items():
            if v is None:
                continue
            if isinstance(v, list):
                # Skip lists of UUIDs (relations)
                if v and all(isinstance(x, str) and len(x) == 36 for x in v):
                    continue
                props_text_parts.append(f"{k}: {', '.join(str(x) for x in v)}")
            else:
                props_text_parts.append(f"{k}: {v}")
        properties_text = "\n".join(props_text_parts)

        conn.execute(
            "INSERT OR REPLACE INTO pages (id, database_key, database_name, title, properties_json, url, created_time, last_edited_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                page_id,
                db_key,
                db_name,
                title,
                json.dumps(props, ensure_ascii=False),
                page.get("url"),
                page.get("created_time"),
                page.get("last_edited_time"),
            ),
        )

        # FTS for pages
        rowid = conn.execute(
            "SELECT rowid FROM pages WHERE id = ?", (page_id,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO pages_fts (rowid, title, properties_text) VALUES (?, ?, ?)",
            (rowid, title, properties_text),
        )

        # Fetch blocks
        if fetch_blocks:
            try:
                blocks = get_block_children(page_id)
            except Exception as e:
                print(f"  Warning: failed to fetch blocks for '{title[:50]}': {e}")
                blocks = []

            for pos, block in enumerate(blocks):
                text = extract_block_text(block)
                conn.execute(
                    "INSERT OR REPLACE INTO blocks (id, page_id, type, text_content, position, parent_block_id) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        block["id"],
                        page_id,
                        block["type"],
                        text,
                        pos,
                        block.get("parent", {}).get("block_id"),
                    ),
                )
                if text.strip():
                    rowid = conn.execute(
                        "SELECT rowid FROM blocks WHERE id = ?", (block["id"],)
                    ).fetchone()[0]
                    conn.execute(
                        "INSERT INTO blocks_fts (rowid, text_content) VALUES (?, ?)",
                        (rowid, text),
                    )
                block_count += 1

        if (i + 1) % 50 == 0:
            conn.commit()
            print(f"  {i + 1}/{len(pages)} pages processed...")

    conn.commit()
    print(f"  Done: {len(pages)} pages, {block_count} blocks")
    return len(pages), block_count


def main():
    parser = argparse.ArgumentParser(description="Sync Notion research databases to SQLite")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="SQLite output path")
    parser.add_argument("--no-blocks", action="store_true", help="Skip fetching block content (faster)")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        print("Error: NOTION_TOKEN not set in .env")
        sys.exit(1)

    args.db.parent.mkdir(parents=True, exist_ok=True)

    print(f"Syncing Notion 'Connaissance du terrain' → {args.db}")
    print(f"Databases: {len(DATABASES)}")
    print(f"Fetch blocks: {not args.no_blocks}")
    print()

    global _request_count
    _request_count = 0
    t0 = time.time()

    conn = init_db(args.db)

    total_pages = 0
    total_blocks = 0
    timings = {}

    for db_key, db_info in DATABASES.items():
        db_t0 = time.time()
        pages, blocks = index_database(conn, db_key, db_info, fetch_blocks=not args.no_blocks)
        db_elapsed = time.time() - db_t0
        total_pages += pages
        total_blocks += blocks
        timings[db_info["name"]] = {
            "pages": pages,
            "blocks": blocks,
            "seconds": round(db_elapsed, 1),
        }

    elapsed = time.time() - t0

    # Store sync metadata
    conn.execute(
        "INSERT OR REPLACE INTO sync_meta (key, value) VALUES (?, ?)",
        ("last_sync", datetime.now().isoformat()),
    )
    conn.execute(
        "INSERT OR REPLACE INTO sync_meta (key, value) VALUES (?, ?)",
        ("sync_duration_seconds", str(round(elapsed, 1))),
    )
    conn.execute(
        "INSERT OR REPLACE INTO sync_meta (key, value) VALUES (?, ?)",
        ("total_pages", str(total_pages)),
    )
    conn.execute(
        "INSERT OR REPLACE INTO sync_meta (key, value) VALUES (?, ?)",
        ("total_blocks", str(total_blocks)),
    )
    conn.execute(
        "INSERT OR REPLACE INTO sync_meta (key, value) VALUES (?, ?)",
        ("total_api_requests", str(_request_count)),
    )
    conn.execute(
        "INSERT OR REPLACE INTO sync_meta (key, value) VALUES (?, ?)",
        ("timings", json.dumps(timings, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()

    # Summary
    print("\n" + "=" * 60)
    print("SYNC COMPLETE")
    print("=" * 60)
    print(f"Total time:     {elapsed:.1f}s ({elapsed/60:.1f} min)")
    print(f"API requests:   {_request_count}")
    print(f"Avg rate:       {_request_count/elapsed:.1f} req/s")
    print(f"Pages indexed:  {total_pages}")
    print(f"Blocks indexed: {total_blocks}")
    print(f"Database:       {args.db} ({args.db.stat().st_size / 1024:.0f} KB)")
    print()
    print("Per database:")
    for name, t in timings.items():
        print(f"  {name}: {t['pages']} pages, {t['blocks']} blocks in {t['seconds']}s")


if __name__ == "__main__":
    main()
