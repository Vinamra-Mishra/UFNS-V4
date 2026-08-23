from __future__ import annotations

from typing import Any

from services.projection import MODEL_VERSION, PROJECTION_METHOD, VALID_LEADS
from services.projection.configs import PROJECTION_CONFIGS, get_projection_config
from services.projection.pipeline import (
    PIPELINE,
    ProjectionBundle,
)
from services.routing.roads import NETWORK


def projection_status() -> dict[str, Any]:
    return {
        "projection_version": MODEL_VERSION,
        "projection_method": PROJECTION_METHOD,
        "available_leads": list(VALID_LEADS),
        "configs": [cfg.to_dict() for cfg in PROJECTION_CONFIGS.values()],
        "cache": PIPELINE.cache.stats(),
        "labels": [
            "PERSISTENCE_PROJECTION",
            "NOT_REAL_TIME",
            "NOT_VALIDATED_FORECAST",
            "SYNTHETIC",
            "SIMULATED",
        ],
    }


def projection_config_detail(config_id: str) -> dict[str, Any]:
    cfg = get_projection_config(config_id)
    return cfg.to_dict()


def projection_bundle(config_id: str) -> ProjectionBundle:
    return PIPELINE.build_from_latest(config_id)


def projection_summary(config_id: str) -> dict[str, Any]:
    bundle = projection_bundle(config_id)
    return bundle.summary()


def rainfall_frame(config_id: str, lead: int) -> dict[str, Any]:
    bundle = projection_bundle(config_id)
    projection = bundle.flood_projections[lead]
    data = projection.rainfall_frame.to_dict(include_values=True)
    data.update(
        {
            "config_id": config_id,
            "projection_fingerprint": projection.projection_fingerprint,
            "labels": list(bundle.config.labels),
        }
    )
    return data


def flood_projection(config_id: str, lead: int) -> dict[str, Any]:
    bundle = projection_bundle(config_id)
    data = bundle.flood_projections[lead].to_dict(include_depth_values=True)
    data["timings_ms"] = bundle.timings_ms
    data["cache_hit"] = bundle.cache_hit
    return data


def road_projection(config_id: str, lead: int) -> dict[str, Any]:
    bundle = projection_bundle(config_id)
    data = bundle.road_projections[lead].to_dict()
    data["timings_ms"] = bundle.timings_ms
    data["cache_hit"] = bundle.cache_hit
    return data


def road_projection_timeline(config_id: str, road_id: str) -> dict[str, Any]:
    bundle = projection_bundle(config_id)
    seg = NETWORK.by_id().get(road_id)
    if seg is None:
        raise KeyError(road_id)
    series = []
    for lead in sorted(bundle.road_projections):
        impacts = {impact.road_id: impact for impact in bundle.road_projections[lead].road_impacts}
        series.append(impacts[road_id].to_dict())
    first_impacted = next((row["lead_minutes"] for row in series if row["classification"] != "DRY"), None)
    first_impassable = next((row["lead_minutes"] for row in series if row["classification"] == "IMPASSABLE"), None)
    return {
        "config_id": config_id,
        "road_id": road_id,
        "scenario_id": config_id,
        "road_class": seg.road_class,
        "length_m": round(seg.length_m, 3),
        "baseline_speed_kmh": seg.baseline_speed_kmh,
        "geometry": [[round(x, 3), round(y, 3)] for x, y in seg.geometry],
        "series": series,
        "first_impacted_lead_minutes": first_impacted,
        "first_impassable_lead_minutes": first_impassable,
        "source": seg.source,
        "status": seg.status,
        "policy_version": bundle.road_projections[min(bundle.road_projections)].policy_version,
        "policy_fingerprint": bundle.road_projections[min(bundle.road_projections)].policy_fingerprint,
        "projection_key": bundle.projection_key,
        "labels": list(bundle.config.labels),
    }


def frame(config_id: str, lead: int) -> dict[str, Any]:
    bundle = projection_bundle(config_id)
    flood = bundle.flood_projections[lead]
    road = bundle.road_projections[lead]
    rainfall = flood.rainfall_frame
    return {
        "config_id": config_id,
        "scenario_id": config_id,
        "mode": "PERSISTENCE_PROJECTION",
        "lead_minutes": lead,
        "valid_time": flood.valid_time.isoformat(),
        "initialization_time": flood.initialization_time.isoformat(),
        "grid": {
            "width": rainfall.width,
            "height": rainfall.height,
            "cell_size_m": rainfall.spatial_resolution_m,
            "crs": rainfall.spatial_reference,
        },
        "depth": [round(float(v), 6) for v in flood.depth_m.reshape(-1)],
        "depth_units": "m",
        "extent_threshold_m": flood.extent_threshold_m,
        "drainage": flood.drainage,
        "rainfall": {
            "current_intensity_mmh": round(float(rainfall.rate_mmh.mean()), 4),
            "status": rainfall.status,
            "lead_minutes": rainfall.lead_minutes,
            "frame_fingerprint": rainfall.fingerprint,
            "observation_fingerprint": rainfall.observation_fingerprint,
            "nowcast_fingerprint": rainfall.nowcast_fingerprint,
            "nowcast_method": rainfall.nowcast_method,
        },
        "road_impacts": [
            {
                "road_id": impact.road_id,
                "classification": impact.classification,
                "passability": impact.passability,
                "max_depth_m": round(impact.max_depth_m, 4),
                "impacted_fraction": round(impact.impacted_fraction, 4),
            }
            for impact in road.road_impacts
        ],
        "road_metrics": road.road_metrics,
        "projection": {
            "config_id": config_id,
            "config_fingerprint": bundle.config.fingerprint,
            "configuration_fingerprint": flood.configuration_fingerprint,
            "projection_fingerprint": flood.projection_fingerprint,
            "road_projection_fingerprint": road.road_projection_fingerprint,
            "observation_fingerprint": flood.observation_fingerprint,
            "nowcast_fingerprint": flood.nowcast_fingerprint,
            "model_version": flood.model_version,
            "engine_version": flood.engine_version,
            "source_type": rainfall.source_type,
            "source_provider_id": rainfall.source_provider_id,
            "status": flood.status,
        },
        "timings_ms": bundle.timings_ms,
        "cache_hit": bundle.cache_hit,
        "labels": list(bundle.config.labels),
    }


def compute_route_request(
    config_id: str,
    lead: int,
    origin: list[float],
    destination: list[float],
    mode: str,
) -> dict[str, Any]:
    bundle = projection_bundle(config_id)
    route = PIPELINE.route(
        bundle,
        lead,
        (float(origin[0]), float(origin[1])),
        (float(destination[0]), float(destination[1])),
        mode,
    )
    return route.to_dict()


def cache_stats() -> dict[str, Any]:
    return PIPELINE.cache.stats()
