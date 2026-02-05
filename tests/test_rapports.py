"""Tests for rapports routes.

Tests the /rapports/ endpoints including the .txt export feature.
"""

import pytest
import tempfile
import os


@pytest.fixture
def app():
    """Create a Flask test app with an in-memory database."""
    from pathlib import Path
    import importlib

    db_fd, db_path = tempfile.mkstemp()

    from web import config
    original_path = config.SQLITE_PATH
    config.SQLITE_PATH = Path(db_path)

    from web import database
    importlib.reload(database)

    from web import storage
    importlib.reload(storage)

    from web.app import app as flask_app
    flask_app.config["TESTING"] = True

    yield flask_app

    config.SQLITE_PATH = original_path
    os.close(db_fd)
    os.unlink(db_path)


@pytest.fixture
def client(app):
    """Create a test client."""
    return app.test_client()


@pytest.fixture
def report(app):
    """Create a test report."""
    from web.storage import store

    with app.test_request_context():
        report = store.create_report(
            title="Test Report",
            content="---\ndate: 2026-01-01\nwebsite: test\n---\n\n# Test Report\n\nThis is **markdown** content.",
            website="test",
            category="testing",
            user_id="test@example.com",
        )
        return report


class TestRapportTxtExport:
    """Test the .txt export endpoint."""

    def test_txt_endpoint_returns_plain_text(self, app, client, report):
        """GET /rapports/<id>.txt returns text/plain content type."""
        response = client.get(
            f"/rapports/{report.id}.txt",
            headers={"X-Forwarded-Email": "test@example.com"},
        )
        assert response.status_code == 200
        assert response.content_type.startswith("text/plain")

    def test_txt_endpoint_returns_raw_markdown(self, app, client, report):
        """GET /rapports/<id>.txt returns the raw markdown content."""
        response = client.get(
            f"/rapports/{report.id}.txt",
            headers={"X-Forwarded-Email": "test@example.com"},
        )
        assert response.status_code == 200
        content = response.data.decode("utf-8")
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

        with app.test_request_context():
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
        content = response.data.decode("utf-8")
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
        assert b"Version exportable" in response.data
        assert f"/rapports/{report.id}.txt".encode() in response.data

    def test_detail_view_has_continue_button(self, app, client, report):
        """Report detail view still includes the 'Poursuivre l'exploration' button."""
        response = client.get(
            f"/rapports/{report.id}",
            headers={"X-Forwarded-Email": "test@example.com"},
        )
        assert response.status_code == 200
        assert b"Poursuivre l'exploration" in response.data


class TestRapportsListView:
    """Test the reports list view."""

    def test_list_view_does_not_have_export_button(self, app, client, report):
        """Reports list view does not show the export button."""
        response = client.get(
            "/rapports",
            headers={"X-Forwarded-Email": "test@example.com"},
        )
        assert response.status_code == 200
        # The export button should only appear on detail view
        assert b"Version exportable" not in response.data
