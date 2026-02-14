#!/usr/bin/env python3
"""Search the Notion research corpus and output citation blocks.

Finds the most relevant quotes, observations, and interview excerpts
for a given topic. Output is formatted as markdown citation blocks
ready to embed in agent responses.

Usage:
    python scripts/search_research.py "accompagnement des prescripteurs"
    python scripts/search_research.py "mobilité zones rurales" --limit 3
    python scripts/search_research.py "freins numériques" --db entretiens
    python scripts/search_research.py "orientation RSA" --type "❝ Verbatim"
"""

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

import numpy as np
import requests
from dotenv import load_dotenv

load_dotenv()

DEFAULT_DB_PATH = Path(os.getenv("DATA_DIR", Path(__file__).parent.parent / "data")) / "notion_research.db"
DEEPINFRA_URL = "https://api.deepinfra.com/v1/openai/embeddings"
EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-0.6B"

# Icons for terminal output (maps to what the web UI shows)
TYPE_PREFIXES = {
    "❝ Verbatim": "❝",
    "👀 Observation": "👀",
    "🗣 Entretien": "🗣",
    "📂 Terrain": "📂",
    "🤼 Open Lab": "🤼",
    "🧮 Questionnaire / quanti": "🧮",
    "📂 Événement": "📅",
    "🗒️ Note": "🗒️",
    "🎤  Retex": "🎤",
    "📖 Lecture": "📖",
}

DB_PREFIXES = {
    "entretiens": "🗣",
    "thematiques": "🔖",
    "segments": "👥",
    "profils": "👤",
    "hypotheses": "❓",
    "conclusions": "✅",
}


def get_type_label(type_str):
    """Strip emoji prefix from type name."""
    if not type_str:
        return None
    # Remove leading emojis/symbols/whitespace
    import re
    return re.sub(r'^[\U0001F000-\U0001FFFF\u2000-\u2BFF\uFE00-\uFEFF❝❞\s]+', '', type_str).strip()


def embed_query(text, api_key):
    """Encode a query string using DeepInfra API."""
    resp = requests.post(
        DEEPINFRA_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": EMBEDDING_MODEL,
            "input": [text],
            "encoding_format": "float",
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    vec = np.array(data["data"][0]["embedding"], dtype=np.float32)
    return vec / np.linalg.norm(vec)


def extract_body(text):
    """Extract body text, stripping metadata header."""
    if "\n---\n" in text:
        return text.split("\n---\n", 1)[1].strip()

    lines = text.split("\n")
    body_start = 1  # skip title
    for i in range(1, len(lines)):
        stripped = lines[i].strip()
        if not stripped:
            body_start = i + 1
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            body_start = i + 1
            continue
        if ": " in stripped and len(stripped) < 200:
            body_start = i + 1
            continue
        break
    return "\n".join(lines[body_start:]).strip()


def search(query, db_path=None, limit=5, db_filter=None, type_filter=None):
    """Search the research corpus and return results."""
    db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
    if not db_path.exists():
        print(f"Error: database not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    api_key = os.getenv("DEEPINFRA_API_KEY")
    if not api_key:
        print("Error: DEEPINFRA_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    # Load chunks and embeddings
    rows = conn.execute(
        "SELECT id, page_id, chunk_index, text, database_key, embedding FROM chunks"
    ).fetchall()

    chunks = []
    vecs = []
    for row in rows:
        chunks.append({
            "id": row["id"],
            "page_id": row["page_id"],
            "chunk_index": row["chunk_index"],
            "text": row["text"],
            "database_key": row["database_key"],
        })
        vecs.append(np.frombuffer(row["embedding"], dtype=np.float32))

    embeddings = np.vstack(vecs)
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1
    embeddings = embeddings / norms

    # Load page metadata
    page_rows = conn.execute(
        "SELECT id, title, database_key, database_name, url, properties_json FROM pages"
    ).fetchall()

    pages = {}
    for row in page_rows:
        props = json.loads(row["properties_json"]) if row["properties_json"] else {}
        pages[row["id"]] = {
            "title": row["title"],
            "database_key": row["database_key"],
            "database_name": row["database_name"],
            "url": row["url"],
            "type": props.get("Type"),
            "date": props.get("Date"),
        }

    conn.close()

    # Embed query and compute scores
    query_vec = embed_query(query, api_key)
    scores = embeddings @ query_vec
    top_indices = np.argsort(scores)[::-1]

    # Collect results with filtering and dedup
    seen_pages = {}
    results = []
    for idx in top_indices:
        if len(results) >= limit * 3:
            break
        chunk = chunks[idx]

        if db_filter and chunk["database_key"] not in db_filter:
            continue

        page_info = pages.get(chunk["page_id"])
        if type_filter and (not page_info or page_info.get("type") not in type_filter):
            continue

        pid = chunk["page_id"]
        if pid in seen_pages:
            continue
        seen_pages[pid] = True

        body = extract_body(chunk["text"])
        results.append({
            "page_id": pid,
            "title": page_info["title"] if page_info else "Sans titre",
            "body": body,
            "database_key": chunk["database_key"],
            "database_name": page_info["database_name"] if page_info else None,
            "page_type": page_info["type"] if page_info else None,
            "page_date": page_info["date"] if page_info else None,
            "page_url": page_info["url"] if page_info else None,
            "score": float(scores[idx]),
        })

        if len(results) >= limit:
            break

    return results


def format_date(date_str):
    """Normalize date: strip ISO time portion, keep just YYYY-MM-DD."""
    if not date_str:
        return None
    return date_str[:10] if len(date_str) >= 10 else date_str


def format_citation(result):
    """Format a single result as a markdown citation block."""
    title = result["title"]
    body = result["body"]
    page_type = result["page_type"]
    date = format_date(result["page_date"])
    page_url = result["page_url"]
    page_id = result["page_id"]
    db_key = result["database_key"]

    type_label = get_type_label(page_type)
    prefix = TYPE_PREFIXES.get(page_type, DB_PREFIXES.get(db_key, "📄"))

    # Build the quote content
    # For verbatims and short items: the title IS the quote
    # For longer items: title + truncated body
    if body:
        text = body
        if len(text) > 300:
            cut = text[:300].rfind(". ")
            if cut > 150:
                text = text[:cut + 1]
            else:
                cut = text[:300].rfind("\n")
                if cut > 100:
                    text = text[:cut]
                else:
                    text = text[:300] + "…"
        lines = [f"{prefix} « {title} »", text]
    else:
        lines = [f"{prefix} « {title} »"]

    # Attribution line
    parts = []
    if type_label:
        parts.append(type_label)
    if date:
        parts.append(date)
    attribution = " · ".join(parts) if parts else result.get("database_name", "")

    # Links
    link_parts = [f"[Explorer](/recherche?page={page_id})"]
    if page_url:
        link_parts.append(f"[Notion]({page_url})")
    links_str = " · ".join(link_parts)

    lines.append(f"— *{attribution}* · {links_str}")

    # Prefix every line with > for blockquote
    return "\n".join(f"> {line}" for line in lines)


def main():
    parser = argparse.ArgumentParser(
        description="Search the Notion research corpus for relevant citations."
    )
    parser.add_argument("query", help="Search query (natural language)")
    parser.add_argument("--limit", type=int, default=5, help="Number of citations (default: 5)")
    parser.add_argument("--db", action="append", help="Filter by database key (repeatable)")
    parser.add_argument("--type", action="append", dest="types", help="Filter by type (repeatable)")
    parser.add_argument("--db-path", help="Path to notion_research.db")
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of citations")
    args = parser.parse_args()

    results = search(
        query=args.query,
        db_path=args.db_path,
        limit=args.limit,
        db_filter=set(args.db) if args.db else None,
        type_filter=set(args.types) if args.types else None,
    )

    if not results:
        print("Aucun résultat trouvé dans le corpus terrain.")
        return

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    for i, r in enumerate(results):
        if i > 0:
            print()
        print(format_citation(r))


if __name__ == "__main__":
    main()
