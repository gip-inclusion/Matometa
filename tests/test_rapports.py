"""Tests for rapports routes.

Tests the /rapports/ endpoints including the .txt export feature.
"""

import pytest


@pytest.fixture
def report(app):
    from web.database import store

    report = store.create_report(
        title="Test Report",
        content="---\ndate: 2026-01-01\nwebsite: test\n---\n\n# Test Report\n\nThis is **markdown** content.",
        website="test",
        category="testing",
        user_id="test@example.com",
    )
    return report


@pytest.fixture
def conversation(app):
    from web.database import store

    return store.create_conversation(user_id="test@example.com")


@pytest.fixture
def report_with_source(app, conversation):
    from web.database import store

    return store.create_report(
        title="Linked Report",
        content="# Linked\n\nContent.",
        website="test",
        category="testing",
        user_id="test@example.com",
        source_conversation_id=conversation.id,
    )


class TestRapportTxtExport:
    """Test the .txt export endpoint."""

    def test_txt_endpoint_returns_plain_text(self, app, client, report):
        """GET /rapports/<id>.txt returns text/plain content type."""
        response = client.get(
            f"/rapports/{report.id}.txt",
            headers={"X-Forwarded-Email": "test@example.com"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain")

    def test_txt_endpoint_returns_raw_markdown(self, app, client, report):
        """GET /rapports/<id>.txt returns the raw markdown content."""
        response = client.get(
            f"/rapports/{report.id}.txt",
            headers={"X-Forwarded-Email": "test@example.com"},
        )
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "# Test Report" in content
        assert "**markdown**" in content
        assert "date: 2026-01-01" in content

    def test_txt_endpoint_nonexistent_report_returns_404(self, app, client):
        """GET /rapports/<nonexistent>.txt returns 404."""
        response = client.get(
            "/rapports/99999.txt",
            headers={"X-Forwarded-Email": "test@example.com"},
        )
        assert response.status_code == 404

    def test_txt_endpoint_utf8_encoding(self, app, client):
        """GET /rapports/<id>.txt handles UTF-8 content correctly."""
        from web.storage import store

        report = store.create_report(
            title="Rapport avec accents",
            content="# Résumé\n\nCe rapport contient des caractères spéciaux: é, è, ê, ë, à, ç, ù.",
            website="test",
            category="testing",
            user_id="test@example.com",
        )

        response = client.get(
            f"/rapports/{report.id}.txt",
            headers={"X-Forwarded-Email": "test@example.com"},
        )
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "Résumé" in content
        assert "é, è, ê, ë, à, ç, ù" in content


class TestRapportDetailView:
    """Test the report detail view includes the export button."""

    def test_detail_view_has_export_button(self, app, client, report):
        """Report detail view includes the 'Version exportable' button."""
        response = client.get(
            f"/rapports/{report.id}",
            headers={"X-Forwarded-Email": "test@example.com"},
        )
        assert response.status_code == 200
        assert b"Version exportable" in response.content
        assert f"/rapports/{report.id}.txt".encode() in response.content

    def test_detail_view_has_continue_button(self, app, client, report):
        """Report detail view still includes the 'Poursuivre l'exploration' button."""
        response = client.get(
            f"/rapports/{report.id}",
            headers={"X-Forwarded-Email": "test@example.com"},
        )
        assert response.status_code == 200
        assert b"Poursuivre l'exploration" in response.content


class TestRapportsListRedirect:
    """Test that /rapports list redirects to /rechercher."""

    def test_list_redirects_to_rechercher(self, app, client, report):
        """/rapports redirects to /rechercher?show=reports."""
        response = client.get(
            "/rapports",
            headers={"X-Forwarded-Email": "test@example.com"},
            follow_redirects=False,
        )
        assert response.status_code == 301
        assert response.headers["location"] == "/rechercher?show=reports"


def _extract_main_content(html: str) -> str:
    """Extract the innerHTML of <main id="main"> from a full page.

    This is what HTMX swaps when using hx-target="#main" hx-select="#main > *".
    """
    # Find <main ... id="main" ...>
    import re

    main_match = re.search(r'<main[^>]*\bid="main"[^>]*>', html)
    assert main_match, "Could not find <main id='main'> in response"
    start = main_match.end()
    end = html.find("</main>", start)
    assert end != -1, "Could not find </main>"
    return html[start:end]


class TestRapportHtmxNavigation:
    """Test that report content renders correctly via HTMX navigation.

    Bug: navigating to /rapports via HTMX sidebar click, then clicking a
    report, the report body stays empty. The request succeeds and HTMX swaps
    #main content, but the report markdown is never rendered into the DOM.

    Root cause: renderReportContent() and its htmx:afterSettle listener are
    defined in {% block scripts %}, which is OUTSIDE <main id="main">. HTMX's
    hx-select="#main > *" excludes it, so the function is never loaded on
    HTMX-navigated pages. The <div id="reportBody"> stays empty because no
    script ever fills it with the parsed markdown from <script id="reportRawContent">.

    Full page loads work fine (all scripts execute), which is why this only
    reproduces when navigating from another section via the sidebar.
    """

    def test_report_rendering_survives_htmx_swap(self, app, client, report):
        """After HTMX swaps #main, report content must be in the DOM.

        The report body must be server-side rendered so HTMX navigation
        (hx-select="#main > *") includes the actual content — no client-side
        JS required.
        """
        response = client.get(
            f"/rapports/{report.id}",
            headers={"X-Forwarded-Email": "test@example.com"},
        )
        assert response.status_code == 200
        html = response.content.decode("utf-8")
        main_content = _extract_main_content(html)

        assert _report_body_has_content(main_content), (
            "Report body is empty inside #main. Content must be server-side rendered so it survives HTMX navigation."
        )

    def test_report_list_items_use_htmx_boost(self, app, client, report):
        """Report list in /rechercher has hx-boost for HTMX navigation."""
        response = client.get(
            "/rechercher?show=reports",
            headers={"X-Forwarded-Email": "test@example.com"},
        )
        html = response.content.decode("utf-8")
        main_content = _extract_main_content(html)

        # Each report link should have the htmx attributes
        assert 'hx-boost="true"' in main_content
        assert 'hx-target="#main"' in main_content
        assert 'hx-select="#main > *"' in main_content

    def test_report_detail_has_rendered_html_in_main(self, app, client, report):
        """The rendered HTML must be inside #main for HTMX swaps."""
        response = client.get(
            f"/rapports/{report.id}",
            headers={"X-Forwarded-Email": "test@example.com"},
        )
        html = response.content.decode("utf-8")
        main_content = _extract_main_content(html)

        # Rendered HTML (not raw markdown) must be present
        assert "<h1" in main_content, "Heading should be rendered as HTML"
        assert "<strong>markdown</strong>" in main_content, "Bold should be rendered as HTML"
        # Front-matter should NOT leak into rendered body
        assert "---\ndate:" not in main_content


def _report_body_has_content(main_html: str) -> bool:
    """Check whether #reportBody has any meaningful content (not just empty).

    Returns True if reportBody contains rendered HTML (server-side rendering).
    Returns False if it's an empty div (client-side rendering that hasn't run).
    """
    import re

    # Match <div ... id="reportBody" ...>CONTENT</div>
    match = re.search(
        r'<div[^>]*\bid="reportBody"[^>]*>(.*?)</div>',
        main_html,
        re.DOTALL,
    )
    if not match:
        return False
    body_content = match.group(1).strip()
    return len(body_content) > 0


class TestReportAuthorInSearch:
    """Test that report author and source conversation appear in /rechercher."""

    def test_report_shows_author(self, app, client, report):
        """Report author (user_id) appears in search results."""
        response = client.get(
            "/rechercher?show=reports",
            headers={"X-Forwarded-Email": "test@example.com"},
        )
        html = response.content.decode("utf-8")
        assert "conv-item-author" in html
        assert "test" in html  # test@example.com -> "test"

    def test_report_shows_source_conversation_link(self, app, client, report_with_source, conversation):
        """Report with source_conversation_id shows a conversation link."""
        response = client.get(
            "/rechercher?show=reports",
            headers={"X-Forwarded-Email": "test@example.com"},
        )
        html = response.content.decode("utf-8")
        assert f"/explorations/{conversation.id}" in html
        assert "Conversation" in html

    def test_report_without_source_has_no_conversation_link(self, app, client, report):
        """Report without source_conversation_id has no conversation link."""
        response = client.get(
            "/rechercher?show=reports",
            headers={"X-Forwarded-Email": "test@example.com"},
        )
        html = response.content.decode("utf-8")
        main_content = _extract_main_content(html)
        # No /explorations/ link inside the report item
        assert "/explorations/" not in main_content

    def test_report_author_is_searchable(self, app, client, report):
        """Report author appears in data-search attribute for client-side filtering."""
        response = client.get(
            "/rechercher?show=reports",
            headers={"X-Forwarded-Email": "test@example.com"},
        )
        html = response.content.decode("utf-8")
        assert 'data-search="' in html
        # user_id should be in the search string
        assert "test@example.com" in html
