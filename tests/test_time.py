"""Timestamp policy tests (ARCHITECTURE §6)."""

from datetime import datetime, timedelta, timezone

import pytest

from services.ingestion.timeutil import (
    ensure_utc,
    forecast_intervals,
    iso_utc,
    local_display,
    parse_utc,
)


def test_naive_datetime_rejected():
    with pytest.raises(ValueError):
        ensure_utc(datetime(2026, 8, 21, 0, 0))


def test_utc_normalization():
    dt = datetime(2026, 8, 21, 5, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert ensure_utc(dt) == datetime(2026, 8, 21, 0, 0, tzinfo=timezone.utc)


def test_rfc3339_roundtrip():
    s = iso_utc(datetime(2026, 8, 21, 0, 0, tzinfo=timezone.utc))
    assert s == "2026-08-21T00:00:00Z"
    assert parse_utc(s) == datetime(2026, 8, 21, 0, 0, tzinfo=timezone.utc)


def test_local_display_is_ist():
    out = local_display(datetime(2026, 8, 21, 0, 0, tzinfo=timezone.utc))
    assert out == "2026-08-21 05:30 IST"


def test_forecast_intervals_half_open_chain():
    issue = datetime(2026, 8, 21, 0, 0, tzinfo=timezone.utc)
    ivs = forecast_intervals(issue, horizon_minutes=180, step_minutes=15)
    assert len(ivs) == 12
    assert ivs[0][2] == 0 and ivs[-1][2] == 165
    for (a_from, a_to, _), (b_from, b_to, _) in zip(ivs, ivs[1:]):
        assert a_to == b_from  # contiguous half-open chain


def test_bad_interval_config():
    issue = datetime(2026, 8, 21, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        forecast_intervals(issue, 180, 7)  # 7 does not divide 180
    with pytest.raises(ValueError):
        forecast_intervals(issue, 0, 15)
