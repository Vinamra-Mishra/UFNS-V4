"""Whole-system mass ledger (MODEL_ASSUMPTIONS §8, D-015, B07).

Identity:
  V_rain + V_external_in + V_surface,0 + V_drain,0
= V_infiltration + V_surface_boundary_out + V_drain_outfall
  + V_microstore,final + V_surface,final + V_drain,final + eps

Surface–drain exchange is internal and must cancel; it never appears here.

Gates (explicit, documented; provisional until benchmark evidence — B07):
  pass:      e_rel <= 1%   (or absolute residual <= 1e-6 m3 when volumes are tiny)
  warning:   1% < e_rel <= 5%
  fail:      e_rel > 5% or non-finite terms
Thresholds are only ever changed with a DECISIONS.md entry + evidence.
"""

from __future__ import annotations

import math
from datetime import datetime

from services.contracts import MassBalance

PASS_REL = 0.01
WARN_REL = 0.05
ABS_SCALE_M3 = 1e-6  # absolute-volume check for near-dry runs


class MassLedger:
    def __init__(self) -> None:
        self.rainfall_input_m3 = 0.0
        self.external_inflow_m3 = 0.0
        self.infiltration_loss_m3 = 0.0
        self.surface_boundary_outflow_m3 = 0.0
        self.drainage_outfall_m3 = 0.0
        self.microstore_final_m3 = 0.0
        self.surface_storage_initial_m3 = 0.0
        self.surface_storage_final_m3 = 0.0
        self.drain_storage_initial_m3 = 0.0
        self.drain_storage_final_m3 = 0.0
        # exchange bookkeeping (internal; must cancel exactly)
        self.exchange_surface_to_drain_m3 = 0.0
        self.exchange_drain_to_surface_m3 = 0.0

    # -- accumulation -------------------------------------------------------
    def add_rainfall(self, volume_m3: float) -> None:
        self.rainfall_input_m3 += volume_m3

    def add_external_inflow(self, volume_m3: float) -> None:
        self.external_inflow_m3 += volume_m3

    def add_infiltration(self, volume_m3: float) -> None:
        self.infiltration_loss_m3 += volume_m3

    def add_surface_boundary_outflow(self, volume_m3: float) -> None:
        self.surface_boundary_outflow_m3 += volume_m3

    def add_drainage_outfall(self, volume_m3: float) -> None:
        self.drainage_outfall_m3 += volume_m3

    def record_exchange(self, surface_to_drain_m3: float, drain_to_surface_m3: float) -> None:
        """Equal-and-opposite exchange under one exchange ID cancels in the ledger."""
        self.exchange_surface_to_drain_m3 += surface_to_drain_m3
        self.exchange_drain_to_surface_m3 += drain_to_surface_m3

    # -- closing ------------------------------------------------------------
    def _residual(self) -> float:
        inputs = (
            self.rainfall_input_m3
            + self.external_inflow_m3
            + self.surface_storage_initial_m3
            + self.drain_storage_initial_m3
        )
        outputs = (
            self.infiltration_loss_m3
            + self.surface_boundary_outflow_m3
            + self.drainage_outfall_m3
            + self.microstore_final_m3
            + self.surface_storage_final_m3
            + self.drain_storage_final_m3
        )
        return inputs - outputs

    def close(self, interval_start: datetime, interval_end: datetime) -> MassBalance:
        residual = self._residual()
        if any(not math.isfinite(x) for x in [residual]):
            status = "fail"
            rel = None
        else:
            scale = max(
                abs(self.rainfall_input_m3)
                + abs(self.external_inflow_m3)
                + abs(self.surface_storage_initial_m3)
                + abs(self.drain_storage_initial_m3),
                ABS_SCALE_M3
            )
            rel = abs(residual) / scale
            if rel <= PASS_REL or (abs(residual) <= ABS_SCALE_M3 and self.rainfall_input_m3 == 0):
                status = "pass"
            elif rel <= WARN_REL:
                status = "warning"
            else:
                status = "fail"
        return MassBalance(
            interval_start=interval_start,
            interval_end=interval_end,
            rainfall_input_m3=self.rainfall_input_m3,
            external_inflow_m3=self.external_inflow_m3,
            infiltration_loss_m3=self.infiltration_loss_m3,
            surface_boundary_outflow_m3=self.surface_boundary_outflow_m3,
            drainage_outfall_m3=self.drainage_outfall_m3,
            initial_surface_storage_m3=self.surface_storage_initial_m3,
            final_surface_storage_m3=self.surface_storage_final_m3,
            initial_drain_storage_m3=self.drain_storage_initial_m3,
            final_drain_storage_m3=self.drain_storage_final_m3,
            residual_m3=residual,
            relative_error=rel,
            status=status,
        )
