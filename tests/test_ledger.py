"""Mass-ledger tests (D-015, B07; thresholds documented in ledger.py)."""

import math
from datetime import datetime, timezone

from services.simulation.ledger import MassLedger

T0 = datetime(2026, 8, 21, 0, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 8, 21, 3, 0, tzinfo=timezone.utc)


def _closed_ledger(rain_m3: float = 1000.0) -> MassLedger:
    """Exact closure: rain goes entirely into final surface storage."""
    led = MassLedger()
    led.add_rainfall(rain_m3)
    led.surface_storage_initial_m3 = 0.0
    led.surface_storage_final_m3 = rain_m3
    return led


def test_exact_closure_passes():
    mb = _closed_ledger().close(T0, T1)
    assert mb.status == "pass"
    assert mb.residual_m3 == 0.0


def test_three_percent_residual_warns():
    led = MassLedger()
    led.add_rainfall(1000.0)
    led.surface_storage_final_m3 = 970.0  # 30 m3 unaccounted = 3%
    mb = led.close(T0, T1)
    assert mb.status == "warning"
    assert mb.relative_error == pytest_approx(0.03)


def test_ten_percent_residual_fails():
    led = MassLedger()
    led.add_rainfall(1000.0)
    led.surface_storage_final_m3 = 900.0
    assert led.close(T0, T1).status == "fail"


def test_dry_run_absolute_check():
    led = MassLedger()  # no rain; tiny numerical dust
    led.surface_storage_final_m3 = 1e-9
    mb = led.close(T0, T1)
    assert mb.status == "pass"


def test_nonfinite_residual_fails_fast():
    """NaN in ledger terms must fail fast (contract refuses non-finite MassBalance)."""
    import pytest as _pytest

    led = MassLedger()
    led.add_rainfall(math.nan)
    with _pytest.raises(ValueError):
        led.close(T0, T1)


def test_exchange_cancels_internally():
    """Surface->drain and drain->surface must cancel; ledger records them but
    they never enter the whole-system identity."""
    led = MassLedger()
    led.add_rainfall(500.0)
    led.record_exchange(200.0, 200.0)  # equal and opposite
    led.surface_storage_final_m3 = 500.0
    mb = led.close(T0, T1)
    assert mb.status == "pass"
    assert mb.residual_m3 == 0.0


def pytest_approx(x, rel=1e-9):
    import pytest

    return pytest.approx(x, rel=rel)
