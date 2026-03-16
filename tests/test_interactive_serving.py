"""Tests for interactive file serving with S3 optimizations."""

from unittest.mock import patch

from fastapi.testclient import TestClient

from web.app import app

client = TestClient(app)


@patch("web.config.USE_S3", True)
@patch("web.s3.file_exists")
@patch("web.s3.get_file_url")
def test_static_asset_redirects_to_s3_presigned_url(mock_get_url, mock_exists):
    """Static assets (.css, .js, images) should redirect to presigned S3 URL."""
    mock_exists.return_value = True
    mock_get_url.return_value = "https://s3.scw.com/bucket/app/style.css?Signature=xyz&Expires=123"

    response = client.get("/interactive/app/style.css", follow_redirects=False)

    assert response.status_code == 307
    assert "s3.scw.com" in response.headers["Location"]
    assert "Signature=" in response.headers["Location"]
    assert response.headers["Cache-Control"] == "private, max-age=300"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    mock_get_url.assert_called_once_with("app/style.css", expires_in=300)


@patch("web.config.USE_S3", True)
@patch("web.s3.stream_file")
def test_html_files_streamed_not_redirected(mock_stream):
    """HTML files should be streamed through app, not redirected to S3."""
    mock_stream.return_value = iter([b"<html>content</html>"])

    response = client.get("/interactive/app/index.html")

    assert response.status_code == 200
    assert response.headers.get("Location") is None  # No redirect
    assert b"<html>content</html>" in response.content
    mock_stream.assert_called_once()


@patch("web.s3.file_exists")
@patch("web.s3.stream_file")
def test_missing_file_returns_404(mock_stream, mock_exists):
    """Missing files should return 404."""
    mock_exists.return_value = False
    mock_stream.return_value = None

    response = client.get("/interactive/app/missing.html")

    assert response.status_code == 404


def test_python_files_blocked():
    """Python files should be blocked for security."""
    response = client.get("/interactive/app/secret.py")

    assert response.status_code == 404


def test_path_traversal_blocked():
    """Path traversal attempts should be blocked."""
    response = client.get("/interactive/../../../etc/passwd")

    assert response.status_code == 404
