"""Tests for Tag Manager functionality in lib._matomo."""

import pytest
from lib._matomo import MatomoAPI
from unittest.mock import Mock, patch, MagicMock


class TestFlattenParams:
    """Test PHP array notation flattening."""

    def test_flatten_simple_dict(self):
        """Simple dict with no nesting stays unchanged."""
        api = MatomoAPI(url="matomo.example.com", token="test")
        params = {"customHtml": "<script>alert('test');</script>"}
        result = api._flatten_params(params)
        assert result == {"customHtml": "<script>alert('test');</script>"}

    def test_flatten_nested_dict(self):
        """Nested dict becomes PHP array notation."""
        api = MatomoAPI(url="matomo.example.com", token="test")
        params = {
            "parameters": {
                "customHtml": "<script></script>",
                "htmlPosition": "bodyEnd"
            }
        }
        result = api._flatten_params(params)
        assert result == {
            "parameters[customHtml]": "<script></script>",
            "parameters[htmlPosition]": "bodyEnd"
        }

    def test_flatten_list_of_dicts(self):
        """List of dicts becomes indexed PHP array notation."""
        api = MatomoAPI(url="matomo.example.com", token="test")
        params = {
            "conditions": [
                {"comparison": "equals", "actual": "ClickClasses", "expected": "btn"},
                {"comparison": "contains", "actual": "PageUrl", "expected": "/services/"}
            ]
        }
        result = api._flatten_params(params)
        assert result == {
            "conditions[0][comparison]": "equals",
            "conditions[0][actual]": "ClickClasses",
            "conditions[0][expected]": "btn",
            "conditions[1][comparison]": "contains",
            "conditions[1][actual]": "PageUrl",
            "conditions[1][expected]": "/services/"
        }

    def test_flatten_simple_list(self):
        """List of simple values becomes indexed array."""
        api = MatomoAPI(url="matomo.example.com", token="test")
        params = {"fireTriggerIds": [123, 456, 789]}
        result = api._flatten_params(params)
        assert result == {
            "fireTriggerIds[0]": 123,
            "fireTriggerIds[1]": 456,
            "fireTriggerIds[2]": 789
        }

    def test_flatten_deeply_nested(self):
        """Handles arbitrary nesting depth."""
        api = MatomoAPI(url="matomo.example.com", token="test")
        params = {
            "config": {
                "triggers": [
                    {"type": "click", "options": {"delay": 100}}
                ]
            }
        }
        result = api._flatten_params(params)
        assert result == {
            "config[triggers][0][type]": "click",
            "config[triggers][0][options][delay]": 100
        }


class TestPostSupport:
    """Test POST request support in MatomoAPI."""

    @patch('lib._matomo.requests.Session')
    def test_request_uses_post_when_specified(self, mock_session_class):
        """_request uses POST method when http_method='POST'."""
        mock_session = Mock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"value": 123}
        mock_session.post.return_value = mock_response
        mock_session_class.return_value = mock_session

        api = MatomoAPI(url="matomo.example.com", token="test_token")
        api._session = mock_session  # Override session

        result = api._request("TagManager.test", {"key": "value"}, timeout=30, http_method="POST")

        # Verify POST was called, not GET
        assert mock_session.post.called
        assert not mock_session.get.called
        assert result == {"value": 123}

    @patch('lib._matomo.requests.Session')
    def test_post_flattens_parameters(self, mock_session_class):
        """POST requests flatten nested parameters."""
        mock_session = Mock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"value": 456}
        mock_session.post.return_value = mock_response
        mock_session_class.return_value = mock_session

        api = MatomoAPI(url="matomo.example.com", token="test_token")
        api._session = mock_session

        api._request(
            "TagManager.test",
            {"conditions": [{"comparison": "equals", "actual": "test"}]},
            timeout=30,
            http_method="POST"
        )

        # Check that post was called with flattened data
        call_args = mock_session.post.call_args
        data_sent = call_args[1]['data']
        assert 'conditions[0][comparison]' in data_sent
        assert data_sent['conditions[0][comparison]'] == 'equals'
        assert data_sent['conditions[0][actual]'] == 'test'

    @patch('lib._matomo.requests.Session')
    def test_get_still_works_with_default(self, mock_session_class):
        """GET requests still work (backward compatibility)."""
        mock_session = Mock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"nb_visits": 100}
        mock_session.get.return_value = mock_response
        mock_session_class.return_value = mock_session

        api = MatomoAPI(url="matomo.example.com", token="test_token")
        api._session = mock_session

        # Default http_method is GET
        result = api._request("VisitsSummary.get", {"idSite": 117, "period": "day", "date": "today"})

        # Verify GET was called, not POST
        assert mock_session.get.called
        assert not mock_session.post.called
        assert result == {"nb_visits": 100}
