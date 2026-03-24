"""Tests for Tag Manager functionality in lib._matomo."""

import pytest

from lib._matomo import MatomoAPI


class TestFlattenParams:
    @pytest.mark.parametrize(
        "params,expected",
        [
            (
                {"customHtml": "<script>alert('test');</script>"},
                {"customHtml": "<script>alert('test');</script>"},
            ),
            (
                {"parameters": {"customHtml": "<script></script>", "htmlPosition": "bodyEnd"}},
                {
                    "parameters[customHtml]": "<script></script>",
                    "parameters[htmlPosition]": "bodyEnd",
                },
            ),
            (
                {
                    "conditions": [
                        {"comparison": "equals", "actual": "ClickClasses", "expected": "btn"},
                        {"comparison": "contains", "actual": "PageUrl", "expected": "/services/"},
                    ]
                },
                {
                    "conditions[0][comparison]": "equals",
                    "conditions[0][actual]": "ClickClasses",
                    "conditions[0][expected]": "btn",
                    "conditions[1][comparison]": "contains",
                    "conditions[1][actual]": "PageUrl",
                    "conditions[1][expected]": "/services/",
                },
            ),
            (
                {"fireTriggerIds": [123, 456, 789]},
                {"fireTriggerIds[0]": 123, "fireTriggerIds[1]": 456, "fireTriggerIds[2]": 789},
            ),
            (
                {"config": {"triggers": [{"type": "click", "options": {"delay": 100}}]}},
                {"config[triggers][0][type]": "click", "config[triggers][0][options][delay]": 100},
            ),
        ],
    )
    def test_flatten_params(self, params, expected):
        api = MatomoAPI(url="matomo.example.com", token="test")
        assert api._flatten_params(params) == expected


class TestPostSupport:
    """Test POST request support in MatomoAPI."""

    def test_request_uses_post_when_specified(self, mocker):
        """_request uses POST method when http_method='POST'."""
        mock_session_class = mocker.patch("lib._matomo.requests.Session")
        mock_session = mocker.Mock()
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.text = '{"value": 123}'
        mock_response.json.return_value = {"value": 123}
        mock_session.post.return_value = mock_response
        mock_session_class.return_value = mock_session

        api = MatomoAPI(url="matomo.example.com", token="test_token")
        api._session = mock_session

        result = api._request("TagManager.test", {"key": "value"}, timeout=30, http_method="POST")

        assert mock_session.post.called
        assert not mock_session.get.called
        assert result == {"value": 123}

    def test_post_flattens_parameters(self, mocker):
        """POST requests flatten nested parameters."""
        mock_session_class = mocker.patch("lib._matomo.requests.Session")
        mock_session = mocker.Mock()
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.text = '{"value": 456}'
        mock_response.json.return_value = {"value": 456}
        mock_session.post.return_value = mock_response
        mock_session_class.return_value = mock_session

        api = MatomoAPI(url="matomo.example.com", token="test_token")
        api._session = mock_session

        api._request(
            "TagManager.test",
            {"conditions": [{"comparison": "equals", "actual": "test"}]},
            timeout=30,
            http_method="POST",
        )

        call_args = mock_session.post.call_args
        data_sent = call_args[1]["data"]
        assert "conditions[0][comparison]" in data_sent
        assert data_sent["conditions[0][comparison]"] == "equals"
        assert data_sent["conditions[0][actual]"] == "test"

    def test_get_still_works_with_default(self, mocker):
        """GET requests still work (backward compatibility)."""
        mock_session_class = mocker.patch("lib._matomo.requests.Session")
        mock_session = mocker.Mock()
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.text = '{"nb_visits": 100}'
        mock_response.json.return_value = {"nb_visits": 100}
        mock_session.get.return_value = mock_response
        mock_session_class.return_value = mock_session

        api = MatomoAPI(url="matomo.example.com", token="test_token")
        api._session = mock_session

        result = api._request("VisitsSummary.get", {"idSite": 117, "period": "day", "date": "today"})

        assert mock_session.get.called
        assert not mock_session.post.called
        assert result == {"nb_visits": 100}

    def test_post_method_convenience(self, mocker):
        """post() method is a convenience wrapper for POST requests."""
        mock_session_class = mocker.patch("lib._matomo.requests.Session")
        mock_session = mocker.Mock()
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"value": 789}
        mock_response.text = '{"value": 789}'
        mock_session.post.return_value = mock_response
        mock_session_class.return_value = mock_session

        api = MatomoAPI(url="matomo.example.com", token="test_token")
        api._session = mock_session

        result = api.post(
            "TagManager.addContainerTrigger", timeout=30, idSite=210, idContainer="xg8aydM9", type="PageView"
        )

        assert mock_session.post.called
        assert result == {"value": 789}

        call_data = mock_session.post.call_args[1]["data"]
        assert call_data["idSite"] == 210
        assert call_data["idContainer"] == "xg8aydM9"


class TestContainerHelpers:
    """Test container-related helper methods."""

    def test_get_container(self, mocker):
        """get_container retrieves container with draft and releases."""
        mock_session_class = mocker.patch("lib._matomo.requests.Session")
        mock_session = mocker.Mock()
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {
            "idcontainer": "xg8aydM9",
            "name": "Dora_Preprod",
            "draft": {"idcontainerversion": 420, "revision": 5},
            "releases": [{"environment": "live", "idcontainerversion": 972}],
        }
        mock_response.text = '{"idcontainer": "xg8aydM9"}'
        mock_session.get.return_value = mock_response
        mock_session_class.return_value = mock_session

        api = MatomoAPI(url="matomo.example.com", token="test_token")
        api._session = mock_session

        result = api.get_container(site_id=210, container_id="xg8aydM9")

        assert result["idcontainer"] == "xg8aydM9"
        assert result["draft"]["idcontainerversion"] == 420
        assert mock_session.get.called

    def test_get_draft_version(self, mocker):
        """get_draft_version extracts draft ID from container."""
        mock_session_class = mocker.patch("lib._matomo.requests.Session")
        mock_session = mocker.Mock()
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"idcontainer": "xg8aydM9", "draft": {"idcontainerversion": 420}}
        mock_response.text = '{"idcontainer": "xg8aydM9"}'
        mock_session.get.return_value = mock_response
        mock_session_class.return_value = mock_session

        api = MatomoAPI(url="matomo.example.com", token="test_token")
        api._session = mock_session

        draft_id = api.get_draft_version(site_id=210, container_id="xg8aydM9")

        assert draft_id == 420


class TestTriggerHelpers:
    """Test trigger-related helper methods."""

    def test_add_trigger_valid_type(self, mocker):
        """add_trigger creates trigger with valid type."""
        mock_session_class = mocker.patch("lib._matomo.requests.Session")
        mock_session = mocker.Mock()
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"value": 13994}
        mock_response.text = '{"value": 13994}'
        mock_session.post.return_value = mock_response
        mock_session_class.return_value = mock_session

        api = MatomoAPI(url="matomo.example.com", token="test_token")
        api._session = mock_session

        trigger_id = api.add_trigger(
            site_id=210,
            container_id="xg8aydM9",
            version_id=420,
            trigger_type="PageView",
            name="Test Trigger",
            conditions=[{"comparison": "equals", "actual": "PageUrl", "expected": "/test"}],
        )

        assert trigger_id == 13994
        assert mock_session.post.called

    def test_add_trigger_invalid_type_raises(self):
        """add_trigger raises ValueError for invalid trigger type."""
        api = MatomoAPI(url="matomo.example.com", token="test_token")

        with pytest.raises(ValueError) as exc_info:
            api.add_trigger(
                site_id=210,
                container_id="xg8aydM9",
                version_id=420,
                trigger_type="InvalidTriggerType",
                name="Test",
                conditions=[],
            )

        assert "Invalid trigger_type" in str(exc_info.value)
        assert "AllElementsClick" in str(exc_info.value)

    def test_update_trigger(self, mocker):
        """update_trigger modifies existing trigger."""
        mock_session_class = mocker.patch("lib._matomo.requests.Session")
        mock_session = mocker.Mock()
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"value": True}
        mock_response.text = '{"value": true}'
        mock_session.post.return_value = mock_response
        mock_session_class.return_value = mock_session

        api = MatomoAPI(url="matomo.example.com", token="test_token")
        api._session = mock_session

        api.update_trigger(site_id=210, container_id="xg8aydM9", version_id=420, trigger_id=13994, name="Updated Name")

        assert mock_session.post.called
        call_data = mock_session.post.call_args[1]["data"]
        assert call_data["idTrigger"] == 13994

    def test_delete_trigger(self, mocker):
        """delete_trigger removes trigger from version."""
        mock_session_class = mocker.patch("lib._matomo.requests.Session")
        mock_session = mocker.Mock()
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"value": True}
        mock_response.text = '{"value": true}'
        mock_session.post.return_value = mock_response
        mock_session_class.return_value = mock_session

        api = MatomoAPI(url="matomo.example.com", token="test_token")
        api._session = mock_session

        api.delete_trigger(site_id=210, container_id="xg8aydM9", version_id=420, trigger_id=13994)

        assert mock_session.post.called


class TestTagHelpers:
    """Test tag-related helper methods."""

    def test_add_tag_valid_params(self, mocker):
        """add_tag creates tag with valid parameters."""
        mock_session_class = mocker.patch("lib._matomo.requests.Session")
        mock_session = mocker.Mock()
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"value": 11149}
        mock_response.text = '{"value": 11149}'
        mock_session.post.return_value = mock_response
        mock_session_class.return_value = mock_session

        api = MatomoAPI(url="matomo.example.com", token="test_token")
        api._session = mock_session

        tag_id = api.add_tag(
            site_id=210,
            container_id="xg8aydM9",
            version_id=420,
            tag_type="CustomHtml",
            name="Test Tag",
            parameters={"customHtml": "<script></script>", "htmlPosition": "bodyEnd"},
            fire_trigger_ids=[13994],
            fire_limit="once_page",
        )

        assert tag_id == 11149
        assert mock_session.post.called

    def test_add_tag_invalid_type_raises(self):
        """add_tag raises ValueError for invalid tag type."""
        api = MatomoAPI(url="matomo.example.com", token="test_token")

        with pytest.raises(ValueError) as exc_info:
            api.add_tag(
                site_id=210,
                container_id="xg8aydM9",
                version_id=420,
                tag_type="InvalidTagType",
                name="Test",
                parameters={},
                fire_trigger_ids=[],
            )

        assert "Invalid tag_type" in str(exc_info.value)
        assert "CustomHtml" in str(exc_info.value)

    def test_add_tag_invalid_fire_limit_raises(self):
        """add_tag raises ValueError for invalid fire_limit."""
        api = MatomoAPI(url="matomo.example.com", token="test_token")

        with pytest.raises(ValueError) as exc_info:
            api.add_tag(
                site_id=210,
                container_id="xg8aydM9",
                version_id=420,
                tag_type="CustomHtml",
                name="Test",
                parameters={},
                fire_trigger_ids=[],
                fire_limit="once_hour",
            )

        assert "Invalid fire_limit" in str(exc_info.value)
        assert "unlimited" in str(exc_info.value)

    def test_add_tag_invalid_html_position_raises(self):
        """add_tag validates htmlPosition for CustomHtml tags."""
        api = MatomoAPI(url="matomo.example.com", token="test_token")

        with pytest.raises(ValueError) as exc_info:
            api.add_tag(
                site_id=210,
                container_id="xg8aydM9",
                version_id=420,
                tag_type="CustomHtml",
                name="Test",
                parameters={"customHtml": "<script></script>", "htmlPosition": "invalidPosition"},
                fire_trigger_ids=[],
            )

        assert "Invalid htmlPosition" in str(exc_info.value)
        assert "bodyEnd" in str(exc_info.value)

    def test_update_tag(self, mocker):
        """update_tag modifies existing tag."""
        mock_session_class = mocker.patch("lib._matomo.requests.Session")
        mock_session = mocker.Mock()
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"value": True}
        mock_response.text = '{"value": true}'
        mock_session.post.return_value = mock_response
        mock_session_class.return_value = mock_session

        api = MatomoAPI(url="matomo.example.com", token="test_token")
        api._session = mock_session

        api.update_tag(site_id=210, container_id="xg8aydM9", version_id=420, tag_id=11149, name="Updated Tag")

        assert mock_session.post.called

    def test_delete_tag(self, mocker):
        """delete_tag removes tag."""
        mock_session_class = mocker.patch("lib._matomo.requests.Session")
        mock_session = mocker.Mock()
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"value": True}
        mock_response.text = '{"value": true}'
        mock_session.post.return_value = mock_response
        mock_session_class.return_value = mock_session

        api = MatomoAPI(url="matomo.example.com", token="test_token")
        api._session = mock_session

        api.delete_tag(210, "xg8aydM9", 420, 11149)
        assert mock_session.post.called

    def test_pause_tag(self, mocker):
        """pause_tag sets status to paused."""
        mock_session_class = mocker.patch("lib._matomo.requests.Session")
        mock_session = mocker.Mock()
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"value": True}
        mock_response.text = '{"value": true}'
        mock_session.post.return_value = mock_response
        mock_session_class.return_value = mock_session

        api = MatomoAPI(url="matomo.example.com", token="test_token")
        api._session = mock_session

        api.pause_tag(210, "xg8aydM9", 420, 11149)
        assert mock_session.post.called

    def test_resume_tag(self, mocker):
        """resume_tag sets status to active."""
        mock_session_class = mocker.patch("lib._matomo.requests.Session")
        mock_session = mocker.Mock()
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"value": True}
        mock_response.text = '{"value": true}'
        mock_session.post.return_value = mock_response
        mock_session_class.return_value = mock_session

        api = MatomoAPI(url="matomo.example.com", token="test_token")
        api._session = mock_session

        api.resume_tag(210, "xg8aydM9", 420, 11149)
        assert mock_session.post.called


class TestWorkflowHelpers:
    """Test workflow helper methods (publish, preview, export)."""

    def test_publish_version_valid_environment(self, mocker):
        """publish_version publishes to valid environment."""
        mock_session_class = mocker.patch("lib._matomo.requests.Session")
        mock_session = mocker.Mock()
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"value": True}
        mock_response.text = '{"value": true}'
        mock_session.post.return_value = mock_response
        mock_session_class.return_value = mock_session

        api = MatomoAPI(url="matomo.example.com", token="test_token")
        api._session = mock_session

        api.publish_version(site_id=210, container_id="xg8aydM9", version_id=420, environment="live")

        assert mock_session.post.called

    def test_publish_version_invalid_environment_raises(self):
        """publish_version raises ValueError for invalid environment."""
        api = MatomoAPI(url="matomo.example.com", token="test_token")

        with pytest.raises(ValueError) as exc_info:
            api.publish_version(site_id=210, container_id="xg8aydM9", version_id=420, environment="invalid_env")

        assert "Invalid environment" in str(exc_info.value)
        assert "live" in str(exc_info.value)

    def test_enable_preview(self, mocker):
        """enable_preview activates preview mode."""
        mock_session_class = mocker.patch("lib._matomo.requests.Session")
        mock_session = mocker.Mock()
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"value": True}
        mock_response.text = '{"value": true}'
        mock_session.post.return_value = mock_response
        mock_session_class.return_value = mock_session

        api = MatomoAPI(url="matomo.example.com", token="test_token")
        api._session = mock_session

        api.enable_preview(site_id=210, container_id="xg8aydM9")
        assert mock_session.post.called

    def test_disable_preview(self, mocker):
        """disable_preview deactivates preview mode."""
        mock_session_class = mocker.patch("lib._matomo.requests.Session")
        mock_session = mocker.Mock()
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"value": True}
        mock_response.text = '{"value": true}'
        mock_session.post.return_value = mock_response
        mock_session_class.return_value = mock_session

        api = MatomoAPI(url="matomo.example.com", token="test_token")
        api._session = mock_session

        api.disable_preview(site_id=210, container_id="xg8aydM9")
        assert mock_session.post.called

    def test_export_version(self, mocker):
        """export_version retrieves version data."""
        mock_session_class = mocker.patch("lib._matomo.requests.Session")
        mock_session = mocker.Mock()
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"triggers": [], "tags": [], "variables": []}
        mock_response.text = '{"triggers": [], "tags": [], "variables": []}'
        mock_session.get.return_value = mock_response
        mock_session_class.return_value = mock_session

        api = MatomoAPI(url="matomo.example.com", token="test_token")
        api._session = mock_session

        result = api.export_version(210, "xg8aydM9", 420)
        assert "triggers" in result
        assert mock_session.get.called
