"""Tests for the Matomo API client."""

import json

import pytest

from lib._matomo_ui import (
    UI_MAPPING,
    format_data_source,
    get_ui_url,
)
from lib._sources import get_matomo
from lib.query import MatomoAPI, MatomoError
from tests.conftest import (
    MATOMO_TEST_DATE,
    MATOMO_TEST_DIMENSION_ID,
    MATOMO_TEST_PERIOD,
    MATOMO_TEST_SEGMENT,
    MATOMO_TEST_SITE_ID,
)


def test_matomo_module_imports():
    from lib import _matomo, query

    assert hasattr(query, "MatomoAPI")
    assert hasattr(query, "MatomoError")
    assert hasattr(_matomo, "MatomoAPI")
    assert hasattr(_matomo, "MatomoError")


def test_ui_mapping_module_imports():
    from lib import _matomo_ui

    assert hasattr(_matomo_ui, "UI_MAPPING")
    assert hasattr(_matomo_ui, "get_ui_url")
    assert hasattr(_matomo_ui, "format_data_source")


def test_ui_mapping_is_dict():
    assert isinstance(UI_MAPPING, dict)
    assert len(UI_MAPPING) > 0
    for method, (category, subcategory) in UI_MAPPING.items():
        assert isinstance(method, str)
        assert "." in method, f"Method {method} should have Module.method format"
        assert isinstance(category, str)
        assert subcategory is None or isinstance(subcategory, str)


def test_matomo_api_class_has_expected_methods():
    expected_methods = [
        "get_sites",
        "get_visits",
        "get_unique_visitors",
        "get_pages",
        "get_configured_dimensions",
        "get_dimension",
        "get_event_categories",
        "get_event_actions",
        "get_event_names",
        "get_entry_pages",
        "get_exit_pages",
        "get_transitions",
        "get_visits_by_hour",
        "get_visits_by_day_of_week",
        "get_referrers",
        "get_referrer_websites",
        "get_referrer_search_engines",
        "get_referrer_socials",
        "get_visit_frequency",
    ]
    for method in expected_methods:
        assert hasattr(MatomoAPI, method), f"Missing method: {method}"


@pytest.mark.parametrize(
    "method,segment,dimension_id,expected_substrings",
    [
        (
            "VisitsSummary.get",
            None,
            None,
            (
                "matomo.example.com",
                "idSite=117",
                "period=month",
                "date=2025-12-01",
                "category=General_Visitors",
                "subcategory=General_Overview",
            ),
        ),
        (
            "VisitsSummary.get",
            "pageUrl=@/gps/",
            None,
            ("segment=pageUrl=@", "gps"),
        ),
        (
            "CustomDimensions.getCustomDimension",
            None,
            1,
            ("subcategory=customdimension1",),
        ),
        (
            "Unknown.method",
            None,
            None,
            ("category=Dashboard_Dashboard",),
        ),
    ],
)
def test_get_ui_url(method, segment, dimension_id, expected_substrings):
    kwargs = dict(
        base_url="matomo.example.com",
        method=method,
        site_id=117,
        period="month",
        date="2025-12-01",
    )
    if segment is not None:
        kwargs["segment"] = segment
    if dimension_id is not None:
        kwargs["dimension_id"] = dimension_id
    url = get_ui_url(**kwargs)
    for s in expected_substrings:
        assert s in url


@pytest.mark.parametrize(
    "method,params,extra_kw,expected_substrings",
    [
        (
            "VisitsSummary.get",
            {"idSite": 117, "period": "month", "date": "2025-12-01"},
            {},
            ("[View in Matomo](", "`VisitsSummary.get?"),
        ),
        (
            "VisitsSummary.get",
            {
                "idSite": 117,
                "period": "month",
                "date": "2025-12-01",
                "segment": "pageUrl=@/gps/",
            },
            {},
            ("segment=pageUrl=@/gps/",),
        ),
        (
            "CustomDimensions.getCustomDimension",
            {"idSite": 117, "period": "month", "date": "2025-12-01"},
            {"dimension_id": 1},
            ("idDimension=1",),
        ),
    ],
)
def test_format_data_source(method, params, extra_kw, expected_substrings):
    result = format_data_source(
        base_url="matomo.example.com",
        method=method,
        params=params,
        **extra_kw,
    )
    for s in expected_substrings:
        assert s in result


def mock_session_get(mocker, api, json_data):
    mock_resp = mocker.MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "application/json"}
    mock_resp.text = json.dumps(json_data)
    mock_resp.json.return_value = json_data
    mock_resp.raise_for_status = mocker.MagicMock()
    api._session.get = mocker.MagicMock(return_value=mock_resp)


def test_matomo_api_init_and_url_redaction(mocker):
    api = MatomoAPI(url="matomo.example.com", token="test_token", instance="test")
    assert api.url == "matomo.example.com"
    assert api.token == "test_token"
    url = api.get_api_url("VisitsSummary.get", {"idSite": 117})
    assert "REDACTED" in url
    assert "test_token" not in url


def test_get_visits_returns_dict(mocker):
    api = MatomoAPI(url="matomo.example.com", token="test_token", instance="test")
    mock_session_get(mocker, api, {"nb_visits": 100, "nb_uniq_visitors": 80})
    result = api.get_visits(site_id=117, period="month", date="2025-12-01")
    assert result["nb_visits"] == 100
    assert result["nb_uniq_visitors"] == 80


def test_get_pages_returns_list(mocker):
    api = MatomoAPI(url="matomo.example.com", token="test_token", instance="test")
    mock_session_get(
        mocker,
        api,
        [{"label": "/home", "nb_visits": 50}, {"label": "/about", "nb_visits": 30}],
    )
    result = api.get_pages(site_id=117, period="month", date="2025-12-01")
    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["label"] == "/home"


def test_api_error_raises_exception(mocker):
    api = MatomoAPI(url="matomo.example.com", token="test_token", instance="test")
    mock_session_get(mocker, api, {"result": "error", "message": "Invalid token"})
    with pytest.raises(MatomoError, match="Invalid token"):
        api.get_visits(site_id=117, period="month", date="2025-12-01")


def test_get_visit_frequency_returns_dict(mocker):
    api = MatomoAPI(url="matomo.example.com", token="test_token", instance="test")
    mock_session_get(
        mocker,
        api,
        {"nb_visits_returning": 500, "nb_visits_new": 200, "nb_actions_returning": 2500, "bounce_rate_new": "45%"},
    )
    result = api.get_visit_frequency(site_id=117, period="month", date="2025-12-01")
    assert isinstance(result, dict)
    assert "nb_visits_returning" in result
    assert "nb_visits_new" in result


@pytest.mark.integration
class TestMatomoAPIIntegration:
    @pytest.fixture
    def api(self):
        try:
            return get_matomo(instance="inclusion")
        except (FileNotFoundError, ValueError) as e:
            pytest.skip(f"No valid config: {e}")

    def test_get_sites_returns_list(self, api):
        sites = api.get_sites()
        assert isinstance(sites, list)
        assert len(sites) > 0
        assert "idsite" in sites[0] or "idSite" in sites[0]

    def test_get_visits_returns_dict_with_expected_keys(self, api):
        result = api.get_visits(
            site_id=MATOMO_TEST_SITE_ID,
            period=MATOMO_TEST_PERIOD,
            date=MATOMO_TEST_DATE,
        )
        assert isinstance(result, dict)
        expected_keys = ["nb_visits", "nb_uniq_visitors", "nb_actions"]
        assert any(k in result for k in expected_keys)

    def test_get_pages_returns_list(self, api):
        result = api.get_pages(
            site_id=MATOMO_TEST_SITE_ID,
            period=MATOMO_TEST_PERIOD,
            date=MATOMO_TEST_DATE,
            limit=5,
        )
        assert isinstance(result, list)

    def test_get_configured_dimensions_returns_list(self, api):
        result = api.get_configured_dimensions(site_id=MATOMO_TEST_SITE_ID)
        assert isinstance(result, list)

    def test_get_dimension_returns_list(self, api):
        result = api.get_dimension(
            site_id=MATOMO_TEST_SITE_ID,
            dimension_id=MATOMO_TEST_DIMENSION_ID,
            period=MATOMO_TEST_PERIOD,
            date=MATOMO_TEST_DATE,
        )
        assert isinstance(result, list)

    def test_get_event_categories_returns_list(self, api):
        result = api.get_event_categories(
            site_id=MATOMO_TEST_SITE_ID,
            period=MATOMO_TEST_PERIOD,
            date=MATOMO_TEST_DATE,
        )
        assert isinstance(result, list)

    def test_get_entry_pages_returns_list(self, api):
        result = api.get_entry_pages(
            site_id=MATOMO_TEST_SITE_ID,
            period=MATOMO_TEST_PERIOD,
            date=MATOMO_TEST_DATE,
            limit=5,
        )
        assert isinstance(result, list)

    def test_get_exit_pages_returns_list(self, api):
        result = api.get_exit_pages(
            site_id=MATOMO_TEST_SITE_ID,
            period=MATOMO_TEST_PERIOD,
            date=MATOMO_TEST_DATE,
            limit=5,
        )
        assert isinstance(result, list)

    def test_get_visits_by_hour_returns_list(self, api):
        result = api.get_visits_by_hour(
            site_id=MATOMO_TEST_SITE_ID,
            period=MATOMO_TEST_PERIOD,
            date=MATOMO_TEST_DATE,
        )
        assert isinstance(result, list)
        assert len(result) == 24

    def test_get_visits_by_day_of_week_returns_list(self, api):
        result = api.get_visits_by_day_of_week(
            site_id=MATOMO_TEST_SITE_ID,
            period=MATOMO_TEST_PERIOD,
            date=MATOMO_TEST_DATE,
        )
        assert isinstance(result, list)
        assert len(result) == 7

    def test_get_referrers_returns_list(self, api):
        result = api.get_referrers(
            site_id=MATOMO_TEST_SITE_ID,
            period=MATOMO_TEST_PERIOD,
            date=MATOMO_TEST_DATE,
        )
        assert isinstance(result, list)

    def test_segment_filter_works(self, api):
        all_visits = api.get_visits(
            site_id=MATOMO_TEST_SITE_ID,
            period=MATOMO_TEST_PERIOD,
            date=MATOMO_TEST_DATE,
        )
        filtered_visits = api.get_visits(
            site_id=MATOMO_TEST_SITE_ID,
            period=MATOMO_TEST_PERIOD,
            date=MATOMO_TEST_DATE,
            segment=MATOMO_TEST_SEGMENT,
        )
        assert filtered_visits.get("nb_visits", 0) <= all_visits.get("nb_visits", 0)

    def test_get_visit_frequency_returns_dict(self, api):
        result = api.get_visit_frequency(
            site_id=MATOMO_TEST_SITE_ID,
            period=MATOMO_TEST_PERIOD,
            date=MATOMO_TEST_DATE,
        )
        assert isinstance(result, dict)
        keys = list(result.keys())
        assert any("returning" in k or "new" in k for k in keys), f"Unexpected keys: {keys}"
