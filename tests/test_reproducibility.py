"""Reproducibility + provenance tests (IMPLEMENTATION_SPEC §23, B12-adjacent)."""

import hashlib
from pathlib import Path

from services.ingestion.dem import synthetic_dem, write_geotiff
from services.ingestion.provenance import Manifest, make_lineage, sha256_file
from services.contracts import ProvenanceClass, QualityFlag


def test_rebuild_is_byte_identical(tmp_path):
    p1 = tmp_path / "a.tif"
    p2 = tmp_path / "b.tif"
    write_geotiff(synthetic_dem(seed=20260821), p1)
    write_geotiff(synthetic_dem(seed=20260821), p2)
    assert sha256_file(p1) == sha256_file(p2)


def test_manifest_checksum_matches_disk(tmp_path):
    p = tmp_path / "dem.tif"
    write_geotiff(synthetic_dem(), p)
    lin = make_lineage(
        "dem", "v1", "test", ProvenanceClass.SYNTHETIC, p,
        quality_flags=[QualityFlag.SYNTHETIC],
    )
    assert lin.content_sha256 == sha256_file(p)
    m = Manifest("pilot_test")
    m.add_asset("dem", p, lin)
    out = m.write(tmp_path / "manifest.json")
    import json

    doc = json.loads(out.read_text())
    assert doc["assets"][0]["content_sha256"] == sha256_file(p)
    assert doc["assets"][0]["provenance_class"] == "SYNTHETIC"


def test_tamper_detection(tmp_path):
    p = tmp_path / "dem.tif"
    write_geotiff(synthetic_dem(), p)
    digest = sha256_file(p)
    data = bytearray(p.read_bytes())
    data[100] ^= 0xFF  # flip one byte
    p.write_bytes(bytes(data))
    assert sha256_file(p) != digest
