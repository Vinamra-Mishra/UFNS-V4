"""M9 — Nowcast -> flood impact -> road impact -> routing.

This suite verifies the executable M9 pipeline:

    observation
      -> M8 nowcast records
      -> M9 forecast rainfall frames
      -> M4 flood projection
      -> M7 road impact
      -> M7 routing
      -> API/dashboard integration

The tests intentionally preserve the existing scientific guardrails:
- persistence only (no advection, no ML)
- NOT_REAL_TIME demonstration
- NOT_VALIDATED_FORECAST
- B13 remains PROVISIONAL DEMONSTRATION
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pytest
from fastapi.testclient import TestClient

from apps.api import projections as projection_api
from apps.api import rainfall_api
from apps.api.app import app
from services.ingestion.dem import synthetic_dem
from services.nowcast.engine import PersistenceNowcast
from services.nowcast.nowcast_record import NowcastRecord
from services.nowcast.providers import RainfallObservation
from services.nowcast.providers.synthetic_provider import SyntheticRainfallProvider
from services.nowcast.quality import validate_observation
from services.projection import MODEL_VERSION as M9_MODEL_VERSION
from services.projection import VALID_LEADS
from services.projection.adapter import (
    ProjectionAdapterError,
    build_runconfig_from_frames,
    forcing_fields_from_frames,
    nowcast_records_to_frames,
)
from services.projection.configs import get_projection_config
from services.projection.contracts import ForecastRainfallFrame, RoadImpactProjection
from services.projection.pipeline import PIPELINE
from services.routing.impact import compute_road_impact
from services.routing.policy import POLICY
from services.routing.roads import NETWORK, cell_to_projected
from services.routing.router import compute_route

# ---------------------------------------------------------------------------
# Shared helpers (cached so the expensive 60-minute M4 run happens once per case)
# ---------------------------------------------------------------------------


def _observation_for_rate(rate_mmh: float, when: datetime | None = None) -> RainfallObservation:
    when = when or datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
    provider = SyntheticRainfallProvider(base_rate_mmh=rate_mmh, seed=123)
    return provider.fetch_observation(when)


@lru_cache(maxsize=16)
def _bundle(config_id: str, rate_mmh: float) -> object:
    obs = _observation_for_rate(rate_mmh)
    quality = validate_observation(obs, now=obs.observation_time)
    return PIPELINE.build_from_observation(config_id, obs, quality=quality)


NW = cell_to_projected(20, 20)
SE = cell_to_projected(113, 113)


# ---------------------------------------------------------------------------
# Fingerprint backward compatibility regression
# ---------------------------------------------------------------------------

class TestM9FingerprintBackwardCompatibility:
    """Legacy M4 configurations must keep byte-identical fingerprints to the
    pre-M9 payload format: no explicit_fields_mmh key (even as null) may leak
    into the payload for legacy rainfall kinds.

    The expected value is an independent oracle, not derived from
    RunConfig.fingerprint(): a hand-written SHA-256 of the pre-M9 payload
    format (documented field set, canonical JSON) for a fixed deterministic
    fixture, plus a from-scratch reconstruction of that payload in the test.
    """

    # Pre-M9-format fingerprint of the deterministic legacy fixture:
    # run_id "fp_legacy_test", uniform 10 mm/h, synthetic DEM (seed 20260821),
    # data/demo/drainage_synthetic.inp, model m4-coupling-v1.
    KNOWN_PRE_M9_LEGACY_FINGERPRINT = "664a6d8b9b8e042795c2964459e559836d006803ce7ab91d2708989c5ce57981"

    @staticmethod
    def _legacy_config():
        from services.ingestion.dem import synthetic_dem
        from services.simulation.engine import RainfallSpec, RunConfig
        return RunConfig(
            run_id="fp_legacy_test",
            scenario_id="uniform",
            issue_time=datetime(2026, 8, 21, tzinfo=timezone.utc),
            dem=synthetic_dem(),
            rainfall=RainfallSpec(kind="uniform", intensities_mmh=[10.0]),
            inlet_cells=[],
            vent_cell=(95, 79),
        )

    def test_legacy_fingerprint_matches_pre_m9_oracle(self):
        assert self._legacy_config().fingerprint() == self.KNOWN_PRE_M9_LEGACY_FINGERPRINT

    def test_legacy_fingerprint_matches_independent_payload_reconstruction(self):
        """Rebuild the pre-M9 payload by hand and verify it hashes to the same
        value — proves the payload format (field set + canonicalisation), not
        just the output value."""
        import hashlib
        import json
        from pathlib import Path

        import numpy as np

        from services.ingestion.dem import synthetic_dem
        from services.ingestion.provenance import sha256_bytes, sha256_file
        from services.simulation.engine import MODEL_VERSION

        # Pre-M9 RainfallSpec payload: no explicit_fields_mmh key at all.
        rainfall_payload = {
            "kind": "uniform",
            "interval_minutes": 15,
            "intensities_mmh": [10.0],
            "pattern": "uniform",
            "seed": 20260821,
        }
        payload = {
            "run_id": "fp_legacy_test",
            "scenario_id": "uniform",
            "issue_time": "2026-08-21T00:00:00+00:00",
            "dem_sha256": sha256_bytes(
                np.ascontiguousarray(synthetic_dem(), dtype=np.float64).tobytes()
            ),
            "cell_size_m": 30.0,
            "crs": "EPSG:32645",
            "vertical_reference": "SYNTHETIC_LOCAL_DATUM",
            "rainfall": rainfall_payload,
            "losses": {
                "enabled": True,
                "f0_mmh": 25.0,
                "fmin_mmh": 2.0,
                "k_s1": 1.0 / 1800.0,
                "microstore_m": 0.002,
            },
            "mannings_n": 0.03,
            "alpha": 0.5,
            "theta": 0.8,
            "h_init": 1e-06,
            "closed_boundaries": False,
            "drainage_inp_sha256": sha256_file(Path("data/demo/drainage_synthetic.inp")),
            "inlet_cells": [],
            "vent_cell": [95, 79],
            "dt_c": 5,
            "surface_substeps": 5,
            "duration_minutes": 180,
            "snapshot_interval_minutes": 5,
            "extent_threshold_m": 0.05,
            "cd": 0.6,
            "ao_per_inlet": 0.002,
            "ao_vent": None,
            "external_inflow_m3s": 0.0,
            "model_version": MODEL_VERSION,
        }
        canon = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        digest = hashlib.sha256(canon.encode("utf-8")).hexdigest()
        assert digest == self.KNOWN_PRE_M9_LEGACY_FINGERPRINT
        assert digest == self._legacy_config().fingerprint()

    def test_explicit_fields_rainfall_fingerprint_includes_field_data(self):
        """When explicit_fields_mmh is provided, the fingerprint must include
        deterministic field hashes."""
        from services.ingestion.dem import synthetic_dem
        from services.simulation.engine import RainfallSpec, RunConfig
        dem = synthetic_dem()
        field = np.full(dem.shape, 5.0, dtype=np.float32)
        cfg = RunConfig(
            run_id="fp_explicit_test",
            scenario_id="projection",
            issue_time=datetime(2026, 8, 21, tzinfo=timezone.utc),
            dem=dem,
            rainfall=RainfallSpec(kind="explicit_fields", explicit_fields_mmh=[field]),
            inlet_cells=[],
            vent_cell=(95, 79),
            duration_minutes=15,
        )
        fp1 = cfg.fingerprint()
        # Different field content -> different fingerprint
        field2 = np.full(dem.shape, 10.0, dtype=np.float32)
        cfg2 = RunConfig(
            run_id="fp_explicit_test",
            scenario_id="projection",
            issue_time=datetime(2026, 8, 21, tzinfo=timezone.utc),
            dem=dem,
            rainfall=RainfallSpec(kind="explicit_fields", explicit_fields_mmh=[field2]),
            inlet_cells=[],
            vent_cell=(95, 79),
            duration_minutes=15,
        )
        assert cfg2.fingerprint() != fp1
        # Same field content -> same fingerprint
        cfg3 = RunConfig(
            run_id="fp_explicit_test",
            scenario_id="projection",
            issue_time=datetime(2026, 8, 21, tzinfo=timezone.utc),
            dem=dem,
            rainfall=RainfallSpec(kind="explicit_fields", explicit_fields_mmh=[field.copy()]),
            inlet_cells=[],
            vent_cell=(95, 79),
            duration_minutes=15,
        )
        assert cfg3.fingerprint() == fp1

    def test_legacy_vs_explicit_fingerprints_differ(self):
        """Legacy (no explicit fields) and explicit-fields configurations must
        produce different fingerprints even with the same other parameters."""
        from services.ingestion.dem import synthetic_dem
        from services.simulation.engine import RainfallSpec, RunConfig
        dem = synthetic_dem()
        legacy = RunConfig(
            run_id="fp_diff_test",
            scenario_id="test",
            issue_time=datetime(2026, 8, 21, tzinfo=timezone.utc),
            dem=dem,
            rainfall=RainfallSpec(kind="uniform", intensities_mmh=[10.0]),
            inlet_cells=[],
            vent_cell=(95, 79),
        )
        field = np.full(dem.shape, 10.0, dtype=np.float32)
        explicit = RunConfig(
            run_id="fp_diff_test",
            scenario_id="test",
            issue_time=datetime(2026, 8, 21, tzinfo=timezone.utc),
            dem=dem,
            rainfall=RainfallSpec(kind="explicit_fields", explicit_fields_mmh=[field]),
            inlet_cells=[],
            vent_cell=(95, 79),
            duration_minutes=15,
        )
        assert legacy.fingerprint() != explicit.fingerprint()


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------

class TestM9ForecastRainfallFrameContract:
    def _record(self, *, lead: int = 15, values: np.ndarray | None = None) -> NowcastRecord:
        init = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
        values = values if values is not None else np.full((134, 134), 10.0, dtype=np.float32)
        rec = NowcastRecord(
            initialization_time=init,
            valid_time=init + timedelta(minutes=lead),
            lead_minutes=lead,
            rate_mmh=values,
            source_type="SYNTHETIC",
            source_name="test",
            source_provider_id="test-provider",
            metadata={"observation_fingerprint": "obs-fp"},
        )
        return NowcastRecord(
            initialization_time=rec.initialization_time,
            valid_time=rec.valid_time,
            lead_minutes=rec.lead_minutes,
            rate_mmh=rec.rate_mmh,
            units=rec.units,
            spatial_reference=rec.spatial_reference,
            spatial_resolution_m=rec.spatial_resolution_m,
            width=rec.width,
            height=rec.height,
            source_type=rec.source_type,
            source_name=rec.source_name,
            source_provider_id=rec.source_provider_id,
            method=rec.method,
            status=rec.status,
            uncertainty=rec.uncertainty,
            quality_flags=rec.quality_flags,
            fingerprint=rec.compute_fingerprint(),
            metadata=rec.metadata,
        )

    def test_valid_forecast_frame(self):
        rec = self._record()
        frame = ForecastRainfallFrame.from_nowcast_record(
            rec, interval_minutes=15, provenance_status=("PERSISTENCE_PROJECTION",)
        )
        assert frame.lead_minutes == 15
        assert frame.valid_time == frame.initialization_time + timedelta(minutes=15)
        assert frame.valid_to == frame.valid_from + timedelta(minutes=15)
        assert frame.units == "mm/h"
        assert frame.fingerprint

    def test_invalid_units(self):
        rec = self._record()
        with pytest.raises(ValueError, match="mm/h"):
            ForecastRainfallFrame(
                initialization_time=rec.initialization_time,
                valid_time=rec.valid_time,
                valid_from=rec.valid_time,
                valid_to=rec.valid_time + timedelta(minutes=15),
                lead_minutes=rec.lead_minutes,
                rate_mmh=rec.rate_mmh,
                units="mm",
                spatial_reference=rec.spatial_reference,
                spatial_resolution_m=rec.spatial_resolution_m,
                width=rec.width,
                height=rec.height,
                source_type=rec.source_type,
                source_name=rec.source_name,
                source_provider_id=rec.source_provider_id,
                nowcast_method=rec.method,
                nowcast_fingerprint=rec.fingerprint,
                observation_fingerprint="obs-fp",
                status=rec.status,
                provenance_status=("PERSISTENCE_PROJECTION",),
            )

    def test_invalid_dimensions(self):
        rec = self._record()
        with pytest.raises(ValueError, match="shape"):
            ForecastRainfallFrame(
                initialization_time=rec.initialization_time,
                valid_time=rec.valid_time,
                valid_from=rec.valid_time,
                valid_to=rec.valid_time + timedelta(minutes=15),
                lead_minutes=rec.lead_minutes,
                rate_mmh=np.ones((10, 10), dtype=np.float32),
                units=rec.units,
                spatial_reference=rec.spatial_reference,
                spatial_resolution_m=rec.spatial_resolution_m,
                width=134,
                height=134,
                source_type=rec.source_type,
                source_name=rec.source_name,
                source_provider_id=rec.source_provider_id,
                nowcast_method=rec.method,
                nowcast_fingerprint=rec.fingerprint,
                observation_fingerprint="obs-fp",
                status=rec.status,
                provenance_status=("PERSISTENCE_PROJECTION",),
            )

    def test_invalid_timestamps(self):
        rec = self._record()
        with pytest.raises(ValueError, match="valid_to"):
            ForecastRainfallFrame(
                initialization_time=rec.initialization_time,
                valid_time=rec.valid_time,
                valid_from=rec.valid_time,
                valid_to=rec.valid_time,
                lead_minutes=rec.lead_minutes,
                rate_mmh=rec.rate_mmh,
                units=rec.units,
                spatial_reference=rec.spatial_reference,
                spatial_resolution_m=rec.spatial_resolution_m,
                width=rec.width,
                height=rec.height,
                source_type=rec.source_type,
                source_name=rec.source_name,
                source_provider_id=rec.source_provider_id,
                nowcast_method=rec.method,
                nowcast_fingerprint=rec.fingerprint,
                observation_fingerprint="obs-fp",
                status=rec.status,
                provenance_status=("PERSISTENCE_PROJECTION",),
            )

    def test_invalid_lead(self):
        rec = self._record(lead=15)
        with pytest.raises(ValueError, match="lead_minutes"):
            ForecastRainfallFrame(
                initialization_time=rec.initialization_time,
                valid_time=rec.valid_time,
                valid_from=rec.valid_time,
                valid_to=rec.valid_time + timedelta(minutes=15),
                lead_minutes=30,
                rate_mmh=rec.rate_mmh,
                units=rec.units,
                spatial_reference=rec.spatial_reference,
                spatial_resolution_m=rec.spatial_resolution_m,
                width=rec.width,
                height=rec.height,
                source_type=rec.source_type,
                source_name=rec.source_name,
                source_provider_id=rec.source_provider_id,
                nowcast_method=rec.method,
                nowcast_fingerprint=rec.fingerprint,
                observation_fingerprint="obs-fp",
                status=rec.status,
                provenance_status=("PERSISTENCE_PROJECTION",),
            )

    def test_invalid_rainfall_values(self):
        rec = self._record()
        with pytest.raises(ValueError, match="negative"):
            ForecastRainfallFrame(
                initialization_time=rec.initialization_time,
                valid_time=rec.valid_time,
                valid_from=rec.valid_time,
                valid_to=rec.valid_time + timedelta(minutes=15),
                lead_minutes=rec.lead_minutes,
                rate_mmh=np.full((134, 134), -1.0, dtype=np.float32),
                units=rec.units,
                spatial_reference=rec.spatial_reference,
                spatial_resolution_m=rec.spatial_resolution_m,
                width=rec.width,
                height=rec.height,
                source_type=rec.source_type,
                source_name=rec.source_name,
                source_provider_id=rec.source_provider_id,
                nowcast_method=rec.method,
                nowcast_fingerprint=rec.fingerprint,
                observation_fingerprint="obs-fp",
                status=rec.status,
                provenance_status=("PERSISTENCE_PROJECTION",),
            )


# ---------------------------------------------------------------------------
# Persistence semantics
# ---------------------------------------------------------------------------

class TestM9PersistenceSemantics:
    def test_leads_0_15_30_45_60_present(self):
        obs = _observation_for_rate(40.0)
        records = PersistenceNowcast().generate(obs)
        frames = nowcast_records_to_frames(records)
        assert [frame.lead_minutes for frame in frames] == [0, 15, 30, 45, 60]

    def test_exact_field_equality_across_leads(self):
        obs = _observation_for_rate(40.0)
        records = PersistenceNowcast().generate(obs)
        frames = nowcast_records_to_frames(records)
        for frame in frames:
            np.testing.assert_array_equal(frame.rate_mmh, obs.rate_mmh)

    def test_forcing_fields_use_interval_start_frames_without_transform(self):
        obs = _observation_for_rate(40.0)
        records = PersistenceNowcast().generate(obs)
        frames = nowcast_records_to_frames(records)
        forcing = forcing_fields_from_frames(frames, max_lead_minutes=60)
        assert len(forcing) == 4
        for field in forcing:
            np.testing.assert_array_equal(field, obs.rate_mmh)


# ---------------------------------------------------------------------------
# Adapter tests
# ---------------------------------------------------------------------------

class TestM9Adapter:
    def test_build_runconfig_preserves_grid_and_units(self):
        obs = _observation_for_rate(40.0)
        records = PersistenceNowcast().generate(obs)
        frames = nowcast_records_to_frames(records)
        cfg = build_runconfig_from_frames(get_projection_config("P_NORMAL"), frames, synthetic_dem())
        assert cfg.rainfall.kind == "explicit_fields"
        assert cfg.rainfall.interval_minutes == 15
        assert len(cfg.rainfall.explicit_fields_mmh) == 4
        for field in cfg.rainfall.explicit_fields_mmh:
            assert field.shape == obs.rate_mmh.shape
            np.testing.assert_array_equal(field, obs.rate_mmh)

    def test_grid_compatibility_rejected(self):
        obs = _observation_for_rate(40.0)
        records = PersistenceNowcast().generate(obs)
        frames = nowcast_records_to_frames(records)
        with pytest.raises(ProjectionAdapterError, match="incompatible"):
            build_runconfig_from_frames(get_projection_config("P_NORMAL"), frames, np.zeros((10, 10), dtype=np.float32))

    def test_provenance_and_fingerprint_preserved(self):
        obs = _observation_for_rate(40.0)
        records = PersistenceNowcast().generate(obs)
        frames = nowcast_records_to_frames(records)
        for frame, record in zip(frames, records):
            assert frame.nowcast_fingerprint == record.fingerprint
            assert frame.observation_fingerprint == record.metadata["observation_fingerprint"]
            assert frame.fingerprint

    def test_explicit_fields_match_uniform_engine_input(self):
        init = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
        rate = np.full((134, 134), 10.0, dtype=np.float32)
        rec = NowcastRecord(
            initialization_time=init,
            valid_time=init,
            lead_minutes=0,
            rate_mmh=rate,
            metadata={"observation_fingerprint": "obs-fp"},
        )
        rec = NowcastRecord(
            initialization_time=rec.initialization_time,
            valid_time=rec.valid_time,
            lead_minutes=rec.lead_minutes,
            rate_mmh=rec.rate_mmh,
            units=rec.units,
            spatial_reference=rec.spatial_reference,
            spatial_resolution_m=rec.spatial_resolution_m,
            width=rec.width,
            height=rec.height,
            source_type=rec.source_type,
            source_name=rec.source_name,
            source_provider_id=rec.source_provider_id,
            method=rec.method,
            status=rec.status,
            uncertainty=rec.uncertainty,
            quality_flags=rec.quality_flags,
            fingerprint=rec.compute_fingerprint(),
            metadata=rec.metadata,
        )
        records = [
            NowcastRecord(
                initialization_time=init,
                valid_time=init + timedelta(minutes=lead),
                lead_minutes=lead,
                rate_mmh=rate.copy(),
                metadata={"observation_fingerprint": "obs-fp"},
                fingerprint="",
            )
            for lead in VALID_LEADS
        ]
        frames = nowcast_records_to_frames(records)
        cfg = build_runconfig_from_frames(get_projection_config("P_NORMAL"), frames, synthetic_dem())
        assert cfg.rainfall.kind == "explicit_fields"
        np.testing.assert_array_equal(cfg.rainfall.explicit_fields_mmh[0], rate)


# ---------------------------------------------------------------------------
# Flood projection tests
# ---------------------------------------------------------------------------

class TestM9FloodProjection:
    def test_nowcast_produces_projection(self):
        bundle = _bundle("P_NORMAL", 40.0)
        proj = bundle.flood_projections[60]
        assert proj.status == "AVAILABLE"
        assert proj.to_dict()["max_depth_m"] > 0
        assert proj.flooded_area_m2 >= 0

    def test_deterministic_result(self):
        # The @lru_cache on _bundle() would return the same object for identical
        # arguments, which does NOT prove deterministic independent execution.
        # Construct two genuinely independent pipeline runs with caches cleared
        # between them and compare the complete deterministic output contract.
        _bundle.cache_clear()
        PIPELINE.cache.clear()
        bundle_a = _bundle("P_NORMAL", 40.0)
        _bundle.cache_clear()
        PIPELINE.cache.clear()
        bundle_b = _bundle("P_NORMAL", 40.0)
        assert bundle_a is not bundle_b

        # Lead sets must match exactly — a missing or reordered lead fails here.
        assert sorted(bundle_a.flood_projections) == [0, 15, 30, 45, 60]
        assert sorted(bundle_a.flood_projections) == sorted(bundle_b.flood_projections)
        assert [f.lead_minutes for f in bundle_a.rainfall_frames] == [0, 15, 30, 45, 60]
        assert [f.lead_minutes for f in bundle_a.rainfall_frames] == [
            f.lead_minutes for f in bundle_b.rainfall_frames
        ]

        # Rainfall-frame fingerprints; strict zip so a length mismatch cannot
        # be silently truncated.
        for frame_a, frame_b in zip(bundle_a.rainfall_frames, bundle_b.rainfall_frames, strict=True):
            assert frame_a.fingerprint == frame_b.fingerprint
            assert frame_a.nowcast_fingerprint == frame_b.nowcast_fingerprint
            assert frame_a.observation_fingerprint == frame_b.observation_fingerprint

        for lead in (0, 15, 30, 45, 60):
            fa = bundle_a.flood_projections[lead]
            fb = bundle_b.flood_projections[lead]
            assert fa.projection_fingerprint == fb.projection_fingerprint
            assert fa.configuration_fingerprint == fb.configuration_fingerprint
            assert fa.observation_fingerprint == fb.observation_fingerprint
            assert fa.nowcast_fingerprint == fb.nowcast_fingerprint
            np.testing.assert_array_equal(fa.depth_m, fb.depth_m)
            assert fa.flooded_area_m2 == fb.flooded_area_m2
            assert fa.flooded_cells == fb.flooded_cells
            assert fa.total_surface_storage_m3 == fb.total_surface_storage_m3
            assert fa.extent_threshold_m == fb.extent_threshold_m
            assert fa.drainage == fb.drainage
            # mass_balance: compare the complete deterministic scientific
            # content. The three resource fields are wall-clock measurements
            # by construction — pinned for presence, excluded from equality.
            runtime_keys = {"run_wall_seconds", "run_cpu_seconds", "peak_rss_mb"}
            assert runtime_keys <= fa.mass_balance.keys()
            assert runtime_keys <= fb.mass_balance.keys()
            mb_a = {k: v for k, v in fa.mass_balance.items() if k not in runtime_keys}
            mb_b = {k: v for k, v in fb.mass_balance.items() if k not in runtime_keys}
            assert mb_a == mb_b
            assert fa.labels == fb.labels

            ra = bundle_a.road_projections[lead]
            rb = bundle_b.road_projections[lead]
            assert ra.projection_fingerprint == rb.projection_fingerprint
            assert ra.road_projection_fingerprint == rb.road_projection_fingerprint
            assert ra.policy_version == rb.policy_version
            assert ra.policy_fingerprint == rb.policy_fingerprint
            assert ra.network_fingerprint == rb.network_fingerprint
            assert ra.road_metrics == rb.road_metrics
            assert len(ra.road_impacts) == len(rb.road_impacts)
            for impact_a, impact_b in zip(ra.road_impacts, rb.road_impacts, strict=True):
                assert impact_a.road_id == impact_b.road_id
                assert impact_a.classification == impact_b.classification
                assert impact_a.passability == impact_b.passability
                assert impact_a.max_depth_m == impact_b.max_depth_m
                assert impact_a.mean_depth_m == impact_b.mean_depth_m
                assert impact_a.impacted_fraction == impact_b.impacted_fraction

    def test_peak_depth_extent_and_mass_balance_available(self):
        bundle = _bundle("P_NORMAL", 40.0)
        proj = bundle.flood_projections[60]
        data = proj.to_dict()
        assert data["max_depth_m"] >= 0
        assert data["flooded_area_m2"] >= 0
        assert data["mass_balance"]["gate"] == "PASS"

    def test_model_version_preserved(self):
        bundle = _bundle("P_NORMAL", 40.0)
        proj = bundle.flood_projections[60]
        assert proj.model_version == M9_MODEL_VERSION
        assert proj.engine_version.startswith("m4")


# ---------------------------------------------------------------------------
# Multi-lead tests
# ---------------------------------------------------------------------------

class TestM9MultiLead:
    def test_all_five_leads_available(self):
        bundle = _bundle("P_NORMAL", 40.0)
        assert sorted(bundle.flood_projections) == [0, 15, 30, 45, 60]

    def test_valid_time_correct(self):
        bundle = _bundle("P_NORMAL", 40.0)
        init = bundle.observation.observation_time
        for lead, proj in bundle.flood_projections.items():
            assert proj.valid_time == init + timedelta(minutes=lead)

    def test_each_projection_traceable_to_same_observation(self):
        bundle = _bundle("P_NORMAL", 40.0)
        obs_fp = bundle.observation.fingerprint()
        assert {proj.observation_fingerprint for proj in bundle.flood_projections.values()} == {obs_fp}


# ---------------------------------------------------------------------------
# Road impact tests
# ---------------------------------------------------------------------------

class TestM9RoadImpact:
    def test_projected_depth_reaches_existing_road_impact_logic(self):
        bundle = _bundle("P_NORMAL", 40.0)
        road = bundle.road_projections[60]
        assert road.road_metrics["total_segments"] == NETWORK.n_segments
        assert road.policy_version == "B13-DEMO-V1"

    def test_road_impact_changes_when_projection_input_changes(self):
        dry_bundle = _bundle("P_NORMAL", 20.0)
        wet_bundle = _bundle("P_NORMAL", 40.0)
        assert dry_bundle.road_projections[60].road_metrics["impacted_segments"] < wet_bundle.road_projections[60].road_metrics["impacted_segments"]

    def test_synthetic_road_labeling_preserved(self):
        # Fixed observation: a wall-clock-dependent provider would make the
        # timeline (and this assertion) non-reproducible.
        class TestM9API_RoadHelper:
            @staticmethod
            def _current_fixed_observation(rate_mmh: float = 40.0) -> RainfallObservation:
                now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
                return SyntheticRainfallProvider(base_rate_mmh=rate_mmh, seed=123).fetch_observation(now)

        obs = TestM9API_RoadHelper._current_fixed_observation(rate_mmh=40.0)
        provider = rainfall_api.get_active_provider()
        projection_api.PIPELINE.cache.clear()
        with mock.patch.object(provider, "fetch_latest", return_value=obs):
            road = projection_api.road_projection_timeline("P_NORMAL", "R-001")
        assert road["source"] == "SYNTHETIC_DEMO"
        assert "NOT REAL ROAD GEOMETRY" in road["status"]


# ---------------------------------------------------------------------------
# Routing tests
# ---------------------------------------------------------------------------

class TestM9Routing:
    def test_routing_consumes_projected_impact(self):
        bundle = _bundle("P_NORMAL", 140.0)
        route = PIPELINE.route(bundle, 60, NW, SE, "flood_aware")
        data = route.to_dict()
        assert data["lead_minutes"] == 60
        assert data["routing"]["status"] == "OK"

    def test_lead_preserved_on_route(self):
        bundle = _bundle("P_NORMAL", 140.0)
        route = PIPELINE.route(bundle, 60, NW, SE, "flood_aware")
        assert route.lead_minutes == 60
        assert route.routing.lead_minutes == 60

    def test_no_safe_route_preserved(self):
        depth = np.full((134, 134), 0.7, dtype=np.float64)
        impacts = tuple(
            compute_road_impact(seg, depth, "P_TEST", 60, "2026-08-22T13:00:00+00:00")
            for seg in NETWORK.segments
        )
        road_projection = RoadImpactProjection(
            config_id="P_TEST",
            initialization_time=datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc),
            valid_time=datetime(2026, 8, 22, 13, 0, tzinfo=timezone.utc),
            lead_minutes=60,
            road_impacts=impacts,
            road_metrics={"total_segments": NETWORK.n_segments},
            projection_fingerprint="proj-fp",
            policy_version=POLICY.policy_id,
            policy_fingerprint=POLICY.fingerprint,
            network_fingerprint=NETWORK.fingerprint,
            road_projection_fingerprint="road-fp",
            labels=("PERSISTENCE_PROJECTION",),
        )
        fake_bundle = SimpleNamespace(
            config=SimpleNamespace(config_id="P_TEST", labels=("PERSISTENCE_PROJECTION",)),
            road_projections={60: road_projection},
        )
        route = PIPELINE.route(fake_bundle, 60, NW, SE, "flood_aware")
        assert route.routing.status == "NO_SAFE_ROUTE"

    def test_no_silent_fallback(self):
        depth = np.full((134, 134), 0.7, dtype=np.float64)
        impacts = {seg.road_id: compute_road_impact(seg, depth, "P_TEST", 60, "t60") for seg in NETWORK.segments}
        result = compute_route(NETWORK, impacts, NW, SE, "flood_aware", "P_TEST", 60, "t60")
        assert result.status == "NO_SAFE_ROUTE"
        assert result.flood_aware is None


# ---------------------------------------------------------------------------
# API tests
# ---------------------------------------------------------------------------

class TestM9API:
    def _current_fixed_observation(self, rate_mmh: float = 140.0) -> RainfallObservation:
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        return SyntheticRainfallProvider(base_rate_mmh=rate_mmh, seed=123).fetch_observation(now)

    def test_status_lists_valid_leads(self):
        client = TestClient(app)
        r = client.get("/api/v1/projections/nowcast/status")
        assert r.status_code == 200
        data = r.json()
        assert data["available_leads"] == [0, 15, 30, 45, 60]
        assert data["projection_version"] == M9_MODEL_VERSION

    def test_valid_lead_projection_frame(self):
        client = TestClient(app)
        obs = self._current_fixed_observation()
        provider = rainfall_api.get_active_provider()
        projection_api.PIPELINE.cache.clear()
        with mock.patch.object(provider, "fetch_latest", return_value=obs):
            r = client.get("/api/v1/projections/nowcast/P_NORMAL/frame?lead=60")
        assert r.status_code == 200
        data = r.json()
        assert data["lead_minutes"] == 60
        assert data["projection"]["observation_fingerprint"] == obs.fingerprint()
        assert "PERSISTENCE_PROJECTION" in data["labels"]

    def test_invalid_lead(self):
        client = TestClient(app)
        r = client.get("/api/v1/projections/nowcast/P_NORMAL/frame?lead=7")
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "INVALID_LEAD"

    def test_missing_observation(self):
        client = TestClient(app)
        provider = rainfall_api.get_active_provider()
        with mock.patch.object(provider, "fetch_latest", return_value=None):
            r = client.get("/api/v1/projections/nowcast/P_NORMAL/frame?lead=15")
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "PROJECTION_UNAVAILABLE"

    def test_cached_projection(self):
        client = TestClient(app)
        obs = self._current_fixed_observation()
        provider = rainfall_api.get_active_provider()
        projection_api.PIPELINE.cache.clear()
        with mock.patch.object(provider, "fetch_latest", return_value=obs):
            first = client.get("/api/v1/projections/nowcast/P_NORMAL/frame?lead=60")
            second = client.get("/api/v1/projections/nowcast/P_NORMAL/frame?lead=60")
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["cache_hit"] is False
        assert second.json()["cache_hit"] is True

    def test_provenance_present(self):
        client = TestClient(app)
        obs = self._current_fixed_observation()
        provider = rainfall_api.get_active_provider()
        with mock.patch.object(provider, "fetch_latest", return_value=obs):
            r = client.get("/api/v1/projections/nowcast/P_NORMAL/flood?lead=45")
        assert r.status_code == 200
        data = r.json()
        for key in (
            "observation_fingerprint",
            "nowcast_fingerprint",
            "projection_fingerprint",
            "configuration_fingerprint",
            "model_version",
            "engine_version",
        ):
            assert key in data


# ---------------------------------------------------------------------------
# Dashboard / HTML integration tests
# ---------------------------------------------------------------------------

class TestM9Dashboard:
    def test_dashboard_contains_projection_controls(self):
        client = TestClient(app)
        r = client.get("/")
        assert r.status_code == 200
        assert 'id="projection-config"' in r.text
        assert 'id="view-mode"' in r.text

    def test_dashboard_contains_required_projection_labels(self):
        client = TestClient(app)
        html = client.get("/").text
        assert "PERSISTENCE PROJECTION" in html
        assert "NOT_REAL_TIME" in html
        assert "NOT_VALIDATED FORECAST" in html

    def test_dashboard_preserves_m7_content(self):
        client = TestClient(app)
        html = client.get("/").text
        assert "Rainfall + Nowcast" in html
        assert "Route around it" in html
        assert "What changed? S3 → S4" in html
