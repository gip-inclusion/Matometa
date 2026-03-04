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

        deeply_nested = {"level1": {"level2": [{"level3": "${env.DEEP_MISSING_VAR}"}]}}
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
    def test_sql_without_database_id_uses_api_default(self, mock_get_metabase, mock_log):
        from lib._metabase import QueryResult as MQR
        from lib.query import CallerType, execute_metabase_query

        mock_api = MagicMock()
        mock_api.execute_sql.return_value = MQR(columns=["x"], rows=[[1]], row_count=1)
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

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.text = json.dumps({"result": "error", "message": "Segment not valid"})
        mock_resp.json.return_value = {"result": "error", "message": "Segment not valid"}
        mock_resp.raise_for_status = MagicMock()
        api._session.get = MagicMock(return_value=mock_resp)

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

        api = MetabaseAPI(url="https://fake.example.com", api_key="fake", database_id=2)

        failed_response = {
            "status": "failed",
            "data": {"cols": [], "rows": []},
        }

        with pytest.raises(MetabaseError, match="Query failed"):
            api._parse_result(failed_response)

    def test_status_failed_with_error_key(self):
        from lib._metabase import MetabaseAPI, MetabaseError

        api = MetabaseAPI(url="https://fake.example.com", api_key="fake", database_id=2)

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

        api = MetabaseAPI(url="https://fake.example.com", api_key="fake", database_id=0)
        assert api.database_id == 0

    def test_database_id_none_defaults_to_2(self):
        from lib._metabase import MetabaseAPI

        api = MetabaseAPI(url="https://fake.example.com", api_key="fake", database_id=None)
        assert api.database_id == 2


# ---------------------------------------------------------------------------
# Fixed: card_id=0 is included in API signals
# ---------------------------------------------------------------------------


class TestApiSignalCardIdZero:
    def test_card_id_zero_is_included_in_signal(self):
        import io

        from lib.api_signals import emit_api_signal

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


# ---------------------------------------------------------------------------
# Fixed: Matomo HTML timeout response raises MatomoError
# ---------------------------------------------------------------------------


class TestMatomoHtmlTimeoutRaises:
    @patch("lib._matomo.emit_api_signal")
    @patch("lib._matomo.log_query")
    def test_html_response_raises_matomo_error(self, mock_log, mock_signal):
        from lib._matomo import MatomoAPI, MatomoError

        api = MatomoAPI(url="fake.example.com", token="fake", instance="test")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "text/html"}
        mock_resp.text = "<!DOCTYPE html><html><body>Gateway Timeout</body></html>"
        mock_resp.raise_for_status = MagicMock()
        api._session.get = MagicMock(return_value=mock_resp)

        with pytest.raises(MatomoError, match="HTML instead of JSON"):
            api._request("VisitsSummary.get", {"idSite": 1}, timeout=10)

        assert mock_log.called
        assert mock_log.call_args.kwargs["success"] is False


# ---------------------------------------------------------------------------
# Fixed: SignalRegistry cold start — is_pm_alive() True on init
# ---------------------------------------------------------------------------


class TestSignalRegistryColdStart:
    def test_pm_alive_on_init(self):
        from web.signals import SignalRegistry

        reg = SignalRegistry()
        assert reg.is_pm_alive(), "PM should be considered alive immediately after init"


# ---------------------------------------------------------------------------
# Fixed: notify_message does not leak signals for unlistened conversations
# ---------------------------------------------------------------------------


class TestSignalRegistryOrphanedLeak:
    def test_notify_message_does_not_create_signal(self):
        from web.signals import SignalRegistry

        reg = SignalRegistry()
        reg.notify_message("no-listener")
        assert "no-listener" not in reg._signals

    def test_notify_finished_does_create_signal(self):
        from web.signals import SignalRegistry

        reg = SignalRegistry()
        reg.notify_finished("no-listener")
        assert "no-listener" in reg._signals
        assert reg.is_finished("no-listener")


# ---------------------------------------------------------------------------
# Fixed: monotonic counter prevents signal loss on clear/set race
# ---------------------------------------------------------------------------


class TestSignalRegistryCounter:
    def test_counter_increments_on_notify(self):
        from web.signals import SignalRegistry

        reg = SignalRegistry()
        sig = reg._get_or_create("conv1")
        assert sig.counter == 0
        reg.notify_message("conv1")
        assert sig.counter == 1
        reg.notify_finished("conv1")
        assert sig.counter == 2

    def test_wait_returns_true_if_counter_advanced_before_wait(self):
        import asyncio

        from web.signals import SignalRegistry

        reg = SignalRegistry()
        reg._get_or_create("conv1")  # register listener so notify_message doesn't no-op
        # Simulate: PM fires signal, then SSE calls wait_for_message
        reg.notify_message("conv1")

        async def _run():
            return await reg.wait_for_message("conv1", timeout=0.01)

        assert asyncio.run(_run()) is True


# ---------------------------------------------------------------------------
# Fixed: TTL eviction removes finished signals that cleanup() missed
# ---------------------------------------------------------------------------


class TestSignalRegistryEviction:
    def test_stale_finished_signals_are_evicted(self):
        from web.signals import SignalRegistry

        reg = SignalRegistry()
        reg.notify_finished("old-conv")
        # Backdate created_at to make it stale
        reg._signals["old-conv"].created_at -= 700
        reg._evict_stale(max_age=600)
        assert "old-conv" not in reg._signals

    def test_recent_finished_signals_are_kept(self):
        from web.signals import SignalRegistry

        reg = SignalRegistry()
        reg.notify_finished("fresh-conv")
        reg._evict_stale(max_age=600)
        assert "fresh-conv" in reg._signals

    def test_unfinished_signals_are_never_evicted(self):
        from web.signals import SignalRegistry

        reg = SignalRegistry()
        reg._get_or_create("active-conv")
        reg._signals["active-conv"].created_at -= 700
        reg._evict_stale(max_age=600)
        assert "active-conv" in reg._signals


class TestMetabaseSearchQueryType:
    @patch("lib._metabase.log_query")
    @patch("lib._metabase.emit_api_signal")
    def test_search_query_type_is_clean(self, mock_signal, mock_log):
        from lib._metabase import MetabaseAPI

        api = MetabaseAPI(url="https://fake.example.com", api_key="fake")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": []}
        mock_resp.raise_for_status = MagicMock()
        api._session.request = MagicMock(return_value=mock_resp)

        api.search_cards("revenue")

        assert mock_log.called
        logged_query_type = mock_log.call_args.kwargs["query_type"]
        assert logged_query_type == "search"
        assert "?" not in logged_query_type
