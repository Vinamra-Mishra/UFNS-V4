# M8 — Velocity Integration Roadmap (B13)

> **Status:** ROADMAP — NOT IMPLEMENTED
> **Date:** 2026-08-22
> **M8 does NOT solve the B13 velocity problem.**

---

## 1. Purpose

This document specifies the future architecture for integrating flow velocity
into the UFNS flood-impact and routing pipeline. M8 implements only the
rainfall nowcast layer; velocity integration is deferred to a future milestone
(likely M9+).

The current B13-DEMO-V1 policy uses **depth only** for road passability
classification. This is a known limitation: velocity is a critical factor in
vehicle stability and human safety (e.g., a shallow but fast-flowing flood can
be more dangerous than deep standing water).

## 2. Current State

- M7 road impact: depth-only sampling from simulated flood-depth fields
- B13-DEMO-V1: PROVISIONAL DEMONSTRATION, depth thresholds only
- No velocity field is currently computed or stored
- The M4 coupled model computes surface water levels but does NOT export
  velocity magnitude or direction fields

## 3. Future Velocity Sources

| Source | Method | Status |
|--------|--------|--------|
| Landlab OverlandFlow | Extract velocity from the de Almeida solver state | FUTURE |
| SWMM conduit velocities | Extract from PySWMM link results | FUTURE |
| Depth-velocity empirical | Manning equation approximation from depth + slope | FUTURE |
| 2-D shallow water | Full velocity field from a dedicated 2-D solver | FUTURE |

## 4. Velocity Extraction Method (Future)

### 4.1 Landlab Surface Velocity

Landlab's `OverlandFlow` component computes `surface_water__discharge`, which
is the **unit-width discharge** q with units **m²/s** — NOT a volumetric
discharge (m³/s). The depth-averaged flow velocity at a cell face is therefore:

    v = q / h        [m/s]

where:

| Symbol | Meaning | Units |
|--------|---------|-------|
| q | `surface_water__discharge` (unit-width discharge) | m²/s |
| h | water depth (`max(0, η − z)`) | m |
| v | derived flow velocity | m/s |

Do **NOT** multiply by the road/cell width unless you are first converting a
true volumetric discharge (m³/s) to a unit-width discharge. Because Landlab's
field is already per unit width, the width cancels and `v = q / h`.

**Edge cases / division-by-zero guard (must be handled defensively):**

| Condition | Definition |
|-----------|------------|
| `h == 0` | No water, no flow. Define `v = 0` (q should also be 0). |
| `h ≈ 0` (e.g. `h < h_min`, where a sensible `h_min` is ~1e-6 m) | Guard: clamp and set `v = 0` to avoid a spurious large velocity from a near-dry cell. |
| `h < 0` or non-finite `h` | Invalid — depth is defined as `max(0, η − z)` so negative depth must not occur; clip to 0 and set `v = 0`. |

**Supported dependency version:** the project pins the Landlab spike via
`requirements-spikes.txt` (`landlab>=2.8` plus `requireit==0.8.0`). The
verified build uses **landlab 2.11.0**. This pin is intentional and must be
kept alongside `requireit==0.8.0` for Python 3.11 compatibility.

### 4.2 SWMM Conduit Velocity

PySWMM provides `Link.result("velocity")` for each conduit. This gives the
1-D velocity along each pipe — useful for drainage surcharge return flow
velocity at inlet points.

### 4.3 Depth × Velocity Calculation

For road impact, the relevant quantity is the local depth-velocity product
or the separate depth and velocity at each road cell:

    hazard = f(depth, velocity, velocity_direction, duration)

## 5. Road Sampling (Future)

The existing Bresenham road rasterization (M7) can be extended to sample
velocity at each cell along the road, in addition to depth:

    road_cells → sample (depth, velocity_magnitude, velocity_direction)

## 6. Hazard Classification (Future)

> **Scope:** This is a specification for the **future** depth + velocity hazard
> model. The current M7 routing does **NOT** use velocity — it is depth-only.
> Nothing here is implemented in the current codebase.

The classification below maps every combination of depth (d) and velocity (v)
to **exactly one** classification. It is exhaustive and mutually exclusive: the
depth bands and velocity bands partition the (d, v) space, and a precedence
rule resolves any residual ambiguity (depth dominates).

### 6.1 Domain

- Depth and velocity are only defined for **wet** cells (`d > 0`). A dry cell
  (`d == 0`) is outside this hazard matrix and is classed as **DRY** (no
  flood-related hazard).
- `d` and `v` are non-negative and finite by construction.

### 6.2 Precedence (evaluated top-down; depth dominates)

This is the exact decision rule that the matrix in §6.3 tabulates. It is
mutually exclusive: depth is checked first, then velocity within each depth
band.

1. **d > 0.50 m** → **MODELLED_UNSUITABLE**. Depth is the dominant safety
   factor; no velocity band can override it.
2. **0.30 m < d ≤ 0.50 m**:
   - `v < 1.0 m/s` → **MODERATE**
   - `1.0 ≤ v < 2.0 m/s` → **HIGH**
   - `v ≥ 2.0 m/s` → **EXTREME**
3. **d ≤ 0.30 m** (with `d > 0`):
   - `v < 1.0 m/s` → **LOW**
   - `1.0 ≤ v < 2.0 m/s` → **MODERATE**
   - `2.0 ≤ v ≤ 3.0 m/s` → **HIGH**
   - `v > 3.0 m/s` → **EXTREME**
4. **d = 0** (dry cell) → **DRY** (outside the wet-hazard matrix; no hazard).

### 6.3 Decision matrix

Depth bands (inclusive upper boundary):

| Band | Range |
|------|-------|
| D1 | `0 < d ≤ 0.30 m` |
| D2 | `0.30 m < d ≤ 0.50 m` |
| D3 | `d > 0.50 m` |

Velocity bands (inclusive lower boundary for the 1.0 and 2.0 thresholds):

| Band | Range |
|------|-------|
| V1 | `0 ≤ v < 1.0 m/s` |
| V2 | `1.0 ≤ v < 2.0 m/s` |
| V3 | `2.0 ≤ v ≤ 3.0 m/s` |
| V4 | `v > 3.0 m/s` |

| | V1 (`v < 1.0`) | V2 (`1.0 ≤ v < 2.0`) | V3 (`2.0 ≤ v ≤ 3.0`) | V4 (`v > 3.0`) |
|---|---|---|---|---|
| **D1** (`d ≤ 0.30`) | LOW | MODERATE | HIGH | EXTREME |
| **D2** (`0.30 < d ≤ 0.50`) | MODERATE | HIGH | EXTREME | EXTREME |
| **D3** (`d > 0.50`) | MODELLED_UNSUITABLE | MODELLED_UNSUITABLE | MODELLED_UNSUITABLE | MODELLED_UNSUITABLE |

Boundary conventions (identical in §6.2 and the matrix):
- `d = 0.30 m` → D1; `d = 0.50 m` → D2; `d > 0.50 m` → D3.
- `v = 1.0 m/s` → V2; `v = 2.0 m/s` → V3; `v = 3.0 m/s` → V3; `v > 3.0 m/s` → V4.
- Because precedence is depth-first and the (d, v) partition is total and
  disjoint, no (d, v) pair maps to more than one classification.

### 6.4 Terminology

- **MODELLED_UNSUITABLE** (not "IMPASSABLE" / not "safe route") describes the
  model's classification of a road cell as unsuitable for the modelled
  condition. It is a modelled result, not a road closure or a safety
  determination.
- "LOW / MODERATE / HIGH / EXTREME" are relative modelled hazard bands, not
  universal safety thresholds.

These thresholds are illustrative and research-informed only; they require
expert review (B13) before any operational use.

## 7. Routing Integration (Future)

When velocity is available:
- Road cost function: `cost = f(depth, velocity, road_class, vehicle_type)`
- Separate vehicle profiles (car, SUV, emergency vehicle, pedestrian)
- Velocity direction affects crossing risk (perpendicular flow more dangerous)

## 8. Validation Requirements

Before any velocity-based routing claim:
1. Velocity field must be validated against analytical or benchmark cases
2. Road-sampled velocity must be shown to be physically reasonable
3. Hazard classification must be reviewed by a flood safety expert
4. Routing cost function must be calibrated against observed vehicle
   instability data (if available)

## 9. M8 Boundary

M8 does NOT:
- Compute or export velocity fields
- Modify the B13 passability policy
- Change road impact from depth-only
- Integrate Landlab velocity extraction
- Add velocity-based routing costs

M8 DOES:
- Provide the architectural foundation (provider independence, typed contracts)
- Document the velocity integration roadmap
- Preserve the B13 PROVISIONAL status (unchanged)
- Keep "MODELLED ROUTE" / "MODELLED UNSUITABLE" wording (no "SAFE ROUTE")
