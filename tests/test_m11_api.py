"""M11 — Real-pilot inspection API tests (Section 17).

The pilot endpoints are an inspection layer over the precomputed M11 artifact
(data/demo/m11/pilot_inspection.json). They are skipped (never weakened) when
the artifact is absent, and they assert the truthfulness labels: REAL_PILOT /
REAL_TERRAIN / SYNTHETIC_HYDRAULICS / PROVISIONAL / MISSING / UNRESOLVED /
NOT_REAL_TIME / NOT_VALIDATED_FORECAST.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api import pilot as pilot_store
from apps.api.app import app

client = TestClient(app)

INSPECTION_JSON = Path("data/demo/m11/pilot_inspection.json")
require_inspection = pytest.mark.skipif(
    not INSPECTION_JSON.exists(),
    reason="M11 pilot inspection artifact not present (run run_m11_real_pilot_validation.py)",
)


@pytest.fixture(autouse=True)
def _reset_pilot_cache():
    pilot_store.reset_cache()
    yield
    pilot_store.reset_cache()


@require_inspection
class TestPilotInspectionAPI:
    def test_overview_endpoints_succeed_and_are_truthful(self):
        for path in ("/api/v1/pilot/real", "/api/v1/pilot/real/dem",
                     "/api/v1/pilot/real/drainage",
                     "/api/v1/pilot/real/hydraulic-readiness"):
            r = client.get(path)
            assert r.status_code == 200, (path, r.text)
            body = r.json()
            assert body.get("not_for_operational_use") is True
            # Never implies operational forecasting / real hydraulic capacity.
            assert "operational" not in str(body).lower() or "not_for_operational_use" in body

    def test_overview_reports_gridspec_and_readiness(self):
        r = client.get("/api/v1/pilot/real")
        assert r.status_code == 200
        body = r.json()
        assert body["gridspec"]["grid_id"] == "ufns_pilot_grid_real"
        assert body["gridspec"]["crs_wkt_or_epsg"] == "EPSG:32645"
        hr = body["hydraulic_readiness"]
        assert hr["hydraulic_network_ready"] is False
        assert set(hr["missing_attributes"]) == {
            "diameter_m", "invert_upstream_m", "invert_downstream_m",
            "manning_n", "capacity_m3s",
        }

    def test_drainage_counts_present(self):
        r = client.get("/api/v1/pilot/real/drainage")
        body = r.json()
        cov = body["drainage_coverage"]
        total = cov["mapped_count"] + cov["unresolved_count"] + cov["rejected_count"]
        assert total == cov["total_source_features"] == 90395
        assert "UNRESOLVED" in body["labels"]

    def test_hydraulic_readiness_marks_missing(self):
        r = client.get("/api/v1/pilot/real/hydraulic-readiness")
        body = r.json()
        hr = body["hydraulic_readiness"]
        # The REAL drainage contract: all required attributes MISSING; the
        # real hydraulic network is NOT ready. (The synthetic MODE-B fixture
        # is a separate path and is never stored as REAL_DATA.)
        assert hr["real_hydraulic_network_ready"] is False
        assert hr["synthetic_fixture_labelled"] is False
        assert set(hr["missing_attributes"]) == {
            "diameter_m", "invert_upstream_m", "invert_downstream_m",
            "manning_n", "capacity_m3s",
        }
        assert "MISSING" in body["labels"]

    def test_rainfall_not_promoted(self):
        r = client.get("/api/v1/pilot/real")
        rs = r.json()["rainfall_status"]
        assert rs["d016_status"] == "PREPARED"
        assert rs["d016_human_review"] == "REQUIRED"
        assert rs["real_time"] is False
        assert rs["validated_forecast"] is False

    def test_health_reports_pilot_availability(self):
        r = client.get("/health")
        assert r.status_code == 200
        assert "real_pilot_inspection_available" in r.json()


class TestPilotInspectionMissing:
    def test_endpoints_503_when_artifact_missing(self, monkeypatch, tmp_path):
        # Point the store at a non-existent artifact location.
        monkeypatch.setattr(pilot_store, "INSPECTION_JSON", tmp_path / "nope.json")
        pilot_store.reset_cache()
        r = client.get("/api/v1/pilot/real")
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "PILOT_INSPECTION_UNAVAILABLE"
