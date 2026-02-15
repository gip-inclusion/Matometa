"""
Pytest configuration for Matometa tests.

Configure test parameters here or via environment variables.
"""

import importlib
import os
import tempfile
from pathlib import Path

import pytest

# Load .env file for integration tests
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not installed, rely on shell environment


# Matomo test configuration - override via environment variables if needed
MATOMO_TEST_SITE_ID = int(os.environ.get("MATOMO_TEST_SITE_ID", "117"))
MATOMO_TEST_PERIOD = os.environ.get("MATOMO_TEST_PERIOD", "month")
MATOMO_TEST_DATE = os.environ.get("MATOMO_TEST_DATE", "2025-12-01")
MATOMO_TEST_DIMENSION_ID = int(os.environ.get("MATOMO_TEST_DIMENSION_ID", "1"))
MATOMO_TEST_SEGMENT = os.environ.get("MATOMO_TEST_SEGMENT", "pageUrl=@/gps/")


@pytest.fixture
def site_id():
    """Test site ID."""
    return MATOMO_TEST_SITE_ID


@pytest.fixture
def period():
    """Test period."""
    return MATOMO_TEST_PERIOD


@pytest.fixture
def date():
    """Test date."""
    return MATOMO_TEST_DATE


@pytest.fixture
def dimension_id():
    """Test dimension ID."""
    return MATOMO_TEST_DIMENSION_ID


@pytest.fixture
def segment():
    """Test segment filter."""
    return MATOMO_TEST_SEGMENT


@pytest.fixture
def app():
    """Create a Flask test app with a temporary database."""
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
