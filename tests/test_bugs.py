"""
Tests that expose real bugs in lib/.

Each test targets a specific, confirmed defect. They are marked xfail so
they document the bugs without breaking CI. When a bug gets fixed, the
corresponding test will start "unexpectedly passing" — that's the signal
to remove the xfail marker.

Run with: pytest tests/test_bugs.py -v
"""

import json
import sqlite3
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Bug 1: _substitute_env_vars drops strict=True when recursing
#
# _sources.py line 48:
#     return {k: _substitute_env_vars(v) for k, v in value.items()}
#
# The `strict` parameter is never forwarded. So get_source_config() calls
# _substitute_env_vars(config, strict=True), but nested ${env.MISSING}
# values silently keep the literal string instead of raising ValueError.
# ---------------------------------------------------------------------------


class TestEnvSubstitutionStrictRecursion:
    @pytest.mark.xfail(
        reason="Bug: _substitute_env_vars doesn't pass strict= when recursing into dicts",
        strict=True,
    )
    def test_strict_mode_raises_on_nested_dict(self):
        from lib._sources import _substitute_env_vars

        nested = {"outer": {"inner_key": "${env.TOTALLY_MISSING_VAR_XYZ}"}}
        with pytest.raises(ValueError, match="TOTALLY_MISSING_VAR_XYZ"):
            _substitute_env_vars(nested, strict=True)

    @pytest.mark.xfail(
        reason="Bug: _substitute_env_vars doesn't pass strict= when recursing into lists",
        strict=True,
    )
    def test_strict_mode_raises_on_nested_list(self):
        from lib._sources import _substitute_env_vars

        nested = ["${env.TOTALLY_MISSING_VAR_ABC}"]
        with pytest.raises(ValueError, match="TOTALLY_MISSING_VAR_ABC"):
            _substitute_env_vars(nested, strict=True)

    @pytest.mark.xfail(
        reason="Bug: strict= lost through multiple nesting levels",
        strict=True,
    )
    def test_strict_mode_raises_on_deeply_nested(self):
        from lib._sources import _substitute_env_vars

        deeply_nested = {
            "level1": {
                "level2": [{"level3": "${env.DEEP_MISSING_VAR}"}]
            }
        }
        with pytest.raises(ValueError, match="DEEP_MISSING_VAR"):
            _substitute_env_vars(deeply_nested, strict=True)


# ---------------------------------------------------------------------------
# Bug 2: execute_metabase_query rejects sql when database_id is omitted
#
# query.py line 82:
#     if sql and database_id is not None:
#
# MetabaseAPI always has a database_id (defaults to 2). But the gateway
# function requires the caller to also pass database_id explicitly.
# Passing sql= alone returns a confusing "sql+database_id or card_id"
# error even though the underlying API would handle it fine.
# ---------------------------------------------------------------------------


class TestMetabaseQueryRequiresExplicitDatabaseId:
    @pytest.mark.xfail(
        reason="Bug: execute_metabase_query rejects sql when database_id is None",
        strict=True,
    )
    @patch("lib._audit.log_query")
    @patch("lib.query.get_metabase")
    def test_sql_without_database_id_should_use_api_default(
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
            # database_id intentionally omitted — API has a default
        )

        assert result.success is True, (
            f"sql without database_id should work (API defaults to 2), "
            f"but got: {result.error}"
        )


# ---------------------------------------------------------------------------
# Bug 3: MatomoError is never logged to audit
#
# _matomo.py lines 119-121:
#     except MatomoError:
#         execution_time_ms = ...
#         raise
#
# When the API returns {"result": "error"}, a MatomoError is raised inside
# the try block (line 79), caught by the specific MatomoError handler
# (line 119), and re-raised WITHOUT calling log_query(). API-level errors
# (bad segment, permission denied, invalid params) are invisible to audit.
# ---------------------------------------------------------------------------


class TestMatomoErrorNotLogged:
    @pytest.mark.xfail(
        reason="Bug: MatomoError handler re-raises without calling log_query",
        strict=True,
    )
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

        # The error should have been logged as a failure
        assert mock_log.called, "MatomoError was not logged to audit"
        logged_success = mock_log.call_args.kwargs.get(
            "success", mock_log.call_args[0][7] if len(mock_log.call_args[0]) > 7 else None
        )
        assert logged_success is False, "MatomoError should be logged as failure"


# ---------------------------------------------------------------------------
# Bug 4: Metabase "status: failed" without "error" key = silent empty success
#
# _metabase.py line 218:
#     if data.get("error"):
#
# Metabase can return {"status": "failed", ...} without a top-level "error".
# _parse_result only checks data.get("error") and misses the failed status,
# returning a 0-row QueryResult that looks like a successful empty query.
# ---------------------------------------------------------------------------


class TestMetabaseSilentFailure:
    @pytest.mark.xfail(
        reason="Bug: _parse_result doesn't check 'status' field, only 'error'",
        strict=True,
    )
    def test_status_failed_without_error_key_should_raise(self):
        from lib._metabase import MetabaseAPI, MetabaseError

        api = MetabaseAPI(
            url="https://fake.example.com", api_key="fake", database_id=2
        )

        failed_response = {
            "status": "failed",
            "data": {"cols": [], "rows": []},
        }

        # Should raise MetabaseError, not return empty QueryResult
        with pytest.raises(MetabaseError):
            api._parse_result(failed_response)


# ---------------------------------------------------------------------------
# Bug 5: database_id=0 silently becomes database_id=2
#
# _metabase.py line 123:
#     self.database_id = database_id or 2
#
# Classic Python falsy bug. 0 is a valid database ID but `0 or 2 == 2`.
# Fix: `database_id if database_id is not None else 2`
# ---------------------------------------------------------------------------


class TestMetabaseFalsyDatabaseId:
    @pytest.mark.xfail(
        reason="Bug: `database_id or 2` treats 0 as falsy",
        strict=True,
    )
    def test_database_id_zero_is_preserved(self):
        from lib._metabase import MetabaseAPI

        api = MetabaseAPI(
            url="https://fake.example.com", api_key="fake", database_id=0
        )

        assert api.database_id == 0, (
            f"database_id=0 should be kept, got {api.database_id}"
        )


# ---------------------------------------------------------------------------
# Bug 6: card_id=0 silently dropped from API signals
#
# api_signals.py line 56:
#     if card_id:
#
# Same falsy bug. card_id=0 is dropped from the signal dict.
# Fix: `if card_id is not None:`
# ---------------------------------------------------------------------------


class TestApiSignalFalsyCardId:
    @pytest.mark.xfail(
        reason="Bug: `if card_id:` drops card_id=0",
        strict=True,
    )
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

        assert "card_id" in signal, "card_id=0 was dropped (falsy check)"
        assert signal["card_id"] == 0


# ---------------------------------------------------------------------------
# Bug 7: search_cards query_type leaks URL parameters into audit log
#
# _metabase.py line 309:
#     result = self._request("GET", f"/api/search?{params}")
#
# _request auto-detects query_type from the endpoint (line 141):
#     endpoint.split("/")[2]  →  "search?q=revenue&models=card&limit=50"
#
# The full query string bleeds into the query_type field in the audit log.
# ---------------------------------------------------------------------------


class TestMetabaseSearchCardLogging:
    @pytest.mark.xfail(
        reason="Bug: query_type for search_cards contains URL params",
        strict=True,
    )
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
        logged_query_type = mock_log.call_args.kwargs.get(
            "query_type",
            mock_log.call_args[0][5] if len(mock_log.call_args[0]) > 5 else None,
        )

        assert "?" not in str(logged_query_type), (
            f"query_type should not contain URL params, got: {logged_query_type}"
        )
