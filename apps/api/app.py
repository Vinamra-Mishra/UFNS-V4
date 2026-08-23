"""UFNS M6 — dashboard/API (FastAPI).

An inspection layer over the precomputed M5 scenario results. It exposes typed,
versioned endpoints for scenario listing/metadata/results, flood-depth and
flood-extent map artifacts, the S3/S4 blockage comparison, mass-balance
presentation, and health/version — and serves the single-file dashboard.

Safety and honesty guarantees (IMPLEMENTATION_SPEC §22, M6 §19-23):
  - scenario identifiers are allow-listed (S1..S4); anything else is 404;
  - no client-supplied file paths are ever accepted (no path traversal);
  - artifact paths are derived server-side from the snapshot inventory;
  - every response carries provenance labels (SYNTHETIC / SIMULATED /
    PROVISIONAL / NOT FOR OPERATIONAL USE) and the D-016 status;
  - the hydraulic simulation is never re-run to serve a request.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from apps.api import impacts, pilot, projections, rainfall_api, render, store
from services.nowcast import NOWCAST_VERSION
from services.projection import MODEL_VERSION as PROJECTION_VERSION
from services.projection.pipeline import ProjectionUnavailableError
from services.routing.policy import POLICY
from services.scenarios import MODEL_VERSION
from services.scenarios.profiles import D016_HUMAN_REVIEW, D016_STATUS

API_VERSION = "1.3.0"
APP_TITLE = "UFNS — Urban Flood Nowcasting System (M9 persistence impact projection)"

REPO_ROOT = Path(__file__).resolve().parents[2]
INDEX_HTML = REPO_ROOT / "apps" / "web" / "index.html"

app = FastAPI(title=APP_TITLE, version=API_VERSION)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _error(status_code: int, code: str, message: str, **details: Any) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"error": {"code": code, "message": message, **details}},
    )


def _require_scenario(scenario_id: str) -> None:
    if scenario_id not in store.VALID_SCENARIO_IDS:
        raise _error(
            404, "SCENARIO_NOT_FOUND",
            f"unknown scenario id {scenario_id!r}",
            valid_scenario_ids=list(store.VALID_SCENARIO_IDS),
        )


def _store_not_ready() -> HTTPException:
    return _error(
        503, "ARTIFACTS_UNAVAILABLE",
        "precomputed M5 scenario artifacts are missing or malformed",
    )


VALID_LEADS = tuple(range(0, 181, 5))
VALID_PROJECTION_LEADS = (0, 15, 30, 45, 60)
VALID_ROUTE_MODES = ("flood_aware", "avoid_impassable")
VALID_PROJECTION_CONFIG_IDS = tuple(projections.PROJECTION_CONFIGS.keys())
# Projected EPSG:32645 domain bounds (matches the synthetic fixture).
_DOMAIN_XMIN, _DOMAIN_YMIN, _DOMAIN_XMAX, _DOMAIN_YMAX = 300000.0, 2500000.0, 304020.0, 2504020.0


def _require_lead(lead: int) -> None:
    if lead not in VALID_LEADS:
        raise _error(
            400, "INVALID_LEAD",
            f"lead {lead} is not a valid snapshot lead",
            valid_leads=list(VALID_LEADS),
        )


def _require_projection_config(config_id: str) -> None:
    if config_id not in VALID_PROJECTION_CONFIG_IDS:
        raise _error(
            404,
            "PROJECTION_CONFIG_NOT_FOUND",
            f"unknown projection config id {config_id!r}",
            valid_config_ids=list(VALID_PROJECTION_CONFIG_IDS),
        )


def _require_projection_lead(lead: int) -> None:
    if lead not in VALID_PROJECTION_LEADS:
        raise _error(
            400,
            "INVALID_LEAD",
            f"lead {lead} is not a valid projection lead",
            valid_leads=list(VALID_PROJECTION_LEADS),
        )


def _validate_xy(name: str, xy: list[float]) -> tuple[float, float]:
    """Validate a projected [x, y] coordinate against the fixture domain."""
    if len(xy) != 2 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in xy):
        raise _error(400, "INVALID_COORDINATES",
                     f"{name} must be [x, y] with two finite numbers")
    x, y = float(xy[0]), float(xy[1])
    if not (_DOMAIN_XMIN <= x <= _DOMAIN_XMAX and _DOMAIN_YMIN <= y <= _DOMAIN_YMAX):
        raise _error(
            400, "COORDINATES_OUT_OF_RANGE",
            f"{name} {xy} is outside the synthetic fixture domain",
            domain_bounds=[_DOMAIN_XMIN, _DOMAIN_YMIN, _DOMAIN_XMAX, _DOMAIN_YMAX],
        )
    return x, y


class RouteRequest(BaseModel):
    scenario_id: str
    lead: int = Field(ge=0, le=180)
    origin: list[float] = Field(min_length=2, max_length=2)
    destination: list[float] = Field(min_length=2, max_length=2)
    mode: Literal["flood_aware", "avoid_impassable"] = "flood_aware"


class ProjectionRouteRequest(BaseModel):
    lead: int = Field(ge=0, le=60)
    origin: list[float] = Field(min_length=2, max_length=2)
    destination: list[float] = Field(min_length=2, max_length=2)
    mode: Literal["flood_aware", "avoid_impassable"] = "flood_aware"


# ---------------------------------------------------------------------------
# Dashboard (root)
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def dashboard() -> HTMLResponse:
    if not INDEX_HTML.exists():
        raise _error(500, "DASHBOARD_MISSING", "dashboard index.html not found")
    return HTMLResponse(INDEX_HTML.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Health / version
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict[str, Any]:
    try:
        results = store.load_results()
        artifacts_ok = all(sid in results for sid in store.VALID_SCENARIO_IDS)
    except store.StoreError:
        results = None
        artifacts_ok = False
    # M8 rainfall/nowcast status. The provider/API contract surfaces the
    # "no provider configured" case as a RuntimeError (get_active_provider);
    # we catch only that expected provider/API failure type rather than
    # broadening to Exception. The UNCONFIGURED/UNAVAILABLE fallback is kept.
    try:
        rain_status = rainfall_api.get_rainfall_status()
        rain_provider_type = rain_status["source_type"]
        rain_health = rain_status["health"]["status"]
    except RuntimeError:
        rain_provider_type = "UNCONFIGURED"
        rain_health = "UNAVAILABLE"
    # Top-level health is degraded when the precomputed artifacts are missing
    # OR when the rainfall dependency is UNAVAILABLE.
    status = "ok"
    if not artifacts_ok or rain_health == "UNAVAILABLE":
        status = "degraded"
    engine_version = ""
    if results:
        engine_version = next(
            (results.get(sid, {}).get("engine_version", "")
             for sid in store.VALID_SCENARIO_IDS if results.get(sid)),
            "",
        )
    return {
        "status": status,
        "app": "ufns-m9",
        "api_version": API_VERSION,
        "model_version": MODEL_VERSION,
        "nowcast_version": NOWCAST_VERSION,
        "projection_version": PROJECTION_VERSION,
        "road_routing_version": impacts.road_network().get("source", ""),
        "b13_policy": POLICY.policy_id,
        "b13_policy_status": POLICY.status,
        "engine_version": engine_version,
        "dataset_status": "SYNTHETIC",
        "d016_status": D016_STATUS,
        "d016_human_review": D016_HUMAN_REVIEW,
        "scenarios_available": list(store.VALID_SCENARIO_IDS),
        "artifacts_ok": artifacts_ok,
        "rainfall_provider_type": rain_provider_type,
        "rainfall_provider_health": rain_health,
        "real_pilot_inspection_available": pilot.inspection_available(),
        "labels": ["SYNTHETIC", "SIMULATED", "PROVISIONAL", "DEMONSTRATION_PROTOTYPE"],
    }


@app.get("/api/v1/version")
def version() -> dict[str, Any]:
    return {
        "api_version": API_VERSION,
        "model_version": MODEL_VERSION,
        "nowcast_version": NOWCAST_VERSION,
        "projection_version": PROJECTION_VERSION,
        "road_routing_version": "m7-road-routing-v1",
        "b13_policy": POLICY.policy_id,
        "b13_policy_status": POLICY.status,
        "d016_status": D016_STATUS,
        "d016_human_review": D016_HUMAN_REVIEW,
        "dataset_status": "SYNTHETIC",
        "maturity": "LEVEL_1_DEMONSTRATION_PROTOTYPE",
    }


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

@app.get("/api/v1/scenarios")
def list_scenarios() -> dict[str, Any]:
    try:
        scenarios = store.list_scenarios()
    except store.StoreError as exc:
        raise _store_not_ready() from exc
    return {
        "scenarios": scenarios,
        "count": len(scenarios),
        "labels": ["SYNTHETIC", "SIMULATED", "PROVISIONAL"],
        "d016_status": D016_STATUS,
        "d016_human_review": D016_HUMAN_REVIEW,
    }


@app.get("/api/v1/scenarios/{scenario_id}")
def scenario_metadata(scenario_id: str) -> dict[str, Any]:
    _require_scenario(scenario_id)
    try:
        meta = store.scenario_metadata(scenario_id)
    except store.StoreError as exc:
        raise _store_not_ready() from exc
    if not meta:
        raise _error(404, "SCENARIO_NOT_FOUND", f"no metadata for {scenario_id!r}")
    return meta


@app.get("/api/v1/scenarios/{scenario_id}/result")
def scenario_result(scenario_id: str) -> dict[str, Any]:
    _require_scenario(scenario_id)
    try:
        result = store.scenario_result(scenario_id)
    except store.StoreError as exc:
        raise _store_not_ready() from exc
    if not result:
        raise _error(404, "RESULT_NOT_FOUND", f"no result for {scenario_id!r}")
    return result


@app.get("/api/v1/scenarios/{scenario_id}/snapshots")
def scenario_snapshots(scenario_id: str) -> dict[str, Any]:
    _require_scenario(scenario_id)
    try:
        timeline = store.snapshot_timeline(scenario_id)
    except store.StoreError as exc:
        raise _store_not_ready() from exc
    return {
        "scenario_id": scenario_id,
        "snapshots": timeline,
        "count": len(timeline),
        "snapshot_interval_minutes": 5,
    }


@app.get("/api/v1/scenarios/{scenario_id}/mass-balance")
def scenario_mass_balance(scenario_id: str) -> dict[str, Any]:
    """Mass-balance presentation from the authoritative backend ledger.

    The identity (IMPLEMENTATION_SPEC §18) is presented verbatim from the
    precomputed ledger; it is NOT recomputed in the frontend.
    """
    _require_scenario(scenario_id)
    try:
        result = store.scenario_result(scenario_id)
    except store.StoreError as exc:
        raise _store_not_ready() from exc
    ml = result.get("mass_ledger", {})
    return {
        "scenario_id": scenario_id,
        "identity": {
            "rainfall_input_m3": ml.get("rainfall_input_m3"),
            "minus_infiltration_loss_m3": -ml.get("infiltration_loss_m3", 0.0),
            "minus_surface_boundary_outflow_m3": -ml.get("surface_boundary_outflow_m3", 0.0),
            "minus_drainage_outfall_m3": -ml.get("drainage_outfall_m3", 0.0),
            "minus_surface_storage_change_m3": -ml.get("surface_storage_change_m3", 0.0),
            "minus_drainage_storage_change_m3": -ml.get("drainage_storage_change_m3", 0.0),
        },
        "residual_m3": ml.get("combined_residual_m3"),
        "absolute_residual_m3": ml.get("absolute_residual_m3"),
        "relative_residual": ml.get("relative_residual"),
        "configured_tolerance_rel": ml.get("configured_tolerance_rel"),
        "gate": ml.get("gate"),
        "source": "authoritative precomputed M5 mass ledger (not frontend-recomputed)",
        "units": "m3",
    }


# ---------------------------------------------------------------------------
# Flood-depth / flood-extent map artifacts
# ---------------------------------------------------------------------------

def _map_image(scenario_id: str, lead_minutes: int, extent: bool) -> Response:
    _require_scenario(scenario_id)
    try:
        tif_path = store.artifact_tif_path(scenario_id, lead_minutes)
        result = store.scenario_result(scenario_id)
        meta = store.scenario_metadata(scenario_id)
    except KeyError as exc:
        raise _error(
            400, "INVALID_LEAD",
            f"no snapshot at lead {lead_minutes} for {scenario_id!r}",
        ) from exc
    except store.StoreError as exc:
        raise _store_not_ready() from exc

    threshold_m = meta.get("extent_threshold_m", 0.05)
    vmax = max(result.get("peak_depth_m") or 0.0, 0.05)
    if extent:
        label = (f"FLOOD EXTENT {scenario_id} t+{lead_minutes} min (h>{threshold_m} m) "
                 f"— SYNTHETIC / SIMULATED / PROVISIONAL / NOT FOR OPERATIONAL USE")
        png = render.render_extent_png(tif_path, threshold_m, label)
    else:
        label = (f"FLOOD DEPTH {scenario_id} t+{lead_minutes} min (m) "
                 f"— SYNTHETIC / SIMULATED / PROVISIONAL / NOT FOR OPERATIONAL USE")
        png = render.render_depth_png(tif_path, vmax, label)
    return Response(content=png, media_type="image/png")


@app.get("/api/v1/scenarios/{scenario_id}/flood-depth")
def flood_depth(scenario_id: str, lead: int = Query(..., ge=0, le=180)) -> Response:
    return _map_image(scenario_id, lead, extent=False)


@app.get("/api/v1/scenarios/{scenario_id}/flood-extent")
def flood_extent(scenario_id: str, lead: int = Query(..., ge=0, le=180)) -> Response:
    return _map_image(scenario_id, lead, extent=True)


# ---------------------------------------------------------------------------
# S3/S4 comparison
# ---------------------------------------------------------------------------

@app.get("/api/v1/comparison/s3s4")
def comparison_s3s4() -> dict[str, Any]:
    try:
        return store.s3s4_comparison()
    except store.StoreError as exc:
        raise _store_not_ready() from exc


# ---------------------------------------------------------------------------
# M7 — roads, road impact, policy, routing
# ---------------------------------------------------------------------------

@app.get("/api/v1/roads")
def roads() -> dict[str, Any]:
    """Synthetic road network (SYNTHETIC / DEMO DATA / NOT REAL ROAD GEOMETRY)."""
    return impacts.road_network()


@app.get("/api/v1/policies")
def policies() -> dict[str, Any]:
    """The active B13 passability policy (PROVISIONAL DEMONSTRATION)."""
    return {
        "policies": [impacts.policy()],
        "labels": ["PROVISIONAL", "NOT FOR OPERATIONAL USE"],
    }


@app.get("/api/v1/scenarios/{scenario_id}/frame")
def scenario_frame(scenario_id: str, lead: int = Query(..., ge=0, le=180)) -> dict[str, Any]:
    """One efficient timeline payload: depth grid + road impacts + metrics."""
    _require_scenario(scenario_id)
    _require_lead(lead)
    try:
        return impacts.frame(scenario_id, lead)
    except store.StoreError as exc:
        raise _store_not_ready() from exc


@app.get("/api/v1/scenarios/{scenario_id}/rainfall")
def scenario_rainfall(scenario_id: str, lead: int = Query(..., ge=0, le=180)) -> dict[str, Any]:
    """Deterministic rainfall forcing field (mm/h) for one scenario/lead."""
    _require_scenario(scenario_id)
    _require_lead(lead)
    try:
        return impacts.rainfall_grid(scenario_id, lead)
    except store.StoreError as exc:
        raise _store_not_ready() from exc


@app.get("/api/v1/scenarios/{scenario_id}/road-impact")
def scenario_road_impact(scenario_id: str, lead: int = Query(..., ge=0, le=180)) -> dict[str, Any]:
    """Per-road impact at one snapshot."""
    _require_scenario(scenario_id)
    _require_lead(lead)
    try:
        imp = impacts.impacts_at(scenario_id, lead)
    except store.StoreError as exc:
        raise _store_not_ready() from exc
    return {
        "scenario_id": scenario_id,
        "lead_minutes": lead,
        "road_impacts": [i.to_dict() for i in imp.values()],
        "road_metrics": impacts.road_metrics(scenario_id, lead),
        "policy": impacts.policy(),
        "labels": ["SYNTHETIC", "SIMULATED", "PROVISIONAL"],
    }


@app.get("/api/v1/scenarios/{scenario_id}/road-impact/{road_id}")
def road_impact_timeline(scenario_id: str, road_id: str) -> dict[str, Any]:
    """Full time series of impact for one road."""
    _require_scenario(scenario_id)
    try:
        return impacts.road_impact_timeline(scenario_id, road_id)
    except KeyError as exc:
        raise _error(404, "ROAD_NOT_FOUND",
                     f"unknown road id {road_id!r} for {scenario_id!r}") from exc
    except store.StoreError as exc:
        raise _store_not_ready() from exc


@app.get("/api/v1/scenarios/{scenario_id}/road-metrics")
def scenario_road_metrics(scenario_id: str, lead: int = Query(..., ge=0, le=180)) -> dict[str, Any]:
    """Scenario-level road-impact metrics at one snapshot."""
    _require_scenario(scenario_id)
    _require_lead(lead)
    try:
        return {
            "scenario_id": scenario_id,
            "lead_minutes": lead,
            "road_metrics": impacts.road_metrics(scenario_id, lead),
            "labels": ["SYNTHETIC", "SIMULATED", "PROVISIONAL"],
        }
    except store.StoreError as exc:
        raise _store_not_ready() from exc


@app.post("/api/v1/routes")
def routes(req: RouteRequest) -> dict[str, Any]:
    """Compute baseline + flood-aware routes (and their comparison)."""
    _require_scenario(req.scenario_id)
    _require_lead(req.lead)
    origin = _validate_xy("origin", req.origin)
    destination = _validate_xy("destination", req.destination)
    try:
        return impacts.compute_route_request(
            req.scenario_id, req.lead, list(origin), list(destination), req.mode,
        )
    except store.StoreError as exc:
        raise _store_not_ready() from exc


@app.get("/api/v1/routing/nodes")
def routing_nodes() -> dict[str, Any]:
    """Road intersection coordinates (used by the map to hint endpoints)."""
    return {
        "nodes": impacts.network_nodes_xy(),
        "labels": ["SYNTHETIC", "DEMO DATA"],
    }


@app.get("/api/v1/drainage/points")
def drainage_points() -> dict[str, Any]:
    """Synthetic inlet/vent points for the drainage map layer."""
    return impacts.drainage_points()


# ---------------------------------------------------------------------------
# M8 — Rainfall ingestion, nowcast, and provider management
# ---------------------------------------------------------------------------

@app.get("/api/v1/rainfall/latest")
def rainfall_latest() -> dict[str, Any]:
    """Latest rainfall observation from the active provider."""
    return rainfall_api.fetch_latest_observation()


@app.get("/api/v1/rainfall/status")
def rainfall_status() -> dict[str, Any]:
    """Overall rainfall system status."""
    return rainfall_api.get_rainfall_status()


@app.get("/api/v1/rainfall/observation")
def rainfall_observation(time: str = Query(...)) -> dict[str, Any]:
    """Fetch an observation at a specific time (ISO 8601 / RFC 3339)."""
    try:
        obs_time = datetime.fromisoformat(time.replace("Z", "+00:00"))
        if obs_time.tzinfo is None:
            obs_time = obs_time.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError) as exc:
        raise _error(400, "INVALID_TIMESTAMP",
                     f"invalid timestamp: {time!r}. Use ISO 8601 / RFC 3339.") from exc
    return rainfall_api.fetch_observation_at(obs_time)


@app.get("/api/v1/nowcast/latest")
def nowcast_latest() -> dict[str, Any]:
    """Latest nowcast (all lead times) from the active provider."""
    return rainfall_api.fetch_latest_nowcast()


@app.get("/api/v1/nowcast/status")
def nowcast_status() -> dict[str, Any]:
    """Overall nowcast system status."""
    return rainfall_api.get_nowcast_status()


@app.get("/api/v1/nowcast/providers")
def nowcast_providers() -> dict[str, Any]:
    """List all registered rainfall providers with health status."""
    providers = rainfall_api.list_providers()
    return {
        "providers": providers,
        "active_provider_id": next(
            (p["provider_id"] for p in providers if p["active"]), None
        ),
        "count": len(providers),
        "labels": ["SYNTHETIC", "FIXTURE", "DEMONSTRATION"],
    }


@app.get("/api/v1/nowcast/providers/{provider_id}")
def nowcast_provider_detail(provider_id: str) -> dict[str, Any]:
    """Detail for a specific provider."""
    provider = rainfall_api.get_provider(provider_id)
    if provider is None:
        raise _error(404, "PROVIDER_NOT_FOUND",
                     f"unknown provider id {provider_id!r}",
                     available_providers=[p["provider_id"]
                                          for p in rainfall_api.list_providers()])
    return {
        "provider_id": provider_id,
        "source_type": provider.source_type.value,
        "source_name": provider.source_name,
        "health": provider.health().to_dict(),
        "metadata": provider.metadata(),
    }


@app.get("/api/v1/nowcast/verification")
def nowcast_verification() -> dict[str, Any]:
    """Nowcast verification status (NOT_EVALUATED until real data exists)."""
    from services.nowcast.verification import no_evaluation_available
    return {
        "verification": no_evaluation_available().to_dict(),
        "explanation": (
            "Forecast verification requires paired (forecast, observation) data. "
            "No verified real-time rainfall feed is currently available for the "
            "pilot region (D-017). Status is NOT_EVALUATED — no skill scores are "
            "fabricated. See docs/M8_SCIENTIFIC_REVIEW.md for methodology."
        ),
        "labels": ["NOT_EVALUATED", "NO_REAL_DATA"],
    }


@app.get("/api/v1/nowcast/cache")
def nowcast_cache_stats() -> dict[str, Any]:
    """Cache statistics for the nowcast system."""
    return rainfall_api.get_cache_stats()


@app.get("/api/v1/nowcast/{lead_minutes}")
def nowcast_at_lead(lead_minutes: int) -> dict[str, Any]:
    """Nowcast for a specific lead time (minutes)."""
    result = rainfall_api.fetch_nowcast_at_lead(lead_minutes)
    if result.get("status") == "INVALID_LEAD":
        raise _error(400, "INVALID_LEAD",
                     f"lead {lead_minutes} not in valid lead times",
                     valid_leads=result.get("valid_leads", []))
    if result.get("status") == "UNAVAILABLE":
        raise _error(503, "DATA_UNAVAILABLE",
                     "no observation available for nowcast generation")
    return result


# ---------------------------------------------------------------------------
# M9 — Nowcast -> flood impact -> road impact -> routing projection pipeline
# ---------------------------------------------------------------------------

@app.get("/api/v1/projections/nowcast/status")
def nowcast_projection_status() -> dict[str, Any]:
    return projections.projection_status()


@app.get("/api/v1/projections/nowcast/cache")
def nowcast_projection_cache() -> dict[str, Any]:
    return projections.cache_stats()


@app.get("/api/v1/projections/nowcast/configs")
def nowcast_projection_configs() -> dict[str, Any]:
    return {
        "configs": [projections.projection_config_detail(cid) for cid in VALID_PROJECTION_CONFIG_IDS],
        "count": len(VALID_PROJECTION_CONFIG_IDS),
        "available_leads": list(VALID_PROJECTION_LEADS),
        "labels": ["PERSISTENCE_PROJECTION", "NOT_REAL_TIME", "NOT_VALIDATED_FORECAST"],
    }


@app.get("/api/v1/projections/nowcast/{config_id}")
def nowcast_projection_summary(config_id: str) -> dict[str, Any]:
    _require_projection_config(config_id)
    try:
        return projections.projection_summary(config_id)
    except ProjectionUnavailableError as exc:
        raise _error(503, "PROJECTION_UNAVAILABLE", str(exc)) from exc


@app.get("/api/v1/projections/nowcast/{config_id}/frame")
def nowcast_projection_frame(config_id: str, lead: int = Query(..., ge=0, le=60)) -> dict[str, Any]:
    _require_projection_config(config_id)
    _require_projection_lead(lead)
    try:
        return projections.frame(config_id, lead)
    except ProjectionUnavailableError as exc:
        raise _error(503, "PROJECTION_UNAVAILABLE", str(exc)) from exc


@app.get("/api/v1/projections/nowcast/{config_id}/rainfall")
def nowcast_projection_rainfall(config_id: str, lead: int = Query(..., ge=0, le=60)) -> dict[str, Any]:
    _require_projection_config(config_id)
    _require_projection_lead(lead)
    try:
        return projections.rainfall_frame(config_id, lead)
    except ProjectionUnavailableError as exc:
        raise _error(503, "PROJECTION_UNAVAILABLE", str(exc)) from exc


@app.get("/api/v1/projections/nowcast/{config_id}/flood")
def nowcast_projection_flood(config_id: str, lead: int = Query(..., ge=0, le=60)) -> dict[str, Any]:
    _require_projection_config(config_id)
    _require_projection_lead(lead)
    try:
        return projections.flood_projection(config_id, lead)
    except ProjectionUnavailableError as exc:
        raise _error(503, "PROJECTION_UNAVAILABLE", str(exc)) from exc


@app.get("/api/v1/projections/nowcast/{config_id}/road-impact")
def nowcast_projection_road_impact(config_id: str, lead: int = Query(..., ge=0, le=60)) -> dict[str, Any]:
    _require_projection_config(config_id)
    _require_projection_lead(lead)
    try:
        return projections.road_projection(config_id, lead)
    except ProjectionUnavailableError as exc:
        raise _error(503, "PROJECTION_UNAVAILABLE", str(exc)) from exc


@app.get("/api/v1/projections/nowcast/{config_id}/road-impact/{road_id}")
def nowcast_projection_road_timeline(config_id: str, road_id: str) -> dict[str, Any]:
    _require_projection_config(config_id)
    try:
        return projections.road_projection_timeline(config_id, road_id)
    except KeyError as exc:
        raise _error(404, "ROAD_NOT_FOUND", f"unknown road id {road_id!r}") from exc
    except ProjectionUnavailableError as exc:
        raise _error(503, "PROJECTION_UNAVAILABLE", str(exc)) from exc


@app.post("/api/v1/projections/nowcast/{config_id}/routes")
def nowcast_projection_routes(config_id: str, req: ProjectionRouteRequest) -> dict[str, Any]:
    _require_projection_config(config_id)
    _require_projection_lead(req.lead)
    origin = _validate_xy("origin", req.origin)
    destination = _validate_xy("destination", req.destination)
    try:
        return projections.compute_route_request(
            config_id, req.lead, list(origin), list(destination), req.mode
        )
    except ProjectionUnavailableError as exc:
        raise _error(503, "PROJECTION_UNAVAILABLE", str(exc)) from exc


# ---------------------------------------------------------------------------
# M11 — Real-pilot inspection (Section 17)
# ---------------------------------------------------------------------------

def _pilot_not_ready() -> HTTPException:
    return _error(
        503, "PILOT_INSPECTION_UNAVAILABLE",
        "M11 real-pilot inspection artifact missing — run "
        "`python scripts/run_m11_real_pilot_validation.py`",
    )


@app.get("/api/v1/pilot/real")
def pilot_real_overview() -> dict[str, Any]:
    """Real-pilot inspection overview (DEM/drainage/hydraulic readiness/grid).

    Truthful labels only: REAL_PILOT / REAL_TERRAIN / SYNTHETIC_HYDRAULICS /
    PROVISIONAL / MISSING / UNRESOLVED / NOT_REAL_TIME / NOT_VALIDATED_FORECAST.
    Never implies operational forecasting or real drainage hydraulic capacity.
    """
    try:
        return pilot.pilot_overview()
    except pilot.PilotStoreError as exc:
        raise _pilot_not_ready() from exc


@app.get("/api/v1/pilot/real/dem")
def pilot_real_dem() -> dict[str, Any]:
    try:
        return pilot.pilot_dem()
    except pilot.PilotStoreError as exc:
        raise _pilot_not_ready() from exc


@app.get("/api/v1/pilot/real/drainage")
def pilot_real_drainage() -> dict[str, Any]:
    """Real drainage coverage + mapped/unresolved/rejected counts.

    Real drainage GEOMETRY only — NOT a real hydraulic network (hydraulics
    MISSING). Never implies real drainage hydraulic capacity.
    """
    try:
        return pilot.pilot_drainage()
    except pilot.PilotStoreError as exc:
        raise _pilot_not_ready() from exc


@app.get("/api/v1/pilot/real/hydraulic-readiness")
def pilot_real_hydraulic_readiness() -> dict[str, Any]:
    """Formal hydraulic readiness contract (MISSING / ASSUMED / UNRESOLVED)."""
    try:
        return pilot.pilot_hydraulic_readiness()
    except pilot.PilotStoreError as exc:
        raise _pilot_not_ready() from exc


@app.exception_handler(pilot.PilotStoreError)
async def _pilot_error_handler(request, exc: pilot.PilotStoreError):
    return JSONResponse(
        status_code=503,
        content={"error": {"code": "PILOT_INSPECTION_UNAVAILABLE", "message": str(exc)}},
    )


# ---------------------------------------------------------------------------
# Global exception handling (structured errors, never hide model failures)
# ---------------------------------------------------------------------------

@app.exception_handler(HTTPException)
async def _http_exception_handler(request, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, dict) and "error" in detail:
        return JSONResponse(status_code=exc.status_code, content=detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": "HTTP_ERROR", "message": str(detail)}},
    )


from fastapi.exceptions import RequestValidationError


@app.exception_handler(RequestValidationError)
async def _validation_error_handler(request, exc: RequestValidationError):
    safe_details = []
    for err in exc.errors():
        safe_details.append({
            "loc": list(err.get("loc", ())),
            "type": str(err.get("type", "value_error")),
        })
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed",
                "details": safe_details,
            }
        },
    )


@app.exception_handler(store.StoreError)
async def _store_error_handler(request, exc: store.StoreError):
    return JSONResponse(
        status_code=503,
        content={"error": {"code": "ARTIFACTS_UNAVAILABLE", "message": str(exc)}},
    )
