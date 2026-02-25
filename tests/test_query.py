"""
Tests for lib/query.py - the public query API with logging.

Run with: pytest tests/test_query.py -v
Integration tests (require .env): pytest tests/test_query.py -v -m integration
"""

import json
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# --- Structural tests ---


def test_query_module_imports():
    """Module imports without errors."""
    from lib import query
    assert hasattr(query, 'execute_query')
    assert hasattr(query, 'execute_metabase_query')
    assert hasattr(query, 'execute_matomo_query')
    assert hasattr(query, 'CallerType')
    assert hasattr(query, 'QueryResult')
    assert hasattr(query, 'get_query_stats')
    # Re-exported classes
    assert hasattr(query, 'MatomoAPI')
    assert hasattr(query, 'MetabaseAPI')
    assert hasattr(query, 'MatomoError')
    assert hasattr(query, 'MetabaseError')


def test_caller_type_enum():
    """CallerType enum has expected values."""
    from lib.query import CallerType
    assert CallerType.AGENT.value == "agent"
    assert CallerType.APP.value == "app"


def test_query_result_dataclass():
    """QueryResult dataclass has expected fields."""
    from lib.query import QueryResult
    result = QueryResult(success=True, data={"test": 1}, execution_time_ms=100)
    assert result.success is True
    assert result.data == {"test": 1}
    assert result.error is None
    assert result.execution_time_ms == 100


def test_sources_module_is_private():
    """lib._sources exists but is marked as private."""
    from lib import _sources
    # The module should have a docstring warning it's private
    assert "PRIVATE" in _sources.__doc__


def test_public_api_exports():
    """lib.query exports the public query functions."""
    from lib import query
    # These are the public API
    assert hasattr(query, 'execute_query')
    assert hasattr(query, 'execute_metabase_query')
    assert hasattr(query, 'execute_matomo_query')
    # Classes are also re-exported
    assert hasattr(query, 'MatomoAPI')
    assert hasattr(query, 'MetabaseAPI')


def test_audit_module_exists():
    """lib._audit module exists and has expected exports."""
    from lib import _audit
    assert hasattr(_audit, 'log_query')
    assert hasattr(_audit, 'get_conversation_id')
    assert hasattr(_audit, '_get_db_connection')


# --- Unit tests (mocked) ---


class TestExecuteMetabaseQuery:
    """Tests for execute_metabase_query with mocked backend."""

    @pytest.fixture
    def mock_metabase_api(self):
        """Mock MetabaseAPI that returns a QueryResult-like object."""
        from lib._metabase import QueryResult as MetabaseQueryResult
        mock_result = MetabaseQueryResult(
            columns=["id", "name"],
            rows=[[1, "test"]],
            row_count=1,
        )

        mock_api = MagicMock()
        mock_api.execute_sql.return_value = mock_result
        mock_api.execute_card.return_value = mock_result
        mock_api.caller = "agent"
        return mock_api

    @patch('lib._audit.log_query')
    @patch('lib.query.get_metabase')
    def test_executes_sql_query(self, mock_get_metabase, mock_log, mock_metabase_api):
        from lib.query import execute_metabase_query, CallerType

        mock_get_metabase.return_value = mock_metabase_api

        result = execute_metabase_query(
            instance="stats",
            caller=CallerType.AGENT,
            sql="SELECT 1",
            database_id=2,
        )

        assert result.success is True
        assert result.data["row_count"] == 1
        mock_metabase_api.execute_sql.assert_called_once()

    @patch('lib._audit.log_query')
    @patch('lib.query.get_metabase')
    def test_executes_card_query(self, mock_get_metabase, mock_log, mock_metabase_api):
        from lib.query import execute_metabase_query, CallerType

        mock_get_metabase.return_value = mock_metabase_api

        result = execute_metabase_query(
            instance="stats",
            caller=CallerType.AGENT,
            card_id=123,
        )

        assert result.success is True
        mock_metabase_api.execute_card.assert_called_once_with(123, timeout=60)

    @patch('lib._audit.log_query')
    @patch('lib.query.get_metabase')
    def test_requires_sql_or_card_id(self, mock_get_metabase, mock_log, mock_metabase_api):
        from lib.query import execute_metabase_query, CallerType

        mock_get_metabase.return_value = mock_metabase_api

        result = execute_metabase_query(
            instance="stats",
            caller=CallerType.AGENT,
            # Neither sql nor card_id provided
        )

        assert result.success is False
        assert "sql+database_id or card_id" in result.error


class TestExecuteMatomoQuery:
    """Tests for execute_matomo_query with mocked backend."""

    @pytest.fixture
    def mock_matomo_api(self):
        """Mock MatomoAPI."""
        mock_api = MagicMock()
        mock_api.request.return_value = {"nb_visits": 100}
        mock_api.caller = "agent"
        return mock_api

    @patch('lib._audit.log_query')
    @patch('lib.query.get_matomo')
    def test_executes_matomo_query(self, mock_get_matomo, mock_log, mock_matomo_api):
        from lib.query import execute_matomo_query, CallerType

        mock_get_matomo.return_value = mock_matomo_api

        result = execute_matomo_query(
            instance="inclusion",
            caller=CallerType.AGENT,
            method="VisitsSummary.get",
            params={"idSite": 117, "period": "month", "date": "2025-12-01"},
        )

        assert result.success is True
        assert result.data == {"nb_visits": 100}
        mock_matomo_api.request.assert_called_once()


class TestExecuteQuery:
    """Tests for the generic execute_query function."""

    @patch('lib.query.execute_metabase_query')
    def test_routes_to_metabase(self, mock_metabase):
        from lib.query import execute_query, CallerType, QueryResult

        mock_metabase.return_value = QueryResult(success=True, data={})

        execute_query(
            source="metabase",
            instance="stats",
            caller=CallerType.AGENT,
            sql="SELECT 1",
            database_id=2,
        )

        mock_metabase.assert_called_once()

    @patch('lib.query.execute_matomo_query')
    def test_routes_to_matomo(self, mock_matomo):
        from lib.query import execute_query, CallerType, QueryResult

        mock_matomo.return_value = QueryResult(success=True, data={})

        execute_query(
            source="matomo",
            instance="inclusion",
            caller=CallerType.AGENT,
            method="VisitsSummary.get",
            params={"idSite": 117},
        )

        mock_matomo.assert_called_once()

    def test_unknown_source_returns_error(self):
        from lib.query import execute_query, CallerType

        result = execute_query(
            source="unknown",
            instance="test",
            caller=CallerType.AGENT,
        )

        assert result.success is False
        assert "Unknown source" in result.error


class TestQueryLogging:
    """Tests for the actual logging to SQLite."""

    @pytest.fixture
    def temp_db(self, tmp_path):
        """Create a temporary audit database."""
        db_path = tmp_path / "test_audit.db"
        return db_path

    def test_log_query_creates_record(self, temp_db):
        """log_query writes to the database."""
        from lib._audit import log_query

        # Create the table
        conn = sqlite3.connect(str(temp_db))
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS query_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                source TEXT NOT NULL,
                instance TEXT NOT NULL,
                caller TEXT NOT NULL,
                conversation_id TEXT,
                query_type TEXT,
                query_details TEXT,
                success INTEGER NOT NULL,
                error TEXT,
                execution_time_ms INTEGER,
                row_count INTEGER
            );
        """)
        conn.commit()
        conn.close()

        # Patch the db path
        with patch('lib._audit.AUDIT_DB_PATH', temp_db):
            log_query(
                source="metabase",
                instance="stats",
                caller="agent",
                conversation_id="test-conv-123",
                query_type="sql",
                query_details={"sql": "SELECT 1"},
                success=True,
                error=None,
                execution_time_ms=50,
                row_count=1,
            )

        # Verify
        conn = sqlite3.connect(str(temp_db))
        row = conn.execute("SELECT * FROM query_log ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()

        assert row is not None
        # row[2] = source, row[3] = instance, row[4] = caller
        assert row[2] == "metabase"
        assert row[3] == "stats"
        assert row[4] == "agent"
        assert row[5] == "test-conv-123"


class TestGetQueryStats:
    """Tests for get_query_stats function."""

    @pytest.fixture
    def populated_db(self, tmp_path):
        """Create a temp db with some query logs."""
        db_path = tmp_path / "test_audit.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE query_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                source TEXT NOT NULL,
                instance TEXT NOT NULL,
                caller TEXT NOT NULL,
                conversation_id TEXT,
                query_type TEXT,
                query_details TEXT,
                success INTEGER NOT NULL,
                error TEXT,
                execution_time_ms INTEGER,
                row_count INTEGER
            );
        """)
        # Insert test data
        for i in range(5):
            conn.execute(
                """INSERT INTO query_log
                   (timestamp, source, instance, caller, success, execution_time_ms)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (datetime.now(timezone.utc).isoformat(), "metabase", "stats", "agent", 1, 100)
            )
        for i in range(3):
            conn.execute(
                """INSERT INTO query_log
                   (timestamp, source, instance, caller, success, execution_time_ms)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (datetime.now(timezone.utc).isoformat(), "matomo", "inclusion", "app", 1, 200)
            )
        # One failed query
        conn.execute(
            """INSERT INTO query_log
               (timestamp, source, instance, caller, success, error, execution_time_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (datetime.now(timezone.utc).isoformat(), "metabase", "stats", "agent", 0, "timeout", 5000)
        )
        conn.commit()
        conn.close()
        return db_path

    def test_returns_stats_dict(self, populated_db):
        with patch('lib._audit.AUDIT_DB_PATH', populated_db):
            from lib.query import get_query_stats

            stats = get_query_stats()

            assert stats["total_queries"] == 9
            assert stats["successful_queries"] == 8
            assert stats["by_source"]["metabase"] == 6
            assert stats["by_source"]["matomo"] == 3
            assert stats["by_caller"]["agent"] == 6
            assert stats["by_caller"]["app"] == 3

    def test_filters_by_source(self, populated_db):
        with patch('lib._audit.AUDIT_DB_PATH', populated_db):
            from lib.query import get_query_stats

            stats = get_query_stats(source="matomo")

            assert stats["total_queries"] == 3
            assert stats["by_source"] == {"matomo": 3}


class TestConversationIdFromEnv:
    """Tests for auto-reading conversation_id from environment."""

    @patch('lib._audit.log_query')
    @patch('lib.query.get_metabase')
    def test_reads_conversation_id_from_env(self, mock_get_metabase, mock_log):
        from lib.query import execute_metabase_query, CallerType
        from lib._metabase import QueryResult as MetabaseQueryResult

        mock_result = MetabaseQueryResult(columns=["x"], rows=[[1]], row_count=1)
        mock_api = MagicMock()
        mock_api.execute_sql.return_value = mock_result
        mock_api.caller = "agent"
        mock_get_metabase.return_value = mock_api

        with patch.dict('os.environ', {'MATOMETA_CONVERSATION_ID': 'env-conv-123'}):
            from lib.query import execute_metabase_query, CallerType
            result = execute_metabase_query(
                instance="stats",
                caller=CallerType.AGENT,
                sql="SELECT 1",
                database_id=2,
                # conversation_id NOT provided
            )

        assert result.success is True


# --- Integration tests ---


@pytest.mark.integration
class TestQueryIntegration:
    """Integration tests against real APIs (requires .env)."""

    def test_metabase_query_executes(self):
        """Real Metabase query executes successfully."""
        from lib.query import execute_metabase_query, CallerType

        result = execute_metabase_query(
            instance="stats",
            caller=CallerType.AGENT,
            conversation_id="integration-test",
            sql="SELECT 1 as test",
            database_id=2,
        )

        assert result.success is True
        assert result.data["row_count"] == 1

    def test_matomo_query_executes(self):
        """Real Matomo query executes successfully."""
        from lib.query import execute_matomo_query, CallerType

        result = execute_matomo_query(
            instance="inclusion",
            caller=CallerType.AGENT,
            conversation_id="integration-test-matomo",
            method="SitesManager.getSitesWithAtLeastViewAccess",
            params={},
        )

        assert result.success is True
        assert isinstance(result.data, list)
