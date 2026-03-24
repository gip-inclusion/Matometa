"""
Pytest configuration for Autometa tests.

Configure test parameters here or via environment variables.
Requires DATABASE_URL to be set (PostgreSQL).
"""

import importlib
import os

os.environ.setdefault("AUTOMETA_SSE_MESSAGE_WAIT_TIMEOUT", "0.05")

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


def _truncate_all_tables():
    """Truncate all application tables (PostgreSQL)."""
    from web.db import get_db

    with get_db() as conn:
        conn.execute_raw("""
            TRUNCATE TABLE messages, conversation_tags, report_tags,
                uploaded_files, cron_runs, pinned_items, pm_commands,
                pm_heartbeat, reports, conversations, tags, schema_version,
                wishlist
                CASCADE;
        """)


@pytest.fixture
def app():
    """Create a FastAPI test app with a fresh database."""
    from web import database

    importlib.reload(database)

    from web import storage

    importlib.reload(storage)

    from web.app import app as fastapi_app

    yield fastapi_app

    _truncate_all_tables()


@pytest.fixture
def client(app):
    """Create a test client."""
    from starlette.testclient import TestClient

    return TestClient(app)
