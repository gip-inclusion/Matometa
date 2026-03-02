"""
Regression tests for bugs found and fixed in lib/.

Each test targets a specific defect that was found and fixed. If a test
fails, it means the bug has been reintroduced.

Run with: pytest tests/test_bugs.py -v
"""

import json
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixed: _substitute_env_vars now propagates strict= when recursing
# ---------------------------------------------------------------------------


class TestEnvSubstitutionStrictRecursion:
    def test_strict_mode_raises_on_nested_dict(self):
        from lib._sources import _substitute_env_vars

        nested = {"outer": {"inner_key": "${env.TOTALLY_MISSING_VAR_XYZ}"}}
        with pytest.raises(ValueError, match="TOTALLY_MISSING_VAR_XYZ"):
            _substitute_env_vars(nested, strict=True)

    def test_strict_mode_raises_on_nested_list(self):
        from lib._sources import _substitute_env_vars

        nested = ["${env.TOTALLY_MISSING_VAR_ABC}"]
        with pytest.raises(ValueError, match="TOTALLY_MISSING_VAR_ABC"):
            _substitute_env_vars(nested, strict=True)

    def test_strict_mode_raises_on_deeply_nested(self):
        from lib._sources import _substitute_env_vars

        deeply_nested = {
            "level1": {
                "level2": [{"level3": "${env.DEEP_MISSING_VAR}"}]
            }
        }
        with pytest.raises(ValueError, match="DEEP_MISSING_VAR"):
            _substitute_env_vars(deeply_nested, strict=True)

    def test_non_strict_mode_preserves_missing_vars(self):
        from lib._sources import _substitute_env_vars

        nested = {"key": "${env.TOTALLY_MISSING_VAR}"}
        result = _substitute_env_vars(nested, strict=False)
        assert result["key"] == "${env.TOTALLY_MISSING_VAR}"


# ---------------------------------------------------------------------------
# Fixed: execute_metabase_query accepts sql without explicit database_id
# ---------------------------------------------------------------------------


class TestMetabaseQueryAcceptsSqlAlone:
    @patch("lib._audit.log_query")
    @patch("lib.query.get_metabase")
    def test_sql_without_database_id_uses_api_default(
        self, mock_get_metabase, mock_log
    ):
        from lib._metabase import QueryResult as MQR
        from lib.query import CallerType, execute_metabase_query

        mock_api = MagicMock()
        mock_api.execute_sql.return_value = MQR(
            columns=["x"], rows=[[1]], row_count=1
        )
        mock_api.caller = "agent"
        mock_get_metabase.return_value = mock_api

        result = execute_metabase_query(
            instance="stats",
            caller=CallerType.AGENT,
            sql="SELECT 1",
        )

        assert result.success is True
        mock_api.execute_sql.assert_called_once()


# ---------------------------------------------------------------------------
# Fixed: MatomoError now gets logged to audit
# ---------------------------------------------------------------------------


class TestMatomoErrorLogged:
    @patch("lib._matomo.emit_api_signal")
    @patch("lib._matomo.log_query")
    def test_api_error_is_logged_to_audit(self, mock_log, mock_signal):
        from lib._matomo import MatomoAPI, MatomoError

        api = MatomoAPI(url="fake.example.com", token="fake", instance="test")

        error_response = json.dumps(
            {"result": "error", "message": "Segment not valid"}
        ).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = error_response
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            with pytest.raises(MatomoError, match="Segment not valid"):
                api._request("VisitsSummary.get", {"idSite": 1}, timeout=10)

        assert mock_log.called, "MatomoError was not logged to audit"
        call_kwargs = mock_log.call_args.kwargs
        assert call_kwargs["success"] is False
        assert "Segment not valid" in call_kwargs["error"]


# ---------------------------------------------------------------------------
# Fixed: Metabase "status: failed" without "error" key now raises
# ---------------------------------------------------------------------------


class TestMetabaseFailedStatusRaises:
    def test_status_failed_without_error_key(self):
        from lib._metabase import MetabaseAPI, MetabaseError

        api = MetabaseAPI(
            url="https://fake.example.com", api_key="fake", database_id=2
        )

        failed_response = {
            "status": "failed",
            "data": {"cols": [], "rows": []},
        }

        with pytest.raises(MetabaseError, match="Query failed"):
            api._parse_result(failed_response)

    def test_status_failed_with_error_key(self):
        from lib._metabase import MetabaseAPI, MetabaseError

        api = MetabaseAPI(
            url="https://fake.example.com", api_key="fake", database_id=2
        )

        failed_response = {
            "status": "failed",
            "error": "Permission denied",
            "data": {"cols": [], "rows": []},
        }

        with pytest.raises(MetabaseError, match="Permission denied"):
            api._parse_result(failed_response)


# ---------------------------------------------------------------------------
# Fixed: database_id=0 is preserved (was treated as falsy)
# ---------------------------------------------------------------------------


class TestMetabaseDatabaseIdZero:
    def test_database_id_zero_is_preserved(self):
        from lib._metabase import MetabaseAPI

        api = MetabaseAPI(
            url="https://fake.example.com", api_key="fake", database_id=0
        )
        assert api.database_id == 0

    def test_database_id_none_defaults_to_2(self):
        from lib._metabase import MetabaseAPI

        api = MetabaseAPI(
            url="https://fake.example.com", api_key="fake", database_id=None
        )
        assert api.database_id == 2


# ---------------------------------------------------------------------------
# Fixed: card_id=0 is included in API signals
# ---------------------------------------------------------------------------


class TestApiSignalCardIdZero:
    def test_card_id_zero_is_included_in_signal(self):
        from lib.api_signals import emit_api_signal
        import io

        captured = io.StringIO()
        with patch("sys.stdout", captured):
            emit_api_signal(
                source="metabase",
                instance="test",
                url="https://example.com/question/0",
                card_id=0,
            )

        output = captured.getvalue()
        signal = json.loads(output.split("MATOMETA:API:")[1].rstrip("]\n"))
        assert "card_id" in signal
        assert signal["card_id"] == 0


# ---------------------------------------------------------------------------
# Fixed: search_cards query_type no longer leaks URL params
# ---------------------------------------------------------------------------


class TestMetabaseSearchQueryType:
    @patch("lib._metabase.log_query")
    @patch("lib._metabase.emit_api_signal")
    def test_search_query_type_is_clean(self, mock_signal, mock_log):
        from lib._metabase import MetabaseAPI

        api = MetabaseAPI(url="https://fake.example.com", api_key="fake")

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"data": []}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            api.search_cards("revenue")

        assert mock_log.called
        logged_query_type = mock_log.call_args.kwargs["query_type"]
        assert logged_query_type == "search"
        assert "?" not in logged_query_type
