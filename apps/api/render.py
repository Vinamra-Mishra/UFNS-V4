"""M6 on-demand PNG rendering of precomputed flood-depth / flood-extent GeoTIFFs.

Renders the single-band float32 depth GeoTIFFs (units: m) produced by the M4/M5
engine into labelled, colour-ramped PNGs for the dashboard. Reads only the
precomputed artifacts — never re-runs the simulation. Colour ramps match the
existing diagnostic renderers (``services/ingestion/visual.py``).

Every returned image carries a visible provenance banner (SYNTHETIC / SIMULATED /
PROVISIONAL / NOT FOR OPERATIONAL USE) so the synthetic nature of the data is
never hidden in the UI.
"""

from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw

# Blue -> red depth ramp (matches services/ingestion/visual.py _LUT_RAIN).
_LUT_RAIN = np.array(
    [[245, 248, 255], [180, 215, 250], [80, 160, 240], [30, 90, 200],
     [120, 60, 200], [200, 40, 120], [220, 20, 30]],
    dtype=np.float64,
)
# Extent mask ramp: dry (light grey) / flooded (dark blue).
_LUT_EXTENT = np.array(
    [[235, 235, 232], [15, 70, 150]],
    dtype=np.float64,
)


@lru_cache(maxsize=512)
def read_depth_tif(tif_path: str) -> np.ndarray:
    """Read a single-band float32 depth GeoTIFF (m). Cached in memory."""
    import rasterio

    with rasterio.open(tif_path) as src:
        arr = src.read(1)
    return arr.astype(np.float64)


def _render_png(array: np.ndarray, lut: np.ndarray, vmin: float, vmax: float,
                label: str) -> bytes:
    """Colour-ramp an array and return labelled PNG bytes."""
    norm = np.clip((array - vmin) / max(vmax - vmin, 1e-12), 0.0, 1.0)
    idx = (norm * (len(lut) - 1)).astype(np.int32)
    rgb = lut[idx].astype(np.uint8)
    img = Image.fromarray(rgb, mode="RGB")
    banner = 16
    canvas = Image.new("RGB", (img.width, img.height + banner), (10, 10, 10))
    canvas.paste(img, (0, banner))
    ImageDraw.Draw(canvas).text((4, 2), label, fill=(235, 235, 235))
    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()


def render_depth_png(tif_path: Path, vmax: float, label: str) -> bytes:
    """Render a flood-depth map (m) as PNG bytes."""
    arr = read_depth_tif(str(tif_path))
    vmax = max(vmax, 0.05)
    return _render_png(arr, _LUT_RAIN, vmin=0.0, vmax=vmax, label=label)


def render_extent_png(tif_path: Path, threshold_m: float, label: str) -> bytes:
    """Render a flood-extent map (depth > threshold) as PNG bytes."""
    arr = read_depth_tif(str(tif_path))
    mask = (arr > threshold_m).astype(np.float64)
    return _render_png(mask, _LUT_EXTENT, vmin=0.0, vmax=1.0, label=label)
