"""SQLite database for conversation and report persistence."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional
import uuid

from . import config

# Database path
DB_PATH = config.BASE_DIR / "data" / "matometa.db"

# Schema version for migrations
SCHEMA_VERSION = 7

# Valid column names for dynamic updates (security: prevents SQL injection)
VALID_CONVERSATION_COLUMNS = frozenset({"title", "session_id", "user_id", "status", "pr_url", "updated_at"})
VALID_REPORT_COLUMNS = frozenset({"title", "website", "category", "tags", "original_query", "content", "updated_at"})


def _build_update_clause(updates: dict, valid_columns: frozenset) -> tuple[str, list]:
    """
    Build a safe UPDATE SET clause from a dict of updates.

    Validates all keys against valid_columns to prevent SQL injection.
    Returns (set_clause, values) for use in parameterized query.

    Raises ValueError if any key is not in valid_columns.
    """
    for key in updates:
        if key not in valid_columns:
            raise ValueError(f"Invalid column name: {key}")

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values())
    return set_clause, values


def get_connection() -> sqlite3.Connection:
    """Get a database connection with row factory."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_db():
    """Context manager for database connections."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def get_schema_version(conn: sqlite3.Connection) -> int:
    """Get current schema version."""
    try:
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        return row["version"] if row else 0
    except sqlite3.OperationalError:
        return 0


def init_db():
    """Initialize or migrate database schema."""
    with get_db() as conn:
        current_version = get_schema_version(conn)

        if current_version < 1:
            _create_schema_v1(conn)

        if current_version < 2:
            _migrate_to_v2(conn)

        if current_version < 3:
            _migrate_to_v3(conn)

        if current_version < 4:
            _migrate_to_v4(conn)

        if current_version < 5:
            _migrate_to_v5(conn)

        if current_version < 6:
            _migrate_to_v6(conn)

        if current_version < 7:
            _migrate_to_v7(conn)


def _create_schema_v1(conn: sqlite3.Connection):
    """Create initial schema (v1 - legacy)."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY
        );

        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            title TEXT,
            session_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            raw_events TEXT,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        );

        CREATE INDEX IF NOT EXISTS idx_messages_conversation
            ON messages(conversation_id);

        CREATE INDEX IF NOT EXISTS idx_conversations_updated
            ON conversations(updated_at DESC);

        INSERT OR REPLACE INTO schema_version (version) VALUES (1);
    """)


def _migrate_to_v2(conn: sqlite3.Connection):
    """Migrate to v2 schema: add type to messages, add reports table."""
    # Check if we need to migrate messages
    cursor = conn.execute("PRAGMA table_info(messages)")
    columns = {row["name"] for row in cursor.fetchall()}

    if "type" not in columns:
        # Add type column, rename role to type
        conn.execute("ALTER TABLE messages ADD COLUMN type TEXT")
        conn.execute("UPDATE messages SET type = role")
        # Note: SQLite doesn't support DROP COLUMN easily, keep role for now

    # Create reports table
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            message_id INTEGER,
            title TEXT NOT NULL,
            website TEXT,
            category TEXT,
            tags TEXT,
            original_query TEXT,
            version INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id),
            FOREIGN KEY (message_id) REFERENCES messages(id)
        );

        CREATE INDEX IF NOT EXISTS idx_reports_conversation
            ON reports(conversation_id);

        CREATE INDEX IF NOT EXISTS idx_reports_updated
            ON reports(updated_at DESC);

        UPDATE schema_version SET version = 2;
    """)


def _migrate_to_v3(conn: sqlite3.Connection):
    """Migrate to v3 schema: add type, file_path, status to conversations for knowledge editing."""
    cursor = conn.execute("PRAGMA table_info(conversations)")
    columns = {row["name"] for row in cursor.fetchall()}

    if "conv_type" not in columns:
        conn.execute("ALTER TABLE conversations ADD COLUMN conv_type TEXT DEFAULT 'exploration'")

    if "file_path" not in columns:
        conn.execute("ALTER TABLE conversations ADD COLUMN file_path TEXT")

    if "status" not in columns:
        conn.execute("ALTER TABLE conversations ADD COLUMN status TEXT DEFAULT 'active'")

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_conversations_type_status
            ON conversations(conv_type, status)
    """)

    conn.execute("UPDATE schema_version SET version = 3")


def _migrate_to_v4(conn: sqlite3.Connection):
    """Migrate to v4: add columns to reports (partial migration, see v5)."""
    cursor = conn.execute("PRAGMA table_info(reports)")
    columns = {row["name"] for row in cursor.fetchall()}

    if "content" not in columns:
        conn.execute("ALTER TABLE reports ADD COLUMN content TEXT")

    if "source_conversation_id" not in columns:
        conn.execute("ALTER TABLE reports ADD COLUMN source_conversation_id TEXT")

    if "user_id" not in columns:
        conn.execute("ALTER TABLE reports ADD COLUMN user_id TEXT")

    conn.execute("UPDATE schema_version SET version = 4")


def _migrate_to_v5(conn: sqlite3.Connection):
    """Migrate to v5: recreate reports table with nullable conversation_id."""
    # Recreate table with new schema (conversation_id nullable)
    # Disable FK checks temporarily for table recreation
    conn.executescript("""
        PRAGMA foreign_keys = OFF;

        DROP TABLE IF EXISTS reports_new;

        CREATE TABLE reports_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT,
            website TEXT,
            category TEXT,
            tags TEXT,
            original_query TEXT,
            source_conversation_id TEXT,
            user_id TEXT,
            version INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            -- Legacy columns (nullable for backwards compat)
            conversation_id TEXT,
            message_id INTEGER
        );

        INSERT INTO reports_new (id, title, content, website, category, tags, original_query,
                                 source_conversation_id, user_id, version, created_at, updated_at,
                                 conversation_id, message_id)
        SELECT id, title, content, website, category, tags, original_query,
               source_conversation_id, user_id, version, created_at, updated_at,
               conversation_id, message_id
        FROM reports;

        DROP TABLE reports;

        ALTER TABLE reports_new RENAME TO reports;

        CREATE INDEX IF NOT EXISTS idx_reports_updated
            ON reports(updated_at DESC);

        UPDATE schema_version SET version = 5;

        PRAGMA foreign_keys = ON;
    """)


def _migrate_to_v6(conn: sqlite3.Connection):
    """Migrate to v6: add archived column to reports."""
    cursor = conn.execute("PRAGMA table_info(reports)")
    columns = {row["name"] for row in cursor.fetchall()}

    if "archived" not in columns:
        conn.execute("ALTER TABLE reports ADD COLUMN archived INTEGER DEFAULT 0")

    conn.execute("UPDATE schema_version SET version = 6")


def _migrate_to_v7(conn: sqlite3.Connection):
    """Migrate to v7: add pr_url column to conversations for GitHub PR tracking."""
    cursor = conn.execute("PRAGMA table_info(conversations)")
    columns = {row["name"] for row in cursor.fetchall()}

    if "pr_url" not in columns:
        conn.execute("ALTER TABLE conversations ADD COLUMN pr_url TEXT")

    conn.execute("UPDATE schema_version SET version = 7")


# =============================================================================
# Data Classes
# =============================================================================

from dataclasses import dataclass, field


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
    messages: list[Message] = field(default_factory=list)
    report: Optional[Report] = None
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

            return Conversation(
                id=row["id"],
                user_id=row["user_id"],
                title=row["title"],
                session_id=row["session_id"],
                conv_type=row["conv_type"] or "exploration",
                file_path=row["file_path"],
                status=row["status"] or "active",
                pr_url=row["pr_url"] if "pr_url" in row.keys() else None,
                messages=messages,
                report=report,
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )

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
        allowed = {"title", "session_id", "user_id", "status", "pr_url"}
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
            cursor = conn.execute(
                """INSERT INTO messages (conversation_id, type, role, content, timestamp)
                   VALUES (?, ?, ?, ?, ?)""",
                (conv_id, type, type, content, msg.created_at.isoformat())
            )
            msg.id = cursor.lastrowid

            # Update conversation timestamp
            now = datetime.now().isoformat()

            # Auto-generate title from first user message
            if row["title"] is None and type == "user":
                title = content[:50] + ("..." if len(content) > 50 else "")
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
            cursor = conn.execute(
                """INSERT INTO reports
                   (title, content, website, category, tags, original_query,
                    source_conversation_id, user_id, version, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (title, content, website, category,
                 json.dumps(tags) if tags else None, original_query,
                 source_conversation_id, user_id,
                 1, report.created_at.isoformat(), report.updated_at.isoformat())
            )
            report.id = cursor.lastrowid

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


# =============================================================================
# Backwards compatibility
# =============================================================================

# Alias for old code
store = ConversationStore()
