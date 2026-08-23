"""Landlab OverlandFlow adapter — D-019 / M2 (IMPLEMENTATION_SPEC §4 B06).

Component verified facts (Landlab 2.11.0, OverlandFlow / de Almeida 2012):
- `rainfall_intensity` is a uniform SCALAR; spatial rain must be applied by
  the adapter per cell (D-019).
- Node update is `h[core] += (rain - div(q)) * dt` — boundary-node depths are
  never updated, so water crossing boundary links leaves the domain by
  construction.
- `calc_time_step()` provides the adaptive CFL-safe dt; `run_one_step(dt)` may
  internally sub-step, and the exposed `surface_water__discharge` link field
  holds only the LAST sub-step's unit-width discharge (m2/s). Therefore
  boundary outflow is measured by the exact residual identity instead:
      outflow_step = V_core(post-rain, before step) - V_core(after step).
  Verified closure on the spike plane: rain - outflow - dV = film volume.
- The `h_init` thin film participates in link-flux friction (h clipped to
  h_init at links). On CLOSED grids it redistributes ~film_volume of water
  (n_core * h_init * A) with zero net bias. On OPEN grids the film acts as a
  bounded virtual-water source of ~film_volume per wetting event (measured on
  the spike plane: residual = -film_volume exactly). With h_init = 1e-6 this
  is < 0.01% of a 45 mm event on the 30 m fixture grid; it remains visible in
  the ledger residual and is reported — never silently absorbed.

HIGH-RISK AI AREA (audit §14): all claims above are proven by the M2 spike
tests in tests/test_landlab_spike.py; do not relax those tests.
"""

from __future__ import annotations

import numpy as np

# Wet-dry-front stability ratio (s per m of cell size). Measured on the M2
# spike grid (10 m cells): the de Almeida storage-cell scheme produces small
# negative depths at wet-dry fronts once dt/dx > ~0.5 s/m (zero negatives at
# dt<=5 s; -4.5e-6 m at 10 s; -1e-4 m at 15 s). The adapter therefore caps
# the timestep at 0.5 * cell_size_m by default. A residual clamp band of
# 0.1 mm exists for numerical dust only; every clamped volume is counted
# into solver_mass_bias_m3 and anything deeper fails the run.
MAX_DT_PER_METRE_S = 0.5
EPS_NEGATIVE_CLAMP_M = 1e-4
H_INIT_DEFAULT = 1e-6


class HortonLoss:
    """Horton infiltration capacity f(t) = fmin + (f0 - fmin) * exp(-k t).

    Per-cell wetting clocks advance only while rainfall is applied to the cell
    (documented simplification per MODEL_ASSUMPTIONS §3.2).
    """

    def __init__(self, f0_ms: float, fmin_ms: float, k_s1: float) -> None:
        if not (f0_ms >= fmin_ms >= 0 and k_s1 > 0):
            raise ValueError("Horton parameters invalid (f0 >= fmin >= 0, k > 0)")
        self.f0, self.fmin, self.k = f0_ms, fmin_ms, k_s1

    def capacity(self, wetting_time_s: np.ndarray) -> np.ndarray:
        return self.fmin + (self.f0 - self.fmin) * np.exp(-self.k * wetting_time_s)


class SurfaceModel:
    """2-D surface flow adapter around Landlab OverlandFlow."""

    def __init__(
        self,
        dem: np.ndarray,
        cell_size_m: float = 30.0,
        mannings_n: float | np.ndarray = 0.03,
        alpha: float = 0.5,
        theta: float = 0.8,
        h_init: float = H_INIT_DEFAULT,
        closed_boundaries: bool = False,
        max_dt_s: float = 30.0,
    ) -> None:
        from landlab import RasterModelGrid
        from landlab.components.overland_flow import OverlandFlow

        if dem.ndim != 2 or dem.shape[0] < 3 or dem.shape[1] < 3:
            raise ValueError("dem must be a 2D array of at least 3x3")
        if not np.all(np.isfinite(dem)):
            raise ValueError("dem must be finite")
        self.dem = dem.astype(np.float64)
        self.cell_size_m = float(cell_size_m)
        self.cell_area_m2 = self.cell_size_m**2
        self.shape = dem.shape
        self.closed_boundaries = bool(closed_boundaries)
        self.h_init = float(h_init)

        self.grid = RasterModelGrid(self.shape, xy_spacing=self.cell_size_m)
        if self.closed_boundaries:
            self.grid.set_closed_boundaries_at_grid_edges(True, True, True, True)
        self.grid.at_node["topographic__elevation"] = self.dem.ravel()
        h = np.zeros(self.grid.number_of_nodes)
        self.core = self.grid.status_at_node == self.grid.BC_NODE_IS_CORE
        h[~self.core] = self.h_init  # boundary film; FIXED_VALUE edges stay at film
        self.grid.at_node["surface_water__depth"] = h

        self.of = OverlandFlow(
            self.grid,
            h_init=self.h_init,
            alpha=alpha,
            mannings_n=mannings_n,
            theta=theta,
            rainfall_intensity=0.0,  # adapter applies rainfall explicitly (D-019)
        )
        self.max_dt_s = min(float(max_dt_s), MAX_DT_PER_METRE_S * self.cell_size_m)
        self.n_clamped = 0
        self.total_steps = 0
        self.boundary_outflow_m3 = 0.0
        self.solver_mass_bias_m3 = 0.0  # film/dry-cell mass creation, diagnostic only
        self.film_volume_m3 = float(np.count_nonzero(self.core)) * self.h_init * self.cell_area_m2

    # -- state ----------------------------------------------------------------
    @property
    def depth(self) -> np.ndarray:
        return self.grid.at_node["surface_water__depth"].reshape(self.shape)

    def surface_storage_m3(self) -> float:
        """Storage on core cells only (boundary film excluded)."""
        return float(np.sum(self.depth.ravel()[self.core]) * self.cell_area_m2)

    def calc_dt(self) -> float:
        """Adaptive stable dt (component CFL), bounded by max_dt_s."""
        from landlab.components.overland_flow.generate_overland_flow_deAlmeida import (
            NoWaterError,
        )

        try:
            dt = float(self.of.calc_time_step())
        except NoWaterError:
            dt = self.max_dt_s  # dry domain: no water to constrain dt
        return min(dt, self.max_dt_s)

    # -- forcing and losses (ledger-accounted) --------------------------------
    def apply_rainfall(self, rain_ms: float | np.ndarray, dt_s: float) -> float:
        """h += r*dt on CORE cells only (boundary film stays fixed);
        returns volume added (m3)."""
        r = np.broadcast_to(np.asarray(rain_ms, dtype=np.float64), self.shape).ravel()
        h = self.grid.at_node["surface_water__depth"]
        h[self.core] += r[self.core] * dt_s
        return float(np.sum(r[self.core]) * dt_s * self.cell_area_m2)

    def apply_infiltration(self, capacity_ms: float | np.ndarray, dt_s: float) -> float:
        """h -= min(f*dt, h) on core cells; returns volume removed (m3)."""
        f = np.broadcast_to(np.asarray(capacity_ms, dtype=np.float64), self.shape).ravel()
        h = self.grid.at_node["surface_water__depth"]
        removal = np.zeros_like(h)
        removal[self.core] = np.minimum(f[self.core] * dt_s, np.maximum(h[self.core], 0.0))
        self.grid.at_node["surface_water__depth"] = h - removal
        return float(np.sum(removal) * self.cell_area_m2)

    # -- integration ----------------------------------------------------------
    def step(self, dt_s: float) -> None:
        """One routing step. Accumulates exact boundary outflow via the
        residual identity; small negative steps are the documented h_init
        film/dry-cell artifact and are recorded as a diagnostic; material
        negative depth still fails fast (instability guard)."""
        h = self.grid.at_node["surface_water__depth"]
        v_before = float(np.sum(h[self.core]) * self.cell_area_m2)
        self.of.run_one_step(dt_s)
        v_after = float(np.sum(h[self.core]) * self.cell_area_m2)
        outflow_step = v_before - v_after
        if outflow_step >= 0.0:
            self.boundary_outflow_m3 += outflow_step
        else:
            self.solver_mass_bias_m3 += -outflow_step

        neg = h[self.core] < 0.0
        if neg.any():
            material = neg & (h[self.core] < -EPS_NEGATIVE_CLAMP_M)
            if material.any():
                raise RuntimeError(
                    f"material negative depth after routing step: min={h[self.core].min():.3e} m "
                    f"at {int(material.sum())} cells"
                )
            clamped_vol = float(np.sum(-h[self.core][neg]) * self.cell_area_m2)
            self.solver_mass_bias_m3 += clamped_vol  # wet-dry front artifact, accounted
            self.n_clamped += int(neg.sum())
            h[self.core] = np.maximum(h[self.core], 0.0)
        self.total_steps += 1
