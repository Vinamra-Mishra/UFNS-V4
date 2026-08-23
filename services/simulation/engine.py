"""M4 — Coupled flood model engine (IMPLEMENTATION_SPEC M4).

Assembles the validated components into one coherent simulation:

    Rainfall fields -> microstore + Horton losses -> Landlab surface routing
        <-> validated M3 signed head-driven orifice exchange <-> SWMM dynamic wave
        -> time-indexed FloodSnapshots + coupled mass ledger

REUSE POLICY (M4 spec §14): the exchange algorithm, sign convention, causal
ordering, per-stride ledger identity, and 5 s coupling stride are the
M3-validated semantics (services/hydraulics/coupling.py). This engine ports
them faithfully and generalizes ONLY the mapping: multiple inlet cells
(each an independent signed orifice into ST1) and one vent cell with its own
opening area. The M4 test suite proves semantic equivalence with the M3 spike
driver on the single-inlet case (tests/test_m4_coupled.py).

TIME ORDER (explicit, causal; identical to M3 per stride):
  1. read SWMM state at t_{i+1} (post-stride)
  2. export completed-stride flooding; record stride outfall volume
  3. update drainage storage via SWMM's own per-stride identity
  4. (final read-only stride ends the loop)
  5. apply rainfall (bucket of the stride start) -> microstore fill ->
     Horton infiltration on core cells
  6. advance surface routing one dt_c
  7. compute signed exchange from aligned states (multi-inlet capture,
     single-vent return, availability caps)
  8. drive SWMM for the next stride (generated_inflow at ST1)
  9. record ledger; write snapshot if scheduled

INITIAL CONDITIONS (per run, clean state, no cross-run leakage):
  surface depth 0 (film only), wetting clocks 0, microstore 0, SWMM dry, t=0.
"""

from __future__ import annotations

import hashlib
import json
import math
import resource
import time as _time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from affine import Affine

from services.contracts import (
    DrainageStateSummary,
    FloodSnapshot,
    GridSpec,
    MassBalance,
    QualityFlag,
    SimulationRun,
)
from services.hydraulics.coupling import (
    PASS_REL,
    WARN_REL,
    CoupledLedger,
    CouplingError,
    orifice_exchange_rate,
)
from services.hydraulics.fixture import CD_ORIFICE
from services.hydrology.surface import HortonLoss, SurfaceModel
from services.ingestion.crs import WB_PROJECTED_CRS
from services.ingestion.dem import CELL_SIZE_M, VERTICAL_REFERENCE, grid_affine
from services.ingestion.provenance import sha256_bytes, sha256_file
from services.rainfall.fields import render_interval

MODEL_VERSION = "m4-coupling-v1"
DT_C_DEFAULT = 5  # coupling stride, integer seconds (pyswmm 2.1 requirement)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class RainfallSpec:
    """M4/M9 forcing spec.

    kind:
      - zero
      - uniform
      - spatial
      - profile
      - explicit_fields  (M9 adapter: direct mm/h fields, no resampling)
    """
    kind: str = "uniform"
    interval_minutes: int = 15
    intensities_mmh: list[float] = field(default_factory=lambda: [10.0])
    pattern: str = "uniform"       # uniform | convective_cell | explicit_fields
    seed: int = 20260821
    explicit_fields_mmh: list[np.ndarray] | None = None


@dataclass
class LossSpec:
    """Horton + micro-depression storage (PROVISIONAL parameters, D-016)."""
    enabled: bool = True
    f0_mmh: float = 25.0
    fmin_mmh: float = 2.0
    k_s1: float = 1.0 / 1800.0
    microstore_m: float = 0.002


@dataclass
class RunConfig:
    """Complete coupled-run configuration; validated and fingerprinted."""

    run_id: str
    scenario_id: str
    issue_time: datetime
    dem: np.ndarray
    cell_size_m: float = CELL_SIZE_M
    crs: str = WB_PROJECTED_CRS
    vertical_reference: str = VERTICAL_REFERENCE
    rainfall: RainfallSpec = field(default_factory=RainfallSpec)
    losses: LossSpec = field(default_factory=LossSpec)
    mannings_n: float = 0.03
    alpha: float = 0.5
    theta: float = 0.8
    h_init: float = 1e-6
    closed_boundaries: bool = False
    drainage_inp: Path = Path("data/demo/drainage_synthetic.inp")
    inlet_cells: list[tuple[int, int]] = field(default_factory=list)
    vent_cell: tuple[int, int] = (95, 79)
    dt_c: int = DT_C_DEFAULT
    surface_substeps: int = 5        # surface advance split per coupling stride (1 s sub-steps)
    duration_minutes: int = 180
    snapshot_interval_minutes: int = 5
    extent_threshold_m: float = 0.05   # documented, configurable, NOT a safety threshold
    cd: float = CD_ORIFICE
    ao_per_inlet: float = 0.002        # ASSUMED per-inlet opening area (m2)
    ao_vent: float | None = None    # default: ao_per_inlet * n_inlets
    external_inflow_m3s: float = 0.0
    artifact_dir: Path | None = None
    # M11 additive (no behaviour change when None): the projected top-left
    # corner (x, y) of the grid affine. When None the engine uses the
    # synthetic fixture affine (grid_affine()) exactly as before, so every
    # M1-M9 run is byte-identical. Set to the real-pilot grid origin to run
    # real terrain through the unchanged coupled engine.
    grid_origin_xy: tuple[float, float] | None = None

    def validate(self) -> None:
        dem = self.dem
        if not isinstance(dem, np.ndarray) or dem.ndim != 2 or min(dem.shape) < 3:
            raise CouplingError("dem must be a 2D array of at least 3x3")
        if not np.all(np.isfinite(dem)):
            raise CouplingError("dem contains non-finite values")
        if not isinstance(self.dt_c, int) or self.dt_c < 1:
            raise CouplingError(f"coupling timestep must be a positive integer, got {self.dt_c}")
        if not isinstance(self.surface_substeps, int) or self.surface_substeps < 1:
            raise CouplingError("surface_substeps must be a positive integer")
        if self.dt_c % self.surface_substeps != 0:
            raise CouplingError("dt_c must be divisible by surface_substeps")
        if self.duration_minutes <= 0 or self.duration_minutes % self.rainfall.interval_minutes != 0:
            raise CouplingError("duration_minutes must be a positive multiple of the rainfall interval")
        if self.snapshot_interval_minutes <= 0 or self.snapshot_interval_minutes * 60 % self.dt_c != 0:
            raise CouplingError("snapshot interval must align with the coupling timestep")
        if self.duration_minutes % self.snapshot_interval_minutes != 0:
            raise CouplingError("duration must be a multiple of the snapshot interval")
        if self.extent_threshold_m <= 0:
            raise CouplingError("extent threshold must be positive")
        if self.cell_size_m <= 0 or self.ao_per_inlet < 0 or self.cd < 0:
            raise CouplingError("cell size must be positive; orifice coefficient/area must be non-negative")
        if self.ao_vent is not None and self.ao_vent < 0:
            raise CouplingError("vent opening area must be non-negative")
        if self.issue_time.tzinfo is None:
            raise CouplingError("issue_time must be timezone-aware")
        if not self.drainage_inp.exists():
            raise CouplingError(f"drainage INP missing: {self.drainage_inp}")
        h, w = dem.shape
        for cell in self.inlet_cells:
            r, c = cell
            if not (0 < r < h - 1 and 0 < c < w - 1):
                raise CouplingError(f"inlet cell {cell} must be interior of {dem.shape}")
        vr, vc = self.vent_cell
        if not (0 < vr < h - 1 and 0 < vc < w - 1):
            raise CouplingError(f"vent cell {self.vent_cell} must be interior of {dem.shape}")
        if len(set(self.inlet_cells)) != len(self.inlet_cells) or self.vent_cell in set(self.inlet_cells):
            raise CouplingError("inlet cells must be unique and distinct from the vent cell")
        if self.rainfall.kind == "profile":
            n = self.duration_minutes // self.rainfall.interval_minutes
            if len(self.rainfall.intensities_mmh) != n:
                raise CouplingError(f"profile needs {n} intensities, got {len(self.rainfall.intensities_mmh)}")
            if any(not math.isfinite(v) or v < 0 for v in self.rainfall.intensities_mmh):
                raise CouplingError("rainfall intensities must be finite and non-negative")
        elif self.rainfall.kind in ("uniform", "spatial"):
            if (
                len(self.rainfall.intensities_mmh) != 1
                or not math.isfinite(self.rainfall.intensities_mmh[0])
                or self.rainfall.intensities_mmh[0] < 0
            ):
                raise CouplingError("uniform/spatial rainfall needs one finite, non-negative intensity")
        elif self.rainfall.kind == "explicit_fields":
            n = self.duration_minutes // self.rainfall.interval_minutes
            fields = self.rainfall.explicit_fields_mmh
            if fields is None:
                raise CouplingError("explicit_fields rainfall requires explicit_fields_mmh")
            if len(fields) != n:
                raise CouplingError(f"explicit_fields needs {n} fields, got {len(fields)}")
            for i, arr in enumerate(fields):
                if not isinstance(arr, np.ndarray) or arr.ndim != 2:
                    raise CouplingError(f"explicit rainfall field {i} must be a 2D numpy array")
                if arr.shape != dem.shape:
                    raise CouplingError(
                        f"explicit rainfall field {i} has shape {arr.shape}, expected {dem.shape}"
                    )
                if np.any(arr < 0):
                    raise CouplingError(f"explicit rainfall field {i} contains negative rates")
                if not np.all(np.isfinite(arr)):
                    raise CouplingError(f"explicit rainfall field {i} contains non-finite values")
        elif self.rainfall.kind != "zero":
            raise CouplingError(f"unknown rainfall kind: {self.rainfall.kind}")
        if self.losses.enabled and not (
            self.losses.f0_mmh >= self.losses.fmin_mmh >= 0
            and self.losses.k_s1 > 0
            and self.losses.microstore_m >= 0
        ):
            raise CouplingError("invalid loss parameters")

    def fingerprint(self) -> str:
        rainfall_payload = dict(self.rainfall.__dict__)
        # Invariant: the fingerprint payload for legacy rainfall kinds must
        # stay byte-identical to the pre-M9 format. explicit_fields_mmh is
        # therefore only serialised when present; adding "…": null would
        # change every legacy M4 fingerprint.
        if self.rainfall.explicit_fields_mmh is not None:
            rainfall_payload["explicit_fields_mmh"] = [
                {
                    "field_hash": sha256_bytes(np.ascontiguousarray(arr).tobytes()),
                    "shape": list(arr.shape),
                    "dtype": str(arr.dtype),
                    "rate_mean_mmh": round(float(np.mean(arr)), 8),
                    "rate_max_mmh": round(float(np.max(arr)), 8),
                    "rate_min_mmh": round(float(np.min(arr)), 8),
                }
                for arr in self.rainfall.explicit_fields_mmh
            ]
        else:
            rainfall_payload.pop("explicit_fields_mmh", None)
        payload = {
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "issue_time": self.issue_time.isoformat(),
            "dem_sha256": sha256_bytes(np.ascontiguousarray(self.dem, dtype=np.float64).tobytes()),
            "cell_size_m": self.cell_size_m,
            "crs": self.crs,
            "vertical_reference": self.vertical_reference,
            "rainfall": rainfall_payload,
            "losses": self.losses.__dict__,
            "mannings_n": self.mannings_n,
            "alpha": self.alpha,
            "theta": self.theta,
            "h_init": self.h_init,
            "closed_boundaries": self.closed_boundaries,
            "drainage_inp_sha256": sha256_file(self.drainage_inp),
            "inlet_cells": sorted(self.inlet_cells),
            "vent_cell": self.vent_cell,
            "dt_c": self.dt_c,
            "surface_substeps": self.surface_substeps,
            "duration_minutes": self.duration_minutes,
            "snapshot_interval_minutes": self.snapshot_interval_minutes,
            "extent_threshold_m": self.extent_threshold_m,
            "cd": self.cd,
            "ao_per_inlet": self.ao_per_inlet,
            "ao_vent": self.ao_vent,
            "external_inflow_m3s": self.external_inflow_m3s,
            "model_version": MODEL_VERSION,
        }
        if self.grid_origin_xy is not None:
            payload["grid_origin_xy"] = self.grid_origin_xy
        canon = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canon.encode("utf-8")).hexdigest()

    @property
    def vent_area(self) -> float:
        return self.ao_vent if self.ao_vent is not None else self.ao_per_inlet * max(len(self.inlet_cells), 1)

    def model_affine(self) -> Affine:
        """Grid affine for this run (M11 additive).

        Returns the synthetic fixture affine when ``grid_origin_xy`` is None
        (byte-identical to the pre-M11 engine), otherwise a north-up
        pixel-is-area affine anchored at the supplied projected origin.
        """
        if self.grid_origin_xy is None:
            return grid_affine()
        ox, oy = self.grid_origin_xy
        return Affine(self.cell_size_m, 0.0, ox, 0.0, -self.cell_size_m, oy)


# ---------------------------------------------------------------------------
# Ledger (M3 structure + microstore; exchange still cancels)
# ---------------------------------------------------------------------------

@dataclass
class RunLedger(CoupledLedger):
    """CoupledLedger extended with the M4 micro-depression store and the
    documented M2 boundary-film bound for dry runs. Residual identities
    follow MODEL_ASSUMPTIONS §8 (V_microstore,final on the output side).
    With microstore disabled the identities reduce exactly to M3's."""

    microstore_final_m3: float = 0.0
    film_bound_m3: float = 0.0

    @property
    def residual_surface(self) -> float:
        return (self.rain_m3 - self.losses_m3 - self.surf_out_m3 - self.S2D_m3
                + self.D2S_m3 + self.flood_export_m3
                - (self.S_s1 - self.S_s0) - self.microstore_final_m3)

    @property
    def residual_total(self) -> float:
        return (self.rain_m3 + self.ext_in_m3 - self.losses_m3 - self.surf_out_m3
                - self.outfall_m3 - (self.S_s1 - self.S_s0) - (self.S_d1 - self.S_d0)
                - self.microstore_final_m3)

    def status(self) -> str:
        """M3 gates plus a documented dry-run allowance: with zero forcing,
        the only possible residual is the M2 h_init boundary film
        (a bounded virtual-water source of ~film_volume m3, audit §5.4),
        so dry runs pass within film_bound_m3. Non-dry behaviour unchanged."""
        if self.rain_m3 == 0 and self.ext_in_m3 == 0:
            return "pass" if abs(self.residual_total) <= self.film_bound_m3 + 1e-6 else "fail"
        rel = self.relative_total()
        if rel is None or not math.isfinite(rel):
            return "fail"
        if rel <= PASS_REL:
            return "pass"
        if rel <= WARN_REL:
            return "warning"
        return "fail"


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class M4RunResult:
    config: RunConfig
    snapshots: list[FloodSnapshot]
    depth_arrays: dict[int, np.ndarray]          # lead_minutes -> depth (m)
    ledger: RunLedger
    mass_balance: MassBalance
    peak_depth_m: float
    max_flooded_area_m2: float
    time_to_peak_min: float
    max_st1_head_m: float
    wall_seconds: float
    cpu_seconds: float
    peak_rss_mb: float
    n_coupling_steps: int
    simulation_run: SimulationRun


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class CoupledFloodModel:
    """The M4 coupled simulation engine (fixture-scale, deterministic)."""

    def __init__(self, config: RunConfig) -> None:
        config.validate()
        self.config = config

    # -- helpers --------------------------------------------------------------
    @staticmethod
    def _add_depth(surface: SurfaceModel, cell: tuple[int, int], depth_m: float) -> None:
        h = surface.depth
        h[cell] += depth_m
        if h[cell] < -1e-12:
            raise CouplingError(f"negative depth {h[cell]:.3e} m at cell {cell} after exchange")

    @staticmethod
    def _remove_depth(surface: SurfaceModel, cell: tuple[int, int], depth_m: float) -> None:
        h = surface.depth
        if h[cell] < depth_m - 1e-12:
            raise CouplingError(f"removing {depth_m:.3e} m from cell {cell} with only {h[cell]:.3e} m available")
        h[cell] -= depth_m

    def _build_fields(self) -> list[np.ndarray]:
        cfg = self.config
        shape = cfg.dem.shape
        n = cfg.duration_minutes // cfg.rainfall.interval_minutes
        if cfg.rainfall.kind == "zero":
            return [np.zeros(shape, dtype=np.float32) for _ in range(n)]
        if cfg.rainfall.kind == "uniform":
            r = cfg.rainfall.intensities_mmh[0]
            return [render_interval(shape, "uniform", r, i, cfg.rainfall.seed) for i in range(n)]
        if cfg.rainfall.kind == "spatial":
            r = cfg.rainfall.intensities_mmh[0]
            return [render_interval(shape, cfg.rainfall.pattern, r, i, cfg.rainfall.seed) for i in range(n)]
        if cfg.rainfall.kind == "explicit_fields":
            assert cfg.rainfall.explicit_fields_mmh is not None  # validated earlier
            return [np.asarray(field, dtype=np.float32).copy() for field in cfg.rainfall.explicit_fields_mmh]
        return [
            render_interval(shape, cfg.rainfall.pattern, v, i, cfg.rainfall.seed)
            for i, v in enumerate(cfg.rainfall.intensities_mmh)
        ]

    def _grid_spec(self) -> GridSpec:
        cfg = self.config
        a = cfg.model_affine()
        return GridSpec(
            grid_id=f"{cfg.run_id}_grid",
            crs_wkt_or_epsg=cfg.crs,
            vertical_crs=cfg.vertical_reference,
            width=cfg.dem.shape[1],
            height=cfg.dem.shape[0],
            affine_transform=[a.a, a.b, a.c, a.d, a.e, a.f],
            cell_size_m=cfg.cell_size_m,
            nodata=None,
            bounds=[a.c, a.f - cfg.dem.shape[0] * cfg.cell_size_m,
                    a.c + cfg.dem.shape[1] * cfg.cell_size_m, a.f],
        )

    # -- main loop ------------------------------------------------------------
    def run(self) -> M4RunResult:
        from pyswmm import Links, Nodes, Simulation
        from pyswmm.swmm5 import PYSWMMException

        cfg = self.config
        t_wall0 = _time.perf_counter()
        n_steps = int(cfg.duration_minutes * 60 / cfg.dt_c)
        out_every = int(cfg.snapshot_interval_minutes * 60 / cfg.dt_c)
        interval_s = cfg.rainfall.interval_minutes * 60
        dt = cfg.dt_c

        surface = SurfaceModel(
            cfg.dem,
            cell_size_m=cfg.cell_size_m,
            mannings_n=cfg.mannings_n,
            alpha=cfg.alpha,
            theta=cfg.theta,
            h_init=cfg.h_init,
            closed_boundaries=cfg.closed_boundaries,
        )
        core = surface.core.reshape(surface.shape)
        horton = HortonLoss(
            f0_ms=cfg.losses.f0_mmh / 3600000.0,
            fmin_ms=cfg.losses.fmin_mmh / 3600000.0,
            k_s1=cfg.losses.k_s1,
        )
        microstore = np.zeros(surface.shape)
        cap_micro = cfg.losses.microstore_m
        wet = np.zeros(surface.shape)
        fields = self._build_fields()
        grid_spec = self._grid_spec()

        led = RunLedger(film_bound_m3=surface.film_volume_m3)
        led.S_s0 = surface.surface_storage_m3()
        output_manifest_uri: str | None = None

        snapshots: list[FloodSnapshot] = []
        depth_arrays: dict[int, np.ndarray] = {}
        max_st1_head = -1e18
        peak_depth = 0.0
        max_flooded_area = 0.0
        time_to_peak = 0.0

        def _snapshot(lead_min: int, st1_head_m: float, st1_depth_m: float) -> None:
            nonlocal peak_depth, max_flooded_area, time_to_peak
            depth = surface.depth.copy()
            wet_mask = depth > cfg.extent_threshold_m
            flooded_cells = int(np.count_nonzero(wet_mask))
            flooded_area = flooded_cells * surface.cell_area_m2
            if depth.max() > peak_depth:
                peak_depth = float(depth.max())
                time_to_peak = float(lead_min)
            max_flooded_area = max(max_flooded_area, flooded_area)
            vent_depth = float(surface.depth[cfg.vent_cell])
            snapshots.append(
                FloodSnapshot(
                    snapshot_id=f"{cfg.run_id}_t{lead_min:03d}",
                    simulation_id=cfg.run_id,
                    run_id=cfg.run_id,
                    valid_time=cfg.issue_time + timedelta(minutes=lead_min),
                    lead_minutes=lead_min,
                    grid=grid_spec,
                    max_depth_m=float(depth.max()),
                    mean_depth_m=float(depth[core].mean()),
                    flooded_cells=flooded_cells,
                    flooded_area_m2=flooded_area,
                    extent_threshold_m=cfg.extent_threshold_m,
                    total_surface_storage_m3=surface.surface_storage_m3(),
                    drainage=DrainageStateSummary(
                        st1_head_m=float(st1_head_m),
                        st1_depth_m=float(st1_depth_m),
                        vent_depth_m=vent_depth,
                        vent_head_m=float(surface.dem[cfg.vent_cell] + vent_depth),
                        outfall_cum_m3=led.outfall_m3,
                        flooding_cum_m3=led.flood_export_m3,
                        exchange_S2D_cum_m3=led.S2D_m3,
                        exchange_D2S_cum_m3=led.D2S_m3,
                        surcharged=float(st1_head_m) > float(surface.dem[cfg.vent_cell]),
                    ),
                    quality_flags=[QualityFlag.SYNTHETIC, QualityFlag.PROVISIONAL],
                )
            )
            depth_arrays[lead_min] = depth

        with Simulation(str(cfg.drainage_inp)) as sim:
            sim.step_advance(dt)
            try:
                st1 = Nodes(sim)["ST1"]
                o1 = Nodes(sim)["O1"]
                c1 = Links(sim)["C1"]
                c2 = Links(sim)["C2"]
                vent_node = Nodes(sim)["V1"]
            except Exception as e:
                raise CouplingError(f"required SWMM object missing in {cfg.drainage_inp}: {e}") from e
            try:
                flood_node = Nodes(sim)["J1"]
            except PYSWMMException:
                flood_node = None

            st1_invert = float(st1.invert_elevation)
            prev_flood = 0.0
            prev_q_out = 0.0
            prev_s2d_rate = 0.0
            prev_d2s_rate = 0.0
            prev_ext_rate = 0.0

            # initial snapshot (dry state, lead 0)
            _snapshot(0, float(st1.head), float(st1.head) - st1_invert)

            last_i = -1
            for i, _ in enumerate(sim):
                last_i = i
                if i >= n_steps + 1:
                    break
                t = (i + 1) * dt

                # 1-2. read post-stride SWMM state; export flooding + outfall
                flood_i = float(flood_node.flooding) if flood_node is not None else 0.0
                q_out_i = float(o1.total_inflow)
                H_d = float(st1.head)
                max_st1_head = max(max_st1_head, H_d)

                stride_flood = (flood_i + prev_flood) / 2.0 * dt
                if stride_flood < -1e-12:
                    raise CouplingError(f"negative flooding export {stride_flood:.3e} m3 at t={t} s")
                self._add_depth(surface, cfg.vent_cell, stride_flood / surface.cell_area_m2)
                led.flood_export_m3 += stride_flood
                prev_flood = flood_i

                stride_out = (q_out_i + prev_q_out) / 2.0 * dt
                led.outfall_m3 += stride_out
                prev_q_out = q_out_i

                # 3. drainage storage via SWMM's own per-stride identity
                led.S_d1 += (prev_ext_rate + prev_s2d_rate - prev_d2s_rate) * dt - stride_out - stride_flood

                if i >= n_steps:
                    break

                # 5. rainfall (bucket of the stride start) -> microstore -> Horton
                idx = min(int((t - dt) // interval_s), len(fields) - 1)
                field_mmh = fields[idx]
                field_ms = field_mmh / 3600000.0
                avail = field_ms * dt
                if cfg.losses.enabled:
                    fill = np.minimum(cap_micro - microstore, avail)
                    microstore += fill
                    rem = avail - fill
                else:
                    rem = avail
                # rainfall_input counts the FULL rainfall; the microstore share is
                # accounted on the output side of the identity (RunLedger).
                led.rain_m3 += float(np.sum(avail[core])) * surface.cell_area_m2
                surface.apply_rainfall(rem / dt, dt)
                if cfg.losses.enabled:
                    wet[core] += dt * (field_ms[core] > 0)
                    led.losses_m3 += surface.apply_infiltration(horton.capacity(wet), dt)

                # 6. surface routing (sub-stepped: 30 m cells at dt_c=5 s can
                #    trip the M2 wet-dry-front fail-fast on sharp convective
                #    gradients; 1.25 s sub-steps stay inside the documented
                #    clamp band. surface_substeps=1 reproduces M3 exactly.)
                surf_dt = dt / cfg.surface_substeps
                for _ in range(cfg.surface_substeps):
                    surface.step(surf_dt)

                # 7. signed exchange from aligned states (M3 semantics,
                #    generalized to multiple sites: capture at each inlet and
                #    return at the vent are independent head-driven orifices;
                #    both may be active in the same stride — inlets keep
                #    admitting while the manhole spills, which is the physical
                #    multi-site behaviour the M3 single-point driver could not
                #    represent. Per-site laws, caps and causality are M3's.)
                eta_v = float(surface.dem[cfg.vent_cell] + surface.depth[cfg.vent_cell])
                q_cap_total = 0.0
                for cell in cfg.inlet_cells:
                    eta_s = float(surface.dem[cell] + surface.depth[cell])
                    # capture-only leg: negative orifice rates (drainage head
                    # above the inlet surface) never extract from SWMM here —
                    # the ONLY reverse path is the vent-driven q_back below
                    # (M3 semantics: reverse uses the vent head, not the
                    # inlet's; a negative per-inlet rate would silently remove
                    # water from SWMM with no ledger entry).
                    q_i = max(orifice_exchange_rate(eta_s, H_d, cfg.cd, cfg.ao_per_inlet), 0.0)
                    if q_i > 0 and flood_i > 0:
                        q_i = 0.0  # inlet regime rule (M3)
                    if q_i > 0:
                        avail_cell = float(surface.depth[cell]) * surface.cell_area_m2
                        q_i = min(q_i, avail_cell / dt)
                        if q_i > 0:
                            self._remove_depth(surface, cell, q_i * dt / surface.cell_area_m2)
                    q_cap_total += q_i

                q_back = max(0.0, orifice_exchange_rate(H_d, eta_v, cfg.cd, cfg.vent_area))
                q_back = min(q_back, float(st1.volume) / dt)
                s2d = max(q_cap_total, 0.0) * dt
                d2s = q_back * dt
                led.S2D_m3 += s2d
                led.D2S_m3 += d2s
                if d2s > 0:
                    self._add_depth(surface, cfg.vent_cell, d2s / surface.cell_area_m2)

                # 8. drive SWMM for the next stride
                st1.generated_inflow(q_cap_total - q_back + cfg.external_inflow_m3s)
                led.ext_in_m3 += cfg.external_inflow_m3s * dt
                prev_s2d_rate = s2d / dt
                prev_d2s_rate = d2s / dt
                prev_ext_rate = cfg.external_inflow_m3s

                if not (math.isfinite(s2d) and math.isfinite(d2s)):
                    raise CouplingError("non-finite exchange volume")

                # 9. snapshot if scheduled
                if (i + 1) % out_every == 0:
                    _snapshot((i + 1) * dt // 60, float(st1.head), float(st1.head) - st1_invert)

            if last_i < n_steps:
                raise CouplingError(f"SWMM simulation ended prematurely at stride {last_i}, expected at least {n_steps}")

            led.flow_routing_error_pct = float(sim.flow_routing_error)
            led.S_s1 = surface.surface_storage_m3()
            led.S_d1_readback = self._drain_storage(st1, vent_node, c1, c2)

            # final snapshot at lead = duration (state after the last stride);
            # skipped when the last loop snapshot already covers it
            if cfg.duration_minutes not in depth_arrays:
                _snapshot(cfg.duration_minutes, float(st1.head), float(st1.head) - st1_invert)

        led.surf_out_m3 = surface.boundary_outflow_m3
        led.microstore_final_m3 = float(np.sum(microstore[core]) * surface.cell_area_m2)

        mass_balance = MassBalance(
            interval_start=cfg.issue_time,
            interval_end=cfg.issue_time + timedelta(minutes=cfg.duration_minutes),
            rainfall_input_m3=led.rain_m3,
            external_inflow_m3=led.ext_in_m3,
            infiltration_loss_m3=led.losses_m3,
            surface_boundary_outflow_m3=led.surf_out_m3,
            drainage_outfall_m3=led.outfall_m3,
            initial_surface_storage_m3=led.S_s0,
            final_surface_storage_m3=led.S_s1,
            initial_drain_storage_m3=led.S_d0,
            final_drain_storage_m3=led.S_d1,
            residual_m3=led.residual_total,
            relative_error=led.relative_total(),
            status=led.status(),
        )


        wall = _time.perf_counter() - t_wall0
        ru = resource.getrusage(resource.RUSAGE_SELF)
        cpu = ru.ru_utime + ru.ru_stime
        rss_mb = ru.ru_maxrss / 1024.0


        # -- artifacts (optional; deterministic) ------------------------------
        if cfg.artifact_dir is not None:
            ad = Path(cfg.artifact_dir)
            ad.mkdir(parents=True, exist_ok=True)
            import rasterio

            for lead in sorted(depth_arrays):
                arr = depth_arrays[lead].astype(np.float32)
                a = cfg.model_affine()
                tif = ad / f"depth_t{lead:03d}.tif"
                with rasterio.open(
                    tif, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1],
                    count=1, dtype="float32", crs=cfg.crs, transform=a, compress="deflate",
                ) as dst:
                    dst.write(arr, 1)
                    dst.update_tags(
                        ARENA_PROVENANCE="MODEL_PREDICTION",
                        ARENA_QUALITY="SYNTHETIC PROVISIONAL",
                        ARENA_VALID_TIME=(cfg.issue_time + timedelta(minutes=lead)).isoformat(),
                        ARENA_EXTENT_THRESHOLD_M=str(cfg.extent_threshold_m),
                        ARENA_SIMULATION_ID=cfg.run_id,
                    )
                for snap in snapshots:
                    if snap.lead_minutes == lead:
                        snap.depth_asset_uri = str(tif)
            summary_path = ad / "run_summary.json"
            summary_path.write_text(
                json.dumps(
                    {
                        "run_id": cfg.run_id,
                        "scenario_id": cfg.scenario_id,
                        "fingerprint": cfg.fingerprint(),
                        "mass_balance": mass_balance.model_dump(mode="json"),
                        "metrics": {
                            "peak_depth_m": peak_depth,
                            "max_flooded_area_m2": max_flooded_area,
                            "time_to_peak_min": time_to_peak,
                            "max_st1_head_m": float(max_st1_head),
                            "total_S2D_m3": led.S2D_m3,
                            "total_D2S_m3": led.D2S_m3,
                            "total_outfall_m3": led.outfall_m3,
                            "wall_seconds": wall,
                            "peak_rss_mb": rss_mb,
                        },
                        "labels": ["SYNTHETIC", "SIMULATED", "PROVISIONAL"],
                    },
                    indent=2,
                    sort_keys=True,
                    default=str,
                )
            )
            output_manifest_uri = str(summary_path)




        sim_run = SimulationRun(
            simulation_id=cfg.run_id,
            run_id=cfg.run_id,
            created_at=cfg.issue_time,
            forecast_issue_time=cfg.issue_time,
            mode="demo",
            scenario_id=cfg.scenario_id,
            status="succeeded",
            start_time=cfg.issue_time,
            end_time=cfg.issue_time + timedelta(minutes=cfg.duration_minutes),
            simulation_timestep_s=float(dt),  # surface solver sub-steps internally
            coupling_timestep_s=cfg.dt_c,
            output_interval_minutes=cfg.snapshot_interval_minutes,
            grid_spec=grid_spec,
            rainfall_source=cfg.rainfall.kind,
            configuration_fingerprint=cfg.fingerprint(),
            input_manifest={
                "dem_sha256": sha256_bytes(np.ascontiguousarray(cfg.dem, dtype=np.float64).tobytes()),
                "drainage_inp_sha256": sha256_file(cfg.drainage_inp),
                "rainfall_kind": cfg.rainfall.kind,
                "rainfall_pattern": cfg.rainfall.pattern,
                "rainfall_seed": cfg.rainfall.seed,
            },
            model_versions={"landlab": "2.11.0", "pyswmm": "2.1.0", "engine": MODEL_VERSION},
            output_manifest_uri=output_manifest_uri,
            parameters={
                "dt_c": cfg.dt_c,
                "cd": cfg.cd,
                "ao_per_inlet": cfg.ao_per_inlet,
                "ao_vent": cfg.vent_area,
                "extent_threshold_m": cfg.extent_threshold_m,
                "n_inlets": len(cfg.inlet_cells),
            },
        )

        return M4RunResult(
            config=cfg,
            snapshots=snapshots,
            depth_arrays=depth_arrays,
            ledger=led,
            mass_balance=mass_balance,
            peak_depth_m=peak_depth,
            max_flooded_area_m2=max_flooded_area,
            time_to_peak_min=time_to_peak,
            max_st1_head_m=float(max_st1_head),
            wall_seconds=wall,
            cpu_seconds=cpu,
            peak_rss_mb=rss_mb,
            n_coupling_steps=n_steps,
            simulation_run=sim_run,
        )

    @staticmethod
    def _drain_storage(st1, vent, c1, c2) -> float:
        return float(st1.volume) + float(vent.volume) + float(c1.volume) + float(c2.volume)


# ---------------------------------------------------------------------------
# M4 scenario configurations (provisional rainfall; M5 formalizes)
# ---------------------------------------------------------------------------

def fixture_inlet_cells(dem: np.ndarray | None = None) -> list[tuple[int, int]]:
    """16 deterministic rim inlet cells with beds in [22.10, 22.30] m — ABOVE
    the synthetic basin's peak flood line (~22.05 m), so the drainage capture
    equilibrium head in the blocked case rises above the flooded vent cell.
    SYNTHETIC mapping; per-inlet orifice Ao = 0.002-0.003 m2 (ASSUMED
    grate-scale opening). Rationale documented in docs/M4_COUPLED_MODEL.md §11."""
    if dem is None:
        from services.ingestion.dem import synthetic_dem as _dem

        dem = _dem()
    cy, cx = 96, 74  # basin centre (SYNTHETIC)
    cands = []
    for r in range(dem.shape[0]):
        for c in range(dem.shape[1]):
            d = max(abs(r - cy), abs(c - cx))
            if 4 <= d <= 9 and 22.10 <= dem[r, c] <= 22.30:
                cands.append((round(float(dem[r, c]), 3), r, c))
    cands.sort()
    return [(r, c) for _, r, c in cands[:16]]


FIXTURE_VENT_CELL = (95, 79)  # basin rim cell, bed ~21.9 m (SYNTHETIC)
M4_DATUM_OFFSET_M = 10.0      # shifts SWMM fixture onto the DEM local datum (B08)


def m4_scenario_configs(
    dem: np.ndarray,
    issue_time: datetime,
    artifact_dir: Path | None = None,
    clean_inp: Path = Path("data/demo/drainage_synthetic_m4.inp"),
    blocked_inp: Path = Path("data/demo/drainage_synthetic_m4_blocked.inp"),
) -> dict[str, RunConfig]:
    """M4 scenario suite: zero, uniform, spatial, heavy, heavy_blocked.
    Identical everything except the labelled difference."""
    from services.rainfall.scenarios import build_profile

    heavy_profile = build_profile("heavy", 45.0)
    base = {
        "issue_time": issue_time,
        "dem": dem,
        "inlet_cells": fixture_inlet_cells(dem),
        "vent_cell": FIXTURE_VENT_CELL,
        "dt_c": 5,
        "duration_minutes": 180,
        "snapshot_interval_minutes": 5,
        "extent_threshold_m": 0.05,
    }
    return {
        "zero": RunConfig(
            run_id=f"m4_zero_{issue_time:%Y%m%dT%H%M%SZ}", scenario_id="zero",
            rainfall=RainfallSpec(kind="zero"),
            drainage_inp=clean_inp,  # datum-shifted fixture for EVERY scenario (B08)
            **base,
        ),
        "uniform": RunConfig(
            run_id=f"m4_uniform_{issue_time:%Y%m%dT%H%M%SZ}", scenario_id="uniform",
            rainfall=RainfallSpec(kind="uniform", intensities_mmh=[10.0]),
            drainage_inp=clean_inp, **base,
        ),
        "spatial": RunConfig(
            run_id=f"m4_spatial_{issue_time:%Y%m%dT%H%M%SZ}", scenario_id="spatial",
            rainfall=RainfallSpec(kind="spatial", intensities_mmh=[20.0], pattern="convective_cell"),
            drainage_inp=clean_inp, **base,
        ),
        "heavy": RunConfig(
            run_id=f"m4_heavy_{issue_time:%Y%m%dT%H%M%SZ}", scenario_id="heavy",
            rainfall=RainfallSpec(kind="profile", intensities_mmh=heavy_profile.intensities_mmh,
                                  pattern="convective_cell"),
            drainage_inp=clean_inp,
            artifact_dir=artifact_dir, **base,
        ),
        "heavy_blocked": RunConfig(
            run_id=f"m4_heavy_blocked_{issue_time:%Y%m%dT%H%M%SZ}", scenario_id="heavy_blocked",
            rainfall=RainfallSpec(kind="profile", intensities_mmh=heavy_profile.intensities_mmh,
                                  pattern="convective_cell"),
            drainage_inp=blocked_inp,
            artifact_dir=artifact_dir, **base,
        ),
    }
