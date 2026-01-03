"""
Tests for the Metabase cards database.

Run with: pytest tests/test_metabase_db.py -v
"""

import json
import pytest
import tempfile
from pathlib import Path

from skills.metabase_query.scripts.cards_db import CardsDB, Card, TOPICS


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_cards.db"
        db = CardsDB(db_path)
        db.init_schema()
        yield db
        db.close()


@pytest.fixture
def populated_db(temp_db):
    """Create database with sample cards."""
    db = temp_db

    # Add sample cards
    db.upsert_card(
        card_id=1,
        name="[408] File active count",
        description="Count of candidates in file active",
        collection_id=453,
        dashboard_id=408,
        topic="file-active",
        sql_query="SELECT COUNT(*) FROM candidats WHERE status = 'active'",
        tables_referenced=["candidats"],
    )
    db.upsert_card(
        card_id=2,
        name="[408] Candidatures by region",
        description="Breakdown of applications by region",
        collection_id=453,
        dashboard_id=408,
        topic="candidatures",
        sql_query="SELECT region, COUNT(*) FROM candidatures GROUP BY region",
        tables_referenced=["candidatures"],
    )
    db.upsert_card(
        card_id=3,
        name="[267] Gender demographics",
        description=None,
        collection_id=453,
        dashboard_id=267,
        topic="demographie",
        sql_query="SELECT gender, COUNT(*) FROM candidats GROUP BY gender",
        tables_referenced=["candidats"],
    )

    db.commit()
    db.rebuild_fts()
    return db


class TestSchema:
    """Test database schema."""

    def test_init_schema(self, temp_db):
        """Schema initialization creates tables."""
        cursor = temp_db.conn.cursor()

        # Check cards table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cards'")
        assert cursor.fetchone() is not None

        # Check FTS table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cards_fts'")
        assert cursor.fetchone() is not None

        # Check dashboards table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='dashboards'")
        assert cursor.fetchone() is not None

    def test_schema_columns(self, temp_db):
        """Cards table has expected columns."""
        cursor = temp_db.conn.cursor()
        cursor.execute("PRAGMA table_info(cards)")
        columns = {row[1] for row in cursor.fetchall()}

        expected = {
            "id", "name", "description", "collection_id", "dashboard_id",
            "topic", "sql_query", "tables_referenced",
            "created_at", "updated_at"
        }
        assert expected.issubset(columns)


class TestCardOperations:
    """Test card CRUD operations."""

    def test_upsert_and_get(self, temp_db):
        """Upsert card and retrieve it."""
        temp_db.upsert_card(
            card_id=100,
            name="[999] Test card",
            description="A test card",
            collection_id=453,
            dashboard_id=999,
            topic="autre",
            sql_query="SELECT 1",
            tables_referenced=["test_table"],
        )
        temp_db.commit()

        card = temp_db.get(100)
        assert card is not None
        assert card.id == 100
        assert card.name == "[999] Test card"
        assert card.description == "A test card"
        assert card.dashboard_id == 999
        assert card.topic == "autre"
        assert card.tables_referenced == ["test_table"]

    def test_get_nonexistent(self, temp_db):
        """Get nonexistent card returns None."""
        card = temp_db.get(99999)
        assert card is None

    def test_all(self, populated_db):
        """Get all cards."""
        cards = populated_db.all()
        assert len(cards) == 3
        assert all(isinstance(c, Card) for c in cards)

    def test_count(self, populated_db):
        """Count cards."""
        assert populated_db.count() == 3


class TestQueries:
    """Test query methods."""

    def test_by_topic(self, populated_db):
        """Filter by topic."""
        cards = populated_db.by_topic("file-active")
        assert len(cards) == 1
        assert cards[0].id == 1

    def test_by_topic_empty(self, populated_db):
        """Filter by nonexistent topic returns empty."""
        cards = populated_db.by_topic("nonexistent")
        assert cards == []

    def test_search(self, populated_db):
        """Full-text search."""
        cards = populated_db.search("file active")
        assert len(cards) >= 1
        # First result should be the file active card
        assert any(c.id == 1 for c in cards)

    def test_search_by_sql(self, populated_db):
        """Search finds matches in SQL."""
        cards = populated_db.search("region")
        assert len(cards) >= 1
        assert any(c.id == 2 for c in cards)

    def test_by_table(self, populated_db):
        """Filter by table reference."""
        cards = populated_db.by_table("candidats")
        assert len(cards) == 2
        ids = {c.id for c in cards}
        assert ids == {1, 3}


class TestSummaries:
    """Test summary methods."""

    def test_topics_summary(self, populated_db):
        """Get topic counts."""
        summary = populated_db.topics_summary()
        assert summary["file-active"] == 1
        assert summary["candidatures"] == 1
        assert summary["demographie"] == 1

    def test_tables_summary(self, populated_db):
        """Get table reference counts."""
        summary = populated_db.tables_summary()
        assert summary["candidats"] == 2
        assert summary["candidatures"] == 1


class TestTopicsTaxonomy:
    """Test topics constant."""

    def test_topics_defined(self):
        """All topics have descriptions."""
        assert len(TOPICS) > 0
        for topic, description in TOPICS.items():
            assert isinstance(topic, str)
            assert isinstance(description, str)
            assert len(description) > 0

    def test_expected_topics_exist(self):
        """Key topics are defined."""
        expected = ["file-active", "candidatures", "demographie", "autre"]
        for topic in expected:
            assert topic in TOPICS
