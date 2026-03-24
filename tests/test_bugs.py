"""Regression tests for bugs fixed in lib/."""

import io
import json

import pytest


@pytest.mark.parametrize(
    "nested,match",
    [
        ({"outer": {"inner_key": "${env.TOTALLY_MISSING_VAR_XYZ}"}}, "TOTALLY_MISSING_VAR_XYZ"),
        (["${env.TOTALLY_MISSING_VAR_ABC}"], "TOTALLY_MISSING_VAR_ABC"),
        (
            {"level1": {"level2": [{"level3": "${env.DEEP_MISSING_VAR}"}]}},
            "DEEP_MISSING_VAR",
        ),
    ],
)
def test_substitute_env_vars_strict_raises(nested, match):
    from lib._sources import _substitute_env_vars

    with pytest.raises(ValueError, match=match):
        _substitute_env_vars(nested, strict=True)


def test_substitute_env_vars_non_strict_preserves_missing():
    from lib._sources import _substitute_env_vars

    nested = {"key": "${env.TOTALLY_MISSING_VAR}"}
    result = _substitute_env_vars(nested, strict=False)
    assert result["key"] == "${env.TOTALLY_MISSING_VAR}"


def test_execute_metabase_query_sql_without_database_id(mocker):
    from lib._metabase import QueryResult as MQR
    from lib.query import CallerType, execute_metabase_query

    mock_api = mocker.MagicMock()
    mock_api.execute_sql.return_value = MQR(columns=["x"], rows=[[1]], row_count=1)
    mock_api.caller = "agent"
    mocker.patch("lib.query.get_metabase", return_value=mock_api)

    result = execute_metabase_query(
        instance="stats",
        caller=CallerType.AGENT,
        sql="SELECT 1",
    )

    assert result.success is True
    mock_api.execute_sql.assert_called_once()


def test_matomo_error_on_api_error(mocker):
    from lib._matomo import MatomoAPI, MatomoError

    api = MatomoAPI(url="fake.example.com", token="fake", instance="test")

    mock_resp = mocker.MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "application/json"}
    mock_resp.text = json.dumps({"result": "error", "message": "Segment not valid"})
    mock_resp.json.return_value = {"result": "error", "message": "Segment not valid"}
    mock_resp.raise_for_status = mocker.MagicMock()
    api._session.get = mocker.MagicMock(return_value=mock_resp)

    with pytest.raises(MatomoError, match="Segment not valid"):
        api._request("VisitsSummary.get", {"idSite": 1}, timeout=10)


@pytest.mark.parametrize(
    "failed_response,match",
    [
        (
            {"status": "failed", "data": {"cols": [], "rows": []}},
            "Query failed",
        ),
        (
            {
                "status": "failed",
                "error": "Permission denied",
                "data": {"cols": [], "rows": []},
            },
            "Permission denied",
        ),
    ],
)
def test_metabase_failed_status_raises(failed_response, match):
    from lib._metabase import MetabaseAPI, MetabaseError

    api = MetabaseAPI(url="https://fake.example.com", api_key="fake", database_id=2)

    with pytest.raises(MetabaseError, match=match):
        api._parse_result(failed_response)


def test_metabase_database_id_zero_preserved():
    from lib._metabase import MetabaseAPI

    api = MetabaseAPI(url="https://fake.example.com", api_key="fake", database_id=0)
    assert api.database_id == 0


def test_metabase_database_id_none_defaults():
    from lib._metabase import MetabaseAPI

    api = MetabaseAPI(url="https://fake.example.com", api_key="fake", database_id=None)
    assert api.database_id == 2


def test_api_signal_card_id_zero(mocker):
    from lib.api_signals import emit_api_signal

    captured = io.StringIO()
    mocker.patch("sys.stdout", captured)
    emit_api_signal(
        source="metabase",
        instance="test",
        url="https://example.com/question/0",
        card_id=0,
    )

    output = captured.getvalue()
    signal = json.loads(output.split("AUTOMETA:API:")[1].rstrip("]\n"))
    assert "card_id" in signal
    assert signal["card_id"] == 0


def test_matomo_html_timeout_raises_matomo_error(mocker):
    from lib._matomo import MatomoAPI, MatomoError

    api = MatomoAPI(url="fake.example.com", token="fake", instance="test")

    mock_resp = mocker.MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "text/html"}
    mock_resp.text = "<!DOCTYPE html><html><body>Gateway Timeout</body></html>"
    mock_resp.raise_for_status = mocker.MagicMock()
    api._session.get = mocker.MagicMock(return_value=mock_resp)

    with pytest.raises(MatomoError, match="HTML instead of JSON"):
        api._request("VisitsSummary.get", {"idSite": 1}, timeout=10)


def test_signal_registry_pm_alive_on_init():
    from web.signals import SignalRegistry

    reg = SignalRegistry()
    assert reg.is_pm_alive()


def test_notify_message_does_not_create_signal():
    from web.signals import SignalRegistry

    reg = SignalRegistry()
    reg.notify_message("no-listener")
    assert "no-listener" not in reg._signals


def test_notify_finished_creates_signal():
    from web.signals import SignalRegistry

    reg = SignalRegistry()
    reg.notify_finished("no-listener")
    assert "no-listener" in reg._signals
    assert reg.is_finished("no-listener")


def test_signal_registry_counter_increments():
    from web.signals import SignalRegistry

    reg = SignalRegistry()
    sig = reg._get_or_create("conv1")
    assert sig.counter == 0
    reg.notify_message("conv1")
    assert sig.counter == 1
    reg.notify_finished("conv1")
    assert sig.counter == 2


def test_wait_returns_true_if_counter_advanced_before_wait():
    import asyncio

    from web.signals import SignalRegistry

    reg = SignalRegistry()
    reg._get_or_create("conv1")
    reg.notify_message("conv1")

    async def _run():
        return await reg.wait_for_message("conv1", timeout=0.01)

    assert asyncio.run(_run()) is True


def test_stale_finished_signals_evicted():
    from web.signals import SignalRegistry

    reg = SignalRegistry()
    reg.notify_finished("old-conv")
    reg._signals["old-conv"].created_at -= 700
    reg._evict_stale(max_age=600)
    assert "old-conv" not in reg._signals


def test_recent_finished_signals_kept():
    from web.signals import SignalRegistry

    reg = SignalRegistry()
    reg.notify_finished("fresh-conv")
    reg._evict_stale(max_age=600)
    assert "fresh-conv" in reg._signals


def test_unfinished_signals_never_evicted():
    from web.signals import SignalRegistry

    reg = SignalRegistry()
    reg._get_or_create("active-conv")
    reg._signals["active-conv"].created_at -= 700
    reg._evict_stale(max_age=600)
    assert "active-conv" in reg._signals


def test_search_cards_returns_data(mocker):
    from lib._metabase import MetabaseAPI

    api = MetabaseAPI(url="https://fake.example.com", api_key="fake")

    mock_resp = mocker.MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": []}
    mock_resp.raise_for_status = mocker.MagicMock()
    api._session.request = mocker.MagicMock(return_value=mock_resp)

    result = api.search_cards("revenue")
    assert result == []
