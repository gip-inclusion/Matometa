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
import sys

import numpy as np
import psycopg2
import requests
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
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

    return re.sub(r"^[\U0001F000-\U0001FFFF\u2000-\u2BFF\uFE00-\uFEFF❝❞\s]+", "", type_str).strip()


def embed_query(text, api_key):
    """Encode a query string using DeepInfra API, return pgvector string."""
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
    vec = vec / np.linalg.norm(vec)
    return "[" + ",".join(str(float(x)) for x in vec) + "]"


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


def search(query, limit=5, db_filter=None, type_filter=None):
    """Search the research corpus via pgvector and return results."""
    if not DATABASE_URL:
        print("Error: DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)

    api_key = os.getenv("DEEPINFRA_API_KEY")
    if not api_key:
        print("Error: DEEPINFRA_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Embed query and search with pgvector
    query_vec = embed_query(query, api_key)

    cur.execute(
        """
        SELECT c.id, c.page_id, c.chunk_index, c.text, c.database_key,
               p.title, p.database_name, p.url, p.properties_json,
               1 - (c.embedding <=> %s::vector) AS score
        FROM research_chunks c
        JOIN research_pages p ON p.id = c.page_id
        WHERE c.embedding IS NOT NULL
        ORDER BY c.embedding <=> %s::vector
        LIMIT %s
    """,
        (query_vec, query_vec, limit * 3),
    )
    rows = cur.fetchall()

    conn.close()

    # Filter and dedup
    seen_pages = {}
    results = []
    for row in rows:
        if db_filter and row["database_key"] not in db_filter:
            continue

        props = json.loads(row["properties_json"]) if row.get("properties_json") else {}
        if type_filter and props.get("Type") not in type_filter:
            continue

        pid = row["page_id"]
        if pid in seen_pages:
            continue
        seen_pages[pid] = True

        body = extract_body(row["text"])
        results.append(
            {
                "page_id": pid,
                "title": row["title"] or "Sans titre",
                "body": body,
                "database_key": row["database_key"],
                "database_name": row["database_name"],
                "page_type": props.get("Type"),
                "page_date": props.get("Date"),
                "page_url": row["url"],
                "score": float(row["score"]),
            }
        )

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

    if body:
        text = body
        if len(text) > 300:
            cut = text[:300].rfind(". ")
            if cut > 150:
                text = text[: cut + 1]
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
    link_parts = [f"[Explorer](/terrain?page={page_id})"]
    if page_url:
        link_parts.append(f"[Notion]({page_url})")
    links_str = " · ".join(link_parts)

    lines.append(f"— *{attribution}* · {links_str}")

    return "\n".join(f"> {line}" for line in lines)


def main():
    parser = argparse.ArgumentParser(description="Search the Notion research corpus for relevant citations.")
    parser.add_argument("query", help="Search query (natural language)")
    parser.add_argument("--limit", type=int, default=5, help="Number of citations (default: 5)")
    parser.add_argument("--db", action="append", help="Filter by database key (repeatable)")
    parser.add_argument("--type", action="append", dest="types", help="Filter by type (repeatable)")
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of citations")
    args = parser.parse_args()

    results = search(
        query=args.query,
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
