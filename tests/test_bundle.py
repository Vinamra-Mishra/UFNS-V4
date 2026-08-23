"""M1 bundle acceptance: loads, CRS verified, timestamps verified, provenance,
reproducibility (IMPLEMENTATION_SPEC M1 acceptance checklist)."""

import json

import numpy as np
import rasterio

import scripts.build_demo_data as bdd
from services.ingestion.provenance import sha256_file


def _build(tmp_path, sub):
    bdd.DATA_DIR = tmp_path / sub
    bdd.DATA_DIR.mkdir(parents=True)
    bdd.main()


def test_bundle_builds_and_loads(tmp_path):
    _build(tmp_path, "b1")
    d = bdd.DATA_DIR
    assert (d / "dem.tif").exists() and (d / "manifest.json").exists()
    with rasterio.open(d / "dem.tif") as src:
        assert src.crs.to_epsg() == 32645
        assert src.read(1).shape == (134, 134)
        assert np.all(np.isfinite(src.read(1)))
    manifest = json.loads((d / "manifest.json").read_text())
    roles = {a["role"] for a in manifest["assets"]}
    assert {"dem", "rainfall_fixture", "scenario_definitions", "preview_dem", "preview_rain"} <= roles
    # every file asset's checksum must match the file on disk
    for a in manifest["assets"]:
        p = d / a["asset_uri"]
        if p.is_file():
            assert a["content_sha256"] == sha256_file(p), a["asset_uri"]
    # rain index entries must match their files too
    rain_index = json.loads((d / "rain_index.json").read_text())
    for f in rain_index["files"]:
        assert f["sha256"] == sha256_file(d / f["uri"]), f["uri"]


def test_bundle_rebuild_is_identical(tmp_path):
    _build(tmp_path, "b1")
    first = {p.name: sha256_file(p) for p in bdd.DATA_DIR.rglob("*") if p.is_file()}
    _build(tmp_path, "b2")
    second = {p.name: sha256_file(p) for p in bdd.DATA_DIR.rglob("*") if p.is_file()}
    assert first == second


def test_rainfall_fields_carry_interval_metadata(tmp_path):
    _build(tmp_path, "b1")
    p = bdd.DATA_DIR / "rain" / "rain_000.tif"
    with rasterio.open(p) as src:
        tags = src.tags()
        assert tags["ARENA_PROVENANCE"] == "SIMULATED_SCENARIO"
        assert tags["ARENA_UNITS"] == "mm/h"
        assert "PROVISIONAL" in tags["ARENA_DERIVATION"]
        assert tags["ARENA_VALID_FROM"].endswith("Z") and tags["ARENA_VALID_TO"].endswith("Z")
        data = src.read(1)
    assert np.all(data >= 0) and np.all(np.isfinite(data))


def test_scenario_json_reproducible_provenance(tmp_path):
    _build(tmp_path, "b1")
    doc = json.loads((bdd.DATA_DIR / "scenarios.json").read_text())
    assert set(doc.keys()) == {"normal", "heavy", "extreme", "extreme_blockage"}
    for s in doc.values():
        assert s["rainfall_profile"]["review_status"] == "PROVISIONAL"
        assert s["provenance"]["provenance_class"] == "SYNTHETIC"
