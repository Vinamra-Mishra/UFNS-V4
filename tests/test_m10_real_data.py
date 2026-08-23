"""M10 — Real-pilot data foundation tests.

Tests verify:
- Source metadata contracts
- File identity/fingerprint determinism
- CRS validation
- Synthetic/real classification separation
- Rejection of fabricated hydraulic parameters
- NOT_FETCHED/NOT_AVAILABLE status when data is unavailable
- Provenance completeness and deep immutability
- Result-specific provenance (templates are never returned by identity)
- No operational claims from data foundation
- Real-pilot artifact execution (2026-08-22): the human-supplied artifacts in
  data/raw/ produce the evidence-backed statuses (DEM VALIDATED; DEM
  normalization BLOCKED on pilot-grid spatial coherence; drainage audits
  AUDIT_PARTIAL on the embedded-CRS gap; entity mapping BLOCKED by the
  VALIDATED-source contract). These tests are skipped when the artifacts are
  absent from data/raw (the canonical raw location; see .gitignore).
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
from fixtures.m10.generators import (
    FIXTURE_DEM_SOURCE,
    FIXTURE_DRAINAGE_SOURCE,
    write_dem_fixture,
    write_dem_fixture_no_overlap,
    write_drainage_fixture,
    write_nan_dem_fixture,
    write_not_a_geotiff,
    write_not_a_parquet,
    write_plain_parquet_fixture,
)

from services.ingestion.real_data import (
    COPERNICUS_DEM_SOURCE,
    WB_AMRUT_SOURCE,
    AttributeAudit,
    AttributeAvailability,
    DataIngestionStatus,
    DatasetAuditResult,
    DataSourceClassification,
    SourceProvenance,
    SpatialBounds,
    compute_data_fingerprint,
    compute_schema_fingerprint,
    validate_crs,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fixture_dem_config():
    from services.ingestion.dem_real import DEMIngestionConfig

    return DEMIngestionConfig(source=FIXTURE_DEM_SOURCE)


def _fixture_mapping_config():
    from services.ingestion.drainage_real import DrainageMappingConfig

    return DrainageMappingConfig(source=FIXTURE_DRAINAGE_SOURCE)


def _write_dem_tif(path: Path) -> Path:
    """Minimal valid GeoTIFF exercising the DEM validation path (~1 arcsec)."""
    return write_dem_fixture(path, window=(77.0, 28.4, 77.1, 28.5))


def _write_drainage_parquet(path: Path) -> Path:
    """Minimal plain parquet with every required hydraulic column present."""
    return write_plain_parquet_fixture(path)


def _sample_provenance(**overrides) -> SourceProvenance:
    base = {
        "source_name": "s",
        "dataset_name": "d",
        "version": "1",
        "acquisition_timestamp": datetime(2026, 8, 22, tzinfo=timezone.utc),
        "source_url": "https://example.org",
        "license_id": "L",
        "classification": DataSourceClassification.PROVISIONAL,
        "crs": "EPSG:4326",
        "spatial_extent": SpatialBounds(west=77.0, south=28.0, east=77.5, north=28.5),
        "schema_fingerprint": "a" * 64,
        "data_fingerprint": "b" * 64,
        "known_limitations": ("a", "b"),
    }
    base.update(overrides)
    return SourceProvenance(**base)


# ---------------------------------------------------------------------------
# B02 WB AMRUT audit
# ---------------------------------------------------------------------------


class TestB02Audit:
    """B02 WB AMRUT data audit status."""

    def test_wb_amrut_source_provenance_complete(self):
        src = WB_AMRUT_SOURCE
        assert src.source_name
        assert src.dataset_name
        assert src.version
        assert src.source_url
        assert src.license_id
        assert src.classification == DataSourceClassification.PROVISIONAL
        assert src.crs == "EPSG:4326"
        assert len(src.known_limitations) > 0

    def test_wb_amrut_not_fetched(self):
        """Without the actual parquet file, the audit must report NOT_FETCHED."""
        from services.ingestion.drainage_real import audit_wb_amrut_drains
        result = audit_wb_amrut_drains(source_path=None)
        assert result.status == DataIngestionStatus.NOT_FETCHED
        assert len(result.blockers) > 0
        assert len(result.missing_hydraulic_parameters) > 0

    def test_wb_amrut_not_fetched_labels(self):
        """NOT_FETCHED represents no data: it must not be labelled SYNTHETIC."""
        from services.ingestion.drainage_real import audit_wb_amrut_drains
        labels = audit_wb_amrut_drains(source_path=None).to_dict()["labels"]
        assert "NOT_FETCHED" in labels
        assert "PROVISIONAL" in labels
        assert "NO_DATA" in labels
        assert "SYNTHETIC" not in labels

    def test_wb_amrut_no_fabrication(self):
        """Real drainage entities must never contain fabricated hydraulic parameters."""
        from services.ingestion.drainage_real import DrainageEntity, DrainageFeatureType
        entity = DrainageEntity(
            feature_id="test-001",
            feature_type=DrainageFeatureType.DRAIN,
            geometry_wkt="LINESTRING(0 0, 1 1)",
            crs="EPSG:4326",
            diameter_m=None,
            diameter_availability=AttributeAvailability.MISSING,
        )
        assert entity.diameter_m is None
        assert entity.diameter_availability == AttributeAvailability.MISSING
        d = entity.to_dict()
        assert d["diameter_availability"] == "MISSING"

    def test_wb_amrut_expected_attributes_documented(self):
        from services.ingestion.drainage_real import EXPECTED_WB_AMRUT_DRAIN_ATTRIBUTES
        assert len(EXPECTED_WB_AMRUT_DRAIN_ATTRIBUTES) > 0
        geom_attrs = [a for a in EXPECTED_WB_AMRUT_DRAIN_ATTRIBUTES if a["name"] == "geometry"]
        assert len(geom_attrs) == 1
        unknown_attrs = [a for a in EXPECTED_WB_AMRUT_DRAIN_ATTRIBUTES if a["dtype"] == "UNKNOWN"]
        assert len(unknown_attrs) >= 4  # diameter, invert, capacity, etc.


# ---------------------------------------------------------------------------
# Real DEM ingestion
# ---------------------------------------------------------------------------


class TestDEMIngestion:
    """Real DEM ingestion pipeline."""

    def test_copernicus_source_provenance_complete(self):
        src = COPERNICUS_DEM_SOURCE
        assert src.source_name
        assert src.dataset_name
        assert src.source_url
        assert src.license_id
        assert src.classification == DataSourceClassification.PROVISIONAL
        assert src.crs == "EPSG:4326"
        assert src.resolution
        assert len(src.known_limitations) > 0

    def test_dem_not_fetched(self):
        """Without the actual DEM file, the ingestion must report NOT_FETCHED."""
        from services.ingestion.dem_real import ingest_dem
        result = ingest_dem(source_path=None)
        assert result.status == DataIngestionStatus.NOT_FETCHED
        assert result.output_array is None
        assert len(result.validation_warnings) > 0

    def test_dem_not_fetched_labels(self):
        """NOT_FETCHED DEM represents no data: never SYNTHETIC (there is no
        synthetic fallback in this result)."""
        from services.ingestion.dem_real import ingest_dem
        labels = ingest_dem(source_path=None).to_dict()["labels"]
        assert "NOT_FETCHED" in labels
        assert "PROVISIONAL" in labels
        assert "NO_DATA" in labels
        assert "SYNTHETIC" not in labels

    def test_dem_nonexistent_file(self):
        """A non-existent file path must also report NOT_FETCHED."""
        from services.ingestion.dem_real import ingest_dem
        result = ingest_dem(source_path=Path("/nonexistent/dem.tif"))
        assert result.status == DataIngestionStatus.NOT_FETCHED

    def test_synthetic_dem_preserved(self):
        """The synthetic DEM fixture must remain available and unchanged."""
        from services.ingestion.dem import synthetic_dem
        dem = synthetic_dem()
        assert dem.shape == (134, 134)
        assert np.all(np.isfinite(dem))


# ---------------------------------------------------------------------------
# Data contracts and provenance
# ---------------------------------------------------------------------------


class TestDataContractAndProvenance:
    """Data contracts and provenance records."""

    def test_source_provenance_serialization(self):
        d = WB_AMRUT_SOURCE.to_dict()
        assert d["source_name"] == WB_AMRUT_SOURCE.source_name
        assert d["classification"] == "PROVISIONAL"
        assert d["crs"] == "EPSG:4326"
        assert isinstance(d["known_limitations"], list)

    def test_schema_fingerprint_deterministic(self):
        columns = [
            {"name": "geometry", "dtype": "LineString"},
            {"name": "id", "dtype": "string"},
            {"name": "type", "dtype": "string"},
        ]
        fp1 = compute_schema_fingerprint(columns)
        fp2 = compute_schema_fingerprint(columns)
        assert fp1 == fp2
        assert len(fp1) == 64  # SHA-256 hex

    def test_schema_fingerprint_changes_with_columns(self):
        cols_a = [{"name": "geometry", "dtype": "LineString"}]
        cols_b = [{"name": "geometry", "dtype": "Point"}]
        assert compute_schema_fingerprint(cols_a) != compute_schema_fingerprint(cols_b)

    def test_schema_fingerprint_order_independent(self):
        """Schema fingerprint must be deterministic regardless of column order."""
        cols_a = [
            {"name": "b", "dtype": "int"},
            {"name": "a", "dtype": "string"},
        ]
        cols_b = [
            {"name": "a", "dtype": "string"},
            {"name": "b", "dtype": "int"},
        ]
        assert compute_schema_fingerprint(cols_a) == compute_schema_fingerprint(cols_b)

    def test_crs_validation(self):
        assert validate_crs("EPSG:4326") is True
        assert validate_crs("EPSG:32645") is True
        assert validate_crs("EPSG:4326", expected_epsg=4326) is True
        assert validate_crs("EPSG:4326", expected_epsg=32645) is False
        assert validate_crs("not-a-crs") is False


# ---------------------------------------------------------------------------
# Provenance immutability (deep)
# ---------------------------------------------------------------------------


class TestProvenanceImmutability:
    """frozen=True must mean deeply immutable: no nested mutable state."""

    def test_nested_spatial_bounds_cannot_be_mutated(self):
        prov = _sample_provenance()
        with pytest.raises(FrozenInstanceError):
            prov.spatial_extent.west = 99.0
        with pytest.raises(FrozenInstanceError):
            prov.spatial_extent = SpatialBounds(0.0, 0.0, 1.0, 1.0)
        with pytest.raises(FrozenInstanceError):
            prov.known_limitations = prov.known_limitations + ("c",)
        with pytest.raises(FrozenInstanceError):
            prov.validation_status = "VALIDATED"

    def test_to_dict_mutation_does_not_affect_provenance(self):
        prov = _sample_provenance()
        d = prov.to_dict()
        d["spatial_extent"]["west"] = 123.0
        d["known_limitations"].append("injected")
        assert prov.spatial_extent.west == 77.0
        assert prov.known_limitations == ("a", "b")
        d2 = prov.to_dict()
        assert d is not d2
        assert d["spatial_extent"] is not d2["spatial_extent"]
        assert d2["spatial_extent"] == {"west": 77.0, "south": 28.0, "east": 77.5, "north": 28.5}

    def test_provenance_equality_and_hash_deterministic(self):
        p1 = _sample_provenance()
        p2 = _sample_provenance()
        assert p1 == p2
        assert hash(p1) == hash(p2)
        assert {p1, p2} == {p1}
        p3 = _sample_provenance(spatial_extent=SpatialBounds(0.0, 0.0, 1.0, 1.0))
        assert p1 != p3

    def test_dataset_audit_spatial_coverage_immutable(self):
        audit = DatasetAuditResult(
            source=WB_AMRUT_SOURCE,
            file_identity="f.parquet",
            file_size_bytes=1,
            record_count=0,
            geometry_type="LineString",
            crs_valid=True,
            coordinate_units="degrees",
            attributes=(),
            spatial_coverage={"pilot_region": 0.9},
        )
        with pytest.raises(TypeError):
            audit.spatial_coverage["injected"] = 1.0
        d = audit.to_dict()
        d["spatial_coverage"]["injected"] = 1.0
        assert dict(audit.spatial_coverage) == {"pilot_region": 0.9}

    def test_spatial_coverage_independent_of_caller_mapping(self):
        """Stored coverage must not be a view of the caller's mutable dict."""
        original = {"pilot_region": 0.9}
        audit = DatasetAuditResult(
            source=WB_AMRUT_SOURCE,
            file_identity="f.parquet",
            file_size_bytes=1,
            record_count=0,
            geometry_type="LineString",
            crs_valid=True,
            coordinate_units="degrees",
            attributes=(),
            spatial_coverage=original,
        )
        original["pilot_region"] = 999.0
        original["injected"] = 1.0
        assert dict(audit.spatial_coverage) == {"pilot_region": 0.9}
        d = audit.to_dict()
        d["spatial_coverage"]["pilot_region"] = -1.0
        assert dict(audit.spatial_coverage) == {"pilot_region": 0.9}


# ---------------------------------------------------------------------------
# Result-specific provenance (templates are never returned into results)
# ---------------------------------------------------------------------------


class TestResultProvenance:
    """Every ingestion result must carry its own observed provenance snapshot;
    the global source templates must never be mutated or shared by identity."""

    def test_source_templates_unchanged_by_ingestion(self, tmp_path):
        from services.ingestion.dem_real import ingest_dem
        from services.ingestion.drainage_real import audit_wb_amrut_drains

        dem_before = COPERNICUS_DEM_SOURCE.to_dict()
        drain_before = WB_AMRUT_SOURCE.to_dict()
        fixture_dem_before = FIXTURE_DEM_SOURCE.to_dict()
        fixture_drain_before = FIXTURE_DRAINAGE_SOURCE.to_dict()
        tif = _write_dem_tif(tmp_path / "dem.tif")
        pq = _write_drainage_parquet(tmp_path / "drains.parquet")
        ingest_dem(source_path=None)
        ingest_dem(source_path=tif, config=_fixture_dem_config())
        audit_wb_amrut_drains(source_path=None)
        audit_wb_amrut_drains(source_path=pq)
        assert COPERNICUS_DEM_SOURCE.to_dict() == dem_before
        assert WB_AMRUT_SOURCE.to_dict() == drain_before
        assert FIXTURE_DEM_SOURCE.to_dict() == fixture_dem_before
        assert FIXTURE_DRAINAGE_SOURCE.to_dict() == fixture_drain_before
        # Results carry snapshots, never the template object itself.
        assert ingest_dem(source_path=tif, config=_fixture_dem_config()).provenance is not FIXTURE_DEM_SOURCE
        assert audit_wb_amrut_drains(source_path=pq).provenance is not WB_AMRUT_SOURCE

    def test_not_fetched_results_do_not_claim_validation(self):
        from services.ingestion.dem_real import ingest_dem
        from services.ingestion.drainage_real import audit_wb_amrut_drains

        for provenance in (
            ingest_dem(source_path=None).provenance,
            audit_wb_amrut_drains(source_path=None).provenance,
        ):
            assert provenance.validation_status == "NOT_VALIDATED"
            assert provenance.data_fingerprint == ""
            assert provenance.schema_fingerprint == ""
            assert provenance.processing_fingerprint == ""
            assert provenance.spatial_extent is None

    def test_validated_dem_provenance_carries_observed_state(self, tmp_path):
        from services.ingestion.dem_real import ingest_dem

        tif = _write_dem_tif(tmp_path / "dem.tif")
        now = datetime.now(timezone.utc)
        result = ingest_dem(source_path=tif, config=_fixture_dem_config())
        assert result.status == DataIngestionStatus.VALIDATED
        p = result.provenance
        # Actual observed fingerprints, not template placeholders.
        assert p.data_fingerprint == compute_data_fingerprint(tif)
        assert len(p.schema_fingerprint) == 64
        assert p.validation_status == "VALIDATED"
        # Actual observed extent (rasterio bounds are west/south/east/north).
        assert p.spatial_extent == SpatialBounds(west=77.0, south=28.4, east=77.1, north=28.5)
        # Acquisition timestamp is the actual acquisition, not the template date.
        assert p.acquisition_timestamp.tzinfo is not None
        assert abs((p.acquisition_timestamp - now).total_seconds()) < 300
        # Limitations reflect the actual result: the template's NOT_FETCHED
        # claims must not survive into a fetched result.
        assert not any("NOT_FETCHED" in lim for lim in p.known_limitations)
        assert any("normalization" in lim.lower() for lim in p.known_limitations)

    def test_fetched_drainage_provenance_carries_observed_state(self, tmp_path):
        from services.ingestion.drainage_real import audit_wb_amrut_drains

        pq = _write_drainage_parquet(tmp_path / "drains.parquet")
        now = datetime.now(timezone.utc)
        result = audit_wb_amrut_drains(source_path=pq)
        assert result.status == DataIngestionStatus.AUDIT_PARTIAL
        p = result.provenance
        assert p.data_fingerprint == compute_data_fingerprint(pq)
        assert len(p.schema_fingerprint) == 64
        # Fetched but attribute audit incomplete (B02 OPEN) => PARTIAL, never
        # a full VALIDATED claim.
        assert p.validation_status == "PARTIAL"
        assert p.acquisition_timestamp.tzinfo is not None
        assert abs((p.acquisition_timestamp - now).total_seconds()) < 300
        assert any("B02" in lim for lim in p.known_limitations)
        assert not any("NOT_FETCHED" in lim for lim in p.known_limitations)

    def test_failed_dem_provenance_carries_observed_failure(self, tmp_path):
        from services.ingestion.dem_real import ingest_dem

        bad = tmp_path / "bad.tif"
        bad.write_bytes(b"this is not a geotiff")
        result = ingest_dem(source_path=bad)
        assert result.status == DataIngestionStatus.BLOCKED
        p = result.provenance
        # The file WAS observed: its fingerprint is recorded and the failure
        # is reflected in the validation status and limitations.
        assert p.data_fingerprint == compute_data_fingerprint(bad)
        assert p.validation_status == "FAILED"
        assert "failed to read" in " ".join(p.known_limitations).lower()
        assert result.validation_errors


# ---------------------------------------------------------------------------
# Real/synthetic label semantics
# ---------------------------------------------------------------------------


class TestRealSyntheticLabelSemantics:
    """Labels must say what is represented: NO_DATA when nothing was loaded,
    REAL_DATA only for data loaded through a real-source classification, and
    SYNTHETIC for fixture/synthetic content — fixture bytes pushed through
    the real ingestion machinery must never be labelled REAL_DATA."""

    def test_loaded_fixture_labeled_synthetic_not_real(self, tmp_path):
        """A validated load of SYNTHETIC TEST FIXTURE bytes is SYNTHETIC."""
        from services.ingestion.dem_real import ingest_dem

        tif = _write_dem_tif(tmp_path / "dem.tif")
        labels = ingest_dem(source_path=tif, config=_fixture_dem_config()).to_dict()["labels"]
        assert labels == ["VALIDATED", "FIXTURE", "SYNTHETIC"]
        assert "REAL_DATA" not in labels
        assert "NOT_FETCHED" not in labels

    @pytest.mark.parametrize(
        "classification,expected",
        [
            (DataSourceClassification.REAL, "REAL_DATA"),
            (DataSourceClassification.PROVISIONAL, "REAL_DATA"),
            (DataSourceClassification.APPROVED, "REAL_DATA"),
            (DataSourceClassification.SYNTHETIC, "SYNTHETIC"),
            (DataSourceClassification.SIMULATED, "SYNTHETIC"),
            (DataSourceClassification.FIXTURE, "SYNTHETIC"),
        ],
    )
    def test_loaded_data_label_by_classification(self, classification, expected):
        """Label rule: what is represented follows the governance
        classification of the loaded source (REAL_DATA claim only for
        real-source classifications)."""
        from services.ingestion.real_data import result_labels

        labels = result_labels(DataIngestionStatus.VALIDATED, classification)
        assert labels == ["VALIDATED", classification.value, expected]

    def test_not_loaded_is_no_data_for_every_classification(self):
        from services.ingestion.real_data import result_labels

        for classification in DataSourceClassification:
            labels = result_labels(DataIngestionStatus.NOT_FETCHED, classification)
            assert labels == ["NOT_FETCHED", classification.value, "NO_DATA"]
            labels = result_labels(DataIngestionStatus.BLOCKED, classification)
            assert labels == ["BLOCKED", classification.value, "NO_DATA"]

    def test_blocked_result_labeled_no_data(self, tmp_path):
        from services.ingestion.dem_real import ingest_dem

        bad = write_not_a_geotiff(tmp_path / "bad.tif")
        labels = ingest_dem(source_path=bad).to_dict()["labels"]
        assert "SYNTHETIC" not in labels
        assert "REAL_DATA" not in labels
        assert "NO_DATA" in labels
        assert "BLOCKED" in labels


# ---------------------------------------------------------------------------
# Synthetic/real separation
# ---------------------------------------------------------------------------


class TestSyntheticRealSeparation:
    """Synthetic and real data must never be visually or semantically confused."""

    def test_classification_enum_complete(self):
        """All required classifications exist."""
        assert DataSourceClassification.SYNTHETIC.value == "SYNTHETIC"
        assert DataSourceClassification.SIMULATED.value == "SIMULATED"
        assert DataSourceClassification.FIXTURE.value == "FIXTURE"
        assert DataSourceClassification.REAL.value == "REAL"
        assert DataSourceClassification.PROVISIONAL.value == "PROVISIONAL"
        assert DataSourceClassification.APPROVED.value == "APPROVED"

    def test_not_fetched_classified_distinctly(self):
        """NOT_FETCHED data must be classified distinctly from APPROVED."""
        from services.ingestion.dem_real import ingest_dem
        result = ingest_dem(source_path=None)
        assert result.provenance.classification != DataSourceClassification.APPROVED
        assert result.provenance.classification == DataSourceClassification.PROVISIONAL

    def test_synthetic_fixture_not_deleted(self):
        """The synthetic DEM fixture must remain available."""
        from services.ingestion.dem import synthetic_dem
        dem = synthetic_dem()
        assert dem is not None
        assert dem.shape == (134, 134)

    def test_synthetic_drainage_fixture_not_deleted(self):
        """The synthetic drainage fixture must remain available."""
        inp = Path("data/demo/drainage_synthetic_m4.inp")
        assert inp.exists()


# ---------------------------------------------------------------------------
# No operational claims
# ---------------------------------------------------------------------------


class TestNoOperationalClaims:
    """M10 must not introduce operational forecasting/safety claims."""

    def test_dem_result_not_operational(self):
        from services.ingestion.dem_real import ingest_dem
        result = ingest_dem(source_path=None)
        d = result.to_dict()
        assert "operational" not in str(d).lower()
        assert "forecast" not in str(d["status"]).lower()

    def test_drainage_result_not_operational(self):
        from services.ingestion.drainage_real import audit_wb_amrut_drains
        result = audit_wb_amrut_drains(source_path=None)
        d = result.to_dict()
        assert "operational" not in str(d).lower()
        assert "forecast" not in str(d["status"]).lower()


# ---------------------------------------------------------------------------
# Rejection of invalid data
# ---------------------------------------------------------------------------


class TestRejectionOfInvalidData:
    """Invalid data must be rejected, not silently accepted."""

    def test_invalid_crs_rejected(self):
        assert validate_crs("invalid-crs-string") is False

    def test_missing_source_returns_not_fetched(self):
        from services.ingestion.dem_real import ingest_dem
        result = ingest_dem(source_path=None)
        assert result.status == DataIngestionStatus.NOT_FETCHED
        assert result.source_fingerprint == ""

    def test_attribute_availability_never_fabricated(self):
        """AttributeAvailability must reflect the actual source data."""
        audit = AttributeAudit(
            name="diameter",
            dtype="float64",
            availability=AttributeAvailability.MISSING,
            null_rate=1.0,
        )
        assert audit.availability == AttributeAvailability.MISSING
        assert audit.null_rate == 1.0

    def test_dataset_audit_serialization(self):
        """DatasetAuditResult must serialize cleanly."""
        audit = DatasetAuditResult(
            source=WB_AMRUT_SOURCE,
            file_identity="test-file.parquet",
            file_size_bytes=15800000,
            record_count=0,
            geometry_type="LineString",
            crs_valid=True,
            coordinate_units="degrees",
            attributes=(),
            blockers=("CDN blocked",),
        )
        d = audit.to_dict()
        assert d["source"]["dataset_name"] == "WB_AMRUT_Stormwater"
        assert d["blockers"] == ["CDN blocked"]
        json_str = json.dumps(d)
        assert len(json_str) > 0


# ---------------------------------------------------------------------------
# DEM validation gates (resolution/nodata/finite/dimensions validated from
# the actual raster metadata, never assumed from the dataset name)
# ---------------------------------------------------------------------------


class TestDEMValidationGates:
    """ingest_dem must validate the actual artifact, not the source label."""

    def test_invalid_file_rejected(self, tmp_path):
        from services.ingestion.dem_real import ingest_dem

        result = ingest_dem(write_not_a_geotiff(tmp_path / "bad.tif"), _fixture_dem_config())
        assert result.status == DataIngestionStatus.BLOCKED
        assert result.validation_errors
        assert "failed to read" in result.validation_errors[0].lower()

    def test_missing_crs_rejected(self, tmp_path):
        import rasterio
        from affine import Affine

        from services.ingestion.dem_real import ingest_dem

        path = tmp_path / "nocrs.tif"
        with rasterio.open(
            path, "w", driver="GTiff", width=60, height=60, count=1, dtype="int16",
            crs=None, nodata=-32768.0, transform=Affine(1 / 3600, 0, 85.0, 0, -1 / 3600, 22.7),
        ) as dst:
            dst.write(np.full((60, 60), 100, dtype="int16"), 1)
        result = ingest_dem(path, _fixture_dem_config())
        assert result.status == DataIngestionStatus.BLOCKED
        assert any("crs" in e.lower() for e in result.validation_errors)

    def test_resolution_validated_from_transform_not_name(self, tmp_path):
        """A ~90 m raster must fail the ~30 m gate even if named GLO-30."""
        import rasterio
        from affine import Affine

        from services.ingestion.dem_real import ingest_dem

        path = tmp_path / "Copernicus_DSM_GLO30_lookalike.tif"
        cell = 3.0 / 3600.0  # ~90 m
        with rasterio.open(
            path, "w", driver="GTiff", width=40, height=40, count=1, dtype="int16",
            crs="EPSG:4326", nodata=-32768.0, transform=Affine(cell, 0, 85.0, 0, -cell, 22.7),
        ) as dst:
            dst.write(np.full((40, 40), 100, dtype="int16"), 1)
        result = ingest_dem(path, _fixture_dem_config())
        assert result.status == DataIngestionStatus.BLOCKED
        assert any("resolution" in e.lower() for e in result.validation_errors)

    def test_nodata_mismatch_warns_but_does_not_block(self, tmp_path):
        import rasterio
        from affine import Affine

        from services.ingestion.dem_real import DEMIngestionConfig, ingest_dem

        path = tmp_path / "othernodata.tif"
        cell = 1 / 3600.0
        with rasterio.open(
            path, "w", driver="GTiff", width=60, height=60, count=1, dtype="int16",
            crs="EPSG:4326", nodata=-9999.0, transform=Affine(cell, 0, 85.0, 0, -cell, 22.7),
        ) as dst:
            dst.write(np.full((60, 60), 100, dtype="int16"), 1)
        cfg = DEMIngestionConfig(source=FIXTURE_DEM_SOURCE)
        result = ingest_dem(path, cfg)
        assert result.status == DataIngestionStatus.VALIDATED
        assert any("nodata mismatch" in w for w in result.validation_warnings)

    def test_nonfinite_values_rejected(self, tmp_path):
        from services.ingestion.dem_real import ingest_dem

        result = ingest_dem(write_nan_dem_fixture(tmp_path / "nan.tif"), _fixture_dem_config())
        assert result.status == DataIngestionStatus.BLOCKED
        assert any("non-finite" in e.lower() for e in result.validation_errors)

    def test_all_nodata_raster_rejected(self, tmp_path):
        import rasterio
        from affine import Affine

        from services.ingestion.dem_real import ingest_dem

        path = tmp_path / "empty.tif"
        cell = 1 / 3600.0
        with rasterio.open(
            path, "w", driver="GTiff", width=60, height=60, count=1, dtype="int16",
            crs="EPSG:4326", nodata=-32768.0, transform=Affine(cell, 0, 85.0, 0, -cell, 22.7),
        ) as dst:
            dst.write(np.full((60, 60), -32768, dtype="int16"), 1)
        result = ingest_dem(path, _fixture_dem_config())
        assert result.status == DataIngestionStatus.BLOCKED
        assert any("no valid" in e.lower() for e in result.validation_errors)

    def test_tiny_raster_rejected(self, tmp_path):
        import rasterio
        from affine import Affine

        from services.ingestion.dem_real import ingest_dem

        path = tmp_path / "tiny.tif"
        cell = 1 / 3600.0
        with rasterio.open(
            path, "w", driver="GTiff", width=1, height=1, count=1, dtype="int16",
            crs="EPSG:4326", nodata=-32768.0, transform=Affine(cell, 0, 85.0, 0, -cell, 22.7),
        ) as dst:
            dst.write(np.array([[100]], dtype="int16"), 1)
        result = ingest_dem(path, _fixture_dem_config())
        assert result.status == DataIngestionStatus.BLOCKED
        assert any("too small" in e.lower() for e in result.validation_errors)

    def test_output_resolution_reported_in_metres(self, tmp_path):
        """A 4326 raster's resolution must be reported in metres, not degrees."""
        from services.ingestion.dem_real import ingest_dem

        result = ingest_dem(_write_dem_tif(tmp_path / "dem.tif"), _fixture_dem_config())
        assert result.status == DataIngestionStatus.VALIDATED
        assert 20.0 < result.output_resolution_m < 40.0


# ---------------------------------------------------------------------------
# DEM normalization (clip → reproject → bilinear → GridSpec alignment)
# ---------------------------------------------------------------------------


class TestDEMNormalization:
    """normalize_dem adapts validated real data TO the pilot GridSpec."""

    def test_not_fetched_passthrough(self, tmp_path):
        from services.ingestion.dem_real import normalize_dem

        result = normalize_dem(None, _fixture_dem_config())
        assert result.status == DataIngestionStatus.NOT_FETCHED
        assert result.elevation is None and result.grid is None
        assert result.labels == ["NOT_FETCHED", "FIXTURE", "NO_DATA"]

    def test_invalid_source_never_normalized(self, tmp_path):
        from services.ingestion.dem_real import normalize_dem

        result = normalize_dem(write_not_a_geotiff(tmp_path / "bad.tif"), _fixture_dem_config())
        assert result.status == DataIngestionStatus.BLOCKED
        assert result.elevation is None
        assert any("VALIDATED source" in e for e in result.validation_errors)

    def test_no_spatial_overlap_blocked(self, tmp_path):
        from services.ingestion.dem_real import normalize_dem

        far = write_dem_fixture_no_overlap(tmp_path / "far.tif")
        result = normalize_dem(far, _fixture_dem_config())
        assert result.status == DataIngestionStatus.BLOCKED
        assert any("overlap" in e.lower() for e in result.validation_errors)

    def test_normalized_output_aligns_to_pilot_gridspec(self, tmp_path):
        from services.ingestion.dem_real import normalize_dem, pilot_grid_spec

        dem = write_dem_fixture(tmp_path / "pilot_dem.tif")
        result = normalize_dem(dem, _fixture_dem_config())
        assert result.status == DataIngestionStatus.NORMALIZED
        assert result.grid is not None
        pilot = pilot_grid_spec()
        assert result.grid == pilot  # exact established grid, not a new one
        assert result.elevation.shape == (pilot.height, pilot.width)
        a, b, c, d, e, f = result.grid.affine_transform
        # Verify against the authoritative pilot grid (not hard-coded legacy values)
        assert (a, b, c, d, e, f) == tuple(pilot.affine_transform)
        assert result.grid.crs_wkt_or_epsg == "EPSG:32645"

    def test_normalized_elevation_values_plausible(self, tmp_path):
        from services.ingestion.dem_real import normalize_dem

        dem = write_dem_fixture(tmp_path / "pilot_dem.tif")
        result = normalize_dem(dem, _fixture_dem_config())
        valid = result.elevation[result.elevation != result.nodata]
        assert valid.size > 0
        assert np.all(np.isfinite(valid))
        # Fixture plane spans ~88–112 m (normalized coordinates); bilinear
        # warp must stay close regardless of pilot grid dimensions.
        assert 80.0 < float(valid.min()) < float(valid.max()) < 120.0

    def test_nodata_preserved_not_filled_with_zero(self, tmp_path):
        from services.ingestion.dem_real import normalize_dem

        dem = write_dem_fixture(tmp_path / "pilot_dem.tif")
        result = normalize_dem(dem, _fixture_dem_config())
        assert result.nodata_cells > 0
        nodata_mask = result.elevation == result.nodata
        assert nodata_mask.sum() == result.nodata_cells
        assert not np.any(result.elevation[nodata_mask] == 0.0)
        assert "no filling or interpolation applied" in " ".join(
            result.provenance.known_limitations
        )

    def test_deterministic_output_and_processing_fingerprint(self, tmp_path):
        from services.ingestion.dem_real import normalize_dem

        dem = write_dem_fixture(tmp_path / "pilot_dem.tif")
        r1 = normalize_dem(dem, _fixture_dem_config())
        r2 = normalize_dem(dem, _fixture_dem_config())
        assert np.array_equal(r1.elevation, r2.elevation)
        assert r1.processing_fingerprint == r2.processing_fingerprint
        assert len(r1.processing_fingerprint) == 64
        assert r1.processing_fingerprint != r1.source_fingerprint

    def test_processing_fingerprint_tracks_config(self, tmp_path):
        """A different target grid must change the processing fingerprint."""
        from services.contracts import GridSpec
        from services.ingestion.dem_real import (
            REAL_PILOT_CELL_SIZE_M,
            REAL_PILOT_ORIGIN_X,
            REAL_PILOT_ORIGIN_Y,
            DEMIngestionConfig,
            normalize_dem,
        )

        dem = write_dem_fixture(tmp_path / "pilot_dem.tif")
        # Shifted grid: 1 cell offset from the real pilot, same CRS and size
        shifted = GridSpec(
            grid_id="ufns_pilot_grid_shifted",
            crs_wkt_or_epsg="EPSG:32645",
            width=846,
            height=934,
            affine_transform=[30.0, 0.0, REAL_PILOT_ORIGIN_X + 30.0, 0.0, -30.0, REAL_PILOT_ORIGIN_Y - 30.0],
            cell_size_m=REAL_PILOT_CELL_SIZE_M,
            bounds=[REAL_PILOT_ORIGIN_X + 30.0, REAL_PILOT_ORIGIN_Y - 934 * 30.0 - 30.0,
                    REAL_PILOT_ORIGIN_X + 30.0 + 846 * 30.0, REAL_PILOT_ORIGIN_Y - 30.0],
        )
        r1 = normalize_dem(dem, _fixture_dem_config())
        r2 = normalize_dem(
            dem, DEMIngestionConfig(source=FIXTURE_DEM_SOURCE, target_grid=shifted)
        )
        assert r2.status == DataIngestionStatus.NORMALIZED
        assert r1.processing_fingerprint != r2.processing_fingerprint

    def test_resampling_policy_is_bilinear_and_documented(self, tmp_path):
        from services.ingestion.dem_real import DEM_RESAMPLING, normalize_dem

        result = normalize_dem(write_dem_fixture(tmp_path / "d.tif"), _fixture_dem_config())
        assert result.resampling == DEM_RESAMPLING == "bilinear"
        assert "bilinear" in " ".join(result.provenance.known_limitations)

    def test_invalid_target_grid_blocked(self, tmp_path):
        from services.contracts import GridSpec
        from services.ingestion.dem_real import DEMIngestionConfig, normalize_dem

        geographic = GridSpec(
            grid_id="bad",
            crs_wkt_or_epsg="EPSG:4326",  # geographic: not a metric sim grid
            width=10, height=10,
            affine_transform=[0.001, 0.0, 85.0, 0.0, -0.001, 22.7],
            cell_size_m=0.001,
            bounds=[85.0, 22.69, 85.01, 22.7],
        )
        result = normalize_dem(
            write_dem_fixture(tmp_path / "d.tif"),
            DEMIngestionConfig(source=FIXTURE_DEM_SOURCE, target_grid=geographic),
        )
        assert result.status == DataIngestionStatus.BLOCKED
        assert any("projected metric" in e for e in result.validation_errors)

    def test_normalized_provenance_describes_processing(self, tmp_path):
        from services.ingestion.dem_real import normalize_dem, pilot_grid_spec

        dem = write_dem_fixture(tmp_path / "pilot_dem.tif")
        result = normalize_dem(dem, _fixture_dem_config())
        p = result.provenance
        assert p.validation_status == "VALIDATED"
        assert p.processing_fingerprint == result.processing_fingerprint
        assert p.data_fingerprint == compute_data_fingerprint(dem)
        grid_id = pilot_grid_spec().grid_id
        assert p.resolution == f"30 m on {grid_id}"
        limitations = " ".join(p.known_limitations)
        assert "resampled" in limitations
        assert "NOT_FETCHED" not in limitations  # no stale template limitations
        assert p.acquisition_timestamp.tzinfo is not None

    def test_normalized_labels_synthetic_for_fixture(self, tmp_path):
        from services.ingestion.dem_real import normalize_dem

        result = normalize_dem(write_dem_fixture(tmp_path / "d.tif"), _fixture_dem_config())
        assert result.labels == ["NORMALIZED", "FIXTURE", "SYNTHETIC"]

    def test_gridspec_serializable_through_pydantic(self, tmp_path):
        from services.ingestion.dem_real import normalize_dem, pilot_grid_spec

        result = normalize_dem(write_dem_fixture(tmp_path / "d.tif"), _fixture_dem_config())
        d = result.to_dict()
        assert d["grid"]["crs_wkt_or_epsg"] == "EPSG:32645"
        assert d["grid"]["width"] == pilot_grid_spec().width
        assert d["grid"]["height"] == pilot_grid_spec().height
        json.dumps(d)  # fully serializable


# ---------------------------------------------------------------------------
# Drainage audit (schema/geometry/CRS/duplicates/extent)
# ---------------------------------------------------------------------------


class TestDrainageAudit:
    """audit_wb_amrut_drains on clearly-labelled SYNTHETIC TEST FIXTUREs."""

    def test_unreadable_parquet_blocked(self, tmp_path):
        from services.ingestion.drainage_real import audit_wb_amrut_drains

        result = audit_wb_amrut_drains(write_not_a_parquet(tmp_path / "bad.parquet"))
        assert result.status == DataIngestionStatus.BLOCKED
        assert any("parquet" in b.lower() for b in result.blockers)

    def test_valid_fixture_audited_and_validated(self, tmp_path):
        from services.ingestion.drainage_real import audit_wb_amrut_drains

        pq = write_drainage_fixture(tmp_path / "drains.parquet")
        result = audit_wb_amrut_drains(pq)
        assert result.status == DataIngestionStatus.VALIDATED
        assert result.crs_valid is True
        assert result.record_count == 4
        assert result.audit.geometry_type == "LineString"
        assert result.audit.duplicate_count == 0
        assert result.audit.invalid_geometry_count == 0
        assert result.unsupported_geometry_count == 0
        assert result.audit.record_count == 4
        assert result.schema_fingerprint

    def test_observed_schema_captured_with_null_rates(self, tmp_path):
        from services.ingestion.drainage_real import audit_wb_amrut_drains

        pq = write_drainage_fixture(tmp_path / "drains.parquet")
        audit = audit_wb_amrut_drains(pq).schema_audit
        names = [c.name for c in audit.observed_columns]
        assert {"id", "name", "type", "diameter_mm", "manning_n", "geometry"} <= set(names)
        diameter = next(c for c in audit.observed_columns if c.name == "diameter_mm")
        assert diameter.null_rate == pytest.approx(1 / 4)

    def test_required_attribute_classification_separation(self, tmp_path):
        """accepted / missing / rejected / unresolved are explicitly separated."""
        from services.ingestion.drainage_real import audit_wb_amrut_drains

        pq = write_drainage_fixture(tmp_path / "amb.parquet", variant="ambiguous_units")
        audit = audit_wb_amrut_drains(pq).schema_audit
        assert any("diameter_mm" not in a and "diameter" in a for a in audit.accepted_attributes) is False
        assert any("satisfies diameter_m" in a for a in audit.accepted_attributes) is False
        assert any(a.startswith("diameter") for a in audit.unresolved_attributes)
        assert any(a.startswith("roughness") for a in audit.unresolved_attributes)
        assert any(a.startswith("invert_level_m") for a in audit.unresolved_attributes)
        assert any(a.startswith("capacity_m3s") for a in audit.missing_attributes)

    def test_non_numeric_hydraulic_column_rejected(self, tmp_path):
        from services.ingestion.drainage_real import audit_wb_amrut_drains

        pq = write_drainage_fixture(tmp_path / "strdiam.parquet", variant="non_numeric_diameter")
        result = audit_wb_amrut_drains(pq)
        assert result.status == DataIngestionStatus.VALIDATED
        assert any("non-numeric" in r for r in result.schema_audit.rejected_attributes)

    def test_duplicate_ids_detected(self, tmp_path):
        from services.ingestion.drainage_real import audit_wb_amrut_drains

        pq = write_drainage_fixture(tmp_path / "dup.parquet", variant="duplicate_ids")
        result = audit_wb_amrut_drains(pq)
        assert result.status == DataIngestionStatus.VALIDATED
        assert result.audit.duplicate_count == 1

    def test_invalid_geometry_counted(self, tmp_path):
        from services.ingestion.drainage_real import audit_wb_amrut_drains

        pq = write_drainage_fixture(tmp_path / "invalid.parquet", variant="invalid_geometry")
        result = audit_wb_amrut_drains(pq)
        assert result.status == DataIngestionStatus.VALIDATED
        assert result.audit.invalid_geometry_count == 2  # unparseable + null

    def test_unsupported_geometry_counted(self, tmp_path):
        from services.ingestion.drainage_real import audit_wb_amrut_drains

        pq = write_drainage_fixture(tmp_path / "pts.parquet", variant="unsupported_geometry")
        result = audit_wb_amrut_drains(pq)
        assert result.status == DataIngestionStatus.VALIDATED
        assert result.unsupported_geometry_count == 2
        assert result.audit.geometry_type == "Point"

    def test_missing_crs_is_audit_partial_not_validated(self, tmp_path):
        from services.ingestion.drainage_real import audit_wb_amrut_drains

        pq = write_drainage_fixture(tmp_path / "nocrs.parquet", crs=False)
        result = audit_wb_amrut_drains(pq)
        assert result.status == DataIngestionStatus.AUDIT_PARTIAL
        assert result.crs_valid is False
        assert result.provenance.validation_status == "PARTIAL"
        assert any("B02" in lim for lim in result.provenance.known_limitations)

    def test_plain_parquet_audit_partial(self, tmp_path):
        """No geometry column: schema audit only — never VALIDATED."""
        from services.ingestion.drainage_real import audit_wb_amrut_drains

        result = audit_wb_amrut_drains(_write_drainage_parquet(tmp_path / "plain.parquet"))
        assert result.status == DataIngestionStatus.AUDIT_PARTIAL
        assert result.audit is not None
        assert any("geometry" in g.lower() for g in result.audit.known_gaps)
        assert result.spatial_coverage is None

    def test_spatial_extent_reported(self, tmp_path):
        from services.ingestion.drainage_real import audit_wb_amrut_drains

        pq = write_drainage_fixture(tmp_path / "drains.parquet")
        result = audit_wb_amrut_drains(pq)
        cov = result.spatial_coverage
        assert cov is not None
        # Fixture drainage are in the real-pilot area (88.68–88.71°E, 22.70–22.73°N)
        assert 88.6 < cov.west < cov.east < 88.9
        assert 22.6 < cov.south < cov.north < 22.9

    def test_missing_hydraulics_reported_not_invented(self, tmp_path):
        from services.ingestion.drainage_real import audit_wb_amrut_drains

        pq = write_drainage_fixture(tmp_path / "nohyd.parquet", variant="missing_hydraulics")
        result = audit_wb_amrut_drains(pq)
        assert result.status == DataIngestionStatus.VALIDATED  # source audit OK
        missing = " ".join(result.missing_hydraulic_parameters)
        assert "diameter_m" in missing and "MISSING" in missing
        assert "manning_n" in missing and "capacity_m3s" in missing

    def test_audit_report_serializes(self, tmp_path):
        from services.ingestion.drainage_real import audit_wb_amrut_drains

        pq = write_drainage_fixture(tmp_path / "drains.parquet")
        d = audit_wb_amrut_drains(pq).to_dict()
        assert d["audit"]["geometry_type"] == "LineString"
        assert d["schema_audit"]["observed_columns"]
        assert d["schema_audit"]["hydraulic_findings"]
        json.dumps(d)

    def test_fetched_audit_provenance_carries_observed_state(self, tmp_path):
        from services.ingestion.drainage_real import audit_wb_amrut_drains

        pq = write_drainage_fixture(tmp_path / "drains.parquet")
        now = datetime.now(timezone.utc)
        result = audit_wb_amrut_drains(pq)
        p = result.provenance
        assert p.data_fingerprint == compute_data_fingerprint(pq)
        assert len(p.schema_fingerprint) == 64
        assert p.validation_status == "VALIDATED"
        assert abs((p.acquisition_timestamp - now).total_seconds()) < 300
        assert not any("NOT_FETCHED" in lim for lim in p.known_limitations)


# ---------------------------------------------------------------------------
# Drainage entity mapping
# ---------------------------------------------------------------------------


class TestDrainageMapping:
    """map_drainage_entities: explicit rules, stable IDs, no fabrication."""

    def test_valid_fixture_maps_entities(self, tmp_path):
        from services.ingestion.drainage_real import map_drainage_entities

        pq = write_drainage_fixture(tmp_path / "drains.parquet")
        result = map_drainage_entities(pq, _fixture_mapping_config())
        assert result.status == DataIngestionStatus.NORMALIZED
        assert result.mapped_count == 4
        assert result.rejected_count == 0
        assert result.labels == ["NORMALIZED", "FIXTURE", "SYNTHETIC"]

    def test_source_id_and_type_preserved(self, tmp_path):
        from services.ingestion.drainage_real import map_drainage_entities

        pq = write_drainage_fixture(tmp_path / "drains.parquet")
        entities = map_drainage_entities(pq, _fixture_mapping_config()).entities
        by_id = {e.source_id: e for e in entities}
        assert set(by_id) == {"d1", "d2", "d3", "d4"}
        assert by_id["d1"].source_type == "drain"
        assert by_id["d2"].feature_type.value == "PIPE"

    def test_stable_entity_ids_deterministic(self, tmp_path):
        from services.ingestion.drainage_real import map_drainage_entities

        pq = write_drainage_fixture(tmp_path / "drains.parquet")
        ids_a = [e.feature_id for e in map_drainage_entities(pq, _fixture_mapping_config()).entities]
        ids_b = [e.feature_id for e in map_drainage_entities(pq, _fixture_mapping_config()).entities]
        assert ids_a == ids_b
        assert all(i.startswith("ufns-") and len(i) == 21 for i in ids_a)
        assert len(set(ids_a)) == len(ids_a)

    def test_geometry_wkt_roundtrip(self, tmp_path):
        from shapely import from_wkt

        from services.ingestion.drainage_real import map_drainage_entities

        pq = write_drainage_fixture(tmp_path / "drains.parquet")
        entities = map_drainage_entities(pq, _fixture_mapping_config()).entities
        for entity in entities:
            geom = from_wkt(entity.geometry_wkt)
            assert geom.geom_type == "LineString"
            assert geom.is_valid
            assert geom.length > 0

    def test_unknown_type_not_guessed(self, tmp_path):
        from services.ingestion.drainage_real import (
            DrainageFeatureType,
            EntityMappingStatus,
            map_drainage_entities,
        )

        pq = write_drainage_fixture(tmp_path / "unknown.parquet", variant="unknown_types")
        result = map_drainage_entities(pq, _fixture_mapping_config())
        assert result.unresolved_count == 2
        assert result.mapped_count == 1
        unresolved = [e for e in result.entities if e.mapping_status == EntityMappingStatus.UNRESOLVED_TYPE]
        assert all(e.feature_type == DrainageFeatureType.UNKNOWN for e in unresolved)
        assert "not guessed" in unresolved[0].mapping_reason
        assert set(result.unresolved_source_types) == {"mystery feature", "<empty type>"}

    def test_unsupported_geometry_rejected(self, tmp_path):
        from services.ingestion.drainage_real import (
            EntityMappingStatus,
            map_drainage_entities,
        )

        pq = write_drainage_fixture(tmp_path / "pts.parquet", variant="unsupported_geometry")
        result = map_drainage_entities(pq, _fixture_mapping_config())
        assert result.entities == ()
        assert result.rejected_count == 2
        assert all(
            r.status == EntityMappingStatus.REJECTED_UNSUPPORTED_GEOMETRY for r in result.rejections
        )
        assert "Point" in result.rejections[0].detail

    def test_invalid_geometry_rejected(self, tmp_path):
        from services.ingestion.drainage_real import (
            EntityMappingStatus,
            map_drainage_entities,
        )

        pq = write_drainage_fixture(tmp_path / "invalid.parquet", variant="invalid_geometry")
        result = map_drainage_entities(pq, _fixture_mapping_config())
        assert result.mapped_count == 1
        assert result.rejected_count == 2
        statuses = {r.status for r in result.rejections}
        assert statuses == {
            EntityMappingStatus.REJECTED_MISSING_GEOMETRY,
            EntityMappingStatus.REJECTED_INVALID_GEOMETRY,
        }

    def test_duplicate_ids_rejected(self, tmp_path):
        from services.ingestion.drainage_real import (
            EntityMappingStatus,
            map_drainage_entities,
        )

        pq = write_drainage_fixture(tmp_path / "dup.parquet", variant="duplicate_ids")
        result = map_drainage_entities(pq, _fixture_mapping_config())
        assert result.mapped_count == 2
        assert result.rejected_count == 1
        assert result.rejections[0].status == EntityMappingStatus.REJECTED_DUPLICATE

    def test_no_fabricated_hydraulic_attributes(self, tmp_path):
        from services.ingestion.drainage_real import (
            AttributeAvailability,
            map_drainage_entities,
        )

        pq = write_drainage_fixture(tmp_path / "nohyd.parquet", variant="missing_hydraulics")
        result = map_drainage_entities(pq, _fixture_mapping_config())
        assert result.status == DataIngestionStatus.NORMALIZED
        for entity in result.entities:
            assert entity.diameter_m is None
            assert entity.invert_upstream_m is None
            assert entity.invert_downstream_m is None
            assert entity.manning_n is None
            assert entity.capacity_m3s is None
            assert all(
                getattr(entity, f"{p}_availability") == AttributeAvailability.MISSING
                or getattr(entity, f"{p}_availability") == AttributeAvailability.UNKNOWN
                for p in ("diameter", "invert_upstream", "invert_downstream", "manning_n", "capacity")
            )
        assert result.missing_hydraulic_parameters

    def test_hydraulic_extraction_with_documented_derivation(self, tmp_path):
        from services.ingestion.drainage_real import (
            AttributeAvailability,
            map_drainage_entities,
        )

        pq = write_drainage_fixture(tmp_path / "drains.parquet")
        entities = {
            e.source_id: e for e in map_drainage_entities(pq, _fixture_mapping_config()).entities
        }
        assert entities["d1"].diameter_m == pytest.approx(0.3)
        assert entities["d1"].diameter_availability == AttributeAvailability.DERIVED
        assert "mm→m" in entities["d1"].mapping_reason
        # d3 has a null diameter_mm: column present, value absent
        assert entities["d3"].diameter_m is None
        assert entities["d3"].diameter_availability == AttributeAvailability.MISSING
        assert entities["d1"].manning_n == pytest.approx(0.013)
        assert entities["d1"].manning_n_availability == AttributeAvailability.PRESENT

    def test_ambiguous_columns_not_mapped_to_hydraulics(self, tmp_path):
        """'diameter'/'roughness'/'invert_level_m' stay in attributes, never guessed."""
        from services.ingestion.drainage_real import (
            AttributeAvailability,
            map_drainage_entities,
        )

        pq = write_drainage_fixture(tmp_path / "amb.parquet", variant="ambiguous_units")
        result = map_drainage_entities(pq, _fixture_mapping_config())
        entity = result.entities[0]
        assert entity.diameter_m is None
        assert entity.diameter_availability == AttributeAvailability.UNKNOWN
        assert entity.manning_n is None
        assert entity.attributes["diameter"] == 300.0  # preserved verbatim
        assert entity.attributes["invert_level_m"] == 100.5

    def test_mapping_requires_validated_source(self, tmp_path):
        from services.ingestion.drainage_real import map_drainage_entities

        plain = map_drainage_entities(
            _write_drainage_parquet(tmp_path / "plain.parquet"), _fixture_mapping_config()
        )
        assert plain.status == DataIngestionStatus.BLOCKED
        assert plain.entities == ()
        assert any("VALIDATED" in b for b in plain.blockers)

        nocrs = map_drainage_entities(
            write_drainage_fixture(tmp_path / "nocrs.parquet", crs=False),
            _fixture_mapping_config(),
        )
        assert nocrs.status == DataIngestionStatus.BLOCKED
        assert nocrs.entities == ()

    def test_mapping_not_fetched_passthrough(self):
        from services.ingestion.drainage_real import map_drainage_entities

        result = map_drainage_entities(None)
        assert result.status == DataIngestionStatus.NOT_FETCHED
        assert result.entities == ()
        assert result.labels == ["NOT_FETCHED", "PROVISIONAL", "NO_DATA"]

    def test_mapping_deterministic_processing_fingerprint(self, tmp_path):
        from services.ingestion.drainage_real import map_drainage_entities

        pq = write_drainage_fixture(tmp_path / "drains.parquet")
        r1 = map_drainage_entities(pq, _fixture_mapping_config())
        r2 = map_drainage_entities(pq, _fixture_mapping_config())
        assert r1.processing_fingerprint == r2.processing_fingerprint
        assert len(r1.processing_fingerprint) == 64
        assert r1.processing_fingerprint != r1.source_fingerprint

    def test_mapping_provenance_describes_result(self, tmp_path):
        from services.ingestion.drainage_real import map_drainage_entities

        pq = write_drainage_fixture(tmp_path / "drains.parquet")
        result = map_drainage_entities(pq, _fixture_mapping_config())
        p = result.provenance
        assert p.validation_status == "VALIDATED"
        assert p.processing_fingerprint == result.processing_fingerprint
        assert p.data_fingerprint == compute_data_fingerprint(pq)
        limitations = " ".join(p.known_limitations)
        assert "domain/grid alignment not yet applied" in limitations
        assert "NOT_FETCHED" not in limitations

    def test_entity_attributes_immutable_and_serializable(self, tmp_path):
        from services.ingestion.drainage_real import map_drainage_entities

        pq = write_drainage_fixture(tmp_path / "drains.parquet")
        entity = map_drainage_entities(pq, _fixture_mapping_config()).entities[0]
        with pytest.raises(TypeError):
            entity.attributes["injected"] = 1.0
        d = entity.to_dict()
        d["attributes"]["injected"] = 1.0
        assert "injected" not in entity.attributes
        json.dumps(entity.to_dict())

    def test_entity_ids_derived_from_geometry_without_id_column(self, tmp_path):
        from services.ingestion.drainage_real import map_drainage_entities

        pq = write_drainage_fixture(tmp_path / "noid.parquet", variant="no_id_column")
        result = map_drainage_entities(pq, _fixture_mapping_config())
        assert result.mapped_count == 2
        assert all("derived from geometry" in e.mapping_reason for e in result.entities)
        ids = [e.feature_id for e in result.entities]
        assert len(set(ids)) == 2


# ---------------------------------------------------------------------------
# Processing fingerprints
# ---------------------------------------------------------------------------


class TestProcessingFingerprint:
    def test_deterministic(self):
        from services.ingestion.real_data import compute_processing_fingerprint

        steps = ["a", "b"]
        params = {"grid": [30.0, 300000.0], "resampling": "bilinear", "nested": {"k": [1, 2]}}
        fp1 = compute_processing_fingerprint(steps, params)
        fp2 = compute_processing_fingerprint(steps, params)
        assert fp1 == fp2 and len(fp1) == 64

    def test_excludes_wall_clock(self):
        """Same content at different times must hash identically."""
        from services.ingestion.real_data import compute_processing_fingerprint

        fp1 = compute_processing_fingerprint(["s"], {"a": 1})
        fp2 = compute_processing_fingerprint(["s"], {"a": 1})
        assert fp1 == fp2

    def test_sensitive_to_steps_and_params(self):
        from services.ingestion.real_data import compute_processing_fingerprint

        base = compute_processing_fingerprint(["a"], {"x": 1})
        assert base != compute_processing_fingerprint(["a", "b"], {"x": 1})
        assert base != compute_processing_fingerprint(["a"], {"x": 2})

    def test_param_key_order_irrelevant(self):
        from services.ingestion.real_data import compute_processing_fingerprint

        a = compute_processing_fingerprint(["s"], {"x": 1, "y": 2})
        b = compute_processing_fingerprint(["s"], {"y": 2, "x": 1})
        assert a == b


# ---------------------------------------------------------------------------
# Acquisition evidence
# ---------------------------------------------------------------------------


class TestAcquisitionEvidence:
    def test_fetch_success_records_artifact_identity(self, tmp_path):
        from services.ingestion.acquisition import attempt_download
        from services.ingestion.provenance import sha256_file

        payload = b"deterministic-fixture-bytes"
        src = tmp_path / "src.bin"
        src.write_bytes(payload)
        attempt = attempt_download(
            source_name="fixture-src",
            url=src.as_uri(),
            dest=tmp_path / "out" / "fetched.bin",
            affected_gate="TEST-GATE",
            consequence="none",
        )
        assert attempt.outcome.value == "FETCHED"
        assert attempt.artifact_bytes == len(payload)
        assert attempt.artifact_sha256 == sha256_file(tmp_path / "out" / "fetched.bin")
        assert attempt.failure_mode == ""

    def test_unreachable_source_blocked_with_failure_mode(self, tmp_path):
        from services.ingestion.acquisition import attempt_download
        from services.ingestion.real_data import AcquisitionOutcome

        attempt = attempt_download(
            source_name="unreachable",
            url="https://receiver.invalid/never-resolves.bin",  # RFC 2606 TLD
            dest=tmp_path / "f.bin",
            affected_gate="TEST-GATE",
            consequence="gate stays blocked",
            timeout_s=5.0,
        )
        assert attempt.outcome == AcquisitionOutcome.BLOCKED
        assert attempt.failure_mode
        assert attempt.artifact_path is None
        assert attempt.artifact_sha256 is None
        assert attempt.consequence == "gate stays blocked"

    def test_failed_attempt_leaves_no_partial_artifact(self, tmp_path):
        from services.ingestion.acquisition import attempt_download

        dest = tmp_path / "f.bin"
        dest.write_bytes(b"stale bytes from an earlier attempt")
        attempt_download(
            source_name="unreachable",
            url="https://receiver.invalid/x.bin",
            dest=dest,
            affected_gate="G",
            consequence="c",
            timeout_s=5.0,
        )
        assert not dest.exists()

    def test_evidence_record_serializes(self):
        from services.ingestion.real_data import AcquisitionAttempt, AcquisitionOutcome

        attempt = AcquisitionAttempt(
            source_name="s",
            url="https://example.invalid/x",
            outcome=AcquisitionOutcome.BLOCKED,
            failure_mode="URLError: EOF",
            affected_gate="RD-01",
            consequence="stays NOT_FETCHED",
        )
        d = attempt.to_dict()
        assert d["outcome"] == "BLOCKED"
        assert d["affected_gate"] == "RD-01"
        assert d["attempted_at"]
        json.dumps(d)

    def test_wb_amrut_urls_are_the_documented_sources(self):
        from services.ingestion.acquisition import (
            COPERNICUS_DEM_STAC_URL,
            WB_AMRUT_DRAINS_URL,
        )

        assert WB_AMRUT_DRAINS_URL.startswith(
            "https://github.com/yashveeeeeeer/india-geodata/releases/download/"
        )
        assert WB_AMRUT_DRAINS_URL.endswith("WB_AMRUT_Stormwater_drains.parquet")
        assert COPERNICUS_DEM_STAC_URL.endswith("cop-dem-glo-30")


# ---------------------------------------------------------------------------
# Fixture classification / synthetic separation
# ---------------------------------------------------------------------------


class TestFixtureClassification:
    """Every M10 test fixture is classified FIXTURE and can never be REAL_DATA."""

    def test_fixture_classification_declared(self):
        from fixtures.m10 import generators

        assert generators.FIXTURE_CLASSIFICATION == DataSourceClassification.FIXTURE
        assert generators.FIXTURE_DEM_SOURCE.classification == DataSourceClassification.FIXTURE
        assert generators.FIXTURE_DRAINAGE_SOURCE.classification == DataSourceClassification.FIXTURE
        assert "SYNTHETIC" in generators.FIXTURE_DEM_SOURCE.source_name

    def test_fixture_pipeline_outputs_never_labeled_real(self, tmp_path):
        from services.ingestion.dem_real import normalize_dem

        dem = write_dem_fixture(tmp_path / "d.tif")
        ingest_labels = ingest_dem_fixture_labels(dem)
        norm_labels = normalize_dem(dem, _fixture_dem_config()).labels
        for labels in (ingest_labels, norm_labels):
            assert "REAL_DATA" not in labels
            assert "SYNTHETIC" in labels
            assert "FIXTURE" in labels

    def test_failed_real_ingestion_returns_no_data_never_synthetic(self, tmp_path):
        """A failed real-source ingestion must not surface synthetic data."""
        from services.ingestion.dem_real import ingest_dem
        from services.ingestion.drainage_real import map_drainage_entities

        dem = ingest_dem(write_not_a_geotiff(tmp_path / "x.tif"))
        assert dem.labels == ["BLOCKED", "PROVISIONAL", "NO_DATA"]
        assert dem.output_array is None
        drains = map_drainage_entities(write_not_a_parquet(tmp_path / "y.parquet"))
        assert drains.labels == ["BLOCKED", "PROVISIONAL", "NO_DATA"]
        assert drains.entities == ()


def ingest_dem_fixture_labels(dem: Path) -> list[str]:
    from services.ingestion.dem_real import ingest_dem

    return ingest_dem(dem, _fixture_dem_config()).labels


# ---------------------------------------------------------------------------
# Explicit failure-state labels across pipelines
# ---------------------------------------------------------------------------


class TestFailureStates:
    """NOT_FETCHED / BLOCKED / AUDIT_PARTIAL / VALIDATED / NORMALIZED labels."""

    def test_all_states_reachable_with_correct_labels(self, tmp_path):
        from services.ingestion.dem_real import ingest_dem, normalize_dem
        from services.ingestion.drainage_real import (
            audit_wb_amrut_drains,
            map_drainage_entities,
        )

        cases = [
            (ingest_dem(None), ["NOT_FETCHED", "PROVISIONAL", "NO_DATA"]),
            (ingest_dem(write_not_a_geotiff(tmp_path / "bad.tif")), ["BLOCKED", "PROVISIONAL", "NO_DATA"]),
            (audit_wb_amrut_drains(None), ["NOT_FETCHED", "PROVISIONAL", "NO_DATA"]),
            (audit_wb_amrut_drains(write_not_a_parquet(tmp_path / "bad.parquet")), ["BLOCKED", "PROVISIONAL", "NO_DATA"]),
            (audit_wb_amrut_drains(_write_drainage_parquet(tmp_path / "p.parquet")), ["AUDIT_PARTIAL", "PROVISIONAL", "REAL_DATA"]),
            (audit_wb_amrut_drains(write_drainage_fixture(tmp_path / "d.parquet")), ["VALIDATED", "PROVISIONAL", "REAL_DATA"]),
            (map_drainage_entities(None), ["NOT_FETCHED", "PROVISIONAL", "NO_DATA"]),
        ]
        for result, expected_labels in cases:
            assert result.labels == expected_labels, result.labels

        normalized = normalize_dem(write_dem_fixture(tmp_path / "d.tif"), _fixture_dem_config())
        assert normalized.labels == ["NORMALIZED", "FIXTURE", "SYNTHETIC"]

    def test_blocked_results_carry_explicit_errors(self, tmp_path):
        from services.ingestion.dem_real import ingest_dem
        from services.ingestion.drainage_real import audit_wb_amrut_drains

        assert ingest_dem(write_not_a_geotiff(tmp_path / "b.tif")).validation_errors
        assert audit_wb_amrut_drains(write_not_a_parquet(tmp_path / "b.parquet")).blockers


# ---------------------------------------------------------------------------
# Real-pilot artifact execution (2026-08-22)
#
# The human-supplied real artifacts live in the canonical raw-data location
# (data/raw/, kept out of Git by repository convention). When present, these
# tests pin the evidence-backed gate statuses produced by the existing M10
# machinery against the actual bytes — they are skipped (never weakened)
# when the artifacts are not available in the working tree.
# ---------------------------------------------------------------------------

REAL_RAW_DIR = Path("data/raw")
REAL_DEM = REAL_RAW_DIR / "bagjola_kolkata_glo30_dem.tif"
REAL_DRAINS = REAL_RAW_DIR / "WB_AMRUT_Stormwater_drains.parquet"
REAL_VENTS = REAL_RAW_DIR / "WB_AMRUT_Stormwater_vents.parquet"
ACQUISITION_EVIDENCE = REAL_RAW_DIR / "acquisition_attempts.json"

# Oracle identities of the real artifacts as acquired (SHA-256 of the
# original source bytes, verified byte-identical after placement in data/raw).
REAL_DEM_SHA256 = "8832ae955ec8b8dbdab5a9bc4047852c17f6343c598514bc6092c38717dcc96a"
REAL_DRAINS_SHA256 = "6b224492d4bd02aae1d282b76ac17ed774554ed4be91d300a07ebec3cb3d3a0b"
REAL_VENTS_SHA256 = "ef017b6fbcee48eb21c62427c7eea2f26c90a639132e7a970db020adc7f5ce37"
REAL_DEM_WEST = 88.6

require_real_artifacts = pytest.mark.skipif(
    not all(p.exists() for p in (REAL_DEM, REAL_DRAINS, REAL_VENTS)),
    reason="real pilot artifacts not present in data/raw (canonical raw location)",
)


@pytest.fixture(scope="module")
def real_drains_audit():
    from services.ingestion.drainage_real import audit_wb_amrut_drains

    return audit_wb_amrut_drains(REAL_DRAINS)


@pytest.fixture(scope="module")
def real_vents_audit():
    from services.ingestion.drainage_real import audit_wb_amrut_drains

    return audit_wb_amrut_drains(REAL_VENTS)


class TestRealPilotArtifactExecution:
    """The actual artifacts must produce the evidence-backed M10 statuses."""

    @require_real_artifacts
    def test_dem_real_validated_from_actual_raster_metadata(self):
        from services.ingestion.dem_real import ingest_dem

        result = ingest_dem(REAL_DEM)
        assert result.status == DataIngestionStatus.VALIDATED
        # Actual metadata, never the filename: 1 arc-second postings.
        assert result.output_crs == "EPSG:4326"
        assert 25.0 < result.output_resolution_m < 36.0
        assert result.output_bounds == (88.6, 22.65, 88.85, 22.9)
        assert result.output_array.shape == (900, 900)
        # The real tile carries no nodata sentinel — surfaced as a warning,
        # never silently substituted.
        assert result.output_nodata is None
        assert any("nodata" in w for w in result.validation_warnings)
        # Real source data is labelled REAL_DATA (governance: PROVISIONAL).
        assert result.labels == ["VALIDATED", "PROVISIONAL", "REAL_DATA"]
        assert result.source_fingerprint == REAL_DEM_SHA256

    @require_real_artifacts
    def test_dem_real_normalization_succeeds_on_authoritative_pilot_grid(self):
        """The real DEM normalizes successfully onto the authoritative pilot
        grid (re-based 2026-08-23 from the DEM tile itself)."""
        from services.ingestion.dem_real import normalize_dem, pilot_grid_spec

        result = normalize_dem(REAL_DEM)
        assert result.status == DataIngestionStatus.NORMALIZED
        assert result.elevation is not None
        grid = pilot_grid_spec()
        assert result.grid == grid
        assert result.elevation.shape == (grid.height, grid.width)
        assert result.processing_fingerprint != ""
        assert len(result.processing_fingerprint) == 64
        # Valid elevation where source data exists
        valid = result.elevation[result.elevation != result.nodata]
        assert valid.size > 0
        assert np.all(np.isfinite(valid))
        assert result.labels == ["NORMALIZED", "PROVISIONAL", "REAL_DATA"]

    @require_real_artifacts
    def test_pilot_grid_derived_from_real_dem_authoritative_extent(self):
        """The pilot GridSpec is derived from the real DEM tile (2026-08-23
        spatial re-baseline). It covers the DEM extent in EPSG:32645 at 30 m."""
        from rasterio.warp import transform_bounds

        from services.ingestion.dem_real import (
            REAL_PILOT_CELL_SIZE_M,
            REAL_PILOT_HEIGHT,
            REAL_PILOT_WIDTH,
            pilot_grid_spec,
        )

        grid = pilot_grid_spec()
        assert (grid.width, grid.height, grid.cell_size_m) == (
            REAL_PILOT_WIDTH, REAL_PILOT_HEIGHT, REAL_PILOT_CELL_SIZE_M
        )
        assert grid.crs_wkt_or_epsg == "EPSG:32645"
        # Grid bounds in WGS84 must overlap the real DEM
        wgs = transform_bounds(grid.crs_wkt_or_epsg, "EPSG:4326", *grid.bounds, densify_pts=21)
        dem_bounds = (88.6, 22.65, 88.85, 22.9)
        assert wgs[0] <= dem_bounds[0]  # grid west ≤ DEM west
        assert wgs[2] >= dem_bounds[2]  # grid east ≥ DEM east
        assert wgs[1] <= dem_bounds[1]  # grid south ≤ DEM south
        assert wgs[3] >= dem_bounds[3]  # grid north ≥ DEM north
        # The old synthetic grid (300000, 2500000) must NOT be the current pilot
        assert grid.bounds[0] != 300000.0 or grid.bounds[1] != 2500000.0

    @require_real_artifacts
    def test_drains_real_audit_partial_on_embedded_crs_gap(self, real_drains_audit):
        from services.ingestion.drainage_real import audit_wb_amrut_drains  # noqa: F401

        result = real_drains_audit
        assert result.status == DataIngestionStatus.AUDIT_PARTIAL
        assert result.crs_valid is False
        assert any("CRS" in g for g in result.audit.known_gaps)
        assert result.record_count == 90395
        assert result.audit.geometry_type == "MultiLineString"
        assert result.audit.duplicate_count == 100
        assert result.audit.invalid_geometry_count == 0
        assert result.unsupported_geometry_count == 0
        cov = result.spatial_coverage
        assert cov is not None
        assert 86.3 < cov.west < 86.4 and 88.8 < cov.east < 88.9
        assert 22.0 < cov.south < 22.1 and 26.7 < cov.north < 26.8
        assert result.labels == ["AUDIT_PARTIAL", "PROVISIONAL", "REAL_DATA"]
        assert result.source_fingerprint == REAL_DRAINS_SHA256

    @require_real_artifacts
    def test_drains_real_hydraulics_confirmed_absent_not_fabricated(self, real_drains_audit):
        missing = " ".join(real_drains_audit.missing_hydraulic_parameters)
        for param in ("diameter_m", "invert_upstream_m", "invert_downstream_m", "manning_n", "capacity_m3s"):
            assert param in missing
        assert missing.count("MISSING confirmed absent") == 5
        schema = real_drains_audit.schema_audit
        assert schema.accepted_attributes == ("id: identifier column",)
        assert any(a.startswith("type:") for a in schema.missing_attributes)
        assert schema.rejected_attributes == ()

    @require_real_artifacts
    def test_vents_real_audit_partial_multipoint(self, real_vents_audit):
        result = real_vents_audit
        assert result.status == DataIngestionStatus.AUDIT_PARTIAL
        assert result.crs_valid is False
        assert result.record_count == 9579
        assert result.audit.geometry_type == "MultiPoint"
        # MultiPoint is unsupported for the drain-LINE mapping contract:
        # counted, never silently coerced.
        assert result.unsupported_geometry_count == 9579
        assert result.source_fingerprint == REAL_VENTS_SHA256
        assert result.labels == ["AUDIT_PARTIAL", "PROVISIONAL", "REAL_DATA"]

    @require_real_artifacts
    def test_real_entity_mapping_blocked_by_validated_source_contract(self):
        from services.ingestion.drainage_real import map_drainage_entities

        for path in (REAL_DRAINS, REAL_VENTS):
            result = map_drainage_entities(path)
            assert result.status == DataIngestionStatus.BLOCKED
            assert result.entities == ()
            assert any("VALIDATED" in b for b in result.blockers)
            assert result.labels == ["BLOCKED", "PROVISIONAL", "NO_DATA"]

    @require_real_artifacts
    def test_real_audit_fingerprints_are_deterministic(self, real_drains_audit):
        from services.ingestion.drainage_real import audit_wb_amrut_drains

        again = audit_wb_amrut_drains(REAL_DRAINS)
        assert again.source_fingerprint == real_drains_audit.source_fingerprint
        assert again.schema_fingerprint == real_drains_audit.schema_fingerprint
        assert len(again.schema_fingerprint) == 64

    @require_real_artifacts
    def test_acquisition_evidence_records_artifact_identity_and_history(self):
        from services.ingestion.provenance import sha256_file

        doc = json.loads(ACQUISITION_EVIDENCE.read_text())
        attempts = doc["attempts"]
        by_path = {a["artifact_path"]: a for a in attempts if a["outcome"] == "FETCHED"}
        for path, expected_sha in (
            (str(REAL_DEM), REAL_DEM_SHA256),
            (str(REAL_DRAINS), REAL_DRAINS_SHA256),
            (str(REAL_VENTS), REAL_VENTS_SHA256),
        ):
            rec = by_path[path]
            assert rec["artifact_sha256"] == expected_sha
            assert rec["artifact_sha256"] == sha256_file(Path(path))
        # The previous in-sandbox BLOCKED attempts must be preserved, not
        # deleted: the B02 acquisition blocker is evidenced, then resolved.
        blocked = [a for a in attempts if a["outcome"] == "BLOCKED"]
        assert blocked and all(a["failure_mode"] for a in blocked)

    @require_real_artifacts
    def test_real_data_never_labeled_synthetic_and_fixtures_untouched(
        self, tmp_path, real_drains_audit, real_vents_audit
    ):
        for labels in (real_drains_audit.labels, real_vents_audit.labels):
            assert "SYNTHETIC" not in labels
            assert "REAL_DATA" in labels
        # Real data must live in data/raw, never inside tests/fixtures.
        assert not (Path("tests/fixtures") / REAL_DEM.name).exists()
        assert not (Path("tests/fixtures") / REAL_DRAINS.name).exists()
        # The synthetic fixture still flows through the machinery as SYNTHETIC.
        from services.ingestion.dem_real import ingest_dem

        fixture_labels = ingest_dem(
            write_dem_fixture(tmp_path / "scratch_fixture.tif"),
            _fixture_dem_config(),
        ).labels
        assert fixture_labels == ["VALIDATED", "FIXTURE", "SYNTHETIC"]


# ---------------------------------------------------------------------------
# Spatial re-baseline regression tests (2026-08-23)
#
# These tests protect against accidentally restoring the old synthetic M1
# GridSpec as the pilot grid. The authoritative pilot grid is derived from
# the real Copernicus DEM tile (bagjola_kolkata_glo30_dem.tif).
# ---------------------------------------------------------------------------


class TestSpatialReBaselineRegression:
    """Regression tests for the 2026-08-23 spatial re-baseline."""

    def test_pilot_grid_is_not_legacy_synthetic_grid(self):
        """The pilot grid must NOT be the old synthetic M1 grid."""
        from services.ingestion.dem_real import (
            _LEGACY_M1_GRID_CELLS,
            _LEGACY_M1_ORIGIN_X,
            _LEGACY_M1_ORIGIN_Y,
            pilot_grid_spec,
        )

        grid = pilot_grid_spec()
        # Not the old synthetic origin
        assert grid.bounds[0] != _LEGACY_M1_ORIGIN_X
        assert grid.bounds[1] != _LEGACY_M1_ORIGIN_Y
        # Not the old synthetic dimensions
        assert grid.width != _LEGACY_M1_GRID_CELLS
        assert grid.height != _LEGACY_M1_GRID_CELLS
        # Real-pilot grid is much larger than the 134×134 synthetic
        assert grid.width > 500
        assert grid.height > 500

    def test_pilot_grid_deterministic_fingerprint(self):
        """The pilot grid fingerprint must be stable across calls."""
        from services.ingestion.dem_real import pilot_grid_spec

        g1 = pilot_grid_spec()
        g2 = pilot_grid_spec()
        assert g1 == g2
        assert g1.model_dump() == g2.model_dump()
        # Specific values from the real DEM derivation
        assert g1.grid_id == "ufns_pilot_grid_real"
        assert g1.crs_wkt_or_epsg == "EPSG:32645"
        assert g1.cell_size_m == 30.0
        assert g1.width == 846
        assert g1.height == 934
        assert g1.bounds == [664380.0, 2505630.0, 689760.0, 2533650.0]
        assert g1.affine_transform == [30.0, 0.0, 664380.0, 0.0, -30.0, 2533650.0]

    def test_pilot_grid_covers_real_dem_extent(self):
        """The pilot grid must fully cover the real DEM geographic extent."""
        from rasterio.warp import transform_bounds

        from services.ingestion.dem_real import pilot_grid_spec

        grid = pilot_grid_spec()
        wgs = transform_bounds(grid.crs_wkt_or_epsg, "EPSG:4326", *grid.bounds, densify_pts=21)
        # Real DEM bounds: 88.60–88.85°E, 22.65–22.90°N
        assert wgs[0] <= 88.60  # grid west ≤ DEM west
        assert wgs[2] >= 88.85  # grid east ≥ DEM east
        assert wgs[1] <= 22.65  # grid south ≤ DEM south
        assert wgs[3] >= 22.90  # grid north ≥ DEM north

    def test_legacy_synthetic_constants_preserved_for_m1_m9(self):
        """The old M1 synthetic constants remain available in dem.py for
        M1–M9 synthetic fixture compatibility."""
        from services.ingestion.dem import (
            CELL_SIZE_M,
            DOMAIN_M,
            GRID_CELLS,
            ORIGIN_X,
            ORIGIN_Y,
            synthetic_dem,
        )

        # Old constants unchanged
        assert ORIGIN_X == 300000.0
        assert ORIGIN_Y == 2500000.0
        assert GRID_CELLS == 134
        assert CELL_SIZE_M == 30.0
        assert DOMAIN_M == 4020.0
        # Synthetic DEM still works
        dem = synthetic_dem()
        assert dem.shape == (134, 134)
        assert np.all(np.isfinite(dem))

    @require_real_artifacts
    def test_real_dem_normalization_produces_deterministic_fingerprint(self):
        """Normalization of the real DEM must produce a deterministic
        processing fingerprint (same input → same output every time)."""
        from services.ingestion.dem_real import normalize_dem

        r1 = normalize_dem(REAL_DEM)
        r2 = normalize_dem(REAL_DEM)
        assert r1.status == DataIngestionStatus.NORMALIZED
        assert r2.status == DataIngestionStatus.NORMALIZED
        assert r1.processing_fingerprint == r2.processing_fingerprint
        assert r1.processing_fingerprint != ""
        assert len(r1.processing_fingerprint) == 64
        # Same grid, same shape
        assert r1.grid == r2.grid
        assert r1.elevation.shape == r2.elevation.shape


# ---------------------------------------------------------------------------
# CRS provenance & entity mapping regression tests (2026-08-23)
#
# These tests verify the external CRS provenance mechanism and the
# resulting entity mapping execution against the real WB AMRUT artifacts.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real_drains_audit_with_crs_provenance():
    if not all(p.exists() for p in (REAL_DEM, REAL_DRAINS, REAL_VENTS)):
        pytest.skip("real pilot artifacts not present in data/raw")
    from services.ingestion.drainage_real import (
        WB_AMRUT_EXTERNAL_CRS_PROVENANCE,
        audit_wb_amrut_drains,
    )

    return audit_wb_amrut_drains(REAL_DRAINS, external_crs_provenance=WB_AMRUT_EXTERNAL_CRS_PROVENANCE)


@pytest.fixture(scope="module")
def real_vents_audit_with_crs_provenance():
    if not all(p.exists() for p in (REAL_DEM, REAL_DRAINS, REAL_VENTS)):
        pytest.skip("real pilot artifacts not present in data/raw")
    from services.ingestion.drainage_real import (
        WB_AMRUT_EXTERNAL_CRS_PROVENANCE,
        audit_wb_amrut_drains,
    )

    return audit_wb_amrut_drains(REAL_VENTS, external_crs_provenance=WB_AMRUT_EXTERNAL_CRS_PROVENANCE)


class TestCRSProvenanceMechanism:
    """Authoritative external CRS provenance mechanism."""

    def test_wb_amrut_external_crs_provenance_constant(self):
        """The pre-defined WB AMRUT external CRS provenance is complete."""
        from services.ingestion.drainage_real import WB_AMRUT_EXTERNAL_CRS_PROVENANCE

        p = WB_AMRUT_EXTERNAL_CRS_PROVENANCE
        assert p.crs == "EPSG:4326"
        assert "MoHUA" in p.authority
        assert "TCPO" in p.authority
        assert "Str_Drain_NW_Line" in p.source_layers
        assert "Str_Drain_NW_Pnt" in p.source_layers
        assert p.evidence_url
        assert "embedded CRS absent" in p.notes

    def test_crs_provenance_status_enum(self):
        """CRSProvenanceStatus distinguishes embedded/external/unresolved."""
        from services.ingestion.drainage_real import CRSProvenanceStatus

        assert CRSProvenanceStatus.EMBEDDED.value == "EMBEDDED"
        assert CRSProvenanceStatus.AUTHORITATIVE_EXTERNAL.value == "AUTHORITATIVE_EXTERNAL_PROVENANCE"
        assert CRSProvenanceStatus.UNRESOLVED.value == "UNRESOLVED"

    def test_embedded_crs_absent_remains_distinguishable(self, tmp_path):
        """Without external provenance, absent embedded CRS is UNRESOLVED."""
        from services.ingestion.drainage_real import (
            CRSProvenanceStatus,
            audit_wb_amrut_drains,
        )

        pq = write_drainage_fixture(tmp_path / "d.parquet", crs=False)
        result = audit_wb_amrut_drains(pq)
        assert result.crs_provenance_status == CRSProvenanceStatus.UNRESOLVED
        assert result.crs_valid is False
        assert result.external_crs_provenance is None

    def test_embedded_crs_present_is_embedded(self, tmp_path):
        """With embedded CRS in the file, provenance is EMBEDDED."""
        from services.ingestion.drainage_real import (
            CRSProvenanceStatus,
            audit_wb_amrut_drains,
        )

        pq = write_drainage_fixture(tmp_path / "d.parquet", crs=True)
        result = audit_wb_amrut_drains(pq)
        assert result.crs_provenance_status == CRSProvenanceStatus.EMBEDDED
        assert result.crs_valid is True

    def test_external_provenance_cannot_silently_invent_crs(self, tmp_path):
        """External provenance with an invalid CRS must NOT become valid."""
        from services.ingestion.drainage_real import (
            CRSProvenanceStatus,
            ExternalCRSProvenance,
            audit_wb_amrut_drains,
        )

        bad_provenance = ExternalCRSProvenance(
            crs="NOT_A_CRS",
            authority="test",
            source_layers=("test",),
        )
        pq = write_drainage_fixture(tmp_path / "d.parquet", crs=False)
        result = audit_wb_amrut_drains(pq, external_crs_provenance=bad_provenance)
        assert result.crs_provenance_status == CRSProvenanceStatus.UNRESOLVED
        assert result.crs_valid is False

    def test_unresolved_crs_cannot_pass_validation(self, tmp_path):
        """An unresolved CRS cannot produce a VALIDATED result."""
        from services.ingestion.drainage_real import audit_wb_amrut_drains

        pq = write_drainage_fixture(tmp_path / "d.parquet", crs=False)
        result = audit_wb_amrut_drains(pq)
        assert result.status != DataIngestionStatus.VALIDATED

    @require_real_artifacts
    def test_authoritative_external_provenance_satisfies_validation(
        self, real_drains_audit_with_crs_provenance
    ):
        """Authoritative external CRS provenance produces VALIDATED status."""
        from services.ingestion.drainage_real import CRSProvenanceStatus

        result = real_drains_audit_with_crs_provenance
        assert result.status == DataIngestionStatus.VALIDATED
        assert result.crs_valid is True
        assert result.crs_provenance_status == CRSProvenanceStatus.AUTHORITATIVE_EXTERNAL
        assert result.external_crs_provenance is not None
        assert result.external_crs_provenance.crs == "EPSG:4326"
        # CRS provenance info is documented in limitations
        limitations = " ".join(result.provenance.known_limitations)
        assert "ABSENT" in limitations  # embedded CRS absence documented
        assert "authoritative external" in limitations.lower()

    @require_real_artifacts
    def test_vents_authoritative_external_provenance(
        self, real_vents_audit_with_crs_provenance
    ):
        """Vents audit also achieves VALIDATED with external CRS provenance."""
        from services.ingestion.drainage_real import CRSProvenanceStatus

        result = real_vents_audit_with_crs_provenance
        assert result.status == DataIngestionStatus.VALIDATED
        assert result.crs_valid is True
        assert result.crs_provenance_status == CRSProvenanceStatus.AUTHORITATIVE_EXTERNAL
        assert result.unsupported_geometry_count == 9579

    @require_real_artifacts
    def test_embedded_crs_absence_remains_documented(
        self, real_drains_audit_with_crs_provenance
    ):
        """Even with external provenance, embedded CRS absence is documented."""
        result = real_drains_audit_with_crs_provenance
        limitations = " ".join(result.provenance.known_limitations)
        # External provenance info is present
        assert "authoritative external" in limitations.lower() or "AUTHORITATIVE" in limitations
        # Embedded CRS absence is explicitly noted
        assert "embedded CRS" in limitations or "ABSENT" in limitations

    @require_real_artifacts
    def test_entity_mapping_runs_with_validated_source(
        self, real_drains_audit_with_crs_provenance
    ):
        """Entity mapping can run when source audit is VALIDATED."""
        from services.ingestion.drainage_real import (
            WB_AMRUT_EXTERNAL_CRS_PROVENANCE,
            map_drainage_entities,
        )

        result = map_drainage_entities(
            REAL_DRAINS, external_crs_provenance=WB_AMRUT_EXTERNAL_CRS_PROVENANCE
        )
        # Mapping executes (not BLOCKED)
        assert result.status != DataIngestionStatus.BLOCKED
        assert result.status == DataIngestionStatus.NORMALIZED
        # Total = mapped + unresolved + rejected
        total = result.mapped_count + result.unresolved_count + result.rejected_count
        assert total == 90395  # all source features accounted for
        # No hydraulic attributes fabricated
        for param in result.missing_hydraulic_parameters:
            assert "MISSING confirmed absent" in param
        assert result.labels == ["NORMALIZED", "PROVISIONAL", "REAL_DATA"]

    @require_real_artifacts
    def test_entity_mapping_cannot_run_without_validated_source(self):
        """Entity mapping remains BLOCKED without external provenance."""
        from services.ingestion.drainage_real import map_drainage_entities

        result = map_drainage_entities(REAL_DRAINS)
        assert result.status == DataIngestionStatus.BLOCKED
        assert any("VALIDATED" in b for b in result.blockers)

    @require_real_artifacts
    def test_drains_mapping_counts_auditable(self):
        """Drainage mapping produces auditable counts per status."""
        from services.ingestion.drainage_real import (
            WB_AMRUT_EXTERNAL_CRS_PROVENANCE,
            map_drainage_entities,
        )

        result = map_drainage_entities(
            REAL_DRAINS, external_crs_provenance=WB_AMRUT_EXTERNAL_CRS_PROVENANCE
        )
        assert result.status == DataIngestionStatus.NORMALIZED
        # All drain entities are UNRESOLVED_TYPE (no "type" column in source)
        assert result.mapped_count == 0
        assert result.unresolved_count > 0
        # Rejections include duplicates and any invalid geometries
        assert result.rejected_count > 0
        # Breakdown from rejections list
        from collections import Counter
        rejection_types = Counter(r["status"] for r in [r.to_dict() for r in result.rejections])
        assert "REJECTED_DUPLICATE" in rejection_types
        # Source type is empty (no "type" column)
        assert "<empty type>" in result.unresolved_source_types
        # Processing fingerprint is deterministic
        assert result.processing_fingerprint != ""
        assert len(result.processing_fingerprint) == 64

    @require_real_artifacts
    def test_vents_mapping_all_rejected_unsupported_geometry(self):
        """All vent features (MultiPoint) are rejected as unsupported geometry."""
        from services.ingestion.drainage_real import (
            WB_AMRUT_EXTERNAL_CRS_PROVENANCE,
            map_drainage_entities,
        )

        result = map_drainage_entities(
            REAL_VENTS, external_crs_provenance=WB_AMRUT_EXTERNAL_CRS_PROVENANCE
        )
        assert result.status == DataIngestionStatus.NORMALIZED
        assert result.mapped_count == 0
        assert result.unresolved_count == 0
        assert result.rejected_count == 9579
        # All rejected as unsupported geometry (MultiPoint)
        from collections import Counter
        rejection_types = Counter(r.status.value for r in result.rejections)
        assert rejection_types == {"REJECTED_UNSUPPORTED_GEOMETRY": 9579}

    @require_real_artifacts
    def test_crs_provenance_in_serialized_result(
        self, real_drains_audit_with_crs_provenance
    ):
        """CRS provenance is included in serialized results."""
        d = real_drains_audit_with_crs_provenance.to_dict()
        assert d["crs_provenance_status"] == "AUTHORITATIVE_EXTERNAL_PROVENANCE"
        assert d["crs_valid"] is True
        assert d["external_crs_provenance"] is not None
        assert d["external_crs_provenance"]["crs"] == "EPSG:4326"
        assert "MoHUA" in d["external_crs_provenance"]["authority"]
        json.dumps(d)  # fully serializable

    def test_legacy_fixture_behavior_unchanged(self, tmp_path):
        """Existing fixture tests remain unaffected by the CRS provenance mechanism."""
        from services.ingestion.drainage_real import (
            CRSProvenanceStatus,
            audit_wb_amrut_drains,
        )

        # Fixture with embedded CRS → EMBEDDED provenance
        pq_with = write_drainage_fixture(tmp_path / "with_crs.parquet", crs=True)
        result_with = audit_wb_amrut_drains(pq_with)
        assert result_with.crs_provenance_status == CRSProvenanceStatus.EMBEDDED
        assert result_with.crs_valid is True
        assert result_with.status == DataIngestionStatus.VALIDATED

        # Fixture without embedded CRS → UNRESOLVED (no external provenance passed)
        pq_without = write_drainage_fixture(tmp_path / "no_crs.parquet", crs=False)
        result_without = audit_wb_amrut_drains(pq_without)
        assert result_without.crs_provenance_status == CRSProvenanceStatus.UNRESOLVED
        assert result_without.crs_valid is False

    @require_real_artifacts
    def test_real_data_never_labeled_synthetic_with_crs_provenance(
        self, real_drains_audit_with_crs_provenance
    ):
        """Real data with external CRS provenance is never labelled SYNTHETIC."""
        labels = real_drains_audit_with_crs_provenance.labels
        assert "SYNTHETIC" not in labels
        assert "REAL_DATA" in labels
