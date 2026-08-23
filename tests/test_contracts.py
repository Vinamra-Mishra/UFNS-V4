"""Contract tests (IMPLEMENTATION_SPEC §6, ARCHITECTURE §7)."""

from datetime import datetime, timezone

import pytest

from services.contracts import (
    BlockageConfiguration,
    DataLineage,
    GridSpec,
    ProvenanceClass,
    RainfallGrid,
    ScenarioDefinition,
    SurfaceParameters,
)
from services.ingestion.dem import grid_affine
from services.rainfall.scenarios import build_demo_scenarios, build_profile

ISSUE = datetime(2026, 8, 21, 0, 0, tzinfo=timezone.utc)


def _grid() -> GridSpec:
    a = grid_affine()
    return GridSpec(
        grid_id="test_grid",
        crs_wkt_or_epsg="EPSG:32645",
        vertical_crs="SYNTHETIC_LOCAL_DATUM",
        width=10,
        height=10,
        affine_transform=[a.a, a.b, a.c, a.d, a.e, a.f],
        cell_size_m=30.0,
        nodata=None,
        bounds=[a.c, a.f - 300.0, a.c + 300.0, a.f],
    )


def _lineage() -> DataLineage:
    return DataLineage(
        dataset_id="t",
        version="v1",
        source_name="test",
        acquired_at=ISSUE,
        content_sha256="0" * 64,
        provenance_class=ProvenanceClass.SIMULATED_SCENARIO,
    )


def test_scenario_definition_valid_and_fingerprint_stable():
    s = build_demo_scenarios(_grid(), "dem.tif", "net.inp", ISSUE, _lineage())[0]
    assert s.scenario_id == "normal"
    f1 = s.fingerprint()
    f2 = s.fingerprint()
    assert f1 == f2
    assert len(f1) == 64


def test_scenario_fingerprint_changes_with_rainfall():
    g = _grid()
    s1 = build_demo_scenarios(g, "dem.tif", "net.inp", ISSUE, _lineage())[0]
    s2 = s1.model_copy(deep=True)
    s2.rainfall_profile.intensities_mmh[0] += 1.0
    assert s1.fingerprint() != s2.fingerprint()


def test_rainfall_grid_interval_validation():
    g = _grid()
    base = dict(
        rainfall_id="r1",
        issue_time=ISSUE,
        valid_from=ISSUE,
        valid_to=datetime(2026, 8, 21, 0, 15, tzinfo=timezone.utc),
        lead_minutes=0,
        grid=g,
        source=_lineage(),
        asset_uri="x.tif",
    )
    RainfallGrid(**base)
    with pytest.raises(ValueError):
        RainfallGrid(**{**base, "valid_to": ISSUE})  # zero-length interval
    with pytest.raises(ValueError):
        RainfallGrid(**{**base, "confidence": 1.5})


def test_blockage_configuration_bounds():
    with pytest.raises(ValueError):
        BlockageConfiguration(fraction=1.5)
    with pytest.raises(ValueError):
        BlockageConfiguration(fraction=-0.1)


def test_surface_parameters_positive():
    with pytest.raises(ValueError):
        SurfaceParameters(manning_n=0.0, horton_f0_m_s=1e-6, horton_fmin_m_s=1e-6, horton_k_s1=1e-4)


def test_naive_timestamp_rejected_in_lineage():
    with pytest.raises(ValueError):
        DataLineage(
            dataset_id="t", version="v1", source_name="t",
            acquired_at=datetime(2026, 8, 21),  # naive
            content_sha256="0" * 64, provenance_class=ProvenanceClass.SYNTHETIC,
        )


def test_demo_scenarios_match_approved_ids():
    scenarios = build_demo_scenarios(_grid(), "dem.tif", "net.inp", ISSUE, _lineage())
    assert [s.scenario_id for s in scenarios] == ["normal", "heavy", "extreme", "extreme_blockage"]
    b = scenarios[-1].drainage_configuration.blockage
    assert b is not None and b.fraction == 1.0 and b.blocked_links == ["C4", "C9"]
    # provisional status must be visible on every demo rainfall profile
    for s in scenarios:
        assert s.rainfall_profile.review_status == "PROVISIONAL"
