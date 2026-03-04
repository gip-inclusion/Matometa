"""Research corpus exploration API routes.

Provides semantic search and navigation across the Notion "Connaissance du terrain"
corpus (interviews, observations, themes, hypotheses, conclusions).

Embeddings are stored in PostgreSQL with pgvector (populated by scripts/refresh_research.py).
Query encoding uses DeepInfra's hosted Qwen3-Embedding-0.6B model.
"""

import json
import logging

import numpy as np
import requests
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from .. import config
from ..db import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/research")

DEEPINFRA_URL = "https://api.deepinfra.com/v1/openai/embeddings"
EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-0.6B"


def _embed_query(text):
    """Encode a query string using DeepInfra API."""
    api_key = config.DEEPINFRA_API_KEY
    if not api_key:
        raise ValueError("DEEPINFRA_API_KEY not configured")

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
    # Format as pgvector string literal
    return '[' + ','.join(str(float(x)) for x in vec) + ']'


def _extract_body(text):
    """Extract body text from a chunk, stripping the metadata header.

    Chunk format:
      Title
      [Database name]
      Key: Value
      ...
      ---           (only in multi-chunk pages)
      body text

    For single-chunk pages (no ---), the title line and metadata lines
    after it are stripped; any remaining content is the body.
    """
    if "\n---\n" in text:
        return text.split("\n---\n", 1)[1].strip()

    # No --- separator: skip title (line 0) + metadata lines
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
        # Non-metadata line found
        break
    body = "\n".join(lines[body_start:]).strip()
    return body


def _build_result(row, score=None):
    """Build a result dict from a database row with joined page info."""
    props = json.loads(row["properties_json"]) if row.get("properties_json") else {}
    result = {
        "chunk_id": row["id"],
        "page_id": row["page_id"],
        "chunk_index": row["chunk_index"],
        "body": _extract_body(row["text"]),
        "database_key": row["database_key"],
        "page_title": row.get("title"),
        "database_name": row.get("database_name"),
        "page_url": row.get("url"),
        "page_type": props.get("Type"),
        "page_date": props.get("Date"),
    }
    if score is not None:
        result["score"] = round(float(score), 4)
    return result


def _dedupe_by_page(results):
    """Keep only the best-scoring result per page_id."""
    seen = {}
    deduped = []
    for r in results:
        pid = r["page_id"]
        if pid not in seen:
            seen[pid] = len(deduped)
            r["matching_chunks"] = 1
            deduped.append(r)
        else:
            deduped[seen[pid]]["matching_chunks"] += 1
    return deduped


def _corpus_available(conn):
    """Check if research corpus has any data."""
    row = conn.execute("SELECT COUNT(*) as n FROM research_pages").fetchone()
    return row["n"] > 0


# ---------------------------------------------------------------------------
# Public helpers (used by HTML routes too)
# ---------------------------------------------------------------------------


def get_corpus_stats():
    """Return corpus stats dict, or None if corpus is empty."""
    with get_db() as conn:
        if not _corpus_available(conn):
            return None

        pages_n = conn.execute("SELECT COUNT(*) as n FROM research_pages").fetchone()["n"]
        chunks_n = conn.execute("SELECT COUNT(*) as n FROM research_chunks").fetchone()["n"]

        db_stats = conn.execute(
            "SELECT database_key, database_name, COUNT(*) as n "
            "FROM research_pages GROUP BY database_key, database_name"
        ).fetchall()

        chunk_counts = conn.execute(
            "SELECT database_key, COUNT(*) as n FROM research_chunks GROUP BY database_key"
        ).fetchall()
        chunks_by_db = {r["database_key"]: r["n"] for r in chunk_counts}

        type_rows = conn.execute(
            "SELECT properties_json FROM research_pages WHERE database_key = 'entretiens'"
        ).fetchall()
        type_counts = {}
        for row in type_rows:
            props = json.loads(row["properties_json"]) if row["properties_json"] else {}
            t = props.get("Type")
            if t:
                type_counts[t] = type_counts.get(t, 0) + 1

        return {
            "pages": pages_n,
            "chunks": chunks_n,
            "databases": [
                {
                    "key": r["database_key"],
                    "name": r["database_name"],
                    "pages": r["n"],
                    "chunks": chunks_by_db.get(r["database_key"], 0),
                }
                for r in db_stats
            ],
            "types": type_counts,
        }


def search_corpus(q, limit=20, db_filter=None, type_filter=None):
    """Run semantic search. Returns (results, total_chunks) or (None, None)."""
    with get_db() as conn:
        if not _corpus_available(conn):
            return None, None

        total_chunks = conn.execute("SELECT COUNT(*) as n FROM research_chunks").fetchone()["n"]
        if total_chunks == 0:
            return [], 0

        query_vec = _embed_query(q)

        # pgvector similarity search with JOIN
        rows = conn.execute("""
            SELECT c.id, c.page_id, c.chunk_index, c.text, c.database_key,
                   p.title, p.database_name, p.url, p.properties_json,
                   1 - (c.embedding <=> %s::vector) AS score
            FROM research_chunks c
            JOIN research_pages p ON p.id = c.page_id
            WHERE c.embedding IS NOT NULL
            ORDER BY c.embedding <=> %s::vector
            LIMIT %s
        """, (query_vec, query_vec, limit * 3)).fetchall()

        raw_results = []
        for row in rows:
            if db_filter and row["database_key"] not in db_filter:
                continue
            props = json.loads(row["properties_json"]) if row.get("properties_json") else {}
            if type_filter and props.get("Type") not in type_filter:
                continue
            raw_results.append(_build_result(row, row["score"]))

        return _dedupe_by_page(raw_results)[:limit], total_chunks


def find_similar_pages(chunk_id, limit=15):
    """Find pages similar to a given chunk. Returns (results, source_page_id) or (None, None)."""
    with get_db() as conn:
        if not _corpus_available(conn):
            return None, None

        # Get the source chunk's page_id
        source = conn.execute(
            "SELECT page_id FROM research_chunks WHERE id = %s", (chunk_id,)
        ).fetchone()
        if not source:
            return None, None
        source_page_id = source["page_id"]

        # pgvector: find similar chunks excluding same page
        rows = conn.execute("""
            SELECT c.id, c.page_id, c.chunk_index, c.text, c.database_key,
                   p.title, p.database_name, p.url, p.properties_json,
                   1 - (c.embedding <=> (SELECT embedding FROM research_chunks WHERE id = %s)) AS score
            FROM research_chunks c
            JOIN research_pages p ON p.id = c.page_id
            WHERE c.page_id != %s AND c.embedding IS NOT NULL
            ORDER BY c.embedding <=> (SELECT embedding FROM research_chunks WHERE id = %s)
            LIMIT %s
        """, (chunk_id, source_page_id, chunk_id, limit * 3)).fetchall()

        raw_results = [_build_result(row, row["score"]) for row in rows]
        return _dedupe_by_page(raw_results)[:limit], source_page_id


def get_page(page_id):
    """Get full page details. Returns dict or None."""
    with get_db() as conn:
        page = conn.execute(
            "SELECT * FROM research_pages WHERE id = %s", (page_id,)
        ).fetchone()
        if not page:
            return None

        props = json.loads(page["properties_json"]) if page["properties_json"] else {}

        blocks = conn.execute(
            "SELECT type, text_content, position FROM research_blocks "
            "WHERE page_id = %s ORDER BY position",
            (page_id,),
        ).fetchall()

        relations = {}
        rels = conn.execute(
            "SELECT r.property_name, p.title, p.id as target_id "
            "FROM research_relations r "
            "LEFT JOIN research_pages p ON p.id = r.target_page_id "
            "WHERE r.source_page_id = %s",
            (page_id,),
        ).fetchall()
        for r in rels:
            prop = r["property_name"]
            if prop not in relations:
                relations[prop] = []
            relations[prop].append({
                "title": r["title"],
                "page_id": r["target_id"],
            })

        chunks = conn.execute(
            "SELECT id, chunk_index FROM research_chunks "
            "WHERE page_id = %s ORDER BY chunk_index",
            (page_id,),
        ).fetchall()

        return {
            "id": page["id"],
            "title": page["title"],
            "database_key": page["database_key"],
            "database_name": page["database_name"],
            "url": page["url"],
            "type": props.get("Type"),
            "date": props.get("Date"),
            "properties": props,
            "blocks": [
                {"type": b["type"], "text": b["text_content"], "position": b["position"]}
                for b in blocks
            ],
            "relations": relations,
            "chunk_ids": [c["id"] for c in chunks],
        }


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------


@router.get("/search")
def search(
    q: str = Query(default=""),
    limit: int = Query(default=20),
    db: list[str] = Query(default=[]),
    type: list[str] = Query(default=[]),
):
    """Semantic search across the research corpus."""
    q = q.strip()
    if not q:
        return JSONResponse({"error": "Missing query parameter 'q'"}, status_code=400)

    limit = min(limit, 50)
    db_filter = set(db)
    type_filter = set(type)

    results, total_chunks = search_corpus(q, limit, db_filter or None, type_filter or None)
    if results is None:
        return JSONResponse({"error": "Research corpus is empty"}, status_code=404)

    return {
        "results": results,
        "query": q,
        "total_chunks": total_chunks,
    }


@router.get("/similar/{chunk_id}")
def similar(chunk_id: int, limit: int = Query(default=15)):
    """Find chunks similar to a given chunk (deduplicated by page)."""
    limit = min(limit, 30)

    results, source_page_id = find_similar_pages(chunk_id, limit)
    if results is None:
        return JSONResponse({"error": "Chunk not found or corpus empty"}, status_code=404)

    return {
        "results": results,
        "source_chunk_id": chunk_id,
        "source_page_id": source_page_id,
    }


@router.get("/pages/{page_id}")
def page_detail(page_id: str):
    """Full page details: properties, blocks, relations, chunks."""
    result = get_page(page_id)
    if not result:
        return JSONResponse({"error": "Page not found"}, status_code=404)
    return result


@router.get("/stats")
def stats():
    """Corpus statistics, including type breakdown for entretiens."""
    with get_db() as conn:
        if not _corpus_available(conn):
            return JSONResponse({"error": "Research corpus is empty"}, status_code=404)

        pages_n = conn.execute("SELECT COUNT(*) as n FROM research_pages").fetchone()["n"]
        blocks_n = conn.execute("SELECT COUNT(*) as n FROM research_blocks").fetchone()["n"]
        chunks_n = conn.execute("SELECT COUNT(*) as n FROM research_chunks").fetchone()["n"]

        db_stats = conn.execute(
            "SELECT database_key, database_name, COUNT(*) as n "
            "FROM research_pages GROUP BY database_key, database_name"
        ).fetchall()

        chunk_counts = conn.execute(
            "SELECT database_key, COUNT(*) as n FROM research_chunks GROUP BY database_key"
        ).fetchall()
        chunks_by_db = {r["database_key"]: r["n"] for r in chunk_counts}

        type_rows = conn.execute(
            "SELECT properties_json FROM research_pages WHERE database_key = 'entretiens'"
        ).fetchall()
        type_counts = {}
        for row in type_rows:
            props = json.loads(row["properties_json"]) if row["properties_json"] else {}
            t = props.get("Type")
            if t:
                type_counts[t] = type_counts.get(t, 0) + 1

        meta = {}
        for row in conn.execute("SELECT key, value FROM research_sync_meta").fetchall():
            meta[row["key"]] = row["value"]

        return {
            "pages": pages_n,
            "blocks": blocks_n,
            "chunks": chunks_n,
            "databases": [
                {
                    "key": r["database_key"],
                    "name": r["database_name"],
                    "pages": r["n"],
                    "chunks": chunks_by_db.get(r["database_key"], 0),
                }
                for r in db_stats
            ],
            "types": type_counts,
            "sync_meta": meta,
        }
