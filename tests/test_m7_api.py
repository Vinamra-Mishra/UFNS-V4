"""M7 — API test matrix (M7-16 … M7-22).

Covers the M7 endpoints (frame, roads, road-impact, road-impact timeline,
road-metrics, rainfall, policies, routes), invalid-input handling, security
(path traversal), timeline metadata, and M6 regression (the pre-existing M6
endpoints keep working). All responses are read from precomputed artifacts;
the hydraulic simulation is never re-run.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.app import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# M7-16 — frame (snapshot) API
# ---------------------------------------------------------------------------

def test_m7_16_frame_api():
    r = client.get("/api/v1/scenarios/S4/frame?lead=110")
    assert r.status_code == 200
    f = r.json()
    assert f["scenario_id"] == "S4"
    assert f["lead_minutes"] == 110
    assert f["grid"]["width"] == f["grid"]["height"] == 134
    assert len(f["depth"]) == 134 * 134
    assert f["depth_units"] == "m"
    assert f["valid_time"] == "2026-08-21T01:50:00+00:00"
    assert "road_impacts" in f and len(f["road_impacts"]) == 57
    assert "road_metrics" in f
    assert f["road_metrics"]["total_segments"] == 57
    assert f["policy"]["policy_id"] == "B13-DEMO-V1"
    assert "NOT FOR OPERATIONAL USE" in f["labels"]
    # drainage state is present and truthful
    assert "surcharged" in f["drainage"]


# ---------------------------------------------------------------------------
# M7-17 — road-impact API
# ---------------------------------------------------------------------------

def test_m7_17_road_impact_api():
    r = client.get("/api/v1/scenarios/S4/road-impact?lead=110")
    assert r.status_code == 200
    body = r.json()
    assert body["scenario_id"] == "S4"
    assert len(body["road_impacts"]) == 57
    imp = body["road_impacts"][0]
    for key in ("road_id", "classification", "passability", "max_depth_m",
                "impacted_fraction", "policy_version", "policy_fingerprint"):
        assert key in imp
    # metrics present
    assert body["road_metrics"]["total_segments"] == 57

    # per-road timeline
    t = client.get("/api/v1/scenarios/S4/road-impact/R-011")
    assert t.status_code == 200
    tl = t.json()
    assert tl["road_id"] == "R-011"
    assert len(tl["series"]) == 37
    assert tl["series"][0]["classification"] == "DRY"
    assert tl["first_impacted_lead_minutes"] is not None
    assert tl["source"] == "SYNTHETIC_DEMO"


# ---------------------------------------------------------------------------
# M7-18 — route API
# ---------------------------------------------------------------------------

def test_m7_18_route_api():
    r = client.post("/api/v1/routes", json={
        "scenario_id": "S4", "lead": 110,
        "origin": [300615.0, 2503405.0], "destination": [303405.0, 2500615.0],
        "mode": "flood_aware",
    })
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "OK"
    assert d["baseline"]["distance_m"] > 0
    assert d["flood_aware"]["distance_m"] > 0
    assert "additional_distance_m" in d["difference"]
    assert d["policy_version"] == "B13-DEMO-V1"
    assert d["explanation"]["summary"]


def test_m7_18b_route_avoid_impassable_mode():
    r = client.post("/api/v1/routes", json={
        "scenario_id": "S4", "lead": 110,
        "origin": [300615.0, 2503405.0], "destination": [303405.0, 2500615.0],
        "mode": "avoid_impassable",
    })
    assert r.status_code == 200
    assert r.json()["mode"] == "avoid_impassable"


# ---------------------------------------------------------------------------
# M7-19 — invalid API handling
# ---------------------------------------------------------------------------

def test_m7_19_invalid_api_handling():
    # invalid scenario
    assert client.get("/api/v1/scenarios/S5/frame?lead=0").status_code == 404
    # invalid lead (7 is not a 5-min snapshot)
    assert client.get("/api/v1/scenarios/S4/frame?lead=7").status_code == 400
    # invalid road id
    r = client.get("/api/v1/scenarios/S4/road-impact/R-999")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "ROAD_NOT_FOUND"
    # malformed coordinates
    r = client.post("/api/v1/routes", json={
        "scenario_id": "S4", "lead": 0, "origin": [0, 0],
        "destination": [303405.0, 2500615.0]})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "COORDINATES_OUT_OF_RANGE"
    # malformed coordinate arity
    r = client.post("/api/v1/routes", json={
        "scenario_id": "S4", "lead": 0, "origin": [1.0],
        "destination": [303405.0, 2500615.0]})
    assert r.status_code in (400, 422)
    # invalid mode
    r = client.post("/api/v1/routes", json={
        "scenario_id": "S4", "lead": 0, "origin": [300615.0, 2503405.0],
        "destination": [303405.0, 2500615.0], "mode": "bogus"})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# M7-20 — security / path traversal
# ---------------------------------------------------------------------------

def test_m7_20_security_no_path_traversal():
    for bad in ("../../etc/passwd", "..%2F..%2Fetc", "S1/../..", "%2e%2e"):
        assert client.get(f"/api/v1/scenarios/{bad}/frame?lead=0").status_code == 404
        assert client.get(f"/api/v1/scenarios/{bad}/road-impact?lead=0").status_code == 404
    # route coordinates cannot escape the domain bounds
    for xy in ([-1e9, -1e9], [1e9, 1e9]):
        r = client.post("/api/v1/routes", json={
            "scenario_id": "S4", "lead": 0, "origin": xy,
            "destination": [303405.0, 2500615.0]})
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# M7-21 — timeline metadata
# ---------------------------------------------------------------------------

def test_m7_21_timeline_metadata():
    r = client.get("/api/v1/scenarios/S1/snapshots")
    assert r.status_code == 200
    leads = [s["lead_minutes"] for s in r.json()["snapshots"]]
    assert leads == list(range(0, 181, 5))
    # every lead yields a valid frame
    for lead in (0, 90, 180):
        f = client.get(f"/api/v1/scenarios/S1/frame?lead={lead}").json()
        assert f["lead_minutes"] == lead
        assert len(f["depth"]) == 134 * 134


# ---------------------------------------------------------------------------
# M7-22 — M6 regression (pre-existing endpoints still work)
# ---------------------------------------------------------------------------

def test_m7_22_m6_regression_endpoints():
    assert client.get("/api/v1/scenarios").json()["count"] == 4
    assert client.get("/api/v1/scenarios/S3/result").status_code == 200
    assert client.get("/api/v1/scenarios/S3/mass-balance").json()["gate"] == "PASS"
    assert client.get("/api/v1/comparison/s3s4").status_code == 200
    png = client.get("/api/v1/scenarios/S3/flood-depth?lead=110")
    assert png.status_code == 200 and png.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert client.get("/").status_code == 200


def test_m7_policy_and_roads_endpoints():
    p = client.get("/api/v1/policies").json()["policies"][0]
    assert p["policy_id"] == "B13-DEMO-V1"
    assert p["approved"] is False
    rd = client.get("/api/v1/roads").json()
    assert rd["n_segments"] == 57
    assert "NOT REAL ROAD GEOMETRY" in rd["status"]
    dp = client.get("/api/v1/drainage/points").json()
    assert len(dp["inlets"]) == 16
    assert len(dp["vent"]) == 2
