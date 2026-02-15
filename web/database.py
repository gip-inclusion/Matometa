"""Database for conversation and report persistence (SQLite or PostgreSQL)."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional, Any
import uuid
import os

from . import config

# Database backend detection from DATABASE_URL
USE_POSTGRES = config.DATABASE_URL is not None and config.DATABASE_URL.startswith(("postgres://", "postgresql://"))

# Schema version - increment when adding migrations
SCHEMA_VERSION = 17

if USE_POSTGRES:
    import psycopg2
    from psycopg2.extras import RealDictCursor

# Valid column names for dynamic updates (security: prevents SQL injection)
VALID_CONVERSATION_COLUMNS = frozenset({"title", "session_id", "user_id", "status", "pr_url", "updated_at", "pinned_at", "pinned_label", "needs_response"})
VALID_REPORT_COLUMNS = frozenset({"title", "website", "category", "tags", "original_query", "content", "updated_at"})


def _build_update_clause(updates: dict, valid_columns: frozenset) -> tuple[str, list]:
    """
    Build a safe UPDATE SET clause from a dict of updates.

    Validates all keys against valid_columns to prevent SQL injection.
    Returns (set_clause, values) for use in parameterized query.
    Uses ? placeholders (ConnectionWrapper converts to %s for PostgreSQL).

    Raises ValueError if any key is not in valid_columns.
    """
    for key in updates:
        if key not in valid_columns:
            raise ValueError(f"Invalid column name: {key}")

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values())
    return set_clause, values


class DictRowWrapper:
    """Wrapper to make psycopg2 RealDictRow behave like sqlite3.Row for .keys() method."""
    def __init__(self, row: dict):
        self._row = row

    def __getitem__(self, key):
        return self._row[key]

    def keys(self):
        return self._row.keys()


class ConnectionWrapper:
    """Wrapper to normalize sqlite3 and psycopg2 connection interfaces.

    Provides a unified interface for both SQLite and PostgreSQL:
    - Automatic placeholder conversion (? to %s for PostgreSQL)
    - Consistent row factory (dict-like access)
    - Helper methods for common patterns (insert_and_get_id, insert_ignore)
    """

    def __init__(self, conn, is_postgres: bool):
        self._conn = conn
        self._is_postgres = is_postgres
        self._cursor = None

    @property
    def is_postgres(self) -> bool:
        """Check if this is a PostgreSQL connection."""
        return self._is_postgres

    def execute(self, sql: str, params: tuple = ()) -> "ConnectionWrapper":
        """Execute a query, converting placeholders if needed."""
        if self._is_postgres:
            # Convert ? to %s for PostgreSQL
            sql = sql.replace("?", "%s")
            self._cursor = self._conn.cursor(cursor_factory=RealDictCursor)
        else:
            self._cursor = self._conn.cursor()
        self._cursor.execute(sql, params)
        return self

    def executescript(self, sql: str) -> "ConnectionWrapper":
        """Execute multiple statements (SQLite) or single execution (PostgreSQL)."""
        if self._is_postgres:
            # PostgreSQL can execute multiple statements in one call
            self._cursor = self._conn.cursor()
            self._cursor.execute(sql)
        else:
            self._conn.executescript(sql)
            self._cursor = self._conn.cursor()
        return self

    def executemany(self, sql: str, params_list: list) -> "ConnectionWrapper":
        """Execute a query with multiple parameter sets."""
        if self._is_postgres:
            sql = sql.replace("?", "%s")
            self._cursor = self._conn.cursor()
        else:
            self._cursor = self._conn.cursor()
        self._cursor.executemany(sql, params_list)
        return self

    def fetchone(self) -> Optional[Any]:
        """Fetch one row."""
        if self._cursor is None:
            return None
        row = self._cursor.fetchone()
        if row is None:
            return None
        if self._is_postgres:
            return DictRowWrapper(row)
        return row

    def fetchall(self) -> list:
        """Fetch all rows."""
        if self._cursor is None:
            return []
        rows = self._cursor.fetchall()
        if self._is_postgres:
            return [DictRowWrapper(row) for row in rows]
        return rows

    @property
    def lastrowid(self) -> Optional[int]:
        """Get last inserted row ID."""
        if self._cursor is None:
            return None
        if self._is_postgres:
            # PostgreSQL needs RETURNING clause, handle in caller
            return None
        return self._cursor.lastrowid

    @property
    def rowcount(self) -> int:
        """Get number of affected rows."""
        if self._cursor is None:
            return 0
        return self._cursor.rowcount

    def insert_and_get_id(self, sql: str, params: tuple = ()) -> Optional[int]:
        """Execute an INSERT and return the new row's ID.

        For PostgreSQL, appends RETURNING id to the query.
        For SQLite, uses lastrowid.
        """
        if self._is_postgres:
            sql = sql.replace("?", "%s")
            if "RETURNING" not in sql.upper():
                sql = sql.rstrip().rstrip(";") + " RETURNING id"
            self._cursor = self._conn.cursor(cursor_factory=RealDictCursor)
            self._cursor.execute(sql, params)
            row = self._cursor.fetchone()
            return row["id"] if row else None
        else:
            self._cursor = self._conn.cursor()
            self._cursor.execute(sql, params)
            return self._cursor.lastrowid

    def insert_ignore(self, table: str, columns: list[str], values: tuple) -> "ConnectionWrapper":
        """Execute an INSERT that ignores conflicts (duplicate keys).

        Uses INSERT OR IGNORE for SQLite, INSERT ... ON CONFLICT DO NOTHING for PostgreSQL.
        """
        placeholders = ", ".join(["%s" if self._is_postgres else "?"] * len(values))
        cols = ", ".join(columns)

        if self._is_postgres:
            sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"
            self._cursor = self._conn.cursor(cursor_factory=RealDictCursor)
        else:
            sql = f"INSERT OR IGNORE INTO {table} ({cols}) VALUES ({placeholders})"
            self._cursor = self._conn.cursor()

        self._cursor.execute(sql, values)
        return self

    def commit(self):
        """Commit the transaction."""
        self._conn.commit()

    def rollback(self):
        """Rollback the transaction."""
        self._conn.rollback()

    def close(self):
        """Close the connection."""
        self._conn.close()


def get_connection() -> ConnectionWrapper:
    """Get a database connection with row factory."""
    if USE_POSTGRES:
        conn = psycopg2.connect(config.DATABASE_URL)
        return ConnectionWrapper(conn, is_postgres=True)
    else:
        config.SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(config.SQLITE_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-65536")
        conn.execute("PRAGMA foreign_keys = ON")
        return ConnectionWrapper(conn, is_postgres=False)


@contextmanager
def get_db():
    """Context manager for database connections."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _get_schema_version(conn: ConnectionWrapper) -> int:
    """Get current schema version, or 0 if no schema exists."""
    try:
        row = conn.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()
        return row["version"] if row else 0
    except sqlite3.OperationalError:
        return 0
    except Exception as e:
        if USE_POSTGRES:
            error_code = getattr(e, "pgcode", None)
            if error_code == "42P01":  # undefined_table
                conn.rollback()
                return 0
        raise


def _set_schema_version(conn: ConnectionWrapper, version: int):
    """Set the schema version."""
    if conn.is_postgres:
        conn.execute(
            "INSERT INTO schema_version (version) VALUES (%s) ON CONFLICT (version) DO UPDATE SET version = %s",
            (version, version)
        )
    else:
        conn.execute("INSERT OR REPLACE INTO schema_version (version) VALUES (?)", (version,))


def _get_table_columns(conn: ConnectionWrapper, table_name: str) -> set[str]:
    """Get column names for a table."""
    if conn.is_postgres:
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
            (table_name,)
        ).fetchall()
        return {row['column_name'] for row in rows}
    else:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {row['name'] for row in rows}


def init_db():
    """Initialize or migrate database schema."""
    with get_db() as conn:
        current_version = _get_schema_version(conn)

        if current_version < SCHEMA_VERSION:
            # Fresh install or pre-versioned database
            if current_version == 0:
                _create_schema(conn)
                _seed_tags(conn)
            else:
                if current_version < 11:
                    _migrate_to_v11(conn)
                if current_version < 12:
                    _migrate_to_v12(conn)
                if current_version < 13:
                    _migrate_to_v13(conn)
                if current_version < 14:
                    _migrate_to_v14(conn)
                if current_version < 15:
                    _migrate_to_v15(conn)
                if current_version < 16:
                    _migrate_to_v16(conn)
                if current_version < 17:
                    _migrate_to_v17(conn)

            _set_schema_version(conn, SCHEMA_VERSION)

        # Safety: ensure tables exist even if version was already bumped
        _migrate_to_v15(conn)
        _migrate_to_v17(conn)


def _migrate_to_v11(conn: ConnectionWrapper):
    """Migrate to v11: rename token columns to usage_ prefix, add cache/backend columns."""
    columns = _get_table_columns(conn, "conversations")

    # Skip if already migrated
    if "usage_input_tokens" in columns:
        return

    has_old_columns = "input_tokens" in columns

    if conn.is_postgres:
        # PostgreSQL supports RENAME COLUMN
        if has_old_columns:
            conn.execute("ALTER TABLE conversations RENAME COLUMN input_tokens TO usage_input_tokens")
            conn.execute("ALTER TABLE conversations RENAME COLUMN output_tokens TO usage_output_tokens")
        else:
            conn.execute("ALTER TABLE conversations ADD COLUMN usage_input_tokens INTEGER DEFAULT 0")
            conn.execute("ALTER TABLE conversations ADD COLUMN usage_output_tokens INTEGER DEFAULT 0")

        conn.execute("ALTER TABLE conversations ADD COLUMN usage_cache_creation_tokens INTEGER DEFAULT 0")
        conn.execute("ALTER TABLE conversations ADD COLUMN usage_cache_read_tokens INTEGER DEFAULT 0")
        conn.execute("ALTER TABLE conversations ADD COLUMN usage_backend TEXT")
        conn.execute("ALTER TABLE conversations ADD COLUMN usage_extra TEXT")
    else:
        # SQLite: RENAME COLUMN supported since 3.25.0
        if has_old_columns and sqlite3.sqlite_version_info >= (3, 25, 0):
            conn.execute("ALTER TABLE conversations RENAME COLUMN input_tokens TO usage_input_tokens")
            conn.execute("ALTER TABLE conversations RENAME COLUMN output_tokens TO usage_output_tokens")
        elif has_old_columns:
            # Old SQLite: add new columns and copy data
            conn.execute("ALTER TABLE conversations ADD COLUMN usage_input_tokens INTEGER DEFAULT 0")
            conn.execute("ALTER TABLE conversations ADD COLUMN usage_output_tokens INTEGER DEFAULT 0")
            conn.execute("UPDATE conversations SET usage_input_tokens = input_tokens, usage_output_tokens = output_tokens")
        else:
            conn.execute("ALTER TABLE conversations ADD COLUMN usage_input_tokens INTEGER DEFAULT 0")
            conn.execute("ALTER TABLE conversations ADD COLUMN usage_output_tokens INTEGER DEFAULT 0")

        conn.execute("ALTER TABLE conversations ADD COLUMN usage_cache_creation_tokens INTEGER DEFAULT 0")
        conn.execute("ALTER TABLE conversations ADD COLUMN usage_cache_read_tokens INTEGER DEFAULT 0")
        conn.execute("ALTER TABLE conversations ADD COLUMN usage_backend TEXT")
        conn.execute("ALTER TABLE conversations ADD COLUMN usage_extra TEXT")

    # Ensure schema_version table exists for older databases
    if conn.is_postgres:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)")
    else:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)")


def _migrate_to_v12(conn: ConnectionWrapper):
    """Migrate to v12: add uploaded_files table for chat file uploads."""
    serial_pk = "SERIAL PRIMARY KEY" if conn.is_postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"

    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS uploaded_files (
            id {serial_pk},
            conversation_id TEXT REFERENCES conversations(id) ON DELETE CASCADE,
            user_id TEXT,
            original_filename TEXT NOT NULL,
            stored_filename TEXT NOT NULL,
            storage_path TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            mime_type TEXT,
            sha256_hash TEXT NOT NULL,
            is_text BOOLEAN DEFAULT FALSE,
            av_scanned BOOLEAN DEFAULT FALSE,
            av_clean BOOLEAN,
            created_at TEXT NOT NULL
        )
    """)

    conn.execute("CREATE INDEX IF NOT EXISTS idx_uploaded_files_conversation ON uploaded_files(conversation_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_uploaded_files_hash ON uploaded_files(sha256_hash)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_uploaded_files_user ON uploaded_files(user_id)")


def _migrate_to_v13(conn: ConnectionWrapper):
    """Migrate to v13: add pinned_at and pinned_label columns to conversations."""
    columns = _get_table_columns(conn, "conversations")
    if "pinned_at" not in columns:
        conn.execute("ALTER TABLE conversations ADD COLUMN pinned_at TEXT")
    if "pinned_label" not in columns:
        conn.execute("ALTER TABLE conversations ADD COLUMN pinned_label TEXT")


def _migrate_to_v14(conn: ConnectionWrapper):
    """Migrate to v14: add notion_url column to reports."""
    columns = _get_table_columns(conn, "reports")
    if "notion_url" not in columns:
        conn.execute("ALTER TABLE reports ADD COLUMN notion_url TEXT")


def _migrate_to_v15(conn: ConnectionWrapper):
    """Migrate to v15: add cron_runs table for scheduled task history."""
    serial_pk = "SERIAL PRIMARY KEY" if conn.is_postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"

    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS cron_runs (
            id {serial_pk},
            app_slug TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL,
            output TEXT,
            duration_ms INTEGER,
            trigger TEXT NOT NULL DEFAULT 'scheduled'
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cron_runs_slug_started ON cron_runs(app_slug, started_at DESC)")


def _migrate_to_v16(conn: ConnectionWrapper):
    """Migrate to v16: add needs_response column for robust stream completion tracking."""
    columns = _get_table_columns(conn, "conversations")
    if "needs_response" not in columns:
        conn.execute("ALTER TABLE conversations ADD COLUMN needs_response INTEGER DEFAULT 0")


def _migrate_to_v17(conn: ConnectionWrapper):
    """Migrate to v17: add pinned_items table for generic pinning (conversations, reports, apps)."""
    serial_pk = "SERIAL PRIMARY KEY" if conn.is_postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"

    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS pinned_items (
            id {serial_pk},
            item_type TEXT NOT NULL,
            item_id TEXT NOT NULL,
            label TEXT,
            pinned_at TEXT NOT NULL,
            UNIQUE(item_type, item_id)
        )
    """)

    # Migrate existing pinned conversations
    conn.execute("""
        INSERT OR IGNORE INTO pinned_items (item_type, item_id, label, pinned_at)
        SELECT 'conversation', id, pinned_label, pinned_at
        FROM conversations WHERE pinned_at IS NOT NULL
    """)


def _create_schema(conn: ConnectionWrapper):
    """Create the complete database schema."""
    # Use SERIAL for PostgreSQL, INTEGER PRIMARY KEY AUTOINCREMENT for SQLite
    serial_pk = "SERIAL PRIMARY KEY" if conn.is_postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"

    conn.executescript(f"""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY
        );

        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            title TEXT,
            session_id TEXT,
            conv_type TEXT DEFAULT 'exploration',
            file_path TEXT,
            status TEXT DEFAULT 'active',
            pr_url TEXT,
            forked_from TEXT,
            usage_input_tokens INTEGER DEFAULT 0,
            usage_output_tokens INTEGER DEFAULT 0,
            usage_cache_creation_tokens INTEGER DEFAULT 0,
            usage_cache_read_tokens INTEGER DEFAULT 0,
            usage_backend TEXT,
            usage_extra TEXT,
            pinned_at TEXT,
            pinned_label TEXT,
            needs_response INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS messages (
            id {serial_pk},
            conversation_id TEXT NOT NULL,
            type TEXT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            raw_events TEXT,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        );

        CREATE TABLE IF NOT EXISTS reports (
            id {serial_pk},
            title TEXT NOT NULL,
            content TEXT,
            website TEXT,
            category TEXT,
            tags TEXT,
            original_query TEXT,
            source_conversation_id TEXT,
            user_id TEXT,
            version INTEGER DEFAULT 1,
            archived INTEGER DEFAULT 0,
            notion_url TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            conversation_id TEXT,
            message_id INTEGER
        );

        CREATE TABLE IF NOT EXISTS tags (
            id {serial_pk},
            name TEXT NOT NULL UNIQUE,
            type TEXT NOT NULL,
            label TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS conversation_tags (
            conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
            PRIMARY KEY (conversation_id, tag_id)
        );

        CREATE TABLE IF NOT EXISTS report_tags (
            report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
            tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
            PRIMARY KEY (report_id, tag_id)
        );

        CREATE TABLE IF NOT EXISTS uploaded_files (
            id {serial_pk},
            conversation_id TEXT REFERENCES conversations(id) ON DELETE CASCADE,
            user_id TEXT,
            original_filename TEXT NOT NULL,
            stored_filename TEXT NOT NULL,
            storage_path TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            mime_type TEXT,
            sha256_hash TEXT NOT NULL,
            is_text BOOLEAN DEFAULT FALSE,
            av_scanned BOOLEAN DEFAULT FALSE,
            av_clean BOOLEAN,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);
        CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations(updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_conversations_type_status ON conversations(conv_type, status);
        CREATE INDEX IF NOT EXISTS idx_reports_updated ON reports(updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_tags_type ON tags(type);
        CREATE INDEX IF NOT EXISTS idx_conversation_tags_conv ON conversation_tags(conversation_id);
        CREATE INDEX IF NOT EXISTS idx_conversation_tags_tag ON conversation_tags(tag_id);
        CREATE INDEX IF NOT EXISTS idx_report_tags_report ON report_tags(report_id);
        CREATE INDEX IF NOT EXISTS idx_report_tags_tag ON report_tags(tag_id);
        CREATE TABLE IF NOT EXISTS cron_runs (
            id {serial_pk},
            app_slug TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL,
            output TEXT,
            duration_ms INTEGER,
            trigger TEXT NOT NULL DEFAULT 'scheduled'
        );

        CREATE TABLE IF NOT EXISTS pinned_items (
            id {serial_pk},
            item_type TEXT NOT NULL,
            item_id TEXT NOT NULL,
            label TEXT,
            pinned_at TEXT NOT NULL,
            UNIQUE(item_type, item_id)
        );

        CREATE INDEX IF NOT EXISTS idx_uploaded_files_conversation ON uploaded_files(conversation_id);
        CREATE INDEX IF NOT EXISTS idx_uploaded_files_hash ON uploaded_files(sha256_hash);
        CREATE INDEX IF NOT EXISTS idx_uploaded_files_user ON uploaded_files(user_id);
        CREATE INDEX IF NOT EXISTS idx_cron_runs_slug_started ON cron_runs(app_slug, started_at DESC);
    """)


# Tag taxonomy
TAGS = [
    # Produits (9)
    ("emplois", "product", "Emplois"),
    ("dora", "product", "Dora"),
    ("marche", "product", "Marché"),
    ("communaute", "product", "Communauté"),
    ("pilotage", "product", "Pilotage"),
    ("plateforme", "product", "Plateforme"),
    ("rdv-insertion", "product", "RDV-Insertion"),
    ("mon-recap", "product", "Mon Récap"),
    ("multi", "product", "Multi-produits"),
    # Sources (3)
    ("matomo", "source", "Matomo"),
    ("stats", "source", "Metabase stats"),
    ("datalake", "source", "Metabase datalake"),
    # Thèmes - Acteurs (6)
    ("candidats", "theme", "Candidats"),
    ("prescripteurs", "theme", "Prescripteurs"),
    ("employeurs", "theme", "Employeurs"),
    ("structures", "theme", "Structures / SIAE"),
    ("acheteurs", "theme", "Acheteurs"),
    ("fournisseurs", "theme", "Fournisseurs"),
    # Thèmes - Concepts métier (5)
    ("iae", "theme", "IAE"),
    ("orientation", "theme", "Orientation"),
    ("depot-de-besoin", "theme", "Dépôt de besoin"),
    ("demande-de-devis", "theme", "Demande de devis"),
    ("commandes", "theme", "Commandes"),
    # Thèmes - Métriques (4)
    ("trafic", "theme", "Trafic"),
    ("conversions", "theme", "Conversions"),
    ("retention", "theme", "Rétention"),
    ("geographique", "theme", "Géographique"),
    # Types de demande (4)
    ("extraction", "type_demande", "Extraction"),
    ("analyse", "type_demande", "Analyse"),
    ("appli", "type_demande", "Appli"),
    ("meta", "type_demande", "Meta"),
]


def _seed_tags(conn: ConnectionWrapper):
    """Seed the tags table with taxonomy."""
    if conn.is_postgres:
        conn.executemany(
            "INSERT INTO tags (name, type, label) VALUES (%s, %s, %s) ON CONFLICT (name) DO NOTHING",
            TAGS
        )
    else:
        conn.executemany(
            "INSERT OR IGNORE INTO tags (name, type, label) VALUES (?, ?, ?)",
            TAGS
        )


# =============================================================================
# Data Classes
# =============================================================================

from dataclasses import dataclass, field


@dataclass
class Tag:
    """A tag for categorizing conversations and reports."""
    id: Optional[int] = None
    name: str = ""
    type: str = ""  # product | theme | source | type_demande
    label: str = ""
    count: int = 0  # Number of conversations/reports with this tag


@dataclass
class PinnedItem:
    """A pinned item (conversation, report, or app)."""
    id: Optional[int] = None
    item_type: str = ""  # conversation | report | app
    item_id: str = ""
    label: str = ""
    pinned_at: Optional[datetime] = None


@dataclass
class UploadedFile:
    """A file uploaded to a conversation."""
    id: Optional[int] = None
    conversation_id: Optional[str] = None
    user_id: Optional[str] = None
    original_filename: str = ""
    stored_filename: str = ""
    storage_path: str = ""
    file_size: int = 0
    mime_type: Optional[str] = None
    sha256_hash: str = ""
    is_text: bool = False
    av_scanned: bool = False
    av_clean: Optional[bool] = None
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "user_id": self.user_id,
            "original_filename": self.original_filename,
            "stored_filename": self.stored_filename,
            "storage_path": self.storage_path,
            "file_size": self.file_size,
            "mime_type": self.mime_type,
            "sha256_hash": self.sha256_hash,
            "is_text": self.is_text,
            "av_scanned": self.av_scanned,
            "av_clean": self.av_clean,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class Message:
    """A single message in a conversation."""
    id: Optional[int] = None
    conversation_id: Optional[str] = None
    type: str = "user"  # user, assistant, tool_use, tool_result
    content: str = ""
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class Report:
    """A report with its content."""
    id: Optional[int] = None
    title: str = ""
    content: Optional[str] = None  # the actual report markdown
    website: Optional[str] = None
    category: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    original_query: Optional[str] = None
    source_conversation_id: Optional[str] = None  # where it came from
    user_id: Optional[str] = None
    archived: bool = False
    notion_url: Optional[str] = None
    version: int = 1
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    # Deprecated - keep for backwards compat during migration
    conversation_id: Optional[str] = None
    message_id: Optional[int] = None


@dataclass
class Conversation:
    """A conversation with its messages and optional report."""
    id: str = ""
    user_id: Optional[str] = None
    title: Optional[str] = None
    session_id: Optional[str] = None
    conv_type: str = "exploration"  # 'exploration' or 'knowledge'
    file_path: Optional[str] = None  # for knowledge conversations
    status: str = "active"  # 'active', 'committed', 'abandoned'
    pr_url: Optional[str] = None  # GitHub PR URL for knowledge conversations
    forked_from: Optional[str] = None  # ID of source conversation if forked
    messages: list[Message] = field(default_factory=list)
    report: Optional[Report] = None
    # Usage tracking (cumulative per conversation)
    usage_input_tokens: int = 0
    usage_output_tokens: int = 0
    usage_cache_creation_tokens: int = 0
    usage_cache_read_tokens: int = 0
    usage_backend: Optional[str] = None  # 'cli', 'sdk', ...
    usage_extra: Optional[dict] = None  # web_search_requests, service_tier, ...
    pinned_at: Optional[datetime] = None  # NULL = not pinned; timestamp = pinned
    pinned_label: Optional[str] = None  # custom label shown in sidebar when pinned
    needs_response: bool = False  # True when user sent a message and agent hasn't finished
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    @property
    def has_report(self) -> bool:
        return self.report is not None

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "title": self.title,
            "session_id": self.session_id,
            "conv_type": self.conv_type,
            "file_path": self.file_path,
            "status": self.status,
            "pr_url": self.pr_url,
            "has_report": self.has_report,
            "usage_input_tokens": self.usage_input_tokens,
            "usage_output_tokens": self.usage_output_tokens,
            "usage_cache_creation_tokens": self.usage_cache_creation_tokens,
            "usage_cache_read_tokens": self.usage_cache_read_tokens,
            "usage_backend": self.usage_backend,
            "usage_extra": self.usage_extra,
            "pinned_at": self.pinned_at.isoformat() if self.pinned_at else None,
            "pinned_label": self.pinned_label,
            "messages": [
                {
                    "id": m.id,
                    "type": m.type,
                    "content": m.content,
                    "created_at": m.created_at.isoformat(),
                }
                for m in self.messages
            ],
            "report": {
                "id": self.report.id,
                "title": self.report.title,
                "website": self.report.website,
                "category": self.report.category,
                "tags": self.report.tags,
                "version": self.report.version,
            } if self.report else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


# =============================================================================
# Store
# =============================================================================

class ConversationStore:
    """SQLite-backed conversation and report store."""

    def __init__(self):
        init_db()

    # -------------------------------------------------------------------------
    # Conversations
    # -------------------------------------------------------------------------

    def create_conversation(
        self,
        user_id: Optional[str] = None,
        conv_type: str = "exploration",
        file_path: Optional[str] = None,
    ) -> Conversation:
        """Create a new conversation."""
        conv = Conversation(
            id=str(uuid.uuid4()),
            user_id=user_id,
            conv_type=conv_type,
            file_path=file_path,
        )

        with get_db() as conn:
            conn.execute(
                """INSERT INTO conversations (id, user_id, title, session_id, conv_type, file_path, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (conv.id, conv.user_id, conv.title, conv.session_id, conv.conv_type, conv.file_path, conv.status,
                 conv.created_at.isoformat(), conv.updated_at.isoformat())
            )

        return conv

    def get_conversation(self, conv_id: str, include_messages: bool = True, user_id: Optional[str] = None) -> Optional[Conversation]:
        """Get a conversation by ID. Optionally filter by user_id for access control."""
        with get_db() as conn:
            if user_id:
                row = conn.execute(
                    "SELECT * FROM conversations WHERE id = ? AND user_id = ?", (conv_id, user_id)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM conversations WHERE id = ?", (conv_id,)
                ).fetchone()

            if not row:
                return None

            messages = []
            if include_messages:
                msg_rows = conn.execute(
                    """SELECT id, conversation_id, COALESCE(type, role) as type, content, timestamp
                       FROM messages WHERE conversation_id = ? ORDER BY timestamp""",
                    (conv_id,)
                ).fetchall()

                messages = [
                    Message(
                        id=m["id"],
                        conversation_id=m["conversation_id"],
                        type=m["type"],
                        content=m["content"],
                        created_at=datetime.fromisoformat(m["timestamp"]),
                    )
                    for m in msg_rows
                ]

            # Load report if exists
            report_row = conn.execute(
                "SELECT * FROM reports WHERE conversation_id = ?", (conv_id,)
            ).fetchone()

            report = None
            if report_row:
                report = Report(
                    id=report_row["id"],
                    title=report_row["title"],
                    # Don't load content when loading via conversation
                    website=report_row["website"],
                    category=report_row["category"],
                    tags=json.loads(report_row["tags"]) if report_row["tags"] else [],
                    original_query=report_row["original_query"],
                    source_conversation_id=report_row["source_conversation_id"] if "source_conversation_id" in report_row.keys() else None,
                    user_id=report_row["user_id"] if "user_id" in report_row.keys() else None,
                    version=report_row["version"],
                    created_at=datetime.fromisoformat(report_row["created_at"]),
                    updated_at=datetime.fromisoformat(report_row["updated_at"]),
                    # Legacy fields
                    conversation_id=report_row["conversation_id"],
                    message_id=report_row["message_id"],
                )

            # Parse usage_extra JSON if present
            usage_extra = None
            if "usage_extra" in row.keys() and row["usage_extra"]:
                usage_extra = json.loads(row["usage_extra"])

            return Conversation(
                id=row["id"],
                user_id=row["user_id"],
                title=row["title"],
                session_id=row["session_id"],
                conv_type=row["conv_type"] or "exploration",
                file_path=row["file_path"],
                status=row["status"] or "active",
                pr_url=row["pr_url"] if "pr_url" in row.keys() else None,
                forked_from=row["forked_from"] if "forked_from" in row.keys() else None,
                messages=messages,
                report=report,
                usage_input_tokens=row["usage_input_tokens"] if "usage_input_tokens" in row.keys() else 0,
                usage_output_tokens=row["usage_output_tokens"] if "usage_output_tokens" in row.keys() else 0,
                usage_cache_creation_tokens=row["usage_cache_creation_tokens"] if "usage_cache_creation_tokens" in row.keys() else 0,
                usage_cache_read_tokens=row["usage_cache_read_tokens"] if "usage_cache_read_tokens" in row.keys() else 0,
                usage_backend=row["usage_backend"] if "usage_backend" in row.keys() else None,
                usage_extra=usage_extra,
                pinned_at=datetime.fromisoformat(row["pinned_at"]) if "pinned_at" in row.keys() and row["pinned_at"] else None,
                pinned_label=row["pinned_label"] if "pinned_label" in row.keys() else None,
                needs_response=bool(row["needs_response"]) if "needs_response" in row.keys() and row["needs_response"] else False,
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )

    def fork_conversation(self, source_conv_id: str, new_user_id: str) -> Optional[Conversation]:
        """
        Deep copy a conversation for a new user.

        Creates a new conversation with all messages copied. The new conversation
        has a new ID, belongs to new_user_id, and tracks its origin via forked_from.
        Reports are NOT copied (they belong to the original conversation).
        """
        # Get source conversation with all messages
        source = self.get_conversation(source_conv_id, include_messages=True)
        if not source:
            return None

        now = datetime.now()
        new_id = str(uuid.uuid4())

        with get_db() as conn:
            # Create the new conversation
            conn.execute(
                """INSERT INTO conversations
                   (id, user_id, title, session_id, conv_type, file_path, status, forked_from, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    new_id,
                    new_user_id,
                    source.title,
                    None,  # New session_id (will be set when agent runs)
                    source.conv_type,
                    source.file_path,
                    "active",  # Reset status
                    source_conv_id,  # Track fork origin
                    now.isoformat(),
                    now.isoformat(),
                )
            )

            # Deep copy all messages
            for msg in source.messages:
                conn.execute(
                    """INSERT INTO messages (conversation_id, type, role, content, timestamp)
                       VALUES (?, ?, ?, ?, ?)""",
                    (new_id, msg.type, msg.type, msg.content, msg.created_at.isoformat())
                )

        # Return the new conversation
        return self.get_conversation(new_id, include_messages=True)

    def list_conversations(
        self, user_id: Optional[str] = None, limit: int = 50, conv_type: Optional[str] = None,
        exclude_report_containers: bool = True
    ) -> list[Conversation]:
        """List recent conversations with report info.

        By default, excludes conversations that were created only to contain a report
        (identified by having a report linked via conversation_id).
        """
        with get_db() as conn:
            conditions = []
            params = []

            if user_id:
                conditions.append("c.user_id = ?")
                params.append(user_id)

            if conv_type:
                conditions.append("c.conv_type = ?")
                params.append(conv_type)
            else:
                # By default, only show exploration conversations
                conditions.append("(c.conv_type = 'exploration' OR c.conv_type IS NULL)")

            if exclude_report_containers:
                # Exclude conversations that exist only to contain a report
                conditions.append("r.id IS NULL")

            where = "WHERE " + " AND ".join(conditions) if conditions else ""
            params.append(limit)

            query = f"""
                SELECT c.*, r.id as report_id, r.title as report_title
                FROM conversations c
                LEFT JOIN reports r ON r.conversation_id = c.id
                {where}
                ORDER BY c.updated_at DESC
                LIMIT ?
            """

            rows = conn.execute(query, params).fetchall()

            return [
                Conversation(
                    id=row["id"],
                    user_id=row["user_id"],
                    title=row["title"],
                    session_id=row["session_id"],
                    conv_type=row["conv_type"] or "exploration",
                    file_path=row["file_path"],
                    status=row["status"] or "active",
                    messages=[],
                    report=Report(id=row["report_id"], title=row["report_title"] or "") if row["report_id"] else None,
                    created_at=datetime.fromisoformat(row["created_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"]),
                )
                for row in rows
            ]

    # --- Generic pinning (pinned_items table) ---

    def pin_item(self, item_type: str, item_id: str, label: str) -> bool:
        """Pin an item (conversation, report, or app)."""
        with get_db() as conn:
            conn.execute(
                """INSERT INTO pinned_items (item_type, item_id, label, pinned_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(item_type, item_id) DO UPDATE SET label = ?, pinned_at = ?""",
                (item_type, str(item_id), label, datetime.now().isoformat(),
                 label, datetime.now().isoformat())
            )
            return True

    def unpin_item(self, item_type: str, item_id: str) -> bool:
        """Unpin an item."""
        with get_db() as conn:
            cursor = conn.execute(
                "DELETE FROM pinned_items WHERE item_type = ? AND item_id = ?",
                (item_type, str(item_id))
            )
            return cursor.rowcount > 0

    def list_pinned_items(self, item_type: Optional[str] = None) -> list[PinnedItem]:
        """List pinned items, optionally filtered by type."""
        with get_db() as conn:
            if item_type:
                rows = conn.execute(
                    "SELECT * FROM pinned_items WHERE item_type = ? ORDER BY pinned_at",
                    (item_type,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM pinned_items ORDER BY pinned_at"
                ).fetchall()
            return [
                PinnedItem(
                    id=row["id"],
                    item_type=row["item_type"],
                    item_id=row["item_id"],
                    label=row["label"],
                    pinned_at=datetime.fromisoformat(row["pinned_at"]),
                )
                for row in rows
            ]

    def get_pinned_ids(self) -> set[tuple[str, str]]:
        """Get set of (item_type, item_id) for all pinned items."""
        with get_db() as conn:
            rows = conn.execute("SELECT item_type, item_id FROM pinned_items").fetchall()
            return {(row["item_type"], row["item_id"]) for row in rows}

    # Backwards-compatible wrappers
    def pin_conversation(self, conv_id: str, label: str) -> bool:
        return self.pin_item("conversation", conv_id, label)

    def unpin_conversation(self, conv_id: str) -> bool:
        return self.unpin_item("conversation", conv_id)

    def list_pinned_conversations(self) -> list[Conversation]:
        """List pinned conversations (legacy wrapper)."""
        with get_db() as conn:
            rows = conn.execute(
                """SELECT c.* FROM conversations c
                   JOIN pinned_items p ON p.item_id = c.id AND p.item_type = 'conversation'
                   ORDER BY p.pinned_at""",
            ).fetchall()
            return [
                Conversation(
                    id=row["id"],
                    user_id=row["user_id"],
                    title=row["title"],
                    pinned_at=datetime.fromisoformat(row["pinned_at"]) if row["pinned_at"] else None,
                    pinned_label=row["pinned_label"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"]),
                )
                for row in rows
            ]

    def get_active_knowledge_conversation(self, file_path: str, user_id: Optional[str] = None) -> Optional[Conversation]:
        """Get active knowledge conversation for a file, optionally filtered by user."""
        with get_db() as conn:
            if user_id:
                row = conn.execute(
                    """SELECT * FROM conversations
                       WHERE conv_type = 'knowledge' AND file_path = ? AND status = 'active' AND user_id = ?
                       ORDER BY updated_at DESC LIMIT 1""",
                    (file_path, user_id)
                ).fetchone()
            else:
                row = conn.execute(
                    """SELECT * FROM conversations
                       WHERE conv_type = 'knowledge' AND file_path = ? AND status = 'active'
                       ORDER BY updated_at DESC LIMIT 1""",
                    (file_path,)
                ).fetchone()

            if not row:
                return None

            return Conversation(
                id=row["id"],
                user_id=row["user_id"],
                title=row["title"],
                session_id=row["session_id"],
                conv_type=row["conv_type"],
                file_path=row["file_path"],
                status=row["status"],
                messages=[],
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )

    def list_active_knowledge_conversations(self) -> list[Conversation]:
        """List all active knowledge conversations."""
        with get_db() as conn:
            rows = conn.execute(
                """SELECT * FROM conversations
                   WHERE conv_type = 'knowledge' AND status = 'active'
                   ORDER BY updated_at DESC"""
            ).fetchall()

            return [
                Conversation(
                    id=row["id"],
                    user_id=row["user_id"],
                    title=row["title"],
                    session_id=row["session_id"],
                    conv_type=row["conv_type"],
                    file_path=row["file_path"],
                    status=row["status"],
                    messages=[],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"]),
                )
                for row in rows
            ]

    def update_conversation(self, conv_id: str, **kwargs) -> bool:
        """Update conversation fields."""
        allowed = {"title", "session_id", "user_id", "status", "pr_url", "needs_response"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return False

        updates["updated_at"] = datetime.now().isoformat()

        set_clause, values = _build_update_clause(updates, VALID_CONVERSATION_COLUMNS)
        values.append(conv_id)

        with get_db() as conn:
            cursor = conn.execute(
                f"UPDATE conversations SET {set_clause} WHERE id = ?",
                values
            )
            return cursor.rowcount > 0

    def update_conversation_usage(
        self,
        conv_id: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0,
        backend: Optional[str] = None,
        extra: Optional[dict] = None,
    ) -> bool:
        """Set usage data on a conversation (overwrites existing values)."""
        extra_json = json.dumps(extra) if extra else None
        with get_db() as conn:
            cursor = conn.execute(
                """UPDATE conversations
                   SET usage_input_tokens = ?,
                       usage_output_tokens = ?,
                       usage_cache_creation_tokens = ?,
                       usage_cache_read_tokens = ?,
                       usage_backend = COALESCE(?, usage_backend),
                       usage_extra = ?,
                       updated_at = ?
                   WHERE id = ?""",
                (input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
                 backend, extra_json, datetime.now().isoformat(), conv_id)
            )
            return cursor.rowcount > 0

    def accumulate_usage(
        self,
        conv_id: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0,
        backend: Optional[str] = None,
        extra: Optional[dict] = None,
    ) -> bool:
        """Add usage to existing counts (for incremental updates).

        Note: extra dict is replaced, not merged.
        """
        extra_json = json.dumps(extra) if extra else None
        with get_db() as conn:
            cursor = conn.execute(
                """UPDATE conversations
                   SET usage_input_tokens = COALESCE(usage_input_tokens, 0) + ?,
                       usage_output_tokens = COALESCE(usage_output_tokens, 0) + ?,
                       usage_cache_creation_tokens = COALESCE(usage_cache_creation_tokens, 0) + ?,
                       usage_cache_read_tokens = COALESCE(usage_cache_read_tokens, 0) + ?,
                       usage_backend = COALESCE(?, usage_backend),
                       usage_extra = COALESCE(?, usage_extra),
                       updated_at = ?
                   WHERE id = ?""",
                (input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
                 backend, extra_json, datetime.now().isoformat(), conv_id)
            )
            return cursor.rowcount > 0

    def delete_conversation(self, conv_id: str) -> bool:
        """Delete a conversation and all related data."""
        with get_db() as conn:
            conn.execute("DELETE FROM reports WHERE conversation_id = ?", (conv_id,))
            conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
            cursor = conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
            return cursor.rowcount > 0

    # -------------------------------------------------------------------------
    # Messages
    # -------------------------------------------------------------------------

    def add_message(
        self,
        conv_id: str,
        type: str,
        content: str,
    ) -> Optional[Message]:
        """Add a message to a conversation. Returns the message with ID."""
        msg = Message(
            conversation_id=conv_id,
            type=type,
            content=content,
        )

        with get_db() as conn:
            # Check conversation exists
            row = conn.execute(
                "SELECT id, title FROM conversations WHERE id = ?", (conv_id,)
            ).fetchone()
            if not row:
                return None

            # Insert message
            msg.id = conn.insert_and_get_id(
                """INSERT INTO messages (conversation_id, type, role, content, timestamp)
                   VALUES (?, ?, ?, ?, ?)""",
                (conv_id, type, type, content, msg.created_at.isoformat())
            )

            # Update conversation timestamp
            now = datetime.now().isoformat()

            # Auto-generate title from first user message
            if row["title"] is None and type == "user":
                title = content[:80] + ("..." if len(content) > 80 else "")
                conn.execute(
                    "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                    (title, now, conv_id)
                )
            else:
                conn.execute(
                    "UPDATE conversations SET updated_at = ? WHERE id = ?",
                    (now, conv_id)
                )

        return msg

    def update_message(self, message_id: int, content: str) -> bool:
        """Update a message's content. Returns True if updated."""
        with get_db() as conn:
            cursor = conn.execute(
                "UPDATE messages SET content = ? WHERE id = ?",
                (content, message_id)
            )
            return cursor.rowcount > 0

    def get_messages(
        self,
        conv_id: str,
        types: Optional[list[str]] = None,
        limit: Optional[int] = None,
    ) -> list[Message]:
        """Get messages for a conversation, optionally filtered by type."""
        with get_db() as conn:
            query = """SELECT id, conversation_id, COALESCE(type, role) as type, content, timestamp
                       FROM messages WHERE conversation_id = ?"""
            params = [conv_id]

            if types:
                placeholders = ",".join("?" * len(types))
                query += f" AND COALESCE(type, role) IN ({placeholders})"
                params.extend(types)

            query += " ORDER BY timestamp"

            if limit:
                query += " LIMIT ?"
                params.append(limit)

            rows = conn.execute(query, params).fetchall()

            return [
                Message(
                    id=m["id"],
                    conversation_id=m["conversation_id"],
                    type=m["type"],
                    content=m["content"],
                    created_at=datetime.fromisoformat(m["timestamp"]),
                )
                for m in rows
            ]

    # -------------------------------------------------------------------------
    # Reports
    # -------------------------------------------------------------------------

    def create_report(
        self,
        title: str,
        content: str,
        website: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[list[str]] = None,
        original_query: Optional[str] = None,
        source_conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Optional[Report]:
        """Create a report with content."""
        report = Report(
            title=title,
            content=content,
            website=website,
            category=category,
            tags=tags or [],
            original_query=original_query,
            source_conversation_id=source_conversation_id,
            user_id=user_id,
        )

        with get_db() as conn:
            report.id = conn.insert_and_get_id(
                """INSERT INTO reports
                   (title, content, website, category, tags, original_query,
                    source_conversation_id, user_id, version, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (title, content, website, category,
                 json.dumps(tags) if tags else None, original_query,
                 source_conversation_id, user_id,
                 1, report.created_at.isoformat(), report.updated_at.isoformat())
            )

        return report

    def get_report(self, report_id: int) -> Optional[Report]:
        """Get a report by ID."""
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM reports WHERE id = ?", (report_id,)
            ).fetchone()

            if not row:
                return None

            # Use content column if available, fall back to message lookup
            content = row["content"] if "content" in row.keys() else None
            if not content and row["message_id"]:
                # Legacy: fetch from messages
                msg = conn.execute(
                    "SELECT content FROM messages WHERE id = ?",
                    (row["message_id"],)
                ).fetchone()
                content = msg["content"] if msg else None

            return Report(
                id=row["id"],
                title=row["title"],
                content=content,
                website=row["website"],
                category=row["category"],
                tags=json.loads(row["tags"]) if row["tags"] else [],
                original_query=row["original_query"],
                source_conversation_id=row["source_conversation_id"] if "source_conversation_id" in row.keys() else None,
                user_id=row["user_id"] if "user_id" in row.keys() else None,
                archived=bool(row["archived"]) if "archived" in row.keys() else False,
                notion_url=row["notion_url"] if "notion_url" in row.keys() else None,
                version=row["version"],
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
                # Legacy fields
                conversation_id=row["conversation_id"],
                message_id=row["message_id"],
            )

    def list_reports(
        self,
        website: Optional[str] = None,
        category: Optional[str] = None,
        include_archived: bool = False,
        limit: int = 50,
    ) -> list[Report]:
        """List reports with optional filtering. Excludes archived by default."""
        with get_db() as conn:
            query = "SELECT * FROM reports WHERE 1=1"
            params = []

            if not include_archived:
                query += " AND (archived = 0 OR archived IS NULL)"

            if website:
                query += " AND website = ?"
                params.append(website)

            if category:
                query += " AND category = ?"
                params.append(category)

            query += " ORDER BY updated_at DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()

            return [
                Report(
                    id=row["id"],
                    title=row["title"],
                    # Don't load content for listing (expensive)
                    website=row["website"],
                    category=row["category"],
                    tags=json.loads(row["tags"]) if row["tags"] else [],
                    original_query=row["original_query"],
                    source_conversation_id=row["source_conversation_id"] if "source_conversation_id" in row.keys() else None,
                    user_id=row["user_id"] if "user_id" in row.keys() else None,
                    archived=bool(row["archived"]) if "archived" in row.keys() else False,
                    version=row["version"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"]),
                    # Legacy fields
                    conversation_id=row["conversation_id"],
                    message_id=row["message_id"],
                )
                for row in rows
            ]

    def archive_report(self, report_id: int) -> bool:
        """Archive a report (soft delete)."""
        with get_db() as conn:
            cursor = conn.execute(
                "UPDATE reports SET archived = 1, updated_at = ? WHERE id = ?",
                (datetime.now().isoformat(), report_id)
            )
            return cursor.rowcount > 0

    def update_report(self, report_id: int, **kwargs) -> bool:
        """Update report fields, incrementing version."""
        allowed = {"title", "content", "website", "category", "tags", "original_query"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return False

        # Handle tags serialization
        if "tags" in updates:
            updates["tags"] = json.dumps(updates["tags"])

        updates["updated_at"] = datetime.now().isoformat()

        set_clause, values = _build_update_clause(updates, VALID_REPORT_COLUMNS)
        values.append(report_id)

        with get_db() as conn:
            # Increment version
            conn.execute(
                "UPDATE reports SET version = version + 1 WHERE id = ?",
                (report_id,)
            )

            cursor = conn.execute(
                f"UPDATE reports SET {set_clause} WHERE id = ?",
                values
            )
            return cursor.rowcount > 0

    def delete_report(self, report_id: int) -> bool:
        """Delete a report."""
        with get_db() as conn:
            cursor = conn.execute("DELETE FROM reports WHERE id = ?", (report_id,))
            return cursor.rowcount > 0

    # -------------------------------------------------------------------------
    # Tags
    # -------------------------------------------------------------------------

    def get_all_tags(self, tag_type: Optional[str] = None) -> list[Tag]:
        """Get all tags, optionally filtered by type."""
        with get_db() as conn:
            if tag_type:
                rows = conn.execute(
                    "SELECT * FROM tags WHERE type = ? ORDER BY label",
                    (tag_type,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM tags ORDER BY type, label"
                ).fetchall()

            return [
                Tag(id=row["id"], name=row["name"], type=row["type"], label=row["label"])
                for row in rows
            ]

    def get_tags_by_type(self) -> dict[str, list[Tag]]:
        """Get all tags grouped by type."""
        tags = self.get_all_tags()
        result: dict[str, list[Tag]] = {}
        for tag in tags:
            if tag.type not in result:
                result[tag.type] = []
            result[tag.type].append(tag)
        return result

    def get_used_conversation_tags_by_type(
        self,
        active_tag_names: Optional[list[str]] = None,
        user_id: Optional[str] = None
    ) -> dict[str, list[Tag]]:
        """Get tags that are actually used by conversations, grouped by type with counts.

        Only returns tags that have at least 1 conversation in the database.
        Counts show how many conversations match the current filters.
        Tags with 0 count (due to filters) should be disabled in the UI.
        """
        with get_db() as conn:
            # Build base query - only include tags used by at least one conversation
            params = []

            # Build conversation filter subquery
            conv_filter = "(c.conv_type = 'exploration' OR c.conv_type IS NULL)"

            if user_id:
                conv_filter += " AND c.user_id = ?"
                params.append(user_id)

            if active_tag_names:
                # Find conversations that have all active tags
                placeholders = ','.join('?' * len(active_tag_names))
                conv_filter += f"""
                    AND c.id IN (
                        SELECT conversation_id FROM conversation_tags ct2
                        JOIN tags t2 ON ct2.tag_id = t2.id
                        WHERE t2.name IN ({placeholders})
                        GROUP BY conversation_id
                        HAVING COUNT(DISTINCT t2.name) = ?
                    )
                """
                params.extend(active_tag_names)
                params.append(len(active_tag_names))

            query = f"""
                SELECT t.*,
                       COUNT(DISTINCT CASE
                           WHEN c.id IS NOT NULL AND {conv_filter} THEN c.id
                           ELSE NULL
                       END) as count
                FROM tags t
                INNER JOIN conversation_tags ct ON t.id = ct.tag_id
                INNER JOIN conversations c ON ct.conversation_id = c.id
                WHERE (c.conv_type = 'exploration' OR c.conv_type IS NULL)
                GROUP BY t.id
                HAVING COUNT(DISTINCT c.id) > 0
                ORDER BY t.type, t.label
            """

            rows = conn.execute(query, params).fetchall()

            result: dict[str, list[Tag]] = {}
            for row in rows:
                tag = Tag(
                    id=row["id"],
                    name=row["name"],
                    type=row["type"],
                    label=row["label"],
                    count=row["count"]
                )
                if tag.type not in result:
                    result[tag.type] = []
                result[tag.type].append(tag)
            return result

    def get_used_report_tags_by_type(self) -> dict[str, list[Tag]]:
        """Get tags that are actually used by non-archived reports, grouped by type."""
        with get_db() as conn:
            rows = conn.execute(
                """SELECT DISTINCT t.* FROM tags t
                   JOIN report_tags rt ON t.id = rt.tag_id
                   JOIN reports r ON rt.report_id = r.id
                   WHERE r.archived = 0 OR r.archived IS NULL
                   ORDER BY t.type, t.label"""
            ).fetchall()

            result: dict[str, list[Tag]] = {}
            for row in rows:
                tag = Tag(id=row["id"], name=row["name"], type=row["type"], label=row["label"])
                if tag.type not in result:
                    result[tag.type] = []
                result[tag.type].append(tag)
            return result

    def get_tag_by_name(self, name: str) -> Optional[Tag]:
        """Get a tag by its name."""
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM tags WHERE name = ?", (name,)
            ).fetchone()
            if row:
                return Tag(id=row["id"], name=row["name"], type=row["type"], label=row["label"])
            return None

    def set_conversation_tags(self, conv_id: str, tag_names: list[str], update_timestamp: bool = True) -> bool:
        """Set tags for a conversation (replaces existing tags)."""
        with get_db() as conn:
            # Clear existing tags
            conn.execute("DELETE FROM conversation_tags WHERE conversation_id = ?", (conv_id,))

            # Add new tags
            for tag_name in tag_names:
                tag_row = conn.execute(
                    "SELECT id FROM tags WHERE name = ?", (tag_name,)
                ).fetchone()
                if tag_row:
                    conn.insert_ignore(
                        "conversation_tags",
                        ["conversation_id", "tag_id"],
                        (conv_id, tag_row["id"])
                    )

            # Update conversation timestamp
            if update_timestamp:
                conn.execute(
                    "UPDATE conversations SET updated_at = ? WHERE id = ?",
                    (datetime.now().isoformat(), conv_id)
                )
            return True

    def get_conversation_tags(self, conv_id: str) -> list[Tag]:
        """Get tags for a conversation."""
        with get_db() as conn:
            rows = conn.execute(
                """SELECT t.* FROM tags t
                   JOIN conversation_tags ct ON t.id = ct.tag_id
                   WHERE ct.conversation_id = ?
                   ORDER BY t.type, t.label""",
                (conv_id,)
            ).fetchall()
            return [
                Tag(id=row["id"], name=row["name"], type=row["type"], label=row["label"])
                for row in rows
            ]

    def set_report_tags(self, report_id: int, tag_names: list[str], update_timestamp: bool = True) -> bool:
        """Set tags for a report (replaces existing tags)."""
        with get_db() as conn:
            # Clear existing tags
            conn.execute("DELETE FROM report_tags WHERE report_id = ?", (report_id,))

            # Add new tags
            for tag_name in tag_names:
                tag_row = conn.execute(
                    "SELECT id FROM tags WHERE name = ?", (tag_name,)
                ).fetchone()
                if tag_row:
                    conn.insert_ignore(
                        "report_tags",
                        ["report_id", "tag_id"],
                        (report_id, tag_row["id"])
                    )

            # Update report timestamp
            if update_timestamp:
                conn.execute(
                    "UPDATE reports SET updated_at = ? WHERE id = ?",
                    (datetime.now().isoformat(), report_id)
                )
            return True

    def get_report_tags(self, report_id: int) -> list[Tag]:
        """Get tags for a report."""
        with get_db() as conn:
            rows = conn.execute(
                """SELECT t.* FROM tags t
                   JOIN report_tags rt ON t.id = rt.tag_id
                   WHERE rt.report_id = ?
                   ORDER BY t.type, t.label""",
                (report_id,)
            ).fetchall()
            return [
                Tag(id=row["id"], name=row["name"], type=row["type"], label=row["label"])
                for row in rows
            ]

    def list_conversations_with_tags(
        self,
        user_id: Optional[str] = None,
        tag_names: Optional[list[str]] = None,
        limit: int = 100,
    ) -> list[tuple[Conversation, list[Tag]]]:
        """List conversations with their tags, optionally filtered."""
        with get_db() as conn:
            conditions = ["(c.conv_type = 'exploration' OR c.conv_type IS NULL)"]
            params: list = []

            if user_id:
                conditions.append("c.user_id = ?")
                params.append(user_id)

            # Filter by tags (AND logic - must have all specified tags)
            if tag_names:
                for tag_name in tag_names:
                    conditions.append("""
                        EXISTS (
                            SELECT 1 FROM conversation_tags ct
                            JOIN tags t ON ct.tag_id = t.id
                            WHERE ct.conversation_id = c.id AND t.name = ?
                        )
                    """)
                    params.append(tag_name)

            where = "WHERE " + " AND ".join(conditions) if conditions else ""
            params.append(limit)

            query = f"""
                SELECT c.*, r.id as report_id, r.title as report_title
                FROM conversations c
                LEFT JOIN reports r ON r.conversation_id = c.id AND r.id IS NULL
                {where}
                ORDER BY c.updated_at DESC
                LIMIT ?
            """

            rows = conn.execute(query, params).fetchall()

            results = []
            for row in rows:
                conv = Conversation(
                    id=row["id"],
                    user_id=row["user_id"],
                    title=row["title"],
                    session_id=row["session_id"],
                    conv_type=row["conv_type"] or "exploration",
                    file_path=row["file_path"],
                    status=row["status"] or "active",
                    messages=[],
                    report=Report(id=row["report_id"], title=row["report_title"] or "") if row["report_id"] else None,
                    created_at=datetime.fromisoformat(row["created_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"]),
                )
                tags = self.get_conversation_tags(row["id"])
                results.append((conv, tags))

            return results

    def list_reports_with_tags(
        self,
        tag_names: Optional[list[str]] = None,
        include_archived: bool = False,
        limit: int = 100,
    ) -> list[tuple[Report, list[Tag]]]:
        """List reports with their tags, optionally filtered."""
        with get_db() as conn:
            conditions: list[str] = []
            params: list = []

            if not include_archived:
                conditions.append("(r.archived = 0 OR r.archived IS NULL)")

            # Filter by tags (AND logic - must have all specified tags)
            if tag_names:
                for tag_name in tag_names:
                    conditions.append("""
                        EXISTS (
                            SELECT 1 FROM report_tags rt
                            JOIN tags t ON rt.tag_id = t.id
                            WHERE rt.report_id = r.id AND t.name = ?
                        )
                    """)
                    params.append(tag_name)

            where = "WHERE " + " AND ".join(conditions) if conditions else ""
            params.append(limit)

            query = f"""
                SELECT r.*
                FROM reports r
                {where}
                ORDER BY r.updated_at DESC
                LIMIT ?
            """

            rows = conn.execute(query, params).fetchall()

            results = []
            for row in rows:
                report = Report(
                    id=row["id"],
                    title=row["title"],
                    website=row["website"],
                    category=row["category"],
                    tags=json.loads(row["tags"]) if row["tags"] else [],
                    original_query=row["original_query"],
                    source_conversation_id=row["source_conversation_id"] if "source_conversation_id" in row.keys() else None,
                    user_id=row["user_id"] if "user_id" in row.keys() else None,
                    archived=bool(row["archived"]) if "archived" in row.keys() else False,
                    version=row["version"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"]),
                    conversation_id=row["conversation_id"],
                    message_id=row["message_id"],
                )
                tags = self.get_report_tags(row["id"])
                results.append((report, tags))

            return results

    # -------------------------------------------------------------------------
    # Uploaded Files
    # -------------------------------------------------------------------------

    def add_uploaded_file(
        self,
        conversation_id: Optional[str],
        user_id: Optional[str],
        original_filename: str,
        stored_filename: str,
        storage_path: str,
        file_size: int,
        sha256_hash: str,
        mime_type: Optional[str] = None,
        is_text: bool = False,
        av_scanned: bool = False,
        av_clean: Optional[bool] = None,
    ) -> Optional[UploadedFile]:
        """Add a new uploaded file record."""
        uploaded_file = UploadedFile(
            conversation_id=conversation_id,
            user_id=user_id,
            original_filename=original_filename,
            stored_filename=stored_filename,
            storage_path=storage_path,
            file_size=file_size,
            mime_type=mime_type,
            sha256_hash=sha256_hash,
            is_text=is_text,
            av_scanned=av_scanned,
            av_clean=av_clean,
        )

        with get_db() as conn:
            uploaded_file.id = conn.insert_and_get_id(
                """INSERT INTO uploaded_files
                   (conversation_id, user_id, original_filename, stored_filename,
                    storage_path, file_size, mime_type, sha256_hash, is_text,
                    av_scanned, av_clean, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (conversation_id, user_id, original_filename, stored_filename,
                 storage_path, file_size, mime_type, sha256_hash, is_text,
                 av_scanned, av_clean, uploaded_file.created_at.isoformat())
            )

        return uploaded_file

    def get_uploaded_file(self, file_id: int) -> Optional[UploadedFile]:
        """Get an uploaded file by ID."""
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM uploaded_files WHERE id = ?", (file_id,)
            ).fetchone()

            if not row:
                return None

            return UploadedFile(
                id=row["id"],
                conversation_id=row["conversation_id"],
                user_id=row["user_id"],
                original_filename=row["original_filename"],
                stored_filename=row["stored_filename"],
                storage_path=row["storage_path"],
                file_size=row["file_size"],
                mime_type=row["mime_type"],
                sha256_hash=row["sha256_hash"],
                is_text=bool(row["is_text"]),
                av_scanned=bool(row["av_scanned"]),
                av_clean=bool(row["av_clean"]) if row["av_clean"] is not None else None,
                created_at=datetime.fromisoformat(row["created_at"]),
            )

    def get_uploaded_file_by_hash(self, sha256_hash: str) -> Optional[UploadedFile]:
        """Get an uploaded file by its SHA256 hash (for deduplication)."""
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM uploaded_files WHERE sha256_hash = ? LIMIT 1", (sha256_hash,)
            ).fetchone()

            if not row:
                return None

            return UploadedFile(
                id=row["id"],
                conversation_id=row["conversation_id"],
                user_id=row["user_id"],
                original_filename=row["original_filename"],
                stored_filename=row["stored_filename"],
                storage_path=row["storage_path"],
                file_size=row["file_size"],
                mime_type=row["mime_type"],
                sha256_hash=row["sha256_hash"],
                is_text=bool(row["is_text"]),
                av_scanned=bool(row["av_scanned"]),
                av_clean=bool(row["av_clean"]) if row["av_clean"] is not None else None,
                created_at=datetime.fromisoformat(row["created_at"]),
            )

    def get_conversation_files(self, conversation_id: str) -> list[UploadedFile]:
        """Get all uploaded files for a conversation."""
        with get_db() as conn:
            rows = conn.execute(
                """SELECT * FROM uploaded_files
                   WHERE conversation_id = ?
                   ORDER BY created_at""",
                (conversation_id,)
            ).fetchall()

            return [
                UploadedFile(
                    id=row["id"],
                    conversation_id=row["conversation_id"],
                    user_id=row["user_id"],
                    original_filename=row["original_filename"],
                    stored_filename=row["stored_filename"],
                    storage_path=row["storage_path"],
                    file_size=row["file_size"],
                    mime_type=row["mime_type"],
                    sha256_hash=row["sha256_hash"],
                    is_text=bool(row["is_text"]),
                    av_scanned=bool(row["av_scanned"]),
                    av_clean=bool(row["av_clean"]) if row["av_clean"] is not None else None,
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
                for row in rows
            ]

    def update_uploaded_file_av_status(
        self, file_id: int, av_scanned: bool, av_clean: Optional[bool]
    ) -> bool:
        """Update the AV scan status of an uploaded file."""
        with get_db() as conn:
            cursor = conn.execute(
                "UPDATE uploaded_files SET av_scanned = ?, av_clean = ? WHERE id = ?",
                (av_scanned, av_clean, file_id)
            )
            return cursor.rowcount > 0

    def delete_uploaded_file(self, file_id: int) -> bool:
        """Delete an uploaded file record."""
        with get_db() as conn:
            cursor = conn.execute(
                "DELETE FROM uploaded_files WHERE id = ?", (file_id,)
            )
            return cursor.rowcount > 0


# =============================================================================
# Backwards compatibility
# =============================================================================

# Alias for old code
store = ConversationStore()
