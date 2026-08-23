"""M6 — Dashboard/API test matrix (master prompt §22).

Covers scenario listing/retrieval, invalid handling, result schema, provenance
preservation, S3/S4 comparison, mass-balance values, artifact existence,
deterministic responses, and safety (path traversal / malformed IDs / invalid
lead). The hydraulic simulation is never re-run: these tests read the
precomputed artifacts only.

M6-01..M6-12 acceptance gates are exercised here (dashboard launches = the
FastAPI app + root HTML; maps render = flood-depth/flood-extent PNG endpoints).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api import store
from apps.api.app import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# M6-01 / M6-02 — dashboard + scenario list
# ---------------------------------------------------------------------------

def test_m6_health_and_version():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("ok", "degraded")
    # The application identifier reflects the current milestone.
    assert body["app"] == "ufns-m9"
    assert body["b13_policy"] == "B13-DEMO-V1"
    assert body["b13_policy_status"] == "PROVISIONAL_DEMONSTRATION"
    assert body["dataset_status"] == "SYNTHETIC"
    assert body["scenarios_available"] == ["S1", "S2", "S3", "S4"]
    assert body["d016_status"] == "PREPARED"

    v = client.get("/api/v1/version")
    assert v.status_code == 200
    assert "model_version" in v.json()


def test_m6_dashboard_root_serves_html():
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "UFNS" in r.text
    assert "NOT FOR OPERATIONAL USE" in r.text


def test_m6_dashboard_includes_m8_rainfall_panel():
    # M8 adds a rainfall/nowcast status panel to the dashboard sidebar.
    r = client.get("/")
    assert r.status_code == 200
    assert "Rainfall + Nowcast" in r.text
    assert 'id="rainfall-status"' in r.text
    assert "PERSISTENCE BASELINE" in r.text


def test_m6_scenario_list():
    r = client.get("/api/v1/scenarios")
    assert r.status_code == 200
    body = r.json()
    ids = [s["scenario_id"] for s in body["scenarios"]]
    assert ids == ["S1", "S2", "S3", "S4"]
    assert body["count"] == 4
    for s in body["scenarios"]:
        assert s["rainfall_total_mm"] in (20.0, 45.0, 90.0)
        assert s["rainfall_status"] == "PROVISIONAL"
        assert s["dataset_status"] == "SYNTHETIC"
        assert s["d016_status"] == "PREPARED"
        assert "PROVISIONAL" in s["labels"]


# ---------------------------------------------------------------------------
# M6-03 — scenario metadata (provenance preserved)
# ---------------------------------------------------------------------------

def test_m6_scenario_metadata_provenance():
    r = client.get("/api/v1/scenarios/S4")
    assert r.status_code == 200
    m = r.json()
    for key in ("scenario_id", "display_name", "description", "rainfall_profile",
                "rainfall_status", "drainage_condition", "assumptions",
                "limitations", "provenance", "scenario_fingerprint",
                "swmm_fixture_fingerprint", "model_version"):
        assert key in m, f"metadata missing {key}"
    assert m["scenario_id"] == "S4"
    assert m["drainage_condition"]["condition_id"] == "D_BLOCKED"
    assert m["d016_status"] == "PREPARED"
    assert m["d016_human_review"] == "REQUIRED"
    assert m["not_for_operational_use"] is True
    assert m["rainfall_profile"]["profile_id"] == "P_EXTREME"
    assert len(m["rainfall_profile"]["fingerprint"]) == 16
    assert m["rainfall_profile"]["d016_review_status"] == "PREPARED"


# ---------------------------------------------------------------------------
# M6-04/05 — result schema + snapshot timeline
# ---------------------------------------------------------------------------

def test_m6_scenario_result_schema():
    r = client.get("/api/v1/scenarios/S2/result")
    assert r.status_code == 200
    d = r.json()
    for key in ("scenario_id", "display_name", "run_id", "config_fingerprint",
                "rainfall_summary", "loss_summary", "surface_storage_summary",
                "drainage_storage_summary", "exchange_summary", "boundary_summary",
                "peak_depth_m", "max_flooded_area_m2", "time_to_peak_min",
                "max_drainage_surcharge_m", "mass_ledger", "snapshot_inventory",
                "acceptance", "run_fingerprint"):
        assert key in d, f"result missing {key}"
    assert d["scenario_id"] == "S2"
    assert d["mass_ledger"]["gate"] == "PASS"
    assert d["acceptance"]["overall"] == "PASS"
    assert d["d016_status"] == "PREPARED"
    assert len(d["snapshot_inventory"]) == 37
    # no absolute artifact URIs leaked (path-traversal safe)
    assert all("depth_asset_uri" not in s for s in d["snapshot_inventory"])


def test_m6_snapshots_timeline():
    r = client.get("/api/v1/scenarios/S1/snapshots")
    assert r.status_code == 200
    body = r.json()
    leads = [s["lead_minutes"] for s in body["snapshots"]]
    assert leads == list(range(0, 181, 5))
    assert body["count"] == 37


# ---------------------------------------------------------------------------
# M6-06 — S3/S4 comparison
# ---------------------------------------------------------------------------

def test_m6_s3s4_comparison():
    r = client.get("/api/v1/comparison/s3s4")
    assert r.status_code == 200
    body = r.json()
    comp = body["comparison"]
    assert comp["interpretation_status"] == "PHYSICALLY CONSISTENT"
    diff = comp["differences"]
    for key in ("delta_peak_depth_m", "delta_flooded_area_m2",
                "delta_surface_storage_change_m3", "delta_max_surcharge_m",
                "capture_reduction_m3", "additional_spill_m3", "outfall_reduction_m3"):
        assert key in diff, f"missing difference {key}"
    # the documented blockage response: capture down, outfall down, D2S spill up
    assert diff["capture_reduction_m3"] > 0
    assert diff["outfall_reduction_m3"] > 0
    assert diff["additional_spill_m3"] > 0
    assert "Blockage" in comp["physical_interpretation"] or "blockage" in comp["physical_interpretation"]
    ctrls = body["comparability_controls"]
    assert ctrls["S3_S4_pairwise_controlled"] is True


# ---------------------------------------------------------------------------
# M6-07 — mass balance from authoritative ledger
# ---------------------------------------------------------------------------

def test_m6_mass_balance():
    r = client.get("/api/v1/scenarios/S3/mass-balance")
    assert r.status_code == 200
    mb = r.json()
    assert mb["scenario_id"] == "S3"
    assert mb["gate"] == "PASS"
    assert mb["units"] == "m3"
    iden = mb["identity"]
    # rainfall is the dominant term; residual is bounded
    assert iden["rainfall_input_m3"] > 0
    assert abs(mb["residual_m3"]) / iden["rainfall_input_m3"] <= mb["configured_tolerance_rel"]
    assert "not frontend-recomputed" in mb["source"] or "authoritative" in mb["source"]


# ---------------------------------------------------------------------------
# M6-04/05 — flood-depth / flood-extent artifacts render
# ---------------------------------------------------------------------------

def test_m6_flood_depth_artifact():
    r = client.get("/api/v1/scenarios/S3/flood-depth?lead=110")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(r.content) > 1000


def test_m6_flood_extent_artifact():
    r = client.get("/api/v1/scenarios/S4/flood-extent?lead=110")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_m6_map_rendering_deterministic():
    a = client.get("/api/v1/scenarios/S1/flood-depth?lead=90").content
    b = client.get("/api/v1/scenarios/S1/flood-depth?lead=90").content
    assert a == b


# ---------------------------------------------------------------------------
# M6-09 — invalid inputs fail safely (no path traversal)
# ---------------------------------------------------------------------------

def test_m6_invalid_scenario_404():
    # These ids match the route and are rejected by the allow-list with a
    # structured error envelope.
    for bad in ("S5", "s1", "S0", "S1x"):
        r = client.get(f"/api/v1/scenarios/{bad}/result")
        assert r.status_code == 404, f"{bad!r} should 404"
        body = r.json()
        assert body["error"]["code"] == "SCENARIO_NOT_FOUND"


def test_m6_no_path_traversal_to_filesystem():
    # The API never accepts a client file path: artifact paths are derived
    # internally from an allow-listed scenario id and a validated lead. Any
    # traversal-looking scenario id is rejected by the allow-list, and the
    # store derives paths only within the artifact root.
    for bad in ("../../etc/passwd", "..%2F..%2Fetc", "S1/../..", "%2e%2e"):
        r = client.get(f"/api/v1/scenarios/{bad}/result")
        assert r.status_code == 404
    # store artifact path is always inside data/demo/m5/
    for sid, lead in (("S1", 0), ("S4", 180)):
        p = store.artifact_tif_path(sid, lead)
        assert str(p).startswith(str(store.ARTIFACT_ROOT))
        assert "data/demo/m5" in str(p)


def test_m6_invalid_lead():
    r = client.get("/api/v1/scenarios/S1/flood-depth?lead=999")
    assert r.status_code in (400, 422, 404)
    # lead 7 is not a valid snapshot lead (5-min cadence)
    r2 = client.get("/api/v1/scenarios/S1/flood-depth?lead=7")
    assert r2.status_code in (400, 404)


def test_m6_structured_error_envelope():
    r = client.get("/api/v1/scenarios/NOPE")
    assert r.status_code == 404
    body = r.json()
    assert "error" in body
    assert "code" in body["error"] and "message" in body["error"]


# ---------------------------------------------------------------------------
# M6-08 — provenance / scientific status visible in API
# ---------------------------------------------------------------------------

def test_m6_provenance_status_labels():
    r = client.get("/api/v1/scenarios/S1")
    m = r.json()
    assert m["dataset_status"] == "SYNTHETIC"
    assert "PROVISIONAL" in m["labels"]
    assert "SYNTHETIC" in m["labels"]
    assert "SIMULATED" in m["labels"]
    assert m["not_for_operational_use"] is True
    # D-016 is NOT fabricated as approved
    assert m["d016_status"] == "PREPARED"
    assert m["d016_human_review"] == "REQUIRED"
    assert m["rainfall_profile"]["review_status"] == "PROVISIONAL"


# ---------------------------------------------------------------------------
# Store-level sanity (no simulation re-run; authoritative artifacts)
# ---------------------------------------------------------------------------

def test_m6_store_does_not_rerun_simulation():
    # The store only reads precomputed artifacts and the registry.
    results = store.load_results()
    assert set(results.keys()) == {"S1", "S2", "S3", "S4"}
    assert store.MODEL_VERSION == "m5-scenario-engine-v1"
    # artifact path derivation is internal (no client path accepted)
    p = store.artifact_tif_path("S1", 0)
    assert p.name == "depth_t000.tif"
    assert str(p).endswith("data/demo/m5/s1/depth_t000.tif")
