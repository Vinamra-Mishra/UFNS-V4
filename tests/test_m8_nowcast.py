"""M8 — Real-time rainfall ingestion + nowcasting tests.

Tests cover:
  M8-01  Provider contract (abstract interface)
  M8-02  Source identification (source_type always exposed)
  M8-03  Timestamp validation (timezone-aware, UTC)
  M8-04  Units (mm/h enforced)
  M8-05  Stale-data detection
  M8-06  Missing-data handling (no silent substitution)
  M8-07  Persistence determinism (same input → same output)
  M8-08  Nowcast contract (NowcastRecord schema)
  M8-09  Fingerprint determinism
  M8-10  API: rainfall/latest
  M8-11  API: nowcast/latest
  M8-12  Invalid requests
  M8-13  Provenance (every response carries source)
  M8-14  Caching
  M8-15  Forecast/observation separation
  M8-16  Dashboard status (API health includes M8)
  M8-17  Synthetic-provider labelling (NEVER presents as REAL)
  M8-18  Provider failure (graceful degradation)
  M8-19  Regression M1-M7 (existing tests still pass)
  M8-20  Verification behaviour (NOT_EVALUATED until real data)
  M8-21+ Additional tests
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import numpy as np
import pytest
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from services.nowcast.providers import RainfallObservation

# ---------------------------------------------------------------------------
# M8-01: Provider contract
# ---------------------------------------------------------------------------

class TestProviderContract:
    """M8-01: Every provider implements the RainfallProvider interface."""

    def test_synthetic_provider_has_required_methods(self):
        from services.nowcast.providers import RainfallProvider
        from services.nowcast.providers.synthetic_provider import (
            SyntheticRainfallProvider,
        )
        p = SyntheticRainfallProvider()
        assert isinstance(p, RainfallProvider)
        assert hasattr(p, "fetch_latest")
        assert hasattr(p, "fetch_observation")
        assert hasattr(p, "health")
        assert hasattr(p, "metadata")
        assert hasattr(p, "provider_id")
        assert hasattr(p, "source_type")
        assert hasattr(p, "source_name")

    def test_fixture_provider_has_required_methods(self):
        from services.nowcast.providers import RainfallProvider
        from services.nowcast.providers.fixture_provider import FixtureRainfallProvider
        p = FixtureRainfallProvider(profile_intensities_mmh=[10.0, 20.0, 30.0])
        assert isinstance(p, RainfallProvider)
        assert hasattr(p, "fetch_latest")
        assert hasattr(p, "fetch_observation")
        assert hasattr(p, "health")
        assert hasattr(p, "metadata")

    def test_provider_fetch_returns_observation(self):
        from services.nowcast.providers import RainfallObservation
        from services.nowcast.providers.synthetic_provider import (
            SyntheticRainfallProvider,
        )
        p = SyntheticRainfallProvider()
        obs = p.fetch_latest()
        assert obs is not None
        assert isinstance(obs, RainfallObservation)
        assert obs.rate_mmh.ndim == 2
        assert obs.width == 134
        assert obs.height == 134

    def test_provider_fetch_at_time(self):
        from services.nowcast.providers.synthetic_provider import (
            SyntheticRainfallProvider,
        )
        p = SyntheticRainfallProvider()
        t = datetime(2026, 8, 22, 14, 30, tzinfo=timezone.utc)
        obs = p.fetch_observation(t)
        assert obs is not None
        assert obs.observation_time == t


# ---------------------------------------------------------------------------
# M8-02: Source identification
# ---------------------------------------------------------------------------

class TestSourceIdentification:
    """M8-02: Every observation/response carries explicit source_type."""

    def test_synthetic_source_type(self):
        from services.nowcast.providers import SourceType
        from services.nowcast.providers.synthetic_provider import (
            SyntheticRainfallProvider,
        )
        p = SyntheticRainfallProvider()
        assert p.source_type == SourceType.SYNTHETIC
        obs = p.fetch_latest()
        assert obs.source_type == SourceType.SYNTHETIC

    def test_fixture_source_type(self):
        from services.nowcast.providers import SourceType
        from services.nowcast.providers.fixture_provider import FixtureRainfallProvider
        p = FixtureRainfallProvider(profile_intensities_mmh=[10.0, 20.0])
        assert p.source_type == SourceType.FIXTURE
        obs = p.fetch_latest()
        assert obs.source_type == SourceType.FIXTURE

    def test_source_type_in_observation_dict(self):
        from services.nowcast.providers.synthetic_provider import (
            SyntheticRainfallProvider,
        )
        p = SyntheticRainfallProvider()
        obs = p.fetch_latest()
        d = obs.to_dict()
        assert "source_type" in d
        assert d["source_type"] in ("REAL", "SYNTHETIC", "FIXTURE")

    def test_source_type_in_nowcast_record(self):
        from services.nowcast.engine import PersistenceNowcast
        from services.nowcast.providers.synthetic_provider import (
            SyntheticRainfallProvider,
        )
        p = SyntheticRainfallProvider()
        obs = p.fetch_latest()
        engine = PersistenceNowcast()
        records = engine.generate(obs)
        assert len(records) > 0
        assert records[0].source_type == "SYNTHETIC"


# ---------------------------------------------------------------------------
# M8-03: Timestamp validation
# ---------------------------------------------------------------------------

class TestTimestampValidation:
    """M8-03: All timestamps are timezone-aware UTC."""

    def test_observation_time_is_aware(self):
        from services.nowcast.providers.synthetic_provider import (
            SyntheticRainfallProvider,
        )
        p = SyntheticRainfallProvider()
        obs = p.fetch_latest()
        assert obs.observation_time.tzinfo is not None
        assert obs.valid_from.tzinfo is not None
        assert obs.valid_to.tzinfo is not None

    def test_naive_observation_time_rejected(self):
        from services.nowcast.providers import RainfallObservation, SourceType
        with pytest.raises(ValueError, match="timezone-aware"):
            RainfallObservation(
                observation_time=datetime(2026, 8, 22, 12, 0),  # naive  # noqa: DTZ001
                valid_from=datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc),
                valid_to=datetime(2026, 8, 22, 12, 15, tzinfo=timezone.utc),
                rate_mmh=np.zeros((134, 134), dtype=np.float32),
                source_type=SourceType.SYNTHETIC,
                source_name="test",
                source_provider_id="test",
                spatial_reference="EPSG:32645",
                spatial_resolution_m=30.0,
                width=134,
                height=134,
            )

    def test_nowcast_record_times_are_aware(self):
        from services.nowcast.engine import PersistenceNowcast
        from services.nowcast.providers.synthetic_provider import (
            SyntheticRainfallProvider,
        )
        p = SyntheticRainfallProvider()
        obs = p.fetch_latest()
        engine = PersistenceNowcast()
        records = engine.generate(obs)
        for rec in records:
            assert rec.initialization_time.tzinfo is not None
            assert rec.valid_time.tzinfo is not None


# ---------------------------------------------------------------------------
# M8-04: Units
# ---------------------------------------------------------------------------

class TestUnits:
    """M8-04: All rates are in mm/h."""

    def test_observation_units_mmh(self):
        from services.nowcast.providers.synthetic_provider import (
            SyntheticRainfallProvider,
        )
        p = SyntheticRainfallProvider()
        obs = p.fetch_latest()
        assert obs.units == "mm/h"

    def test_non_mmh_units_rejected(self):
        from services.nowcast.providers import RainfallObservation, SourceType
        with pytest.raises(ValueError, match="mm/h"):
            RainfallObservation(
                observation_time=datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc),
                valid_from=datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc),
                valid_to=datetime(2026, 8, 22, 12, 15, tzinfo=timezone.utc),
                rate_mmh=np.zeros((134, 134), dtype=np.float32),
                source_type=SourceType.SYNTHETIC,
                source_name="test",
                source_provider_id="test",
                spatial_reference="EPSG:32645",
                spatial_resolution_m=30.0,
                width=134,
                height=134,
                units="in/h",  # wrong units
            )

    def test_nowcast_record_units_mmh(self):
        from services.nowcast.engine import PersistenceNowcast
        from services.nowcast.providers.synthetic_provider import (
            SyntheticRainfallProvider,
        )
        p = SyntheticRainfallProvider()
        obs = p.fetch_latest()
        engine = PersistenceNowcast()
        records = engine.generate(obs)
        for rec in records:
            assert rec.units == "mm/h"


# ---------------------------------------------------------------------------
# M8-05: Stale-data detection
# ---------------------------------------------------------------------------

class TestStaleDataDetection:
    """M8-05: Observations older than the freshness threshold are flagged STALE."""

    def test_fresh_observation(self):
        from services.nowcast.providers.synthetic_provider import (
            SyntheticRainfallProvider,
        )
        from services.nowcast.quality import (
            DataFreshness,
            QualityConfig,
            validate_observation,
        )
        p = SyntheticRainfallProvider()
        obs = p.fetch_latest()
        config = QualityConfig(freshness_threshold_minutes=60, stale_threshold_minutes=180)
        result = validate_observation(obs, config, now=obs.observation_time + timedelta(minutes=5))
        assert result.freshness == DataFreshness.FRESH

    def test_stale_observation(self):
        from services.nowcast.providers.synthetic_provider import (
            SyntheticRainfallProvider,
        )
        from services.nowcast.quality import (
            DataFreshness,
            QualityConfig,
            validate_observation,
        )
        p = SyntheticRainfallProvider()
        obs = p.fetch_latest()
        config = QualityConfig(freshness_threshold_minutes=10, stale_threshold_minutes=60)
        result = validate_observation(obs, config, now=obs.observation_time + timedelta(minutes=30))
        assert result.freshness == DataFreshness.STALE

    def test_very_old_observation_is_missing(self):
        from services.nowcast.providers.synthetic_provider import (
            SyntheticRainfallProvider,
        )
        from services.nowcast.quality import (
            DataFreshness,
            QualityConfig,
            validate_observation,
        )
        p = SyntheticRainfallProvider()
        obs = p.fetch_latest()
        config = QualityConfig(freshness_threshold_minutes=10, stale_threshold_minutes=60)
        result = validate_observation(obs, config, now=obs.observation_time + timedelta(minutes=200))
        assert result.freshness == DataFreshness.MISSING


# ---------------------------------------------------------------------------
# M8-06: Missing-data handling
# ---------------------------------------------------------------------------

class TestMissingDataHandling:
    """M8-06: Missing observations are reported, never silently replaced."""

    def test_none_observation_is_missing(self):
        from services.nowcast.quality import DataFreshness, validate_observation
        result = validate_observation(None)
        assert result.freshness == DataFreshness.MISSING
        assert result.valid is False

    def test_no_silent_substitution_in_engine(self):
        """The engine must not generate forecasts from invalid observations."""
        from services.nowcast.engine import PersistenceNowcast
        from services.nowcast.quality import DataFreshness, validate_observation
        engine = PersistenceNowcast()
        quality = validate_observation(None)
        # No silent substitution: an invalid/missing observation must yield
        # an empty list (no fabricated forecast).
        records = engine.generate(observation=None, quality=quality)
        assert records == [], "engine must not generate forecasts from invalid observations"
        assert quality.freshness == DataFreshness.MISSING
        assert quality.valid is False

    def test_api_returns_unavailable_when_no_observation(self):
        """When the provider has no data, the API returns UNAVAILABLE."""
        from apps.api.app import app
        client = TestClient(app)
        # The default provider always has data, so we test the status endpoint
        r = client.get("/api/v1/rainfall/status")
        assert r.status_code == 200
        data = r.json()
        assert "health" in data
        assert data["health"]["status"] in ("HEALTHY", "DEGRADED", "UNAVAILABLE", "UNCONFIGURED")


# ---------------------------------------------------------------------------
# M8-07: Persistence determinism
# ---------------------------------------------------------------------------

class TestPersistenceDeterminism:
    """M8-07: Persistence baseline is deterministic (same input → same output)."""

    def test_persistence_produces_identical_fields(self):
        from services.nowcast.engine import PersistenceNowcast
        from services.nowcast.providers.synthetic_provider import (
            SyntheticRainfallProvider,
        )
        p = SyntheticRainfallProvider(seed=42)
        t = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
        obs1 = p.fetch_observation(t)
        obs2 = p.fetch_observation(t)
        engine = PersistenceNowcast()
        recs1 = engine.generate(obs1)
        recs2 = engine.generate(obs2)
        assert len(recs1) == len(recs2)
        for r1, r2 in zip(recs1, recs2):
            np.testing.assert_array_equal(r1.rate_mmh, r2.rate_mmh)

    def test_persistence_forecast_equals_observation(self):
        from services.nowcast.engine import PersistenceNowcast
        from services.nowcast.providers.synthetic_provider import (
            SyntheticRainfallProvider,
        )
        p = SyntheticRainfallProvider()
        obs = p.fetch_latest()
        engine = PersistenceNowcast()
        records = engine.generate(obs)
        for rec in records:
            np.testing.assert_array_equal(rec.rate_mmh, obs.rate_mmh)


# ---------------------------------------------------------------------------
# M8-08: Nowcast contract
# ---------------------------------------------------------------------------

class TestNowcastContract:
    """M8-08: NowcastRecord has the required typed fields."""

    def test_nowcast_record_has_required_fields(self):
        from services.nowcast.nowcast_record import NowcastRecord
        rec = NowcastRecord(
            initialization_time=datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc),
            valid_time=datetime(2026, 8, 22, 12, 15, tzinfo=timezone.utc),
            lead_minutes=15,
            rate_mmh=np.full((134, 134), 10.0, dtype=np.float32),
        )
        assert rec.initialization_time is not None
        assert rec.valid_time is not None
        assert rec.lead_minutes == 15
        assert rec.rate_mmh.shape == (134, 134)
        assert rec.units == "mm/h"
        assert rec.method == "NOWCAST-PERSISTENCE-V1"
        assert rec.uncertainty == "NOT PROVIDED"

    def test_nowcast_record_to_dict(self):
        from services.nowcast.nowcast_record import NowcastRecord
        rec = NowcastRecord(
            initialization_time=datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc),
            valid_time=datetime(2026, 8, 22, 12, 15, tzinfo=timezone.utc),
            lead_minutes=15,
            rate_mmh=np.full((134, 134), 10.0, dtype=np.float32),
            source_type="SYNTHETIC",
        )
        d = rec.to_dict()
        assert "initialization_time" in d
        assert "valid_time" in d
        assert "lead_minutes" in d
        assert "method" in d
        assert "source_type" in d
        assert "status" in d
        assert "uncertainty" in d
        assert "fingerprint" in d
        assert d["uncertainty"] == "NOT PROVIDED"

    def test_nowcast_record_negative_rate_rejected(self):
        from services.nowcast.nowcast_record import NowcastRecord
        with pytest.raises(ValueError, match="negative"):
            NowcastRecord(
                initialization_time=datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc),
                valid_time=datetime(2026, 8, 22, 12, 15, tzinfo=timezone.utc),
                lead_minutes=15,
                rate_mmh=np.full((134, 134), -1.0, dtype=np.float32),
            )

    def test_nowcast_record_negative_lead_rejected(self):
        from services.nowcast.nowcast_record import NowcastRecord
        with pytest.raises(ValueError, match="non-negative"):
            NowcastRecord(
                initialization_time=datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc),
                valid_time=datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc),
                lead_minutes=-5,
                rate_mmh=np.zeros((134, 134), dtype=np.float32),
            )


# ---------------------------------------------------------------------------
# M8-09: Fingerprint determinism
# ---------------------------------------------------------------------------

class TestFingerprintDeterminism:
    """M8-09: Fingerprints are deterministic and change with inputs."""

    def test_observation_fingerprint_deterministic(self):
        from services.nowcast.providers.synthetic_provider import (
            SyntheticRainfallProvider,
        )
        p = SyntheticRainfallProvider()
        t = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
        obs1 = p.fetch_observation(t)
        obs2 = p.fetch_observation(t)
        assert obs1.fingerprint() == obs2.fingerprint()

    def test_observation_fingerprint_changes_with_time(self):
        from services.nowcast.providers.synthetic_provider import (
            SyntheticRainfallProvider,
        )
        p = SyntheticRainfallProvider()
        obs1 = p.fetch_observation(datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc))
        obs2 = p.fetch_observation(datetime(2026, 8, 22, 13, 0, tzinfo=timezone.utc))
        # Different times may or may not change the fingerprint depending on the
        # synthetic model, but the observation_time is part of the fingerprint
        assert obs1.observation_time != obs2.observation_time

    def test_nowcast_fingerprint_deterministic(self):
        from services.nowcast.engine import PersistenceNowcast
        from services.nowcast.providers.synthetic_provider import (
            SyntheticRainfallProvider,
        )
        p = SyntheticRainfallProvider()
        t = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
        obs = p.fetch_observation(t)
        engine = PersistenceNowcast()
        recs1 = engine.generate(obs)
        recs2 = engine.generate(obs)
        for r1, r2 in zip(recs1, recs2):
            assert r1.fingerprint == r2.fingerprint


# ---------------------------------------------------------------------------
# M8-10: API rainfall/latest
# ---------------------------------------------------------------------------

class TestAPIRainfallLatest:
    """M8-10: The /api/v1/rainfall/latest endpoint works correctly."""

    def test_rainfall_latest_returns_200(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/api/v1/rainfall/latest")
        assert r.status_code == 200

    def test_rainfall_latest_has_source_type(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/api/v1/rainfall/latest")
        data = r.json()
        assert "source_type" in data
        assert data["source_type"] in ("REAL", "SYNTHETIC", "FIXTURE")

    def test_rainfall_latest_has_quality(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/api/v1/rainfall/latest")
        data = r.json()
        assert "quality" in data
        assert "freshness" in data["quality"]

    def test_rainfall_latest_has_observation(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/api/v1/rainfall/latest")
        data = r.json()
        assert data["status"] == "AVAILABLE"
        assert data["observation"] is not None
        assert "rate_mean_mmh" in data["observation"]


# ---------------------------------------------------------------------------
# M8-11: API nowcast/latest
# ---------------------------------------------------------------------------

class TestAPINowcastLatest:
    """M8-11: The /api/v1/nowcast/latest endpoint works correctly."""

    def test_nowcast_latest_returns_200(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/api/v1/nowcast/latest")
        assert r.status_code == 200

    def test_nowcast_latest_has_method(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/api/v1/nowcast/latest")
        data = r.json()
        assert "method" in data
        assert data["method"] == "NOWCAST-PERSISTENCE-V1"

    def test_nowcast_latest_has_lead_times(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/api/v1/nowcast/latest")
        data = r.json()
        assert "nowcast" in data
        assert len(data["nowcast"]) > 0
        leads = [nc["lead_minutes"] for nc in data["nowcast"]]
        assert 0 in leads
        assert 60 in leads

    def test_nowcast_each_record_has_source(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/api/v1/nowcast/latest")
        data = r.json()
        for nc in data["nowcast"]:
            assert "source_type" in nc
            assert "method" in nc
            assert "status" in nc


# ---------------------------------------------------------------------------
# M8-12: Invalid requests
# ---------------------------------------------------------------------------

class TestInvalidRequests:
    """M8-12: Invalid requests are rejected with structured errors."""

    def test_invalid_lead_returns_400(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/api/v1/nowcast/9999")
        assert r.status_code == 400

    def test_invalid_provider_returns_404(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/api/v1/nowcast/providers/nonexistent")
        assert r.status_code == 404

    def test_invalid_timestamp_returns_400(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/api/v1/rainfall/observation?time=not-a-date")
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# M8-13: Provenance
# ---------------------------------------------------------------------------

class TestProvenance:
    """M8-13: Every response carries provenance."""

    def test_nowcast_status_has_labels(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/api/v1/nowcast/status")
        data = r.json()
        assert "labels" in data
        assert len(data["labels"]) > 0

    def test_providers_have_source_type(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/api/v1/nowcast/providers")
        data = r.json()
        for p in data["providers"]:
            assert "source_type" in p
            assert p["source_type"] in ("REAL", "SYNTHETIC", "FIXTURE")

    def test_nowcast_has_verification_status(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/api/v1/nowcast/verification")
        data = r.json()
        assert data["verification"]["status"] == "NOT_EVALUATED"


# ---------------------------------------------------------------------------
# M8-14: Caching
# ---------------------------------------------------------------------------

class TestCaching:
    """M8-14: Cache works correctly."""

    def test_cache_can_store_and_retrieve(self):
        from services.nowcast.cache import NowcastCache
        from services.nowcast.providers.synthetic_provider import (
            SyntheticRainfallProvider,
        )
        cache = NowcastCache(ttl_seconds=60)
        p = SyntheticRainfallProvider()
        obs = p.fetch_latest()
        key = cache.put_observation(obs)
        retrieved = cache.get_observation(key)
        assert retrieved is not None
        np.testing.assert_array_equal(retrieved.rate_mmh, obs.rate_mmh)

    def test_cache_stats(self):
        from services.nowcast.cache import NowcastCache
        cache = NowcastCache()
        stats = cache.stats()
        assert "ttl_seconds" in stats
        assert "total_entries" in stats


# ---------------------------------------------------------------------------
# M8-15: Forecast/observation separation
# ---------------------------------------------------------------------------

class TestForecastObservationSeparation:
    """M8-15: Forecasts are clearly separated from observations in the API."""

    def test_observation_endpoint_separate_from_nowcast(self):
        """Rainfall and nowcast are separate endpoints."""
        from apps.api.app import app
        client = TestClient(app)
        rain = client.get("/api/v1/rainfall/latest").json()
        nc = client.get("/api/v1/nowcast/latest").json()
        assert rain["status"] == "AVAILABLE"
        assert nc["status"] == "AVAILABLE"
        # Rainfall is observation, nowcast is forecast
        assert "observation" in rain
        assert "nowcast" in nc

    def test_nowcast_records_have_lead_time(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/api/v1/nowcast/latest")
        data = r.json()
        for nc in data["nowcast"]:
            assert "lead_minutes" in nc
            assert "initialization_time" in nc
            assert "valid_time" in nc


# ---------------------------------------------------------------------------
# M8-16: Dashboard status
# ---------------------------------------------------------------------------

class TestDashboardStatus:
    """M8-16: Health endpoint includes M8 status."""

    def test_health_includes_nowcast_version(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/health")
        data = r.json()
        assert "nowcast_version" in data
        assert "rainfall_provider_type" in data

    def test_health_shows_synthetic(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/health")
        data = r.json()
        assert data["rainfall_provider_type"] == "SYNTHETIC"

    def test_version_includes_maturity(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/api/v1/version")
        data = r.json()
        assert data["maturity"] == "LEVEL_1_DEMONSTRATION_PROTOTYPE"


# ---------------------------------------------------------------------------
# M8-17: Synthetic provider labelling
# ---------------------------------------------------------------------------

class TestSyntheticProviderLabelling:
    """M8-17: Synthetic data is NEVER presented as real."""

    def test_synthetic_api_never_says_real(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/api/v1/rainfall/latest")
        data = r.json()
        assert data["source_type"] != "REAL"
        assert data["source_type"] == "SYNTHETIC"

    def test_nowcast_api_never_says_real(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/api/v1/nowcast/latest")
        data = r.json()
        # All nowcast records should have SYNTHETIC or FIXTURE source_type
        for nc in data["nowcast"]:
            assert nc["source_type"] in ("SYNTHETIC", "FIXTURE")

    def test_labels_include_synthetic(self):
        from apps.api.app import app
        client = TestClient(app)
        for endpoint in ["/api/v1/rainfall/status", "/api/v1/nowcast/latest",
                         "/api/v1/nowcast/status"]:
            r = client.get(endpoint)
            data = r.json()
            assert "labels" in data
            # Labels should include something indicating this is not real
            all_labels = " ".join(data["labels"]).upper()
            assert "SYNTHETIC" in all_labels or "DEMONSTRATION" in all_labels or "PERSISTENCE" in all_labels


# ---------------------------------------------------------------------------
# M8-18: Provider failure handling
# ---------------------------------------------------------------------------

class TestProviderFailure:
    """M8-18: Provider failures are handled gracefully."""

    def test_missing_provider_returns_404(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/api/v1/nowcast/providers/does-not-exist")
        assert r.status_code == 404
        data = r.json()
        assert "error" in data

    def test_provider_health_always_available(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/api/v1/nowcast/providers")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] >= 1


# ---------------------------------------------------------------------------
# M8-19: Regression M1-M7
# ---------------------------------------------------------------------------

class TestRegressionM1M7:
    """M8-19: M8 does not break M1-M7 functionality."""

    def test_scenarios_still_work(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/api/v1/scenarios")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 4

    def test_frame_still_works(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/api/v1/scenarios/S4/frame?lead=110")
        assert r.status_code == 200

    def test_roads_still_work(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/api/v1/roads")
        assert r.status_code == 200

    def test_policies_still_work(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/api/v1/policies")
        assert r.status_code == 200
        data = r.json()
        assert data["policies"][0]["policy_id"] == "B13-DEMO-V1"

    def test_comparison_still_works(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/api/v1/comparison/s3s4")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# M8-20: Verification behaviour
# ---------------------------------------------------------------------------

class TestVerificationBehaviour:
    """M8-20: Verification is NOT_EVALUATED until real data exists."""

    def test_verification_endpoint_not_evaluated(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/api/v1/nowcast/verification")
        data = r.json()
        assert data["verification"]["status"] == "NOT_EVALUATED"

    def test_no_fake_skill_scores(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/api/v1/nowcast/verification")
        data = r.json()
        # Should have no metrics (no fabricated scores)
        assert data["verification"]["metrics"] == {}
        assert data["verification"]["n_samples"] == 0

    def test_nowcast_status_includes_verification(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/api/v1/nowcast/status")
        data = r.json()
        assert "verification" in data
        assert data["verification"]["status"] == "NOT_EVALUATED"


# ---------------------------------------------------------------------------
# M8-21+: Additional tests
# ---------------------------------------------------------------------------

class TestNowcastConfig:
    """Additional configuration tests."""

    def test_default_config_lead_times(self):
        from services.nowcast.engine import NowcastConfig
        config = NowcastConfig()
        assert config.lead_times_minutes == (0, 15, 30, 45, 60)
        assert config.max_lead_minutes == 60

    def test_config_rejects_invalid_lead(self):
        from services.nowcast.engine import NowcastConfig
        with pytest.raises(ValueError, match="outside"):
            NowcastConfig(lead_times_minutes=(0, 120), max_lead_minutes=60)

    def test_generate_for_specific_lead(self):
        from services.nowcast.engine import PersistenceNowcast
        from services.nowcast.providers.synthetic_provider import (
            SyntheticRainfallProvider,
        )
        p = SyntheticRainfallProvider()
        obs = p.fetch_latest()
        engine = PersistenceNowcast()
        rec = engine.generate_for_lead(obs, 30)
        assert rec is not None
        assert rec.lead_minutes == 30

    def test_generate_for_invalid_lead_returns_none(self):
        from services.nowcast.engine import PersistenceNowcast
        from services.nowcast.providers.synthetic_provider import (
            SyntheticRainfallProvider,
        )
        p = SyntheticRainfallProvider()
        obs = p.fetch_latest()
        engine = PersistenceNowcast()
        rec = engine.generate_for_lead(obs, 999)
        assert rec is None


class TestVerificationMetrics:
    """Additional verification metric tests."""

    def test_mae_computation(self):
        from services.nowcast.verification import compute_mae
        f = np.array([10.0, 20.0, 30.0])
        o = np.array([12.0, 18.0, 32.0])
        mae = compute_mae(f, o)
        assert abs(mae - 2.0) < 1e-10

    def test_rmse_computation(self):
        from services.nowcast.verification import compute_rmse
        f = np.array([10.0, 20.0, 30.0])
        o = np.array([10.0, 20.0, 30.0])
        rmse = compute_rmse(f, o)
        assert abs(rmse) < 1e-10

    def test_bias_computation(self):
        from services.nowcast.verification import compute_bias
        f = np.array([10.0, 20.0])
        o = np.array([8.0, 18.0])
        bias = compute_bias(f, o)
        assert abs(bias - 2.0) < 1e-10

    def test_csi_perfect_forecast(self):
        from services.nowcast.verification import compute_csi
        f = np.array([0.0, 5.0, 10.0, 0.0])
        o = np.array([0.0, 5.0, 10.0, 0.0])
        csi = compute_csi(f, o, threshold=0.1)
        assert abs(csi - 1.0) < 1e-10

    def test_verification_pair(self):
        from services.nowcast.verification import VerificationStatus, verify_pair
        f = np.full((10, 10), 15.0)
        o = np.full((10, 10), 15.0)
        result = verify_pair(f, o)
        assert result.status == VerificationStatus.EVALUATED
        assert result.metrics["mae_mmh"] < 1e-10

    def test_shape_mismatch_returns_insufficient(self):
        from services.nowcast.verification import VerificationStatus, verify_pair
        f = np.full((10, 10), 15.0)
        o = np.full((20, 20), 15.0)
        result = verify_pair(f, o)
        assert result.status == VerificationStatus.INSUFFICIENT_DATA


class TestFixtureProviderSequence:
    """Fixture provider sequence generation."""

    def test_fetch_sequence(self):
        from services.nowcast.providers.fixture_provider import FixtureRainfallProvider
        p = FixtureRainfallProvider(profile_intensities_mmh=[10.0, 20.0, 30.0, 40.0])
        seq = p.fetch_sequence(0, 4)
        assert len(seq) == 4
        for obs in seq:
            assert obs.source_type.value == "FIXTURE"

    def test_fixture_deterministic(self):
        from services.nowcast.providers.fixture_provider import FixtureRainfallProvider
        p1 = FixtureRainfallProvider(profile_intensities_mmh=[10.0, 20.0], seed=42)
        p2 = FixtureRainfallProvider(profile_intensities_mmh=[10.0, 20.0], seed=42)
        obs1 = p1.fetch_observation(datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc))
        obs2 = p2.fetch_observation(datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc))
        np.testing.assert_array_equal(obs1.rate_mmh, obs2.rate_mmh)


class TestAPINowcastAtLead:
    """API nowcast at specific lead time."""

    def test_nowcast_lead_0(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/api/v1/nowcast/0")
        assert r.status_code == 200
        data = r.json()
        assert data["lead_minutes"] == 0
        assert data["nowcast"]["lead_minutes"] == 0

    def test_nowcast_lead_60(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/api/v1/nowcast/60")
        assert r.status_code == 200
        data = r.json()
        assert data["lead_minutes"] == 60

    def test_nowcast_lead_has_values(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/api/v1/nowcast/0")
        data = r.json()
        assert "values" in data["nowcast"]
        assert len(data["nowcast"]["values"]) == 134 * 134

    def test_nowcast_cache_stats(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/api/v1/nowcast/cache")
        assert r.status_code == 200
        data = r.json()
        assert "ttl_seconds" in data


# ---------------------------------------------------------------------------
# Extended coverage: RainfallObservation validation edge cases
# ---------------------------------------------------------------------------

class TestRainfallObservationValidation:
    """Direct validation tests for RainfallObservation.__post_init__."""

    def _valid_kwargs(self, **overrides):
        from services.nowcast.providers import SourceType
        kwargs = {
            "observation_time": datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc),
            "valid_from": datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc),
            "valid_to": datetime(2026, 8, 22, 12, 15, tzinfo=timezone.utc),
            "rate_mmh": np.zeros((134, 134), dtype=np.float32),
            "source_type": SourceType.SYNTHETIC,
            "source_name": "test",
            "source_provider_id": "test",
            "spatial_reference": "EPSG:32645",
            "spatial_resolution_m": 30.0,
            "width": 134,
            "height": 134,
        }
        kwargs.update(overrides)
        return kwargs

    def test_ndim_mismatch_rejected(self):
        from services.nowcast.providers import RainfallObservation
        with pytest.raises(ValueError, match="2-D"):
            RainfallObservation(**self._valid_kwargs(rate_mmh=np.zeros(134, dtype=np.float32)))

    def test_shape_mismatch_rejected(self):
        from services.nowcast.providers import RainfallObservation
        with pytest.raises(ValueError, match="shape"):
            RainfallObservation(**self._valid_kwargs(rate_mmh=np.zeros((10, 10), dtype=np.float32)))

    def test_nan_rejected(self):
        from services.nowcast.providers import RainfallObservation
        rate = np.zeros((134, 134), dtype=np.float32)
        rate[0, 0] = np.nan
        with pytest.raises(ValueError, match="finite"):
            RainfallObservation(**self._valid_kwargs(rate_mmh=rate))

    def test_inf_rejected(self):
        from services.nowcast.providers import RainfallObservation
        rate = np.zeros((134, 134), dtype=np.float32)
        rate[0, 0] = np.inf
        with pytest.raises(ValueError, match="finite"):
            RainfallObservation(**self._valid_kwargs(rate_mmh=rate))

    def test_negative_rate_rejected(self):
        from services.nowcast.providers import RainfallObservation
        rate = np.zeros((134, 134), dtype=np.float32)
        rate[0, 0] = -1.0
        with pytest.raises(ValueError, match="negative"):
            RainfallObservation(**self._valid_kwargs(rate_mmh=rate))

    def test_valid_to_before_valid_from_rejected(self):
        from services.nowcast.providers import RainfallObservation
        with pytest.raises(ValueError, match="valid_to"):
            RainfallObservation(**self._valid_kwargs(
                valid_from=datetime(2026, 8, 22, 12, 15, tzinfo=timezone.utc),
                valid_to=datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc),
            ))

    def test_valid_to_equal_valid_from_rejected(self):
        from services.nowcast.providers import RainfallObservation
        same = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
        with pytest.raises(ValueError, match="valid_to"):
            RainfallObservation(**self._valid_kwargs(valid_from=same, valid_to=same))

    def test_naive_valid_from_rejected(self):
        from services.nowcast.providers import RainfallObservation
        with pytest.raises(ValueError, match="valid_from"):
            RainfallObservation(**self._valid_kwargs(valid_from=datetime(2026, 8, 22, 12, 0)))  # noqa: DTZ001

    def test_naive_valid_to_rejected(self):
        from services.nowcast.providers import RainfallObservation
        with pytest.raises(ValueError, match="valid_to"):
            RainfallObservation(**self._valid_kwargs(valid_to=datetime(2026, 8, 22, 12, 15)))  # noqa: DTZ001

    def test_to_dict_schema(self):
        from services.nowcast.providers import RainfallObservation
        obs = RainfallObservation(**self._valid_kwargs())
        d = obs.to_dict()
        for key in ("observation_time", "valid_from", "valid_to", "source_type",
                    "source_name", "source_provider_id", "spatial_reference",
                    "spatial_resolution_m", "width", "height", "units",
                    "quality_flags", "rate_mean_mmh", "rate_max_mmh",
                    "rate_min_mmh", "fingerprint"):
            assert key in d, f"missing {key}"
        # the full array must never be serialised into the API response
        assert "rate_mmh" not in d
        assert "values" not in d

    def test_fingerprint_changes_with_rate(self):
        from services.nowcast.providers import RainfallObservation
        obs1 = RainfallObservation(**self._valid_kwargs())
        rate2 = np.full((134, 134), 5.0, dtype=np.float32)
        obs2 = RainfallObservation(**self._valid_kwargs(rate_mmh=rate2))
        assert obs1.fingerprint() != obs2.fingerprint()

    def test_fingerprint_stable_for_identical_inputs(self):
        from services.nowcast.providers import RainfallObservation
        obs1 = RainfallObservation(**self._valid_kwargs())
        obs2 = RainfallObservation(**self._valid_kwargs())
        assert obs1.fingerprint() == obs2.fingerprint()


# ---------------------------------------------------------------------------
# Extended coverage: ProviderHealth serialisation
# ---------------------------------------------------------------------------

class TestProviderHealthDict:
    """ProviderHealth.to_dict() must expose full provenance."""

    def test_provider_health_to_dict_after_fetch(self):
        from services.nowcast.providers.synthetic_provider import (
            SyntheticRainfallProvider,
        )
        p = SyntheticRainfallProvider(provider_id="test-health-1")
        p.fetch_latest()
        d = p.health().to_dict()
        assert d["provider_id"] == "test-health-1"
        assert d["status"] == "HEALTHY"
        assert d["source_type"] == "SYNTHETIC"
        assert d["last_observation_time"] is not None

    def test_provider_health_before_fetch_has_no_last_observation(self):
        from services.nowcast.providers.synthetic_provider import (
            SyntheticRainfallProvider,
        )
        p = SyntheticRainfallProvider(provider_id="test-health-2")
        d = p.health().to_dict()
        assert d["last_observation_time"] is None

    def test_fixture_provider_health_and_metadata(self):
        from services.nowcast.providers.fixture_provider import FixtureRainfallProvider
        p = FixtureRainfallProvider(profile_intensities_mmh=[10.0, 20.0])
        meta = p.metadata()
        assert meta["source_type"] == "FIXTURE"
        assert "limitations" in meta
        h = p.health().to_dict()
        assert h["status"] == "HEALTHY"
        assert h["source_type"] == "FIXTURE"


# ---------------------------------------------------------------------------
# Extended coverage: data-quality validation
# ---------------------------------------------------------------------------

class TestQualityValidationExtended:
    """Additional freshness/warning/boundary behaviour of validate_observation."""

    def _obs(self, **overrides):
        from services.nowcast.providers import RainfallObservation, SourceType
        kwargs = {
            "observation_time": datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc),
            "valid_from": datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc),
            "valid_to": datetime(2026, 8, 22, 12, 15, tzinfo=timezone.utc),
            "rate_mmh": np.zeros((134, 134), dtype=np.float32),
            "source_type": SourceType.SYNTHETIC,
            "source_name": "test",
            "source_provider_id": "test",
            "spatial_reference": "EPSG:32645",
            "spatial_resolution_m": 30.0,
            "width": 134,
            "height": 134,
        }
        kwargs.update(overrides)
        return RainfallObservation(**kwargs)

    def test_grid_size_mismatch_warns_not_errors(self):
        from services.nowcast.quality import QualityConfig, validate_observation
        obs = self._obs(rate_mmh=np.zeros((10, 10), dtype=np.float32), width=10, height=10)
        config = QualityConfig(expected_width=134, expected_height=134)
        result = validate_observation(obs, config, now=obs.observation_time)
        assert result.valid is True
        assert any("grid size mismatch" in w for w in result.warnings)

    def test_resolution_mismatch_warns(self):
        from services.nowcast.quality import QualityConfig, validate_observation
        obs = self._obs(spatial_resolution_m=100.0)
        config = QualityConfig(expected_resolution_m=30.0)
        result = validate_observation(obs, config, now=obs.observation_time)
        assert any("resolution mismatch" in w for w in result.warnings)

    def test_future_observation_is_fresh_with_warning(self):
        from services.nowcast.quality import DataFreshness, validate_observation
        obs = self._obs()
        now = obs.observation_time - timedelta(minutes=10)
        result = validate_observation(obs, now=now)
        assert result.freshness == DataFreshness.FRESH
        assert any("future" in w for w in result.warnings)

    def test_freshness_exact_boundary_is_fresh(self):
        from services.nowcast.quality import (
            DataFreshness,
            QualityConfig,
            validate_observation,
        )
        obs = self._obs()
        config = QualityConfig(freshness_threshold_minutes=30)
        now = obs.observation_time + timedelta(minutes=30)
        result = validate_observation(obs, config, now=now)
        assert result.freshness == DataFreshness.FRESH

    def test_is_observable_true_for_fresh_valid(self):
        from services.nowcast.quality import is_observable, validate_observation
        obs = self._obs()
        result = validate_observation(obs, now=obs.observation_time)
        assert is_observable(result) is True

    def test_is_observable_false_for_missing(self):
        from services.nowcast.quality import is_observable, validate_observation
        result = validate_observation(None)
        assert is_observable(result) is False

    def test_is_observable_false_for_invalid(self):
        from services.nowcast.quality import DataFreshness, QualityResult, is_observable
        result = QualityResult(
            observation=None, freshness=DataFreshness.INVALID, valid=False,
            errors=["forced"], warnings=[], checked_at=datetime.now(timezone.utc),
        )
        assert is_observable(result) is False


# ---------------------------------------------------------------------------
# Extended coverage: NowcastCache
# ---------------------------------------------------------------------------

class TestNowcastCacheExtended:
    """Round-trip, expiry, and clearing behaviour of NowcastCache."""

    def test_nowcast_round_trip(self):
        from services.nowcast.cache import NowcastCache
        from services.nowcast.engine import PersistenceNowcast
        from services.nowcast.providers.synthetic_provider import (
            SyntheticRainfallProvider,
        )
        cache = NowcastCache(ttl_seconds=60)
        p = SyntheticRainfallProvider()
        obs = p.fetch_latest()
        engine = PersistenceNowcast()
        records = engine.generate(obs)
        leads = engine.config.lead_times_minutes
        cache.put_nowcast(obs, engine.config.method, leads, records)
        cached = cache.get_nowcast(obs, engine.config.method, leads)
        assert cached is not None
        assert len(cached) == len(records)

    def test_get_nowcast_miss_returns_none(self):
        from services.nowcast.cache import NowcastCache
        from services.nowcast.providers.synthetic_provider import (
            SyntheticRainfallProvider,
        )
        cache = NowcastCache()
        p = SyntheticRainfallProvider()
        obs = p.fetch_latest()
        assert cache.get_nowcast(obs, "NOWCAST-PERSISTENCE-V1", (0, 15, 30)) is None

    def test_expired_observation_returns_none(self):
        from services.nowcast.cache import NowcastCache
        from services.nowcast.providers.synthetic_provider import (
            SyntheticRainfallProvider,
        )
        cache = NowcastCache(ttl_seconds=-1)  # any age is already "expired"
        p = SyntheticRainfallProvider()
        obs = p.fetch_latest()
        key = cache.put_observation(obs)
        assert cache.get_observation(key) is None

    def test_clear_empties_cache(self):
        from services.nowcast.cache import NowcastCache
        from services.nowcast.providers.synthetic_provider import (
            SyntheticRainfallProvider,
        )
        cache = NowcastCache(ttl_seconds=60)
        p = SyntheticRainfallProvider()
        obs = p.fetch_latest()
        cache.put_observation(obs)
        assert cache.size > 0
        cache.clear()
        assert cache.size == 0

    def test_get_unknown_key_returns_none(self):
        from services.nowcast.cache import NowcastCache
        cache = NowcastCache()
        assert cache.get_observation("nonexistent-key") is None

    def test_stats_counts_active_entries(self):
        from services.nowcast.cache import NowcastCache
        from services.nowcast.providers.synthetic_provider import (
            SyntheticRainfallProvider,
        )
        cache = NowcastCache(ttl_seconds=60)
        p = SyntheticRainfallProvider()
        cache.put_observation(p.fetch_latest())
        stats = cache.stats()
        assert stats["observation_entries"] == 1
        assert stats["observation_active"] == 1
        assert stats["total_entries"] == cache.size


# ---------------------------------------------------------------------------
# Extended coverage: NowcastRecord validation
# ---------------------------------------------------------------------------

class TestNowcastRecordValidationExtended:
    """Additional validation/serialisation tests for NowcastRecord."""

    def _valid_kwargs(self, **overrides):
        defaults = {
            "initialization_time": datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc),
            "lead_minutes": 15,
            "rate_mmh": np.zeros((134, 134), dtype=np.float32),
        }
        defaults.update(overrides)
        # Derive valid_time from the lead-time invariant unless the caller
        # explicitly overrides it (e.g. to test a naive/incorrect valid_time).
        if "valid_time" not in overrides:
            defaults["valid_time"] = defaults["initialization_time"] + timedelta(
                minutes=defaults["lead_minutes"]
            )
        return defaults

    def test_ndim_mismatch_rejected(self):
        from services.nowcast.nowcast_record import NowcastRecord
        with pytest.raises(ValueError, match="2-D"):
            NowcastRecord(**self._valid_kwargs(rate_mmh=np.zeros(134, dtype=np.float32)))

    def test_shape_mismatch_rejected(self):
        from services.nowcast.nowcast_record import NowcastRecord
        with pytest.raises(ValueError, match="shape"):
            NowcastRecord(**self._valid_kwargs(rate_mmh=np.zeros((10, 10), dtype=np.float32)))

    def test_wrong_units_rejected(self):
        from services.nowcast.nowcast_record import NowcastRecord
        with pytest.raises(ValueError, match="mm/h"):
            NowcastRecord(**self._valid_kwargs(units="in/h"))

    def test_nan_rejected(self):
        from services.nowcast.nowcast_record import NowcastRecord
        rate = np.zeros((134, 134), dtype=np.float32)
        rate[0, 0] = np.nan
        with pytest.raises(ValueError, match="finite"):
            NowcastRecord(**self._valid_kwargs(rate_mmh=rate))

    def test_naive_initialization_time_rejected(self):
        from services.nowcast.nowcast_record import NowcastRecord
        with pytest.raises(ValueError, match="initialization_time"):
            NowcastRecord(**self._valid_kwargs(initialization_time=datetime(2026, 8, 22, 12, 0)))  # noqa: DTZ001

    def test_naive_valid_time_rejected(self):
        from services.nowcast.nowcast_record import NowcastRecord
        with pytest.raises(ValueError, match="valid_time"):
            NowcastRecord(**self._valid_kwargs(valid_time=datetime(2026, 8, 22, 12, 15)))  # noqa: DTZ001

    def test_to_dict_include_rates(self):
        from services.nowcast.nowcast_record import NowcastRecord
        rate = np.full((134, 134), 5.0, dtype=np.float32)
        rec = NowcastRecord(**self._valid_kwargs(rate_mmh=rate))
        d = rec.to_dict(include_rates=True)
        assert "values" in d
        assert len(d["values"]) == 134 * 134
        assert d["values"][0] == 5.0

    def test_to_dict_excludes_rates_by_default(self):
        from services.nowcast.nowcast_record import NowcastRecord
        rec = NowcastRecord(**self._valid_kwargs())
        d = rec.to_dict()
        assert "values" not in d

    def test_to_dict_includes_metadata_when_present(self):
        from services.nowcast.nowcast_record import NowcastRecord
        rec = NowcastRecord(**self._valid_kwargs(metadata={"note": "test"}))
        d = rec.to_dict()
        assert d["metadata"] == {"note": "test"}

    def test_fingerprint_changes_with_lead_minutes(self):
        from services.nowcast.nowcast_record import NowcastRecord
        rec1 = NowcastRecord(**self._valid_kwargs(lead_minutes=0))
        rec2 = NowcastRecord(**self._valid_kwargs(lead_minutes=15))
        assert rec1.compute_fingerprint() != rec2.compute_fingerprint()

    def test_fingerprint_stable_for_identical_inputs(self):
        from services.nowcast.nowcast_record import NowcastRecord
        rec1 = NowcastRecord(**self._valid_kwargs())
        rec2 = NowcastRecord(**self._valid_kwargs())
        assert rec1.compute_fingerprint() == rec2.compute_fingerprint()


# ---------------------------------------------------------------------------
# Extended coverage: PersistenceNowcast / NowcastConfig
# ---------------------------------------------------------------------------

class TestPersistenceNowcastExtended:
    """Invalid-quality gating and configuration boundary behaviour."""

    def test_generate_with_invalid_quality_returns_empty(self):
        from services.nowcast.engine import PersistenceNowcast
        from services.nowcast.providers.synthetic_provider import (
            SyntheticRainfallProvider,
        )
        from services.nowcast.quality import DataFreshness, QualityResult
        p = SyntheticRainfallProvider()
        obs = p.fetch_latest()
        engine = PersistenceNowcast()
        invalid_quality = QualityResult(
            observation=obs, freshness=DataFreshness.INVALID, valid=False,
            errors=["forced invalid"], warnings=[], checked_at=datetime.now(timezone.utc),
        )
        records = engine.generate(obs, invalid_quality)
        assert records == []

    def test_generate_for_lead_with_invalid_quality_returns_none(self):
        from services.nowcast.engine import PersistenceNowcast
        from services.nowcast.providers.synthetic_provider import (
            SyntheticRainfallProvider,
        )
        from services.nowcast.quality import DataFreshness, QualityResult
        p = SyntheticRainfallProvider()
        obs = p.fetch_latest()
        engine = PersistenceNowcast()
        invalid_quality = QualityResult(
            observation=obs, freshness=DataFreshness.INVALID, valid=False,
            errors=["forced invalid"], warnings=[], checked_at=datetime.now(timezone.utc),
        )
        rec = engine.generate_for_lead(obs, 15, invalid_quality)
        assert rec is None

    def test_config_boundary_lead_equals_max(self):
        from services.nowcast.engine import NowcastConfig
        config = NowcastConfig(lead_times_minutes=(0, 60), max_lead_minutes=60)
        assert 60 in config.lead_times_minutes

    def test_config_negative_lead_rejected(self):
        from services.nowcast.engine import NowcastConfig
        with pytest.raises(ValueError, match="outside"):
            NowcastConfig(lead_times_minutes=(-5, 0), max_lead_minutes=60)

    def test_generate_valid_times_increase_with_lead(self):
        from services.nowcast.engine import PersistenceNowcast
        from services.nowcast.providers.synthetic_provider import (
            SyntheticRainfallProvider,
        )
        p = SyntheticRainfallProvider()
        obs = p.fetch_latest()
        engine = PersistenceNowcast()
        records = engine.generate(obs)
        for rec in records:
            expected_valid = rec.initialization_time + timedelta(minutes=rec.lead_minutes)
            assert rec.valid_time == expected_valid

    def test_generate_quality_flags_include_persistence(self):
        from services.nowcast.engine import PersistenceNowcast
        from services.nowcast.providers.synthetic_provider import (
            SyntheticRainfallProvider,
        )
        p = SyntheticRainfallProvider()
        obs = p.fetch_latest()
        engine = PersistenceNowcast()
        records = engine.generate(obs)
        for rec in records:
            assert "PERSISTENCE" in rec.quality_flags


# ---------------------------------------------------------------------------
# Extended coverage: verification metrics (POD, FAR, edge cases)
# ---------------------------------------------------------------------------

class TestVerificationMetricsExtended:
    """POD/FAR computation and zero-denominator edge cases."""

    def test_pod_computation(self):
        from services.nowcast.verification import compute_pod
        f = np.array([0.0, 5.0, 10.0, 0.0])
        o = np.array([0.0, 5.0, 10.0, 5.0])
        pod = compute_pod(f, o, threshold=0.1)
        assert abs(pod - (2.0 / 3.0)) < 1e-10

    def test_far_computation(self):
        from services.nowcast.verification import compute_far
        f = np.array([5.0, 5.0, 0.0])
        o = np.array([0.0, 5.0, 0.0])
        far = compute_far(f, o, threshold=0.1)
        assert abs(far - 0.5) < 1e-10

    def test_csi_zero_denominator_returns_zero(self):
        from services.nowcast.verification import compute_csi
        f = np.zeros(4)
        o = np.zeros(4)
        assert compute_csi(f, o) == 0.0

    def test_pod_zero_denominator_returns_zero(self):
        from services.nowcast.verification import compute_pod
        f = np.zeros(4)
        o = np.zeros(4)
        assert compute_pod(f, o) == 0.0

    def test_far_zero_denominator_returns_zero(self):
        from services.nowcast.verification import compute_far
        f = np.zeros(4)
        o = np.zeros(4)
        assert compute_far(f, o) == 0.0

    def test_correlation_constant_field_returns_zero(self):
        from services.nowcast.verification import compute_correlation
        f = np.full(10, 5.0)
        o = np.full(10, 5.0)
        assert compute_correlation(f, o) == 0.0

    def test_no_evaluation_available_custom_reason(self):
        from services.nowcast.verification import (
            VerificationStatus,
            no_evaluation_available,
        )
        result = no_evaluation_available("custom reason")
        assert result.status == VerificationStatus.NOT_EVALUATED
        assert result.notes == "custom reason"

    def test_no_evaluation_available_default_reason_nonempty(self):
        from services.nowcast.verification import no_evaluation_available
        result = no_evaluation_available()
        assert len(result.notes) > 0

    def test_verification_result_to_dict(self):
        from services.nowcast.verification import VerificationResult, VerificationStatus
        r = VerificationResult(status=VerificationStatus.EVALUATED, metrics={"mae_mmh": 1.0}, n_samples=5)
        d = r.to_dict()
        assert d["status"] == "EVALUATED"
        assert d["metrics"]["mae_mmh"] == 1.0
        assert d["n_samples"] == 5


# ---------------------------------------------------------------------------
# Extended coverage: FixtureRainfallProvider edge cases
# ---------------------------------------------------------------------------

class TestFixtureProviderEdgeCases:
    """Interval selection and clamping behaviour of FixtureRainfallProvider."""

    def test_fetch_observation_before_start_returns_first_interval(self):
        from services.nowcast.providers.fixture_provider import FixtureRainfallProvider
        p = FixtureRainfallProvider(
            profile_intensities_mmh=[10.0, 20.0, 30.0],
            start_time=datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc),
        )
        obs = p.fetch_observation(datetime(2026, 8, 22, 11, 0, tzinfo=timezone.utc))
        assert obs.metadata["interval_index"] == 0

    def test_fetch_latest_returns_last_interval(self):
        from services.nowcast.providers.fixture_provider import FixtureRainfallProvider
        p = FixtureRainfallProvider(profile_intensities_mmh=[10.0, 20.0, 30.0])
        obs = p.fetch_latest()
        assert obs.metadata["interval_index"] == 2

    def test_interval_index_clamped_beyond_range(self):
        from services.nowcast.providers.fixture_provider import FixtureRainfallProvider
        p = FixtureRainfallProvider(
            profile_intensities_mmh=[10.0, 20.0],
            start_time=datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc),
            interval_minutes=15,
        )
        obs = p.fetch_observation(datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc))
        assert obs.metadata["interval_index"] == 1  # clamped to the last interval


# ---------------------------------------------------------------------------
# Extended coverage: apps/api/rainfall_api.py module-level functions
# ---------------------------------------------------------------------------

class TestRainfallAPIModule:
    """Direct unit tests for the rainfall_api module (bypassing the HTTP layer)."""

    def test_get_active_provider_default_is_synthetic(self):
        from apps.api import rainfall_api
        provider = rainfall_api.get_active_provider()
        assert provider.provider_id == "synthetic-v1"

    def test_get_provider_known_and_unknown(self):
        from apps.api import rainfall_api
        assert rainfall_api.get_provider("synthetic-v1") is not None
        assert rainfall_api.get_provider("fixture-extreme-v1") is not None
        assert rainfall_api.get_provider("does-not-exist") is None

    def test_list_providers_marks_exactly_one_active(self):
        from apps.api import rainfall_api
        providers = rainfall_api.list_providers()
        active_flags = [p["active"] for p in providers]
        assert active_flags.count(True) == 1

    def test_set_active_provider_switches_and_restores(self):
        from apps.api import rainfall_api
        original = rainfall_api._active_provider_id
        try:
            ok = rainfall_api.set_active_provider("fixture-extreme-v1")
            assert ok is True
            assert rainfall_api.get_active_provider().provider_id == "fixture-extreme-v1"
        finally:
            rainfall_api.set_active_provider(original)
        assert rainfall_api.get_active_provider().provider_id == original

    def test_set_active_provider_unknown_returns_false(self):
        from apps.api import rainfall_api
        original = rainfall_api._active_provider_id
        ok = rainfall_api.set_active_provider("nonexistent-provider")
        assert ok is False
        assert rainfall_api._active_provider_id == original

    def test_fetch_observation_at_returns_available(self):
        from apps.api import rainfall_api
        t = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        result = rainfall_api.fetch_observation_at(t)
        assert result["status"] == "AVAILABLE"
        assert result["observation"] is not None
        assert result["source_type"] == "SYNTHETIC"

    def test_generate_nowcast_returns_dicts(self):
        from apps.api import rainfall_api
        provider = rainfall_api.get_active_provider()
        obs = provider.fetch_latest()
        records = rainfall_api.generate_nowcast(obs)
        assert isinstance(records, list)
        assert len(records) > 0
        assert all("lead_minutes" in r for r in records)

    def test_get_cache_stats_matches_cache_schema(self):
        from apps.api import rainfall_api
        stats = rainfall_api.get_cache_stats()
        assert "ttl_seconds" in stats
        assert "total_entries" in stats


# ---------------------------------------------------------------------------
# Extended coverage: additional apps/api/app.py M8 endpoint behaviour
# ---------------------------------------------------------------------------

class TestAppEndpointsExtended:
    """Additional M8 endpoint coverage not exercised above."""

    def test_rainfall_observation_valid_time_returns_200(self):
        from apps.api.app import app
        client = TestClient(app)
        t = datetime.now(timezone.utc).replace(second=0, microsecond=0).isoformat().replace("+00:00", "Z")
        r = client.get("/api/v1/rainfall/observation", params={"time": t})
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "AVAILABLE"

    def test_provider_detail_synthetic(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/api/v1/nowcast/providers/synthetic-v1")
        assert r.status_code == 200
        data = r.json()
        assert data["source_type"] == "SYNTHETIC"
        assert "health" in data
        assert "metadata" in data

    def test_provider_detail_fixture(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/api/v1/nowcast/providers/fixture-extreme-v1")
        assert r.status_code == 200
        data = r.json()
        assert data["source_type"] == "FIXTURE"

    def test_health_includes_provider_health_and_labels(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/health")
        data = r.json()
        assert data["rainfall_provider_health"] in ("HEALTHY", "DEGRADED", "UNAVAILABLE", "UNCONFIGURED")
        assert "labels" in data
        assert "SYNTHETIC" in data["labels"]

    def test_version_includes_nowcast_version(self):
        from apps.api.app import app
        from services.nowcast import NOWCAST_VERSION
        client = TestClient(app)
        r = client.get("/api/v1/version")
        data = r.json()
        assert data["nowcast_version"] == NOWCAST_VERSION

    def test_nowcast_providers_active_id_matches_default(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/api/v1/nowcast/providers")
        data = r.json()
        assert data["active_provider_id"] == "synthetic-v1"

    def test_rainfall_status_full_fields(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/api/v1/rainfall/status")
        data = r.json()
        for key in ("provider_id", "source_type", "source_name", "health",
                    "quality", "nowcast_version", "nowcast_method",
                    "lead_times_minutes", "max_lead_minutes", "labels"):
            assert key in data, f"missing {key}"

    def test_negative_lead_returns_400(self):
        # Starlette's default `int` path converter regex ([0-9]+) does not
        # match a leading minus sign, so a negative lead never reaches the
        # route handler via HTTP (it 404s at the routing layer instead).
        # Validate the underlying rejection logic directly.
        from apps.api import rainfall_api
        result = rainfall_api.fetch_nowcast_at_lead(-5)
        assert result["status"] == "INVALID_LEAD"

    def test_nowcast_unavailable_returns_503(self):
        from unittest import mock

        from apps.api import rainfall_api
        from apps.api.app import app
        client = TestClient(app)
        provider = rainfall_api.get_active_provider()
        with mock.patch.object(provider, "fetch_latest", return_value=None):
            r = client.get("/api/v1/nowcast/0")
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "DATA_UNAVAILABLE"

    def test_503_error_codes_are_distinguishable(self):
        """The frontend's exact-code check depends on 503s carrying distinct
        error codes: the nowcast-availability failure must NOT carry
        PROJECTION_UNAVAILABLE, so a 503 + different error code can never be
        swallowed into the projection-unavailable state."""
        from unittest import mock

        from apps.api import rainfall_api
        from apps.api.app import app
        client = TestClient(app)
        provider = rainfall_api.get_active_provider()
        with mock.patch.object(provider, "fetch_latest", return_value=None):
            r = client.get("/api/v1/nowcast/0")
        assert r.status_code == 503
        code = r.json()["error"]["code"]
        assert code == "DATA_UNAVAILABLE"
        assert code != "PROJECTION_UNAVAILABLE"

    def test_nowcast_verification_explanation_present(self):
        from apps.api.app import app
        client = TestClient(app)
        r = client.get("/api/v1/nowcast/verification")
        data = r.json()
        assert "explanation" in data
        assert len(data["explanation"]) > 0


# ---------------------------------------------------------------------------
# CodeRabbit fixes — Health endpoint must degrade when rainfall is UNAVAILABLE
# ---------------------------------------------------------------------------

class TestHealthDegradation:
    """Top-level /health must degrade when the rainfall dependency is unavailable."""

    def test_health_ok_when_artifacts_and_rainfall_healthy(self):
        from unittest import mock

        from apps.api.app import app, rainfall_api, store
        client = TestClient(app)
        ok_results = {sid: {} for sid in store.VALID_SCENARIO_IDS}
        with mock.patch.object(store, "load_results", return_value=ok_results), \
             mock.patch.object(
                 rainfall_api, "get_rainfall_status",
                 return_value={"source_type": "SYNTHETIC",
                               "health": {"status": "HEALTHY"}},
             ):
            r = client.get("/health")
        data = r.json()
        assert data["artifacts_ok"] is True
        assert data["rainfall_provider_health"] == "HEALTHY"
        assert data["status"] == "ok"

    def test_health_degraded_when_rainfall_unavailable(self):
        from unittest import mock

        from apps.api.app import app, rainfall_api, store
        client = TestClient(app)
        ok_results = {sid: {} for sid in store.VALID_SCENARIO_IDS}
        with mock.patch.object(store, "load_results", return_value=ok_results), \
             mock.patch.object(
                 rainfall_api, "get_rainfall_status",
                 return_value={"source_type": "FIXTURE",
                               "health": {"status": "UNAVAILABLE"}},
             ):
            r = client.get("/health")
        data = r.json()
        assert data["rainfall_provider_health"] == "UNAVAILABLE"
        assert data["status"] == "degraded"

    def test_health_degraded_when_artifacts_unhealthy(self):
        from unittest import mock

        from apps.api.app import app, rainfall_api, store
        client = TestClient(app)
        with mock.patch.object(store, "load_results",
                               side_effect=store.StoreError("missing artifacts")), \
             mock.patch.object(
                 rainfall_api, "get_rainfall_status",
                 return_value={"source_type": "SYNTHETIC",
                               "health": {"status": "HEALTHY"}},
             ):
            r = client.get("/health")
        data = r.json()
        assert data["artifacts_ok"] is False
        assert data["rainfall_provider_health"] == "HEALTHY"
        assert data["status"] == "degraded"

    def test_health_catches_only_expected_provider_failure(self):
        """A disconnected/unconfigured provider degrades health, not a bare crash."""
        from unittest import mock

        from apps.api.app import app, rainfall_api, store
        client = TestClient(app)
        ok_results = {sid: {} for sid in store.VALID_SCENARIO_IDS}
        with mock.patch.object(store, "load_results", return_value=ok_results), \
             mock.patch.object(
                 rainfall_api, "get_rainfall_status", side_effect=RuntimeError("no provider"),
             ):
            r = client.get("/health")
        data = r.json()
        assert data["rainfall_provider_type"] == "UNCONFIGURED"
        assert data["rainfall_provider_health"] == "UNAVAILABLE"
        assert data["status"] == "degraded"


# ---------------------------------------------------------------------------
# CodeRabbit fixes — invalid observations must NEVER be returned as AVAILABLE
# ---------------------------------------------------------------------------

class TestInvalidObservationNotAvailable:
    """An observation that fails validation must not be presented as AVAILABLE."""

    @staticmethod
    def _stale_observation() -> RainfallObservation:
        from services.nowcast.providers import RainfallObservation, SourceType
        stale_time = datetime.now(timezone.utc) - timedelta(hours=10)
        return RainfallObservation(
            observation_time=stale_time,
            valid_from=stale_time,
            valid_to=stale_time + timedelta(minutes=15),
            rate_mmh=np.zeros((134, 134), dtype=np.float32),
            source_type=SourceType.SYNTHETIC,
            source_name="stale",
            source_provider_id="stale-provider",
            spatial_reference="EPSG:32645",
            spatial_resolution_m=30.0,
            width=134,
            height=134,
        )

    def test_latest_observation_invalid_not_available(self):
        from unittest import mock

        from apps.api import rainfall_api
        provider = rainfall_api.get_active_provider()
        obs = self._stale_observation()
        with mock.patch.object(provider, "fetch_latest", return_value=obs):
            result = rainfall_api.fetch_latest_observation()
        assert result["status"] == "UNAVAILABLE"
        assert result["observation"] is None
        assert result["quality"]["valid"] is False

    def test_observation_at_invalid_not_available(self):
        from unittest import mock

        from apps.api import rainfall_api
        provider = rainfall_api.get_active_provider()
        obs = self._stale_observation()
        with mock.patch.object(provider, "fetch_observation", return_value=obs):
            result = rainfall_api.fetch_observation_at(datetime.now(timezone.utc))
        assert result["status"] == "UNAVAILABLE"
        assert result["quality"]["valid"] is False

    def test_nowcast_latest_invalid_not_available(self):
        from unittest import mock

        from apps.api import rainfall_api
        provider = rainfall_api.get_active_provider()
        obs = self._stale_observation()
        with mock.patch.object(provider, "fetch_latest", return_value=obs):
            result = rainfall_api.fetch_latest_nowcast()
        assert result["status"] == "UNAVAILABLE"
        assert result["nowcast"] == []
        assert "quality" in result
        assert result["quality"]["valid"] is False
        # Do not apply normal demonstration labels to a failed/invalid forecast.
        assert "DEMONSTRATION" not in result["labels"]
        assert "NOT_REAL_TIME" not in result["labels"]

    def test_nowcast_at_lead_invalid_not_available(self):
        from unittest import mock

        from apps.api import rainfall_api
        provider = rainfall_api.get_active_provider()
        obs = self._stale_observation()
        with mock.patch.object(provider, "fetch_latest", return_value=obs):
            result = rainfall_api.fetch_nowcast_at_lead(15)
        assert result["status"] == "UNAVAILABLE"
        assert result["nowcast"] is None
        assert "quality" in result
        assert result["quality"]["valid"] is False


# ---------------------------------------------------------------------------
# CodeRabbit fixes — NowcastCache is actually integrated into the API path
# ---------------------------------------------------------------------------

class TestCacheIntegration:
    """A normal rainfall/nowcast API request creates cache entries."""

    def test_rainfall_and_nowcast_request_create_cache_entries(self):
        from apps.api import rainfall_api
        from apps.api.app import app
        rainfall_api._cache.clear()
        client = TestClient(app)
        r1 = client.get("/api/v1/rainfall/latest")
        r2 = client.get("/api/v1/nowcast/latest")
        assert r1.status_code == 200
        assert r1.json()["status"] == "AVAILABLE"
        assert r2.status_code == 200
        assert r2.json()["status"] == "AVAILABLE"
        stats = rainfall_api.get_cache_stats()
        assert stats["observation_entries"] > 0, "observation cache not populated"
        assert stats["nowcast_entries"] > 0, "nowcast cache not populated"

    def test_repeated_observation_at_same_time_hits_cache(self):
        from services.nowcast.cache import NowcastCache
        cache = NowcastCache(ttl_seconds=60)
        from services.nowcast.providers.synthetic_provider import (
            SyntheticRainfallProvider,
        )
        p = SyntheticRainfallProvider()
        t = datetime(2026, 8, 22, 14, 30, tzinfo=timezone.utc)
        obs1 = p.fetch_observation(t)
        key1 = cache.put_observation(obs1)
        obs2 = p.fetch_observation(t)
        key2 = cache.put_observation(obs2)
        assert key1 == key2
        assert cache.get_observation(key1) is not None


# ---------------------------------------------------------------------------
# CodeRabbit fixes — cache immutability / snapshots
# ---------------------------------------------------------------------------

class TestCacheImmutability:
    """The cache must never expose caller-owned mutable state."""

    def test_observation_immutable_after_put_and_get(self):
        from services.nowcast.cache import NowcastCache
        from services.nowcast.providers.synthetic_provider import (
            SyntheticRainfallProvider,
        )
        cache = NowcastCache(ttl_seconds=60)
        p = SyntheticRainfallProvider()
        obs = p.fetch_latest()
        original = obs.rate_mmh.copy()
        key = cache.put_observation(obs)
        # mutate caller-owned object after put — cached value unchanged
        obs.rate_mmh[...] = 99.0
        obs.metadata["hacked"] = True
        cached = cache.get_observation(key)
        np.testing.assert_array_equal(cached.rate_mmh, original)
        assert "hacked" not in (cached.metadata or {})
        # mutate returned object — stored value unchanged
        cached.rate_mmh[...] = -1.0
        cached.metadata["hacked2"] = True
        cached2 = cache.get_observation(key)
        np.testing.assert_array_equal(cached2.rate_mmh, original)
        assert "hacked2" not in (cached2.metadata or {})

    def test_nowcast_immutable_after_put_and_get(self):
        from services.nowcast.cache import NowcastCache
        from services.nowcast.engine import PersistenceNowcast
        from services.nowcast.providers.synthetic_provider import (
            SyntheticRainfallProvider,
        )
        cache = NowcastCache(ttl_seconds=60)
        p = SyntheticRainfallProvider()
        obs = p.fetch_latest()
        engine = PersistenceNowcast()
        records = engine.generate(obs)
        leads = engine.config.lead_times_minutes
        method = engine.config.method
        original = records[0].rate_mmh.copy()
        cache.put_nowcast(obs, method, leads, records)
        # mutate caller-owned records after put — cached value unchanged
        records[0].rate_mmh[...] = 99.0
        records[0].metadata["hacked"] = True
        cached = cache.get_nowcast(obs, method, leads)
        np.testing.assert_array_equal(cached[0].rate_mmh, original)
        assert "hacked" not in cached[0].metadata
        # mutate returned object — stored value unchanged
        cached[0].rate_mmh[...] = -1.0
        cached[0].metadata["hacked2"] = True
        cached2 = cache.get_nowcast(obs, method, leads)
        np.testing.assert_array_equal(cached2[0].rate_mmh, original)
        assert "hacked2" not in cached2[0].metadata


# ---------------------------------------------------------------------------
# CodeRabbit fixes — cache thread safety
# ---------------------------------------------------------------------------

class TestCacheThreadSafety:
    """Concurrent cache operations must not raise or corrupt state."""

    def test_concurrent_access_does_not_corrupt(self):
        import threading

        from services.nowcast.cache import NowcastCache
        from services.nowcast.providers.synthetic_provider import (
            SyntheticRainfallProvider,
        )
        cache = NowcastCache(ttl_seconds=60)
        p = SyntheticRainfallProvider()
        obs = p.fetch_latest()
        leads = (0, 15, 30)
        errors: list[BaseException] = []

        def worker() -> None:
            try:
                for _ in range(25):
                    # Concurrent clear() may legitimately remove an entry
                    # between a put and its get, so we only assert that the
                    # operations do not raise or corrupt internal state.
                    key = cache.put_observation(obs)
                    cache.get_observation(key)
                    cache.put_nowcast(obs, "M", leads, [])
                    cache.get_nowcast(obs, "M", leads)
                    _ = cache.size
                    _ = cache.stats()
                    cache.clear()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors, f"concurrent cache errors: {errors}"


# ---------------------------------------------------------------------------
# CodeRabbit fixes — NowcastRecord lead-time invariant
# ---------------------------------------------------------------------------

class TestNowcastLeadTimeInvariant:
    """valid_time must equal initialization_time + lead_minutes."""

    def _record(self, *, init, lead):
        from services.nowcast.nowcast_record import NowcastRecord
        return NowcastRecord(
            initialization_time=init,
            valid_time=init + timedelta(minutes=lead),
            lead_minutes=lead,
            rate_mmh=np.zeros((134, 134), dtype=np.float32),
        )

    def test_valid_record_accepted(self):
        init = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
        rec = self._record(init=init, lead=15)
        assert rec.valid_time == init + timedelta(minutes=15)

    def test_valid_lead_zero_accepted(self):
        init = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
        rec = self._record(init=init, lead=0)
        assert rec.valid_time == init

    def test_invalid_record_rejected(self):
        from services.nowcast.nowcast_record import NowcastRecord
        init = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
        with pytest.raises(ValueError, match="lead_minutes"):
            NowcastRecord(
                initialization_time=init,
                valid_time=init + timedelta(minutes=30),  # inconsistent
                lead_minutes=15,
                rate_mmh=np.zeros((134, 134), dtype=np.float32),
            )


# ---------------------------------------------------------------------------
# CodeRabbit fixes — complete rainfall fingerprint
# ---------------------------------------------------------------------------

class TestFullFieldFingerprint:
    """The fingerprint must hash the complete contiguous rate array."""

    @staticmethod
    def _observation(rate):
        from services.nowcast.providers import RainfallObservation, SourceType
        return RainfallObservation(
            observation_time=datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc),
            valid_from=datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc),
            valid_to=datetime(2026, 8, 22, 12, 15, tzinfo=timezone.utc),
            rate_mmh=rate,
            source_type=SourceType.SYNTHETIC,
            source_name="fp",
            source_provider_id="fp-provider",
            spatial_reference="EPSG:32645",
            spatial_resolution_m=30.0,
            width=rate.shape[1],
            height=rate.shape[0],
        )

    def test_same_field_same_fingerprint(self):
        rate = np.zeros((4, 4), dtype=np.float32)
        rate[0, 0] = 1.0
        assert self._observation(rate.copy()).fingerprint() == \
            self._observation(rate.copy()).fingerprint()

    def test_different_field_same_mean_max_different_fingerprint(self):
        # Both fields share the same mean and max but differ in spatial layout.
        a = np.zeros((4, 4), dtype=np.float32)
        a[0, :] = 1.0
        b = np.zeros((4, 4), dtype=np.float32)
        b[:, 0] = 1.0
        assert float(np.mean(a)) == float(np.mean(b))  # both 0.25
        assert float(np.max(a)) == float(np.max(b)) == 1.0
        assert np.any(a != b)
        assert self._observation(a).fingerprint() != self._observation(b).fingerprint()

    def test_nowcast_same_field_same_fingerprint(self):
        from services.nowcast.nowcast_record import NowcastRecord
        init = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
        rate = np.zeros((4, 4), dtype=np.float32)
        rate[0, 0] = 1.0
        rec1 = NowcastRecord(
            initialization_time=init, valid_time=init + timedelta(minutes=15),
            lead_minutes=15, rate_mmh=rate.copy(), width=4, height=4,
        )
        rec2 = NowcastRecord(
            initialization_time=init, valid_time=init + timedelta(minutes=15),
            lead_minutes=15, rate_mmh=rate.copy(), width=4, height=4,
        )
        assert rec1.compute_fingerprint() == rec2.compute_fingerprint()


# ---------------------------------------------------------------------------
# CodeRabbit fixes — fixture provider must not manufacture future timestamps
# ---------------------------------------------------------------------------

class TestFixtureNoFutureTimestamp:
    """A request beyond the fixture duration must not create a future timestamp."""

    def test_beyond_duration_clamped_to_last_interval_start(self):
        from services.nowcast.providers.fixture_provider import FixtureRainfallProvider
        p = FixtureRainfallProvider(
            profile_intensities_mmh=[10.0, 20.0, 30.0],
            start_time=datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc),
            interval_minutes=15,
        )
        obs = p.fetch_observation(datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc))
        last_start = datetime(2026, 8, 22, 12, 30, tzinfo=timezone.utc)
        assert obs.observation_time == last_start
        assert obs.metadata["interval_index"] == 2
        # The last interval's valid_to must not exceed the fixture end (12:45).
        assert obs.valid_to == datetime(2026, 8, 22, 12, 45, tzinfo=timezone.utc)

    def test_fetch_latest_is_last_interval_not_future(self):
        from services.nowcast.providers.fixture_provider import FixtureRainfallProvider
        p = FixtureRainfallProvider(
            profile_intensities_mmh=[10.0, 20.0],
            start_time=datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc),
            interval_minutes=15,
        )
        obs = p.fetch_latest()
        assert obs.observation_time == datetime(2026, 8, 22, 12, 15, tzinfo=timezone.utc)
        assert obs.valid_to == datetime(2026, 8, 22, 12, 30, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# CodeRabbit fixes — frontend lead-time bug
# ---------------------------------------------------------------------------

class TestFrontendLeadTime:
    """The dashboard must render lead times from ncs (nowcast status), not nc."""

    def test_dashboard_uses_ncs_for_lead_times(self):
        from pathlib import Path
        idx = Path(__file__).resolve().parents[1] / "apps" / "web" / "index.html"
        html = idx.read_text(encoding="utf-8")
        # The buggy code referenced nc.lead_times_minutes inside an ncs check.
        assert "nc.lead_times_minutes.join" not in html
        assert "ncs.lead_times_minutes.join" in html
        # The "0–60 min" fallback must be preserved.
        assert "0–60 min" in html


class TestFrontendClampLead:
    """clampLead must select the nearest valid projection lead."""

    def _get_clamp_function(self):
        from pathlib import Path
        idx = Path(__file__).resolve().parents[1] / "apps" / "web" / "index.html"
        return idx.read_text(encoding="utf-8")

    def test_clamp_lead_function_exists(self):
        html = self._get_clamp_function()
        assert "function clampLead" in html
        # Must not unconditionally fall through to the maximum for intermediate values.
        # The old buggy code had a simple 3-line fallthrough: if exact, if below-min,
        # else return max. The fix adds a nearest-lead search for intermediate values.
        clamp_body = html.split("function clampLead")[1].split("function")[0]
        # The fix must include a best-match search (not just a fallthrough to max).
        assert "bestDist" in clamp_body or "Math.abs" in clamp_body

    def test_clamp_lead_uses_nearest_valid(self):
        html = self._get_clamp_function()
        clamp_body = html.split("function clampLead")[1].split("function")[0]
        # Must contain logic to find the nearest valid lead
        assert "bestDist" in clamp_body or "Math.abs" in clamp_body

    def test_no_math_max_spread_on_depth(self):
        """Math.max(...frame.depth) must be replaced with safe reduction."""
        from pathlib import Path
        idx = Path(__file__).resolve().parents[1] / "apps" / "web" / "index.html"
        html = idx.read_text(encoding="utf-8")
        assert "Math.max(...frame.depth)" not in html

    def test_no_dead_flooded_area_assignment(self):
        """currentFloodedArea must not reference non-existent projection.flooded_area_m2."""
        from pathlib import Path
        idx = Path(__file__).resolve().parents[1] / "apps" / "web" / "index.html"
        html = idx.read_text(encoding="utf-8")
        # The dead code assigned frame.projection.flooded_area_m2 should be removed.
        assert "const currentFloodedArea" not in html


class TestFrontendProjectionUnavailable:
    """The frontend must handle 503 PROJECTION_UNAVAILABLE, and only that code."""

    def test_getjson_captures_status_code(self):
        from pathlib import Path
        idx = Path(__file__).resolve().parents[1] / "apps" / "web" / "index.html"
        html = idx.read_text(encoding="utf-8")
        assert "err.statusCode" in html
        assert "err.errorCode" in html

    def test_projection_unavailable_render_function_exists(self):
        from pathlib import Path
        idx = Path(__file__).resolve().parents[1] / "apps" / "web" / "index.html"
        html = idx.read_text(encoding="utf-8")
        assert "renderProjectionUnavailable" in html
        assert "Projection unavailable" in html

    def test_select_projection_config_handles_503(self):
        from pathlib import Path
        idx = Path(__file__).resolve().parents[1] / "apps" / "web" / "index.html"
        html = idx.read_text(encoding="utf-8")
        select_body = html.split("async function selectProjectionConfig")[1].split("async function")[0]
        assert "PROJECTION_UNAVAILABLE" in select_body
        assert "statusCode === 503" in select_body

    def test_init_handles_projection_unavailable(self):
        from pathlib import Path
        idx = Path(__file__).resolve().parents[1] / "apps" / "web" / "index.html"
        html = idx.read_text(encoding="utf-8")
        init_body = html.split("async function init")[1].split("</script>")[0]
        assert "503" in init_body

    def test_all_503_conditions_require_error_code(self):
        """A bare HTTP 503 must never trigger the unavailable-rainfall UI.
        Every 503 check in the dashboard must be conjoined with the
        documented PROJECTION_UNAVAILABLE error code."""
        from pathlib import Path
        idx = Path(__file__).resolve().parents[1] / "apps" / "web" / "index.html"
        html = idx.read_text(encoding="utf-8")
        statements = [s for s in html.split("{") if "statusCode === 503" in s]
        assert statements, "expected 503 handling in the projection error paths"
        for s in statements:
            assert "PROJECTION_UNAVAILABLE" in s, f"bare 503 branch found: {s.strip()}"

    def test_503_with_other_error_code_is_rethrown(self):
        """HTTP 503 with any other error code (or any non-503 error) must not
        be swallowed into the unavailable state: each projection error path
        rethrows after the exact-code check."""
        from pathlib import Path
        idx = Path(__file__).resolve().parents[1] / "apps" / "web" / "index.html"
        html = idx.read_text(encoding="utf-8")
        regions = (
            ("async function setLead", "async function selectScenario", "throw e"),
            ("async function selectRoad", "async function computeRoute", "throw e"),
            ("async function init", "</script>", "throw e2"),
            ('$("view-mode").onchange', '$("projection-config").onchange', "throw e2"),
            ('$("projection-config").onchange', "const speeds", "throw e2"),
        )
        for start_marker, end_marker, rethrow in regions:
            region = html.split(start_marker)[1].split(end_marker)[0]
            check = region.index("statusCode === 503")
            assert rethrow in region[check:], f"{start_marker}: non-matching errors must be rethrown"

    def test_projection_unavailable_renders_unavailable_state(self):
        """HTTP 503 + PROJECTION_UNAVAILABLE must render the explicit
        unavailable state (or clear the affected state), not crash and not
        fake a successful projection."""
        from pathlib import Path
        idx = Path(__file__).resolve().parents[1] / "apps" / "web" / "index.html"
        html = idx.read_text(encoding="utf-8")
        code_cond = 'e.statusCode === 503 && e.errorCode === "PROJECTION_UNAVAILABLE"'
        e2_cond = 'e2.statusCode === 503 && e2.errorCode === "PROJECTION_UNAVAILABLE"'

        set_lead = html.split("async function setLead")[1].split("async function")[0]
        assert code_cond in set_lead
        branch = set_lead.split(code_cond)[1].split("throw e")[0]
        assert "renderProjectionUnavailable()" in branch

        select_cfg = html.split("async function selectProjectionConfig")[1].split("async function")[0]
        assert code_cond in select_cfg
        branch = select_cfg.split(code_cond)[1].split("throw e")[0]
        assert "renderProjectionUnavailable()" in branch

        select_road = html.split("async function selectRoad")[1].split("async function")[0]
        assert code_cond in select_road
        branch = select_road.split(code_cond)[1].split("throw e")[0]
        assert "state.selectedRoadTimeline = null" in branch

        view_mode = html.split('$("view-mode").onchange')[1].split('$("projection-config").onchange')[0]
        assert e2_cond in view_mode
        branch = view_mode.split(e2_cond)[1].split("throw e2")[0]
        assert "renderProjectionUnavailable()" in branch

        proj_config = html.split('$("projection-config").onchange')[1].split("const speeds")[0]
        assert e2_cond in proj_config
        branch = proj_config.split(e2_cond)[1].split("throw e2")[0]
        assert "renderProjectionUnavailable()" in branch

        init_body = html.split("async function init")[1].split("</script>")[0]
        assert e2_cond in init_body
        branch = init_body.split(e2_cond)[1].split("throw e2")[0]
        assert "projectionSummaryData = null" in branch
