from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from time import perf_counter
from typing import Any

import numpy as np

from apps.api import rainfall_api
from services.ingestion.dem import synthetic_dem
from services.nowcast.engine import PersistenceNowcast
from services.nowcast.providers import RainfallObservation
from services.nowcast.quality import QualityResult, validate_observation
from services.projection import MODEL_VERSION
from services.projection.adapter import (
    build_runconfig_from_frames,
    nowcast_records_to_frames,
)
from services.projection.cache import ProjectionCache
from services.projection.configs import (
    ProjectionConfigRecord,
    get_projection_config,
)
from services.projection.contracts import (
    FloodImpactProjection,
    ForecastRainfallFrame,
    RoadImpactProjection,
    RouteProjection,
)
from services.routing.impact import build_index, metrics_at_lead, time_aggregates
from services.routing.policy import POLICY
from services.routing.roads import NETWORK
from services.routing.router import compute_route
from services.simulation.engine import CoupledFloodModel


class ProjectionUnavailableError(RuntimeError):
    """Raised when a projection cannot be generated from the active nowcast state."""


@dataclass(frozen=True)
class ProjectionBundle:
    config: ProjectionConfigRecord
    observation: RainfallObservation
    quality: QualityResult
    nowcast_records: tuple[Any, ...]
    rainfall_frames: tuple[ForecastRainfallFrame, ...]
    flood_projections: dict[int, FloodImpactProjection]
    road_projections: dict[int, RoadImpactProjection]
    configuration_fingerprint: str
    projection_key: str
    timings_ms: dict[str, float]
    cache_hit: bool

    def summary(self) -> dict[str, Any]:
        return {
            "config": self.config.to_dict(),
            "observation": self.observation.to_dict(),
            "quality": self.quality.to_dict(),
            "lead_times_minutes": sorted(self.flood_projections),
            "configuration_fingerprint": self.configuration_fingerprint,
            "projection_key": self.projection_key,
            "timings_ms": self.timings_ms,
            "cache_hit": self.cache_hit,
            "labels": list(self.config.labels),
            "observation_fingerprint": self.observation.fingerprint(),
            "nowcast_fingerprints": {
                lead: proj.nowcast_fingerprint for lead, proj in sorted(self.flood_projections.items())
            },
            "projection_fingerprints": {
                lead: proj.projection_fingerprint for lead, proj in sorted(self.flood_projections.items())
            },
        }


class ProjectionPipeline:
    """Build and cache M9 persistence-impact projection bundles."""

    def __init__(self, ttl_seconds: int = 300) -> None:
        self._cache = ProjectionCache(ttl_seconds=ttl_seconds)
        self._compute_lock = threading.RLock()

    @property
    def cache(self) -> ProjectionCache:
        return self._cache

    def build_from_latest(self, config_id: str) -> ProjectionBundle:
        get_projection_config(config_id)
        nowcast_t0 = perf_counter()
        _provider, observation, quality, records = rainfall_api.fetch_latest_nowcast_records()
        nowcast_ms = (perf_counter() - nowcast_t0) * 1000.0
        if observation is None:
            raise ProjectionUnavailableError("no rainfall observation available for projection")
        if not quality.valid:
            raise ProjectionUnavailableError(
                "; ".join(quality.errors) or "active rainfall observation failed validation"
            )
        if not records:
            raise ProjectionUnavailableError("no nowcast records available for projection")
        return self.build_from_observation(
            config_id,
            observation,
            quality=quality,
            nowcast_records=records,
            base_timings_ms={"nowcast_generation": nowcast_ms},
        )

    def build_from_observation(
        self,
        config_id: str,
        observation: RainfallObservation,
        *,
        quality: QualityResult | None = None,
        nowcast_records: list[Any] | None = None,
        base_timings_ms: dict[str, float] | None = None,
    ) -> ProjectionBundle:
        config = get_projection_config(config_id)
        quality = quality or validate_observation(observation)
        if not quality.valid:
            raise ProjectionUnavailableError(
                "; ".join(quality.errors) or "projection observation failed validation"
            )

        timings_ms = dict(base_timings_ms or {})
        if nowcast_records is None:
            t0 = perf_counter()
            engine = PersistenceNowcast(rainfall_api.get_nowcast_config())
            nowcast_records = engine.generate(observation, quality)
            timings_ms.setdefault("nowcast_generation", (perf_counter() - t0) * 1000.0)
        if not nowcast_records:
            raise ProjectionUnavailableError("projection nowcast generation returned no records")

        frames = nowcast_records_to_frames(nowcast_records, interval_minutes=config.rainfall_interval_minutes)
        dem = synthetic_dem()
        run_config = build_runconfig_from_frames(config, frames, dem)
        combined_nowcast_fp = self._combine_nowcast_fingerprints(nowcast_records)
        projection_key = self._bundle_key(
            observation_fingerprint=observation.fingerprint(),
            nowcast_fingerprint=combined_nowcast_fp,
            config_fingerprint=config.fingerprint,
            runconfig_fingerprint=run_config.fingerprint(),
        )

        cached = self._cache.get(projection_key)
        if cached is not None:
            timings = dict(cached.timings_ms)
            timings.update(timings_ms)
            return ProjectionBundle(
                config=cached.config,
                observation=cached.observation,
                quality=cached.quality,
                nowcast_records=cached.nowcast_records,
                rainfall_frames=cached.rainfall_frames,
                flood_projections=cached.flood_projections,
                road_projections=cached.road_projections,
                configuration_fingerprint=cached.configuration_fingerprint,
                projection_key=cached.projection_key,
                timings_ms=timings,
                cache_hit=True,
            )

        with self._compute_lock:
            cached = self._cache.get(projection_key)
            if cached is not None:
                timings = dict(cached.timings_ms)
                timings.update(timings_ms)
                return ProjectionBundle(
                    config=cached.config,
                    observation=cached.observation,
                    quality=cached.quality,
                    nowcast_records=cached.nowcast_records,
                    rainfall_frames=cached.rainfall_frames,
                    flood_projections=cached.flood_projections,
                    road_projections=cached.road_projections,
                    configuration_fingerprint=cached.configuration_fingerprint,
                    projection_key=cached.projection_key,
                    timings_ms=timings,
                    cache_hit=True,
                )

            flood_t0 = perf_counter()
            result = CoupledFloodModel(run_config).run()
            timings_ms["flood_projection"] = (perf_counter() - flood_t0) * 1000.0
            timings_ms["flood_projection_per_lead"] = timings_ms["flood_projection"] / max(len(config.lead_times_minutes), 1)

            road_t0 = perf_counter()
            flood = self._build_flood_projections(
                config,
                observation,
                frames,
                result,
                configuration_fingerprint=run_config.fingerprint(),
            )
            road = self._build_road_projections(config, flood)
            timings_ms["road_impact"] = (perf_counter() - road_t0) * 1000.0
            timings_ms["total_projection"] = sum(timings_ms.values())

            bundle = ProjectionBundle(
                config=config,
                observation=observation,
                quality=quality,
                nowcast_records=tuple(nowcast_records),
                rainfall_frames=tuple(frames),
                flood_projections=flood,
                road_projections=road,
                configuration_fingerprint=run_config.fingerprint(),
                projection_key=projection_key,
                timings_ms=timings_ms,
                cache_hit=False,
            )
            self._cache.put(projection_key, bundle)
            return bundle

    def route(
        self,
        bundle: ProjectionBundle,
        lead_minutes: int,
        origin_xy: tuple[float, float],
        destination_xy: tuple[float, float],
        mode: str,
    ) -> RouteProjection:
        if lead_minutes not in bundle.road_projections:
            raise KeyError(lead_minutes)
        road_projection = bundle.road_projections[lead_minutes]
        routing_t0 = perf_counter()
        impacts = {impact.road_id: impact for impact in road_projection.road_impacts}
        route_result = compute_route(
            NETWORK,
            impacts,
            origin_xy,
            destination_xy,
            mode,
            bundle.config.config_id,
            lead_minutes,
            road_projection.valid_time.isoformat(),
        )
        routing_ms = (perf_counter() - routing_t0) * 1000.0
        payload = {
            "config_id": bundle.config.config_id,
            "lead_minutes": lead_minutes,
            "mode": mode,
            "origin_xy": [round(origin_xy[0], 3), round(origin_xy[1], 3)],
            "destination_xy": [round(destination_xy[0], 3), round(destination_xy[1], 3)],
            "projection_fingerprint": road_projection.projection_fingerprint,
            "routing": route_result.to_dict(),
        }
        route_fp = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return RouteProjection(
            config_id=bundle.config.config_id,
            lead_minutes=lead_minutes,
            valid_time=road_projection.valid_time,
            routing=route_result,
            projection_fingerprint=road_projection.projection_fingerprint,
            route_projection_fingerprint=route_fp,
            labels=bundle.config.labels,
            timings_ms={"routing": routing_ms},
        )

    @staticmethod
    def _combine_nowcast_fingerprints(records: list[Any]) -> str:
        canon = json.dumps(
            [record.fingerprint or record.compute_fingerprint() for record in records],
            separators=(",", ":"),
        )
        return hashlib.sha256(canon.encode("utf-8")).hexdigest()

    @staticmethod
    def _bundle_key(
        *,
        observation_fingerprint: str,
        nowcast_fingerprint: str,
        config_fingerprint: str,
        runconfig_fingerprint: str,
    ) -> str:
        payload = {
            "observation_fingerprint": observation_fingerprint,
            "nowcast_fingerprint": nowcast_fingerprint,
            "config_fingerprint": config_fingerprint,
            "runconfig_fingerprint": runconfig_fingerprint,
            "model_version": MODEL_VERSION,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _build_flood_projections(
        config: ProjectionConfigRecord,
        observation: RainfallObservation,
        frames: list[ForecastRainfallFrame],
        result,
        *,
        configuration_fingerprint: str,
    ) -> dict[int, FloodImpactProjection]:
        frame_by_lead = {frame.lead_minutes: frame for frame in frames}
        snapshot_by_lead = {snapshot.lead_minutes: snapshot for snapshot in result.snapshots}
        out: dict[int, FloodImpactProjection] = {}
        mass_balance = result.mass_balance.model_dump(mode="json")
        for lead in config.lead_times_minutes:
            snapshot = snapshot_by_lead[lead]
            frame = frame_by_lead[lead]
            depth = result.depth_arrays[lead].copy()
            payload = {
                "config_id": config.config_id,
                "lead_minutes": lead,
                "configuration_fingerprint": configuration_fingerprint,
                "rainfall_frame_fingerprint": frame.fingerprint,
                "observation_fingerprint": observation.fingerprint(),
                "depth_field_hash": hashlib.sha256(np.ascontiguousarray(depth).tobytes()).hexdigest(),
                "engine_version": result.simulation_run.model_versions.get("engine", ""),
                "model_version": MODEL_VERSION,
            }
            projection_fp = hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            out[lead] = FloodImpactProjection(
                config_id=config.config_id,
                initialization_time=frame.initialization_time,
                valid_time=frame.valid_time,
                lead_minutes=lead,
                rainfall_frame=frame,
                depth_m=depth,
                flooded_area_m2=snapshot.flooded_area_m2,
                flooded_cells=snapshot.flooded_cells,
                extent_threshold_m=snapshot.extent_threshold_m,
                total_surface_storage_m3=snapshot.total_surface_storage_m3,
                drainage={
                    "st1_head_m": round(snapshot.drainage.st1_head_m, 6),
                    "st1_depth_m": round(snapshot.drainage.st1_depth_m, 6),
                    "vent_depth_m": round(snapshot.drainage.vent_depth_m, 6),
                    "vent_head_m": round(snapshot.drainage.vent_head_m, 6),
                    "outfall_cum_m3": round(snapshot.drainage.outfall_cum_m3, 4),
                    "flooding_cum_m3": round(snapshot.drainage.flooding_cum_m3, 4),
                    "exchange_S2D_cum_m3": round(snapshot.drainage.exchange_S2D_cum_m3, 4),
                    "exchange_D2S_cum_m3": round(snapshot.drainage.exchange_D2S_cum_m3, 4),
                    "surcharged": snapshot.drainage.surcharged,
                },
                model_version=MODEL_VERSION,
                engine_version=result.simulation_run.model_versions.get("engine", ""),
                configuration_fingerprint=configuration_fingerprint,
                observation_fingerprint=observation.fingerprint(),
                nowcast_fingerprint=frame.nowcast_fingerprint,
                projection_fingerprint=projection_fp,
                status="AVAILABLE",
                mass_balance={
                    **mass_balance,
                    "gate": str(result.mass_balance.status).upper(),
                    "run_wall_seconds": round(result.wall_seconds, 3),
                    "run_cpu_seconds": round(result.cpu_seconds, 3),
                    "peak_rss_mb": round(result.peak_rss_mb, 1),
                },
                labels=config.labels,
            )
        return out

    @staticmethod
    def _build_road_projections(
        config: ProjectionConfigRecord,
        flood_projections: dict[int, FloodImpactProjection],
    ) -> dict[int, RoadImpactProjection]:
        grids = {lead: projection.depth_m for lead, projection in flood_projections.items()}
        valid_times = {lead: projection.valid_time.isoformat() for lead, projection in flood_projections.items()}
        index = build_index(NETWORK, grids, config.config_id, valid_times)
        aggregates = time_aggregates(NETWORK, index)
        out: dict[int, RoadImpactProjection] = {}
        for lead, impacts in index.items():
            road_metrics = metrics_at_lead(NETWORK, impacts)
            road_metrics.update(aggregates)
            payload = {
                "config_id": config.config_id,
                "lead_minutes": lead,
                "projection_fingerprint": flood_projections[lead].projection_fingerprint,
                "policy_fingerprint": POLICY.fingerprint,
                "network_fingerprint": NETWORK.fingerprint,
                "road_impact_fingerprints": [impact.to_dict() for impact in impacts.values()],
            }
            road_fp = hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            out[lead] = RoadImpactProjection(
                config_id=config.config_id,
                initialization_time=flood_projections[lead].initialization_time,
                valid_time=flood_projections[lead].valid_time,
                lead_minutes=lead,
                road_impacts=tuple(impacts.values()),
                road_metrics=road_metrics,
                projection_fingerprint=flood_projections[lead].projection_fingerprint,
                policy_version=POLICY.policy_id,
                policy_fingerprint=POLICY.fingerprint,
                network_fingerprint=NETWORK.fingerprint,
                road_projection_fingerprint=road_fp,
                labels=config.labels,
            )
        return out


PIPELINE = ProjectionPipeline(ttl_seconds=300)
