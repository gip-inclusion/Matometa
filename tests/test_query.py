"""
Tests for lib/query.py - the public query API.

Run with: pytest tests/test_query.py -v
Integration tests (require .env): pytest tests/test_query.py -v -m integration
"""

from unittest.mock import MagicMock, patch

import pytest

# --- Structural tests ---


def test_query_module_imports():
    """Module imports without errors."""
    from lib import query

    assert hasattr(query, "execute_query")
    assert hasattr(query, "execute_metabase_query")
    assert hasattr(query, "execute_matomo_query")
    assert hasattr(query, "CallerType")
    assert hasattr(query, "QueryResult")
    # Re-exported classes
    assert hasattr(query, "MatomoAPI")
    assert hasattr(query, "MetabaseAPI")
    assert hasattr(query, "MatomoError")
    assert hasattr(query, "MetabaseError")


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
    assert hasattr(query, "execute_query")
    assert hasattr(query, "execute_metabase_query")
    assert hasattr(query, "execute_matomo_query")
    # Classes are also re-exported
    assert hasattr(query, "MatomoAPI")
    assert hasattr(query, "MetabaseAPI")


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

    @patch("lib.query.get_metabase")
    def test_executes_sql_query(self, mock_get_metabase, mock_metabase_api):
        from lib.query import CallerType, execute_metabase_query

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

    @patch("lib.query.get_metabase")
    def test_executes_card_query(self, mock_get_metabase, mock_metabase_api):
        from lib.query import CallerType, execute_metabase_query

        mock_get_metabase.return_value = mock_metabase_api

        result = execute_metabase_query(
            instance="stats",
            caller=CallerType.AGENT,
            card_id=123,
        )

        assert result.success is True
        mock_metabase_api.execute_card.assert_called_once_with(123, timeout=60)

    @patch("lib.query.get_metabase")
    def test_requires_sql_or_card_id(self, mock_get_metabase, mock_metabase_api):
        from lib.query import CallerType, execute_metabase_query

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

    @patch("lib.query.get_matomo")
    def test_executes_matomo_query(self, mock_get_matomo, mock_matomo_api):
        from lib.query import CallerType, execute_matomo_query

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

    @patch("lib.query.execute_metabase_query")
    def test_routes_to_metabase(self, mock_metabase):
        from lib.query import CallerType, QueryResult, execute_query

        mock_metabase.return_value = QueryResult(success=True, data={})

        execute_query(
            source="metabase",
            instance="stats",
            caller=CallerType.AGENT,
            sql="SELECT 1",
            database_id=2,
        )

        mock_metabase.assert_called_once()

    @patch("lib.query.execute_matomo_query")
    def test_routes_to_matomo(self, mock_matomo):
        from lib.query import CallerType, QueryResult, execute_query

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
        from lib.query import CallerType, execute_query

        result = execute_query(
            source="unknown",
            instance="test",
            caller=CallerType.AGENT,
        )

        assert result.success is False
        assert "Unknown source" in result.error


class TestConversationIdFromEnv:
    """Tests for auto-reading conversation_id from environment."""

    @patch("lib.query.get_metabase")
    def test_reads_conversation_id_from_env(self, mock_get_metabase):
        from lib._metabase import QueryResult as MetabaseQueryResult
        from lib.query import CallerType, execute_metabase_query

        mock_result = MetabaseQueryResult(columns=["x"], rows=[[1]], row_count=1)
        mock_api = MagicMock()
        mock_api.execute_sql.return_value = mock_result
        mock_api.caller = "agent"
        mock_get_metabase.return_value = mock_api

        with patch.dict("os.environ", {"MATOMETA_CONVERSATION_ID": "env-conv-123"}):
            from lib.query import CallerType, execute_metabase_query

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
        from lib.query import CallerType, execute_metabase_query

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
        from lib.query import CallerType, execute_matomo_query

        result = execute_matomo_query(
            instance="inclusion",
            caller=CallerType.AGENT,
            conversation_id="integration-test-matomo",
            method="SitesManager.getSitesWithAtLeastViewAccess",
            params={},
        )

        assert result.success is True
        assert isinstance(result.data, list)
