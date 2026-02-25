#!/usr/bin/env python3
"""Sync from ljt.cc (SQLite) to Scalingo (PostgreSQL + S3).

Data before CUTOFF is assumed correct in PG.  Everything from CUTOFF onward
is deleted from PG and re-inserted from SQLite (source of truth).

Files (interactive/, uploads/) are synced to S3 via size comparison.
matometa.db stays local — never uploaded to S3 or Scalingo.

Usage:
    .venv/bin/python scripts/sync_to_scalingo.py --pull --dry-run
    .venv/bin/python scripts/sync_to_scalingo.py --pull
    .venv/bin/python scripts/sync_to_scalingo.py --db-only
    .venv/bin/python scripts/sync_to_scalingo.py --s3-only
"""

import argparse
import mimetypes
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

DATA_DIR = PROJECT_ROOT / "data-remote"
SQLITE_PATH = DATA_DIR / "matometa.db"
VPS_DATA = "matometa@ljt.cc:/srv/matometa/data"
CUTOFF = "2025-02-24"

# PG BOOLEAN columns — SQLite stores as 0/1, PG needs True/False
PG_BOOL_COLUMNS = {"is_text", "av_scanned", "av_clean"}


def pull_from_vps():
    """Rsync data from ljt.cc to data-remote/."""
    print("=== Pulling from VPS ===")
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # DB file (no --delete, single file)
    print(f"  rsync matometa.db")
    subprocess.run(
        ["rsync", "-avz", f"{VPS_DATA}/matometa.db", str(DATA_DIR) + "/"],
        check=True,
    )

    # Directories (--delete into their own subdirs)
    for subdir in ["interactive", "uploads"]:
        local = DATA_DIR / subdir
        local.mkdir(parents=True, exist_ok=True)
        print(f"  rsync {subdir}/")
        subprocess.run(
            ["rsync", "-avz", "--delete", f"{VPS_DATA}/{subdir}/", str(local) + "/"],
            check=True,
        )


def cast_row(columns, row):
    """Cast SQLite 0/1 to Python bool for PG BOOLEAN columns."""
    return tuple(
        bool(v) if c in PG_BOOL_COLUMNS and isinstance(v, int) else v
        for c, v in zip(columns, row)
    )


def _fetch_rows(src, table, where=None):
    """Fetch rows from SQLite, return (columns, values) ready for PG."""
    query = f"SELECT * FROM [{table}]"
    if where:
        query += f" WHERE {where}"
    rows = src.execute(query).fetchall()
    if not rows:
        return [], []
    columns = [c for c in rows[0].keys() if c != "rowid"]
    values = [cast_row(columns, tuple(r[c] for c in columns)) for r in rows]
    return columns, values


def sync_db(database_url: str, dry_run: bool = False):
    """Sync SQLite → PG.  Delete post-cutoff PG data, re-insert from SQLite."""
    import psycopg2
    from psycopg2.extras import execute_values

    src = sqlite3.connect(str(SQLITE_PATH))
    src.row_factory = sqlite3.Row
    dst = psycopg2.connect(database_url)
    dst.autocommit = False
    cur = dst.cursor()

    try:
        print(f"  Cutoff: {CUTOFF}\n")

        # ── Phase 1: Delete post-cutoff PG data (children first) ──

        for t in ["conversation_tags", "report_tags", "tags"]:
            if not dry_run:
                cur.execute(f"DELETE FROM {t}")
            print(f"  {t}: cleared")

        for t, ts in [("messages", "timestamp"), ("uploaded_files", "created_at")]:
            if not dry_run:
                cur.execute(f"DELETE FROM {t} WHERE {ts} >= %s", (CUTOFF,))
            print(f"  {t}: deleted rows >= {CUTOFF}")

        for t, ts in [("conversations", "created_at"), ("reports", "created_at"),
                       ("pinned_items", "pinned_at"), ("cron_runs", "started_at")]:
            if not dry_run:
                cur.execute(f"DELETE FROM {t} WHERE {ts} >= %s", (CUTOFF,))
            print(f"  {t}: deleted rows >= {CUTOFF}")

        # ── Phase 2: Insert from SQLite (parents first) ──

        print()

        # Conversations: upsert (catches both new and pre-cutoff modified)
        columns, values = _fetch_rows(src, "conversations", f"updated_at >= '{CUTOFF}'")
        if values:
            col_list = ", ".join(columns)
            set_cols = [c for c in columns if c != "id"]
            conflict_update = ", ".join(f"{c} = EXCLUDED.{c}" for c in set_cols)
            if dry_run:
                print(f"  conversations: would upsert {len(values)} rows")
            else:
                execute_values(
                    cur,
                    f"INSERT INTO conversations ({col_list}) VALUES %s "
                    f"ON CONFLICT (id) DO UPDATE SET {conflict_update}",
                    values, page_size=500,
                )
                print(f"  conversations: upserted {len(values)} rows")
        else:
            print("  conversations: nothing to sync")

        # Other timestamped tables: plain insert (post-cutoff rows were deleted)
        for t, ts in [("messages", "timestamp"), ("reports", "updated_at"),
                       ("uploaded_files", "created_at"), ("pinned_items", "pinned_at"),
                       ("cron_runs", "started_at")]:
            columns, values = _fetch_rows(src, t, f"{ts} >= '{CUTOFF}'")
            if values:
                col_list = ", ".join(columns)
                if dry_run:
                    print(f"  {t}: would insert {len(values)} rows")
                else:
                    execute_values(cur, f"INSERT INTO {t} ({col_list}) VALUES %s",
                                   values, page_size=500)
                    print(f"  {t}: inserted {len(values)} rows")
            else:
                print(f"  {t}: nothing to sync")

        # Join tables: full replace (filter to existing FK parents)
        cur.execute("SELECT id FROM conversations")
        pg_conv_ids = {r[0] for r in cur.fetchall()}
        cur.execute("SELECT id FROM reports")
        pg_report_ids = {r[0] for r in cur.fetchall()}
        cur.execute("SELECT id FROM tags")
        pg_tag_ids = {r[0] for r in cur.fetchall()}

        # tags first (no FK filter needed)
        columns, values = _fetch_rows(src, "tags")
        if values:
            col_list = ", ".join(columns)
            if not dry_run:
                execute_values(cur, f"INSERT INTO tags ({col_list}) VALUES %s",
                               values, page_size=500)
            print(f"  tags: inserted {len(values)} rows")
            # refresh tag IDs after insert
            cur.execute("SELECT id FROM tags")
            pg_tag_ids = {r[0] for r in cur.fetchall()}

        # conversation_tags: filter to existing conversations + tags
        columns, values = _fetch_rows(src, "conversation_tags")
        if values:
            ci = columns.index("conversation_id")
            ti = columns.index("tag_id")
            values = [v for v in values if v[ci] in pg_conv_ids and v[ti] in pg_tag_ids]
            col_list = ", ".join(columns)
            if not dry_run:
                execute_values(cur, f"INSERT INTO conversation_tags ({col_list}) VALUES %s",
                               values, page_size=500)
            print(f"  conversation_tags: inserted {len(values)} rows")

        # report_tags: filter to existing reports + tags
        columns, values = _fetch_rows(src, "report_tags")
        if values:
            ri = columns.index("report_id")
            ti = columns.index("tag_id")
            values = [v for v in values if v[ri] in pg_report_ids and v[ti] in pg_tag_ids]
            col_list = ", ".join(columns)
            if not dry_run:
                execute_values(cur, f"INSERT INTO report_tags ({col_list}) VALUES %s",
                               values, page_size=500)
            print(f"  report_tags: inserted {len(values)} rows")

        # Reset sequences
        if not dry_run:
            for t in ["messages", "reports", "uploaded_files",
                       "pinned_items", "cron_runs", "tags"]:
                cur.execute(
                    f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), "
                    f"COALESCE(MAX(id), 0) + 1, false) FROM {t}"
                )

        if not dry_run:
            dst.commit()
            print("\nDB sync committed.")
        else:
            dst.rollback()
            print("\n[dry-run] No DB changes made.")

    except Exception:
        dst.rollback()
        raise
    finally:
        cur.close()
        dst.close()
        src.close()


def sync_s3(dry_run: bool = False):
    """Sync interactive/ and uploads/ to S3, skipping unchanged files."""
    import boto3
    from botocore.config import Config as BotoConfig

    bucket = os.environ["S3_BUCKET"]
    endpoint = os.environ.get("S3_ENDPOINT")
    prefix = os.environ.get("S3_PREFIX", "interactive/")

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ["S3_ACCESS_KEY"],
        aws_secret_access_key=os.environ["S3_SECRET_KEY"],
        region_name=os.environ.get("S3_REGION", "fr-par"),
        config=BotoConfig(signature_version="s3v4"),
    )

    existing = {}
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            existing[obj["Key"]] = obj["Size"]

    uploaded = 0
    skipped = 0

    for subdir, key_prefix in [("interactive", prefix), ("uploads", f"{prefix}uploads/")]:
        local_dir = DATA_DIR / subdir
        if not local_dir.exists():
            continue

        for f in sorted(f for f in local_dir.rglob("*") if f.is_file()):
            key = f"{key_prefix}{f.relative_to(local_dir)}"
            size = f.stat().st_size

            if key in existing and existing[key] == size:
                skipped += 1
                continue

            content_type = mimetypes.guess_type(str(f))[0] or "application/octet-stream"

            if dry_run:
                action = "new" if key not in existing else "changed"
                print(f"  [{action}] {key} ({size:,} bytes)")
            else:
                client.put_object(Bucket=bucket, Key=key,
                                  Body=f.read_bytes(), ContentType=content_type)
                print(f"  {key} ({size:,} bytes)")
            uploaded += 1

    print(f"\nS3: {uploaded} {'would upload' if dry_run else 'uploaded'}, {skipped} unchanged")


def main():
    parser = argparse.ArgumentParser(description="Sync ljt.cc → Scalingo")
    parser.add_argument("--pull", action="store_true", help="Rsync from VPS first")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done")
    parser.add_argument("--db-only", action="store_true", help="Only sync database")
    parser.add_argument("--s3-only", action="store_true", help="Only sync files to S3")
    args = parser.parse_args()

    if args.pull:
        pull_from_vps()

    if not SQLITE_PATH.exists():
        print(f"ERROR: {SQLITE_PATH} not found. Run with --pull first.")
        sys.exit(1)

    do_db = not args.s3_only
    do_s3 = not args.db_only

    if do_db:
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            print("ERROR: DATABASE_URL not set.")
            sys.exit(1)
        print("=== DB Sync (SQLite → PostgreSQL) ===")
        sync_db(database_url, dry_run=args.dry_run)

    if do_s3:
        if not os.environ.get("S3_BUCKET"):
            print("ERROR: S3_BUCKET not set.")
            sys.exit(1)
        print(f"\n=== S3 Sync (files → {os.environ['S3_BUCKET']}) ===")
        sync_s3(dry_run=args.dry_run)

    print("\nDone!")


if __name__ == "__main__":
    main()
