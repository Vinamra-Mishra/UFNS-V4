"""M5 visual diagnostics (M5 spec §15).

Deterministic, clearly labelled PNG artifacts for each scenario:
  - rainfall preview (peak-intensity interval)
  - peak-depth preview
  - maximum flood-extent preview
  - depth timeline (peak depth + flooded area vs lead)
  - drainage-surcharge timeline
  - scenario-summary table

S3/S4 additionally:
  - clean peak depth
  - blocked peak depth
  - depth difference (blocked - clean)
  - flooded-area difference
  - drainage-surcharge comparison

Every artifact is labelled SYNTHETIC / SIMULATED / PROVISIONAL.
Rendering uses Pillow (no matplotlib dependency), consistent with
scripts/run_m4_diagnostics.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from services.ingestion.visual import render_depth, render_difference, render_png
from services.scenarios.comparison import ScenarioComparison, compare
from services.scenarios.profiles import all_profiles
from services.scenarios.registry import M5_SCENARIOS
from services.scenarios.runner import ScenarioResult


def _line_chart(path: Path, series: dict[str, list[float]], x: list[float],
                xlabel: str = "lead (min)", title: str = "",
                ylabels: Optional[dict[str, str]] = None,
                colors: Optional[dict[str, tuple[int, int, int]]] = None) -> None:
    """Multi-panel line chart (one panel per series)."""
    w, h = 800, 80 + 200 * len(series)
    img = Image.new("RGB", (w, h), (250, 250, 248))
    d = ImageDraw.Draw(img)
    default_colors = {
        "peak_depth": (200, 30, 20),
        "flooded_area": (30, 90, 200),
        "st1_head": (200, 120, 20),
        "outfall": (30, 130, 90),
        "D2S": (140, 60, 180),
        "S2D": (60, 60, 180),
        "vent_depth": (180, 60, 60),
        "surcharge": (180, 20, 120),
    }
    if colors is None:
        colors = default_colors
    if ylabels is None:
        ylabels = {k: k for k in series}
    pad_l, pad_r, pad_t, pad_b = 90, 30, 36, 50
    n_panels = len(series)
    panel_h = (h - pad_t - pad_b) / max(n_panels, 1)
    d.text((8, 6), f"{title} - SYNTHETIC / SIMULATED / PROVISIONAL", fill=(20, 20, 20))
    for p_i, (name, ys) in enumerate(series.items()):
        y0 = pad_t + p_i * panel_h
        y1 = pad_t + (p_i + 1) * panel_h
        ymax = max(max(ys), 1e-9) * 1.1 if ys else 1.0
        plot_h = panel_h - 28
        plot_w = w - pad_l - pad_r
        d.line([(pad_l, y1 - 4), (w - pad_r, y1 - 4)], fill=(200, 200, 200), width=1)
        d.line([(pad_l, y0 + 4), (pad_l, y1 - 4)], fill=(200, 200, 200), width=1)
        d.text((8, y0 + 2), f"{ylabels.get(name, name)} (max {ymax:.3g})", fill=(20, 20, 20))
        if len(ys) >= 2:
            pts = []
            for i, yi in enumerate(ys):
                px = pad_l + plot_w * (x[i] - x[0]) / max(x[-1] - x[0], 1)
                py = y1 - 4 - (yi / ymax) * plot_h
                pts.append((px, py))
            d.line(pts, fill=colors.get(name, (0, 0, 0)), width=2)
    d.text((pad_l, h - pad_b + 10), xlabel, fill=(60, 60, 60))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def _rainfall_preview(profile_id: str, shape: tuple[int, int], path: Path) -> None:
    """Render peak-interval rainfall as a PNG."""
    from services.rainfall.fields import render_interval
    profiles = all_profiles()
    p = profiles[profile_id]
    peak_idx = int(np.argmax(p.intensities_mmh))
    peak_rate = float(p.intensities_mmh[peak_idx])
    field = render_interval(shape, "convective_cell", peak_rate, peak_idx, seed=20260821)
    label = (f"SIMULATED RAINFALL - {p.display_name}; peak "
             f"{peak_rate:.1f} mm/h interval {peak_idx+1}/{len(p.intensities_mmh)}; "
             f"PROVISIONAL (D-016 {p.d016_review_status})")
    render_png(field.astype(np.float32), path, vmin=0.0, vmax=max(peak_rate * 1.1, 1.0),
               label=label)


def _write_summary_table(path: Path, results: dict[str, ScenarioResult],
                         comparison: ScenarioComparison) -> None:
    """Render a simple text summary table as PNG (provenance banner included)."""
    rows = []
    header = ("scenario", "rain mm", "drainage", "peak m", "area km2",
              "S2D m3", "D2S m3", "outfall m3", "surcharge m",
              "rel.resid", "status")
    rows.append(header)
    for sid in ("S1", "S2", "S3", "S4"):
        r = results[sid]
        led = r.m4_result.ledger
        rows.append((
            sid,
            f"{r.scenario.rainfall_profile.total_depth_mm:.0f}",
            r.scenario.drainage_condition.status.value[:3],
            f"{r.peak_depth_m:.3f}",
            f"{r.max_flooded_area_m2/1e6:.3f}",
            f"{led.S2D_m3:.1f}",
            f"{led.D2S_m3:.1f}",
            f"{led.outfall_m3:.1f}",
            f"{r.max_drainage_surcharge_m:.3f}",
            f"{led.relative_total() or 0:.1e}",
            r.acceptance["overall"],
        ))
    col_w = [max(len(row[i]) for row in rows) + 2 for i in range(len(header))]
    line_h = 22
    w = sum(col_w) * 10 + 40
    h = line_h * (len(rows) + 4) + 40
    img = Image.new("RGB", (w, h), (250, 250, 248))
    d = ImageDraw.Draw(img)
    d.text((8, 6), "M5 SCENARIO SUMMARY - SYNTHETIC / SIMULATED / PROVISIONAL", fill=(20, 20, 20))
    y = 36
    for i, row in enumerate(rows):
        x = 20
        fill = (20, 20, 20) if i > 0 else (220, 60, 20)
        for j, cell in enumerate(row):
            d.text((x, y), str(cell).ljust(col_w[j]), fill=fill)
            x += col_w[j] * 10
        y += line_h
    y += 12
    s3s4 = comparison.s3s4_comparison
    d.text((8, y), f"S3/S4 blockage comparison: {s3s4['interpretation_status']}", fill=(20, 20, 20))
    y += line_h
    diff = s3s4["differences"]
    d.text((8, y), f"  delta peak {diff['delta_peak_depth_m']:+.3f} m | "
                   f"delta area {diff['delta_flooded_area_m2']:+,.0f} m2 | "
                   f"delta surf.storage {diff['delta_surface_storage_change_m3']:+,.1f} m3 | "
                   f"delta surcharge {diff['delta_max_surcharge_m']:+.3f} m", fill=(40, 40, 40))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def generate_diagnostics(
    results: dict[str, ScenarioResult],
    out_dir: Path,
    dem_shape: tuple[int, int] = (134, 134),
) -> dict[str, Path]:
    """Generate all M5 visual diagnostics under out_dir/. Returns path manifest."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    comparison = compare(results)

    # Per-scenario artifacts
    for sid in ("S1", "S2", "S3", "S4"):
        r = results[sid]
        sc = r.scenario
        sdir = out_dir / sid.lower()
        sdir.mkdir(parents=True, exist_ok=True)

        # Rainfall preview
        rain_png = sdir / f"{sid}_rainfall_peak.png"
        _rainfall_preview(sc.rainfall_profile.profile_id, dem_shape, rain_png)
        paths[f"{sid}.rainfall"] = rain_png

        # Peak depth: find lead with max depth
        peak_lead = max(r.m4_result.depth_arrays.keys(),
                        key=lambda l: float(r.m4_result.depth_arrays[l].max()))
        peak_arr = r.m4_result.depth_arrays[peak_lead]
        vmax_depth = max((float(r.m4_result.depth_arrays[l].max()) for l in r.m4_result.depth_arrays))
        vmax_depth = max(vmax_depth, 0.05)

        depth_png = sdir / f"{sid}_peak_depth_t{peak_lead:03d}.png"
        render_depth(peak_arr, depth_png, vmax=vmax_depth,
                     label=(f"MODEL PREDICTION - {sid} {sc.display_name}; "
                            f"peak depth t+{peak_lead} min (SYNTHETIC FIXTURE, SIMULATED, PROVISIONAL)"))
        paths[f"{sid}.peak_depth"] = depth_png

        # Maximum flood extent (depth > threshold)
        extent_png = sdir / f"{sid}_max_flood_extent.png"
        flood_mask = (peak_arr > sc.extent_threshold_m).astype(np.float32)
        render_depth(flood_mask * peak_arr, extent_png, vmax=vmax_depth,
                     label=(f"MODEL PREDICTION - {sid} flood extent (h > "
                            f"{sc.extent_threshold_m} m) at t+{peak_lead} min "
                            f"(SYNTHETIC FIXTURE, SIMULATED, PROVISIONAL)"))
        paths[f"{sid}.flood_extent"] = extent_png

        # Depth timeline (peak depth + flooded area)
        leads = sorted(r.m4_result.depth_arrays.keys())
        peak_series = [float(r.m4_result.depth_arrays[l].max()) for l in leads]
        area_series = [float((r.m4_result.depth_arrays[l] > sc.extent_threshold_m).sum())
                       * 900.0 / 1e6 for l in leads]
        timeline_png = sdir / f"{sid}_depth_timeline.png"
        _line_chart(timeline_png,
                    {"peak_depth": peak_series, "flooded_area": area_series},
                    list(leads),
                    title=f"{sid} {sc.display_name}",
                    ylabels={"peak_depth": "peak depth (m)", "flooded_area": "flooded area (km2)"})
        paths[f"{sid}.timeline"] = timeline_png

        # Drainage timeline (ST1 head, outfall cum, D2S cum)
        drain_png = sdir / f"{sid}_drainage_timeline.png"
        st1 = [s.drainage.st1_head_m for s in r.m4_result.snapshots]
        outf = [s.drainage.outfall_cum_m3 for s in r.m4_result.snapshots]
        d2s = [s.drainage.exchange_D2S_cum_m3 for s in r.m4_result.snapshots]
        s2d = [s.drainage.exchange_S2D_cum_m3 for s in r.m4_result.snapshots]
        _line_chart(drain_png,
                    {"st1_head": st1, "S2D": s2d, "D2S": d2s, "outfall": outf},
                    [s.lead_minutes for s in r.m4_result.snapshots],
                    title=f"{sid} drainage state (ST1 head m / S2D / D2S / outfall m3)",
                    ylabels={"st1_head": "ST1 head (m)", "S2D": "S2D cum (m3)",
                             "D2S": "D2S cum (m3)", "outfall": "outfall (m3)"})
        paths[f"{sid}.drainage"] = drain_png

    # S3/S4 comparison artifacts
    s3 = results["S3"]
    s4 = results["S4"]
    peak_lead_s3 = max(s3.m4_result.depth_arrays.keys(),
                       key=lambda l: float(s3.m4_result.depth_arrays[l].max()))
    peak_lead_s4 = max(s4.m4_result.depth_arrays.keys(),
                       key=lambda l: float(s4.m4_result.depth_arrays[l].max()))
    peak_lead = max(peak_lead_s3, peak_lead_s4)
    arr3 = s3.m4_result.depth_arrays.get(peak_lead, s3.m4_result.depth_arrays[max(s3.m4_result.depth_arrays)])
    arr4 = s4.m4_result.depth_arrays.get(peak_lead, s4.m4_result.depth_arrays[max(s4.m4_result.depth_arrays)])
    vmax_pair = max(float(arr3.max()), float(arr4.max()))

    cdir = out_dir / "s3s4_comparison"
    cdir.mkdir(parents=True, exist_ok=True)

    s3_peak_png = cdir / "S3_peak_depth.png"
    render_depth(arr3, s3_peak_png, vmax=vmax_pair,
                 label="S3 (clean) peak depth - SYNTHETIC / SIMULATED / PROVISIONAL")
    paths["s3s4.s3_peak"] = s3_peak_png

    s4_peak_png = cdir / "S4_peak_depth.png"
    render_depth(arr4, s4_peak_png, vmax=vmax_pair,
                 label="S4 (blocked) peak depth - SYNTHETIC / SIMULATED / PROVISIONAL")
    paths["s3s4.s4_peak"] = s4_peak_png

    diff = arr4 - arr3
    diff_png = cdir / "S4_minus_S3_depth_diff.png"
    bound = max(abs(float(diff.min())), abs(float(diff.max())), 1e-6)
    render_difference(diff, diff_png,
                      label=f"Depth difference S4 - S3 at t+{peak_lead} min (m); "
                            f"range +/-{bound:.3f} m - SYNTHETIC / SIMULATED / PROVISIONAL")
    paths["s3s4.diff"] = diff_png

    # Flooded area difference timeline
    leads = sorted(s3.m4_result.depth_arrays.keys())
    thresh = M5_SCENARIOS["S3"].extent_threshold_m
    area_s3 = [float((s3.m4_result.depth_arrays[l] > thresh).sum()) * 900.0 / 1e6 for l in leads]
    area_s4 = [float((s4.m4_result.depth_arrays[l] > thresh).sum()) * 900.0 / 1e6 for l in leads]
    area_diff_png = cdir / "flooded_area_difference.png"
    _line_chart(area_diff_png,
                {"S3 flooded area": area_s3, "S4 flooded area": area_s4},
                list(leads),
                title="S3 vs S4 flooded area (km2, h > 0.05 m)",
                ylabels={"S3 flooded area": "S3 (km2)", "S4 flooded area": "S4 (km2)"},
                colors={"S3 flooded area": (30, 90, 200), "S4 flooded area": (200, 30, 20)})
    paths["s3s4.area_diff"] = area_diff_png

    # Surcharge comparison
    surcharge_png = cdir / "drainage_surcharge_comparison.png"
    s3_heads = [s.drainage.st1_head_m for s in s3.m4_result.snapshots]
    s4_heads = [s.drainage.st1_head_m for s in s4.m4_result.snapshots]
    s3_d2s = [s.drainage.exchange_D2S_cum_m3 for s in s3.m4_result.snapshots]
    s4_d2s = [s.drainage.exchange_D2S_cum_m3 for s in s4.m4_result.snapshots]
    _line_chart(surcharge_png,
                {"S3 ST1 head": s3_heads, "S4 ST1 head": s4_heads,
                 "S3 D2S": s3_d2s, "S4 D2S": s4_d2s},
                [s.lead_minutes for s in s3.m4_result.snapshots],
                title="Drainage surcharge comparison: S3 clean vs S4 blocked",
                ylabels={"S3 ST1 head": "S3 ST1 head (m)", "S4 ST1 head": "S4 ST1 head (m)",
                         "S3 D2S": "S3 D2S cum (m3)", "S4 D2S": "S4 D2S cum (m3)"},
                colors={"S3 ST1 head": (30, 90, 200), "S4 ST1 head": (200, 30, 20),
                        "S3 D2S": (60, 60, 180), "S4 D2S": (140, 60, 180)})
    paths["s3s4.surcharge"] = surcharge_png

    # Summary table
    table_png = out_dir / "m5_summary_table.png"
    _write_summary_table(table_png, results, comparison)
    paths["summary_table"] = table_png

    return paths
