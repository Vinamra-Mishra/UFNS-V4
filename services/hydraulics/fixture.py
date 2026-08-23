"""Synthetic SWMM drainage fixtures (M3 spike) — fully SYNTHETIC/ASSUMED.

FIXTURE A (exact-exchange fixture; ledger-exact by construction):
    surface inlet cell  --capture-->  ST1 (storage, 4 m2)
                                        |
                                        C1 (100 m, D=0.3, n=0.013)
                                        v
    surface vent cell   <--return----  V1 (storage, 1 m2; the vent node)
                                        |
                                        C2 (5 m, D=0.3)
                                        v
                                        O1 (FREE outfall)
  No junctions anywhere: every drainage storage term (ST1.volume,
  V1.volume, C1.volume, C2.volume) is engine-exact, so the coupled ledger
  closes to machine precision. "Surcharge" is represented by the head-driven
  return orifice: water emerges when V1 head exceeds the ASSUMED vent ground
  level (10.4 m, i.e. V1 depth > 1.4 m).
  Variants: clean (C1 D=0.3), blocked (C1 D=0.15; Manning capacity ratio
  (0.5)^(8/3) = 0.157).

FIXTURE B (engine-flooding demonstration, M3-05 only):
  ST1 -> C1 -> J1 (junction, MaxDepth 0.01, Apond=0) -> C2 -> O1.
  Demonstrates SWMM's native surcharge flooding (head >= rim, flooding > 0).
  Its flooding-rate export is approximate (point-in-time sampling), so it is
  used for the physical surcharge demonstration only — no exact-mass claim.

Every parameter is labelled SYNTHETIC (geometry) or ASSUMED (hydraulic values
chosen to make analytical checks possible). These networks represent NO real
place.

Analytical reference: C1 full-bore Manning capacity (D=0.3, S=0.01, n=0.013):
  Q = (1/n) A R^(2/3) S^(1/2) = 0.0968 m3/s (~97 L/s); blocked (D=0.15): 15.2 L/s.
"""

from __future__ import annotations

import math
from pathlib import Path

# -- SYNTHETIC network parameters (all SI) -----------------------------------
ST1_INVERT = 10.0        # m  (SYNTHETIC)
ST1_AREA = 4.0           # m2 (SYNTHETIC, constant tabular area)
V1_INVERT = 9.0          # m  (SYNTHETIC; gives C1 slope = 0.01)
V1_AREA = 1.0            # m2 (SYNTHETIC, constant tabular area)
C1_LENGTH = 100.0        # m  (SYNTHETIC)
C1_DIAMETER = 0.3        # m  (SYNTHETIC)
C1_MANNING = 0.013       # s/m^(1/3) (ASSUMED: concrete pipe literature value)
J1_INVERT = 9.0          # m  (SYNTHETIC, flooding-demo fixture)
J1_MAXDEPTH = 0.01       # m  (SYNTHETIC: pure surcharge vent)
C2_LENGTH = 5.0          # m  (SYNTHETIC)
C2_DIAMETER = 0.3        # m  (SYNTHETIC)
OUTFALL_INVERT = 8.95    # m  (SYNTHETIC; C2 slope = 0.01)

# -- ASSUMED exchange parameters ---------------------------------------------
VENT_GROUND_LEVEL = 10.4  # m (ASSUMED: ground at the vent manhole)
CD_ORIFICE = 0.6          # -  (ASSUMED: standard submerged-orifice coefficient)
AO_ORIFICE = 0.1          # m2 (ASSUMED: inlet opening area)
G = 9.80665               # m/s2 (physical constant)


def full_bore_capacity(diameter_m: float, slope: float, n: float) -> float:
    """Manning full-bore capacity (m3/s) — analytical cross-check."""
    a = math.pi * diameter_m**2 / 4.0
    r = diameter_m / 4.0
    return (1.0 / n) * a * r ** (2.0 / 3.0) * math.sqrt(slope)


C1_SLOPE = (ST1_INVERT - V1_INVERT) / C1_LENGTH
C1_CAPACITY = full_bore_capacity(C1_DIAMETER, C1_SLOPE, C1_MANNING)
C1_BLOCKED_CAPACITY = full_bore_capacity(C1_DIAMETER / 2, C1_SLOPE, C1_MANNING)


FIXTURE_SPAN_HOURS = 6.0  # (SYNTHETIC: duration of the fixed SWMM simulation clock)

def _options() -> str:
    # 06:00:00 matches FIXTURE_SPAN_HOURS
    return """[OPTIONS]
FLOW_UNITS           CMS
FLOW_ROUTING         DYNWAVE
START_DATE           08/21/2026
START_TIME           00:00:00
END_DATE             08/21/2026
END_TIME             06:00:00
REPORT_STEP          00:05:00
DRY_STEP             00:01:00
WET_STEP             00:01:00
ROUTING_STEP         1.0
ALLOW_PONDING        NO
"""


def _storage_st1() -> str:
    return f"""[STORAGE]
;;Name  Elev       MaxDepth  InitDepth  Shape    Curve
ST1     {ST1_INVERT}    5.0       0.0       TABULAR  area_st1
[CURVES]
;;Curve    Type     X     Y
area_st1  STORAGE  0.0   {ST1_AREA}
area_st1           5.0   {ST1_AREA}
"""


def exact_fixture_inp(blocked: bool, datum_offset_m: float = 0.0, blocked_diameter_m: float = 0.15) -> str:
    """Exact-exchange fixture. `datum_offset_m` shifts ALL elevations by the
    same constant (B08: the 134x134 synthetic DEM's local datum sits ~10 m
    above the M3 spike datum; a constant shift preserves every slope/invert
    difference exactly, so hydraulic behaviour is unchanged — M3 tests at
    offset 0 verify the unshifted baseline).

    Blocked variant: `blocked_diameter_m` replaces C1's diameter (M3 default
    0.15 m, capacity ratio (0.5)^(8/3)=0.157; M4 uses 0.12 m, ratio 0.087 —
    documented in the M4 fixture spec)."""
    variant = f"blocked C1 D={blocked_diameter_m}" if blocked else "clean C1 D=0.3"
    d1 = blocked_diameter_m if blocked else C1_DIAMETER
    o = float(datum_offset_m)
    storage = f"""[STORAGE]
;;Name  Elev       MaxDepth  InitDepth  Shape    Curve
ST1     {ST1_INVERT + o}    5.0       0.0       TABULAR  area_st1
V1      {V1_INVERT + o}     5.0       0.0       TABULAR  area_v1
[CURVES]
;;Curve    Type     X     Y
area_st1  STORAGE  0.0   {ST1_AREA}
area_st1           5.0   {ST1_AREA}
area_v1   STORAGE  0.0   {V1_AREA}
area_v1            5.0   {V1_AREA}
"""
    return f"""[TITLE]
UFNS M3 synthetic drainage fixture (exact-exchange) - {variant} - SYNTHETIC/ASSUMED, represents no real place
{_options()}{storage}[CONDUITS]
;;Name  From  To   Length     Manning  InOffset  OutOffset  InitFlow  MaxFlow
C1      ST1   V1   {C1_LENGTH}     {C1_MANNING}   0         0          0         0
C2      V1    O1   {C2_LENGTH}      {C1_MANNING}   0         0          0         0
[XSECTIONS]
;;Link  Shape      Geom1   Geom2  Geom3  Geom4  Barrels
C1      CIRCULAR   {d1}     0      0      0      1
C2      CIRCULAR   {C2_DIAMETER}     0      0      0      1
[OUTFALLS]
;;Name  Elev       Type  Stage/Gated
O1      {OUTFALL_INVERT + o}     FREE  NO
[REPORT]
INPUT YES
CONTROLS YES
NODES ALL
LINKS ALL
"""


def flood_fixture_inp() -> str:
    """Fixture B: native SWMM flooding demonstration (M3-05)."""
    return f"""[TITLE]
UFNS M3 synthetic drainage fixture (flooding demo) - SYNTHETIC/ASSUMED, represents no real place
{_options()}{_storage_st1()}
[JUNCTIONS]
;;Name  Elev       MaxDepth      InitDepth  SurDepth  Apond
J1      {J1_INVERT}        {J1_MAXDEPTH}        0.0        0.0       0
[CONDUITS]
;;Name  From  To   Length     Manning  InOffset  OutOffset  InitFlow  MaxFlow
C1      ST1   J1   {C1_LENGTH}     {C1_MANNING}   0         0          0         0
C2      J1    O1   {C2_LENGTH}      {C1_MANNING}   0         0          0         0
[XSECTIONS]
;;Link  Shape      Geom1   Geom2  Geom3  Geom4  Barrels
C1      CIRCULAR   {C1_DIAMETER}     0      0      0      1
C2      CIRCULAR   {C2_DIAMETER}     0      0      0      1
[OUTFALLS]
;;Name  Elev       Type  Stage/Gated
O1      {OUTFALL_INVERT}     FREE  NO
[REPORT]
INPUT YES
CONTROLS YES
NODES ALL
LINKS ALL
"""


def write_fixtures(data_dir: Path) -> dict[str, Path]:
    data_dir.mkdir(parents=True, exist_ok=True)
    out = {
        "clean": data_dir / "drainage_synthetic.inp",
        "blocked": data_dir / "drainage_synthetic_blocked.inp",
        "flood": data_dir / "drainage_synthetic_flood.inp",
    }
    out["clean"].write_text(exact_fixture_inp(blocked=False))
    out["blocked"].write_text(exact_fixture_inp(blocked=True))
    out["flood"].write_text(flood_fixture_inp())
    return out


FIXTURE_CLEAN = Path("data/demo/drainage_synthetic.inp")
FIXTURE_BLOCKED = Path("data/demo/drainage_synthetic_blocked.inp")
FIXTURE_FLOOD = Path("data/demo/drainage_synthetic_flood.inp")
