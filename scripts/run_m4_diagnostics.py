#!/usr/bin/env python3
"""M4 diagnostics generator (IMPLEMENTATION_SPEC M4 §21-22).

Produces deterministic visual artifacts under data/demo/m4/:
  m4_dem.png                     synthetic DEM (labelled)
  m4_rain_peak.png               peak-intensity rainfall field
  m4_flood_clean_peak.png        heavy scenario, clean drainage, peak depth
  m4_flood_blocked_peak.png      heavy scenario, blocked drainage, peak depth
  m4_diff_blocked_clean.png      peak-depth difference (blocked - clean)
  m4_depth_timeline.png          peak depth + flooded area vs time (clean)
  m4_drainage_state.png          ST1 head / outfall / D2S vs time (blocked)
  m4_summary.json                per-scenario metrics + mass balance
All outputs labelled SYNTHETIC / SIMULATED / PROVISIONAL — never observations.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.ingestion.dem import synthetic_dem
from services.ingestion.visual import render_dem, render_depth, render_difference, render_rain
from services.rainfall.scenarios import build_profile
from services.simulation.engine import CoupledFloodModel, m4_scenario_configs

OUT = Path(__file__).resolve().parents[1] / "data" / "demo" / "m4"
ISSUE = datetime(2026, 8, 21, tzinfo=timezone.utc)


def _line_chart(path: Path, series: dict[str, list[float]], x: list[float],
                xlabel: str = "lead (min)", title: str = "") -> None:
    """Line chart drawn with PIL (no matplotlib dependency)."""
    w, h = 720, 460
    img = Image.new("RGB", (w, h), (250, 250, 248))
    d = ImageDraw.Draw(img)
    colors = {"peak_depth": (200, 30, 20), "flooded_area": (30, 90, 200),
              "st1_head": (200, 120, 20), "outfall": (30, 130, 90), "D2S": (140, 60, 180)}
    pad_l, pad_r, pad_t, pad_b = 60, 20, 40, 40
    n_panels = len(series)
    panel_h = (h - pad_t - pad_b) / n_panels
    for p_i, (name, ys) in enumerate(series.items()):
        y0 = pad_t + p_i * panel_h
        y1 = pad_t + (p_i + 1) * panel_h
        ymax = max(max(ys), 1e-9)
        xs = [pad_l + (h - pad_l - pad_r) * (xi - x[0]) / max(x[-1] - x[0], 1) for xi in x]
        pts = [(xs[i], y1 - (yi / ymax) * (panel_h - 28)) for i, yi in enumerate(ys)]
        d.line(pts, fill=colors.get(name, (0, 0, 0)), width=2)
        d.text((8, y0 + 2), f"{name} (max {ymax:.3g})", fill=(20, 20, 20))
        d.line([(pad_l, y1), (h - pad_r, y1)], fill=(180, 180, 180), width=1)
    d.text((8, 4), f"{title} - SYNTHETIC / SIMULATED", fill=(20, 20, 20))
    d.text((pad_l, h - pad_b + 12), xlabel, fill=(60, 60, 60))
    img.save(path)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    dem = synthetic_dem()
    cfgs = m4_scenario_configs(dem, ISSUE)
    cfgs["heavy"].artifact_dir = OUT / "clean"
    cfgs["heavy_blocked"].artifact_dir = OUT / "blocked"

    # -- run every scenario once, keep results ---------------------------------
    results: dict[str, dict] = {}
    runs: dict[str, "CoupledFloodModel"] = {}
    print("running M4 scenario suite (zero, uniform, spatial, heavy, heavy_blocked)...")
    for key in ("zero", "uniform", "spatial", "heavy", "heavy_blocked"):
        model = CoupledFloodModel(cfgs[key])
        res = model.run()
        runs[key] = res
        led = res.ledger
        results[key] = {
            "scenario_id": key,
            "run_id": res.simulation_run.run_id,
            "fingerprint": res.simulation_run.configuration_fingerprint,
            "mass_status": res.mass_balance.status,
            "relative_residual": led.relative_total() if led.rain_m3 + led.ext_in_m3 > 0 else None,
            "residual_m3": led.residual_total,
            "rain_m3": led.rain_m3,
            "losses_m3": led.losses_m3,
            "surface_out_m3": led.surf_out_m3,
            "microstore_m3": led.microstore_final_m3,
            "S2D_m3": led.S2D_m3,
            "D2S_m3": led.D2S_m3,
            "outfall_m3": led.outfall_m3,
            "peak_depth_m": res.peak_depth_m,
            "max_flooded_area_m2": res.max_flooded_area_m2,
            "time_to_peak_min": res.time_to_peak_min,
            "max_st1_head_m": res.max_st1_head_m,
            "wall_seconds": res.wall_seconds,
            "peak_rss_mb": res.peak_rss_mb,
            "n_snapshots": len(res.snapshots),
        }
        rel = led.relative_total() if led.rain_m3 + led.ext_in_m3 > 0 else 0.0
        print(f"  {key}: peak={res.peak_depth_m:.3f}m area={res.max_flooded_area_m2/1e6:.3f}km2 "
              f"S2D={led.S2D_m3:.1f} D2S={led.D2S_m3:.1f} outfall={led.outfall_m3:.1f} "
              f"resid={rel:.2e} "
              f"{res.mass_balance.status} ({res.wall_seconds:.1f}s)")

    # -- static previews --------------------------------------------------------
    render_dem(dem, OUT / "m4_dem.png")
    peak_rate = max(build_profile("heavy", 45.0).intensities_mmh)
    field_img = np.full(dem.shape, float(peak_rate), dtype=np.float32)
    render_rain(field_img, OUT / "m4_rain_peak.png",
                label=f"SIMULATED RAINFALL - peak intensity {peak_rate:.0f} mm/h (PROVISIONAL)")

    # -- flood previews ---------------------------------------------------------
    clean = runs["heavy"]
    blocked = runs["heavy_blocked"]
    peak_lead = max(clean.depth_arrays)
    render_depth(clean.depth_arrays[peak_lead], OUT / "m4_flood_clean_peak.png", vmax=0.5,
                 label="MODEL PREDICTION - heavy rain, CLEAN drainage, peak depth (SYNTHETIC FIXTURE)")
    render_depth(blocked.depth_arrays[peak_lead], OUT / "m4_flood_blocked_peak.png", vmax=0.5,
                 label="MODEL PREDICTION - heavy rain, BLOCKED drainage, peak depth (SYNTHETIC FIXTURE)")
    diff = blocked.depth_arrays[peak_lead] - clean.depth_arrays[peak_lead]
    render_difference(diff, OUT / "m4_diff_blocked_clean.png",
                      label="MODEL DIFFERENCE - blocked minus clean drainage, peak depth (SYNTHETIC FIXTURE)")

    # -- timelines --------------------------------------------------------------
    leads = sorted(clean.depth_arrays)
    peak_series = [float(clean.depth_arrays[l].max()) for l in leads]
    area_series = [float((clean.depth_arrays[l] > 0.05).sum()) * 900.0 / 1e6 for l in leads]
    _line_chart(OUT / "m4_depth_timeline.png",
                {"peak_depth": peak_series, "flooded_area": area_series}, leads,
                title="heavy scenario, clean drainage (area > 0.05 m, km2)")
    s_b = blocked.snapshots
    _line_chart(OUT / "m4_drainage_state.png",
                {
                    "st1_head": [s.drainage.st1_head_m for s in s_b],
                    "outfall": [s.drainage.outfall_cum_m3 for s in s_b],
                    "D2S": [s.drainage.exchange_D2S_cum_m3 for s in s_b],
                },
                [s.lead_minutes for s in s_b],
                title="blocked drainage: ST1 head (m) / outfall (m3) / D2S spill (m3)")

    (OUT / "m4_summary.json").write_text(
        json.dumps({"issue_time": ISSUE.isoformat(), "scenarios": results,
                    "labels": ["SYNTHETIC", "SIMULATED", "PROVISIONAL"]}, indent=2, sort_keys=True)
    )
    print(f"\ndiagnostics written to {OUT}")
    print(f"summary: {OUT / 'm4_summary.json'}")


if __name__ == "__main__":
    main()
