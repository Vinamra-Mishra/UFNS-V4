"""Deterministic diagnostic renderers (PNG via Pillow; no matplotlib).

All previews are labelled SYNTHETIC/SIMULATED where applicable — these are
scientific diagnostics, never to be presented as observations (audit §15).
LUTs: hypsometric ramp for elevation, blue->red ramp for rainfall/depth,
diverging ramp for differences. Deterministic: same array -> same bytes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw

_LUT_ELEV = np.array(
    [[20, 70, 30], [60, 110, 40], [120, 160, 60], [190, 200, 110],
     [220, 210, 150], [235, 235, 235], [200, 200, 210]],
    dtype=np.float64,
)
_LUT_RAIN = np.array(
    [[245, 248, 255], [180, 215, 250], [80, 160, 240], [30, 90, 200],
     [120, 60, 200], [200, 40, 120], [220, 20, 30]],
    dtype=np.float64,
)
_LUT_DIFF = np.array(
    [[30, 60, 180], [90, 140, 220], [200, 220, 240], [245, 245, 245],
     [250, 210, 180], [235, 120, 90], [200, 30, 20]],
    dtype=np.float64,
)


def render_png(
    array: np.ndarray,
    path: Path,
    lut: np.ndarray = _LUT_ELEV,
    vmin: Optional[float] = None,
    vmax: Optional[float] = None,
    label: str = "SYNTHETIC / SIMULATED - NOT REAL DATA",
    symmetric: bool = False,
) -> Path:
    """Colour-ramp PNG with a provenance banner."""
    norm = array.astype(np.float64)
    if symmetric:
        bound = float(np.max(np.abs(norm))) if np.any(np.isfinite(norm)) else 0.0
        if bound <= 0:
            bound = 1.0
        lo, hi = -bound, bound
    else:
        lo = vmin if vmin is not None else float(np.nanmin(norm))
        hi = vmax if vmax is not None else float(np.nanmax(norm))
        if hi <= lo:
            hi = lo + 1.0
    norm = np.clip((norm - lo) / (hi - lo), 0.0, 1.0)
    idx = (norm * (len(lut) - 1)).astype(np.int32)
    rgb = lut[idx].astype(np.uint8)
    img = Image.fromarray(rgb, mode="RGB")
    banner = 16
    canvas = Image.new("RGB", (img.width, img.height + banner), (10, 10, 10))
    canvas.paste(img, (0, banner))
    draw = ImageDraw.Draw(canvas)
    draw.text((4, 2), label, fill=(235, 235, 235))
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path)
    return path


# Convenience wrappers used by diagnostics and the M1 bundle builder.
def render_dem(array: np.ndarray, path: Path, label: str = "SYNTHETIC DSM FIXTURE - NOT REAL TERRAIN") -> Path:
    return render_png(array, path, lut=_LUT_ELEV, label=label)


def render_rain(array: np.ndarray, path: Path, vmax: Optional[float] = None,
                label: str = "SIMULATED RAINFALL (PROVISIONAL) - NOT OBSERVED") -> Path:
    return render_png(array, path, lut=_LUT_RAIN, vmin=0.0, vmax=vmax, label=label)


def render_depth(array: np.ndarray, path: Path, vmax: Optional[float] = None,
                 label: str = "MODEL PREDICTION (SYNTHETIC FIXTURE) - SIMULATED") -> Path:
    return render_png(array, path, lut=_LUT_RAIN, vmin=0.0, vmax=vmax, label=label)


def render_difference(array: np.ndarray, path: Path,
                      label: str = "MODEL DIFFERENCE (SYNTHETIC FIXTURE) - SIMULATED") -> Path:
    return render_png(array, path, lut=_LUT_DIFF, symmetric=True, label=label)
