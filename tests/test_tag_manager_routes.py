"""Tests for Tag Manager dashboard routes."""

from unittest.mock import patch

MOCK_SITES = [
    {"name": "Dora", "matomo_id": 211, "container_id": "1y35glgB"},
    {"name": "Marché", "matomo_id": 136, "container_id": "RBvmJtrU"},
    {"name": "Dora preprod", "matomo_id": 210, "container_id": "xg8aydM9", "staging": True},
]

MOCK_CONTAINER = {
    "idcontainer": "1y35glgB",
    "name": "Dora",
    "draft": {"idcontainerversion": 500},
    "releases": [{"environment": "live", "idcontainerversion": 971}],
}

MOCK_LIVE_EXPORT = {
    "triggers": [
        {"idtrigger": 9001, "name": "PageView", "type": "Pageview", "conditions": []},
        {
            "idtrigger": 9002,
            "name": "Click CTA",
            "type": "AllElementsClick",
            "conditions": [
                {"actual": "ClickClasses", "comparison": "contains", "expected": "btn-cta"},
            ],
        },
    ],
    "tags": [
        {
            "idtag": 8001,
            "name": "Matomo Pageview",
            "type": "Matomo",
            "status": "active",
            "fire_trigger_ids": [9001],
            "block_trigger_ids": [],
            "fire_limit": "unlimited",
            "priority": 999,
            "parameters": {"trackingType": "pageview"},
        },
        {
            "idtag": 8002,
            "name": "CTA Tracker",
            "type": "CustomHtml",
            "status": "active",
            "fire_trigger_ids": [9002],
            "block_trigger_ids": [],
            "fire_limit": "once_page",
            "priority": 100,
            "parameters": {"customHtml": "<script>track()</script>"},
        },
    ],
    "variables": [{"name": "Matomo Configuration"}],
}

MOCK_DRAFT_EXPORT = {
    "triggers": [
        {"idtrigger": 3577, "name": "PageView", "type": "Pageview", "conditions": []},
        {"idtrigger": 3578, "name": "Click CTA", "type": "AllElementsClick", "conditions": []},
    ],
    "tags": [
        {"idtag": 2777, "name": "Matomo Pageview", "type": "Matomo"},
        {"idtag": 2778, "name": "CTA Tracker", "type": "CustomHtml"},
    ],
    "variables": [],
}


def _patch_sources():
    """Patch get_tag_manager_sites and get_matomo for route tests."""
    mock_api = type(
        "MockAPI",
        (),
        {
            "url": "matomo.example.com",
            "get_container": lambda self, *a: MOCK_CONTAINER,
            "export_version": lambda self, site_id, container_id, version_id: (
                MOCK_DRAFT_EXPORT if version_id == 500 else MOCK_LIVE_EXPORT
            ),
        },
    )()
    return (
        patch("web.routes.tag_manager.get_tag_manager_sites", return_value=MOCK_SITES),
        patch("web.routes.tag_manager.get_matomo", return_value=mock_api),
    )


class TestGetTagManagerSites:
    """Test get_tag_manager_sites config loader."""

    def test_returns_sites_from_config(self):
        with patch(
            "lib._sources.load_config",
            return_value={
                "tag_manager": {"sites": MOCK_SITES},
            },
        ):
            from lib._sources import get_tag_manager_sites

            sites = get_tag_manager_sites()
            assert len(sites) == 3
            assert sites[0]["name"] == "Dora"
            assert sites[2].get("staging") is True

    def test_returns_empty_list_when_no_config(self):
        with patch("lib._sources.load_config", return_value={}):
            from lib._sources import get_tag_manager_sites

            assert get_tag_manager_sites() == []


class TestTagManagerPages:
    """Test HTML page routes."""

    def test_tag_manager_root(self, client):
        p1, p2 = _patch_sources()
        with p1, p2:
            resp = client.get("/tag-manager")
        assert resp.status_code == 200
        assert "Tag Manager" in resp.text
        assert 'data-matomo-id="211"' in resp.text
        assert 'data-matomo-id="136"' in resp.text

    def test_tag_manager_root_has_all_sites(self, client):
        p1, p2 = _patch_sources()
        with p1, p2:
            resp = client.get("/tag-manager")
        assert "Dora" in resp.text
        assert "Marché" in resp.text
        assert "staging" in resp.text

    def test_tag_manager_site_route(self, client):
        p1, p2 = _patch_sources()
        with p1, p2:
            resp = client.get("/tag-manager/211")
        assert resp.status_code == 200
        assert 'data-selected-site="211"' in resp.text
        assert 'data-selected-trigger="null"' in resp.text

    def test_tag_manager_site_trigger_route(self, client):
        p1, p2 = _patch_sources()
        with p1, p2:
            resp = client.get("/tag-manager/211/3577")
        assert resp.status_code == 200
        assert 'data-selected-site="211"' in resp.text
        assert 'data-selected-trigger="3577"' in resp.text

    def test_no_sidebar_class(self, client):
        p1, p2 = _patch_sources()
        with p1, p2:
            resp = client.get("/tag-manager")
        assert 'class="no-sidebar"' in resp.text


class TestTagManagerAPI:
    """Test JSON API endpoints."""

    def test_api_sites_returns_config(self, client):
        p1, p2 = _patch_sources()
        with p1, p2:
            resp = client.get("/api/tag-manager/sites")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3
        assert data[0]["name"] == "Dora"

    def test_api_site_returns_live_data(self, client):
        p1, p2 = _patch_sources()
        with p1, p2:
            resp = client.get("/api/tag-manager/site/211")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["triggers"]) == 2
        assert len(data["tags"]) == 2
        assert data["triggers"][0]["name"] == "PageView"
        assert data["tags"][0]["name"] == "Matomo Pageview"

    def test_api_site_includes_draft_ids(self, client):
        p1, p2 = _patch_sources()
        with p1, p2:
            resp = client.get("/api/tag-manager/site/211")
        data = resp.json()
        # Draft IDs should be mapped by name from draft export
        pageview_trigger = next(t for t in data["triggers"] if t["name"] == "PageView")
        assert pageview_trigger["draft_id"] == 3577
        cta_tag = next(t for t in data["tags"] if t["name"] == "CTA Tracker")
        assert cta_tag["draft_id"] == 2778

    def test_api_site_not_found(self, client):
        p1, p2 = _patch_sources()
        with p1, p2:
            resp = client.get("/api/tag-manager/site/999")
        assert resp.status_code == 404

    def test_api_site_no_live_release(self, client):
        container_no_live = {
            "idcontainer": "1y35glgB",
            "draft": {"idcontainerversion": 500},
            "releases": [{"environment": "staging", "idcontainerversion": 100}],
        }
        mock_api = type(
            "MockAPI",
            (),
            {
                "url": "matomo.example.com",
                "get_container": lambda self, *a: container_no_live,
            },
        )()
        with (
            patch("web.routes.tag_manager.get_tag_manager_sites", return_value=MOCK_SITES),
            patch("web.routes.tag_manager.get_matomo", return_value=mock_api),
        ):
            resp = client.get("/api/tag-manager/site/211")
        assert resp.status_code == 200
        data = resp.json()
        assert data["triggers"] == []
        assert data["tags"] == []
        assert data["version"] is None

    def test_api_site_includes_metadata(self, client):
        p1, p2 = _patch_sources()
        with p1, p2:
            resp = client.get("/api/tag-manager/site/211")
        data = resp.json()
        assert "query_time_ms" in data
        assert "site" in data
        assert data["site"]["name"] == "Dora"
        assert "version" in data
        assert "variables" in data
