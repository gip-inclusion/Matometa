"""Tests for lib/query.py — the public query API."""

import pytest


def test_query_module_imports():
    from lib import query

    assert hasattr(query, "execute_query")
    assert hasattr(query, "execute_metabase_query")
    assert hasattr(query, "execute_matomo_query")
    assert hasattr(query, "CallerType")
    assert hasattr(query, "QueryResult")
    assert hasattr(query, "MatomoAPI")
    assert hasattr(query, "MetabaseAPI")
    assert hasattr(query, "MatomoError")
    assert hasattr(query, "MetabaseError")


def test_caller_type_enum():
    from lib.query import CallerType

    assert CallerType.AGENT.value == "agent"
    assert CallerType.APP.value == "app"


def test_query_result_dataclass():
    from lib.query import QueryResult

    result = QueryResult(success=True, data={"test": 1}, execution_time_ms=100)
    assert result.success is True
    assert result.data == {"test": 1}
    assert result.error is None
    assert result.execution_time_ms == 100


def test_sources_module_is_private():
    from lib import _sources

    assert "PRIVATE" in _sources.__doc__


def test_public_api_exports():
    from lib import query

    assert hasattr(query, "execute_query")
    assert hasattr(query, "execute_metabase_query")
    assert hasattr(query, "execute_matomo_query")
    assert hasattr(query, "MatomoAPI")
    assert hasattr(query, "MetabaseAPI")


def _metabase_api_mock(mocker):
    from lib._metabase import QueryResult as MetabaseQueryResult

    mock_result = MetabaseQueryResult(
        columns=["id", "name"],
        rows=[[1, "test"]],
        row_count=1,
    )
    mock_api = mocker.MagicMock()
    mock_api.execute_sql.return_value = mock_result
    mock_api.execute_card.return_value = mock_result
    mock_api.caller = "agent"
    return mock_api


def test_execute_metabase_sql(mocker):
    from lib.query import CallerType, execute_metabase_query

    mock_api = _metabase_api_mock(mocker)
    mocker.patch("lib.query.get_metabase", return_value=mock_api)

    result = execute_metabase_query(
        instance="stats",
        caller=CallerType.AGENT,
        sql="SELECT 1",
        database_id=2,
    )

    assert result.success is True
    assert result.data["row_count"] == 1
    mock_api.execute_sql.assert_called_once()


def test_execute_metabase_card(mocker):
    from lib.query import CallerType, execute_metabase_query

    mock_api = _metabase_api_mock(mocker)
    mocker.patch("lib.query.get_metabase", return_value=mock_api)

    result = execute_metabase_query(
        instance="stats",
        caller=CallerType.AGENT,
        card_id=123,
    )

    assert result.success is True
    mock_api.execute_card.assert_called_once_with(123, timeout=60)


def test_execute_metabase_requires_sql_or_card(mocker):
    from lib.query import CallerType, execute_metabase_query

    mock_api = _metabase_api_mock(mocker)
    mocker.patch("lib.query.get_metabase", return_value=mock_api)

    result = execute_metabase_query(
        instance="stats",
        caller=CallerType.AGENT,
    )

    assert result.success is False
    assert "sql+database_id or card_id" in result.error


def test_execute_matomo_query(mocker):
    from lib.query import CallerType, execute_matomo_query

    mock_api = mocker.MagicMock()
    mock_api.request.return_value = {"nb_visits": 100}
    mock_api.caller = "agent"
    mocker.patch("lib.query.get_matomo", return_value=mock_api)

    result = execute_matomo_query(
        instance="inclusion",
        caller=CallerType.AGENT,
        method="VisitsSummary.get",
        params={"idSite": 117, "period": "month", "date": "2025-12-01"},
    )

    assert result.success is True
    assert result.data == {"nb_visits": 100}
    mock_api.request.assert_called_once()


def test_execute_query_routes_to_metabase(mocker):
    from lib.query import CallerType, QueryResult, execute_query

    mock_metabase = mocker.patch("lib.query.execute_metabase_query")
    mock_metabase.return_value = QueryResult(success=True, data={})

    execute_query(
        source="metabase",
        instance="stats",
        caller=CallerType.AGENT,
        sql="SELECT 1",
        database_id=2,
    )

    mock_metabase.assert_called_once()


def test_execute_query_routes_to_matomo(mocker):
    from lib.query import CallerType, QueryResult, execute_query

    mock_matomo = mocker.patch("lib.query.execute_matomo_query")
    mock_matomo.return_value = QueryResult(success=True, data={})

    execute_query(
        source="matomo",
        instance="inclusion",
        caller=CallerType.AGENT,
        method="VisitsSummary.get",
        params={"idSite": 117},
    )

    mock_matomo.assert_called_once()


def test_execute_query_unknown_source():
    from lib.query import CallerType, execute_query

    result = execute_query(
        source="unknown",
        instance="test",
        caller=CallerType.AGENT,
    )

    assert result.success is False
    assert "Unknown source" in result.error


def test_reads_conversation_id_from_env(mocker):
    from lib._metabase import QueryResult as MetabaseQueryResult
    from lib.query import CallerType, execute_metabase_query

    mock_result = MetabaseQueryResult(columns=["x"], rows=[[1]], row_count=1)
    mock_api = mocker.MagicMock()
    mock_api.execute_sql.return_value = mock_result
    mock_api.caller = "agent"
    mocker.patch("lib.query.get_metabase", return_value=mock_api)
    mocker.patch.dict("os.environ", {"MATOMETA_CONVERSATION_ID": "env-conv-123"})

    result = execute_metabase_query(
        instance="stats",
        caller=CallerType.AGENT,
        sql="SELECT 1",
        database_id=2,
    )

    assert result.success is True


@pytest.mark.integration
class TestQueryIntegration:
    def test_metabase_query_executes(self):
        from lib.query import CallerType, execute_metabase_query

        result = execute_metabase_query(
            instance="stats",
            caller=CallerType.AGENT,
            sql="SELECT 1 as test",
            database_id=2,
        )

        assert result.success is True
        assert result.data["row_count"] == 1

    def test_matomo_query_executes(self):
        from lib.query import CallerType, execute_matomo_query

        result = execute_matomo_query(
            instance="inclusion",
            caller=CallerType.AGENT,
            method="SitesManager.getSitesWithAtLeastViewAccess",
            params={},
        )

        assert result.success is True
        assert isinstance(result.data, list)
