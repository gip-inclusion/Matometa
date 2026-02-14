#!/usr/bin/env python3
"""Generate embeddings for Notion research corpus using Qwen3-Embedding-0.6B.

Chunks strategy:
- Pages with 0-5 blocks: single chunk (title + properties + body)
- Pages with >5 blocks: split into chunks of ~300-500 chars, each inheriting
  page metadata (title, database, relations)

Each chunk gets a 1024-dim embedding stored in SQLite as a blob.
Similarity search is brute-force cosine (fast enough for <2000 chunks).

Usage:
    python scripts/embed_notion_research.py
    python scripts/embed_notion_research.py --db data/notion_research.db
"""

import argparse
import json
import sqlite3
import struct
import sys
import time
from pathlib import Path

import numpy as np

DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "notion_research.db"
MODEL_NAME = "Qwen/Qwen3-Embedding-0.6B"
CHUNK_THRESHOLD = 5  # blocks: above this, split into chunks
CHUNK_TARGET_CHARS = 400  # target chunk size in characters
CHUNK_MAX_CHARS = 1500  # hard max per chunk (model context limit)


def get_page_body(conn, page_id):
    """Get concatenated block text for a page."""
    rows = conn.execute(
        "SELECT text_content FROM blocks WHERE page_id = ? ORDER BY position",
        (page_id,),
    ).fetchall()
    return "\n".join(r["text_content"] for r in rows if r["text_content"])


def get_page_block_texts(conn, page_id):
    """Get individual block texts for a page."""
    rows = conn.execute(
        "SELECT text_content FROM blocks WHERE page_id = ? ORDER BY position",
        (page_id,),
    ).fetchall()
    return [r["text_content"] for r in rows if r["text_content"] and r["text_content"].strip()]


def resolve_relation_names(conn, page_id, property_name):
    """Resolve relation IDs to page titles."""
    rows = conn.execute(
        """
        SELECT p.title FROM relations r
        JOIN pages p ON p.id = r.target_page_id
        WHERE r.source_page_id = ? AND r.property_name = ?
        """,
        (page_id, property_name),
    ).fetchall()
    return [r["title"] for r in rows if r["title"]]


def build_page_context(conn, page):
    """Build metadata context string for a page."""
    page_id = page["id"]
    parts = []

    # Database
    parts.append(f"[{page['database_name']}]")

    # Resolved relations
    for prop in ["Thématiques", "Cible générale", "Cibles précises", "Hypothèses", "Conclusions"]:
        names = resolve_relation_names(conn, page_id, prop)
        if names:
            parts.append(f"{prop}: {', '.join(names)}")

    # Select properties
    props = json.loads(page["properties_json"])
    for key in ["Type", "Métier", "Structure"]:
        if props.get(key):
            parts.append(f"{key}: {props[key]}")

    # Parent context
    parents = resolve_relation_names(conn, page_id, "Contexte de l'observation")
    if parents:
        parts.append(f"Contexte: {', '.join(parents)}")

    return "\n".join(parts)


def _split_text(text, max_chars):
    """Split text into pieces of at most max_chars, breaking at newlines or spaces."""
    if len(text) <= max_chars:
        return [text]
    pieces = []
    while text:
        if len(text) <= max_chars:
            pieces.append(text)
            break
        # Find a good break point
        cut = text.rfind("\n", 0, max_chars)
        if cut < max_chars // 2:
            cut = text.rfind(" ", 0, max_chars)
        if cut < max_chars // 2:
            cut = max_chars
        pieces.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    return pieces


def build_chunks(conn):
    """Build embedding chunks from the database."""
    pages = conn.execute(
        "SELECT id, database_key, database_name, title, properties_json FROM pages"
    ).fetchall()

    chunks = []
    for page in pages:
        page_id = page["id"]
        title = page["title"] or ""
        context = build_page_context(conn, page)
        header = f"{title}\n{context}"
        block_texts = get_page_block_texts(conn, page_id)

        # Available chars for body in each chunk
        body_budget = CHUNK_MAX_CHARS - len(header) - 10  # 10 for separator
        if body_budget < 100:
            body_budget = 100

        if len(block_texts) <= CHUNK_THRESHOLD:
            # Short page: single chunk (or split if body too long)
            body = "\n".join(block_texts)
            for i, piece in enumerate(_split_text(body, body_budget)):
                text = f"{header}\n{piece}".strip()
                if text:
                    chunks.append({
                        "page_id": page_id,
                        "chunk_index": i,
                        "text": text,
                        "database_key": page["database_key"],
                    })
        else:
            # Long page: group blocks into chunks
            current_chunk_texts = []
            current_chars = 0
            chunk_idx = 0

            for block_text in block_texts:
                # Split individual blocks that are too long
                if len(block_text) > body_budget:
                    # Flush current accumulator first
                    if current_chunk_texts:
                        body = "\n".join(current_chunk_texts)
                        text = f"{header}\n---\n{body}".strip()
                        chunks.append({
                            "page_id": page_id,
                            "chunk_index": chunk_idx,
                            "text": text,
                            "database_key": page["database_key"],
                        })
                        chunk_idx += 1
                        current_chunk_texts = []
                        current_chars = 0

                    for piece in _split_text(block_text, body_budget):
                        text = f"{header}\n---\n{piece}".strip()
                        chunks.append({
                            "page_id": page_id,
                            "chunk_index": chunk_idx,
                            "text": text,
                            "database_key": page["database_key"],
                        })
                        chunk_idx += 1
                    continue

                current_chunk_texts.append(block_text)
                current_chars += len(block_text)

                if current_chars >= CHUNK_TARGET_CHARS:
                    body = "\n".join(current_chunk_texts)
                    text = f"{header}\n---\n{body}".strip()
                    chunks.append({
                        "page_id": page_id,
                        "chunk_index": chunk_idx,
                        "text": text,
                        "database_key": page["database_key"],
                    })
                    chunk_idx += 1
                    current_chunk_texts = []
                    current_chars = 0

            # Remaining blocks
            if current_chunk_texts:
                body = "\n".join(current_chunk_texts)
                text = f"{header}\n---\n{body}".strip()
                chunks.append({
                    "page_id": page_id,
                    "chunk_index": chunk_idx,
                    "text": text,
                    "database_key": page["database_key"],
                })

    return chunks


def embedding_to_blob(vec):
    """Convert numpy array to bytes for SQLite storage."""
    return vec.astype(np.float32).tobytes()


def blob_to_embedding(blob):
    """Convert SQLite blob back to numpy array."""
    return np.frombuffer(blob, dtype=np.float32)


def init_embeddings_table(conn):
    """Create embeddings table."""
    conn.executescript("""
        DROP TABLE IF EXISTS chunks;

        CREATE TABLE chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            page_id TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            text TEXT NOT NULL,
            database_key TEXT NOT NULL,
            embedding BLOB,
            FOREIGN KEY (page_id) REFERENCES pages(id)
        );

        CREATE INDEX idx_chunks_page ON chunks(page_id);
    """)
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="Embed Notion research chunks")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--batch-size", type=int, default=16)
    args = parser.parse_args()

    if not args.db.exists():
        print(f"Error: database not found at {args.db}")
        print("Run sync_notion_research.py first.")
        sys.exit(1)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    # Build chunks
    print("Building chunks...")
    t0 = time.time()
    chunks = build_chunks(conn)
    print(f"  {len(chunks)} chunks built in {time.time() - t0:.1f}s")

    # Show distribution
    from collections import Counter
    db_counts = Counter(c["database_key"] for c in chunks)
    for db_key, count in db_counts.most_common():
        print(f"  {db_key}: {count} chunks")

    # Chunk size stats
    lengths = [len(c["text"]) for c in chunks]
    print(f"  Text length: min={min(lengths)}, median={sorted(lengths)[len(lengths)//2]}, max={max(lengths)}")

    # Load model
    print(f"\nLoading {MODEL_NAME}...")
    t1 = time.time()
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(MODEL_NAME)
    print(f"  Model loaded in {time.time() - t1:.1f}s")

    # Generate embeddings in batches
    print(f"\nEmbedding {len(chunks)} chunks (batch_size={args.batch_size})...")
    t2 = time.time()
    texts = [c["text"] for c in chunks]
    all_embeddings = []

    for i in range(0, len(texts), args.batch_size):
        batch = texts[i : i + args.batch_size]
        embeddings = model.encode(batch, show_progress_bar=False)
        all_embeddings.append(embeddings)
        done = min(i + args.batch_size, len(texts))
        if done % 100 == 0 or done == len(texts):
            elapsed = time.time() - t2
            rate = done / elapsed
            print(f"  {done}/{len(texts)} ({rate:.1f} chunks/s)")

    all_embeddings = np.vstack(all_embeddings)
    embed_time = time.time() - t2
    print(f"  Done in {embed_time:.1f}s ({len(chunks)/embed_time:.1f} chunks/s)")
    print(f"  Embedding shape: {all_embeddings.shape}")

    # Store in database
    print("\nStoring in database...")
    init_embeddings_table(conn)

    for i, chunk in enumerate(chunks):
        conn.execute(
            "INSERT INTO chunks (page_id, chunk_index, text, database_key, embedding) VALUES (?, ?, ?, ?, ?)",
            (
                chunk["page_id"],
                chunk["chunk_index"],
                chunk["text"],
                chunk["database_key"],
                embedding_to_blob(all_embeddings[i]),
            ),
        )

    # Store metadata
    conn.execute(
        "INSERT OR REPLACE INTO sync_meta (key, value) VALUES (?, ?)",
        ("embedding_model", MODEL_NAME),
    )
    conn.execute(
        "INSERT OR REPLACE INTO sync_meta (key, value) VALUES (?, ?)",
        ("embedding_dim", str(all_embeddings.shape[1])),
    )
    conn.execute(
        "INSERT OR REPLACE INTO sync_meta (key, value) VALUES (?, ?)",
        ("embedding_count", str(len(chunks))),
    )
    conn.execute(
        "INSERT OR REPLACE INTO sync_meta (key, value) VALUES (?, ?)",
        ("embedding_time_seconds", str(round(embed_time, 1))),
    )

    conn.commit()
    conn.close()

    # Summary
    db_size = args.db.stat().st_size / 1024 / 1024
    print(f"\n{'=' * 50}")
    print("EMBEDDING COMPLETE")
    print(f"{'=' * 50}")
    print(f"Chunks:     {len(chunks)}")
    print(f"Dimensions: {all_embeddings.shape[1]}")
    print(f"Embed time: {embed_time:.1f}s")
    print(f"DB size:    {db_size:.1f} MB")


if __name__ == "__main__":
    main()
