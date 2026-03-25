"""SQLite database for Metabase cards inventory."""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

# Database location
DB_PATH = Path(__file__).parent.parent.parent.parent / "knowledge" / "metabase" / "cards.db"

# Topic taxonomy (no "autre" - all cards must be categorized)
TOPICS = {
    "file-active": "Candidats dans la file active (30+ days waiting)",
    "postes-tension": "Postes en tension (difficult to recruit)",
    "demographie": "Age, gender, geographic breakdowns",
    "candidatures": "Candidature metrics, states, flows",
    "employeurs": "SIAE and employer information",
    "prescripteurs": "Prescripteur and orientation data",
    "auto-prescription": "Auto-prescription metrics",
    "controles": "Control and compliance",
    "prolongations": "PASS extensions",
    "etp-effectifs": "ETP and workforce metrics",
    "esat": "ESAT-specific data",
    "pass-iae": "PASS IAE delivery and tracking",
}

# Table name patterns to topic mapping (for fallback inference)
TABLE_TO_TOPIC = {
    "esat": "esat",
    "questionnaire": "esat",  # ESAT questionnaires
    "candidat": "candidatures",
    "candidature": "candidatures",
    "prolongation": "prolongations",
    "pass_iae": "pass-iae",
    "pass-iae": "pass-iae",
    "suivi_pass": "pass-iae",
    "prescripteur": "prescripteurs",
    "orientation": "prescripteurs",
    "auto_prescription": "auto-prescription",
    "controle": "controles",
    "structure": "employeurs",
    "organisation": "employeurs",
    "siae": "employeurs",
    "convention": "employeurs",
    "poste": "postes-tension",
    "tension": "postes-tension",
    "file_active": "file-active",
    "recherche_active": "file-active",
    "age": "demographie",
    "genre": "demographie",
    "sexe": "demographie",
    "departement": "demographie",
    "region": "demographie",
    "etp": "etp-effectifs",
    "effectif": "etp-effectifs",
}

@dataclass
class Card:
    """A Metabase card/question."""

    id: int
    name: str
    description: Optional[str]
    collection_id: Optional[int]
    dashboard_id: Optional[int]
    topic: Optional[str]
    sql_query: Optional[str]
    tables_referenced: list[str]
    created_at: Optional[str]
    updated_at: Optional[str]

    @classmethod
    def from_row(cls, row: tuple) -> "Card":
        return cls(
            id=row[0],
            name=row[1],
            description=row[2],
            collection_id=row[3],
            dashboard_id=row[4],
            topic=row[5],
            sql_query=row[6],
            tables_referenced=json.loads(row[7]) if row[7] else [],
            created_at=row[8],
            updated_at=row[9],
        )

@dataclass
class Dashboard:
    """A Metabase dashboard."""

    id: int
    name: str
    description: Optional[str]
    topic: Optional[str]
    pilotage_url: Optional[str]
    collection_id: Optional[int]

    @classmethod
    def from_row(cls, row: tuple) -> "Dashboard":
        return cls(
            id=row[0],
            name=row[1],
            description=row[2],
            topic=row[3],
            pilotage_url=row[4],
            collection_id=row[5],
        )

class CardsDB:
    """SQLite database for Metabase cards."""

    def __init__(self, db_path: Optional[Path] = DB_PATH, in_memory: bool = False):
        self.db_path = db_path
        self.in_memory = in_memory
        self._conn: Optional[sqlite3.Connection] = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            if self.in_memory:
                self._conn = sqlite3.connect(":memory:")
            else:
                if not self.db_path.exists():
                    raise FileNotFoundError(
                        f"Cards database not found at {self.db_path}. "
                        "Run sync_inventory.py to populate it."
                    )
                self._conn = sqlite3.connect(self.db_path)
        return self._conn

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # --- Schema management ---

    def init_schema(self):
        if not self.in_memory and self.db_path:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        cursor = self.conn.cursor()

        # Main cards table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cards (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                collection_id INTEGER,
                dashboard_id INTEGER,
                topic TEXT,
                sql_query TEXT,
                tables_referenced TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        """)

        # Indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cards_topic ON cards(topic)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cards_collection ON cards(collection_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cards_dashboard ON cards(dashboard_id)")

        # Full-text search table
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS cards_fts USING fts5(
                name, description, sql_query,
                content=cards, content_rowid=id
            )
        """)

        # Dashboards table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dashboards (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                topic TEXT,
                pilotage_url TEXT,
                collection_id INTEGER
            )
        """)

        # Dashboard-card relationship
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dashboard_cards (
                dashboard_id INTEGER,
                card_id INTEGER,
                position INTEGER,
                tab_name TEXT,
                FOREIGN KEY (dashboard_id) REFERENCES dashboards(id),
                FOREIGN KEY (card_id) REFERENCES cards(id),
                PRIMARY KEY (dashboard_id, card_id)
            )
        """)

        self.conn.commit()

    def save_to_file(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        file_conn = sqlite3.connect(path)
        self.conn.backup(file_conn)
        file_conn.close()

    # --- Card queries ---

    def get(self, card_id: int) -> Optional[Card]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM cards WHERE id = ?", (card_id,))
        row = cursor.fetchone()
        return Card.from_row(row) if row else None

    def all(self) -> list[Card]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM cards ORDER BY id")
        return [Card.from_row(row) for row in cursor.fetchall()]

    def by_topic(self, topic: str) -> list[Card]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM cards WHERE topic = ? ORDER BY id", (topic,))
        return [Card.from_row(row) for row in cursor.fetchall()]

    def search(self, query: str, limit: int = 50) -> list[Card]:
        """Full-text search across name, description, and SQL."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT cards.*
            FROM cards_fts
            JOIN cards ON cards_fts.rowid = cards.id
            WHERE cards_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (query, limit))
        return [Card.from_row(row) for row in cursor.fetchall()]

    def by_table(self, table_name: str) -> list[Card]:
        cursor = self.conn.cursor()
        # Use JSON contains pattern
        cursor.execute("""
            SELECT * FROM cards
            WHERE tables_referenced LIKE ?
            ORDER BY id
        """, (f'%"{table_name}"%',))
        return [Card.from_row(row) for row in cursor.fetchall()]

    def by_dashboard(self, dashboard_id: int) -> list[Card]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM cards WHERE dashboard_id = ? ORDER BY id", (dashboard_id,))
        return [Card.from_row(row) for row in cursor.fetchall()]

    def dashboards_summary(self) -> dict[int, int]:
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT dashboard_id, COUNT(*) as count
            FROM cards
            WHERE dashboard_id IS NOT NULL
            GROUP BY dashboard_id
            ORDER BY count DESC
        """)
        return {row[0]: row[1] for row in cursor.fetchall()}

    def topics_summary(self) -> dict[str, int]:
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT topic, COUNT(*) as count
            FROM cards
            GROUP BY topic
            ORDER BY count DESC
        """)
        return {row[0] or "autre": row[1] for row in cursor.fetchall()}

    def tables_summary(self) -> dict[str, int]:
        cards = self.all()
        counts: dict[str, int] = {}
        for card in cards:
            for table in card.tables_referenced:
                counts[table] = counts.get(table, 0) + 1
        return dict(sorted(counts.items(), key=lambda x: -x[1]))

    def count(self) -> int:
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM cards")
        return cursor.fetchone()[0]

    # --- Card write operations (for sync) ---

    def upsert_card(
        self,
        card_id: int,
        name: str,
        description: Optional[str],
        collection_id: Optional[int],
        dashboard_id: Optional[int],
        topic: Optional[str],
        sql_query: Optional[str],
        tables_referenced: list[str],
    ):
        now = datetime.now().isoformat()
        tables_json = json.dumps(tables_referenced)

        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO cards (id, name, description, collection_id, dashboard_id, topic, sql_query, tables_referenced, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                collection_id = excluded.collection_id,
                dashboard_id = excluded.dashboard_id,
                topic = excluded.topic,
                sql_query = excluded.sql_query,
                tables_referenced = excluded.tables_referenced,
                updated_at = excluded.updated_at
        """, (card_id, name, description, collection_id, dashboard_id, topic, sql_query, tables_json, now, now))

    def rebuild_fts(self):
        """Rebuild full-text search index."""
        cursor = self.conn.cursor()
        cursor.execute("INSERT INTO cards_fts(cards_fts) VALUES('rebuild')")
        self.conn.commit()

    def commit(self):
        self.conn.commit()

    def clear(self):
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM cards")
        cursor.execute("DELETE FROM cards_fts")
        self.conn.commit()

    # --- Dashboard operations ---

    def get_dashboard(self, dashboard_id: int) -> Optional[Dashboard]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM dashboards WHERE id = ?", (dashboard_id,))
        row = cursor.fetchone()
        return Dashboard.from_row(row) if row else None

    def all_dashboards(self) -> list[Dashboard]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM dashboards ORDER BY id")
        return [Dashboard.from_row(row) for row in cursor.fetchall()]

    def dashboards_by_topic(self, topic: str) -> list[Dashboard]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM dashboards WHERE topic = ? ORDER BY id", (topic,))
        return [Dashboard.from_row(row) for row in cursor.fetchall()]

    def upsert_dashboard(
        self,
        dashboard_id: int,
        name: str,
        description: Optional[str],
        topic: Optional[str],
        pilotage_url: Optional[str],
        collection_id: Optional[int],
    ):
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO dashboards (id, name, description, topic, pilotage_url, collection_id)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                topic = excluded.topic,
                pilotage_url = excluded.pilotage_url,
                collection_id = excluded.collection_id
        """, (dashboard_id, name, description, topic, pilotage_url, collection_id))

    def clear_dashboards(self):
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM dashboards")
        cursor.execute("DELETE FROM dashboard_cards")
        self.conn.commit()

def load_cards_db() -> CardsDB:
    return CardsDB()

if __name__ == "__main__":
    # Quick test
    db = load_cards_db()
    print(f"Total cards: {db.count()}")
    print(f"\nTopics: {db.topics_summary()}")
