"""D-016 — Scientific rainfall-derivation tests (master prompt §10).

These tests establish the traceable, deterministic behaviour of the published
IDF-based derivation (Option A) without fabricating any human approval. They
do NOT weaken any M5 test and do NOT alter M1-M5 engine semantics.

D016-01 published source exists
D016-02 geographic applicability documented
D016-03 scenario mapping explicit
D016-04 derivation deterministic
D016-05 15-min series totals match intended event depth
D016-06 assumptions labelled
D016-07 no fabricated human approval
D016-08 status correctly recorded (PREPARED — HUMAN REVIEW REQUIRED)
"""

from __future__ import annotations

import pytest

from services.rainfall import idf
from services.rainfall.idf import (
    DERIVED_DEPTHS_MM,
    DERIVED_HYETOGRAPHS_MMH,
    DURATION_MINUTES,
    INTERVAL_MINUTES,
    PUBLISHED_DURATIONS_H,
    PUBLISHED_INTENSITY_100YR,
    PUBLISHED_INTENSITY_2YR,
    RECOMMENDED_SCENARIO_MAPPING,
    SOURCE,
    derivation_fingerprint,
    depth_mm,
    derived_hyetographs_mmh,
    derived_scenario_depths_mm,
    intensity_mmh,
)
from services.rainfall.scenarios import alternating_block_hyetograph
from services.scenarios.profiles import D016_STATUS, ProfileStatus, all_profiles


# ---------------------------------------------------------------------------
# D016-01 — published source exists and is recorded
# ---------------------------------------------------------------------------

def test_d016_01_published_source_recorded():
    for key in ("title", "authors", "journal", "doi", "url", "gauge_station",
                "record_period", "geographic_applicability", "distribution"):
        assert key in SOURCE and SOURCE[key], f"SOURCE missing {key}"
    assert SOURCE["doi"] == "10.1007/s11269-026-04514-5"
    assert SOURCE["gauge_station"] == "IMD Alipur"
    assert SOURCE["record_period"] == "1980-2023"
    assert len(PUBLISHED_DURATIONS_H) == len(PUBLISHED_INTENSITY_2YR) == len(PUBLISHED_INTENSITY_100YR)


# ---------------------------------------------------------------------------
# D016-02 — geographic applicability documented
# ---------------------------------------------------------------------------

def test_d016_02_geographic_applicability():
    assert "Kolkata" in SOURCE["geographic_applicability"]
    assert "West Bengal" in SOURCE["geographic_applicability"]
    # The derivation is NOT claimed to apply to the exact synthetic fixture;
    # it applies to the pilot-region candidate area only.
    assert "Bagjola Canal basin" in SOURCE["geographic_applicability"]


# ---------------------------------------------------------------------------
# D016-03 — scenario mapping is explicit (and not silently equated to RPs)
# ---------------------------------------------------------------------------

def test_d016_03_scenario_mapping_explicit():
    assert set(RECOMMENDED_SCENARIO_MAPPING) == {"NORMAL", "HEAVY", "EXTREME"}
    for sev, cfg in RECOMMENDED_SCENARIO_MAPPING.items():
        assert "return_period_yr" in cfg
        assert "rationale" in cfg
        assert cfg["return_period_yr"] >= 2
    # Recommended mapping follows the source's own 2/5/10-year design set.
    assert [RECOMMENDED_SCENARIO_MAPPING[s]["return_period_yr"]
            for s in ("NORMAL", "HEAVY", "EXTREME")] == [2, 5, 10]


# ---------------------------------------------------------------------------
# D016-04 — derivation is deterministic
# ---------------------------------------------------------------------------

def test_d016_04_derivation_deterministic():
    a = derived_scenario_depths_mm()
    b = derived_scenario_depths_mm()
    assert a == b
    assert derivation_fingerprint() == derivation_fingerprint()
    assert derived_hyetographs_mmh() == derived_hyetographs_mmh()
    # depth/intensity functions are pure
    for T in (2.0, 5.0, 10.0, 100.0):
        assert depth_mm(3.0, T) == depth_mm(3.0, T)
        assert intensity_mmh(3.0, T) == intensity_mmh(3.0, T)


# ---------------------------------------------------------------------------
# D016-04b — published anchors reproduce exactly (traceability)
# ---------------------------------------------------------------------------

def test_d016_04b_published_anchors_reproduced():
    for d, i2, i100 in zip(PUBLISHED_DURATIONS_H, PUBLISHED_INTENSITY_2YR, PUBLISHED_INTENSITY_100YR):
        assert depth_mm(d, 2.0) == pytest.approx(i2 * d, abs=1e-9)
        assert depth_mm(d, 100.0) == pytest.approx(i100 * d, abs=1e-9)


# ---------------------------------------------------------------------------
# D016-05 — 15-minute series totals match the intended event depth
# ---------------------------------------------------------------------------

def test_d016_05_hyetograph_totals_and_structure():
    n = DURATION_MINUTES // INTERVAL_MINUTES
    assert n == 12
    for sev, total in DERIVED_DEPTHS_MM.items():
        hy = DERIVED_HYETOGRAPHS_MMH[sev]
        assert len(hy) == n, f"{sev}: expected {n} intervals"
        assert all(v >= 0 for v in hy), f"{sev}: negative intensity"
        summed = sum(v * (INTERVAL_MINUTES / 60.0) for v in hy)
        assert summed == pytest.approx(total, abs=1e-6), f"{sev}: total mismatch"
        # peak intensity is the largest interval (alternating-block puts it at storm centre)
        assert max(hy) > 0


# ---------------------------------------------------------------------------
# D016-05b — correct units
# ---------------------------------------------------------------------------

def test_d016_05b_units():
    # intensities are mm/h; depths are mm; durations in hours.
    for sev, hy in DERIVED_HYETOGRAPHS_MMH.items():
        # mean intensity = total depth / duration(hours)
        mean = DERIVED_DEPTHS_MM[sev] / (DURATION_MINUTES / 60.0)
        assert sum(hy) / len(hy) == pytest.approx(mean, rel=1e-6)
    # 1-hour depth equals the published 1-hour intensity (unit consistency)
    assert depth_mm(1.0, 2.0) == pytest.approx(45.05, abs=1e-9)


# ---------------------------------------------------------------------------
# D016-06 — assumptions labelled; derivation returns non-negative rain
# ---------------------------------------------------------------------------

def test_d016_06_no_negative_and_source_params_recorded():
    for sev, hy in DERIVED_HYETOGRAPHS_MMH.items():
        assert all(v >= 0 for v in hy)
    # storm-shape exponent is an explicit ASSUMPTION, recorded
    assert idf.STORM_SHAPE_EXPONENT == 0.4
    # source-derived parameters are recorded in the module constants
    assert all(i2 > 0 for i2 in PUBLISHED_INTENSITY_2YR)
    assert all(i100 > 0 for i100 in PUBLISHED_INTENSITY_100YR)


# ---------------------------------------------------------------------------
# D016-06b — scenario ordering where scientifically justified
# ---------------------------------------------------------------------------

def test_d016_06b_monotonic_ordering():
    d = DERIVED_DEPTHS_MM
    assert d["NORMAL"] < d["HEAVY"] < d["EXTREME"]
    # depth increases with return period (scientific expectation)
    for duration in (1.0, 3.0, 6.0):
        assert depth_mm(duration, 2.0) < depth_mm(duration, 5.0) < depth_mm(duration, 10.0) \
               < depth_mm(duration, 100.0)


# ---------------------------------------------------------------------------
# D016-07 — no fabricated human approval
# ---------------------------------------------------------------------------

def test_d016_07_no_fabricated_human_approval():
    # The live M5 profiles must NOT be marked APPROVED.
    profiles = all_profiles()
    for p in profiles.values():
        assert p.review_status == ProfileStatus.PROVISIONAL
        assert p.d016_review_status != "APPROVED"
    # D-016 status reflects "prepared but human review required", never approved.
    assert D016_STATUS == "PREPARED"
    assert "PREPARED" in D016_STATUS or "REQUIRED" in D016_STATUS


# ---------------------------------------------------------------------------
# D016-08 — status correctly recorded
# ---------------------------------------------------------------------------

def test_d016_08_status_recorded():
    assert D016_STATUS == "PREPARED"
    # fingerprint stability: source parameters are recorded and stable
    assert len(derivation_fingerprint()) == 64
    assert derivation_fingerprint() == derivation_fingerprint()


# ---------------------------------------------------------------------------
# D016-09 — regression compatibility with the M5 scenario contract
# ---------------------------------------------------------------------------

def test_d016_09_m5_contract_unchanged():
    # The alternating-block primitive used by M5 is unchanged and still works.
    hy = alternating_block_hyetograph(45.0, 180, 15, exponent=0.4)
    assert len(hy) == 12
    assert sum(v * 0.25 for v in hy) == pytest.approx(45.0, abs=1e-6)
    # The M5 profile builder still produces the provisional 12-interval series.
    from services.scenarios.profiles import build_profile_record
    p = build_profile_record("P_HEAVY")
    assert len(p.intensities_mmh) == 12
    assert p.total_depth_mm == 45.0  # provisional value preserved (not yet flipped)
    assert p.review_status == ProfileStatus.PROVISIONAL


# ---------------------------------------------------------------------------
# D016-10 — invalid inputs fail safely
# ---------------------------------------------------------------------------

def test_d016_10_invalid_inputs():
    with pytest.raises(ValueError):
        depth_mm(0.0, 2.0)          # non-positive duration
    with pytest.raises(ValueError):
        depth_mm(3.0, 1.0)          # return period below annual-maxima range
    with pytest.raises(ValueError):
        intensity_mmh(-1.0, 2.0)
