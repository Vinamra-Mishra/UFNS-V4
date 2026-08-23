"""CRS policy tests (D-006, ARCHITECTURE §6)."""

import pytest

from services.ingestion.crs import (
    LonLat,
    require_projected_metric,
    roundtrip_error,
    to_lonlat,
    to_projected,
)


def test_lonlat_range_checks():
    with pytest.raises(ValueError):
        LonLat(181.0, 10.0)
    with pytest.raises(ValueError):
        LonLat(10.0, 91.0)
    assert LonLat(88.36, 22.57).lat == 22.57  # Kolkata test point


def test_geographic_crs_rejected_for_simulation():
    with pytest.raises(ValueError):
        require_projected_metric("EPSG:4326")
    crs = require_projected_metric("EPSG:32645")
    assert not crs.is_geographic


def test_projected_roundtrip_closure():
    # Kolkata coordinates -> UTM 45N -> back; closure must be sub-centimetre
    err = roundtrip_error(88.36, 22.57)
    assert err < 0.01


def test_axis_order_guard_roundtrip():
    # to_projected is always (lon, lat) with always_xy; round trip must be exact.
    x, y = to_projected(88.36, 22.57)
    assert 0 < x < 1_000_000 and 0 < y < 10_000_000  # UTM easting/northing ranges
    ll = to_lonlat(x, y)
    assert abs(ll.lon - 88.36) < 1e-6 and abs(ll.lat - 22.57) < 1e-6
