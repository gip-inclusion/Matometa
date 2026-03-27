"""Pytest configuration. Requires DATABASE_URL (PostgreSQL)."""

import importlib
import os

os.environ.setdefault("AUTOMETA_SSE_MESSAGE_WAIT_TIMEOUT", "0.05")

import pytest

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass  # dotenv not installed, rely on shell environment

MATOMO_TEST_SITE_ID = int(os.environ.get("MATOMO_TEST_SITE_ID", "117"))
MATOMO_TEST_PERIOD = os.environ.get("MATOMO_TEST_PERIOD", "month")
MATOMO_TEST_DATE = os.environ.get("MATOMO_TEST_DATE", "2025-12-01")
MATOMO_TEST_DIMENSION_ID = int(os.environ.get("MATOMO_TEST_DIMENSION_ID", "1"))
MATOMO_TEST_SEGMENT = os.environ.get("MATOMO_TEST_SEGMENT", "pageUrl=@/gps/")


def truncate_all_tables():
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
    from web import database

    importlib.reload(database)

    from web.app import app as fastapi_app

    yield fastapi_app

    truncate_all_tables()


@pytest.fixture
def client(app):
    from starlette.testclient import TestClient

    return TestClient(app)
