"""Time policy (ARCHITECTURE §6).

- Store/exchange: timezone-aware UTC, RFC 3339.
- Display: local IANA timezone separately (default Asia/Kolkata).
- Issue time, valid time, lead time are distinct fields.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Asia/Kolkata")


def ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("naive datetime not allowed; provide timezone-aware UTC")
    return dt.astimezone(timezone.utc)


def iso_utc(dt: datetime) -> str:
    """RFC 3339 UTC string (the only interchange format)."""
    return ensure_utc(dt).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(s: str) -> datetime:
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return ensure_utc(dt)


def local_display(dt: datetime, tz: ZoneInfo = LOCAL_TZ) -> str:
    """Human-facing local time, e.g. '2026-08-21 05:30 IST'."""
    return ensure_utc(dt).astimezone(tz).strftime("%Y-%m-%d %H:%M %Z")


def forecast_intervals(issue_time: datetime, horizon_minutes: int, step_minutes: int) -> list[tuple[datetime, datetime, int]]:
    """Emit (valid_from, valid_to, lead_minutes) for the forecast window.

    Intervals are half-open [valid_from, valid_to); lead is the interval start
    offset from issue time. Raises on non-positive/overlapping configuration.
    """
    issue = ensure_utc(issue_time)
    if horizon_minutes <= 0 or step_minutes <= 0:
        raise ValueError("horizon and step must be positive")
    if horizon_minutes % step_minutes != 0:
        raise ValueError("horizon must be a multiple of the forcing step")
    out = []
    for lead in range(0, horizon_minutes, step_minutes):
        start = issue + timedelta(minutes=lead)
        end = issue + timedelta(minutes=lead + step_minutes)
        out.append((start, end, lead))
    return out
