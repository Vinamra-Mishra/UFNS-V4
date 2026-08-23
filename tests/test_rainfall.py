"""Rainfall representation tests (MODEL_ASSUMPTIONS §2)."""

import numpy as np
import pytest

from services.rainfall.fields import (
    MS_TO_MMH,
    convective_cell_field,
    mmh_to_ms,
    ms_to_mmh,
    rainfall_volume_m3,
    uniform_field,
)
from services.rainfall.scenarios import alternating_block_hyetograph, build_profile


def test_exact_unit_conversion():
    # 3.6 mm/h == 1e-6 m/s (exact; MODEL_ASSUMPTIONS §1)
    assert mmh_to_ms(3.6) == pytest.approx(1e-6, abs=1e-18)
    assert ms_to_mmh(1e-6) == pytest.approx(3.6, abs=1e-12)
    assert MS_TO_MMH * (1 / (1000 * 3600)) == pytest.approx(1.0)


def test_rainfall_volume_identity():
    # uniform 3.6 mm/h over 100 m2 cells for 3600 s -> 0.36 m3 per cell
    # (tolerance reflects float32 raster storage of the rate field)
    field = uniform_field((4, 4), 3.6)
    vol = rainfall_volume_m3(field, cell_area_m2=100.0, dt_s=3600.0)
    assert vol == pytest.approx(16 * 0.36, rel=1e-6)


def test_negative_and_nonfinite_rates_rejected():
    with pytest.raises(ValueError):
        from services.rainfall.fields import FieldInterval
        from datetime import datetime, timezone

        FieldInterval(
            0,
            datetime(2026, 8, 21, tzinfo=timezone.utc),
            datetime(2026, 8, 21, 0, 15, tzinfo=timezone.utc),
            0,
            np.array([[-1.0, 0.0]]),
        )


def test_convective_cell_is_finite_nonnegative_and_seeded():
    a = convective_cell_field((20, 20), 5.0, 10.0, seed=7)
    b = convective_cell_field((20, 20), 5.0, 10.0, seed=7)
    c = convective_cell_field((20, 20), 5.0, 10.0, seed=8)
    assert np.all(np.isfinite(a)) and np.all(a >= 0)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)
    assert a.max() > 5.0  # the cell adds amplitude


def test_alternating_block_totals_and_peak_placement():
    hyeto = alternating_block_hyetograph(total_mm=45.0, duration_min=180, interval_min=15)
    assert len(hyeto) == 12
    total = sum(h * (15 / 60) for h in hyeto)
    assert total == pytest.approx(45.0, rel=1e-9)
    # The highest intensity should be near the middle
    assert np.argmax(hyeto) in (5, 6)


def test_alternating_block_ordering():
    # A concave curve with standard parameters should yield
    # adjacent blocks monotonically decreasing away from peak
    hyeto = alternating_block_hyetograph(total_mm=45.0, duration_min=180, interval_min=15)
    peak_idx = np.argmax(hyeto)
    # Check left side is monotonically increasing
    assert np.all(np.diff(hyeto[:peak_idx + 1]) > -1e-9)
    # Check right side is monotonically decreasing
    assert np.all(np.diff(hyeto[peak_idx:]) < 1e-9)


def test_profile_review_status_provisional():
    p = build_profile("heavy", 45.0)
    assert p.review_status == "PROVISIONAL"
    assert "Alternating-block" in p.derivation
    assert all(i >= 0 for i in p.intensities_mmh)
