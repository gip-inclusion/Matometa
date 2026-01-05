"""
Pytest configuration for Matometa tests.

Configure test parameters here or via environment variables.
"""

import os
import pytest


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
