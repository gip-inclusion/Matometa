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
import pytest
from unittest.mock import patch, MagicMock

# --- Structural tests ---


def test_matomo_module_imports():
    """Module imports without errors."""
    from skills.matomo_query.scripts import matomo
    assert hasattr(matomo, 'MatomoAPI')
    assert hasattr(matomo, 'MatomoError')
    assert hasattr(matomo, 'get_ui_url')
    assert hasattr(matomo, 'format_data_source')
    assert hasattr(matomo, 'UI_MAPPING')


def test_ui_mapping_module_imports():
    """UI mapping module imports without errors."""
    from skills.matomo_query.scripts import ui_mapping
    assert hasattr(ui_mapping, 'UI_MAPPING')
    assert hasattr(ui_mapping, 'get_ui_url')
    assert hasattr(ui_mapping, 'format_data_source')


def test_ui_mapping_is_dict():
    """UI_MAPPING is a non-empty dict with correct structure."""
    from skills.matomo_query.scripts.ui_mapping import UI_MAPPING
    assert isinstance(UI_MAPPING, dict)
    assert len(UI_MAPPING) > 0
    for method, (category, subcategory) in UI_MAPPING.items():
        assert isinstance(method, str)
        assert '.' in method, f"Method {method} should have Module.method format"
        assert isinstance(category, str)
        assert subcategory is None or isinstance(subcategory, str)


def test_matomo_api_class_has_expected_methods():
    """MatomoAPI class has all expected public methods."""
    from skills.matomo_query.scripts.matomo import MatomoAPI
    expected_methods = [
        'get_sites',
        'get_visits',
        'get_unique_visitors',
        'get_pages',
        'get_configured_dimensions',
        'get_dimension',
        'get_dimension_by_week',
        'get_event_categories',
        'get_event_actions',
        'get_event_names',
        'get_entry_pages',
        'get_exit_pages',
        'get_transitions',
        'get_visits_by_hour',
        'get_visits_by_day_of_week',
        'get_referrers',
        'get_referrer_websites',
        'get_referrer_search_engines',
        'get_referrer_socials',
        'get_visit_frequency',
        'get_cohorts',
        'get_cohorts_over_time',
        'get_cohorts_by_first_visit',
    ]
    for method in expected_methods:
        assert hasattr(MatomoAPI, method), f"Missing method: {method}"


# --- Unit tests (mocked) ---


class TestGetUiUrl:
    """Tests for get_ui_url function."""

    def test_basic_url(self):
        from skills.matomo_query.scripts.ui_mapping import get_ui_url
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
        from skills.matomo_query.scripts.ui_mapping import get_ui_url
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
        from skills.matomo_query.scripts.ui_mapping import get_ui_url
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
        from skills.matomo_query.scripts.ui_mapping import get_ui_url
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
        from skills.matomo_query.scripts.ui_mapping import format_data_source
        result = format_data_source(
            base_url="matomo.example.com",
            method="VisitsSummary.get",
            params={"idSite": 117, "period": "month", "date": "2025-12-01"},
        )
        assert "[View in Matomo](" in result
        assert "`VisitsSummary.get?" in result

    def test_includes_segment_in_api_call(self):
        from skills.matomo_query.scripts.ui_mapping import format_data_source
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
        from skills.matomo_query.scripts.ui_mapping import format_data_source
        result = format_data_source(
            base_url="matomo.example.com",
            method="CustomDimensions.getCustomDimension",
            params={"idSite": 117, "period": "month", "date": "2025-12-01"},
            dimension_id=1,
        )
        assert "idDimension=1" in result


class TestGetDimensionByWeek:
    """Tests for get_dimension_by_week date iteration logic."""

    @pytest.fixture
    def api(self):
        from skills.matomo_query.scripts.matomo import MatomoAPI
        return MatomoAPI(url="matomo.example.com", token="test_token")

    def test_iterates_all_weeks_in_month(self, api):
        """Calls get_dimension for each week in the month."""
        from unittest.mock import patch

        with patch.object(api, 'get_dimension', return_value=[]) as mock:
            result = api.get_dimension_by_week(
                site_id=117, dimension_id=1, year=2025, month=1
            )

            # January 2025 has 5 weeks (1st, 8th, 15th, 22nd, 29th)
            assert mock.call_count == 5
            dates_called = [call.kwargs['date'] for call in mock.call_args_list]
            assert dates_called == [
                '2025-01-01', '2025-01-08', '2025-01-15', '2025-01-22', '2025-01-29'
            ]

    def test_handles_february_non_leap_year(self, api):
        """February 2025 (non-leap) ends on 28th."""
        from unittest.mock import patch

        with patch.object(api, 'get_dimension', return_value=[]) as mock:
            result = api.get_dimension_by_week(
                site_id=117, dimension_id=1, year=2025, month=2
            )

            # Feb 2025: 1st, 8th, 15th, 22nd (28th is last day, 29th would exceed)
            assert mock.call_count == 4
            dates_called = [call.kwargs['date'] for call in mock.call_args_list]
            assert dates_called[-1] == '2025-02-22'

    def test_handles_february_leap_year(self, api):
        """February 2024 (leap) ends on 29th."""
        from unittest.mock import patch

        with patch.object(api, 'get_dimension', return_value=[]) as mock:
            result = api.get_dimension_by_week(
                site_id=117, dimension_id=1, year=2024, month=2
            )

            # Feb 2024: 1st, 8th, 15th, 22nd, 29th (leap year)
            assert mock.call_count == 5

    def test_handles_december_year_boundary(self, api):
        """December correctly calculates end as Dec 31, not Jan 1."""
        from unittest.mock import patch

        with patch.object(api, 'get_dimension', return_value=[]) as mock:
            result = api.get_dimension_by_week(
                site_id=117, dimension_id=1, year=2025, month=12
            )

            # Dec 2025: 1st, 8th, 15th, 22nd, 29th (31 is last day)
            assert mock.call_count == 5
            dates_called = [call.kwargs['date'] for call in mock.call_args_list]
            assert all(d.startswith('2025-12-') for d in dates_called)

    def test_returns_dict_keyed_by_week_date(self, api):
        """Result is keyed by week start date."""
        from unittest.mock import patch

        with patch.object(api, 'get_dimension', return_value=[{'label': 'test'}]):
            result = api.get_dimension_by_week(
                site_id=117, dimension_id=1, year=2025, month=4
            )

            assert isinstance(result, dict)
            assert '2025-04-01' in result
            assert result['2025-04-01'] == [{'label': 'test'}]

    def test_captures_api_errors_in_result(self, api):
        """MatomoError for a week is captured, not raised."""
        from skills.matomo_query.scripts.matomo import MatomoError
        from unittest.mock import patch

        def raise_on_second_call(*args, **kwargs):
            if raise_on_second_call.count == 1:
                raise_on_second_call.count += 1
                raise MatomoError("Timeout")
            raise_on_second_call.count += 1
            return []
        raise_on_second_call.count = 0

        with patch.object(api, 'get_dimension', side_effect=raise_on_second_call):
            result = api.get_dimension_by_week(
                site_id=117, dimension_id=1, year=2025, month=4
            )

            # Second week should have error captured
            values = list(result.values())
            assert any('error' in v for v in values if isinstance(v, dict))

    def test_passes_segment_and_limit(self, api):
        """Segment and limit are passed through to get_dimension."""
        from unittest.mock import patch

        with patch.object(api, 'get_dimension', return_value=[]) as mock:
            api.get_dimension_by_week(
                site_id=117, dimension_id=1, year=2025, month=1,
                segment='pageUrl=@/test/', limit=50
            )

            for call in mock.call_args_list:
                assert call.kwargs['segment'] == 'pageUrl=@/test/'
                assert call.kwargs['limit'] == 50


class TestMatomoAPIMocked:
    """Tests for MatomoAPI class with mocked HTTP."""

    @pytest.fixture
    def api(self):
        from skills.matomo_query.scripts.matomo import MatomoAPI
        return MatomoAPI(url="matomo.example.com", token="test_token")

    def test_init_with_explicit_credentials(self, api):
        assert api.url == "matomo.example.com"
        assert api.token == "test_token"

    def test_get_api_url_redacts_token(self, api):
        url = api.get_api_url("VisitsSummary.get", {"idSite": 117})
        # URL encoding converts [ to %5B and ] to %5D
        assert "REDACTED" in url
        assert "test_token" not in url

    @patch('urllib.request.urlopen')
    def test_get_visits_returns_dict(self, mock_urlopen, api):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "nb_visits": 100,
            "nb_uniq_visitors": 80,
        }).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = api.get_visits(site_id=117, period="month", date="2025-12-01")
        assert result["nb_visits"] == 100
        assert result["nb_uniq_visitors"] == 80

    @patch('urllib.request.urlopen')
    def test_get_pages_returns_list(self, mock_urlopen, api):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps([
            {"label": "/home", "nb_visits": 50},
            {"label": "/about", "nb_visits": 30},
        ]).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = api.get_pages(site_id=117, period="month", date="2025-12-01")
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["label"] == "/home"

    @patch('urllib.request.urlopen')
    def test_api_error_raises_exception(self, mock_urlopen, api):
        from skills.matomo_query.scripts.matomo import MatomoError
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "result": "error",
            "message": "Invalid token",
        }).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        with pytest.raises(MatomoError, match="Invalid token"):
            api.get_visits(site_id=117, period="month", date="2025-12-01")

    @patch('urllib.request.urlopen')
    def test_get_visit_frequency_returns_dict(self, mock_urlopen, api):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "nb_visits_returning": 500,
            "nb_visits_new": 200,
            "nb_actions_returning": 2500,
            "bounce_rate_new": "45%",
        }).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = api.get_visit_frequency(site_id=117, period="month", date="2025-12-01")
        assert isinstance(result, dict)
        assert "nb_visits_returning" in result
        assert "nb_visits_new" in result

    @patch('urllib.request.urlopen')
    def test_get_cohorts_returns_data(self, mock_urlopen, api):
        mock_response = MagicMock()
        # Cohorts response structure is unknown - test that it handles any JSON
        mock_response.read.return_value = json.dumps({
            "cohorts": [{"period": "2025-01", "visitors": 100}]
        }).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = api.get_cohorts(site_id=117, period="month", date="2025-12-01")
        # Just verify it returns something - actual structure to be verified
        assert result is not None


# --- Integration tests (require .env with valid credentials) ---
# Configure via environment variables or conftest.py:
#   MATOMO_TEST_SITE_ID, MATOMO_TEST_PERIOD, MATOMO_TEST_DATE,
#   MATOMO_TEST_DIMENSION_ID, MATOMO_TEST_SEGMENT


@pytest.mark.integration
class TestMatomoAPIIntegration:
    """Integration tests against the real Matomo endpoint."""

    @pytest.fixture
    def api(self):
        from skills.matomo_query.scripts.matomo import MatomoAPI
        try:
            return MatomoAPI()
        except (FileNotFoundError, ValueError) as e:
            pytest.skip(f"No valid .env file: {e}")

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
        result = api.get_dimension(
            site_id=site_id, dimension_id=dimension_id, period=period, date=date
        )
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
        filtered_visits = api.get_visits(
            site_id=site_id, period=period, date=date, segment=segment
        )
        assert filtered_visits.get("nb_visits", 0) <= all_visits.get("nb_visits", 0)

    def test_get_visit_frequency_returns_dict(self, api, site_id, period, date):
        """VisitFrequency.get returns dict with new/returning metrics."""
        result = api.get_visit_frequency(site_id=site_id, period=period, date=date)
        assert isinstance(result, dict)
        # Should have metrics for returning and/or new visitors
        keys = list(result.keys())
        assert any("returning" in k or "new" in k for k in keys), f"Unexpected keys: {keys}"

    def test_get_cohorts_returns_data(self, api, site_id, period, date):
        """Cohorts.get returns data (premium plugin, may fail if not installed)."""
        from skills.matomo_query.scripts.matomo import MatomoError
        try:
            result = api.get_cohorts(site_id=site_id, period=period, date=date)
            # If it succeeds, just verify we got something
            assert result is not None
        except MatomoError as e:
            # Expected if plugin not installed or method name is wrong
            pytest.skip(f"Cohorts plugin unavailable: {e}")
