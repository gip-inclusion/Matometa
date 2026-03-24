"""Database models and ConversationStore for conversation/report persistence."""

import json
import uuid

# =============================================================================
# Data Classes
# =============================================================================
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .db import (
    VALID_CONVERSATION_COLUMNS,
    VALID_REPORT_COLUMNS,
    _build_update_clause,
    get_db,
)
from .schema import init_db


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
            }
            if self.report
            else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


def _row_to_list_report(row) -> "Report":
    return Report(
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


def _row_to_list_conversation(row) -> "Conversation":
    return Conversation(
        id=row["id"],
        user_id=row["user_id"],
        title=row["title"],
        session_id=row["session_id"],
        conv_type=row["conv_type"] or "exploration",
        file_path=row["file_path"],
        status=row["status"] or "active",
        needs_response=bool(row["needs_response"]) if row["needs_response"] else False,
        messages=[],
        report=Report(id=row["report_id"], title=row["report_title"] or "") if row["report_id"] else None,
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _row_to_knowledge_conversation(row) -> "Conversation":
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


class ConversationStore:
    """PostgreSQL-backed conversation and report store."""

    def __init__(self):
        init_db()

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
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    conv.id,
                    conv.user_id,
                    conv.title,
                    conv.session_id,
                    conv.conv_type,
                    conv.file_path,
                    conv.status,
                    conv.created_at.isoformat(),
                    conv.updated_at.isoformat(),
                ),
            )

        return conv

    def get_conversation(
        self, conv_id: str, include_messages: bool = True, user_id: Optional[str] = None
    ) -> Optional[Conversation]:
        """Get a conversation by ID. Optionally filter by user_id for access control."""
        with get_db() as conn:
            if user_id:
                row = conn.execute(
                    """SELECT c.*, p.pinned_at AS p_pinned_at, p.label AS p_label
                       FROM conversations c
                       LEFT JOIN pinned_items p ON p.item_id = c.id AND p.item_type = 'conversation'
                       WHERE c.id = %s AND c.user_id = %s""",
                    (conv_id, user_id),
                ).fetchone()
            else:
                row = conn.execute(
                    """SELECT c.*, p.pinned_at AS p_pinned_at, p.label AS p_label
                       FROM conversations c
                       LEFT JOIN pinned_items p ON p.item_id = c.id AND p.item_type = 'conversation'
                       WHERE c.id = %s""",
                    (conv_id,),
                ).fetchone()

            if not row:
                return None

            messages = []
            if include_messages:
                msg_rows = conn.execute(
                    """SELECT id, conversation_id, COALESCE(type, role) as type, content, timestamp
                       FROM messages WHERE conversation_id = %s ORDER BY timestamp""",
                    (conv_id,),
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
            report_row = conn.execute("SELECT * FROM reports WHERE conversation_id = %s", (conv_id,)).fetchone()

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
                    source_conversation_id=report_row["source_conversation_id"]
                    if "source_conversation_id" in report_row.keys()
                    else None,
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
                usage_cache_creation_tokens=row["usage_cache_creation_tokens"]
                if "usage_cache_creation_tokens" in row.keys()
                else 0,
                usage_cache_read_tokens=row["usage_cache_read_tokens"]
                if "usage_cache_read_tokens" in row.keys()
                else 0,
                usage_backend=row["usage_backend"] if "usage_backend" in row.keys() else None,
                usage_extra=usage_extra,
                pinned_at=datetime.fromisoformat(row["p_pinned_at"])
                if "p_pinned_at" in row.keys() and row["p_pinned_at"]
                else None,
                pinned_label=row["p_label"] if "p_label" in row.keys() else None,
                needs_response=bool(row["needs_response"])
                if "needs_response" in row.keys() and row["needs_response"]
                else False,
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
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
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
                ),
            )

            # Deep copy all messages
            for msg in source.messages:
                conn.execute(
                    """INSERT INTO messages (conversation_id, type, role, content, timestamp)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (new_id, msg.type, msg.type, msg.content, msg.created_at.isoformat()),
                )

        # Return the new conversation
        return self.get_conversation(new_id, include_messages=True)

    def list_conversations(
        self,
        user_id: Optional[str] = None,
        limit: int = 50,
        conv_type: Optional[str] = None,
        exclude_report_containers: bool = True,
    ) -> list[Conversation]:
        """List recent conversations with report info.

        By default, excludes conversations that were created only to contain a report
        (identified by having a report linked via conversation_id).
        """
        with get_db() as conn:
            conditions = []
            params = []

            if user_id:
                conditions.append("c.user_id = %s")
                params.append(user_id)

            if conv_type:
                conditions.append("c.conv_type = %s")
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
                LIMIT %s
            """

            rows = conn.execute(query, params).fetchall()

            return [_row_to_list_conversation(row) for row in rows]

    def pin_item(self, item_type: str, item_id: str, label: str) -> bool:
        """Pin an item (conversation, report, or app)."""
        with get_db() as conn:
            conn.execute(
                """INSERT INTO pinned_items (item_type, item_id, label, pinned_at)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT(item_type, item_id) DO UPDATE SET label = %s, pinned_at = %s""",
                (item_type, str(item_id), label, datetime.now().isoformat(), label, datetime.now().isoformat()),
            )
            return True

    def unpin_item(self, item_type: str, item_id: str) -> bool:
        """Unpin an item."""
        with get_db() as conn:
            cursor = conn.execute(
                "DELETE FROM pinned_items WHERE item_type = %s AND item_id = %s", (item_type, str(item_id))
            )
            return cursor.rowcount > 0

    def list_pinned_items(self, item_type: Optional[str] = None) -> list[PinnedItem]:
        """List pinned items, optionally filtered by type."""
        with get_db() as conn:
            if item_type:
                rows = conn.execute(
                    "SELECT * FROM pinned_items WHERE item_type = %s ORDER BY pinned_at", (item_type,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM pinned_items ORDER BY pinned_at").fetchall()
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
                """SELECT c.*, p.pinned_at AS p_pinned_at, p.label AS p_label
                   FROM conversations c
                   JOIN pinned_items p ON p.item_id = c.id AND p.item_type = 'conversation'
                   ORDER BY p.pinned_at""",
            ).fetchall()
            return [
                Conversation(
                    id=row["id"],
                    user_id=row["user_id"],
                    title=row["title"],
                    pinned_at=datetime.fromisoformat(row["p_pinned_at"]) if row["p_pinned_at"] else None,
                    pinned_label=row["p_label"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"]),
                )
                for row in rows
            ]

    def get_active_knowledge_conversation(
        self, file_path: str, user_id: Optional[str] = None
    ) -> Optional[Conversation]:
        """Get active knowledge conversation for a file, optionally filtered by user."""
        with get_db() as conn:
            if user_id:
                row = conn.execute(
                    """SELECT * FROM conversations
                       WHERE conv_type = 'knowledge' AND file_path = %s AND status = 'active' AND user_id = %s
                       ORDER BY updated_at DESC LIMIT 1""",
                    (file_path, user_id),
                ).fetchone()
            else:
                row = conn.execute(
                    """SELECT * FROM conversations
                       WHERE conv_type = 'knowledge' AND file_path = %s AND status = 'active'
                       ORDER BY updated_at DESC LIMIT 1""",
                    (file_path,),
                ).fetchone()

            if not row:
                return None

            return _row_to_knowledge_conversation(row)

    def list_active_knowledge_conversations(self) -> list[Conversation]:
        """List all active knowledge conversations."""
        with get_db() as conn:
            rows = conn.execute(
                """SELECT * FROM conversations
                   WHERE conv_type = 'knowledge' AND status = 'active'
                   ORDER BY updated_at DESC"""
            ).fetchall()

            return [_row_to_knowledge_conversation(row) for row in rows]

    def get_running_conversation_ids(self) -> list[str]:
        """Return IDs of conversations where needs_response is True."""
        with get_db() as conn:
            rows = conn.execute("SELECT id FROM conversations WHERE needs_response = 1").fetchall()
            return [r["id"] for r in rows]

    def clear_all_needs_response(self) -> list[str]:
        """Clear needs_response for all conversations. Used on PM startup to unstick zombies.

        Returns list of conversation IDs that were cleared.
        """
        with get_db() as conn:
            rows = conn.execute("SELECT id FROM conversations WHERE needs_response = 1").fetchall()
            ids = [r["id"] for r in rows]
            if ids:
                conn.execute("UPDATE conversations SET needs_response = 0 WHERE needs_response = 1")
            return ids

    def update_pm_heartbeat(self):
        """Update the PM heartbeat timestamp. Called each PM poll loop iteration."""
        now = datetime.now().isoformat()
        with get_db() as conn:
            conn.execute(
                "INSERT INTO pm_heartbeat (id, last_seen) VALUES (1, %s) ON CONFLICT (id) DO UPDATE SET last_seen = %s",
                (now, now),
            )

    def is_pm_alive(self, max_age_seconds: int = 30) -> bool:
        """Check if the PM has sent a heartbeat recently."""
        with get_db() as conn:
            row = conn.execute("SELECT last_seen FROM pm_heartbeat WHERE id = 1").fetchone()
            if not row:
                return False
            last_seen = datetime.fromisoformat(row["last_seen"])
            return (datetime.now() - last_seen).total_seconds() < max_age_seconds

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
            cursor = conn.execute(f"UPDATE conversations SET {set_clause} WHERE id = %s", values)
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
                   SET usage_input_tokens = %s,
                       usage_output_tokens = %s,
                       usage_cache_creation_tokens = %s,
                       usage_cache_read_tokens = %s,
                       usage_backend = COALESCE(%s, usage_backend),
                       usage_extra = %s,
                       updated_at = %s
                   WHERE id = %s""",
                (
                    input_tokens,
                    output_tokens,
                    cache_creation_tokens,
                    cache_read_tokens,
                    backend,
                    extra_json,
                    datetime.now().isoformat(),
                    conv_id,
                ),
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
                   SET usage_input_tokens = COALESCE(usage_input_tokens, 0) + %s,
                       usage_output_tokens = COALESCE(usage_output_tokens, 0) + %s,
                       usage_cache_creation_tokens = COALESCE(usage_cache_creation_tokens, 0) + %s,
                       usage_cache_read_tokens = COALESCE(usage_cache_read_tokens, 0) + %s,
                       usage_backend = COALESCE(%s, usage_backend),
                       usage_extra = COALESCE(%s, usage_extra),
                       updated_at = %s
                   WHERE id = %s""",
                (
                    input_tokens,
                    output_tokens,
                    cache_creation_tokens,
                    cache_read_tokens,
                    backend,
                    extra_json,
                    datetime.now().isoformat(),
                    conv_id,
                ),
            )
            return cursor.rowcount > 0

    def delete_conversation(self, conv_id: str) -> bool:
        """Delete a conversation and all related data."""
        with get_db() as conn:
            conn.execute("DELETE FROM reports WHERE conversation_id = %s", (conv_id,))
            conn.execute("DELETE FROM messages WHERE conversation_id = %s", (conv_id,))
            cursor = conn.execute("DELETE FROM conversations WHERE id = %s", (conv_id,))
            return cursor.rowcount > 0

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
            row = conn.execute("SELECT id, title FROM conversations WHERE id = %s", (conv_id,)).fetchone()
            if not row:
                return None

            # Insert message
            msg.id = conn.insert_and_get_id(
                """INSERT INTO messages (conversation_id, type, role, content, timestamp)
                   VALUES (%s, %s, %s, %s, %s)""",
                (conv_id, type, type, content, msg.created_at.isoformat()),
            )

            # Update conversation timestamp
            now = datetime.now().isoformat()

            # Auto-generate title from first user message
            if row["title"] is None and type == "user":
                title = content[:80] + ("..." if len(content) > 80 else "")
                conn.execute(
                    "UPDATE conversations SET title = %s, updated_at = %s WHERE id = %s", (title, now, conv_id)
                )
            else:
                conn.execute("UPDATE conversations SET updated_at = %s WHERE id = %s", (now, conv_id))

        return msg

    def update_message(self, message_id: int, content: str) -> bool:
        """Update a message's content. Returns True if updated."""
        with get_db() as conn:
            cursor = conn.execute("UPDATE messages SET content = %s WHERE id = %s", (content, message_id))
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
                       FROM messages WHERE conversation_id = %s"""
            params = [conv_id]

            if types:
                placeholders = ",".join(["%s"] * len(types))
                query += f" AND COALESCE(type, role) IN ({placeholders})"
                params.extend(types)

            query += " ORDER BY timestamp"

            if limit:
                query += " LIMIT %s"
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
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    title,
                    content,
                    website,
                    category,
                    json.dumps(tags) if tags else None,
                    original_query,
                    source_conversation_id,
                    user_id,
                    1,
                    report.created_at.isoformat(),
                    report.updated_at.isoformat(),
                ),
            )

        return report

    def get_report(self, report_id: int) -> Optional[Report]:
        """Get a report by ID."""
        with get_db() as conn:
            row = conn.execute("SELECT * FROM reports WHERE id = %s", (report_id,)).fetchone()

            if not row:
                return None

            # Use content column if available, fall back to message lookup
            content = row["content"] if "content" in row.keys() else None
            if not content and row["message_id"]:
                # Legacy: fetch from messages
                msg = conn.execute("SELECT content FROM messages WHERE id = %s", (row["message_id"],)).fetchone()
                content = msg["content"] if msg else None

            return Report(
                id=row["id"],
                title=row["title"],
                content=content,
                website=row["website"],
                category=row["category"],
                tags=json.loads(row["tags"]) if row["tags"] else [],
                original_query=row["original_query"],
                source_conversation_id=row["source_conversation_id"]
                if "source_conversation_id" in row.keys()
                else None,
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
                query += " AND website = %s"
                params.append(website)

            if category:
                query += " AND category = %s"
                params.append(category)

            query += " ORDER BY updated_at DESC LIMIT %s"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()

            return [_row_to_list_report(row) for row in rows]

    def archive_report(self, report_id: int) -> bool:
        """Archive a report (soft delete)."""
        with get_db() as conn:
            cursor = conn.execute(
                "UPDATE reports SET archived = 1, updated_at = %s WHERE id = %s",
                (datetime.now().isoformat(), report_id),
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
            conn.execute("UPDATE reports SET version = version + 1 WHERE id = %s", (report_id,))

            cursor = conn.execute(f"UPDATE reports SET {set_clause} WHERE id = %s", values)
            return cursor.rowcount > 0

    def delete_report(self, report_id: int) -> bool:
        """Delete a report."""
        with get_db() as conn:
            cursor = conn.execute("DELETE FROM reports WHERE id = %s", (report_id,))
            return cursor.rowcount > 0

    def get_all_tags(self, tag_type: Optional[str] = None) -> list[Tag]:
        """Get all tags, optionally filtered by type."""
        with get_db() as conn:
            if tag_type:
                rows = conn.execute("SELECT * FROM tags WHERE type = %s ORDER BY label", (tag_type,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM tags ORDER BY type, label").fetchall()

            return [Tag(id=row["id"], name=row["name"], type=row["type"], label=row["label"]) for row in rows]

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
        self, active_tag_names: Optional[list[str]] = None, user_id: Optional[str] = None
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
                conv_filter += " AND c.user_id = %s"
                params.append(user_id)

            if active_tag_names:
                # Find conversations that have all active tags
                placeholders = ",".join(["%s"] * len(active_tag_names))
                conv_filter += f"""
                    AND c.id IN (
                        SELECT conversation_id FROM conversation_tags ct2
                        JOIN tags t2 ON ct2.tag_id = t2.id
                        WHERE t2.name IN ({placeholders})
                        GROUP BY conversation_id
                        HAVING COUNT(DISTINCT t2.name) = %s
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
                tag = Tag(id=row["id"], name=row["name"], type=row["type"], label=row["label"], count=row["count"])
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
            row = conn.execute("SELECT * FROM tags WHERE name = %s", (name,)).fetchone()
            if row:
                return Tag(id=row["id"], name=row["name"], type=row["type"], label=row["label"])
            return None

    def set_conversation_tags(self, conv_id: str, tag_names: list[str], update_timestamp: bool = True) -> bool:
        """Set tags for a conversation (replaces existing tags)."""
        with get_db() as conn:
            # Clear existing tags
            conn.execute("DELETE FROM conversation_tags WHERE conversation_id = %s", (conv_id,))

            # Add new tags
            for tag_name in tag_names:
                tag_row = conn.execute("SELECT id FROM tags WHERE name = %s", (tag_name,)).fetchone()
                if tag_row:
                    conn.insert_ignore("conversation_tags", ["conversation_id", "tag_id"], (conv_id, tag_row["id"]))

            # Update conversation timestamp
            if update_timestamp:
                conn.execute(
                    "UPDATE conversations SET updated_at = %s WHERE id = %s", (datetime.now().isoformat(), conv_id)
                )
            return True

    def get_conversation_tags(self, conv_id: str) -> list[Tag]:
        """Get tags for a conversation."""
        with get_db() as conn:
            rows = conn.execute(
                """SELECT t.* FROM tags t
                   JOIN conversation_tags ct ON t.id = ct.tag_id
                   WHERE ct.conversation_id = %s
                   ORDER BY t.type, t.label""",
                (conv_id,),
            ).fetchall()
            return [Tag(id=row["id"], name=row["name"], type=row["type"], label=row["label"]) for row in rows]

    def get_conversation_tags_batch(self, conv_ids: list[str]) -> dict[str, list[Tag]]:
        """Get tags for multiple conversations in a single query."""
        if not conv_ids:
            return {}
        with get_db() as conn:
            placeholders = ",".join(["%s"] * len(conv_ids))
            rows = conn.execute(
                f"""SELECT ct.conversation_id, t.id, t.name, t.type, t.label
                   FROM tags t
                   JOIN conversation_tags ct ON t.id = ct.tag_id
                   WHERE ct.conversation_id IN ({placeholders})
                   ORDER BY t.type, t.label""",
                tuple(conv_ids),
            ).fetchall()
            result: dict[str, list[Tag]] = {cid: [] for cid in conv_ids}
            for row in rows:
                result[row["conversation_id"]].append(
                    Tag(id=row["id"], name=row["name"], type=row["type"], label=row["label"])
                )
            return result

    def set_report_tags(self, report_id: int, tag_names: list[str], update_timestamp: bool = True) -> bool:
        """Set tags for a report (replaces existing tags)."""
        with get_db() as conn:
            # Clear existing tags
            conn.execute("DELETE FROM report_tags WHERE report_id = %s", (report_id,))

            # Add new tags
            for tag_name in tag_names:
                tag_row = conn.execute("SELECT id FROM tags WHERE name = %s", (tag_name,)).fetchone()
                if tag_row:
                    conn.insert_ignore("report_tags", ["report_id", "tag_id"], (report_id, tag_row["id"]))

            # Update report timestamp
            if update_timestamp:
                conn.execute(
                    "UPDATE reports SET updated_at = %s WHERE id = %s", (datetime.now().isoformat(), report_id)
                )
            return True

    def get_report_tags(self, report_id: int) -> list[Tag]:
        """Get tags for a report."""
        with get_db() as conn:
            rows = conn.execute(
                """SELECT t.* FROM tags t
                   JOIN report_tags rt ON t.id = rt.tag_id
                   WHERE rt.report_id = %s
                   ORDER BY t.type, t.label""",
                (report_id,),
            ).fetchall()
            return [Tag(id=row["id"], name=row["name"], type=row["type"], label=row["label"]) for row in rows]

    def get_report_tags_batch(self, report_ids: list[int]) -> dict[int, list[Tag]]:
        """Get tags for multiple reports in a single query."""
        if not report_ids:
            return {}
        with get_db() as conn:
            placeholders = ",".join(["%s"] * len(report_ids))
            rows = conn.execute(
                f"""SELECT rt.report_id, t.id, t.name, t.type, t.label
                   FROM tags t
                   JOIN report_tags rt ON t.id = rt.tag_id
                   WHERE rt.report_id IN ({placeholders})
                   ORDER BY t.type, t.label""",
                tuple(report_ids),
            ).fetchall()
            result: dict[int, list[Tag]] = {rid: [] for rid in report_ids}
            for row in rows:
                result[row["report_id"]].append(
                    Tag(id=row["id"], name=row["name"], type=row["type"], label=row["label"])
                )
            return result

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
                conditions.append("c.user_id = %s")
                params.append(user_id)

            # Filter by tags (AND logic - must have all specified tags)
            if tag_names:
                for tag_name in tag_names:
                    conditions.append("""
                        EXISTS (
                            SELECT 1 FROM conversation_tags ct
                            JOIN tags t ON ct.tag_id = t.id
                            WHERE ct.conversation_id = c.id AND t.name = %s
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
                LIMIT %s
            """

            rows = conn.execute(query, params).fetchall()

            # Batch fetch tags for all conversations (1 query instead of N)
            conv_ids = [row["id"] for row in rows]
            tags_by_conv: dict[str, list[Tag]] = {cid: [] for cid in conv_ids}
            if conv_ids:
                tag_ph = ",".join(["%s"] * len(conv_ids))
                tag_rows = conn.execute(
                    f"""SELECT ct.conversation_id, t.id, t.name, t.type, t.label
                       FROM tags t
                       JOIN conversation_tags ct ON t.id = ct.tag_id
                       WHERE ct.conversation_id IN ({tag_ph})
                       ORDER BY t.type, t.label""",
                    tuple(conv_ids),
                ).fetchall()
                for tr in tag_rows:
                    tags_by_conv[tr["conversation_id"]].append(
                        Tag(id=tr["id"], name=tr["name"], type=tr["type"], label=tr["label"])
                    )

            results = []
            for row in rows:
                conv = _row_to_list_conversation(row)
                results.append((conv, tags_by_conv.get(row["id"], [])))

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
                            WHERE rt.report_id = r.id AND t.name = %s
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
                LIMIT %s
            """

            rows = conn.execute(query, params).fetchall()

            # Batch fetch tags for all reports (1 query instead of N)
            report_ids = [row["id"] for row in rows]
            tags_by_report: dict[int, list[Tag]] = {rid: [] for rid in report_ids}
            if report_ids:
                tag_ph = ",".join(["%s"] * len(report_ids))
                tag_rows = conn.execute(
                    f"""SELECT rt.report_id, t.id, t.name, t.type, t.label
                       FROM tags t
                       JOIN report_tags rt ON t.id = rt.tag_id
                       WHERE rt.report_id IN ({tag_ph})
                       ORDER BY t.type, t.label""",
                    tuple(report_ids),
                ).fetchall()
                for tr in tag_rows:
                    tags_by_report[tr["report_id"]].append(
                        Tag(id=tr["id"], name=tr["name"], type=tr["type"], label=tr["label"])
                    )

            results = []
            for row in rows:
                report = _row_to_list_report(row)
                results.append((report, tags_by_report.get(row["id"], [])))

            return results

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
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    conversation_id,
                    user_id,
                    original_filename,
                    stored_filename,
                    storage_path,
                    file_size,
                    mime_type,
                    sha256_hash,
                    is_text,
                    av_scanned,
                    av_clean,
                    uploaded_file.created_at.isoformat(),
                ),
            )

        return uploaded_file

    def get_uploaded_file(self, file_id: int) -> Optional[UploadedFile]:
        """Get an uploaded file by ID."""
        with get_db() as conn:
            row = conn.execute("SELECT * FROM uploaded_files WHERE id = %s", (file_id,)).fetchone()

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
            row = conn.execute("SELECT * FROM uploaded_files WHERE sha256_hash = %s LIMIT 1", (sha256_hash,)).fetchone()

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
                   WHERE conversation_id = %s
                   ORDER BY created_at""",
                (conversation_id,),
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

    def update_uploaded_file_av_status(self, file_id: int, av_scanned: bool, av_clean: Optional[bool]) -> bool:
        """Update the AV scan status of an uploaded file."""
        with get_db() as conn:
            cursor = conn.execute(
                "UPDATE uploaded_files SET av_scanned = %s, av_clean = %s WHERE id = %s",
                (av_scanned, av_clean, file_id),
            )
            return cursor.rowcount > 0

    def delete_uploaded_file(self, file_id: int) -> bool:
        """Delete an uploaded file record."""
        with get_db() as conn:
            cursor = conn.execute("DELETE FROM uploaded_files WHERE id = %s", (file_id,))
            return cursor.rowcount > 0

    def get_messages_since(self, conv_id: str, after_id: int) -> list[Message]:
        """Get messages with id > after_id for a conversation."""
        with get_db() as conn:
            rows = conn.execute(
                """SELECT id, conversation_id, COALESCE(type, role) as type, content, timestamp
                   FROM messages
                   WHERE conversation_id = %s AND id > %s
                   ORDER BY id""",
                (conv_id, after_id),
            ).fetchall()

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

    def get_last_message_role(self, conversation_id: str) -> Optional[str]:
        """Get the role/type of the last message in a conversation."""
        with get_db() as conn:
            row = conn.execute(
                """SELECT COALESCE(type, role) as type FROM messages
                   WHERE conversation_id = %s ORDER BY id DESC LIMIT 1""",
                (conversation_id,),
            ).fetchone()
            return row["type"] if row else None

    def enqueue_pm_command(self, conversation_id: str, command: str, payload: Optional[dict] = None) -> int:
        """Queue a command for the process manager. Returns the command ID."""
        with get_db() as conn:
            return conn.insert_and_get_id(
                """INSERT INTO pm_commands (conversation_id, command, payload, created_at)
                   VALUES (%s, %s, %s, %s)""",
                (conversation_id, command, json.dumps(payload) if payload else None, datetime.now().isoformat()),
            )

    def claim_pending_pm_commands(self) -> list[dict]:
        """Atomically claim and return unprocessed PM commands.

        Uses UPDATE ... RETURNING to prevent two PM instances from
        processing the same command (the SELECT+UPDATE race condition).
        """
        now = datetime.now().isoformat()
        with get_db() as conn:
            rows = conn.execute(
                """UPDATE pm_commands
                   SET processed_at = %s
                   WHERE processed_at IS NULL
                   RETURNING id, conversation_id, command, payload, created_at""",
                (now,),
            ).fetchall()

            return [
                {
                    "id": r["id"],
                    "conversation_id": r["conversation_id"],
                    "command": r["command"],
                    "payload": json.loads(r["payload"]) if r["payload"] else None,
                    "created_at": r["created_at"],
                }
                for r in rows
            ]

    def get_pending_pm_commands(self) -> list[dict]:
        """Get unprocessed PM commands (read-only, for status checks)."""
        with get_db() as conn:
            rows = conn.execute(
                """SELECT id, conversation_id, command, payload, created_at
                   FROM pm_commands
                   WHERE processed_at IS NULL
                   ORDER BY id"""
            ).fetchall()

            return [
                {
                    "id": r["id"],
                    "conversation_id": r["conversation_id"],
                    "command": r["command"],
                    "payload": json.loads(r["payload"]) if r["payload"] else None,
                    "created_at": r["created_at"],
                }
                for r in rows
            ]


# =============================================================================
# Backwards compatibility
# =============================================================================


class LazyConversationStore:
    _store = None

    def __getattr__(self, name):
        if LazyConversationStore._store is None:
            LazyConversationStore._store = ConversationStore()
        return getattr(LazyConversationStore._store, name)


store = LazyConversationStore()
