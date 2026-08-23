#!/usr/bin/env python3
"""M5 diagnostics generator (M5 spec §15).

Produces deterministic visual artifacts under data/demo/m5/:
  m5_summary_table.png           Scenario summary table
  m5_comparison.json             Deterministic comparison artifact
  m5_results.json                Per-scenario result summaries
  s{1,2,3,4}/                    Per-scenario folders containing:
    S{n}_rainfall_peak.png       Rainfall preview (peak interval)
    S{n}_peak_depth_t*.png       Peak-depth preview
    S{n}_max_flood_extent.png    Flood extent preview
    S{n}_depth_timeline.png      Peak depth + flooded area vs lead
    S{n}_drainage_timeline.png   ST1 head / S2D / D2S / outfall vs lead
    depth_t*.tif                 Per-snapshot GeoTIFFs with provenance
  s3s4_comparison/
    S3_peak_depth.png            S3 (clean) peak depth
    S4_peak_depth.png            S4 (blocked) peak depth
    S4_minus_S3_depth_diff.png   Depth difference (blocked - clean)
    flooded_area_difference.png  Flooded area vs lead, both scenarios
    drainage_surcharge_comparison.png  Drainage-state comparison
All outputs labelled SYNTHETIC / SIMULATED / PROVISIONAL.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.ingestion.dem import synthetic_dem
from services.scenarios.comparison import compare
from services.scenarios.diagnostics import generate_diagnostics
from services.scenarios.runner import run_all_scenarios

OUT = Path(__file__).resolve().parents[1] / "data" / "demo" / "m5"
ISSUE = datetime(2026, 8, 21, tzinfo=timezone.utc)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    dem = synthetic_dem()

    print(f"Running M5 scenario suite (S1–S4)...")
    results = run_all_scenarios(dem, issue_time=ISSUE, artifact_root=OUT)

    total_wall = sum(r.wall_seconds for r in results.values())
    print()
    for sid in ("S1", "S2", "S3", "S4"):
        r = results[sid]
        led = r.m4_result.ledger
        print(
            f"  {sid} ({r.scenario.display_name}): "
            f"peak={r.peak_depth_m:.3f}m  area={r.max_flooded_area_m2/1e6:.3f}km2  "
            f"S2D={led.S2D_m3:.1f}  D2S={led.D2S_m3:.1f}  "
            f"outfall={led.outfall_m3:.1f}  surcharge={r.max_drainage_surcharge_m:.3f}m  "
            f"rel_resid={led.relative_total():.2e}  {r.mass_ledger['gate']}  "
            f"({r.wall_seconds:.1f}s)"
        )

    comp = compare(results)
    s3s4 = comp.s3s4_comparison
    print(f"\nS3/S4 blockage comparison: {s3s4['interpretation_status']}")
    for k, v in s3s4["differences"].items():
        print(f"  {k}: {v:+.4f}")

    print(f"\nGenerating visual diagnostics under {OUT}...")
    paths = generate_diagnostics(results, OUT, dem_shape=dem.shape)
    print(f"  {len(paths)} diagnostic artifacts")

    comp_path = comp.write_json(OUT / "m5_comparison.json")
    results_path = OUT / "m5_results.json"
    results_path.write_text(
        json.dumps(
            {sid: r.to_dict() for sid, r in results.items()},
            indent=2, sort_keys=True, default=str,
        )
    )
    print(f"  wrote {comp_path}")
    print(f"  wrote {results_path}")
    print(f"\nTotal scenario wall time: {total_wall:.1f}s")
    print(f"Labels: SYNTHETIC / SIMULATED / PROVISIONAL (D-016 PENDING)")


if __name__ == "__main__":
    main()
