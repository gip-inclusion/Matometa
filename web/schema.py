"""Database schema creation, migrations, and tag taxonomy.

Called once at startup by ConversationStore.__init__().
"""

from .db import ConnectionWrapper, get_db

# Schema version - increment when adding migrations
SCHEMA_VERSION = 20


def _get_schema_version(conn: ConnectionWrapper) -> int:
    """Get current schema version, or 0 if no schema exists."""
    try:
        row = conn.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()
        return row["version"] if row else 0
    except Exception as e:
        error_code = getattr(e, "pgcode", None)
        if error_code == "42P01":  # undefined_table
            conn.rollback()
            return 0
        raise


def _set_schema_version(conn: ConnectionWrapper, version: int):
    """Set the schema version."""
    conn.execute(
        "INSERT INTO schema_version (version) VALUES (%s) ON CONFLICT (version) DO UPDATE SET version = %s",
        (version, version)
    )


def _get_table_columns(conn: ConnectionWrapper, table_name: str) -> set[str]:
    """Get column names for a table."""
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
        (table_name,)
    ).fetchall()
    return {row['column_name'] for row in rows}


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
                if current_version < 18:
                    _migrate_to_v18(conn)
                if current_version < 19:
                    _migrate_to_v19(conn)
                if current_version < 20:
                    _migrate_to_v20(conn)

            _set_schema_version(conn, SCHEMA_VERSION)

        # Safety: ensure tables exist even if version was already bumped
        _migrate_to_v15(conn)
        _migrate_to_v17(conn)
        _migrate_to_v18(conn)
        _migrate_to_v19(conn)
        _migrate_to_v20(conn)


# =============================================================================
# Migrations
# =============================================================================

def _migrate_to_v11(conn: ConnectionWrapper):
    """Migrate to v11: rename token columns to usage_ prefix, add cache/backend columns."""
    columns = _get_table_columns(conn, "conversations")

    # Skip if already migrated
    if "usage_input_tokens" in columns:
        return

    has_old_columns = "input_tokens" in columns

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

    # Ensure schema_version table exists for older databases
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)")


def _migrate_to_v12(conn: ConnectionWrapper):
    """Migrate to v12: add uploaded_files table for chat file uploads."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS uploaded_files (
            id SERIAL PRIMARY KEY,
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cron_runs (
            id SERIAL PRIMARY KEY,
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pinned_items (
            id SERIAL PRIMARY KEY,
            item_type TEXT NOT NULL,
            item_id TEXT NOT NULL,
            label TEXT,
            pinned_at TEXT NOT NULL,
            UNIQUE(item_type, item_id)
        )
    """)

    # Migrate existing pinned conversations
    conn.execute("""
        INSERT INTO pinned_items (item_type, item_id, label, pinned_at)
        SELECT 'conversation', id, pinned_label, pinned_at
        FROM conversations WHERE pinned_at IS NOT NULL
        ON CONFLICT (item_type, item_id) DO NOTHING
    """)


def _migrate_to_v18(conn: ConnectionWrapper):
    """Migrate to v18: add pm_commands table for process manager coordination."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pm_commands (
            id SERIAL PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            command TEXT NOT NULL,
            payload TEXT,
            created_at TEXT NOT NULL,
            processed_at TEXT
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_pm_commands_pending
        ON pm_commands(processed_at) WHERE processed_at IS NULL
    """)


def _migrate_to_v19(conn: ConnectionWrapper):
    """Migrate to v19: add pm_heartbeat table for PM liveness detection."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pm_heartbeat (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            last_seen TEXT NOT NULL
        )
    """)


# =============================================================================
# Full schema creation
# =============================================================================

def _create_schema(conn: ConnectionWrapper):
    """Create the complete database schema."""
    conn.execute_raw("""
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
            id SERIAL PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            type TEXT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            raw_events TEXT,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        );

        CREATE TABLE IF NOT EXISTS reports (
            id SERIAL PRIMARY KEY,
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
            id SERIAL PRIMARY KEY,
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
            id SERIAL PRIMARY KEY,
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
            id SERIAL PRIMARY KEY,
            app_slug TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL,
            output TEXT,
            duration_ms INTEGER,
            trigger TEXT NOT NULL DEFAULT 'scheduled'
        );

        CREATE TABLE IF NOT EXISTS pinned_items (
            id SERIAL PRIMARY KEY,
            item_type TEXT NOT NULL,
            item_id TEXT NOT NULL,
            label TEXT,
            pinned_at TEXT NOT NULL,
            UNIQUE(item_type, item_id)
        );

        CREATE TABLE IF NOT EXISTS pm_commands (
            id SERIAL PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            command TEXT NOT NULL,
            payload TEXT,
            created_at TEXT NOT NULL,
            processed_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_uploaded_files_conversation ON uploaded_files(conversation_id);
        CREATE INDEX IF NOT EXISTS idx_uploaded_files_hash ON uploaded_files(sha256_hash);
        CREATE INDEX IF NOT EXISTS idx_uploaded_files_user ON uploaded_files(user_id);
        CREATE INDEX IF NOT EXISTS idx_cron_runs_slug_started ON cron_runs(app_slug, started_at DESC);
        CREATE INDEX IF NOT EXISTS idx_pm_commands_pending ON pm_commands(processed_at) WHERE processed_at IS NULL;

        CREATE TABLE IF NOT EXISTS pm_heartbeat (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            last_seen TEXT NOT NULL
        );
    """)


def _migrate_to_v20(conn: ConnectionWrapper):
    """Migrate to v20: add compound indexes for hot queries.

    - messages(conversation_id, id): SSE polling query
    - conversations(user_id, updated_at): list conversations by user
    - conversations(needs_response): running conversations check
    """
    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_conv_id ON messages(conversation_id, id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_user_updated ON conversations(user_id, updated_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_needs_response ON conversations(needs_response) WHERE needs_response = 1")


# =============================================================================
# Tag taxonomy
# =============================================================================

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
    conn.executemany(
        "INSERT INTO tags (name, type, label) VALUES (%s, %s, %s) ON CONFLICT (name) DO NOTHING",
        TAGS
    )
