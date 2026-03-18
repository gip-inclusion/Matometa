"""
Tests for the Matomo API client.

Run with: pytest tests/test_matomo.py -v
Integration tests (require .env): pytest -v -m integration

Configure integration tests via environment variables:
    MATOMO_TEST_SITE_ID=117
    MATOMO_TEST_PERIOD=month
    MATOMO_TEST_DATE=2025-12-01
    MATOMO_TEST_DIMENSION_ID=1
    MATOMO_TEST_SEGMENT=pageUrl=@/gps/

Or edit conftest.py defaults.
"""

import json
from unittest.mock import MagicMock

import pytest

from lib._matomo_ui import (
    UI_MAPPING,
    format_data_source,
    get_ui_url,
)
from lib._sources import get_matomo
from lib.query import MatomoAPI, MatomoError

# --- Structural tests ---


def test_matomo_module_imports():
    """Module imports without errors."""
    from lib import _matomo, query

    assert hasattr(query, "MatomoAPI")
    assert hasattr(query, "MatomoError")
    assert hasattr(_matomo, "MatomoAPI")
    assert hasattr(_matomo, "MatomoError")


def test_ui_mapping_module_imports():
    """UI mapping module imports without errors."""
    from lib import _matomo_ui

    assert hasattr(_matomo_ui, "UI_MAPPING")
    assert hasattr(_matomo_ui, "get_ui_url")
    assert hasattr(_matomo_ui, "format_data_source")


def test_ui_mapping_is_dict():
    """UI_MAPPING is a non-empty dict with correct structure."""
    assert isinstance(UI_MAPPING, dict)
    assert len(UI_MAPPING) > 0
    for method, (category, subcategory) in UI_MAPPING.items():
        assert isinstance(method, str)
        assert "." in method, f"Method {method} should have Module.method format"
        assert isinstance(category, str)
        assert subcategory is None or isinstance(subcategory, str)


def test_matomo_api_class_has_expected_methods():
    """MatomoAPI class has all expected public methods."""
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


# --- Unit tests (mocked) ---


class TestGetUiUrl:
    """Tests for get_ui_url function."""

    def test_basic_url(self):
        url = get_ui_url(
            base_url="matomo.example.com",
            method="VisitsSummary.get",
            site_id=117,
            period="month",
            date="2025-12-01",
        )
        assert "matomo.example.com" in url
        assert "idSite=117" in url
        assert "period=month" in url
        assert "date=2025-12-01" in url
        assert "category=General_Visitors" in url
        assert "subcategory=General_Overview" in url

    def test_url_with_segment(self):
        url = get_ui_url(
            base_url="matomo.example.com",
            method="VisitsSummary.get",
            site_id=117,
            period="month",
            date="2025-12-01",
            segment="pageUrl=@/gps/",
        )
        # Segment should be in the hash fragment
        # Note: / is encoded as %2F, but @ and = are preserved
        assert "segment=pageUrl=@" in url
        assert "gps" in url

    def test_custom_dimension_url(self):
        url = get_ui_url(
            base_url="matomo.example.com",
            method="CustomDimensions.getCustomDimension",
            site_id=117,
            period="month",
            date="2025-12-01",
            dimension_id=1,
        )
        assert "subcategory=customdimension1" in url

    def test_unknown_method_falls_back_to_dashboard(self):
        url = get_ui_url(
            base_url="matomo.example.com",
            method="Unknown.method",
            site_id=117,
            period="month",
            date="2025-12-01",
        )
        assert "category=Dashboard_Dashboard" in url


class TestFormatDataSource:
    """Tests for format_data_source function."""

    def test_returns_markdown(self):
        result = format_data_source(
            base_url="matomo.example.com",
            method="VisitsSummary.get",
            params={"idSite": 117, "period": "month", "date": "2025-12-01"},
        )
        assert "[View in Matomo](" in result
        assert "`VisitsSummary.get?" in result

    def test_includes_segment_in_api_call(self):
        result = format_data_source(
            base_url="matomo.example.com",
            method="VisitsSummary.get",
            params={
                "idSite": 117,
                "period": "month",
                "date": "2025-12-01",
                "segment": "pageUrl=@/gps/",
            },
        )
        assert "segment=pageUrl=@/gps/" in result

    def test_includes_dimension_id(self):
        result = format_data_source(
            base_url="matomo.example.com",
            method="CustomDimensions.getCustomDimension",
            params={"idSite": 117, "period": "month", "date": "2025-12-01"},
            dimension_id=1,
        )
        assert "idDimension=1" in result


class TestMatomoAPIMocked:
    """Tests for MatomoAPI class with mocked HTTP."""

    @pytest.fixture
    def api(self):
        return MatomoAPI(url="matomo.example.com", token="test_token", instance="test")

    def test_init_with_explicit_credentials(self, api):
        assert api.url == "matomo.example.com"
        assert api.token == "test_token"

    def test_get_api_url_redacts_token(self, api):
        url = api.get_api_url("VisitsSummary.get", {"idSite": 117})
        # URL encoding converts [ to %5B and ] to %5D
        assert "REDACTED" in url
        assert "test_token" not in url

    def _mock_session_get(self, api, json_data):
        """Helper: mock api._session.get to return a response with given JSON."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.text = json.dumps(json_data)
        mock_resp.json.return_value = json_data
        mock_resp.raise_for_status = MagicMock()
        api._session.get = MagicMock(return_value=mock_resp)

    def test_get_visits_returns_dict(self, api):
        self._mock_session_get(api, {"nb_visits": 100, "nb_uniq_visitors": 80})
        result = api.get_visits(site_id=117, period="month", date="2025-12-01")
        assert result["nb_visits"] == 100
        assert result["nb_uniq_visitors"] == 80

    def test_get_pages_returns_list(self, api):
        self._mock_session_get(api, [{"label": "/home", "nb_visits": 50}, {"label": "/about", "nb_visits": 30}])
        result = api.get_pages(site_id=117, period="month", date="2025-12-01")
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["label"] == "/home"

    def test_api_error_raises_exception(self, api):
        self._mock_session_get(api, {"result": "error", "message": "Invalid token"})
        with pytest.raises(MatomoError, match="Invalid token"):
            api.get_visits(site_id=117, period="month", date="2025-12-01")

    def test_get_visit_frequency_returns_dict(self, api):
        self._mock_session_get(
            api,
            {"nb_visits_returning": 500, "nb_visits_new": 200, "nb_actions_returning": 2500, "bounce_rate_new": "45%"},
        )
        result = api.get_visit_frequency(site_id=117, period="month", date="2025-12-01")
        assert isinstance(result, dict)
        assert "nb_visits_returning" in result
        assert "nb_visits_new" in result


# --- Integration tests (require .env with valid credentials) ---
# Configure via environment variables or conftest.py:
#   MATOMO_TEST_SITE_ID, MATOMO_TEST_PERIOD, MATOMO_TEST_DATE,
#   MATOMO_TEST_DIMENSION_ID, MATOMO_TEST_SEGMENT


@pytest.mark.integration
class TestMatomoAPIIntegration:
    """Integration tests against the real Matomo endpoint."""

    @pytest.fixture
    def api(self):
        try:
            return get_matomo(instance="inclusion")
        except (FileNotFoundError, ValueError) as e:
            pytest.skip(f"No valid config: {e}")

    def test_get_sites_returns_list(self, api):
        """API returns list of accessible sites."""
        sites = api.get_sites()
        assert isinstance(sites, list)
        assert len(sites) > 0
        assert "idsite" in sites[0] or "idSite" in sites[0]

    def test_get_visits_returns_dict_with_expected_keys(self, api, site_id, period, date):
        """VisitsSummary.get returns dict with visit metrics."""
        result = api.get_visits(site_id=site_id, period=period, date=date)
        assert isinstance(result, dict)
        expected_keys = ["nb_visits", "nb_uniq_visitors", "nb_actions"]
        assert any(k in result for k in expected_keys)

    def test_get_pages_returns_list(self, api, site_id, period, date):
        """Actions.getPageUrls returns list of pages."""
        result = api.get_pages(site_id=site_id, period=period, date=date, limit=5)
        assert isinstance(result, list)

    def test_get_configured_dimensions_returns_list(self, api, site_id):
        """CustomDimensions.getConfiguredCustomDimensions returns list."""
        result = api.get_configured_dimensions(site_id=site_id)
        assert isinstance(result, list)

    def test_get_dimension_returns_list(self, api, site_id, period, date, dimension_id):
        """CustomDimensions.getCustomDimension returns list."""
        result = api.get_dimension(site_id=site_id, dimension_id=dimension_id, period=period, date=date)
        assert isinstance(result, list)

    def test_get_event_categories_returns_list(self, api, site_id, period, date):
        """Events.getCategory returns list."""
        result = api.get_event_categories(site_id=site_id, period=period, date=date)
        assert isinstance(result, list)

    def test_get_entry_pages_returns_list(self, api, site_id, period, date):
        """Actions.getEntryPageUrls returns list."""
        result = api.get_entry_pages(site_id=site_id, period=period, date=date, limit=5)
        assert isinstance(result, list)

    def test_get_exit_pages_returns_list(self, api, site_id, period, date):
        """Actions.getExitPageUrls returns list."""
        result = api.get_exit_pages(site_id=site_id, period=period, date=date, limit=5)
        assert isinstance(result, list)

    def test_get_visits_by_hour_returns_list(self, api, site_id, period, date):
        """VisitTime.getVisitInformationPerServerTime returns list of 24 items."""
        result = api.get_visits_by_hour(site_id=site_id, period=period, date=date)
        assert isinstance(result, list)
        assert len(result) == 24

    def test_get_visits_by_day_of_week_returns_list(self, api, site_id, period, date):
        """VisitTime.getByDayOfWeek returns list of 7 items."""
        result = api.get_visits_by_day_of_week(site_id=site_id, period=period, date=date)
        assert isinstance(result, list)
        assert len(result) == 7

    def test_get_referrers_returns_list(self, api, site_id, period, date):
        """Referrers.getReferrerType returns list."""
        result = api.get_referrers(site_id=site_id, period=period, date=date)
        assert isinstance(result, list)

    def test_segment_filter_works(self, api, site_id, period, date, segment):
        """Segment filters reduce the result set."""
        all_visits = api.get_visits(site_id=site_id, period=period, date=date)
        filtered_visits = api.get_visits(site_id=site_id, period=period, date=date, segment=segment)
        assert filtered_visits.get("nb_visits", 0) <= all_visits.get("nb_visits", 0)

    def test_get_visit_frequency_returns_dict(self, api, site_id, period, date):
        """VisitFrequency.get returns dict with new/returning metrics."""
        result = api.get_visit_frequency(site_id=site_id, period=period, date=date)
        assert isinstance(result, dict)
        # Should have metrics for returning and/or new visitors
        keys = list(result.keys())
        assert any("returning" in k or "new" in k for k in keys), f"Unexpected keys: {keys}"
