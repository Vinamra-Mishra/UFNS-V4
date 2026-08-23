"""M3 two-way surface↔SWMM coupling spike driver (diagnostic, not the M4 engine).

EXCHANGE CONVENTION (ARCHITECTURE §7.7 / MODEL_ASSUMPTIONS §7.1):
  Q_ex > 0 means SURFACE -> DRAINAGE.
Two ledger terms, recorded once each, opposite signs in the two subsystem
ledgers, excluded from the combined ledger:
  S2D = surface capture  (m3)
  D2S = drainage return  (m3)

EXCHANGE MECHANISM (Phase 0 design direction, made concrete for the spike):
  A single signed head-driven orifice at the exchange node (ST1):
      Q_ex = Cd*Ao*sqrt(2g*|eta_s - H_d|) * sign(eta_s - H_d)
  * eta_s: water-surface elevation at the mapped surface cell (inlet cell for
    capture, vent cell for return — see ASYMMETRY note below)
  * H_d:   hydraulic head at ST1 (invert + depth)
  * capture  (Q_ex > 0): water removed from the inlet surface cell, applied to
    SWMM as +generated_inflow at ST1 for the next stride; capped by the water
    physically available in the inlet cell.
  * return   (Q_ex < 0): the head comparison uses the exchange node's head
    (ST1 — the manhole above the hydraulic bottleneck) against the vent
    cell's water surface: water emerges at ground level when the pipe at the
    coupling point is pressurized above the ASSUMED manhole ground level.
    Water is extracted from SWMM via -generated_inflow at ST1 (the storage
    whose volume is exactly known, giving an exact extraction cap) and placed
    on the vent cell. Hydraulic feedback propagates on the next stride.
    Documented spike simplification; the M4 real-network adapter will map the
    extraction to actual manhole nodes.
  * inlet regime rule: capture is suspended while the downstream junction is
    flooding (prevents pump-and-spill oscillation; documented, spike scope).

  ASYMMETRY (documented, deliberate): capture head uses the inlet cell vs ST1
  head (the inlet storage node); return head uses ST1 head vs the vent cell.
  Both are mapped elements of the same network; extraction always happens at
  ST1 where volume is exactly known. The M4 real-network adapter will map
  exchanges to actual inlets/manholes.

  ADDITIONALLY, SWMM's own surcharge flooding at the junction vent (Apond=0)
  is exported to the vent cell: this is real water SWMM drops, integrated by
  trapezoid on stride-endpoint rates (approximate on ramps — quantified in
  M3 tests; exactness of the orifice-ledger does not depend on it).

TIMESTEP: explicit, surface-first; dt_c is an integer number of seconds
(pyswmm 2.1 swmm_stride requires int). Both solvers advance dt_c per coupling
step; Landlab sub-steps internally, SWMM uses its internal 1 s routing step.

HIGH-RISK AI AREA (audit §14): all accounting claims are proven by the M3 test
matrix (tests/test_swmm_spike.py). Do not weaken those tests.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from services.hydraulics.fixture import AO_ORIFICE, CD_ORIFICE, G
from services.hydrology.surface import SurfaceModel

PASS_REL = 0.01
WARN_REL = 0.05
EPS_HEAD = 1e-6  # exchange dead-band (m): avoids sign chatter at zero head


class CouplingError(RuntimeError):
    """Explicit coupling failure — never silently clamped or continued."""


@dataclass
class ExchangeStep:
    t_s: float
    S2D_vol: float      # m3, positive = surface -> drainage
    D2S_vol: float      # m3, positive = drainage -> surface
    flood_export_vol: float  # m3, SWMM flooding exported to vent cell
    eta_s: float        # surface head at inlet cell (m)
    eta_v: float        # surface head at vent cell (m)
    H_d: float          # drainage head at ST1 (m)


@dataclass
class CoupledLedger:
    rain_m3: float = 0.0
    ext_in_m3: float = 0.0
    losses_m3: float = 0.0
    surf_out_m3: float = 0.0
    outfall_m3: float = 0.0
    S2D_m3: float = 0.0
    D2S_m3: float = 0.0
    flood_export_m3: float = 0.0
    S_s0: float = 0.0
    S_s1: float = 0.0
    S_d0: float = 0.0
    S_d1: float = 0.0          # identity-based (engine-exact)
    S_d1_readback: float = 0.0  # state readback (diagnostic; known SWMM quirk)
    flow_routing_error_pct: Optional[float] = None

    @property
    def readback_discrepancy(self) -> float:
        """Engine-identity storage minus state-readback storage. Documented
        SWMM 5.2.4 quirk: storage-node depth/volume readback under dynamic
        wave under-reports by ~10-15% while the engine's own continuity is
        exact (proven by the M3 fill-drain probe: 30.000 in / 30.003 out /
        0.000% continuity error)."""
        return (self.S_d1 - self.S_d0) - (self.S_d1_readback - self.S_d0)

    @property
    def residual_surface(self) -> float:
        # rain - losses - surf_out - S2D + (D2S + flood_export) - dS_s
        return (self.rain_m3 - self.losses_m3 - self.surf_out_m3 - self.S2D_m3
                + self.D2S_m3 + self.flood_export_m3 - (self.S_s1 - self.S_s0))

    @property
    def residual_drainage(self) -> float:
        # By construction ~0: dS_d is computed from SWMM's own per-stride
        # conservation identity (engine-exact; verified via flow_routing_error
        # and the fill-drain probe). The readback cross-check is reported
        # separately (readback_discrepancy).
        return (self.ext_in_m3 + self.S2D_m3 - self.D2S_m3 - self.flood_export_m3
                - self.outfall_m3 - (self.S_d1 - self.S_d0))

    @property
    def residual_total(self) -> float:
        # rain + ext_in - losses - surf_out - outfall - dS_s - dS_d
        # (flooding export and exchange are internal transfers and cancel)
        return (self.rain_m3 + self.ext_in_m3 - self.losses_m3 - self.surf_out_m3
                - self.outfall_m3 - (self.S_s1 - self.S_s0) - (self.S_d1 - self.S_d0))

    def relative_total(self) -> Optional[float]:
        scale = max(abs(self.rain_m3) + abs(self.ext_in_m3), 1e-6)
        return abs(self.residual_total) / scale

    def status(self) -> str:
        rel = self.relative_total()
        if rel is None or not math.isfinite(rel):
            return "fail"
        if rel <= PASS_REL or (abs(self.residual_total) <= 1e-6 and self.rain_m3 == 0 and self.ext_in_m3 == 0):
            return "pass"
        if rel <= WARN_REL:
            return "warning"
        return "fail"


def orifice_exchange_rate(eta_s: float, H_d: float, cd: float = CD_ORIFICE, ao: float = AO_ORIFICE) -> float:
    """Signed orifice exchange (m3/s): + = surface->drainage, - = drainage->surface."""
    dh = eta_s - H_d
    if abs(dh) <= EPS_HEAD:
        return 0.0
    return math.copysign(cd * ao * math.sqrt(2.0 * G * abs(dh)), dh)


class CoupledSpike:
    """Two-way coupled spike run: Landlab surface <-> synthetic SWMM network."""

    def __init__(
        self,
        surface: SurfaceModel,
        inp_path: Path,
        inlet_cell: tuple[int, int],
        vent_cell: tuple[int, int],
        dt_c: int,
        cd: float = CD_ORIFICE,
        ao: float = AO_ORIFICE,
    ) -> None:
        if dt_c < 1 or not isinstance(dt_c, int):
            raise CouplingError(f"coupling timestep must be a positive integer number of seconds, got {dt_c}")
        self.surface = surface
        self.inp_path = inp_path
        self.inlet = inlet_cell
        self.vent = vent_cell
        self.dt_c = dt_c
        self.cd = cd
        self.ao = ao
        h, w = surface.shape
        for cell, name in ((inlet_cell, "inlet"), (vent_cell, "vent")):
            r, c = cell
            if not (0 < r < h - 1 and 0 < c < w - 1):
                raise CouplingError(f"{name} cell {cell} must be a core (non-boundary) cell of {surface.shape}")
        if inlet_cell == vent_cell:
            raise CouplingError("inlet and vent cells must differ (separate exchange locations)")
        self.exchange: list[ExchangeStep] = []
        self.ledger = CoupledLedger()

    # ------------------------------------------------------------------
    def _head_at(self, cell: tuple[int, int]) -> float:
        return float(self.surface.dem[cell] + self.surface.depth[cell])

    def _add_depth(self, cell: tuple[int, int], depth_m: float) -> None:
        h = self.surface.depth
        h[cell] += depth_m
        if h[cell] < -1e-12:
            raise CouplingError(f"negative depth {h[cell]:.3e} m at cell {cell} after exchange")

    def _remove_depth(self, cell: tuple[int, int], depth_m: float) -> None:
        h = self.surface.depth
        if h[cell] < depth_m - 1e-12:
            raise CouplingError(f"removing {depth_m:.3e} m from cell {cell} with only {h[cell]:.3e} m available")
        h[cell] -= depth_m

    # ------------------------------------------------------------------
    def run(self, minutes: float, rain_mmh: float = 0.0, external_inflow_m3s: float = 0.0, ext_node: str = "ST1") -> None:
        from pyswmm import Links, Nodes, Simulation

        n_steps = int(round(minutes * 60 / self.dt_c))
        dt = self.dt_c
        if external_inflow_m3s < 0:
            raise CouplingError("external inflow must be >= 0")

        led = self.ledger
        led.S_s0 = self.surface.surface_storage_m3()

        with Simulation(str(self.inp_path)) as sim:
            sim.step_advance(dt)
            try:
                st1 = Nodes(sim)["ST1"]
                o1 = Nodes(sim)["O1"]
                c1 = Links(sim)["C1"]
                c2 = Links(sim)["C2"]
            except Exception as e:
                raise CouplingError(f"required SWMM object missing in {self.inp_path}: {e}") from e
            try:
                ext_inflow_node = Nodes(sim)[ext_node]
            except Exception as e:
                raise CouplingError(f"external inflow node {ext_node!r} missing in {self.inp_path}: {e}") from e
            try:
                vent = Nodes(sim)["V1"]   # exact-exchange fixture (storage vent)
            except Exception:
                vent = Nodes(sim)["J1"]   # flooding demo fixture (junction vent)
            try:
                flood_node = Nodes(sim)["J1"]
            except Exception:
                flood_node = None  # exact-exchange fixture has no junction

            led.S_d0 = 0.0  # identity-based drainage storage starts at 0
            led.S_d1 = 0.0

            prev_flood = 0.0
            prev_q_out = 0.0
            prev_s2d_rate = 0.0
            prev_d2s_rate = 0.0
            prev_ext_rate = 0.0  # external inflow active during the completed stride
            rain_ms = rain_mmh / 3600000.0
            last_i = -1
            for i, _ in enumerate(sim):
                last_i = i
                if i >= n_steps + 1:
                    break
                t = (i + 1) * dt  # SWMM state is at t_{i+1} after stride i

                # -- read SWMM state at t_{i+1} -------------------------------
                flood_i = float(flood_node.flooding) if flood_node is not None else 0.0
                q_out_i = float(o1.total_inflow)
                H_d = float(st1.head)

                # -- flooding export of completed stride (real water) ---------
                stride_flood = (flood_i + prev_flood) / 2.0 * dt
                if stride_flood < -1e-12:
                    raise CouplingError(f"negative flooding export {stride_flood:.3e} m3 at t={t} s")
                self._add_depth(self.vent, stride_flood / self.surface.cell_area_m2)
                led.flood_export_m3 += stride_flood
                prev_flood = flood_i

                # -- outfall volume of completed stride -----------------------
                stride_out = (q_out_i + prev_q_out) / 2.0 * dt
                led.outfall_m3 += stride_out
                prev_q_out = q_out_i

                # -- drainage storage via SWMM's own per-stride identity ------
                # dS_d(stride) = (ext_rate_prev + S2D_rate_prev - D2S_rate_prev
                #                 - outfall_rate - flood_rate) * dt   [engine-exact]
                led.S_d1 += (prev_ext_rate + prev_s2d_rate - prev_d2s_rate) * dt - stride_out - stride_flood

                if i >= n_steps:
                    break  # final read-only iteration closes the last stride

                # -- advance surface [t_i -> t_{i+1}] with rain ----------------
                led.rain_m3 += self.surface.apply_rainfall(rain_ms, dt)
                self.surface.step(dt)

                # -- signed orifice exchange at t_{i+1} ------------------------
                eta_s = self._head_at(self.inlet)
                eta_v = self._head_at(self.vent)
                q_ex = orifice_exchange_rate(eta_s, H_d, self.cd, self.ao)
                if q_ex > 0 and flood_i > 0:
                    q_ex = 0.0  # inlet regime rule: no admission while flooding
                s2d = d2s = 0.0
                if q_ex > 0:
                    avail = float(self.surface.depth[self.inlet]) * self.surface.cell_area_m2
                    q_ex = min(q_ex, avail / dt)
                    s2d = q_ex * dt
                    self._remove_depth(self.inlet, s2d / self.surface.cell_area_m2)
                elif q_ex <= 0:
                    # reverse leg: ST1 head vs vent cell water surface
                    q_back = max(0.0, orifice_exchange_rate(H_d, eta_v, self.cd, self.ao))
                    q_back = min(q_back, float(st1.volume) / dt)  # exact extraction cap
                    q_ex = -q_back
                    d2s = q_back * dt
                    self._add_depth(self.vent, d2s / self.surface.cell_area_m2)
                led.S2D_m3 += s2d
                led.D2S_m3 += d2s

                # -- drive SWMM for the next stride ----------------------------
                if ext_node == "ST1":
                    st1.generated_inflow(q_ex + external_inflow_m3s)
                else:
                    st1.generated_inflow(q_ex)
                    ext_inflow_node.generated_inflow(external_inflow_m3s)
                led.ext_in_m3 += external_inflow_m3s * dt
                prev_s2d_rate = s2d / dt
                prev_d2s_rate = d2s / dt
                prev_ext_rate = external_inflow_m3s

                self.exchange.append(
                    ExchangeStep(t_s=t + dt, S2D_vol=s2d, D2S_vol=d2s,
                                 flood_export_vol=stride_flood, eta_s=eta_s, eta_v=eta_v, H_d=H_d)
                )
                if not math.isfinite(s2d) or not math.isfinite(d2s):
                    raise CouplingError("non-finite exchange volume")

            if last_i < n_steps:
                raise CouplingError(f"SWMM simulation ended prematurely at stride {last_i}, expected at least {n_steps}")

            led.flow_routing_error_pct = float(sim.flow_routing_error)
            led.S_s1 = self.surface.surface_storage_m3()
            led.S_d1_readback = self._drain_storage(st1, vent, c1, c2)

    # ------------------------------------------------------------------
    @staticmethod
    def _drain_storage(st1, vent, c1, c2) -> float:
        """Drainage storage: ST1 volume + V1 volume (exact TABULAR storages)
        + conduit volumes (engine-reported). In the exact-exchange fixture
        there are no junctions, so every term is engine-exact."""
        return float(st1.volume) + float(vent.volume) + float(c1.volume) + float(c2.volume)


def build_spike_surface(n: int = 7, cell_m: float = 30.0) -> SurfaceModel:
    """7x7 @30 m surface (closed boundaries), SYNTHETIC.

    A shallow bowl centred on the inlet cell concentrates rainfall there;
    the vent cell is a small raised mound where returned water ponds.
    Inlet bed 10.0 m (level with ST1 invert); vent bed 10.4 m (0.4 m above
    ST1 invert: the pipe must pressurize above ground level to emerge).
    """
    y, x = np.mgrid[0:n, 0:n]
    cy, cx = 3, 3
    r2 = (x - cx) ** 2 + (y - cy) ** 2
    dem = 10.5 - 0.5 * np.exp(-r2 / 3.0)
    dem[3, 3] = 10.0   # inlet cell (capture location, low point)
    dem[3, 4] = 10.4   # vent cell (return location, raised)
    return SurfaceModel(dem.astype(np.float64), cell_size_m=cell_m, closed_boundaries=True)
