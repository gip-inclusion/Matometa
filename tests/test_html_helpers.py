"""Tests for web.routes.html time-display helpers (timezone localization)."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from web.helpers import format_relative_date
from web.routes.html import group_items_by_date

PARIS = ZoneInfo("Europe/Paris")


@pytest.mark.parametrize(
    "fake_now_utc,event_dt,expected",
    [
        (
            datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc),
            datetime(2026, 1, 15, 9, 30),
            "10:30",
        ),
        (
            datetime(2026, 1, 13, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 1, 12, 23, 30),
            "00:30",
        ),
        (
            datetime(2026, 1, 14, 11, 0, tzinfo=timezone.utc),
            datetime(2026, 1, 13, 15, 0),
            "hier, 16:00",
        ),
        (
            datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc),
            datetime(2026, 7, 15, 8, 0),
            "10:00",
        ),
        (
            datetime(2026, 1, 15, 11, 0, tzinfo=timezone.utc),
            datetime(2026, 1, 13, 14, 0),
            "mardi 15:00",
        ),
        (
            datetime(2026, 1, 15, 11, 0, tzinfo=timezone.utc),
            datetime(2025, 12, 25, 20, 0),
            "25/12/2025 à 21:00",
        ),
    ],
)
def test_format_relative_date_paris(mocker, fake_now_utc, event_dt, expected):
    mocker.patch("web.helpers.now_local", return_value=fake_now_utc.astimezone(PARIS))
    assert format_relative_date(event_dt) == expected


def test_group_items_late_utc_bucket(mocker):
    fake_now = datetime(2026, 1, 13, 0, 0, tzinfo=timezone.utc)
    mocker.patch("web.helpers.now_local", return_value=fake_now.astimezone(PARIS))
    items = [{"sort_date": datetime(2026, 1, 12, 23, 30)}]
    groups = group_items_by_date(items)
    assert "aujourd'hui" in groups
    assert len(groups["aujourd'hui"]) == 1
