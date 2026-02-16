#!/usr/bin/env python3
"""Create webinaires tables on datalake and optionally export existing SQLite data.

Usage:
    python scripts/datalake_create_webinaires.py                    # Create tables only
    python scripts/datalake_create_webinaires.py --export data/webinaires.db  # Create + export
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from lib.query import execute_metabase_query, CallerType

DATABASE_ID = 2


def run_sql(sql, label="", write=False):
    result = execute_metabase_query(
        instance="datalake",
        caller=CallerType.APP,
        sql=sql,
        database_id=DATABASE_ID,
    )
    if result.success:
        if label:
            print(f"  OK: {label}")
    elif write and result.error and "ResultSet" in result.error:
        # DDL/INSERT/UPDATE execute but Metabase complains about no ResultSet
        if label:
            print(f"  OK: {label}")
    else:
        print(f"  FAIL: {label}: {result.error}")
        sys.exit(1)
    return result


def create_tables():
    print("Creating tables on datalake...")

    run_sql("""
    CREATE TABLE IF NOT EXISTS matometa_webinaires (
        id VARCHAR(255) PRIMARY KEY,
        source VARCHAR(20) NOT NULL,
        source_id TEXT NOT NULL,
        title TEXT,
        description TEXT,
        organizer_email TEXT,
        product VARCHAR(50),
        status VARCHAR(50),
        started_at TIMESTAMPTZ,
        ended_at TIMESTAMPTZ,
        duration_minutes INTEGER,
        capacity INTEGER,
        registrants_count INTEGER,
        attendees_count INTEGER,
        registration_url TEXT,
        webinar_url TEXT,
        raw_json JSONB,
        synced_at TIMESTAMPTZ
    )
    """, "matometa_webinaires", write=True)

    run_sql("""
    CREATE TABLE IF NOT EXISTS matometa_webinaire_sessions (
        id VARCHAR(255) PRIMARY KEY,
        webinar_id VARCHAR(255) REFERENCES matometa_webinaires(id),
        status VARCHAR(50),
        started_at TIMESTAMPTZ,
        ended_at TIMESTAMPTZ,
        duration_seconds INTEGER,
        registrants_count INTEGER,
        attendees_count INTEGER,
        room_link TEXT,
        synced_at TIMESTAMPTZ
    )
    """, "matometa_webinaire_sessions", write=True)

    run_sql("""
    CREATE TABLE IF NOT EXISTS matometa_webinaire_inscriptions (
        id SERIAL PRIMARY KEY,
        source VARCHAR(20) NOT NULL,
        webinar_id VARCHAR(255) NOT NULL,
        session_id VARCHAR(255) NOT NULL DEFAULT '',
        email TEXT NOT NULL,
        first_name TEXT,
        last_name TEXT,
        organisation TEXT,
        registered SMALLINT DEFAULT 1,
        attended SMALLINT,
        attendance_rate REAL,
        attendance_duration_seconds INTEGER,
        has_viewed_replay SMALLINT,
        custom_fields JSONB,
        registered_at TIMESTAMPTZ,
        synced_at TIMESTAMPTZ,
        UNIQUE(source, webinar_id, session_id, email)
    )
    """, "matometa_webinaire_inscriptions", write=True)

    run_sql("""
    CREATE TABLE IF NOT EXISTS matometa_webinaire_sync_meta (
        key VARCHAR(255) PRIMARY KEY,
        value TEXT
    )
    """, "matometa_webinaire_sync_meta", write=True)

    # Indexes
    for idx_sql, label in [
        ("CREATE INDEX IF NOT EXISTS idx_mw_reg_email ON matometa_webinaire_inscriptions(email)",
         "idx email"),
        ("CREATE INDEX IF NOT EXISTS idx_mw_reg_org ON matometa_webinaire_inscriptions(organisation)",
         "idx organisation"),
        ("CREATE INDEX IF NOT EXISTS idx_mw_reg_webinar ON matometa_webinaire_inscriptions(webinar_id)",
         "idx webinar_id"),
        ("CREATE INDEX IF NOT EXISTS idx_mw_sessions_webinar ON matometa_webinaire_sessions(webinar_id)",
         "idx sessions.webinar_id"),
    ]:
        run_sql(idx_sql, label, write=True)

    print("Done.\n")


def escape(val):
    if val is None:
        return "NULL"
    if isinstance(val, (int, float)):
        return str(val)
    s = str(val).replace("'", "''")
    return f"'{s}'"


def export_sqlite(db_path: Path):
    print(f"Exporting from {db_path}...")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Webinars
    rows = conn.execute("SELECT * FROM webinars").fetchall()
    print(f"  webinars: {len(rows)} rows")
    batch_size = 10
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        values = []
        for r in batch:
            values.append("({})".format(", ".join([
                escape(r["id"]), escape(r["source"]), escape(r["source_id"]),
                escape(r["title"]), escape(r["description"]),
                escape(r["organizer_email"]), escape(r["product"]),
                escape(r["status"]), escape(r["started_at"]),
                escape(r["ended_at"]), escape(r["duration_minutes"]),
                escape(r["capacity"]), escape(r["registrants_count"]),
                escape(r["attendees_count"]), escape(r["registration_url"]),
                escape(r["webinar_url"]), escape(r["raw_json"]),
                escape(r["synced_at"]),
            ])))
        sql = """INSERT INTO matometa_webinaires
            (id, source, source_id, title, description, organizer_email,
             product, status, started_at, ended_at, duration_minutes,
             capacity, registrants_count, attendees_count, registration_url,
             webinar_url, raw_json, synced_at)
            VALUES {} ON CONFLICT(id) DO NOTHING""".format(", ".join(values))
        run_sql(sql, f"webinars batch {i // batch_size + 1}", write=True)

    # Sessions
    rows = conn.execute("SELECT * FROM sessions").fetchall()
    print(f"  sessions: {len(rows)} rows")
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        values = []
        for r in batch:
            values.append("({})".format(", ".join([
                escape(r["id"]), escape(r["webinar_id"]), escape(r["status"]),
                escape(r["started_at"]), escape(r["ended_at"]),
                escape(r["duration_seconds"]), escape(r["registrants_count"]),
                escape(r["attendees_count"]), escape(r["room_link"]),
                escape(r["synced_at"]),
            ])))
        sql = """INSERT INTO matometa_webinaire_sessions
            (id, webinar_id, status, started_at, ended_at, duration_seconds,
             registrants_count, attendees_count, room_link, synced_at)
            VALUES {} ON CONFLICT(id) DO NOTHING""".format(", ".join(values))
        run_sql(sql, f"sessions batch {i // batch_size + 1}", write=True)

    # Registrations (bigger, use larger batches)
    rows = conn.execute("SELECT * FROM registrations").fetchall()
    print(f"  registrations: {len(rows)} rows")
    reg_batch = 20
    for i in range(0, len(rows), reg_batch):
        batch = rows[i:i + reg_batch]
        values = []
        for r in batch:
            values.append("({})".format(", ".join([
                escape(r["source"]), escape(r["webinar_id"]),
                escape(r["session_id"]), escape(r["email"]),
                escape(r["first_name"]), escape(r["last_name"]),
                escape(r["organisation"]), escape(r["registered"]),
                escape(r["attended"]), escape(r["attendance_rate"]),
                escape(r["attendance_duration_seconds"]),
                escape(r["has_viewed_replay"]), escape(r["custom_fields"]),
                escape(r["registered_at"]), escape(r["synced_at"]),
            ])))
        sql = """INSERT INTO matometa_webinaire_inscriptions
            (source, webinar_id, session_id, email, first_name, last_name,
             organisation, registered, attended, attendance_rate,
             attendance_duration_seconds, has_viewed_replay, custom_fields,
             registered_at, synced_at)
            VALUES {}
            ON CONFLICT(source, webinar_id, session_id, email) DO NOTHING""".format(
                ", ".join(values))
        run_sql(sql, f"registrations batch {i // reg_batch + 1}", write=True)
        if (i + reg_batch) % 1000 == 0:
            print(f"    {i + reg_batch}/{len(rows)}")

    # Sync meta
    rows = conn.execute("SELECT * FROM sync_meta").fetchall()
    for r in rows:
        sql = """INSERT INTO matometa_webinaire_sync_meta (key, value) VALUES ({}, {})
            ON CONFLICT(key) DO UPDATE SET value=excluded.value""".format(
                escape(r["key"]), escape(r["value"]))
        run_sql(sql, f"sync_meta: {r['key']}", write=True)

    conn.close()

    # Verify
    print("\nVerifying...")
    for table, expected in [
        ("matometa_webinaires", "webinars"),
        ("matometa_webinaire_sessions", "sessions"),
        ("matometa_webinaire_inscriptions", "registrations"),
    ]:
        result = run_sql(f"SELECT COUNT(*) FROM {table}", f"count {table}")
        count = result.data["rows"][0][0]
        print(f"  {table}: {count} rows")

    print("\nExport complete.")


def main():
    parser = argparse.ArgumentParser(description="Create webinaires tables on datalake")
    parser.add_argument("--export", type=Path, help="SQLite DB to export from")
    args = parser.parse_args()

    create_tables()

    if args.export:
        if not args.export.exists():
            print(f"Error: {args.export} not found")
            sys.exit(1)
        export_sqlite(args.export)


if __name__ == "__main__":
    main()
